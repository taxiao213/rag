"""目录同步 API：配置多个监视路径、手动触发扫描。"""

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import require_admin_key, require_query_key
from app.sync.dir_sync import get_watch_paths, save_watch_paths, scan_watch_paths

router = APIRouter(prefix="/api/paths", tags=["paths"])


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
            {**p, "exists": os.path.isdir(p.get("path", ""))} for p in paths
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


@router.post("/scan")
async def scan_now(
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_admin_key),
) -> dict:
    """立即扫描所有启用路径：新文件入库、变更重建、消失删除。"""
    stats = await scan_watch_paths(session)
    await session.commit()
    return stats
