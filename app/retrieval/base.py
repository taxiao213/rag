"""Retriever 抽象：检索层统一接口，MCP / Web / 未来 Agentic 循环共用。"""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class Retriever(Protocol):
    async def search(
        self, session: AsyncSession, query: str, *, modality: str | None = None, top_n: int = 8
    ) -> list[dict]:
        """返回带引用元数据的 chunk 列表。具体实现见 hybrid_search。"""
        ...
