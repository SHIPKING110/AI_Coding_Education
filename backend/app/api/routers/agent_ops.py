"""Agent 任务监控 API（管理员）：运行列表、时间线、意图与 RAG 决策指标。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.crud import agent_ops as crud
from app.models.agent_trace import AgentRunSpan, AgentRunTrace
from app.models.user import Role

router = APIRouter(
    prefix="/admin/agent-ops",
    tags=["agent-ops"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _run_out(run: AgentRunTrace) -> dict:
    return {
        "id": str(run.id),
        "run_id": run.run_id,
        "conversation_id": str(run.conversation_id) if run.conversation_id else None,
        "message_id": str(run.message_id) if run.message_id else None,
        "agent_id": run.agent_id,
        "user_id": str(run.user_id) if run.user_id else None,
        "domain": run.domain,
        "intent": run.intent,
        "intent_confidence": run.intent_confidence,
        "intent_source": run.intent_source,
        "needs_rag": bool(run.needs_rag),
        "rag_decision": run.rag_decision,
        "rag_skip_reason": run.rag_skip_reason,
        "retrieval_trace_id": run.retrieval_trace_id,
        "task_kind": run.task_kind,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "latency_ms": run.latency_ms,
        "first_token_ms": run.first_token_ms,
        "model_calls": run.model_calls,
        "tool_calls": run.tool_calls,
        "rag_calls": run.rag_calls,
        "mcp_calls": run.mcp_calls,
        "skill_calls": run.skill_calls,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost_estimate": run.cost_estimate,
        "ppt_target_pages": run.ppt_target_pages,
        "ppt_current_pages": run.ppt_current_pages,
        "ppt_aligned": bool(run.ppt_aligned),
        "ppt_project_key": run.ppt_project_key,
        "artifact_url": run.artifact_url,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "attributes": run.attributes or {},
        "created_at": _iso(run.created_at),
    }


def _span_out(span: AgentRunSpan) -> dict:
    return {
        "id": str(span.id),
        "run_id": span.run_id,
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
        "span_type": span.span_type,
        "name": span.name,
        "status": span.status,
        "started_at": _iso(span.started_at),
        "ended_at": _iso(span.ended_at),
        "latency_ms": span.latency_ms,
        "model": span.model,
        "provider": span.provider,
        "input_tokens": span.input_tokens,
        "output_tokens": span.output_tokens,
        "cost_estimate": span.cost_estimate,
        "summary": span.summary,
        "error": span.error,
        "attributes": span.attributes or {},
    }


@router.get("/runs")
def list_runs(
    page: int = 1,
    page_size: int = Query(20, ge=1, le=100),
    intent: str | None = None,
    task_kind: str | None = None,
    status: str | None = None,
    rag_decision: str | None = None,
    needs_rag: bool | None = None,
    ppt_aligned: bool | None = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    conv = None
    if conversation_id:
        import uuid

        try:
            conv = uuid.UUID(conversation_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="conversation_id 非法")
    result = crud.list_runs(
        db,
        page=page,
        page_size=page_size,
        intent=intent,
        task_kind=task_kind,
        status=status,
        rag_decision=rag_decision,
        needs_rag=needs_rag,
        ppt_aligned=ppt_aligned,
        agent_id=agent_id,
        conversation_id=conv,
        since=since,
    )
    return {
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "items": [_run_out(x) for x in result["items"]],
    }


@router.get("/stats")
def get_stats(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    return crud.stats(db, since=since)


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = crud.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    spans = crud.list_spans(db, run_id)
    return {"run": _run_out(run), "spans": [_span_out(s) for s in spans]}
