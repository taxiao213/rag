"""运行时 LLM 配置 API：读取（掩码）/ 保存（加密+缓存失效）/ 测试连接。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.models import Setting
from app.core.security import encrypt_secret, mask_secret, require_admin_key, require_query_key
from app.llm import client as llm_client
from app.llm.client import SETTINGS_KEY, load_config, test_connection

router = APIRouter(prefix="/api/settings", tags=["settings"])


class LLMSettingsIn(BaseModel):
    base_url: str
    api_key: str | None = None  # None = 保持原值不变
    llm_model: str
    embedding_model: str | None = None
    rerank_model: str | None = None
    vlm_model: str | None = None
    max_tokens: int = 2048


@router.get("/llm")
async def get_llm_settings(
    _: str = Depends(require_query_key),
) -> dict:
    config = await load_config()
    return {
        "base_url": config.base_url,
        "api_key_masked": mask_secret(config.api_key) if config.api_key else "",
        "api_key_configured": bool(config.api_key),
        "llm_model": config.llm_model,
        "embedding_model": config.embedding_model,
        "rerank_model": config.rerank_model,
        "vlm_model": config.vlm_model,
        "max_tokens": config.max_tokens,
    }


@router.put("/llm")
async def save_llm_settings(
    body: LLMSettingsIn,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin_key),
) -> dict:
    value: dict = body.model_dump(exclude={"api_key"}, exclude_none=True)

    if body.api_key:
        value["api_key_encrypted"] = encrypt_secret(body.api_key)
    else:
        # 保留原有加密 key
        row = await session.scalar(select(Setting).where(Setting.key == SETTINGS_KEY))
        if row and row.value.get("api_key_encrypted"):
            value["api_key_encrypted"] = row.value["api_key_encrypted"]

    row = await session.scalar(select(Setting).where(Setting.key == SETTINGS_KEY))
    if row:
        row.value = value
    else:
        session.add(Setting(key=SETTINGS_KEY, value=value))

    llm_client.invalidate_cache()
    return {"status": "saved"}


@router.post("/llm/test")
async def test_llm_settings(
    body: LLMSettingsIn,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin_key),
) -> dict:
    api_key = body.api_key
    if not api_key:
        # 用已保存的 key 测试
        row = await session.scalar(select(Setting).where(Setting.key == SETTINGS_KEY))
        from app.core.security import decrypt_secret

        if row and row.value.get("api_key_encrypted"):
            api_key = decrypt_secret(row.value["api_key_encrypted"])
    if not api_key:
        return {"ok": False, "message": "未提供 API Key，且没有已保存的 Key"}

    ok, message = await test_connection(body.base_url, api_key, body.llm_model)
    return {"ok": ok, "message": message}
