"""Agent 运行观测数据访问。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.agent_trace import AgentRunSpan, AgentRunTrace
from app.models.ppt_task import AgentPptTask


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


def run_usage_map(db: Session, run_ids: list[str]) -> dict[str, dict]:
    """按 run_id 汇总「Token 与成本」，供任务监控/会话观测展示。

    数据现实：AgentRunTrace 的 tokens/cost 历史上未回填（常为 0），而：
    - span 表有**真实 tokens**（按 run_id 可聚合，覆盖全）；
    - llm_usage_events 有**真实且已计价的 cost**（按 run_id 可聚合，覆盖部分）。
    因此优先用「已计价事件」同时给 tokens+cost（自洽）；无事件的 run 退回 span tokens、
    成本标记为未知（不会臆造 0）。返回 {run_id: {input_tokens, output_tokens, cost, has_cost}}。
    """
    if not run_ids:
        return {}
    from app.models.usage import LLMUsageEvent

    ids = list(dict.fromkeys(run_ids))  # 去重保序

    event_rows = db.execute(
        select(
            LLMUsageEvent.run_id,
            func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0),
            func.coalesce(func.sum(LLMUsageEvent.cost), 0.0),
            func.count(),
        )
        .where(LLMUsageEvent.run_id.in_(ids))
        .group_by(LLMUsageEvent.run_id)
    ).all()
    events = {
        rid: {"input_tokens": int(it or 0), "output_tokens": int(ot or 0), "cost": float(cost or 0.0), "has_cost": True}
        for rid, it, ot, cost, n in event_rows if n
    }

    span_rows = db.execute(
        select(
            AgentRunSpan.run_id,
            func.coalesce(func.sum(AgentRunSpan.input_tokens), 0),
            func.coalesce(func.sum(AgentRunSpan.output_tokens), 0),
        )
        .where(AgentRunSpan.run_id.in_(ids))
        .group_by(AgentRunSpan.run_id)
    ).all()
    spans = {rid: (int(it or 0), int(ot or 0)) for rid, it, ot in span_rows}

    out: dict[str, dict] = {}
    for rid in ids:
        if rid in events:
            out[rid] = events[rid]
        elif rid in spans:
            it, ot = spans[rid]
            out[rid] = {"input_tokens": it, "output_tokens": ot, "cost": None, "has_cost": False}
        else:
            out[rid] = {"input_tokens": 0, "output_tokens": 0, "cost": None, "has_cost": False}
    return out


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

    per_conv_runs = []
    all_run_ids: list[str] = []
    for conv in rows:
        runs = list(
            db.scalars(
                select(AgentRunTrace)
                .where(AgentRunTrace.conversation_id == conv.id)
                .order_by(AgentRunTrace.created_at.desc())
            ).all()
        )
        per_conv_runs.append((conv, runs))
        all_run_ids.extend(r.run_id for r in runs)
    usage = run_usage_map(db, all_run_ids)

    items = []
    for conv, runs in per_conv_runs:
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
        tok_in = sum(int((usage.get(r.run_id) or {}).get("input_tokens") or 0) for r in runs)
        tok_out = sum(int((usage.get(r.run_id) or {}).get("output_tokens") or 0) for r in runs)
        cost = sum(float((usage.get(r.run_id) or {}).get("cost") or 0.0) for r in runs)
        cost_known = any((usage.get(r.run_id) or {}).get("has_cost") for r in runs)
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
            "input_tokens": tok_in,
            "output_tokens": tok_out,
            "cost_estimate": round(cost, 6),
            "cost_known": cost_known,
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
    ppt_planned = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(
            *conds, AgentRunTrace.task_kind == "ppt", AgentRunTrace.ppt_target_pages > 0
        )
    ) or 0)
    ppt_aligned = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(
            *conds, AgentRunTrace.task_kind == "ppt",
            AgentRunTrace.ppt_current_pages > 0, AgentRunTrace.ppt_aligned.is_(True),
        )
    ) or 0)
    ppt_delivered = int(db.scalar(
        select(func.count()).select_from(AgentRunTrace).where(
            *conds, AgentRunTrace.task_kind == "ppt", AgentRunTrace.artifact_url != ""
        )
    ) or 0)
    ppt_pages_target = int(db.scalar(
        select(func.coalesce(func.sum(AgentRunTrace.ppt_target_pages), 0)).where(
            *conds, AgentRunTrace.task_kind == "ppt"
        )
    ) or 0)
    ppt_pages_current = int(db.scalar(
        select(func.coalesce(func.sum(AgentRunTrace.ppt_current_pages), 0)).where(
            *conds, AgentRunTrace.task_kind == "ppt"
        )
    ) or 0)
    # PPT 任务契约（更准确的成品口径：按任务计数，交付且页数一致）
    ppt_task_total = int(db.scalar(
        select(func.count()).select_from(AgentPptTask).where(AgentPptTask.created_at >= since)
    ) or 0)
    ppt_task_aligned = int(db.scalar(
        select(func.count()).select_from(AgentPptTask).where(
            AgentPptTask.created_at >= since,
            AgentPptTask.current_pptx_url != "",
            or_(
                AgentPptTask.target_page_count == 0,
                AgentPptTask.current_page_count == AgentPptTask.target_page_count,
            ),
        )
    ) or 0)
    ppt_task_delivered = int(db.scalar(
        select(func.count()).select_from(AgentPptTask).where(
            AgentPptTask.created_at >= since, AgentPptTask.current_pptx_url != ""
        )
    ) or 0)
    ppt_task_pages_target = int(db.scalar(
        select(func.coalesce(func.sum(AgentPptTask.target_page_count), 0)).where(AgentPptTask.created_at >= since)
    ) or 0)
    ppt_task_pages_current = int(db.scalar(
        select(func.coalesce(func.sum(AgentPptTask.current_page_count), 0)).where(AgentPptTask.created_at >= since)
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

    def _pct(values: list[int], p: float) -> int | None:
        if not values:
            return None
        vals = sorted(values)
        idx = min(len(vals) - 1, max(0, int(len(vals) * p) - 1))
        return int(vals[idx])

    def _segment(values: list[tuple[str, int, int]]) -> dict:
        """按任务类型聚合时延/首字：交互应答与长任务分开统计，避免长任务把 P95 拖高。"""
        by_kind: dict[str, dict] = {}
        for kind, latency, first_token in values:
            k = (kind or "unknown").strip() or "unknown"
            cur = by_kind.setdefault(k, {"runs": 0, "latencies": [], "first_tokens": []})
            cur["runs"] += 1
            if latency:
                cur["latencies"].append(int(latency))
            if first_token:
                cur["first_tokens"].append(int(first_token))
        out = {}
        for k, v in by_kind.items():
            lats = v["latencies"]
            fts = v["first_tokens"]
            out[k] = {
                "runs": v["runs"],
                "avg_ms": round(sum(lats) / len(lats), 1) if lats else None,
                "p50_ms": _pct(lats, 0.50),
                "p95_ms": _pct(lats, 0.95),
                "first_token_p95_ms": _pct(fts, 0.95) if fts else None,
            }
        return out

    latency_rows = db.execute(
        select(AgentRunTrace.task_kind, AgentRunTrace.latency_ms, AgentRunTrace.first_token_ms)
        .where(*conds)
    ).all()
    latency_by_kind = _segment([(k, int(lat or 0), int(ft or 0)) for k, lat, ft in latency_rows])
    interactive_kinds = ("chat", "rag_qa", "smalltalk", "knowledge_qa", "unknown")
    interactive_lats = [
        int(lat or 0) for k, lat, _ in latency_rows
        if (k or "unknown") in interactive_kinds and lat
    ]
    long_lats = [
        int(lat or 0) for k, lat, _ in latency_rows
        if (k or "unknown") not in interactive_kinds and lat
    ]
    interactive_ft = [
        int(ft or 0) for k, _, ft in latency_rows
        if (k or "unknown") in interactive_kinds and ft
    ]
    # Token/成本：run 表历史字段未回填，改从 span 聚合真实 tokens、从已计价用量事件聚合成本
    from app.models.usage import LLMUsageEvent

    run_ids_subq = select(AgentRunTrace.run_id).where(*conds)
    tokens_in = int(db.scalar(
        select(func.coalesce(func.sum(AgentRunSpan.input_tokens), 0)).where(AgentRunSpan.run_id.in_(run_ids_subq))
    ) or 0)
    tokens_out = int(db.scalar(
        select(func.coalesce(func.sum(AgentRunSpan.output_tokens), 0)).where(AgentRunSpan.run_id.in_(run_ids_subq))
    ) or 0)
    cost = float(db.scalar(
        select(func.coalesce(func.sum(LLMUsageEvent.cost), 0.0)).where(LLMUsageEvent.run_id.in_(run_ids_subq))
    ) or 0.0)
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
        "ppt_planned_runs": ppt_planned,
        "ppt_delivered": ppt_delivered,
        "ppt_aligned": ppt_aligned,
        "ppt_alignment_rate": (ppt_aligned / ppt_planned) if ppt_planned else None,
        "ppt_delivery_rate": (ppt_delivered / ppt_total) if ppt_total else None,
        "ppt_task_runs": ppt_task_total,
        "ppt_task_aligned": ppt_task_aligned,
        "ppt_task_delivered": ppt_task_delivered,
        "ppt_task_alignment_rate": (ppt_task_aligned / ppt_task_total) if ppt_task_total else None,
        "ppt_task_delivery_rate": (ppt_task_delivered / ppt_task_total) if ppt_task_total else None,
        "ppt_task_pages_target": ppt_task_pages_target,
        "ppt_task_pages_current": ppt_task_pages_current,
        "ppt_pages_target": ppt_pages_target,
        "ppt_pages_current": ppt_pages_current,
        "avg_latency_ms": float(avg_latency) if avg_latency is not None else None,
        "p95_latency_ms": float(p95) if p95 is not None else None,
        "latency_by_task": latency_by_kind,
        "interactive_latency": {
            "runs": len(interactive_lats),
            "p50_ms": _pct(interactive_lats, 0.50),
            "p95_ms": _pct(interactive_lats, 0.95),
            "first_token_p95_ms": _pct(interactive_ft, 0.95),
        },
        "long_task_latency": {
            "runs": len(long_lats),
            "p50_ms": _pct(long_lats, 0.50),
            "p95_ms": _pct(long_lats, 0.95),
        },
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
