"""生成层：检索 → 上下文组装 → LLM SSE 流式生成 → 流末下发引用元数据。"""

import json
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.context_builder import build_context
from app.generation.prompts import build_messages
from app.llm.client import get_chat_client
from app.retrieval.hybrid_search import hybrid_search


async def answer_stream(
    session: AsyncSession, query: str
) -> AsyncIterator[str]:
    """SSE 事件流：先逐 token 推内容（data: {"type":"token","content":...}），
    最后推引用元数据（data: {"type":"refs","refs":[...]}），以 [DONE] 结束。
    """
    results = await hybrid_search(session, query)
    context, refs = build_context(results)

    client = await get_chat_client()
    messages = build_messages(query, context)

    async def sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    async for token in client.chat_stream(messages):
        yield await sse({"type": "token", "content": token})

    yield await sse({"type": "refs", "refs": refs})
    yield "data: [DONE]\n\n"
