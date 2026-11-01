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
    rag_status: str | None = None,
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
    if rag_status:
        if rag_status == "used":
            conds.append(AgentRunTrace.rag_decision.in_(("used", "auto")))
        elif rag_status == "skipped":
            conds.append(AgentRunTrace.rag_decision.like("skipped_%"))
        elif rag_status == "error":
            conds.append(AgentRunTrace.rag_decision == "error")
        elif rag_status == "not_needed":
            conds.append(AgentRunTrace.needs_rag.is_(False))
        elif rag_status == "needed":
            conds.append(AgentRunTrace.needs_rag.is_(True))
            conds.append(~AgentRunTrace.rag_decision.in_(("used", "auto")))
            conds.append(~AgentRunTrace.rag_decision.like("skipped_%"))
            conds.append(AgentRunTrace.rag_decision != "error")
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


def list_runs_by_trace(db: Session, trace_id: str) -> list[AgentRunTrace]:
    return list(
        db.scalars(
            select(AgentRunTrace)
            .where(AgentRunTrace.retrieval_trace_id == trace_id)
            .order_by(AgentRunTrace.created_at.asc())
        ).all()
    )


def list_sessions(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    agent_id: str | None = None,
    q: str | None = None,
    days: int = 30,
) -> dict:
    from datetime import UTC, datetime, timedelta

    from app.models.agent import AgentConversation, AgentMessage

    since = datetime.now(UTC) - timedelta(days=days)
    conds = [AgentConversation.updated_at >= since]
    if agent_id:
        conds.append(AgentConversation.agent_id == agent_id)
    if q:
        like = f"%{q.strip()}%"
        conds.append(AgentConversation.title.ilike(like))

    base = select(AgentConversation)
    count_stmt = select(func.count()).select_from(AgentConversation)
    if conds:
        base = base.where(*conds)
        count_stmt = count_stmt.where(*conds)
    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        base.order_by(AgentConversation.updated_at.desc())
        .offset(max(0, (page - 1) * page_size))
        .limit(page_size)
    ).all()

    items = []
    for conv in rows:
        runs = list(
            db.scalars(
                select(AgentRunTrace)
                .where(AgentRunTrace.conversation_id == conv.id)
                .order_by(AgentRunTrace.created_at.desc())
            ).all()
        )
        msg_count = int(db.scalar(
            select(func.count()).select_from(AgentMessage).where(AgentMessage.conversation_id == conv.id)
        ) or 0)
        ok_runs = sum(1 for r in runs if r.status == "ok")
        error_runs = sum(1 for r in runs if r.status == "error")
        needs_rag = sum(1 for r in runs if r.needs_rag)
        rag_used = sum(1 for r in runs if r.rag_decision in ("used", "auto"))
        intents = {}
        for r in runs:
            intents[r.intent or "unknown"] = intents.get(r.intent or "unknown", 0) + 1
        items.append({
            "conversation_id": str(conv.id),
            "title": conv.title,
            "agent_id": conv.agent_id,
            "owner_id": str(conv.owner_id) if conv.owner_id else None,
            "rag_enabled": bool(conv.rag_enabled),
            "stage": conv.stage,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            "message_count": msg_count,
            "run_count": len(runs),
            "ok_runs": ok_runs,
            "error_runs": error_runs,
            "needs_rag": needs_rag,
            "rag_used": rag_used,
            "intents": [{"intent": k, "runs": v} for k, v in intents.items()],
            "last_run_at": runs[0].created_at.isoformat() if runs else None,
        })
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def get_session_detail(db: Session, conversation_id) -> dict | None:
    from uuid import UUID

    from app.models.agent import AgentConversation, AgentMessage

    try:
        cid = UUID(str(conversation_id))
    except (ValueError, TypeError):
        return None
    conv = db.get(AgentConversation, cid)
    if conv is None:
        return None
    msgs = db.scalars(
        select(AgentMessage).where(AgentMessage.conversation_id == cid).order_by(AgentMessage.created_at.asc())
    ).all()
    runs = db.scalars(
        select(AgentRunTrace).where(AgentRunTrace.conversation_id == cid).order_by(AgentRunTrace.created_at.asc())
    ).all()
    run_by_message = {}
    for r in runs:
        if r.message_id:
            run_by_message[str(r.message_id)] = r.run_id
    messages = [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "run_id": run_by_message.get(str(m.id)),
        }
        for m in msgs
    ]
    return {
        "conversation": {
            "id": str(conv.id),
            "title": conv.title,
            "agent_id": conv.agent_id,
            "owner_id": str(conv.owner_id) if conv.owner_id else None,
            "rag_enabled": bool(conv.rag_enabled),
            "stage": conv.stage,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        },
        "messages": messages,
        "runs": list(runs),
    }


def _rag_status(run: AgentRunTrace) -> str:
    rd = run.rag_decision or ""
    if rd in ("used", "auto"):
        return "used"
    if rd.startswith("skipped_"):
        return "skipped"
    if rd == "error":
        return "error"
    if run.needs_rag:
        return "needed"
    return "not_needed"


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
    # RAG 状态计数（run 层）
    used_runs = rag_used
    skipped_runs = rag_skipped
    error_runs_rag = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(*conds, AgentRunTrace.rag_decision == "error")
    ) or 0)
    not_needed_runs = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(*conds, AgentRunTrace.needs_rag.is_(False))
    ) or 0)
    needed_runs = max(0, needs_rag - used_runs - skipped_runs - error_runs_rag)

    # 组件协同
    tool_runs = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(*conds, AgentRunTrace.tool_calls > 0)
    ) or 0)
    skill_runs = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(*conds, AgentRunTrace.skill_calls > 0)
    ) or 0)
    mcp_runs = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(*conds, AgentRunTrace.mcp_calls > 0)
    ) or 0)
    pure_rag = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(
            *conds, AgentRunTrace.rag_decision.in_(("used", "auto")),
            AgentRunTrace.tool_calls == 0, AgentRunTrace.skill_calls == 0, AgentRunTrace.mcp_calls == 0,
        )
    ) or 0)
    pure_tool = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(
            *conds, ~AgentRunTrace.rag_decision.in_(("used", "auto")),
            (AgentRunTrace.tool_calls > 0) | (AgentRunTrace.skill_calls > 0) | (AgentRunTrace.mcp_calls > 0),
        )
    ) or 0)
    rag_plus_tool = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(
            *conds, AgentRunTrace.rag_decision.in_(("used", "auto")), AgentRunTrace.tool_calls > 0,
        )
    ) or 0)

    # 任务类型分布
    task_rows = db.execute(
        select(AgentRunTrace.task_kind, func.count()).where(*conds).group_by(AgentRunTrace.task_kind)
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
        "rag_status_counts": {
            "used": used_runs,
            "skipped": skipped_runs,
            "error": error_runs_rag,
            "needed": needed_runs,
            "not_needed": not_needed_runs,
        },
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
        "task_kinds": [{"task_kind": k or "unknown", "runs": int(v or 0)} for k, v in task_rows],
        "component_synergy": {
            "rag_used": rag_used,
            "tool_runs": tool_runs,
            "skill_runs": skill_runs,
            "mcp_runs": mcp_runs,
            "pure_rag": pure_rag,
            "pure_tool": pure_tool,
            "rag_plus_tool": rag_plus_tool,
        },
    }


__all__ = ["list_runs", "get_run", "list_spans", "list_runs_by_trace", "list_sessions", "get_session_detail", "stats"]
