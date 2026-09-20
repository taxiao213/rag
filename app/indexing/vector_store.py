"""Qdrant 向量库封装：collection 初始化、upsert、按 document_id 删除、向量检索。"""

from functools import lru_cache

from qdrant_client import AsyncQdrantClient, models as qm

from app.config import get_settings


@lru_cache
def get_qdrant() -> AsyncQdrantClient:
    return AsyncQdrantClient(url=get_settings().qdrant_url)


async def ensure_collection() -> None:
    client = get_qdrant()
    settings = get_settings()
    existing = await client.get_collections()
    names = {c.name for c in existing.collections}
    if settings.qdrant_collection not in names:
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=qm.VectorParams(
                size=settings.embedding_dim, distance=qm.Distance.COSINE
            ),
        )
        # payload 索引：检索过滤 + 按文档删除
        await client.create_payload_index(
            settings.qdrant_collection, "document_id", qm.PayloadSchemaType.KEYWORD
        )
        await client.create_payload_index(
            settings.qdrant_collection, "modality", qm.PayloadSchemaType.KEYWORD
        )
        await client.create_payload_index(
            settings.qdrant_collection, "acl", qm.PayloadSchemaType.KEYWORD
        )


async def upsert_chunks(points: list[dict]) -> None:
    """points: [{chunk_id, document_id, vector, modality, version}]，point id 用 chunk_id。"""
    client = get_qdrant()
    await ensure_collection()
    await client.upsert(
        collection_name=get_settings().qdrant_collection,
        points=[
            qm.PointStruct(
                id=p["chunk_id"],
                vector=p["vector"],
                payload={
                    "document_id": p["document_id"],
                    "modality": p["modality"],
                    "version": p.get("version", 1),
                    "acl": p.get("acl", "public"),
                },
            )
            for p in points
        ],
    )


async def search(vector: list[float], top_k: int, *, modality: str | None = None) -> list[dict]:
    """返回 [{chunk_id, score, document_id, modality}]。"""
    client = get_qdrant()
    await ensure_collection()
    query_filter = None
    if modality:
        query_filter = qm.Filter(
            must=[qm.FieldCondition(key="modality", match=qm.MatchValue(value=modality))]
        )
    result = await client.query_points(
        collection_name=get_settings().qdrant_collection,
        query=vector,
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
    )
    return [
        {
            "chunk_id": str(p.id),
            "score": p.score,
            "document_id": p.payload.get("document_id"),
            "modality": p.payload.get("modality"),
        }
        for p in result.points
    ]


async def delete_by_document(document_id: str) -> None:
    client = get_qdrant()
    await ensure_collection()
    await client.delete(
        collection_name=get_settings().qdrant_collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(
                must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))]
            )
        ),
    )
