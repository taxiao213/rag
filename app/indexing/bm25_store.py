"""BM25 检索：PostgreSQL tsvector + bigram 分词（中文零依赖方案）。

原理：中文不做分词，将文本切为 2 字滑窗 bigram 存入 tsvector（PG 内置 simple 配置
会按非字母数字拆分，但中文字符整体视为一个 token——因此检索侧同样 bigram 化查询，
用 & 连接匹配所有 bigram）。实现简单、无 zhparser 依赖，中文召回效果可用。

该模块维护 chunk 的 search_vector 字段（存储在 chunk 表上，tsvector 类型由 Alembic 迁移添加）。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def to_bigrams(s: str) -> str:
    """中文字符串 → 空格分隔的 bigram（含 ASCII 单词原样保留）。"""
    import re

    parts: list[str] = []
    for token in re.findall(r"[A-Za-z0-9]+|[一-鿿]+", s):
        if re.fullmatch(r"[A-Za-z0-9]+", token):
            parts.append(token.lower())
        else:
            # CJK 连续段 → bigram（单字也保留）
            if len(token) == 1:
                parts.append(token)
            else:
                parts.extend(token[i : i + 2] for i in range(len(token) - 1))
    return " ".join(parts)


async def update_search_vectors(session: AsyncSession, chunk_ids: list[str]) -> None:
    """将指定 chunk 的 content bigram 化写入 search_vector。"""
    for cid in chunk_ids:
        row = await session.execute(
            text("SELECT content FROM chunk WHERE id = :cid"), {"cid": cid}
        )
        content = row.scalar_one()
        await session.execute(
            text("UPDATE chunk SET search_vector = to_tsvector('simple', :vec) WHERE id = :cid"),
            {"vec": to_bigrams(content), "cid": cid},
        )


async def delete_by_document(session: AsyncSession, document_id: str) -> None:
    """chunk 级联删除即可，无需额外操作（保留接口与 vector_store 对称）。"""


async def search(session: AsyncSession, query: str, top_k: int) -> list[dict]:
    """BM25 检索：查询 bigram 化后 tsquery & 匹配，ts_rank 排序。"""
    bigrams = to_bigrams(query)
    if not bigrams:
        return []
    result = await session.execute(
        text(
            """
            SELECT c.id AS chunk_id, c.document_id, c.modality::text AS modality,
                   ts_rank(c.search_vector, q.query) AS score
            FROM chunk c,
                 (SELECT to_tsquery('simple', :tsq) AS query) q
            WHERE c.search_vector @@ q.query
            ORDER BY score DESC
            LIMIT :top_k
            """
        ),
        {"tsq": " & ".join(bigrams.split()), "top_k": top_k},
    )
    return [
        {"chunk_id": str(r.chunk_id), "document_id": r.document_id,
         "modality": r.modality, "score": float(r.score)}
        for r in result
    ]
