# kb-rag 多模态知识库系统

多模态 RAG：PDF/Word/xlsx/PPT/图片/视频入库 → 混合检索（向量+BM25+RRF+Rerank）→ 云端 LLM 带引用回答。完整方案见 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)。

## 快速启动

```bash
# 1. 基础设施（PG / Qdrant / Redis / MinIO）
docker compose up -d

# 2. 后端依赖与数据库
uv venv && uv pip install fastapi "uvicorn[standard]" pydantic pydantic-settings \
  "sqlalchemy[asyncio]" asyncpg psycopg2-binary alembic httpx qdrant-client redis arq \
  minio python-magic structlog cryptography pymupdf python-docx openpyxl python-pptx \
  watchdog "apscheduler<4.0" mcp sse-starlette pytest pytest-asyncio ruff
cp .env.example .env          # 按需修改
.venv/bin/alembic upgrade head

# 3. 前端
cd web && pnpm install && pnpm build && cd ..

# 4. 启动（两个终端）
.venv/bin/uvicorn app.main:app --port 8000          # API + 前端 http://localhost:8000
.venv/bin/arq app.workers.worker.WorkerSettings     # 索引 worker
```

## 使用

1. 打开 http://localhost:8000 → 设置页：选服务商（百炼/DeepSeek/硅基流动/OpenAI/自定义）→ 填 Base URL + API Key + 模型 → 测试连接 → 保存生效
2. 文档页：拖拽上传（重要=立即索引，普通=≤10 分钟定时入库）
3. 对话页：提问，答案带 [1][2] 引用可点击溯源；对话记录自动保存

## Claude Code 接入（MCP）

```bash
claude mcp add kb-rag --transport http http://localhost:8000/mcp
```

暴露工具：`kb_search` / `kb_get_document` / `kb_list_documents` / `kb_task_status`

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```
