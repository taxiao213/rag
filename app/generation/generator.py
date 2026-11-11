"""生成层：检索（含降级）→ 上下文组装 → LLM SSE 流式生成 → 流末下发引用元数据。

降级策略（检索失败不阻断对话）：
- 混合检索（向量+BM25+rerank）失败 → 退纯本地 BM25 单路
- BM25 也失败 → 无引用直答（切换系统提示词，流开头注明本次未经知识库校验）
"""

import json
from typing import AsyncIterator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.context_builder import build_context
from app.generation.prompts import build_messages
from app.llm.client import get_chat_client
from app.retrieval.hybrid_search import bm25_search, hybrid_search

log = structlog.get_logger()

DEGRADED_NOTICE = "（⚠️ 知识库检索服务暂不可用，以下回答未经知识库校验）\n\n"


async def answer_stream(
    session: AsyncSession, query: str, history: list[dict] | None = None
) -> AsyncIterator[str]:
    """SSE 事件流：先逐 token 推内容（data: {"type":"token","content":...}），
    最后推引用元数据（data: {"type":"refs","refs":[...]}），以 [DONE] 结束。
    history: 该对话的最近若干轮消息（[{role, content}]），用于追问上下文。
    """
    grounded = True
    try:
        results = await hybrid_search(session, query)
    except Exception as e:
        log.warning("混合检索失败，尝试 BM25 降级", err=str(e))
        try:
            results = await bm25_search(session, query)
        except Exception as e2:
            log.warning("BM25 降级也失败，转为无引用直答", err=str(e2))
            results = []
            grounded = False

    context, refs = build_context(results)

    client = await get_chat_client()
    messages = build_messages(query, context, history, grounded=grounded)

    async def sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    if not grounded:
        yield await sse({"type": "token", "content": DEGRADED_NOTICE})
    async for token in client.chat_stream(messages):
        yield await sse({"type": "token", "content": token})

    yield await sse({"type": "refs", "refs": refs})
    yield "data: [DONE]\n\n"
