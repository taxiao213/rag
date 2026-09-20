"""混合检索：向量 + BM25 双路召回 → RRF 融合 → 云端 Rerank。"""

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.models import Chunk, Document
from app.indexing import bm25_store, vector_store
from app.llm.embeddings import embed_texts
from app.llm.reranker import rerank

log = structlog.get_logger()

RRF_K = 60  # RRF 常数，业界默认


def rrf_fuse(rankings: list[list[dict]], top_n: int) -> list[str]:
    """Reciprocal Rank Fusion：输入多路排名结果（每路按序的 chunk 列表），返回融合后 chunk_id 列表。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            cid = item["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
    return [cid for cid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]]


async def hybrid_search(
    session: AsyncSession, query: str, *, modality: str | None = None, top_n: int | None = None
) -> list[dict]:
    """混合检索主入口。返回带引用元数据的 chunk 列表（按 rerank 分数降序）。"""
    settings = get_settings()
    top_n = top_n or settings.rerank_top_k

    # 1. 双路召回
    vector = (await embed_texts([query]))[0]
    vec_hits = await vector_store.search(vector, settings.retrieve_vector_top_k, modality=modality)
    bm25_hits = await bm25_store.search(session, query, settings.retrieve_bm25_top_k)

    # 2. RRF 融合
    fused_ids = rrf_fuse([vec_hits, bm25_hits], top_n=settings.rerank_top_k * 4)
    if not fused_ids:
        return []

    # 3. 回表取 chunk 内容（PG 是真相源）
    rows = (
        await session.execute(
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.id.in_(fused_ids), Document.deleted_at.is_(None))
        )
    ).all()
    by_id = {chunk.id: (chunk, doc) for chunk, doc in rows}
    ordered = [by_id[cid] for cid in fused_ids if cid in by_id]
    if not ordered:
        return []

    # 4. Rerank
    ranked = await rerank(query, [c.content for c, _ in ordered], top_n)
    return [_to_result(ordered[idx][0], ordered[idx][1], score) for idx, score in ranked]


def _to_result(chunk: Chunk, doc: Document, score: float) -> dict:
    return {
        "chunk_id": chunk.id,
        "content": chunk.content,
        "score": score,
        "modality": chunk.modality.value,
        "document_id": doc.id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "page_no": chunk.page_no,
        "slide_no": chunk.slide_no,
        "start_ts": chunk.start_ts,
        "end_ts": chunk.end_ts,
        "asset_id": chunk.asset_id,
    }
