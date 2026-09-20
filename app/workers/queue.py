"""arq 任务投递：与 worker 共用 Redis 队列。"""

import arq
from arq.connections import RedisSettings, create_pool
from arq.connections import ArqRedis

from app.config import get_settings

_pool: ArqRedis | None = None


def _redis_settings() -> RedisSettings:
    url = get_settings().redis_url
    # arq 接受 "redis://host:port/db" 解析；简化：直接传 URL
    return RedisSettings.from_dsn(url)


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool


async def enqueue_index_task(task_id: str) -> None:
    pool = await get_pool()
    await pool.enqueue_job("process_index_task", task_id)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
