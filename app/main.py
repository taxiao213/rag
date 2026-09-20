"""FastAPI 装配：路由、健康检查、MCP 挂载、静态文件托管。"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_chunks,
    routes_conversations,
    routes_documents,
    routes_query,
    routes_settings,
    routes_tasks,
)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(ensure_ascii=False),
    ]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.storage import ensure_bucket

    ensure_bucket()
    # MCP session manager 任务组必须在宿主 lifespan 中启动（挂载不触发子应用 lifespan）
    from app.api.mcp_server import mcp as kb_mcp

    async with kb_mcp.session_manager.run():
        yield
    from app.workers.queue import close_pool

    await close_pool()


app = FastAPI(title="kb-rag", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_documents.router)
app.include_router(routes_query.router)
app.include_router(routes_tasks.router)
app.include_router(routes_settings.router)
app.include_router(routes_conversations.router)
app.include_router(routes_chunks.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ---- MCP（Streamable HTTP，挂载 Starlette 子应用到 /mcp） ----
from app.api.mcp_server import mcp as kb_mcp  # noqa: E402

_mcp_app = kb_mcp.streamable_http_app(streamable_http_path="/")
app.mount("/mcp", _mcp_app)


# ---- 前端静态文件（web/dist 构建产物，存在则托管） ----
from pathlib import Path  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
