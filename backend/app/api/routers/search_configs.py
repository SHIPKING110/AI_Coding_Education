"""联网搜索配置 API：系统级单例（管理员配置，全校共用）。

Key 只进不出（列表脱敏）；连通性检查用一次最小搜索。
"""

import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_teacher_permission
from app.core.database import get_db
from app.crud import search_config as crud
from app.models.user import User

router = APIRouter(prefix="/search-configs", tags=["search-configs"])

# 系统级单例：管理员，或已被授予「设置-模型配置」权限的教师（与管理员配置项对齐）
SETTING_PERM = require_teacher_permission("settings_tab_model")


class SearchIn(BaseModel):
    base_url: str = "https://api.tavily.com"
    api_key: str = ""
    enabled: bool = True
    search_depth: str = "basic"
    max_results: int = 5
    language: str = "zh"


def _out(row) -> dict:
    return {
        "id": str(row.id),
        "provider": row.provider,
        "base_url": row.base_url,
        "api_key_masked": "***" if row.api_key_enc else "",
        "enabled": row.enabled,
        "search_depth": row.search_depth,
        "max_results": row.max_results,
        "language": row.language,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
def get_search_config(
    db: Session = Depends(get_db),
    _: User = Depends(SETTING_PERM),
) -> dict:
    row = crud.get_system_search(db)
    return {"item": _out(row) if row else None}


@router.put("")
def set_search_config(
    payload: SearchIn,
    db: Session = Depends(get_db),
    _: User = Depends(SETTING_PERM),
) -> dict:
    existing = crud.get_system_search(db)
    # 创建时必填 Key；编辑时留空表示不改密钥
    if existing is None and not payload.api_key.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="首次配置需填写 Tavily API Key")
    row = crud.upsert_system_search(
        db,
        base_url=payload.base_url,
        api_key=payload.api_key,
        enabled=payload.enabled,
        search_depth=payload.search_depth,
        max_results=payload.max_results,
        language=payload.language,
    )
    return {"item": _out(row)}


@router.delete("")
def remove_search_config(
    db: Session = Depends(get_db),
    _: User = Depends(SETTING_PERM),
) -> dict:
    crud.delete_system_search(db)
    return {"deleted": True}


@router.post("/test")
def test_search_config(
    db: Session = Depends(get_db),
    _: User = Depends(SETTING_PERM),
) -> dict:
    """连通性检查：用当前生效配置做一次最小搜索。"""
    resolved = crud.resolve_search(db)
    if resolved is None:
        return {"ok": False, "error": "尚未配置可用的联网搜索（Tavily）"}
    from app.services import web_search

    started = time.time()
    result = web_search.search_web(resolved, query="pytest tavily connectivity check", max_results=1)
    elapsed = int((time.time() - started) * 1000)
    if result.get("错误"):
        return {"ok": False, "error": result["错误"], "latency_ms": elapsed}
    return {"ok": True, "latency_ms": elapsed, "count": result.get("条数", 0)}


__all__ = ["router"]
