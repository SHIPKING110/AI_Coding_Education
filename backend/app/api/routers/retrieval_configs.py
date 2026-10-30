"""检索模型配置 API：系统级 Embedding（管理员）+ 教师级 Rerank（教师本人）。

Key 只进不出（列表脱敏）；连通性检查用一次最小 embedding / rerank 调用。
"""

import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_teacher_permission
from app.core.database import get_db
from app.crud import retrieval_config as crud
from app.models.user import User

router = APIRouter(prefix="/retrieval-configs", tags=["retrieval-configs"])

# 系统级 Embedding：管理员，或已被授予「设置-模型配置」权限的教师（与管理员配置项对齐）
EMBEDDING_PERM = require_teacher_permission("settings_tab_model")


class EmbeddingIn(BaseModel):
    provider: str = "remote"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    model_path: str = ""
    enabled: bool = True


class RerankIn(BaseModel):
    provider: str = "remote"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    model_path: str = ""
    enabled: bool = True


def _embedding_out(row) -> dict:
    return {
        "id": str(row.id),
        "provider": row.provider,
        "base_url": row.base_url,
        "api_key_masked": "***" if row.api_key_enc else "",
        "model": row.model,
        "model_path": row.model_path,
        "enabled": row.enabled,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _rerank_out(row) -> dict:
    return {
        "id": str(row.id),
        "provider": row.provider,
        "base_url": row.base_url,
        "api_key_masked": "***" if row.api_key_enc else "",
        "model": row.model,
        "model_path": row.model_path,
        "enabled": row.enabled,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/embedding")
def get_embedding_config(
    db: Session = Depends(get_db),
    _: User = Depends(EMBEDDING_PERM),
) -> dict:
    row = crud.get_system_embedding(db)
    return {"item": _embedding_out(row) if row else None}


@router.put("/embedding")
def set_embedding_config(
    payload: EmbeddingIn,
    db: Session = Depends(get_db),
    _: User = Depends(EMBEDDING_PERM),
) -> dict:
    if payload.provider != "local" and not (payload.base_url.strip() and payload.model.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="接口地址与模型名不能为空")
    if payload.provider != "local" and not payload.api_key.strip() and payload.api_key == "":
        # 编辑时允许留空表示不改密钥；创建时必填
        if crud.get_system_embedding(db) is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API Key 不能为空")
    row = crud.upsert_system_embedding(
        db,
        provider=payload.provider,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
        model_path=payload.model_path,
        enabled=payload.enabled,
    )
    # embedding 变更 → 集合分片指纹可能变化：立即失效缓存，让新配置即刻生效
    from app.services import rag

    rag.invalidate_embedding_cache()
    return {"item": _embedding_out(row)}


@router.delete("/embedding")
def remove_embedding_config(
    db: Session = Depends(get_db),
    _: User = Depends(EMBEDDING_PERM),
) -> dict:
    crud.delete_system_embedding(db)
    from app.services import rag

    rag.invalidate_embedding_cache()
    return {"deleted": True}


@router.post("/embedding/test")
def test_embedding_config(
    db: Session = Depends(get_db),
    _: User = Depends(EMBEDDING_PERM),
) -> dict:
    """连通性检查：用当前生效配置做一次 embedding。"""
    resolved = crud.resolve_embedding(db)
    if resolved is None:
        return {"ok": False, "error": "尚未配置可用的 Embedding 模型"}
    started = time.time()
    try:
        from app.services import rag

        vecs = rag.embed_texts(["连通性检查"])
        dim = len(vecs[0]) if vecs else 0
        return {"ok": True, "latency_ms": int((time.time() - started) * 1000), "dim": dim}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@router.get("/rerank")
def get_rerank_config(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    row = crud.get_rerank(db, user.id)
    return {"item": _rerank_out(row) if row else None}


@router.put("/rerank")
def set_rerank_config(
    payload: RerankIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if payload.provider != "local" and not (payload.base_url.strip() and payload.model.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="接口地址与模型名不能为空")
    if crud.get_rerank(db, user.id) is None and payload.provider != "local" and not payload.api_key.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API Key 不能为空")
    row = crud.upsert_rerank(
        db,
        owner_id=user.id,
        provider=payload.provider,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
        model_path=payload.model_path,
        enabled=payload.enabled,
    )
    return {"item": _rerank_out(row)}


@router.delete("/rerank")
def remove_rerank_config(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    crud.delete_rerank(db, user.id)
    return {"deleted": True}


@router.post("/rerank/test")
def test_rerank_config(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """连通性检查：一次最小 rerank 打分（remote 才可检查；local 预留）。"""
    resolved = crud.resolve_rerank(db, user.id)
    if resolved is None:
        return {"ok": False, "error": "尚未配置可用的 Rerank 模型"}
    if resolved.provider == "local":
        return {"ok": True, "latency_ms": 0, "note": "本地 Rerank 预留接口，未做远程连通检查"}
    started = time.time()
    try:
        from app.services import rag

        rag.rerank_documents("测试查询", ["这是第一段文档", "这是第二段文档"], resolved)
        return {"ok": True, "latency_ms": int((time.time() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


__all__ = ["router"]