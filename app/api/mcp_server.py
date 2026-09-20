"""MCP Server（mcp 2.x）：暴露知识库检索工具给 Claude Code 等 Agent 客户端。

工具：kb_search / kb_get_document / kb_list_documents / kb_task_status
挂载方式：MCPServer.streamable_http_app() 挂到 FastAPI（见 main.py）。
"""

from mcp.server.mcpserver import MCPServer
from sqlalchemy import select

from app.core.db import get_session_factory
from app.core.models import Document, IndexTask
from app.retrieval.hybrid_search import hybrid_search

mcp = MCPServer("kb-rag", instructions=(
    "本地多模态知识库检索服务。用户询问知识库中可能存在的内容时，"
    "使用 kb_search 检索；需要深入阅读某个来源时用 kb_get_document。"
))


@mcp.tool()
async def kb_search(query: str, modality: str | None = None, top_n: int = 8) -> str:
    """在本地知识库中检索相关内容。返回按相关度排序的文档片段，
    每条带引用元数据（文件名、页码/视频时间点）。

    Args:
        query: 检索查询（自然语言）
        modality: 可选内容类型过滤（text/image/video_transcript/video_frame）
        top_n: 返回条数
    """
    factory = get_session_factory()
    async with factory() as session:
        results = await hybrid_search(session, query, modality=modality, top_n=top_n)
    if not results:
        return "知识库中未找到相关内容。"
    lines = []
    for i, r in enumerate(results, 1):
        loc = ""
        if r.get("page_no"):
            loc = f"第 {r['page_no']} 页"
        elif r.get("start_ts") is not None:
            loc = f"视频 {r['start_ts']:.0f}s-{r['end_ts']:.0f}s"
        elif r.get("slide_no"):
            loc = f"第 {r['slide_no']} 张"
        lines.append(
            f"[{i}] 《{r['filename']}》{loc}\n{r['content']}\n"
            f"（相关度 {r['score']:.3f}，chunk_id: {r['chunk_id']}）"
        )
    return "\n\n---\n\n".join(lines)


@mcp.tool()
async def kb_get_document(document_id: str) -> str:
    """获取某文档的全部内容片段（用于深入阅读某个来源）。

    Args:
        document_id: 文档 ID（由 kb_list_documents 或 kb_search 返回）
    """
    from app.core.models import Chunk

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(Chunk)
                .where(Chunk.document_id == document_id)
                .order_by(Chunk.chunk_index)
            )
        ).scalars().all()
    if not rows:
        return "文档不存在或尚未索引。"
    return "\n\n".join(f"[{c.chunk_index}] {c.content}" for c in rows)


@mcp.tool()
async def kb_list_documents(status: str | None = None) -> str:
    """列出知识库中的文档及其索引状态。

    Args:
        status: 可选状态过滤（uploaded/pending/indexing/indexed/failed）
    """
    factory = get_session_factory()
    async with factory() as session:
        q = select(Document).where(Document.deleted_at.is_(None))
        if status:
            q = q.where(Document.status == status)
        docs = (await session.execute(q)).scalars().all()
    lines = [f"- {d.filename}（{d.status.value}，{d.modality.value}，id: {d.id}）" for d in docs]
    return "\n".join(lines) or "知识库为空。"


@mcp.tool()
async def kb_task_status(task_id: str) -> str:
    """查询索引任务进度（上传后确认是否处理完成）。

    Args:
        task_id: 索引任务 ID
    """
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(IndexTask, task_id)
    if task is None:
        return "任务不存在。"
    return (
        f"任务 {task.id}: {task.status.value}（重试 {task.retry_count} 次）"
        + (f"，错误: {task.error}" if task.error else "")
    )
