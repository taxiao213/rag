"""运行时 LLM 配置 API：生成与索引两组独立配置，读取（掩码）/ 保存（加密+缓存失效）/ 测试连接。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.models import Setting
from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    mask_secret,
    require_admin_key,
    require_query_key,
)
from app.llm import client as llm_client
from app.llm.client import (
    SETTINGS_KEY_CHAT,
    SETTINGS_KEY_INDEX,
    load_chat_config,
    load_index_config,
    test_connection,
    test_embedding,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ChatSettingsIn(BaseModel):
    base_url: str
    api_key: str | None = None  # None = 保持原值不变
    llm_model: str
    max_tokens: int = 2048


class IndexSettingsIn(BaseModel):
    base_url: str
    api_key: str | None = None
    embedding_model: str
    rerank_model: str | None = None
    vlm_model: str | None = None


async def _masked_response() -> dict:
    chat = await load_chat_config()
    index = await load_index_config()
    return {
        "chat": {
            "base_url": chat.base_url,
            "api_key_masked": mask_secret(chat.api_key) if chat.api_key else "",
            "api_key_configured": bool(chat.api_key),
            "llm_model": chat.llm_model,
            "max_tokens": chat.max_tokens,
        },
        "index": {
            "base_url": index.base_url,
            "api_key_masked": mask_secret(index.api_key) if index.api_key else "",
            "api_key_configured": bool(index.api_key),
            "embedding_model": index.embedding_model,
            "rerank_model": index.rerank_model,
            "vlm_model": index.vlm_model,
        },
    }


@router.get("/llm")
async def get_llm_settings(_: str = Depends(require_query_key)) -> dict:
    return await _masked_response()


async def _save_group(
    session: AsyncSession, key: str, value: dict, api_key: str | None
) -> None:
    if api_key:
        value["api_key_encrypted"] = encrypt_secret(api_key)
    else:
        row = await session.scalar(select(Setting).where(Setting.key == key))
        if row and row.value.get("api_key_encrypted"):
            value["api_key_encrypted"] = row.value["api_key_encrypted"]

    row = await session.scalar(select(Setting).where(Setting.key == key))
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


@router.put("/llm")
async def save_llm_settings(
    body: dict,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin_key),
) -> dict:
    """保存一组或两组配置：{"chat": {...}} / {"index": {...}} / 两者。"""
    if chat := body.get("chat"):
        data = ChatSettingsIn(**chat)
        await _save_group(
            session,
            SETTINGS_KEY_CHAT,
            data.model_dump(exclude={"api_key"}),
            data.api_key,
        )
    if index := body.get("index"):
        data = IndexSettingsIn(**index)
        await _save_group(
            session,
            SETTINGS_KEY_INDEX,
            data.model_dump(exclude={"api_key"}),
            data.api_key,
        )
    await llm_client.reset_clients()
    return {"status": "saved"}


@router.post("/llm/test")
async def test_llm_settings(
    body: dict,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin_key),
) -> dict:
    """测试连接：{"group": "chat"|"index", ...配置}。index 组测 embedding 接口。"""
    group = body.get("group", "chat")

    async def resolve_key(settings_key: str, provided: str | None) -> str:
        if provided:
            return provided
        row = await session.scalar(select(Setting).where(Setting.key == settings_key))
        if row and row.value.get("api_key_encrypted"):
            return decrypt_secret(row.value["api_key_encrypted"])
        return ""

    if group == "chat":
        data = ChatSettingsIn(**{k: v for k, v in body.items() if k != "group"})
        api_key = await resolve_key(SETTINGS_KEY_CHAT, data.api_key)
        if not api_key:
            return {"ok": False, "message": "未提供 API Key，且没有已保存的 Key"}
        ok, message = await test_connection(data.base_url, api_key, data.llm_model)
        return {"ok": ok, "message": message}

    data = IndexSettingsIn(**{k: v for k, v in body.items() if k != "group"})
    api_key = await resolve_key(SETTINGS_KEY_INDEX, data.api_key)
    if not api_key:
        # index 组可能复用 chat 组的 key
        api_key = await resolve_key(SETTINGS_KEY_CHAT, None)
    if not api_key:
        return {"ok": False, "message": "未提供 API Key，且没有已保存的 Key"}
    ok, message = await test_embedding(data.base_url, api_key, data.embedding_model)
    return {"ok": ok, "message": message}
