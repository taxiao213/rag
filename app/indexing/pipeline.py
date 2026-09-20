"""索引主流程：解析 → 切片 → 资产处理 → embedding → 双库写入。

一致性原则（文档级重建）：
1. 先完整索引新版本（新 chunk 入库 + 向量写入）
2. 再删旧版本（旧 chunk 行 + 旧向量）
3. 切 document.version / status
绝不做先删后插，避免窗口期查不到。
"""

import hashlib
import structlog
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking.chunker import chunk_blocks
from app.core import storage
from app.core.models import (
    Asset,
    AssetType,
    Chunk,
    ChunkModality,
    Document,
    DocumentStatus,
    IndexTask,
    TaskStatus,
)
from app.indexing import bm25_store, vector_store
from app.llm.embeddings import embed_texts
from app.llm.vlm import describe_image
from app.parsers import ParseInput, parse

log = structlog.get_logger()


async def run_index_task(session: AsyncSession, task: IndexTask) -> None:
    """执行单个索引任务（index / reindex / delete）。"""
    task.status = TaskStatus.running
    task.started_at = datetime.utcnow()
    await session.flush()

    doc = await session.get(Document, task.document_id)
    if doc is None:
        task.status = TaskStatus.failed
        task.error = "document 不存在"
        task.finished_at = datetime.utcnow()
        return

    try:
        if task.task_type.value == "delete":
            await _delete_document(session, doc)
        else:
            await _index_document(session, doc)
        task.status = TaskStatus.success
    except Exception as e:
        task.retry_count += 1
        task.status = TaskStatus.failed
        task.error = str(e)[:1000]
        doc.status = DocumentStatus.failed
        log.error("index task 失败", task=task.id, err=str(e))
    task.finished_at = datetime.utcnow()


async def _index_document(session: AsyncSession, doc: Document) -> None:
    doc.status = DocumentStatus.indexing
    await session.flush()

    # 1. 解析
    data = await storage.get_object(doc.storage_key)
    parsed = parse(ParseInput(data=data, filename=doc.filename, file_type=doc.file_type))
    doc.needs_ocr = parsed.needs_ocr

    # 2. 切片
    chunk_records = chunk_blocks(parsed.blocks)
    if not chunk_records:
        raise ValueError("解析结果为空，无可索引内容")

    # 3. 资产处理：IMAGE_REF/FRAME_REF 存 MinIO + VLM 描述
    new_chunks: list[Chunk] = []
    for idx, rec in enumerate(chunk_records):
        asset_id = None
        if rec.asset_bytes is not None:
            asset = Asset(
                document_id=doc.id,
                asset_type=AssetType.image,
                storage_key=f"assets/{doc.id}/{idx}.{rec.asset_ext or 'png'}",
                width=None,
                height=None,
            )
            session.add(asset)
            await session.flush()
            asset_id = asset.id
            await storage.put_object(
                asset.storage_key, rec.asset_bytes, f"image/{rec.asset_ext or 'png'}"
            )
            # VLM 描述（失败不阻塞，描述为空则 chunk 用占位文本）
            try:
                desc = await describe_image(rec.asset_bytes, rec.asset_ext or "png")
                asset.vlm_description = desc
                rec.content = desc
            except Exception as e:
                log.warning("VLM 描述失败", asset=asset.id, err=str(e))

        new_chunks.append(
            Chunk(
                document_id=doc.id,
                chunk_index=idx,
                content=rec.content,
                modality=ChunkModality(rec.modality),
                token_count=max(1, len(rec.content) // 2),
                content_hash=hashlib.sha256(rec.content.encode()).hexdigest(),
                page_no=rec.page_no,
                slide_no=rec.slide_no,
                start_ts=rec.start_ts,
                end_ts=rec.end_ts,
                asset_id=asset_id,
            )
        )

    # 4. embedding + 双库写入（新版本先就绪）
    texts = [c.content for c in new_chunks]
    vectors = await embed_texts(texts)
    session.add_all(new_chunks)
    await session.flush()

    await vector_store.upsert_chunks(
        [
            {
                "chunk_id": c.id,
                "document_id": doc.id,
                "vector": v,
                "modality": c.modality.value,
                "version": doc.version,
            }
            for c, v in zip(new_chunks, vectors, strict=True)
        ]
    )
    for c in new_chunks:
        c.qdrant_point_id = c.id
        c.indexed_at = datetime.utcnow()
    await bm25_store.update_search_vectors(session, [c.id for c in new_chunks])

    # 5. 清理旧版本 chunk（含旧向量）
    old_chunk_ids = [
        row[0]
        for row in await session.execute(
            select(Chunk.id).where(
                Chunk.document_id == doc.id,
                Chunk.id.not_in([c.id for c in new_chunks]),
            )
        )
    ]
    if old_chunk_ids:
        await session.execute(delete(Chunk).where(Chunk.id.in_(old_chunk_ids)))
        # Qdrant 按 document_id 删旧向量：新向量已 upsert（point id 不同），
        # 精确做法是先删全部再 upsert 新的——但 point id 唯一不冲突，
        # 旧向量（旧 chunk_id）单独按 id 集合删除
        await _delete_vectors_by_ids(old_chunk_ids)

    # 6. 切状态
    doc.version += 1
    doc.status = DocumentStatus.indexed
    doc.error = None
    log.info("文档索引完成", doc=doc.id, chunks=len(new_chunks))


async def _delete_vectors_by_ids(point_ids: list[str]) -> None:
    from qdrant_client import models as qm

    from app.indexing.vector_store import ensure_collection, get_qdrant

    client = get_qdrant()
    await ensure_collection()
    from app.config import get_settings

    await client.delete(
        collection_name=get_settings().qdrant_collection,
        points_selector=qm.PointIdsList(points=point_ids),
    )


async def _delete_document(session: AsyncSession, doc: Document) -> None:
    """删除：向量 + chunk + 资产文件 + 文档存储副本 + 软删标记。
    注意：只删系统内部副本（MinIO docs/ 与 assets/），不触碰 source_path 原始文件。"""
    await vector_store.delete_by_document(doc.id)

    assets = (await session.execute(select(Asset).where(Asset.document_id == doc.id))).scalars()
    for asset in assets:
        try:
            storage.remove_object(asset.storage_key)
        except Exception as e:
            log.warning("资产文件删除失败", key=asset.storage_key, err=str(e))
    try:
        storage.remove_object(doc.storage_key)
    except Exception as e:
        log.warning("文档存储副本删除失败", key=doc.storage_key, err=str(e))

    await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    await session.execute(delete(Asset).where(Asset.document_id == doc.id))
    doc.deleted_at = datetime.utcnow()
    log.info("文档已删除", doc=doc.id)
