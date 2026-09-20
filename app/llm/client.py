"""云端 LLM 统一客户端：OpenAI 兼容协议，一处封装可切换供应商。

配置优先级：settings 表（网页配置） > .env 兜底。配置带缓存，settings 更新时失效。
"""

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.core.db import get_session_factory
from app.core.models import Setting
from app.core.security import decrypt_secret

SETTINGS_KEY = "llm_config"


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    llm_model: str
    embedding_model: str
    rerank_model: str
    vlm_model: str
    temperature: float | None = None  # None = 不下发，用服务商默认（部分模型仅允许默认值）
    max_tokens: int = 2048


_cache: LLMConfig | None = None


def invalidate_cache() -> None:
    global _cache
    _cache = None


async def load_config() -> LLMConfig:
    """读 settings 表（解密），缺失字段回落到 .env。"""
    global _cache
    if _cache is not None:
        return _cache

    env = get_settings()
    base = {
        "base_url": env.llm_base_url,
        "api_key": env.llm_api_key,
        "llm_model": env.llm_model,
        "embedding_model": env.embedding_model,
        "rerank_model": env.rerank_model,
        "vlm_model": env.vlm_model,
        "max_tokens": 2048,
    }

    factory = get_session_factory()
    async with factory() as session:
        row = await session.scalar(select(Setting).where(Setting.key == SETTINGS_KEY))
        if row:
            value = dict(row.value)
            if value.get("api_key_encrypted"):
                value["api_key"] = decrypt_secret(value.pop("api_key_encrypted"))
            base.update({k: v for k, v in value.items() if v not in (None, "")})

    _cache = LLMConfig(**{k: v for k, v in base.items() if k in LLMConfig.__dataclass_fields__})
    return _cache


class LLMClient:
    """OpenAI 兼容协议客户端：chat（含流式）、embedding、vlm 描述。"""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def chat(self, messages: list[dict], *, model: str | None = None,
                   temperature: float | None = None, max_tokens: int | None = None) -> dict:
        payload: dict = {
            "model": model or self._config.llm_model,
            "messages": messages,
            "max_tokens": max_tokens or self._config.max_tokens,
        }
        temp = temperature if temperature is not None else self._config.temperature
        if temp is not None:
            payload["temperature"] = temp
        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """SSE 流式：逐 token 产出内容文本。"""
        payload: dict = {
            "model": kwargs.pop("model", None) or self._config.llm_model,
            "messages": messages,
            "stream": True,
            "max_tokens": kwargs.get("max_tokens") or self._config.max_tokens,
        }
        temp = kwargs.get("temperature") or self._config.temperature
        if temp is not None:
            payload["temperature"] = temp
        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                import json

                delta = json.loads(line[6:])["choices"][0].get("delta", {})
                if content := delta.get("content"):
                    yield content

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.post(
            "/embeddings",
            json={"model": self._config.embedding_model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]

    async def close(self) -> None:
        await self._client.aclose()


_client: LLMClient | None = None
_lock = asyncio.Lock()


async def get_client() -> LLMClient:
    """进程级单例：config 变化时（invalidate_cache 后）重建。"""
    global _client
    async with _lock:
        if _client is None:
            _client = LLMClient(await load_config())
        return _client


async def test_connection(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    """最小请求验证配置有效性，返回 (是否成功, 消息)。"""
    try:
        client = LLMClient(LLMConfig(
            base_url=base_url, api_key=api_key, llm_model=model,
            embedding_model="", rerank_model="", vlm_model="",
        ))
        resp = await client.chat(
            [{"role": "user", "content": "ping"}], max_tokens=4
        )
        await client.close()
        return True, f"连接成功，模型 {resp['model']} 响应正常"
    except httpx.HTTPStatusError as e:
        return False, f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        return False, f"连接失败: {e}"
