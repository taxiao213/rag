"""云端 LLM 统一客户端：OpenAI 兼容协议，生成与索引两组独立配置。

- chat 配置：生成层（对话回答）
- index 配置：索引层（embedding / vlm / rerank）——可与生成层不同供应商
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

SETTINGS_KEY_CHAT = "llm_config_chat"
SETTINGS_KEY_INDEX = "llm_config_index"


@dataclass
class ChatConfig:
    base_url: str
    api_key: str
    llm_model: str
    max_tokens: int = 2048


@dataclass
class IndexConfig:
    base_url: str
    api_key: str
    embedding_model: str
    rerank_model: str
    vlm_model: str


_chat_cache: ChatConfig | None = None
_index_cache: IndexConfig | None = None


def invalidate_cache() -> None:
    global _chat_cache, _index_cache
    _chat_cache = None
    _index_cache = None


async def _read_setting(session, key: str) -> dict:
    row = await session.scalar(select(Setting).where(Setting.key == key))
    if not row:
        return {}
    value = dict(row.value)
    if value.get("api_key_encrypted"):
        value["api_key"] = decrypt_secret(value.pop("api_key_encrypted"))
    return {k: v for k, v in value.items() if v not in (None, "")}


async def load_chat_config() -> ChatConfig:
    """生成层配置：settings 表优先，回落 .env。"""
    global _chat_cache
    if _chat_cache is not None:
        return _chat_cache
    env = get_settings()
    base = {
        "base_url": env.llm_base_url,
        "api_key": env.llm_api_key,
        "llm_model": env.llm_model,
        "max_tokens": 2048,
    }
    factory = get_session_factory()
    async with factory() as session:
        base.update(await _read_setting(session, SETTINGS_KEY_CHAT))
    _chat_cache = ChatConfig(**{k: v for k, v in base.items() if k in ChatConfig.__dataclass_fields__})
    return _chat_cache


async def load_index_config() -> IndexConfig:
    """索引层配置：独立 settings，缺失回落到生成层配置（兼容旧单配置）。"""
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    env = get_settings()
    chat = await load_chat_config()
    base = {
        "base_url": chat.base_url,
        "api_key": chat.api_key,
        "embedding_model": env.embedding_model,
        "rerank_model": env.rerank_model,
        "vlm_model": env.vlm_model,
    }
    factory = get_session_factory()
    async with factory() as session:
        base.update(await _read_setting(session, SETTINGS_KEY_INDEX))
    _index_cache = IndexConfig(
        **{k: v for k, v in base.items() if k in IndexConfig.__dataclass_fields__}
    )
    return _index_cache


class LLMClient:
    """OpenAI 兼容协议客户端：chat（含流式）与 embedding。"""

    def __init__(self, base_url: str, api_key: str, default_model: str = "",
                 default_max_tokens: int = 2048) -> None:
        self.default_model = default_model
        self.default_max_tokens = default_max_tokens
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def chat(self, messages: list[dict], *, model: str | None = None,
                   max_tokens: int | None = None) -> dict:
        resp = await self._client.post(
            "/chat/completions",
            json={
                "model": model or self.default_model,
                "messages": messages,
                "max_tokens": max_tokens or self.default_max_tokens,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """SSE 流式：逐 token 产出内容文本。"""
        payload = {
            "model": kwargs.pop("model", None) or self.default_model,
            "messages": messages,
            "stream": True,
            "max_tokens": kwargs.get("max_tokens") or self.default_max_tokens,
        }
        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.is_error:
                await resp.aread()  # 读取错误响应体，便于上层展示具体原因
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                import json

                delta = json.loads(line[6:])["choices"][0].get("delta", {})
                if content := delta.get("content"):
                    yield content

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        resp = await self._client.post(
            "/embeddings",
            json={"model": model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]

    async def close(self) -> None:
        await self._client.aclose()


_chat_client: LLMClient | None = None
_index_client: LLMClient | None = None
_lock = asyncio.Lock()


async def get_chat_client() -> LLMClient:
    """生成层单例：对话问答用。"""
    global _chat_client
    async with _lock:
        if _chat_client is None:
            cfg = await load_chat_config()
            _chat_client = LLMClient(cfg.base_url, cfg.api_key, cfg.llm_model, cfg.max_tokens)
        return _chat_client


async def get_index_client() -> LLMClient:
    """索引层单例：embedding/VLM 用。"""
    global _index_client
    async with _lock:
        if _index_client is None:
            cfg = await load_index_config()
            _index_client = LLMClient(cfg.base_url, cfg.api_key)
        return _index_client


async def reset_clients() -> None:
    """配置变更后调用：关闭并清空客户端缓存。"""
    global _chat_client, _index_client
    invalidate_cache()
    async with _lock:
        for client in (_chat_client, _index_client):
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass
        _chat_client = None
        _index_client = None


def describe_llm_error(e: Exception) -> str:
    """把 LLM/embedding 调用异常转成用户可读文案（沿 __cause__ 追溯被包装的原始错误）。"""
    try:
        return _describe_llm_error(e)
    except Exception:
        return f"调用失败：{type(e).__name__}"


def _describe_llm_error(e: Exception) -> str:
    err: BaseException = e
    while getattr(err, "__cause__", None) is not None:
        err = err.__cause__
    if isinstance(err, httpx.HTTPStatusError):
        code = err.response.status_code
        try:
            body = (err.response.text or "").strip()[:200]
        except Exception:
            body = ""  # 流式响应未读取时 body 不可访问，仅报状态码
        suffix = f"：{body}" if body else ""
        if code == 401:
            return f"模型 API 鉴权失败（401），请到设置页检查对应组的 API Key{suffix}"
        if code == 404:
            return f"模型 API 返回 404，请检查设置页的 Base URL 或模型名是否正确{suffix}"
        if code == 429:
            return f"模型 API 调用频率超限（429），请稍后重试{suffix}"
        return f"模型 API 返回 HTTP {code}{suffix}"
    if isinstance(err, httpx.TimeoutException):
        return "模型 API 请求超时，请稍后重试或检查网络"
    if isinstance(err, httpx.HTTPError):
        return f"无法连接模型服务，请检查网络或代理设置（{type(err).__name__}）"
    return f"调用失败：{err}"


async def test_connection(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    """最小请求验证配置有效性，返回 (是否成功, 消息)。"""
    try:
        client = LLMClient(base_url, api_key, model)
        resp = await client.chat([{"role": "user", "content": "ping"}], max_tokens=4)
        await client.close()
        return True, f"连接成功，模型 {resp.get('model', model)} 响应正常"
    except httpx.HTTPStatusError as e:
        return False, f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        return False, f"连接失败: {e}"


async def test_embedding(base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    """验证 embedding 接口可用性。"""
    try:
        client = LLMClient(base_url, api_key)
        vectors = await client.embed(["测试"], model)
        await client.close()
        return True, f"连接成功，返回 {len(vectors[0])} 维向量"
    except httpx.HTTPStatusError as e:
        return False, f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        return False, f"连接失败: {e}"
