"""文档管理 API：上传、列表、删除、重建索引。"""

import hashlib
import structlog
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.db import get_session
from app.core.models import (
    Document,
    DocumentStatus,
    IndexTask,
    Modality,
    TaskType,
    TriggeredBy,
)
from app.core.security import require_admin_key, require_query_key, validate_upload

log = structlog.get_logger()
router = APIRouter(prefix="/api/documents", tags=["documents"])

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
VIDEO_EXTS = {"mp4", "mov", "avi", "mkv"}


def _modality_of(ext: str) -> Modality:
    if ext in IMAGE_EXTS:
        return Modality.image
    if ext in VIDEO_EXTS:
        return Modality.video
    return Modality.text


@router.post("")
async def upload(
    file: UploadFile,
    importance: str = "normal",
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin_key),
) -> dict:
    data = await file.read()
    ext = validate_upload(file.filename or "", len(data))

    file_hash = hashlib.sha256(data).hexdigest()
    # 同 hash 的未删除文档 → 去重直接返回
    existing = await session.scalar(
        select(Document).where(Document.file_hash == file_hash, Document.deleted_at.is_(None))
    )
    if existing:
        return {"document_id": existing.id, "deduplicated": True, "status": existing.status}

    doc_id = str(uuid.uuid4())
    storage_key = f"docs/{doc_id}.{ext}"
    await storage.put_object(storage_key, data, file.content_type or "application/octet-stream")

    is_high = importance == "high"
    doc = Document(
        id=doc_id,
        filename=file.filename or "unnamed",
        file_type=ext,
        modality=_modality_of(ext),
        storage_key=storage_key,
        file_hash=file_hash,
        size_bytes=len(data),
        importance=importance,
        status=DocumentStatus.indexing if is_high else DocumentStatus.pending,
    )
    session.add(doc)
    task = IndexTask(
        document_id=doc_id,
        task_type=TaskType.index,
        triggered_by=TriggeredBy.event if is_high else TriggeredBy.scheduler,
    )
    session.add(task)
    await session.flush()

    if is_high:
        # 事件驱动：通知 arq worker 立即执行
        from app.workers.queue import enqueue_index_task

        await enqueue_index_task(task.id)

    return {"document_id": doc_id, "deduplicated": False, "status": doc.status.value}


@router.get("")
async def list_documents(
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_query_key),
) -> list[dict]:
    q = select(Document).where(Document.deleted_at.is_(None)).order_by(Document.created_at.desc())
    if status:
        q = q.where(Document.status == status)
    docs = (await session.execute(q)).scalars()
    return [
        {
            "document_id": d.id,
            "filename": d.filename,
            "file_type": d.file_type,
            "modality": d.modality.value,
            "status": d.status.value,
            "importance": d.importance,
            "size_bytes": d.size_bytes,
            "version": d.version,
            "created_at": d.created_at.isoformat(),
        }
        for d in docs
    ]


@router.post("/{document_id}/reindex")
async def reindex(
    document_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin_key),
) -> dict:
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(404, "文档不存在")
    task = IndexTask(
        document_id=document_id, task_type=TaskType.reindex, triggered_by=TriggeredBy.manual
    )
    session.add(task)
    doc.status = DocumentStatus.indexing
    await session.flush()
    from app.workers.queue import enqueue_index_task

    await enqueue_index_task(task.id)
    return {"task_id": task.id, "status": "queued"}


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin_key),
) -> dict:
    doc = await session.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(404, "文档不存在")
    task = IndexTask(
        document_id=document_id, task_type=TaskType.delete, triggered_by=TriggeredBy.manual
    )
    session.add(task)
    await session.flush()
    from app.workers.queue import enqueue_index_task

    await enqueue_index_task(task.id)
    return {"task_id": task.id, "status": "queued"}
