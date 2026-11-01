"""Agent 运行观测数据访问。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent_trace import AgentRunSpan, AgentRunTrace


def list_runs(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    intent: str | None = None,
    task_kind: str | None = None,
    status: str | None = None,
    rag_decision: str | None = None,
    needs_rag: bool | None = None,
    ppt_aligned: bool | None = None,
    agent_id: str | None = None,
    conversation_id=None,
    since: datetime | None = None,
) -> dict:
    conds = []
    if intent:
        conds.append(AgentRunTrace.intent == intent)
    if task_kind:
        conds.append(AgentRunTrace.task_kind == task_kind)
    if status:
        conds.append(AgentRunTrace.status == status)
    if rag_decision:
        conds.append(AgentRunTrace.rag_decision == rag_decision)
    if needs_rag is not None:
        conds.append(AgentRunTrace.needs_rag.is_(needs_rag))
    if ppt_aligned is not None:
        conds.append(AgentRunTrace.ppt_aligned.is_(ppt_aligned))
    if agent_id:
        conds.append(AgentRunTrace.agent_id == agent_id)
    if conversation_id:
        conds.append(AgentRunTrace.conversation_id == conversation_id)
    if since:
        conds.append(AgentRunTrace.created_at >= since)
    base = select(AgentRunTrace)
    count_stmt = select(func.count()).select_from(AgentRunTrace)
    if conds:
        base = base.where(*conds)
        count_stmt = count_stmt.where(*conds)
    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        base.order_by(AgentRunTrace.created_at.desc())
        .offset(max(0, (page - 1) * page_size))
        .limit(page_size)
    ).all()
    return {"total": total, "page": page, "page_size": page_size, "items": list(rows)}


def get_run(db: Session, run_id: str) -> AgentRunTrace | None:
    return db.scalar(select(AgentRunTrace).where(AgentRunTrace.run_id == run_id))


def list_spans(db: Session, run_id: str) -> list[AgentRunSpan]:
    return list(
        db.scalars(
            select(AgentRunSpan)
            .where(AgentRunSpan.run_id == run_id)
            .order_by(AgentRunSpan.started_at.asc(), AgentRunSpan.created_at.asc())
        ).all()
    )


def stats(db: Session, *, since: datetime) -> dict:
    conds = [AgentRunTrace.created_at >= since]
    total = int(db.scalar(select(func.count()).select_from(AgentRunTrace).where(*conds)) or 0)
    ok = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(*conds, AgentRunTrace.status == "ok")
    ) or 0)
    error = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(*conds, AgentRunTrace.status == "error")
    ) or 0)
    needs_rag = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(*conds, AgentRunTrace.needs_rag.is_(True))
    ) or 0)
    rag_used = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(
            *conds, AgentRunTrace.rag_decision.in_(("used", "auto"))
        )
    ) or 0)
    rag_skipped = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(
            *conds, AgentRunTrace.rag_decision.like("skipped_%")
        )
    ) or 0)
    rag_missed = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(
            *conds,
            AgentRunTrace.needs_rag.is_(True),
            AgentRunTrace.rag_decision.like("skipped_%"),
        )
    ) or 0)
    ppt_total = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(*conds, AgentRunTrace.task_kind == "ppt")
    ) or 0)
    ppt_aligned = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(
            *conds, AgentRunTrace.task_kind == "ppt", AgentRunTrace.ppt_aligned.is_(True)
        )
    ) or 0)
    avg_latency = db.scalar(select(func.avg(AgentRunTrace.latency_ms)).where(*conds))
    p95 = None
    if total:
        offset = max(0, int(total * 0.95) - 1)
        p95 = db.scalar(
            select(AgentRunTrace.latency_ms)
            .where(*conds)
            .order_by(AgentRunTrace.latency_ms.asc())
            .offset(offset)
            .limit(1)
        )
    tokens_in = int(db.scalar(select(func.coalesce(func.sum(AgentRunTrace.input_tokens), 0)).where(*conds)) or 0)
    tokens_out = int(db.scalar(select(func.coalesce(func.sum(AgentRunTrace.output_tokens), 0)).where(*conds)) or 0)
    cost = float(db.scalar(select(func.coalesce(func.sum(AgentRunTrace.cost_estimate), 0)).where(*conds)) or 0)
    intents = db.execute(
        select(AgentRunTrace.intent, func.count())
        .where(*conds)
        .group_by(AgentRunTrace.intent)
    ).all()
    decisions = db.execute(
        select(AgentRunTrace.rag_decision, func.count())
        .where(*conds)
        .group_by(AgentRunTrace.rag_decision)
    ).all()
    return {
        "total_runs": total,
        "ok_runs": ok,
        "error_runs": error,
        "success_rate": (ok / total) if total else None,
        "needs_rag": needs_rag,
        "rag_used": rag_used,
        "rag_skipped": rag_skipped,
        "rag_missed": rag_missed,
        "rag_miss_rate": (rag_missed / needs_rag) if needs_rag else None,
        "ppt_runs": ppt_total,
        "ppt_aligned": ppt_aligned,
        "ppt_alignment_rate": (ppt_aligned / ppt_total) if ppt_total else None,
        "avg_latency_ms": float(avg_latency) if avg_latency is not None else None,
        "p95_latency_ms": float(p95) if p95 is not None else None,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cost_estimate": cost,
        "intents": [{"intent": k or "unknown", "runs": int(v or 0)} for k, v in intents],
        "rag_decisions": [{"decision": k or "unknown", "runs": int(v or 0)} for k, v in decisions],
    }


__all__ = ["list_runs", "get_run", "list_spans", "stats"]
