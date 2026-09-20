"""任务状态 API：查询索引任务进度与失败详情。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.models import IndexTask
from app.core.security import require_query_key

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_query_key),
) -> dict:
    task = await session.get(IndexTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return {
        "task_id": task.id,
        "document_id": task.document_id,
        "task_type": task.task_type.value,
        "status": task.status.value,
        "retry_count": task.retry_count,
        "error": task.error,
        "triggered_by": task.triggered_by.value,
        "created_at": task.created_at.isoformat(),
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


@router.get("")
async def list_tasks(
    status: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_query_key),
) -> list[dict]:
    q = select(IndexTask).order_by(IndexTask.created_at.desc()).limit(limit)
    if status:
        q = q.where(IndexTask.status == status)
    tasks = (await session.execute(q)).scalars()
    return [
        {
            "task_id": t.id,
            "document_id": t.document_id,
            "task_type": t.task_type.value,
            "status": t.status.value,
            "retry_count": t.retry_count,
            "triggered_by": t.triggered_by.value,
            "created_at": t.created_at.isoformat(),
        }
        for t in tasks
    ]
