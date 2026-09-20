"""对话记录 API：列表、详情（含消息）、删除。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.models import Conversation, Message
from app.core.security import require_query_key

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_query_key),
) -> list[dict]:
    rows = (
        await session.execute(
            select(Conversation).order_by(Conversation.updated_at.desc()).limit(100)
        )
    ).scalars().all()
    return [
        {"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()} for c in rows
    ]


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_query_key),
) -> dict:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "对话不存在")
    messages = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
    ).scalars().all()
    return {
        "id": conv.id,
        "title": conv.title,
        "messages": [
            {"role": m.role, "content": m.content, "refs": m.refs or []} for m in messages
        ],
    }


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_query_key),
) -> dict:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "对话不存在")
    await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
    await session.delete(conv)
    return {"status": "deleted"}
