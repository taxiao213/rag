"""arq worker：索引任务执行 + APScheduler 定时兜底扫描 pending/failed 任务。

启动方式：
  uv run arq app.workers.worker.WorkerSettings

定时器跑在 worker 进程内（协程方式），周期性扫描：
- pending 任务（普通文件上传的定时批量）
- failed 且 retry_count < max_retries 的任务（失败兜底重试）
"""

import structlog
from arq import cron
from sqlalchemy import or_, select

from app.core.db import get_session_factory
from app.core.models import IndexTask, TaskStatus
from app.indexing.pipeline import run_index_task
from app.workers.queue import _redis_settings

log = structlog.get_logger()

# 定时扫描间隔（秒）
SCAN_INTERVAL = 300  # 5 分钟


async def process_index_task(ctx: dict, task_id: str) -> None:
    """arq job：执行单个索引任务。"""
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(IndexTask, task_id)
        if task is None:
            log.warning("任务不存在", task=task_id)
            return
        try:
            await run_index_task(session, task)
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def scan_pending_tasks(ctx: dict) -> None:
    """定时 job：扫描 pending / 可重试 failed 任务并直接执行（定时批量 + 兜底）。"""
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(IndexTask)
                .where(
                    or_(
                        IndexTask.status == TaskStatus.pending,
                        (IndexTask.status == TaskStatus.failed)
                        & (IndexTask.retry_count < IndexTask.max_retries),
                    )
                )
                .order_by(IndexTask.created_at)
                .limit(20)
            )
        ).scalars().all()

        if not rows:
            return
        log.info("定时扫描发现待处理任务", count=len(rows))
        for task in rows:
            try:
                await run_index_task(session, task)
            except Exception as e:
                log.error("定时任务执行失败", task=task.id, err=str(e))
        await session.commit()


class WorkerSettings:
    functions = [process_index_task]
    cron_jobs = [cron(scan_pending_tasks, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55})]
    redis_settings = _redis_settings()
