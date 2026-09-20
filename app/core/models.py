"""SQLAlchemy 表定义：PG 是唯一真相源，Qdrant/BM25 是派生物。

状态机约定：
  document.status: uploaded → pending → indexing → indexed | failed
  index_task.status: pending → running → success | failed（retry_count < 3 可被定时器捞起）
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    pending = "pending"
    indexing = "indexing"
    indexed = "indexed"
    failed = "failed"


class Modality(str, enum.Enum):
    text = "text"
    image = "image"
    video = "video"


class ChunkModality(str, enum.Enum):
    text = "text"
    image = "image"
    video_transcript = "video_transcript"
    video_frame = "video_frame"


class AssetType(str, enum.Enum):
    image = "image"
    video_frame = "video_frame"
    thumbnail = "thumbnail"
    scanned_page = "scanned_page"


class TaskType(str, enum.Enum):
    index = "index"
    reindex = "reindex"
    delete = "delete"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class TriggeredBy(str, enum.Enum):
    event = "event"
    scheduler = "scheduler"
    manual = "manual"


class Document(Base):
    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512))
    file_type: Mapped[str] = mapped_column(String(32))  # 扩展名，如 pdf/docx/mp4
    modality: Mapped[Modality] = mapped_column(SAEnum(Modality))
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    file_hash: Mapped[str] = mapped_column(String(64), index=True)  # sha256，去重/变更检测
    source_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, index=True
    )  # 目录同步来源路径（上传文档为 None）
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    importance: Mapped[str] = mapped_column(String(16), default="normal")  # high/normal
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus), default=DocumentStatus.uploaded, index=True
    )
    needs_ocr: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class Chunk(Base):
    __tablename__ = "chunk"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    modality: Mapped[ChunkModality] = mapped_column(SAEnum(ChunkModality), index=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64))
    # 溯源元数据
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slide_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_ts: Mapped[float | None] = mapped_column(Float, nullable=True)  # 视频秒
    end_ts: Mapped[float | None] = mapped_column(Float, nullable=True)
    asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 派生索引
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # BM25 检索字段（tsvector，由 bigram 化 content 填充；类型在 Alembic 迁移中定义）
    # search_vector: 非 ORM 映射列，通过 raw SQL 访问（见 indexing/bm25_store.py）

    __table_args__ = (Index("ix_chunk_doc_ver", "document_id"),)


class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document.id", ondelete="CASCADE"), index=True
    )
    asset_type: Mapped[AssetType] = mapped_column(SAEnum(AssetType))
    storage_key: Mapped[str] = mapped_column(String(512))
    timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vlm_description: Mapped[str | None] = mapped_column(Text, nullable=True)


class IndexTask(Base):
    __tablename__ = "index_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("document.id"), index=True)
    task_type: Mapped[TaskType] = mapped_column(SAEnum(TaskType))
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus), default=TaskStatus.pending, index=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[TriggeredBy] = mapped_column(SAEnum(TriggeredBy))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_task_pending", "status", "created_at"),)


class UsageLog(Base):
    __tablename__ = "usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(32))  # embedding/rerank/vlm/llm
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    """对话记录：一问一答为一组 Message。"""

    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(128), default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversation.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    refs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    """key/value 运行时配置（API Key 等敏感值已 Fernet 加密）。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
