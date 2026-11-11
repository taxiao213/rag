"""Embedding 批量调用：并发信号量控制 + 指数退避重试（云 API 限流保护）。"""

import asyncio

import structlog

from app.llm.client import get_index_client, load_index_config

log = structlog.get_logger()

BATCH_SIZE = 25  # 通义 text-embedding-v3 单批上限 25


async def embed_texts(texts: list[str], *, concurrency: int = 3) -> list[list[float]]:
    """分批并发 embedding，保持与输入顺序一致。"""
    client = await get_index_client()
    config = await load_index_config()
    model = config.embedding_model
    sem = asyncio.Semaphore(concurrency)

    async def embed_batch(idx: int, batch: list[str]) -> tuple[int, list[list[float]]]:
        async with sem:
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    return idx, await client.embed(batch, model)
                except Exception as e:
                    last_err = e
                    wait = 2**attempt
                    log.warning("embedding 重试", batch_idx=idx, attempt=attempt, err=str(e))
                    await asyncio.sleep(wait)
            raise RuntimeError(f"embedding 批次 {idx} 重试 3 次仍失败") from last_err

    batches = [texts[i : i + BATCH_SIZE] for i in range(0, len(texts), BATCH_SIZE)]
    results = await asyncio.gather(*[embed_batch(i, b) for i, b in enumerate(batches)])
    vectors: list[list[float]] = []
    for _, vecs in sorted(results, key=lambda x: x[0]):
        vectors.extend(vecs)
    return vectors
