# 多模态 RAG 知识库系统实施方案

> 版本：v1.0（定稿）· 日期：2026-09-20
> 状态：待实施 · 项目目录：`/Users/secneo/Documents/workspace/ai_project/RAG`

## 1. 背景与目标

从零构建多模态知识库 + RAG 系统：

- **内容类型**：PDF / Word / xlsx / PPT / 视频 / 图片 / 文本
- **实时更新**：重要文件事件驱动（≤1 分钟入索引）+ 普通文件定时批量（≤10 分钟）
- **核心能力**：自然语言查询混合检索各模态内容，统一重排后作为上下文喂给云端 LLM，生成带引用溯源的答案
- **消费端**：Web 前端（对话+管理）、Claude Code（MCP 接入）、REST API

### 已确认约束

| 项 | 约束 |
|---|---|
| 部署 | 普通服务器（8C16G + 500G SSD），**无 GPU**，Docker Compose 单机 |
| 模型 | 智能调用全走云端 API（Embedding/VLM/ASR/Rerank/LLM） |
| 规模 | 试点/小规模（十万文档以内） |
| 技术栈 | Python + FastAPI，轻量自研（不用 LangChain/LlamaIndex） |

## 2. 核心架构决策

1. **统一中间表示**：所有 parser 输出 `ParsedDocument{blocks}`（text / table / image_ref / transcript_segment / frame_ref），切片器只面向 Block 流——新增格式 = 新增 parser，互不影响
2. **全模态统一为文本向量空间**：图片/视频帧/扫描页用 VLM 生成文字描述后入文本索引。单索引覆盖全模态，rerank 天然跨模态排序，BM25 白送，描述可直接喂 LLM
3. **PG chunk 表是唯一真相源**：Qdrant / BM25 是派生物（payload 只存 chunk_id + 过滤字段）。更新 = 先索引新版本 → 再删旧版本 → 切 version，绝不做先删后插（避免窗口期查不到）
4. **index_task 表统一事件驱动与定时批量**：事件 = 插任务行 + 立即通知 arq worker；APScheduler 定时扫描 pending/failed 行兜底重试；两路天然幂等（同文档已有 running 任务则不重复投递）
5. **可插拔检索抽象**：统一 `Retriever` 接口 + Qdrant payload 预留 `acl` 字段，为二期 ColPali 视觉索引 / Agentic 循环留扩展点（本期不实现）

## 3. 系统架构

```
┌─ 服务器 (8C16G, 无GPU, Docker Compose) ──────────────────┐
│  接入层  FastAPI  上传/管理/查询(SSE)/设置/MCP endpoint     │
│  前端    Vite+React+TS 静态文件（FastAPI 托管）             │
│  同步层  arq worker (Redis 队列, 事件驱动)                  │
│          APScheduler (定时批量 + 失败兜底重试)               │
│          watchdog watcher (热目录监视自动入库)               │
│  解析层  Parser 注册表 → 统一 Block 中间表示 → 切片器        │
│  索引层  Qdrant (向量, HNSW, payload 过滤)                  │
│          PostgreSQL tsvector bigram (BM25)                 │
│  检索层  查询改写 → 双路召回 → RRF 融合 → 云端 Rerank        │
│  生成层  token 预算裁剪 + 引用编号组装 → LLM SSE 流式        │
│  存储层  MinIO (原文件/帧/缩略图) + PostgreSQL (元数据)      │
├─ 云端 API (阿里云百炼 DashScope, 一把 Key) ────────────────┤
│  Embedding: text-embedding-v3                              │
│  VLM: qwen-vl-max (图片/扫描页/视频帧描述)                  │
│  Rerank: gte-rerank-v2                                     │
│  ASR: paraformer-v2 (Phase 3 视频)                          │
│  LLM: qwen-max (可切 Claude/GPT, OpenAI 兼容封装)           │
└───────────────────────────────────────────────────────────┘
```

### 云 API 配置（双层）

- `.env` 静态配置（`DASHSCOPE_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`）：**初始默认值/兜底**，启动时校验
- **网页设置页配置优先**：运行时可改、保存即时生效——前端配好 Base URL + API Key + 模型并测试通过后，对话页直接可用，无需改文件重启

### 成本估算（试点规模）

月度 API 成本约 ¥400-1000，主要在 LLM 生成（随查询量线性增长）。建库期 embedding 为一次性成本（1 万文档 ≈ ¥100-200）。

## 4. 技术选型

| 组件 | 选型 | 说明 |
|---|---|---|
| Web 框架 | FastAPI | 异步原生，SSE 一等公民 |
| 任务队列/调度 | arq（Redis）+ APScheduler（worker 内） | 比 Celery 轻，原生 asyncio |
| 向量库 | Qdrant（单容器） | payload 过滤/按 document_id 删除干净 |
| BM25 | PostgreSQL tsvector + bigram 分词 | 零额外依赖；规模化后迁 zhparser 自制镜像或 ES |
| 对象存储 | MinIO（S3 协议） | 云上可切 OSS，代码不绑定 |
| 元数据 DB | PostgreSQL + SQLAlchemy 2.0 + Alembic | chunk 表即真相源 |
| Embedding/Rerank/VLM/LLM | 通义系（百炼） | `llm/client.py` OpenAI 兼容统一封装，可切换供应商 |
| 解析 | pymupdf / python-docx / openpyxl / python-pptx | 标准答案 |
| 视频（P3） | ffmpeg + PySceneDetect | 抽帧/场景切分 |
| MCP | 官方 `mcp` Python SDK（Streamable HTTP） | 与 FastAPI 同进程 |

## 5. 各模态处理策略

| 格式 | 策略 |
|---|---|
| txt/md | 按标题/段落切分 |
| PDF 文字型 | pymupdf 提取文本+页码，标题层级切片；内嵌图片抽出走图片管线 |
| PDF 扫描件 | 页均字符数低于阈值标 `needs_ocr`，整页当图片送 VLM 生成描述（免独立 OCR 管线） |
| docx | python-docx 保留 heading 层级切片 |
| xlsx | 逐 sheet 转 Markdown 表；小表整块 chunk，大表按行块切片且**每 chunk 重复注入表头**（保证单独命中时语义完整） |
| pptx | 每页一个 chunk（文本+备注），页内图片走图片管线，`slide_no` 入元数据 |
| 图片 | VLM 生成描述（prompt：客观描述+可见文字+图表数据），描述冗余存 `asset.vlm_description`（换供应商/重建不重跑） |
| 视频（P3） | ffmpeg 抽音轨 → paraformer ASR 带时间戳 → 30-60s 窗口聚合 chunk（含 start_ts/end_ts）；PySceneDetect 场景切分 + pHash 去重 → 差异帧 VLM 一句描述，元数据关联帧图+时间戳 |

## 6. 检索与生成流水线

```
用户 query
  → 查询改写（LLM，Phase 2）
  → 双路召回：向量 top-30 + BM25 top-30
  → RRF 融合（无需调权重）
  → 云端 Rerank 重排取 top-8（全模态统一文本空间，天然跨模态排序）
  → token 预算裁剪（默认 5k 硬上限）
  → 引用编号组装 [1][2]...
  → LLM SSE 流式生成
  → 流末下发引用元数据（文件名/页码/sheet/时间戳/缩略图 URL，可点击溯源）
```

## 7. 数据模型（关键表）

```
document    id, filename, file_type, modality, storage_key, file_hash(去重/变更检测),
            version, importance, status(uploaded→pending→indexing→indexed/failed),
            needs_ocr, deleted_at(软删)

chunk       id, document_id, chunk_index, content, modality(text/image/video_transcript/
            video_frame), token_count, content_hash,
            溯源: page_no/slide_no/start_ts/end_ts/asset_id, qdrant_point_id

asset       id, document_id, asset_type(image/video_frame/thumbnail), storage_key,
            timestamp, vlm_description

index_task  id, document_id, task_type(index/reindex/delete), status(pending/running/
            success/failed), retry_count, triggered_by(event/scheduler/manual)

usage_log   request_id, 阶段(embedding/rerank/vlm/llm), token 消耗, 成本, created_at

settings    key/value（API Key 用 APP_SECRET 派生密钥 Fernet 加密落库）
```

## 8. 数据接入与消费端

### 三种接入通道

1. **REST API 上传**：multipart，`importance=high` 立即索引 / `normal` 定时批量
2. **目录同步 Agent**（`workers/watcher.py`，watchdog）：
   ```
   /data/kb-drop/important/   ← 秒级：文件落盘即触发事件驱动索引
   /data/kb-drop/normal/      ← ≤10 分钟：标记 pending 定时批量
   ```
   拷入即自动「上传→存储→解析→索引」；改名/修改（file_hash 变化）自动重建；删除自动清理向量
3. **定时全量比对兜底**：APScheduler 扫目录与库内 hash 比对，捕获停机期变更

### MCP Server（Claude Code 接入）

`api/mcp_server.py` 暴露工具：`kb_search` / `kb_get_document` / `kb_list_documents` / `kb_upload` / `kb_task_status`

```bash
claude mcp add rag-kb --transport http http://<服务器>:8000/mcp
```

接入后 Claude 在对话中自主调用知识库检索。**检索与生成分离**支撑双消费端：Web 端走 `/api/query` SSE 全流程；Claude Code 走 MCP 只取检索结果，生成由 Claude 完成。一套索引，多消费端。

## 9. 前端（Vite + React + TS）

### 设计风格：米纸靛蓝（Paper & Indigo）

文档工作台气质——米纸白底承载内容，深靛蓝只做「交互与引用」的强调，知识感强、长时间阅读不累眼，会议室演示明亮得体。

**设计令牌（CSS Custom Properties，web/src/styles/tokens.css）**：

```css
:root {
  /* 表面 */
  --color-bg:        #FAF7F2;   /* 米纸白 */
  --color-surface:   #FFFFFF;   /* 卡片/输入框 */
  --color-border:    #E5DFD5;   /* 暖灰边框 */
  --color-ink:       #1F2430;   /* 主文字 */
  --color-ink-2:     #6B7280;   /* 次要文字 */
  --color-ink-3:     #9CA3AF;   /* 占位/禁用 */

  /* 强调（仅用于交互与引用，克制使用） */
  --color-accent:      #2E4BD8; /* 深靛蓝：按钮/链接/引用编号 */
  --color-accent-ink:  #FFFFFF;
  --color-accent-soft: rgba(46,75,216,.08);  /* 引用卡底/选中态 */

  /* 语义 */
  --color-ok:   #0E9F6E;  /* 已索引/成功 */
  --color-err:  #D92D20;  /* 失败/删除 */
  --color-warn: #B45309;  /* 索引中/警告 */

  /* 排版 */
  --font-body:  'Source Serif 4','Noto Serif SC',Georgia,serif; /* 正文/对话：衬线，知识气质 */
  --font-ui:    'Inter','Noto Sans SC',-apple-system,sans-serif; /* 界面元素/标签 */
  --font-mono:  'JetBrains Mono',ui-monospace,monospace;         /* 引用编号/元数据/代码 */

  --text-sm: 13px;  --text-base: 15px;  --text-lg: 18px;  --text-title: 22px;

  /* 节奏 */
  --radius-sm: 6px;  --radius-md: 10px;  --radius-lg: 16px;
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-6: 24px; --space-8: 32px; --space-12: 48px;
  --shadow-card: 0 1px 2px rgba(31,36,48,.05), 0 4px 16px rgba(31,36,48,.06);
}
```

**排版策略**：正文与对话气泡用衬线（Source Serif 4 + 思源宋体）营造"阅读文档"的气质；界面导航、按钮、标签用无衬线 Inter 保证清晰度；引用编号 `[1]`、chunk 元数据（页码/时间戳/sheet）、代码片段用等宽 JetBrains Mono——三种字体的分工本身就是层级。

**组件规范要点**：
- **引用卡片**：左侧 3px 靛蓝边条 + 米纸软底，文件名衬线粗体，元数据等弱小字；视频引用内嵌缩略图 + 播放时间点
- **引用编号内联标记**：等宽小字 + 靛蓝软底圆角，可点击跳转对应卡片
- **状态徽标**：已索引●绿 / 索引中◌靛蓝转圈 / 失败✕红（可重试）
- **强调色纪律**：靛蓝只出现在"可交互/可溯源"元素上，纯展示内容不使用，保证引用体系一目了然
- **深色模式**：一期不做（内部工作台场景）；tokens 已按变量化组织，二期如需可按同套 accent 派生深色表面，成本极低

### 页面功能

| 页面 | 功能 |
|---|---|
| **设置页** | LLM 运行时配置：服务商预设下拉（百炼/OpenAI/Anthropic/硅基流动/自定义）自动填 Base URL + API Key + 模型名（常用下拉+手动输入）+「测试连接」；高级项 temperature/max_tokens/上下文预算；embedding/rerank/VLM 同页可配，**换 embedding 需全量重建索引**（UI 警示 + 一键 reindex_all）；Key 掩码显示（仅回传尾 4 位），保存即时生效 |
| **文档管理页** | 拖拽/多文件上传、列表（状态筛选 indexing/indexed/failed）、删除、重建索引、任务进度 |
| **对话页** | SSE 流式回答、引用 [1][2] 点击溯源（文档跳页码/视频跳时间点/图片展示缩略图） |
| **热目录说明** | 展示监视目录路径与规则 |

轻量实现：无重型组件库依赖，fetch + SSE 原生，`web/` 构建产物由 FastAPI 托管。所有云 API 调用发生在后端（Key 不暴露给浏览器）。

### 运行时 LLM 配置（后端）

- `GET/PUT /api/settings/llm` + `POST /api/settings/llm/test`（最小请求验证连通性）；修改需管理级 API Key
- `llm/client.py` 读动态配置（带缓存，保存时失效）；`.env` Key 降级为初始默认值

## 10. 安全鉴权

- **API**：API Key 头校验（FastAPI middleware，`X-API-Key`），管理操作与查询可分两级 Key
- **MCP endpoint**：token 校验
- **上传校验**：扩展名白名单（pdf/docx/xlsx/pptx/txt/md/png/jpg/mp4 等）+ 实际 MIME 嗅探（python-magic）+ 单文件大小上限（默认 500MB）
- **密钥管理**：全部走 `.env` 或 settings 表（加密），启动校验存在性，不硬编码

## 11. 可观测性与备份

**可观测性**：
- 结构化日志（structlog）：每请求记录 query、命中 chunk 数、检索各阶段耗时
- `usage_log` 表逐请求记录 token 消耗与成本（embedding/rerank/vlm/llm 分列）
- 基础指标：索引队列积压深度、检索延迟 P95、云 API 失败率（`/metrics` Prometheus 格式）

**备份容灾**：
- PostgreSQL：每日 `pg_dump`（cron + 本地保留 7 天）
- MinIO 数据目录：定期 rsync 备份盘
- Qdrant 不备份——可由 chunk 表全量重建（`scripts/reindex_all.py` 即恢复工具）

## 12. 项目目录结构

```
RAG/
├── pyproject.toml
├── docker-compose.yml          # qdrant + postgres + redis + minio
├── alembic/                    # DB 迁移
├── app/
│   ├── main.py                 # FastAPI 装配
│   ├── config.py               # pydantic-settings
│   ├── api/
│   │   ├── routes_documents.py # 上传/列表/删除/重建
│   │   ├── routes_query.py     # 查询 + SSE 流式
│   │   ├── routes_tasks.py     # 任务状态
│   │   ├── routes_settings.py  # LLM 运行时配置 + 测试连接
│   │   └── mcp_server.py       # MCP: kb_search 等工具
│   ├── core/
│   │   ├── models.py           # SQLAlchemy 表定义
│   │   ├── schemas.py          # Pydantic DTO
│   │   ├── storage.py          # MinIO/S3 封装
│   │   ├── security.py         # API Key 鉴权 + Fernet 加密
│   │   └── db.py               # session/引擎
│   ├── parsers/
│   │   ├── base.py             # Block 中间表示 + 注册表
│   │   ├── pdf_parser.py       # 文字型 + 扫描件检测
│   │   ├── docx_parser.py / xlsx_parser.py / pptx_parser.py / text_parser.py
│   │   ├── image_parser.py     # VLM 描述
│   │   └── video_parser.py     # ASR + 抽帧（Phase 3）
│   ├── chunking/chunker.py     # 标题感知/表头注入/时间窗
│   ├── llm/
│   │   ├── client.py           # OpenAI 兼容统一封装（读动态配置）
│   │   ├── embeddings.py / reranker.py / vlm.py
│   │   └── asr.py              # Phase 3
│   ├── indexing/
│   │   ├── vector_store.py     # Qdrant 封装
│   │   ├── bm25_store.py       # PG tsvector bigram
│   │   └── pipeline.py         # 解析→切片→embed→upsert 编排
│   ├── retrieval/
│   │   ├── base.py             # Retriever 抽象
│   │   ├── query_rewrite.py / hybrid_search.py(双路+RRF) / rerank.py
│   ├── generation/
│   │   ├── context_builder.py  # token 预算 + 引用编号
│   │   ├── prompts.py / generator.py
│   └── workers/
│       ├── worker.py           # arq 任务定义
│       ├── scheduler.py        # APScheduler 定时扫描
│       └── watcher.py          # watchdog 目录监视
├── web/                        # Vite + React + TS 前端（米纸靛蓝主题，见 §9 设计规范）
│   └── src/styles/tokens.css   # 设计令牌（CSS 变量单一来源）
├── scripts/
│   ├── reindex_all.py          # 全量重建（兼恢复工具）
│   └── backup.sh               # pg_dump + MinIO 同步
└── tests/
    ├── test_chunker.py / test_parsers/ / test_retrieval.py
```

## 13. 实施阶段与验收标准

### Phase 0+1（第 1-2 周）：骨架与 MVP——文本 + 图片
- docker-compose 一键起依赖；DB 表 + Alembic；配置体系
- txt/md/pdf(文字型)/docx 解析切片 + 图片 VLM 描述
- embedding + Qdrant + BM25(bigram) + RRF + rerank
- 查询 API（SSE）+ 引用溯源；事件驱动索引 + 删除同步
- **MCP Server**（Claude Code 可接入）

**验收**：20 文档 + 20 图，10 条测试 query ≥8 条正确且引用可溯源；图片语义查询命中；删除后不再出现其引用；Claude Code 通过 MCP 检索正常工作

### Phase 2（第 3-4 周）：办公格式 + 定时增量 + 前端
- xlsx（表头注入）/pptx（按页）/扫描件 PDF（VLM）
- 定时批量 + 失败重试 + 任务状态 API；查询改写
- **目录监视 watcher**（热目录自动入库）
- **前端**：设置页（含测试连接）+ 文档管理页 + 对话页（引用溯源）
- 安全鉴权与上传校验

**验收**：xlsx 数据行查中（引用带 sheet/行号）；普通文件 ≤10 分钟入索引、重要文件 ≤1 分钟；kill worker 任务不丢、重启恢复；文件拷入热目录自动入库；前端完成「配置 API → 上传 → 状态查看 → 问答 → 引用溯源」全流程

### Phase 3（第 5-7 周）：视频 + 加固
- ASR 转录 + 时间窗切片；场景抽帧（pHash 去重）+ VLM 帧描述
- 命中返回时间点/时间段 + 缩略图
- 可观测性（结构化日志 + usage 表 + 指标）；备份脚本

**验收**：10 分钟视频提问命中转录段时间点 ±10s；usage 表可查每请求成本；备份脚本可恢复

### 二期预留（不在本期）
ColPali 视觉文档索引（届时租按量 GPU）、Agentic 检索循环、Text2SQL（xlsx 精确查询）、Wiki 综述层、权限过滤（acl 字段已预留）

## 14. 风险与对策

| 风险 | 对策 |
|---|---|
| 视频处理成本 | 场景检测 + pHash 去重只描述差异帧，单视频 VLM <¥1；放 Phase 3 不拖 MVP |
| token 成本 | 上下文 5k 硬上限、rerank 后 top-8、chunk 300-500 token、逐请求 usage 日志 |
| 增量一致性 | 文档级重建（先索引新→删旧→切 version）+ 定时器兜底；不做 chunk 级差量（字段预留） |
| 中文分词 | PG 官方镜像无 zhparser——MVP 用 bigram（零依赖），规模化后迁 zhparser/ES |
| 云 API 限流/失败 | 批量调用加并发信号量 + arq 指数退避重试（默认 3 次） |
| 大文件上传 | multipart 流式直写 MinIO（不落临时盘），超时按视频大小调大 |
| 明确不做 | 多租户/权限、分布式 worker、独立 OCR 管线、LangChain |

## 15. 验证方式

- **单元测试**：chunker（标题/表头/时间窗边界）、各 parser（含扫描件检测）、RRF 融合、context_builder（预算裁剪、引用映射）
- **端到端**：`docker compose up` 后按各阶段验收标准人工测试（上传→索引→查询→引用→删除→复查）
- **MCP 验证**：`claude mcp add` 接入后对话测试 kb_search 工具调用
