"""RAG 运营后台 API（管理员）：总览 / 知识资产 / 追踪 / 配置 / 评测。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import SessionLocal, get_db
from app.crud import knowledge as kb_crud
from app.crud import rag_admin as crud
from app.models.knowledge import KnowledgeDocument
from app.models.user import Role, User
from app.services import agent_ops, rag_evaluation, rag_settings, rag_trace
from app.services import rag as rag_service

router = APIRouter(
    prefix="/admin/rag",
    tags=["rag-admin"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
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


@router.get("/overview")
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


@router.get("/documents")
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


@router.get("/documents/{doc_id}")
def document_detail(doc_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    doc = kb_crud.get_document_any(db, doc_id=doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    owner = db.get(User, doc.owner_id)
    out = _doc_out(doc, owner.name if owner else "")
    out["extra"] = doc.extra or {}
    return out


@router.get("/documents/{doc_id}/chunks")
def document_chunks(doc_id: uuid.UUID, limit: int = 500) -> dict:
    return {"items": rag_service.get_document_chunks(doc_id, limit=limit)}


@router.post("/documents/{doc_id}/reindex")
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


@router.post("/documents/{doc_id}/toggle")
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


@router.post("/documents/{doc_id}/parent-visible")
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


@router.delete("/documents/{doc_id}")
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


@router.get("/knowledge-bases")
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


@router.get("/collections")
def collections() -> dict:
    try:
        return rag_service.collection_stats()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取向量集合失败：{exc}")


@router.post("/collections/sweep")
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


@router.post("/maintenance/sync")
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


@router.get("/routes")
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


@router.put("/routes/{route_key}")
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


@router.post("/routes/test")
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


@router.get("/traces")
def list_traces(
    domain: str | None = None,
    owner_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    zero_only: bool = False,
    error_only: bool = False,
    rag_status: str | None = None,
    q: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
) -> dict:
    return crud.list_traces(
        db, domain=domain, owner_id=owner_id, conversation_id=conversation_id,
        zero_only=zero_only, error_only=error_only, rag_status=rag_status, q=q,
        created_from=created_from, created_to=created_to,
        page=page, page_size=page_size,
    )


@router.get("/traces/{trace_id}")
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


@router.post("/traces/{trace_id}/feedback")
def trace_feedback(trace_id: str, body: TraceFeedbackIn, db: Session = Depends(get_db)) -> dict:
    ok = crud.set_trace_feedback(db, trace_id, body.feedback)
    if not ok:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return {"ok": True}


@router.post("/maintenance/cleanup-traces")
def cleanup_traces(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    result = rag_trace.cleanup_expired()
    try:
        result["agent_runs"] = agent_ops.cleanup_expired()
    except Exception:
        result["agent_runs"] = {"deleted": 0}
    crud.add_audit(db, action="maintenance.cleanup_traces", target="trace", detail=result, operator_id=user.id)
    return result


@router.get("/parent-sessions")
def list_parent_sessions(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    risk: bool | None = None,
    days: int = 30,
    db: Session = Depends(get_db),
) -> dict:
    return crud.list_parent_sessions(db, page=page, page_size=page_size, status=status, risk=risk, days=days)


@router.get("/parent-sessions/{thread_id}")
def parent_session_detail(thread_id: str, db: Session = Depends(get_db)) -> dict:
    detail = crud.get_parent_session_detail(db, thread_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return detail


@router.get("/config")
def get_config(db: Session = Depends(get_db)) -> dict:
    return {"config": rag_settings.get_config(db, force=True), "defaults": rag_settings.DEFAULTS}


class ConfigIn(BaseModel):
    config: dict | None = None
    note: str = ""


@router.put("/config")
def update_config(body: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    result = rag_settings.update_config(db, body, operator_id=user.id)
    return result


@router.get("/config/versions")
def config_versions(db: Session = Depends(get_db)) -> dict:
    return {"items": rag_settings.list_versions(db)}


@router.post("/config/rollback/{version}")
def rollback_config(version: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    try:
        return rag_settings.rollback_config(db, version, operator_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/audit")
def audit_log(limit: int = 100, db: Session = Depends(get_db)) -> dict:
    return {"items": crud.list_audit(db, limit=limit)}


# —— 评测 ——

class EvalSetIn(BaseModel):
    name: str
    description: str = ""
    domain: str = "agent_teacher"
    owner_id: uuid.UUID | None = None


@router.get("/eval/sets")
def list_eval_sets(db: Session = Depends(get_db)) -> dict:
    return {"items": [crud.eval_set_to_dict(x) for x in crud.list_eval_sets(db)]}


@router.post("/eval/sets")
def create_eval_set(body: EvalSetIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    row = crud.create_eval_set(
        db, name=body.name, description=body.description, domain=body.domain,
        owner_id=body.owner_id, created_by=user.id,
    )
    crud.add_audit(db, action="eval.set.create", target=str(row.id), detail={"name": row.name}, operator_id=user.id)
    return crud.eval_set_to_dict(row)


@router.delete("/eval/sets/{set_id}")
def delete_eval_set(set_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ok = crud.delete_eval_set(db, set_id)
    if not ok:
        raise HTTPException(status_code=404, detail="评测集不存在")
    crud.add_audit(db, action="eval.set.delete", target=str(set_id), operator_id=user.id)
    return {"ok": True}


class EvalCaseIn(BaseModel):
    query: str
    relevant: list[str] = Field(default_factory=list)
    gt_answer: str = ""
    gt_keywords: list[str] = Field(default_factory=list)
    query_type: str = "fact"
    difficulty: str = "normal"
    notes: str = ""
    source: str = "manual"


@router.get("/eval/sets/{set_id}/cases")
def list_eval_cases(set_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    if crud.get_eval_set(db, set_id) is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    return {"items": [crud.eval_case_to_dict(x) for x in crud.list_eval_cases(db, set_id)]}


@router.post("/eval/sets/{set_id}/cases")
def add_eval_case(set_id: uuid.UUID, body: EvalCaseIn, db: Session = Depends(get_db)) -> dict:
    if crud.get_eval_set(db, set_id) is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    row = crud.add_eval_case(
        db, set_id=set_id, query=body.query, relevant=body.relevant,
        gt_answer=body.gt_answer, gt_keywords=body.gt_keywords,
        query_type=body.query_type, difficulty=body.difficulty,
        notes=body.notes, source=body.source,
    )
    return crud.eval_case_to_dict(row)


class EvalCaseBulkIn(BaseModel):
    cases: list[EvalCaseIn]


@router.post("/eval/sets/{set_id}/cases/bulk")
def add_eval_cases(set_id: uuid.UUID, body: EvalCaseBulkIn, db: Session = Depends(get_db)) -> dict:
    if crud.get_eval_set(db, set_id) is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    out = []
    for c in body.cases:
        row = crud.add_eval_case(
            db, set_id=set_id, query=c.query, relevant=c.relevant,
            gt_answer=c.gt_answer, gt_keywords=c.gt_keywords,
            query_type=c.query_type, difficulty=c.difficulty,
            notes=c.notes, source=c.source,
        )
        out.append(crud.eval_case_to_dict(row))
    return {"created": len(out), "items": out}


@router.delete("/eval/cases/{case_id}")
def delete_eval_case(case_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    ok = crud.delete_eval_case(db, case_id)
    if not ok:
        raise HTTPException(status_code=404, detail="用例不存在")
    return {"ok": True}


class GenerateCasesIn(BaseModel):
    doc_ids: list[uuid.UUID] = Field(default_factory=list)
    count: int = 10
    use_llm: bool = False


@router.post("/eval/sets/{set_id}/generate")
def generate_eval_cases(set_id: uuid.UUID, body: GenerateCasesIn, db: Session = Depends(get_db)) -> dict:
    es = crud.get_eval_set(db, set_id)
    if es is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    return rag_evaluation.generate_cases(
        db, set_id=set_id, doc_ids=body.doc_ids, count=max(1, min(100, body.count)),
        owner_id=es.owner_id, use_llm=body.use_llm,
    )


class EvalRunIn(BaseModel):
    owner_id: uuid.UUID | None = None
    top_k: int = 5
    rerank: bool = True
    answer_eval: bool = False


@router.post("/eval/sets/{set_id}/runs")
def create_eval_run(set_id: uuid.UUID, body: EvalRunIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    es = crud.get_eval_set(db, set_id)
    if es is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    cases = crud.list_eval_cases(db, set_id)
    if not cases:
        raise HTTPException(status_code=400, detail="评测集为空，请先添加用例")
    cfg = rag_settings.get_config(db)
    version = None
    try:
        versions = rag_settings.list_versions(db, limit=1)
        version = versions[0]["version"] if versions else None
    except Exception:
        version = None
    run = crud.create_eval_run(
        db, set_id=set_id, owner_id=body.owner_id or es.owner_id or user.id,
        top_k=max(1, min(50, body.top_k)), rerank=body.rerank,
        answer_eval=body.answer_eval, config_version=version, created_by=user.id,
    )
    rag_evaluation.start_run(run.id)
    crud.add_audit(db, action="eval.run.start", target=str(run.id), detail={"set_id": str(set_id)}, operator_id=user.id)
    return crud.eval_run_to_dict(run)


@router.get("/eval/runs")
def list_eval_runs(set_id: uuid.UUID | None = None, limit: int = 30, db: Session = Depends(get_db)) -> dict:
    return {"items": [crud.eval_run_to_dict(x) for x in crud.list_eval_runs(db, set_id=set_id, limit=limit)]}


@router.get("/eval/runs/{run_id}")
def eval_run_detail(run_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    run = crud.get_eval_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评测运行不存在")
    return {
        "run": crud.eval_run_to_dict(run),
        "results": [crud.eval_result_to_dict(x) for x in crud.list_eval_results(db, run_id)],
    }


__all__ = ["router"]
