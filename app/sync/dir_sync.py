"""目录同步：配置的多个目录路径 → 扫描入库 / 变更重建 / 消失删除。

路径配置存 settings 表（key=watch_paths），JSON：
  {"paths": [{"path": "/data/kb", "importance": "normal", "enabled": true}]}

扫描规则（与上传共用同一入库管线）：
- 启用路径可以是目录（递归遍历）或单个文件，按扩展名白名单过滤（同上传）
- 新文件 → 创建 Document(source_path=绝对路径) + index 任务
- 同一路径文件内容变化（hash 不同）→ 覆盖对象存储 + reindex 任务（文档级重建）
- source_path 在某启用路径下但文件已消失 → delete 任务（仅当该路径本身可访问时执行，防误删）
- importance=high 的任务立即投递 arq（事件驱动），normal 留给定时批量
"""

import hashlib
import os
import uuid
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.models import (
    Document,
    DocumentStatus,
    IndexTask,
    Modality,
    Setting,
    TaskType,
    TriggeredBy,
)
from app.core.security import ALLOWED_EXTENSIONS, get_settings

log = structlog.get_logger()

SETTINGS_KEY_PATHS = "watch_paths"

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
VIDEO_EXTS = {"mp4", "mov", "avi", "mkv"}


def _modality_of(ext: str) -> Modality:
    if ext in IMAGE_EXTS:
        return Modality.image
    if ext in VIDEO_EXTS:
        return Modality.video
    return Modality.text


def iter_sync_files(root: str) -> list[Path]:
    """递归列出目录下符合白名单与大小上限的文件（纯函数，便于测试）。"""
    max_bytes = get_settings().upload_max_mb * 1024 * 1024
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in ALLOWED_EXTENSIONS:
                continue
            p = Path(dirpath) / name
            try:
                if p.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            results.append(p)
    return sorted(results)


def _file_watch_check(p: Path) -> str | None:
    """单文件监视路径的准入检查（纯函数，便于测试）。返回错误信息，None 表示可入库。"""
    ext = p.name.rsplit(".", 1)[-1].lower() if "." in p.name else ""
    if ext not in ALLOWED_EXTENSIONS:
        return f"不支持的文件类型：{p.name}"
    max_bytes = get_settings().upload_max_mb * 1024 * 1024
    try:
        if p.stat().st_size > max_bytes:
            return f"文件超过大小上限：{p.name}"
    except OSError:
        return f"文件不可访问：{p.name}"
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


async def get_watch_paths(session: AsyncSession) -> list[dict]:
    row = await session.scalar(select(Setting).where(Setting.key == SETTINGS_KEY_PATHS))
    if not row:
        return []
    return row.value.get("paths", [])


async def save_watch_paths(session: AsyncSession, paths: list[dict]) -> None:
    row = await session.scalar(select(Setting).where(Setting.key == SETTINGS_KEY_PATHS))
    value = {"paths": paths}
    if row:
        row.value = value
    else:
        session.add(Setting(key=SETTINGS_KEY_PATHS, value=value))


async def _enqueue(session: AsyncSession, doc_id: str, task_type: TaskType, high: bool) -> None:
    task = IndexTask(
        document_id=doc_id,
        task_type=task_type,
        triggered_by=TriggeredBy.event if high else TriggeredBy.scheduler,
    )
    session.add(task)
    await session.flush()
    if high:
        from app.workers.queue import enqueue_index_task

        await enqueue_index_task(task.id)


async def _sync_one_file(
    session: AsyncSession, path: Path, importance: str, stats: dict
) -> None:
    full = str(path.resolve())
    file_hash = sha256_file(path)
    ext = path.name.rsplit(".", 1)[-1].lower()
    high = importance == "high"

    # 同一路径的文档（含已删除）：活跃文档按 hash 跳过/重建；
    # 已删除且 hash 未变 → 用户在知识库手动移除的，尊重删除不再回捞；
    # 已删除但 hash 变了 → 文件内容已更新，当作新内容重新入库
    docs = (
        await session.execute(select(Document).where(Document.source_path == full))
    ).scalars().all()
    doc = next((d for d in docs if d.deleted_at is None), None)
    if doc is None and any(d.file_hash == file_hash for d in docs):
        stats["skipped"] += 1
        return
    if doc:
        if doc.file_hash == file_hash:
            stats["skipped"] += 1
            return
        data = path.read_bytes()
        doc.storage_key = f"docs/{doc.id}.{ext}"
        await storage.put_object(doc.storage_key, data, "application/octet-stream")
        doc.file_hash = file_hash
        doc.size_bytes = len(data)
        doc.status = DocumentStatus.indexing if high else DocumentStatus.pending
        doc.error = None
        await _enqueue(session, doc.id, TaskType.reindex, high)
        stats["updated"] += 1
        log.info("目录同步：文件变更，重建索引", path=full)
        return

    # 内容与其他来源文档重复 → 跳过
    dup = await session.scalar(
        select(Document).where(Document.file_hash == file_hash, Document.deleted_at.is_(None))
    )
    if dup:
        stats["skipped"] += 1
        return

    data = path.read_bytes()
    doc_id = str(uuid.uuid4())
    storage_key = f"docs/{doc_id}.{ext}"
    await storage.put_object(storage_key, data, "application/octet-stream")
    doc = Document(
        id=doc_id,
        filename=path.name,
        file_type=ext,
        modality=_modality_of(ext),
        storage_key=storage_key,
        file_hash=file_hash,
        source_path=full,
        size_bytes=len(data),
        importance=importance,
        status=DocumentStatus.indexing if high else DocumentStatus.pending,
    )
    session.add(doc)
    await session.flush()
    await _enqueue(session, doc_id, TaskType.index, high)
    stats["added"] += 1
    log.info("目录同步：新文件入库", path=full)


async def scan_watch_paths(session: AsyncSession) -> dict:
    """扫描所有启用路径，返回统计。路径不可访问时跳过该路径（不执行删除同步）。"""
    paths = await get_watch_paths(session)
    stats: dict = {
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped": 0,
        "errors": [],
    }
    for entry in paths:
        if not entry.get("enabled", True):
            continue
        root = entry.get("path", "").strip()
        importance = entry.get("importance", "normal")
        if not root:
            continue
        if os.path.isfile(root):
            # 单文件监视：走与目录同一的入库管线；文件消失时与目录同样保守处理（不误删文档）
            p = Path(root)
            err = _file_watch_check(p)
            if err:
                stats["errors"].append(f"{root}：{err}")
                log.warning("目录同步：单文件路径不满足入库条件，跳过", path=root, err=err)
                continue
            try:
                await _sync_one_file(session, p, importance, stats)
            except Exception as e:
                stats["errors"].append(f"{p.name}: {e}")
                log.error("目录同步：文件处理失败", path=root, err=str(e))
            continue
        if not os.path.isdir(root):
            stats["errors"].append(f"路径不存在或不可访问：{root}")
            log.warning("目录同步：路径不可访问，跳过", path=root)
            continue
        # 解析符号链接（如 macOS /tmp → /private/tmp），与 source_path 的 resolve 保持一致
        root = str(Path(root).resolve())

        seen: set[str] = set()
        for p in iter_sync_files(root):
            full = str(p.resolve())
            seen.add(full)
            try:
                await _sync_one_file(session, p, importance, stats)
            except Exception as e:
                stats["errors"].append(f"{p.name}: {e}")
                log.error("目录同步：文件处理失败", path=full, err=str(e))

        # 删除同步：该路径下 source_path 的文档，文件已不存在 → 删除
        prefix = os.path.join(root, "")
        stale = (
            await session.execute(
                select(Document).where(
                    Document.source_path.like(f"{prefix}%"),
                    Document.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for doc in stale:
            if doc.source_path in seen:
                continue
            await _enqueue(
                session, doc.id, TaskType.delete, high=doc.importance == "high"
            )
            stats["deleted"] += 1
            log.info("目录同步：文件已移除，删除文档", path=doc.source_path)

    return stats
