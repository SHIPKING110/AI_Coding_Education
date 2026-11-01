"""RAG 运行参数：版本化配置、校验、缓存与回滚。

参数分为三组：
- 索引：chunk_size / chunk_overlap / parent_chunk_size
- 检索：top_k / rerank_oversample / min_similarity / per_doc_cap / hybrid 等
- 观测：trace 采样率与保留期

所有参数都可从后台修改；每次修改生成 RagConfigVersion 快照，支持回滚。
读取带 30s TTL 缓存，更新后立即失效。
"""

from __future__ import annotations

import copy
import threading
import time

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

DEFAULTS: dict = {
    # 索引
    "chunk_size": 512,
    "chunk_overlap": 100,
    "parent_chunk_size": 0,  # 0=关闭父子切分；>0 时为大块上下文字符上限
    # 检索
    "top_k": 5,
    "rerank_oversample": 5,
    "min_similarity": 0.35,
    "per_doc_cap": 2,
    "rerank_timeout_s": 1.5,
    "rerank_circuit_threshold": 3,
    "rerank_circuit_cooldown_s": 60,
    "keyword_fallback_enabled": True,
    "hybrid_enabled": False,
    "hybrid_candidates": 50,
    "query_rewrite_enabled": False,
    # 观测
    "trace_success_sample_rate": 1.0,
    "trace_retention_days": 30,
    "trace_error_retention_days": 90,
    # 按业务路由覆盖：{"agent_teacher": {"top_k": 5}, ...}
    "route_overrides": {},
}

_TTL_S = 30.0
_cache: tuple[float, dict] = (0.0, {})
_lock = threading.Lock()


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _clamp_float(value, lo: float, hi: float, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def sanitize(raw: dict | None) -> dict:
    """把任意输入规整为合法配置；未知键丢弃，越界值夹紧。"""
    src = dict(raw or {})
    out = copy.deepcopy(DEFAULTS)
    out["chunk_size"] = _clamp_int(src.get("chunk_size", DEFAULTS["chunk_size"]), 128, 2048, 512)
    out["chunk_overlap"] = _clamp_int(src.get("chunk_overlap", DEFAULTS["chunk_overlap"]), 0, 1024, 100)
    out["parent_chunk_size"] = _clamp_int(src.get("parent_chunk_size", 0), 0, 8192, 0)
    out["top_k"] = _clamp_int(src.get("top_k", DEFAULTS["top_k"]), 1, 50, 5)
    out["rerank_oversample"] = _clamp_int(src.get("rerank_oversample", 5), 1, 20, 5)
    out["min_similarity"] = _clamp_float(src.get("min_similarity", 0.35), 0.0, 1.0, 0.35)
    out["per_doc_cap"] = _clamp_int(src.get("per_doc_cap", 2), 1, 20, 2)
    out["rerank_timeout_s"] = _clamp_float(src.get("rerank_timeout_s", 1.5), 0.2, 10.0, 1.5)
    out["rerank_circuit_threshold"] = _clamp_int(src.get("rerank_circuit_threshold", 3), 1, 20, 3)
    out["rerank_circuit_cooldown_s"] = _clamp_int(src.get("rerank_circuit_cooldown_s", 60), 10, 3600, 60)
    out["keyword_fallback_enabled"] = bool(src.get("keyword_fallback_enabled", True))
    out["hybrid_enabled"] = bool(src.get("hybrid_enabled", False))
    out["hybrid_candidates"] = _clamp_int(src.get("hybrid_candidates", 50), 5, 200, 50)
    out["query_rewrite_enabled"] = bool(src.get("query_rewrite_enabled", False))
    out["trace_success_sample_rate"] = _clamp_float(src.get("trace_success_sample_rate", 1.0), 0.0, 1.0, 1.0)
    out["trace_retention_days"] = _clamp_int(src.get("trace_retention_days", 30), 1, 365, 30)
    out["trace_error_retention_days"] = _clamp_int(src.get("trace_error_retention_days", 90), 1, 365, 90)
    ro = src.get("route_overrides")
    out["route_overrides"] = ro if isinstance(ro, dict) else {}
    return out


def _load_from_db(db: Session) -> dict:
    from app.models.rag_admin import RagConfigVersion

    row = db.scalars(select(RagConfigVersion).order_by(desc(RagConfigVersion.version)).limit(1)).first()
    return sanitize((row.config if row else None) or {})


def get_config(db: Session | None = None, *, force: bool = False) -> dict:
    """读取当前生效配置；db 为空时自建短会话。"""
    global _cache
    now = time.time()
    if not force and now - _cache[0] < _TTL_S and _cache[1]:
        return copy.deepcopy(_cache[1])
    own = db is None
    session = db
    if session is None:
        from app.core.database import SessionLocal

        session = SessionLocal()
    try:
        cfg = _load_from_db(session)
    except Exception:
        cfg = copy.deepcopy(DEFAULTS)
    finally:
        if own:
            session.close()
    with _lock:
        _cache = (now, cfg)
    return copy.deepcopy(cfg)


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = (0.0, {})


def _next_version(db: Session) -> int:
    from app.models.rag_admin import RagConfigVersion

    row = db.scalars(select(RagConfigVersion).order_by(desc(RagConfigVersion.version)).limit(1)).first()
    return int(row.version) + 1 if row else 1


def _diff(old: dict, new: dict) -> dict:
    keys = set(old) | set(new)
    return {k: {"old": old.get(k), "new": new.get(k)} for k in keys if old.get(k) != new.get(k)}


def _write_audit(db: Session, *, action: str, target: str, detail: dict | None, operator_id) -> None:
    from app.models.rag_admin import RagAdminAudit

    db.add(RagAdminAudit(action=action, target=target, detail=detail or {}, operator_id=operator_id))
    db.commit()


def update_config(db: Session, payload: dict, *, operator_id=None, note: str = "") -> dict:
    """合并更新配置并生成新版本。"""
    from app.models.rag_admin import RagConfigVersion

    old = get_config(db, force=True)
    # 允许 payload 直接是 config，或 {"config": {...}, "note": "..."}
    incoming = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    merged = {**old}
    merged.update({k: v for k, v in incoming.items() if k in DEFAULTS})
    new = sanitize(merged)
    version = _next_version(db)
    row = RagConfigVersion(
        version=version,
        config=new,
        diff=_diff(old, new),
        note=(payload.get("note") or note or "")[:255],
        updated_by=operator_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _write_audit(
        db, action="config.update", target=f"v{version}",
        detail={"diff": row.diff, "note": row.note}, operator_id=operator_id,
    )
    invalidate()
    return {"version": version, "config": new, "diff": row.diff}


def list_versions(db: Session, *, limit: int = 50) -> list[dict]:
    from app.models.rag_admin import RagConfigVersion

    rows = db.scalars(
        select(RagConfigVersion).order_by(desc(RagConfigVersion.version)).limit(limit)
    ).all()
    return [
        {
            "version": r.version,
            "config": r.config,
            "diff": r.diff,
            "note": r.note,
            "updated_by": str(r.updated_by) if r.updated_by else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def rollback_config(db: Session, version: int, *, operator_id=None) -> dict:
    from app.models.rag_admin import RagConfigVersion

    src = db.scalars(select(RagConfigVersion).where(RagConfigVersion.version == version)).first()
    if src is None:
        raise ValueError("配置版本不存在")
    return update_config(
        db, dict(src.config or {}), operator_id=operator_id,
        note=f"回滚到 v{version}",
    )


__all__ = [
    "DEFAULTS",
    "get_config",
    "invalidate",
    "sanitize",
    "update_config",
    "list_versions",
    "rollback_config",
]
