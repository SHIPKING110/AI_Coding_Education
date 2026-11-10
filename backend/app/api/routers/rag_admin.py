"""RAG 运营后台 API（管理员）：总览 / 知识资产 / 追踪 / 配置 / 评测。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_teacher_permission
from app.core.database import SessionLocal, get_db
from app.crud import knowledge as kb_crud
from app.crud import llm_config as llm_crud
from app.crud import rag_admin as crud
from app.models.knowledge import KnowledgeDocument
from app.models.user import Role, User
from app.services import agent_ops, rag_evaluation, rag_settings, rag_trace
from app.services import rag as rag_service

router = APIRouter(
    prefix="/admin/rag",
    tags=["rag-admin"],
)

_SESSION_FACTORY = SessionLocal


def _doc_out(doc: KnowledgeDocument, owner_name: str = "") -> dict:
    extra = doc.extra or {}
    return {
        "id": str(doc.id),
        "title": doc.title,
        "description": doc.description,
        "owner_id": str(doc.owner_id),
        "owner_name": owner_name,
        "visibility": doc.visibility,
        "enabled": bool(doc.enabled),
        "visible_to_parents": bool(doc.visible_to_parents),
        "file_name": doc.file_name,
        "status": doc.status,
        "error": doc.error,
        "chunk_count": doc.chunk_count,
        "progress": extra.get("progress"),
        "indexed_hash": extra.get("indexed_hash"),
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


def _mark_done(doc_id, chunk_count: int, error: str | None) -> None:
    db = _SESSION_FACTORY()
    try:
        kb_crud.mark_indexed(db, doc_id=doc_id, chunk_count=chunk_count, error=error)
    finally:
        db.close()


def _mark_progress(doc_id, stage: str, percent: int, detail: str = "") -> None:
    db = _SESSION_FACTORY()
    try:
        kb_crud.mark_progress(db, doc_id=doc_id, stage=stage, percent=percent, detail=detail)
    finally:
        db.close()


@router.get("/overview", dependencies=[Depends(require_teacher_permission("rag_overview_view", staff_allowed=False))])
def overview(db: Session = Depends(get_db)) -> dict:
    now = datetime.now(UTC)
    status_rows = db.execute(
        select(KnowledgeDocument.status, func.count()).group_by(KnowledgeDocument.status)
    ).all()
    status_counts = {str(k or "unknown"): int(v or 0) for k, v in status_rows}
    total_docs = sum(status_counts.values())
    chunks = int(db.scalar(select(func.coalesce(func.sum(KnowledgeDocument.chunk_count), 0))) or 0)
    enabled = int(db.scalar(
        select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.enabled.is_(True))
    ) or 0)
    parent_visible = int(db.scalar(
        select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.visible_to_parents.is_(True))
    ) or 0)
    plaza = int(db.scalar(
        select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.visibility == "plaza")
    ) or 0)
    last_updated = db.scalar(select(func.max(KnowledgeDocument.updated_at)))
    stats_24h = crud.trace_stats(db, since=now - timedelta(hours=24))
    stats_7d = crud.trace_stats(db, since=now - timedelta(days=7))
    domains = crud.trace_domain_stats(db, since=now - timedelta(days=7))
    recent_errors = crud.list_traces(db, error_only=True, page_size=5)["items"]
    latest_eval = next(
        (crud.eval_run_to_dict(r) for r in crud.list_eval_runs(db, limit=20) if r.status == "done"),
        None,
    )
    try:
        collections = rag_service.collection_stats()
    except Exception:
        collections = {"active": rag_service.active_collection_name(), "collections": []}
    risks: list[dict] = []
    if status_counts.get("failed"):
        risks.append({"level": "error", "title": "索引失败文档", "detail": f"{status_counts['failed']} 篇文档索引失败"})
    if stats_24h["zero_result_rate"] and stats_24h["zero_result_rate"] > 0.2:
        risks.append({"level": "warn", "title": "零结果率偏高", "detail": f"24h 零结果率 {stats_24h['zero_result_rate']:.0%}"})
    if stats_24h["vector_fail"]:
        risks.append({"level": "warn", "title": "向量召回降级", "detail": f"24h 有 {stats_24h['vector_fail']} 次向量失败"})
    if not collections.get("collections"):
        risks.append({"level": "warn", "title": "向量集合为空", "detail": "尚未建立知识库集合或 embedding 未配置"})
    return {
        "assets": {
            "documents": total_docs,
            "ready": status_counts.get("ready", 0),
            "indexing": status_counts.get("indexing", 0) + status_counts.get("pending", 0),
            "failed": status_counts.get("failed", 0),
            "chunks": chunks,
            "enabled": enabled,
            "parent_visible": parent_visible,
            "plaza": plaza,
            "last_updated": last_updated.isoformat() if last_updated else None,
        },
        "retrieval_24h": stats_24h,
        "retrieval_7d": stats_7d,
        "domains_7d": domains,
        "collections": collections,
        "risks": risks,
        "recent_errors": recent_errors,
        "latest_eval": latest_eval,
    }


@router.get("/documents", dependencies=[Depends(require_teacher_permission("rag_assets_view", staff_allowed=False))])
def list_documents(
    q: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    visibility: str | None = None,
    enabled: bool | None = None,
    parent_visible: bool | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
) -> dict:
    conds = []
    if q:
        like = f"%{q.strip()}%"
        conds.append(KnowledgeDocument.title.ilike(like) | KnowledgeDocument.description.ilike(like))
    if status_filter:
        conds.append(KnowledgeDocument.status == status_filter)
    if visibility:
        conds.append(KnowledgeDocument.visibility == visibility)
    if enabled is not None:
        conds.append(KnowledgeDocument.enabled.is_(enabled))
    if parent_visible is not None:
        conds.append(KnowledgeDocument.visible_to_parents.is_(parent_visible))
    base = select(KnowledgeDocument, User.name).outerjoin(User, User.id == KnowledgeDocument.owner_id)
    count_stmt = select(func.count()).select_from(KnowledgeDocument)
    if conds:
        base = base.where(*conds)
        count_stmt = count_stmt.where(*conds)
    total = int(db.scalar(count_stmt) or 0)
    rows = db.execute(
        base.order_by(KnowledgeDocument.updated_at.desc())
        .offset(max(0, (page - 1) * page_size)).limit(page_size)
    ).all()
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [_doc_out(doc, owner_name or "") for doc, owner_name in rows],
    }


@router.get("/documents/{doc_id}", dependencies=[Depends(require_teacher_permission("rag_assets_view", staff_allowed=False))])
def document_detail(doc_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    doc = kb_crud.get_document_any(db, doc_id=doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    owner = db.get(User, doc.owner_id)
    out = _doc_out(doc, owner.name if owner else "")
    out["extra"] = doc.extra or {}
    out["storage"] = rag_service.document_storage_profile(doc)
    if doc.visible_to_parents:
        out["parent_storage"] = rag_service.document_storage_profile(doc, parent=True)
    else:
        out["parent_storage"] = None
    return out


@router.get("/documents/{doc_id}/chunks", dependencies=[Depends(require_teacher_permission("rag_assets_view", staff_allowed=False))])
def document_chunks(doc_id: uuid.UUID, limit: int = 500) -> dict:
    return {"items": rag_service.get_document_chunks(doc_id, limit=limit)}


@router.post("/documents/{doc_id}/reindex", dependencies=[Depends(require_teacher_permission("rag_assets_reindex", staff_allowed=False))])
def reindex_document(
    doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    doc = kb_crud.get_document_any(db, doc_id=doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not doc.file_path:
        raise HTTPException(status_code=400, detail="源文件路径为空")
    from pathlib import Path

    if not Path(doc.file_path).exists():
        raise HTTPException(status_code=400, detail="源文件已丢失，请删除后重新上传")
    doc = kb_crud.mark_indexing(db, doc)
    rag_service.index_in_background(
        doc_id=doc.id, owner_id=doc.owner_id, title=doc.title,
        file_path=doc.file_path, file_name=doc.file_name or "",
        mark_done=_mark_done, mark_progress=_mark_progress,
    )
    crud.add_audit(
        db, action="document.reindex", target=str(doc.id),
        detail={"title": doc.title}, operator_id=user.id,
    )
    return _doc_out(doc)


@router.post("/documents/{doc_id}/toggle", dependencies=[Depends(require_teacher_permission("rag_assets_reindex", staff_allowed=False))])
def toggle_document(
    doc_id: uuid.UUID,
    enabled: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    doc = kb_crud.get_document_any(db, doc_id=doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    new_value = (not bool(doc.enabled)) if enabled is None else enabled
    doc = kb_crud.set_enabled(db, doc, new_value)
    crud.add_audit(
        db, action="document.toggle", target=str(doc.id),
        detail={"enabled": new_value}, operator_id=user.id,
    )
    return _doc_out(doc)


@router.post("/documents/{doc_id}/parent-visible", dependencies=[Depends(require_teacher_permission("rag_assets_reindex", staff_allowed=False))])
def toggle_parent_visible(
    doc_id: uuid.UUID,
    visible: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    doc = kb_crud.get_document_any(db, doc_id=doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    new_value = (not bool(doc.visible_to_parents)) if visible is None else visible
    doc = kb_crud.set_parent_visible(db, doc, new_value)
    if new_value:
        # 开启家长可见 → 若配置了家长专属 Embedding，后台补建父索引
        rag_service.start_parent_index_sync()
    else:
        rag_service.delete_document_vectors(doc.id, parent=True)
    crud.add_audit(
        db, action="document.parent_visible", target=str(doc.id),
        detail={"visible": new_value}, operator_id=user.id,
    )
    return _doc_out(doc)


@router.delete("/documents/{doc_id}", dependencies=[Depends(require_teacher_permission("rag_assets_delete", staff_allowed=False))])
def delete_document(
    doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    doc = kb_crud.get_document_any(db, doc_id=doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    rag_service.delete_document_vectors(doc.id)
    rag_service.delete_document_vectors(doc.id, parent=True)
    from pathlib import Path

    try:
        Path(doc.file_path).unlink(missing_ok=True)
    except OSError:
        pass
    title = doc.title
    kb_crud.delete_document(db, doc)
    crud.add_audit(
        db, action="document.delete", target=str(doc_id),
        detail={"title": title}, operator_id=user.id,
    )
    return {"ok": True}


@router.get("/knowledge-bases", dependencies=[Depends(require_teacher_permission("rag_assets_view", staff_allowed=False))])
def knowledge_bases(db: Session = Depends(get_db)) -> dict:
    docs = list(db.scalars(select(KnowledgeDocument)).all())
    buckets = {
        "private": {"key": "private", "name": "教师私有库", "description": "教师本人上传、未发布到广场的文档", "docs": []},
        "plaza": {"key": "plaza", "name": "广场库", "description": "全校教师发布、可被收录的文档", "docs": []},
        "parent": {"key": "parent", "name": "家长政策库", "description": "家长客服白名单文档", "docs": []},
    }
    for d in docs:
        if d.visibility == "plaza":
            buckets["plaza"]["docs"].append(d)
        else:
            buckets["private"]["docs"].append(d)
        if d.visible_to_parents:
            buckets["parent"]["docs"].append(d)
    now = datetime.now(UTC)
    domains = {x["domain"]: x for x in crud.trace_domain_stats(db, since=now - timedelta(days=7))}
    out = []
    for key, b in buckets.items():
        items = b.pop("docs")
        out.append({
            **b,
            "documents": len(items),
            "ready": sum(1 for d in items if d.status == "ready"),
            "failed": sum(1 for d in items if d.status == "failed"),
            "chunks": sum(int(d.chunk_count or 0) for d in items),
            "queries_7d": (domains.get("agent_teacher" if key in ("private", "plaza") else "parent_service") or {}).get("queries", 0),
            "zero_result_rate_7d": (domains.get("agent_teacher" if key in ("private", "plaza") else "parent_service") or {}).get("zero_result_rate"),
        })
    return {"items": out}


@router.get("/collections", dependencies=[Depends(require_teacher_permission("rag_assets_view", staff_allowed=False))])
def collections() -> dict:
    try:
        return rag_service.collection_stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取向量集合失败：{exc}")


@router.post("/collections/sweep", dependencies=[Depends(require_teacher_permission("rag_assets_sweep", staff_allowed=False))])
def sweep_collections(
    dry_run: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    result = rag_service.sweep_orphan_vectors(db, delete=not dry_run)
    crud.add_audit(
        db, action="collections.sweep", target=result.get("collection", ""),
        detail={**result, "dry_run": dry_run}, operator_id=user.id,
    )
    return result


@router.post("/maintenance/sync", dependencies=[Depends(require_teacher_permission("rag_assets_reindex", staff_allowed=False))])
def trigger_sync(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    result = rag_service.sync_changed_documents(limit=limit)
    crud.add_audit(
        db, action="maintenance.sync", target="knowledge",
        detail=result, operator_id=user.id,
    )
    return result


@router.get("/routes", dependencies=[Depends(require_teacher_permission("rag_routes_view", staff_allowed=False))])
def routes(db: Session = Depends(get_db)) -> dict:
    cfg = rag_settings.get_config(db)
    overrides = cfg.get("route_overrides") or {}
    base = [
        {
            "key": "agent_teacher", "name": "Agent 教师域",
            "owner_scope": "当前教师", "doc_scope": "本人文档 + 收录的广场文档",
            "description": "Agent 工作台对话开启/自动引用知识库时使用",
            "defaults": {"top_k": cfg.get("top_k"), "min_similarity": cfg.get("min_similarity"), "per_doc_cap": cfg.get("per_doc_cap"), "rerank": True},
        },
        {
            "key": "parent_service", "name": "家长客服域",
            "owner_scope": "归属教师/管理员", "doc_scope": "家长版白名单文档",
            "description": "家长 AI 客服问答，严格白名单隔离",
            "defaults": {"top_k": 5, "min_similarity": cfg.get("min_similarity"), "per_doc_cap": cfg.get("per_doc_cap"), "rerank": True},
        },
        {
            "key": "admin_test", "name": "后台测试域",
            "owner_scope": "指定 owner", "doc_scope": "指定文档集合",
            "description": "管理员测试台，不参与生产对话",
            "defaults": {"top_k": cfg.get("top_k"), "min_similarity": cfg.get("min_similarity"), "per_doc_cap": cfg.get("per_doc_cap"), "rerank": True},
        },
    ]
    for r in base:
        r["override"] = overrides.get(r["key"]) or {}
        r["effective"] = {**r["defaults"], **r["override"]}
    return {"items": base}


class RouteOverrideIn(BaseModel):
    top_k: int | None = None
    min_similarity: float | None = None
    per_doc_cap: int | None = None
    rerank_oversample: int | None = None


@router.put("/routes/{route_key}", dependencies=[Depends(require_teacher_permission("rag_routes_save", staff_allowed=False))])
def update_route_override(
    route_key: str, body: RouteOverrideIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    if route_key not in {"agent_teacher", "parent_service", "admin_test", "eval"}:
        raise HTTPException(status_code=404, detail="未知路由")
    cfg = rag_settings.get_config(db, force=True)
    overrides = dict(cfg.get("route_overrides") or {})
    current = dict(overrides.get(route_key) or {})
    for k, v in body.model_dump(exclude_none=True).items():
        current[k] = v
    overrides[route_key] = current
    result = rag_settings.update_config(
        db, {"config": {"route_overrides": overrides}, "note": f"路由 {route_key} 参数覆盖"},
        operator_id=user.id,
    )
    crud.add_audit(
        db, action="route.update", target=route_key,
        detail={"override": current}, operator_id=user.id,
    )
    return {"route_key": route_key, "override": current, "version": result.get("version")}


class RouteTestIn(BaseModel):
    query: str
    owner_id: uuid.UUID | None = None
    route_key: str = "admin_test"
    collected_ids: list[uuid.UUID] = Field(default_factory=list)
    top_k: int | None = None
    rerank: bool = True
    min_similarity: float | None = None


@router.post("/routes/test", dependencies=[Depends(require_teacher_permission("rag_routes_test", staff_allowed=False))])
def route_test(body: RouteTestIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    if not body.query.strip():
        raise HTTPException(status_code=422, detail="query 不能为空")
    owner_id = body.owner_id or user.id
    diag: dict = {}
    with rag_trace.trace_scope(
        domain="admin_test", user_id=user.id, owner_id=owner_id,
        route=body.route_key or "admin_test",
    ):
        hits = rag_service.retrieve(
            body.query.strip(), db=db, owner_id=owner_id,
            collected_ids=body.collected_ids, top_k=body.top_k,
            rerank=body.rerank, min_similarity=body.min_similarity,
            diag=diag, route_key=body.route_key or "admin_test",
        )
    return {
        "hits": hits,
        "diag": diag,
        "summary": rag_service.retrieval_summary(diag),
        "trace_id": diag.get("trace_id"),
    }


@router.get("/traces", dependencies=[Depends(require_teacher_permission("rag_traces_view", staff_allowed=False))])
def list_traces(
    domain: str | None = None,
    owner_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    zero_only: bool = False,
    error_only: bool = False,
    rag_status: str | None = None,
    feedback: str | None = None,
    q: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
) -> dict:
    return crud.list_traces(
        db, domain=domain, owner_id=owner_id, conversation_id=conversation_id,
        zero_only=zero_only, error_only=error_only, rag_status=rag_status, feedback=feedback, q=q,
        created_from=created_from, created_to=created_to,
        page=page, page_size=page_size,
    )


@router.get("/traces/{trace_id}", dependencies=[Depends(require_teacher_permission("rag_traces_view", staff_allowed=False))])
def trace_detail(trace_id: str, db: Session = Depends(get_db)) -> dict:
    row = crud.get_trace(db, trace_id)
    if row is None:
        raise HTTPException(status_code=404, detail="trace 不存在")
    out = crud.trace_to_dict(row)
    # 关联的 Agent 运行（任务型对话可查看完整执行过程）
    try:
        from app.crud import agent_ops as agent_ops_crud
        runs = agent_ops_crud.list_runs_by_trace(db, trace_id)
        out["related_runs"] = [
            {
                "run_id": r.run_id,
                "agent_id": r.agent_id,
                "intent": r.intent,
                "task_kind": r.task_kind,
                "status": r.status,
                "needs_rag": bool(r.needs_rag),
                "rag_decision": r.rag_decision,
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ]
    except Exception:
        out["related_runs"] = []
    return out


class TraceFeedbackIn(BaseModel):
    feedback: str


@router.post("/traces/{trace_id}/feedback", dependencies=[Depends(require_teacher_permission("rag_traces_view", staff_allowed=False))])
def trace_feedback(trace_id: str, body: TraceFeedbackIn, db: Session = Depends(get_db)) -> dict:
    ok = crud.set_trace_feedback(db, trace_id, body.feedback)
    if not ok:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return {"ok": True}


@router.post("/maintenance/cleanup-traces", dependencies=[Depends(require_teacher_permission("rag_traces_view", staff_allowed=False))])
def cleanup_traces(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    result = rag_trace.cleanup_expired()
    try:
        result["agent_runs"] = agent_ops.cleanup_expired()
    except Exception:
        result["agent_runs"] = {"deleted": 0}
    crud.add_audit(db, action="maintenance.cleanup_traces", target="trace", detail=result, operator_id=user.id)
    return result


@router.get("/parent-sessions", dependencies=[Depends(require_teacher_permission("rag_parent_sessions_view", staff_allowed=False))])
def list_parent_sessions(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    risk: bool | None = None,
    days: int = 30,
    db: Session = Depends(get_db),
) -> dict:
    return crud.list_parent_sessions(db, page=page, page_size=page_size, status=status, risk=risk, days=days)


@router.get("/parent-sessions/{thread_id}", dependencies=[Depends(require_teacher_permission("rag_parent_sessions_view", staff_allowed=False))])
def parent_session_detail(thread_id: str, db: Session = Depends(get_db)) -> dict:
    detail = crud.get_parent_session_detail(db, thread_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return detail


@router.get("/config", dependencies=[Depends(require_teacher_permission("rag_settings_view", staff_allowed=False))])
def get_config(db: Session = Depends(get_db)) -> dict:
    return {"config": rag_settings.get_config(db, force=True), "defaults": rag_settings.DEFAULTS}


class ConfigIn(BaseModel):
    config: dict | None = None
    note: str = ""


@router.put("/config", dependencies=[Depends(require_teacher_permission("rag_settings_save", staff_allowed=False))])
def update_config(body: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    result = rag_settings.update_config(db, body, operator_id=user.id)
    return result


@router.get("/config/versions", dependencies=[Depends(require_teacher_permission("rag_settings_view", staff_allowed=False))])
def config_versions(db: Session = Depends(get_db)) -> dict:
    return {"items": rag_settings.list_versions(db)}


@router.post("/config/rollback/{version}", dependencies=[Depends(require_teacher_permission("rag_settings_save", staff_allowed=False))])
def rollback_config(version: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    try:
        return rag_settings.rollback_config(db, version, operator_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/audit", dependencies=[Depends(require_teacher_permission("rag_settings_view", staff_allowed=False))])
def audit_log(limit: int = 100, db: Session = Depends(get_db)) -> dict:
    return {"items": crud.list_audit(db, limit=limit)}


# —— 评测 ——

class EvalSetIn(BaseModel):
    name: str
    description: str = ""
    domain: str = "agent_teacher"
    owner_id: uuid.UUID | None = None


@router.get("/eval/sets", dependencies=[Depends(require_teacher_permission("rag_eval_view", staff_allowed=False))])
def list_eval_sets(db: Session = Depends(get_db)) -> dict:
    return {"items": [crud.eval_set_to_dict(x) for x in crud.list_eval_sets(db)]}


@router.post("/eval/sets", dependencies=[Depends(require_teacher_permission("rag_eval_set_create", staff_allowed=False))])
def create_eval_set(body: EvalSetIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    row = crud.create_eval_set(
        db, name=body.name, description=body.description, domain=body.domain,
        owner_id=body.owner_id, created_by=user.id,
    )
    crud.add_audit(db, action="eval.set.create", target=str(row.id), detail={"name": row.name}, operator_id=user.id)
    return crud.eval_set_to_dict(row)


@router.delete("/eval/sets/{set_id}", dependencies=[Depends(require_teacher_permission("rag_eval_set_create", staff_allowed=False))])
def delete_eval_set(set_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ok = crud.delete_eval_set(db, set_id)
    if not ok:
        raise HTTPException(status_code=404, detail="评测集不存在")
    crud.add_audit(db, action="eval.set.delete", target=str(set_id), operator_id=user.id)
    return {"ok": True}


class EvalCaseIn(BaseModel):
    query: str
    relevant: list[str] = Field(default_factory=list)
    # 显式可答性：answerable / unanswerable / unlabeled；留空保持历史推断逻辑
    answerability: str = ""
    split: str = "regression"
    business_criticality: str = "normal"
    gt_answer: str = ""
    gt_keywords: list[str] = Field(default_factory=list)
    query_type: str = "fact"
    difficulty: str = "normal"
    notes: str = ""
    source: str = "manual"


@router.get("/eval/models", dependencies=[Depends(require_teacher_permission("rag_eval_view", staff_allowed=False))])
def list_eval_models(
    owner_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """可选的评测模型配置：默认当前用户；管理员/教务可查看指定 owner。"""
    target = owner_id or user.id
    if user.role not in (Role.ADMIN.value, Role.STAFF.value) and target != user.id:
        raise HTTPException(status_code=403, detail="只能查看自己的模型配置")
    rows = llm_crud.list_configs(db, target)
    return {
        "owner_id": str(target),
        "items": [
            {
                "id": str(c.id),
                "name": c.name,
                "model": c.model,
                "base_url": c.base_url,
                "is_default": bool(c.is_default),
            }
            for c in rows
        ],
    }


@router.get("/eval/sets/{set_id}/cases", dependencies=[Depends(require_teacher_permission("rag_eval_view", staff_allowed=False))])
def list_eval_cases(
    set_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    if crud.get_eval_set(db, set_id) is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    total = crud.count_eval_cases(db, set_id)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    rows = crud.list_eval_cases(
        db, set_id, offset=(page - 1) * page_size, limit=page_size
    )
    return {
        "items": [crud.eval_case_to_dict(x) for x in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/eval/sets/{set_id}/cases", dependencies=[Depends(require_teacher_permission("rag_eval_case_add", staff_allowed=False))])
def add_eval_case(set_id: uuid.UUID, body: EvalCaseIn, db: Session = Depends(get_db)) -> dict:
    if crud.get_eval_set(db, set_id) is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    row = crud.add_eval_case(
        db, set_id=set_id, query=body.query, relevant=body.relevant,
        answerability=body.answerability, split=body.split,
        business_criticality=body.business_criticality,
        gt_answer=body.gt_answer, gt_keywords=body.gt_keywords,
        query_type=body.query_type, difficulty=body.difficulty,
        notes=body.notes, source=body.source,
    )
    return crud.eval_case_to_dict(row)


class EvalCaseBulkIn(BaseModel):
    cases: list[dict]
    skip_duplicates: bool = True


@router.post("/eval/sets/{set_id}/cases/bulk", dependencies=[Depends(require_teacher_permission("rag_eval_case_add", staff_allowed=False))])
def add_eval_cases(
    set_id: uuid.UUID,
    body: EvalCaseBulkIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """批量导入用例：逐行校验，坏行跳过并返回行号；默认按 query 去重。"""
    if crud.get_eval_set(db, set_id) is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    if len(body.cases) > 500:
        raise HTTPException(status_code=400, detail="单次导入最多 500 条，请分批")
    existing = {
        (c.query or "").strip().lower()
        for c in crud.list_eval_cases(db, set_id)
    }
    out: list[dict] = []
    errors: list[dict] = []
    skipped = 0
    for idx, raw in enumerate(body.cases):
        try:
            c = EvalCaseIn.model_validate(raw)
        except ValidationError as exc:
            detail = "; ".join(
                f"{'.'.join(str(x) for x in err.get('loc', ())) or 'row'}: {err.get('msg', '')}"
                for err in exc.errors()
            )
            errors.append({"index": idx + 1, "error": detail or "字段校验失败"})
            continue
        key = c.query.strip().lower()
        if body.skip_duplicates and key in existing:
            skipped += 1
            continue
        row = crud.add_eval_case(
            db, set_id=set_id, query=c.query, relevant=c.relevant,
            answerability=c.answerability, split=c.split,
            business_criticality=c.business_criticality,
            gt_answer=c.gt_answer, gt_keywords=c.gt_keywords,
            query_type=c.query_type, difficulty=c.difficulty,
            notes=c.notes, source=c.source,
        )
        existing.add(key)
        out.append(crud.eval_case_to_dict(row))
    crud.add_audit(
        db, action="eval.cases.import", target=str(set_id),
        detail={
            "created": len(out),
            "failed": len(errors),
            "skipped_duplicates": skipped,
            "skip_duplicates": body.skip_duplicates,
        },
        operator_id=user.id,
    )
    return {
        "created": len(out),
        "failed": len(errors),
        "skipped_duplicates": skipped,
        "items": out,
        "errors": errors,
    }


class EvalCaseUpdateIn(BaseModel):
    query: str | None = None
    relevant: list[str] | None = None
    answerability: str | None = None
    split: str | None = None
    business_criticality: str | None = None
    gt_answer: str | None = None
    gt_keywords: list[str] | None = None
    query_type: str | None = None
    difficulty: str | None = None
    notes: str | None = None


@router.put("/eval/cases/{case_id}", dependencies=[Depends(require_teacher_permission("rag_eval_case_add", staff_allowed=False))])
def update_eval_case(
    case_id: uuid.UUID, body: EvalCaseUpdateIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    """行内编辑评测用例：补标 relevant、调整可答性/分层/关键度等。"""
    row = crud.update_eval_case(db, case_id, **body.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(status_code=404, detail="用例不存在")
    crud.add_audit(
        db, action="eval.case.update", target=str(case_id),
        detail={"fields": sorted(body.model_dump(exclude_none=True).keys())},
        operator_id=user.id,
    )
    return crud.eval_case_to_dict(row)


@router.delete("/eval/cases/{case_id}", dependencies=[Depends(require_teacher_permission("rag_eval_case_add", staff_allowed=False))])
def delete_eval_case(case_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    ok = crud.delete_eval_case(db, case_id)
    if not ok:
        raise HTTPException(status_code=404, detail="用例不存在")
    return {"ok": True}


class GenerateCasesIn(BaseModel):
    doc_ids: list[uuid.UUID] = Field(default_factory=list)
    count: int = 10
    use_llm: bool = False


@router.post("/eval/sets/{set_id}/generate", dependencies=[Depends(require_teacher_permission("rag_eval_case_add", staff_allowed=False))])
def generate_eval_cases(set_id: uuid.UUID, body: GenerateCasesIn, db: Session = Depends(get_db)) -> dict:
    es = crud.get_eval_set(db, set_id)
    if es is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    return rag_evaluation.generate_cases(
        db, set_id=set_id, doc_ids=body.doc_ids, count=max(1, min(100, body.count)),
        owner_id=es.owner_id, use_llm=body.use_llm,
    )


class TraceToCaseIn(BaseModel):
    trace_id: str
    relevant: list[str] | None = None
    answerability: str = ""
    split: str = "regression"
    business_criticality: str = "normal"
    query_type: str = "fact"
    difficulty: str = "normal"
    notes: str = ""


@router.post("/eval/sets/{set_id}/cases/from-trace", dependencies=[Depends(require_teacher_permission("rag_eval_case_add", staff_allowed=False))])
def add_eval_case_from_trace(
    set_id: uuid.UUID, body: TraceToCaseIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    """把线上真实 trace 转为评测用例：线上 Bad Case → 回归集闭环。

    不自动把当次命中标为 relevant（那会把错误结果固化成标准答案）；
    命中标题仅写入 notes 作为复核参考，标注由人工确认。
    """
    if crud.get_eval_set(db, set_id) is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    trace = crud.get_trace(db, body.trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace 不存在或已过期")
    if not (trace.query or "").strip():
        raise HTTPException(status_code=400, detail="该 trace 没有 query，无法生成用例")
    hit_titles = [str((h or {}).get("title") or "") for h in (trace.hits or [])]
    hit_titles = list(dict.fromkeys(t for t in hit_titles if t))
    status = "error" if trace.is_error else "zero_result" if trace.zero_result else "hit"
    note_parts = [
        f"来源 trace {trace.trace_id}",
        f"route={trace.route} status={status} latency={trace.latency_ms}ms",
    ]
    if trace.rewritten_query and trace.rewritten_query != trace.query:
        note_parts.append(f"改写：{trace.rewritten_query}")
    if hit_titles:
        note_parts.append("当次命中（请复核，不自动标为相关）：" + "、".join(hit_titles[:8]))
    if body.notes:
        note_parts.append(body.notes)
    row = crud.add_eval_case(
        db, set_id=set_id, query=trace.query,
        relevant=body.relevant or [],
        answerability=body.answerability,
        split=body.split, business_criticality=body.business_criticality,
        query_type=body.query_type, difficulty=body.difficulty,
        notes="；".join(note_parts),
        source=f"trace:{trace.route or 'unknown'}",
    )
    crud.add_audit(
        db, action="eval.case.from_trace", target=str(set_id),
        detail={"trace_id": trace.trace_id, "case_id": str(row.id)},
        operator_id=user.id,
    )
    return crud.eval_case_to_dict(row)


class EvalRunIn(BaseModel):
    owner_id: uuid.UUID | None = None
    top_k: int = 5
    rerank: bool = True
    retrieval_mode: str = "auto"
    answer_eval: bool = False
    generation_config_id: uuid.UUID | None = None
    judge_config_id: uuid.UUID | None = None


def _eval_model_config(db: Session, config_id: uuid.UUID | None, owner_id: uuid.UUID):
    if config_id is None:
        return None
    cfg = llm_crud.get_config(db, config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    if cfg.owner_id != owner_id:
        raise HTTPException(status_code=400, detail="模型配置不属于评测运行 owner，请切换到对应账号或先配置模型")
    return cfg


@router.post("/eval/sets/{set_id}/runs", dependencies=[Depends(require_teacher_permission("rag_eval_view", staff_allowed=False))])
def create_eval_run(set_id: uuid.UUID, body: EvalRunIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    es = crud.get_eval_set(db, set_id)
    if es is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    cases = crud.list_eval_cases(db, set_id)
    if not cases:
        raise HTTPException(status_code=400, detail="评测集为空，请先添加用例")
    owner_id = body.owner_id or es.owner_id or user.id
    gen_cfg = judge_cfg = None
    if body.answer_eval:
        gen_cfg = _eval_model_config(db, body.generation_config_id, owner_id)
        judge_cfg = _eval_model_config(db, body.judge_config_id, owner_id)
        if gen_cfg is None or judge_cfg is None:
            raise HTTPException(status_code=400, detail="答案质量评测需分别选择生成模型与评测模型")
        if gen_cfg.id == judge_cfg.id:
            raise HTTPException(status_code=400, detail="生成模型与评测模型不能是同一个配置")
        if (gen_cfg.model or "").strip().lower() == (judge_cfg.model or "").strip().lower():
            raise HTTPException(status_code=400, detail="生成模型与评测模型不能使用同一个模型")
    version = None
    try:
        versions = rag_settings.list_versions(db, limit=1)
        version = versions[0]["version"] if versions else None
    except Exception:
        version = None
    run = crud.create_eval_run(
        db, set_id=set_id, owner_id=owner_id,
        top_k=max(1, min(50, body.top_k)), rerank=body.rerank,
        retrieval_mode=(body.retrieval_mode if body.retrieval_mode in ("auto", "dense", "hybrid") else "auto"),
        answer_eval=body.answer_eval, config_version=version, created_by=user.id,
        generation_config_id=body.generation_config_id if body.answer_eval else None,
        judge_config_id=body.judge_config_id if body.answer_eval else None,
        generation_model=gen_cfg.model if gen_cfg else "",
        judge_model=judge_cfg.model if judge_cfg else "",
    )
    run.total_cases = len(cases)
    run.stage = "pending"
    db.commit()
    rag_evaluation.start_run(run.id)
    crud.add_audit(
        db, action="eval.run.start", target=str(run.id),
        detail={
            "set_id": str(set_id),
            "generation_config_id": str(body.generation_config_id) if body.answer_eval and body.generation_config_id else None,
            "judge_config_id": str(body.judge_config_id) if body.answer_eval and body.judge_config_id else None,
        },
        operator_id=user.id,
    )
    return crud.eval_run_to_dict(run)


@router.get("/eval/runs", dependencies=[Depends(require_teacher_permission("rag_eval_view", staff_allowed=False))])
def list_eval_runs(set_id: uuid.UUID | None = None, limit: int = 30, db: Session = Depends(get_db)) -> dict:
    return {"items": [crud.eval_run_to_dict(x) for x in crud.list_eval_runs(db, set_id=set_id, limit=limit)]}


@router.get("/eval/runs/{run_id}", dependencies=[Depends(require_teacher_permission("rag_eval_view", staff_allowed=False))])
def eval_run_detail(run_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    run = crud.get_eval_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评测运行不存在")
    return {
        "run": crud.eval_run_to_dict(run),
        "results": [crud.eval_result_to_dict(x) for x in crud.list_eval_results(db, run_id)],
    }


class EvalHumanScoreIn(BaseModel):
    score: int = Field(ge=0, le=5)
    judge: str = ""
    reason: str = ""


@router.post("/eval/results/{result_id}/human-score", dependencies=[Depends(require_teacher_permission("rag_eval_case_add", staff_allowed=False))])
def set_eval_result_human_score(
    result_id: uuid.UUID, body: EvalHumanScoreIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    """对单条评测结果做人工复核打分（0-5），并重算该运行的裁判-人工一致性（Kappa）。

    Kappa ≥ 0.6 且样本 ≥ 10 对时，自动评测结论才被视为可信；否则闸门判 fail。
    """
    updated = crud.update_eval_result_human_score(
        db, result_id=result_id, score=body.score,
        judge=body.judge or None, reason=body.reason or None,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="评测结果不存在")
    run_id = updated.run_id
    run = crud.get_eval_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评测运行不存在")
    calibration = rag_evaluation.recompute_run_calibration(db, run_id)
    crud.add_audit(
        db, action="eval.result.human_score", target=str(result_id),
        detail={"score": body.score, "judge": body.judge, "run_id": str(run_id),
                "kappa": calibration.get("kappa"), "pairs": calibration.get("pairs")},
        operator_id=user.id,
    )
    return {
        "result_id": str(result_id),
        "run_id": str(run_id),
        "human_score": updated.human_score,
        "calibration": calibration,
    }


__all__ = ["router"]
