"""查询 API：SSE 流式问答 + 对话持久化。

流程：无 conversation_id 则创建新对话（首条 query 前 30 字为标题）→
SSE 推流（conversation 事件 → token 事件 → refs 事件 → DONE）→ 流结束后落库。
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.db import get_session
from app.core.models import Conversation, Message
from app.core.security import require_query_key
from app.generation.generator import answer_stream
from app.llm.client import describe_llm_error

router = APIRouter(prefix="/api/query", tags=["query"])


class QueryRequest(BaseModel):
    query: str
    conversation_id: str | None = None


@router.post("")
async def query(
    req: QueryRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_query_key),
) -> EventSourceResponse:
    # 对话准备：复用或新建
    if req.conversation_id:
        conv = await session.get(Conversation, req.conversation_id)
    else:
        conv = None
    if conv is None:
        conv = Conversation(title=req.query.strip()[:30] or "新对话")
        session.add(conv)
        await session.flush()
    conv.updated_at = datetime.utcnow()
    conv_id = conv.id

    # 追问上下文：取该对话最近 6 条消息（3 轮）
    from sqlalchemy import select

    recent = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(6)
        )
    ).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in reversed(recent)]

    collected: list[str] = []
    refs: list = []

    async def events():
        yield {"data": json.dumps({"type": "conversation", "id": conv_id}, ensure_ascii=False)}
        try:
            async for raw in answer_stream(session, req.query, history):
                data = raw.split("data: ", 1)[1].rstrip("\n")
                yield {"data": data}
                # 收集内容用于落库
                if data == "[DONE]":
                    continue
                try:
                    parsed = json.loads(data)
                    if parsed.get("type") == "token":
                        collected.append(parsed["content"])
                    elif parsed.get("type") == "refs":
                        refs.extend(parsed["refs"])
                except json.JSONDecodeError:
                    pass
        except Exception as e:  # 出错时下发 error 事件，避免 SSE 流无声中断让前端报 network error
            yield {
                "data": json.dumps(
                    {"type": "error", "content": describe_llm_error(e)}, ensure_ascii=False
                )
            }
            return

        # 流结束：落库一问一答
        session.add(Message(conversation_id=conv_id, role="user", content=req.query))
        session.add(
            Message(
                conversation_id=conv_id,
                role="assistant",
                content="".join(collected),
                refs=refs,
            )
        )
        await session.commit()

    return EventSourceResponse(events())
