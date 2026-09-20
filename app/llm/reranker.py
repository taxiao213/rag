"""Rerank：通义 gte-rerank-v2（DashScope 原生接口，非 OpenAI 兼容路径）。"""

import httpx

from app.llm.client import load_index_config

DASHSCOPE_RERANK_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"


async def rerank(query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
    """返回 (原文档索引, 相关分) 列表，按分数降序，长度 top_n。"""
    config = await load_index_config()
    if "dashscope" in config.base_url:
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(
                DASHSCOPE_RERANK_URL,
                headers={"Authorization": f"Bearer {config.api_key}"},
                json={
                    "model": config.rerank_model,
                    "input": {"query": query, "documents": documents},
                    "parameters": {"return_documents": False, "top_n": top_n},
                },
            )
            resp.raise_for_status()
            results = resp.json()["output"]["results"]
            return [(r["index"], r["relevance_score"]) for r in results]

    # 非 DashScope（无 rerank 接口）：回退为按原序取 top_n
    return [(i, 1.0 - i * 0.01) for i in range(min(top_n, len(documents)))]
