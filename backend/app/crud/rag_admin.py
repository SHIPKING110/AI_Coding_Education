"""RAG 运营后台 CRUD：trace / 审计 / 评测。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.rag_admin import (
    RagAdminAudit,
    RagEvalCase,
    RagEvalResult,
    RagEvalRun,
    RagEvalSet,
    RagRetrievalTrace,
)


def add_audit(
    db: Session, *, action: str, target: str = "", detail: dict | None = None, operator_id=None
) -> None:
    db.add(RagAdminAudit(action=action, target=target, detail=detail or {}, operator_id=operator_id))
    db.commit()


def list_audit(db: Session, *, limit: int = 100) -> list[dict]:
    rows = db.scalars(select(RagAdminAudit).order_by(desc(RagAdminAudit.created_at)).limit(limit)).all()
    return [
        {
            "id": str(r.id), "action": r.action, "target": r.target,
            "detail": r.detail, "operator_id": str(r.operator_id) if r.operator_id else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def _rag_status(r: RagRetrievalTrace) -> str:
    if r.is_error:
        return "error"
    if r.zero_result:
        return "no_hit"
    return "hit"


def trace_to_dict(r: RagRetrievalTrace) -> dict:
    return {
        "id": str(r.id),
        "trace_id": r.trace_id,
        "domain": r.domain,
        "user_id": str(r.user_id) if r.user_id else None,
        "owner_id": str(r.owner_id) if r.owner_id else None,
        "conversation_id": str(r.conversation_id) if r.conversation_id else None,
        "message_id": str(r.message_id) if r.message_id else None,
        "route": r.route,
        "query": r.query,
        "rewritten_query": r.rewritten_query,
        "filters": r.filters,
        "embedding_fingerprint": r.embedding_fingerprint,
        "vector_candidates": r.vector_candidates,
        "keyword_candidates": r.keyword_candidates,
        "rerank_candidates": r.rerank_candidates,
        "gated_out": r.gated_out,
        "vector_ok": r.vector_ok,
        "keyword_used": r.keyword_used,
        "rerank_ok": r.rerank_ok,
        "rerank_model": r.rerank_model,
        "zero_result": r.zero_result,
        "is_error": r.is_error,
        "rag_status": _rag_status(r),
        "error": r.error,
        "latency_ms": r.latency_ms,
        "stage_timings": r.stage_timings,
        "hits": r.hits,
        "feedback": r.feedback,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def list_traces(
    db: Session, *, domain: str | None = None, owner_id=None, conversation_id=None,
    zero_only: bool = False, error_only: bool = False, rag_status: str | None = None,
    feedback: str | None = None, q: str | None = None,
    created_from: datetime | None = None, created_to: datetime | None = None,
    page: int = 1, page_size: int = 20,
) -> dict:
    conds = []
    if domain:
        conds.append(RagRetrievalTrace.domain == domain)
    if owner_id:
        conds.append(RagRetrievalTrace.owner_id == owner_id)
    if conversation_id:
        conds.append(RagRetrievalTrace.conversation_id == conversation_id)
    if feedback:
        # "none" = 未反馈；"up"/"down" = 赞/踩（发现 Bad Case 的主要入口）
        if feedback == "none":
            conds.append(RagRetrievalTrace.feedback.is_(None))
        elif feedback in ("up", "down"):
            conds.append(RagRetrievalTrace.feedback == feedback)
    if rag_status:
        if rag_status == "error":
            conds.append(RagRetrievalTrace.is_error.is_(True))
        elif rag_status == "no_hit":
            conds.append(RagRetrievalTrace.zero_result.is_(True))
            conds.append(RagRetrievalTrace.is_error.is_(False))
        elif rag_status == "hit":
            conds.append(RagRetrievalTrace.zero_result.is_(False))
            conds.append(RagRetrievalTrace.is_error.is_(False))
    elif zero_only:
        conds.append(RagRetrievalTrace.zero_result.is_(True))
    if error_only:
        conds.append(RagRetrievalTrace.is_error.is_(True))
    if q:
        like = f"%{q}%"
        conds.append(or_(RagRetrievalTrace.query.ilike(like), RagRetrievalTrace.rewritten_query.ilike(like)))
    if created_from:
        conds.append(RagRetrievalTrace.created_at >= created_from)
    if created_to:
        conds.append(RagRetrievalTrace.created_at <= created_to)
    base = select(RagRetrievalTrace)
    count_stmt = select(func.count()).select_from(RagRetrievalTrace)
    if conds:
        base = base.where(*conds)
        count_stmt = count_stmt.where(*conds)
    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        base.order_by(desc(RagRetrievalTrace.created_at))
        .offset(max(0, (page - 1) * page_size))
        .limit(page_size)
    ).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [trace_to_dict(r) for r in rows]}


def get_trace(db: Session, trace_id: str) -> RagRetrievalTrace | None:
    return db.scalars(select(RagRetrievalTrace).where(RagRetrievalTrace.trace_id == trace_id)).first()


def set_trace_feedback(db: Session, trace_id: str, feedback: str) -> bool:
    row = get_trace(db, trace_id)
    if row is None:
        return False
    row.feedback = feedback[:16] if feedback else None
    db.commit()
    return True


def trace_stats(db: Session, *, since: datetime) -> dict:
    total = int(db.scalar(
        select(func.count()).select_from(RagRetrievalTrace).where(RagRetrievalTrace.created_at >= since)
    ) or 0)
    zero = int(db.scalar(
        select(func.count()).select_from(RagRetrievalTrace).where(
            RagRetrievalTrace.created_at >= since, RagRetrievalTrace.zero_result.is_(True)
        )
    ) or 0)
    errors = int(db.scalar(
        select(func.count()).select_from(RagRetrievalTrace).where(
            RagRetrievalTrace.created_at >= since, RagRetrievalTrace.is_error.is_(True)
        )
    ) or 0)
    avg_latency = db.scalar(
        select(func.avg(RagRetrievalTrace.latency_ms)).where(RagRetrievalTrace.created_at >= since)
    )
    vector_fail = int(db.scalar(
        select(func.count()).select_from(RagRetrievalTrace).where(
            RagRetrievalTrace.created_at >= since, RagRetrievalTrace.vector_ok.is_(False)
        )
    ) or 0)
    keyword = int(db.scalar(
        select(func.count()).select_from(RagRetrievalTrace).where(
            RagRetrievalTrace.created_at >= since, RagRetrievalTrace.keyword_used.is_(True)
        )
    ) or 0)
    rerank_fail = int(db.scalar(
        select(func.count()).select_from(RagRetrievalTrace).where(
            RagRetrievalTrace.created_at >= since,
            RagRetrievalTrace.rerank_ok.is_(False),
            RagRetrievalTrace.rerank_candidates > 0,
        )
    ) or 0)
    feedback_up = int(db.scalar(
        select(func.count()).select_from(RagRetrievalTrace).where(
            RagRetrievalTrace.created_at >= since, RagRetrievalTrace.feedback == "up"
        )
    ) or 0)
    feedback_down = int(db.scalar(
        select(func.count()).select_from(RagRetrievalTrace).where(
            RagRetrievalTrace.created_at >= since, RagRetrievalTrace.feedback == "down"
        )
    ) or 0)
    hit = max(0, total - zero - errors)
    rows = db.execute(
        select(
            RagRetrievalTrace.latency_ms,
            RagRetrievalTrace.vector_candidates,
            RagRetrievalTrace.keyword_candidates,
            RagRetrievalTrace.rerank_candidates,
            RagRetrievalTrace.rerank_ok,
        ).where(RagRetrievalTrace.created_at >= since)
    ).all()

    def _pct(values: list[int], p: float) -> int | None:
        if not values:
            return None
        vals = sorted(values)
        idx = min(len(vals) - 1, max(0, int(len(vals) * p) - 1))
        return int(vals[idx])

    latencies = [int(r[0] or 0) for r in rows if r[0]]
    candidates = [int(r[1] or 0) + int(r[2] or 0) for r in rows]
    rerank_attempts = sum(1 for r in rows if int(r[3] or 0) > 0)
    rerank_ok = sum(1 for r in rows if bool(r[4]))
    return {
        "queries": total,
        "zero_results": zero,
        "errors": errors,
        "hits": hit,
        "hit_rate": round((total - zero) / total, 4) if total else None,
        "hit_rate_excl_errors": round(hit / max(0, total - errors), 4) if total - errors > 0 else None,
        "zero_result_rate": round(zero / total, 4) if total else None,
        "error_rate": round(errors / total, 4) if total else None,
        "avg_latency_ms": round(float(avg_latency), 2) if avg_latency is not None else None,
        "p95_latency_ms": _pct(latencies, 0.95),
        "avg_candidates": round(sum(candidates) / len(candidates), 1) if candidates else None,
        "vector_fail": vector_fail,
        "vector_success_rate": round((total - vector_fail) / total, 4) if total else None,
        "keyword_used": keyword,
        "keyword_rate": round(keyword / total, 4) if total else None,
        "rerank_fail": rerank_fail,
        "rerank_attempts": rerank_attempts,
        "rerank_success_rate": round(rerank_ok / rerank_attempts, 4) if rerank_attempts else None,
        "feedback_up": feedback_up,
        "feedback_down": feedback_down,
        "rag_status_counts": {
            "hit": hit,
            "no_hit": zero,
            "error": errors,
        },
    }


def trace_domain_stats(db: Session, *, since: datetime) -> list[dict]:
    rows = db.execute(
        select(
            RagRetrievalTrace.domain,
            func.count().label("queries"),
            func.sum(case((RagRetrievalTrace.zero_result.is_(True), 1), else_=0)).label("zero_results"),
            func.avg(RagRetrievalTrace.latency_ms).label("avg_latency"),
        )
        .where(RagRetrievalTrace.created_at >= since)
        .group_by(RagRetrievalTrace.domain)
    ).all()
    out = []
    for domain, queries, zero, avg_latency in rows:
        queries = int(queries or 0)
        zero = int(zero or 0)
        out.append({
            "domain": domain or "unknown",
            "queries": queries,
            "zero_results": zero,
            "zero_result_rate": round(zero / queries, 4) if queries else None,
            "avg_latency_ms": round(float(avg_latency), 2) if avg_latency is not None else None,
        })
    return out


# —— 评测 ——

def eval_set_to_dict(r: RagEvalSet) -> dict:
    return {
        "id": str(r.id), "name": r.name, "description": r.description, "domain": r.domain,
        "owner_id": str(r.owner_id) if r.owner_id else None,
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def eval_case_to_dict(r: RagEvalCase) -> dict:
    return {
        "id": str(r.id), "set_id": str(r.set_id), "query": r.query,
        "relevant": r.relevant or [], "answerability": r.answerability or "unlabeled",
        "split": r.split or "regression", "business_criticality": r.business_criticality or "normal",
        "gt_answer": r.gt_answer, "gt_keywords": r.gt_keywords or [],
        "query_type": r.query_type, "difficulty": r.difficulty,
        "notes": r.notes, "source": r.source,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def eval_run_to_dict(r: RagEvalRun) -> dict:
    return {
        "id": str(r.id), "set_id": str(r.set_id), "status": r.status,
        "total_cases": r.total_cases, "processed_cases": r.processed_cases,
        "stage": r.stage or "", "progress": r.progress,
        "owner_id": str(r.owner_id) if r.owner_id else None,
        "top_k": r.top_k, "rerank": r.rerank,
        "retrieval_mode": r.retrieval_mode or "auto",
        "answer_eval": bool(r.answer_eval),
        "generation_config_id": str(r.generation_config_id) if r.generation_config_id else None,
        "judge_config_id": str(r.judge_config_id) if r.judge_config_id else None,
        "generation_model": r.generation_model or "",
        "judge_model": r.judge_model or "",
        "config_version": r.config_version,
        "eval_snapshot": r.eval_snapshot,
        "metrics": r.metrics, "compare": r.compare, "error": r.error,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


def eval_result_to_dict(r: RagEvalResult) -> dict:
    return {
        "id": str(r.id), "run_id": str(r.run_id), "case_id": str(r.case_id) if r.case_id else None,
        "query": r.query, "ranked": r.ranked or [], "relevant": r.relevant or [],
        "hits": r.hits or [], "metrics": r.metrics, "retrieval_summary": r.retrieval_summary,
        "bad_case_type": r.bad_case_type,
        "human_score": r.human_score,
        "human_judge": r.human_judge,
        "human_at": r.human_at.isoformat() if r.human_at else None,
        "human_reason": r.human_reason,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def list_eval_sets(db: Session) -> list[RagEvalSet]:
    return list(db.scalars(select(RagEvalSet).order_by(desc(RagEvalSet.updated_at))).all())


def get_eval_set(db: Session, set_id) -> RagEvalSet | None:
    return db.get(RagEvalSet, set_id)


def create_eval_set(db: Session, *, name: str, description: str, domain: str, owner_id, created_by) -> RagEvalSet:
    row = RagEvalSet(name=name.strip() or "未命名评测集", description=description or "", domain=domain or "agent_teacher", owner_id=owner_id, created_by=created_by)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_eval_set(db: Session, set_id) -> bool:
    row = get_eval_set(db, set_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def list_eval_cases(db: Session, set_id, *, offset: int | None = None, limit: int | None = None) -> list[RagEvalCase]:
    stmt = (
        select(RagEvalCase)
        .where(RagEvalCase.set_id == set_id)
        .order_by(RagEvalCase.created_at, RagEvalCase.id)
    )
    if offset is not None:
        stmt = stmt.offset(max(0, offset))
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    return list(db.scalars(stmt).all())


def count_eval_cases(db: Session, set_id) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(RagEvalCase).where(RagEvalCase.set_id == set_id)
        )
        or 0
    )


_ANSWERABILITY_VALUES = ("answerable", "unanswerable", "unlabeled")
_SPLIT_VALUES = ("tuning", "regression", "frozen")
_CRITICALITY_VALUES = ("critical", "important", "normal")


def _norm_enum(value, allowed: tuple[str, ...], default: str) -> str:
    v = str(value or "").strip().lower()
    return v if v in allowed else default


def normalize_answerability(value, relevant: list | None = None) -> str:
    """可答性归一：未声明时按是否有 relevant 推导，避免脏值进库。"""
    v = str(value or "").strip().lower()
    if v in _ANSWERABILITY_VALUES:
        return v
    return "answerable" if (relevant or []) else "unlabeled"


def add_eval_case(
    db: Session, *, set_id, query: str, relevant: list | None = None,
    answerability: str = "", split: str = "regression",
    business_criticality: str = "normal",
    gt_answer: str = "", gt_keywords: list | None = None,
    query_type: str = "fact", difficulty: str = "normal",
    notes: str = "", source: str = "manual",
) -> RagEvalCase:
    row = RagEvalCase(
        set_id=set_id, query=query.strip(), relevant=relevant or [],
        answerability=normalize_answerability(answerability, relevant),
        split=_norm_enum(split, _SPLIT_VALUES, "regression"),
        business_criticality=_norm_enum(business_criticality, _CRITICALITY_VALUES, "normal"),
        gt_answer=gt_answer or "", gt_keywords=gt_keywords or [],
        query_type=query_type or "fact", difficulty=difficulty or "normal",
        notes=notes or "", source=source or "manual",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_eval_case(
    db: Session, case_id, *,
    query: str | None = None,
    relevant: list | None = None,
    answerability: str | None = None,
    split: str | None = None,
    business_criticality: str | None = None,
    gt_answer: str | None = None,
    gt_keywords: list | None = None,
    query_type: str | None = None,
    difficulty: str | None = None,
    notes: str | None = None,
) -> RagEvalCase | None:
    """行内编辑用例：只改传入字段；relevant 变化且未显式给可答性时按标注重新推导。"""
    row = db.get(RagEvalCase, case_id)
    if row is None:
        return None
    if query is not None and query.strip():
        row.query = query.strip()
    if relevant is not None:
        row.relevant = relevant
    if answerability is not None:
        row.answerability = normalize_answerability(answerability, row.relevant)
    elif relevant is not None:
        # 未显式给可答性时按最新标注推导，避免「不可答 + 有 relevant」的矛盾数据
        row.answerability = normalize_answerability("", row.relevant)
    if split is not None:
        row.split = _norm_enum(split, _SPLIT_VALUES, row.split or "regression")
    if business_criticality is not None:
        row.business_criticality = _norm_enum(
            business_criticality, _CRITICALITY_VALUES, row.business_criticality or "normal"
        )
    if gt_answer is not None:
        row.gt_answer = gt_answer
    if gt_keywords is not None:
        row.gt_keywords = gt_keywords
    if query_type is not None:
        row.query_type = query_type or row.query_type
    if difficulty is not None:
        row.difficulty = difficulty or row.difficulty
    if notes is not None:
        row.notes = notes
    db.commit()
    db.refresh(row)
    return row


def delete_eval_case(db: Session, case_id) -> bool:
    row = db.get(RagEvalCase, case_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def create_eval_run(
    db: Session, *, set_id, owner_id, top_k: int, rerank: bool,
    answer_eval: bool = False, config_version: int | None, created_by,
    generation_config_id=None, judge_config_id=None,
    generation_model: str = "", judge_model: str = "",
    retrieval_mode: str = "auto",
) -> RagEvalRun:
    row = RagEvalRun(
        set_id=set_id, owner_id=owner_id, top_k=top_k, rerank=rerank,
        retrieval_mode=retrieval_mode or "auto",
        answer_eval=answer_eval, config_version=config_version, status="pending", created_by=created_by,
        generation_config_id=generation_config_id, judge_config_id=judge_config_id,
        generation_model=generation_model or "", judge_model=judge_model or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_eval_run(db: Session, run_id) -> RagEvalRun | None:
    return db.get(RagEvalRun, run_id)


def list_eval_runs(db: Session, *, set_id=None, limit: int = 30) -> list[RagEvalRun]:
    stmt = select(RagEvalRun).order_by(desc(RagEvalRun.created_at)).limit(limit)
    if set_id:
        stmt = stmt.where(RagEvalRun.set_id == set_id)
    return list(db.scalars(stmt).all())


def previous_done_run(db: Session, set_id, exclude_id) -> RagEvalRun | None:
    """同一评测集最近一次成功的运行：用于验收闸门的前后对比。"""
    stmt = (
        select(RagEvalRun)
        .where(
            RagEvalRun.set_id == set_id,
            RagEvalRun.status == "done",
            RagEvalRun.id != exclude_id,
        )
        .order_by(desc(RagEvalRun.created_at))
        .limit(1)
    )
    return db.scalars(stmt).first()


def list_eval_results(db: Session, run_id) -> list[RagEvalResult]:
    return list(db.scalars(
        select(RagEvalResult).where(RagEvalResult.run_id == run_id).order_by(RagEvalResult.created_at)
    ).all())


def delete_eval_run(db: Session, run_id) -> bool:
    row = get_eval_run(db, run_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def update_eval_result_human_score(
    db: Session, *, result_id, score: int | None, judge: str | None = None,
    reason: str | None = None,
) -> RagEvalResult | None:
    """人工复核打分：0-5 分，与 LLM Judge 的 0-5 维度计算 Cohen's Kappa。"""
    from datetime import UTC, datetime

    row = db.get(RagEvalResult, result_id)
    if row is None:
        return None
    if score is not None:
        row.human_score = max(0, min(5, int(score)))
    if judge is not None:
        row.human_judge = judge.strip() or None
    row.human_at = datetime.now(UTC)
    if reason is not None:
        row.human_reason = reason.strip() or None
    db.commit()
    db.refresh(row)
    return row


def list_parent_sessions(
    db: Session, *, page: int = 1, page_size: int = 20, status: str | None = None, risk: bool | None = None, days: int = 30,
) -> dict:
    from datetime import UTC, datetime, timedelta

    from app.models.parent_service import ParentServiceMessage, ParentServiceThread

    since = datetime.now(UTC) - timedelta(days=days)
    conds = [ParentServiceThread.updated_at >= since]
    if status:
        conds.append(ParentServiceThread.status == status)
    if risk is not None:
        conds.append(ParentServiceThread.risk_flag.is_(risk))
    base = select(ParentServiceThread)
    count_stmt = select(func.count()).select_from(ParentServiceThread)
    if conds:
        base = base.where(*conds)
        count_stmt = count_stmt.where(*conds)
    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        base.order_by(ParentServiceThread.updated_at.desc())
        .offset(max(0, (page - 1) * page_size))
        .limit(page_size)
    ).all()
    items = []
    for th in rows:
        msg_count = int(db.scalar(
            select(func.count()).select_from(ParentServiceMessage).where(ParentServiceMessage.thread_id == th.id)
        ) or 0)
        trace_count = int(db.scalar(
            select(func.count()).select_from(RagRetrievalTrace).where(
                RagRetrievalTrace.conversation_id == th.id,
                RagRetrievalTrace.domain == "parent_service",
            )
        ) or 0)
        items.append({
            "thread_id": str(th.id),
            "parent_id": str(th.parent_id) if th.parent_id else None,
            "status": th.status,
            "risk_flag": bool(th.risk_flag),
            "owner_teacher_id": str(th.owner_teacher_id) if th.owner_teacher_id else None,
            "created_at": th.created_at.isoformat() if th.created_at else None,
            "updated_at": th.updated_at.isoformat() if th.updated_at else None,
            "message_count": msg_count,
            "trace_count": trace_count,
        })
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def get_parent_session_detail(db: Session, thread_id) -> dict | None:
    from uuid import UUID

    from app.models.parent_service import ParentServiceMessage, ParentServiceThread

    try:
        tid = UUID(str(thread_id))
    except (ValueError, TypeError):
        return None
    th = db.get(ParentServiceThread, tid)
    if th is None:
        return None
    msgs = db.scalars(
        select(ParentServiceMessage).where(ParentServiceMessage.thread_id == tid).order_by(ParentServiceMessage.created_at.asc())
    ).all()
    traces = db.scalars(
        select(RagRetrievalTrace).where(
            RagRetrievalTrace.conversation_id == tid,
            RagRetrievalTrace.domain == "parent_service",
        ).order_by(RagRetrievalTrace.created_at.asc())
    ).all()
    return {
        "thread": {
            "id": str(th.id),
            "parent_id": str(th.parent_id) if th.parent_id else None,
            "status": th.status,
            "risk_flag": bool(th.risk_flag),
            "owner_teacher_id": str(th.owner_teacher_id) if th.owner_teacher_id else None,
            "created_at": th.created_at.isoformat() if th.created_at else None,
            "updated_at": th.updated_at.isoformat() if th.updated_at else None,
        },
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "tokens": m.tokens,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "retrieval_diag": m.retrieval_diag,
            }
            for m in msgs
        ],
        "traces": [trace_to_dict(t) for t in traces],
    }


__all__ = [name for name in globals() if not name.startswith("_")]
