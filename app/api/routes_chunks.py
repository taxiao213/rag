"""引用溯源 API：查看 chunk 原文片段、资产图片、源文件下载链接。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.db import get_session
from app.core.models import Asset, Chunk, Document
from app.core.security import require_query_key

router = APIRouter(prefix="/api/chunks", tags=["chunks"])


@router.get("/{chunk_id}")
async def get_chunk(
    chunk_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_query_key),
) -> dict:
    chunk = await session.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(404, "引用片段不存在")
    doc = await session.get(Document, chunk.document_id)

    # 资产（图片/视频帧）：预签名直链
    asset = None
    if chunk.asset_id:
        a = await session.get(Asset, chunk.asset_id)
        if a:
            asset = {
                "asset_id": a.id,
                "asset_type": a.asset_type.value,
                "url": storage.presigned_get_url(a.storage_key),
                "width": a.width,
                "height": a.height,
                "timestamp": a.timestamp,
            }

    return {
        "chunk_id": chunk.id,
        "content": chunk.content,
        "modality": chunk.modality.value,
        "page_no": chunk.page_no,
        "slide_no": chunk.slide_no,
        "start_ts": chunk.start_ts,
        "end_ts": chunk.end_ts,
        "asset": asset,
        "document": {
            "document_id": doc.id if doc else None,
            "filename": doc.filename if doc else "",
            "file_type": doc.file_type if doc else "",
            # 源文件预签名下载/预览链接
            "file_url": storage.presigned_get_url(doc.storage_key) if doc else None,
        },
    }
