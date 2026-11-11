"""目录同步 API：配置多个监视路径、手动触发扫描。"""

import asyncio
import os
import sys

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import require_admin_key, require_query_key
from app.sync.dir_sync import get_watch_paths, save_watch_paths, scan_watch_paths

router = APIRouter(prefix="/api/paths", tags=["paths"])

# macOS 原生选择窗口（NSOpenPanel，文件/文件夹同框可选），JXA 调用；选中输出 POSIX 路径
_BROWSE_JXA = """
ObjC.import("AppKit");
const panel = $.NSOpenPanel.openPanel;
panel.canChooseFiles = true;
panel.canChooseDirectories = true;
panel.allowsMultipleSelection = false;
panel.message = "选择要监视的文件或文件夹";
panel.prompt = "选择";
if (panel.runModal === $.NSModalResponseOK) {
  panel.URLs[0].path.js;
} else {
  "";
}
"""

_BROWSE_TIMEOUT_SECONDS = 180


def _parse_browse_output(raw: str) -> str | None:
    """解析 osascript 输出：返回 POSIX 路径，取消/无选择返回 None。"""
    return raw.strip() or None


async def _run_browse_dialog() -> str:
    """调起系统选择窗口，返回选中路径；取消抛出 HTTPException(204 语义由调用方处理)。"""
    if sys.platform != "darwin":
        raise HTTPException(status_code=400, detail="仅 macOS 支持系统选择窗口，请手动输入路径")
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-l", "JavaScript", "-e", _BROWSE_JXA,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"无法启动 osascript：{e}") from e
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_BROWSE_TIMEOUT_SECONDS
        )
    except TimeoutError:
        proc.kill()
        raise HTTPException(
            status_code=504, detail="选择窗口超时未响应，请重试或手动输入路径"
        ) from None
    if proc.returncode != 0:
        detail = stderr.decode(errors="replace")[:200] or f"osascript 退出码 {proc.returncode}"
        raise HTTPException(status_code=500, detail=f"系统选择窗口失败：{detail}")
    return stdout.decode()


class WatchPath(BaseModel):
    path: str
    importance: str = "normal"  # high / normal
    enabled: bool = True

    @field_validator("path")
    @classmethod
    def must_be_absolute(cls, v: str) -> str:
        v = v.strip()
        if not v or not os.path.isabs(v):
            raise ValueError("必须是绝对路径，如 /data/kb")
        return v

    @field_validator("importance")
    @classmethod
    def must_be_valid_importance(cls, v: str) -> str:
        if v not in ("high", "normal"):
            raise ValueError("importance 只能是 high 或 normal")
        return v


class PathsIn(BaseModel):
    paths: list[WatchPath]


@router.get("")
async def list_paths(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_query_key),
) -> dict:
    paths = await get_watch_paths(session)
    return {
        "paths": [
            {
                **p,
                "exists": os.path.exists(p.get("path", "")),
            }
            for p in paths
        ]
    }


@router.put("")
async def save_paths(
    body: PathsIn,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin_key),
) -> dict:
    # 去重（同一路径只保留一条）
    seen: set[str] = set()
    unique = []
    for p in body.paths:
        if p.path in seen:
            continue
        seen.add(p.path)
        unique.append(p.model_dump())
    await save_watch_paths(session, unique)
    await session.commit()
    return {"status": "saved", "count": len(unique)}


@router.post("/browse")
async def browse_path(_: str = Depends(require_admin_key)) -> dict:
    """调起 macOS 原生选择窗口，返回选中的文件或文件夹绝对路径（取消时 path 为 null）。"""
    raw = await _run_browse_dialog()
    path = _parse_browse_output(raw)
    if path is None:
        return {"path": None, "cancelled": True}
    return {"path": path, "cancelled": False}


@router.post("/scan")
async def scan_now(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin_key),
) -> dict:
    """立即扫描所有启用路径：新文件入库、变更重建、消失删除。"""
    stats = await scan_watch_paths(session)
    await session.commit()
    return stats
