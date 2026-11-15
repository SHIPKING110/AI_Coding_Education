"""Agent 任务全链路观测：run / span 异步写入与上下文。

使用方式：
    run_id = agent_ops.start_run(conversation_id=..., user_id=..., intent=...)
    with agent_ops.run_scope(run_id):
        with agent_ops.span(span_type="rag", name="retrieve") as sp:
            ...
            sp.summary = "命中 3 篇"
    agent_ops.finish_run(run_id, status="ok", latency_ms=...)

约束：观测写入走后台队列，任何异常只记日志，不影响主对话。
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import queue
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

_QUEUE: queue.Queue = queue.Queue(maxsize=5000)
_WORKER: threading.Thread | None = None
_WORKER_LOCK = threading.Lock()
_SESSION_FACTORY = None
_CURRENT_RUN: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent_run_id", default=None
)


def new_run_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex


def _enabled() -> bool:
    try:
        from app.core.config import get_settings

        return bool(get_settings().AGENT_RUN_TRACE_ENABLED)
    except Exception:
        return True


def _sample_out() -> bool:
    try:
        from app.core.config import get_settings

        rate = float(get_settings().AGENT_RUN_TRACE_SAMPLE_RATE)
    except Exception:
        rate = 1.0
    return random.random() > max(0.0, min(1.0, rate))


def _session_factory():
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        from app.core.database import SessionLocal

        _SESSION_FACTORY = SessionLocal
    return _SESSION_FACTORY


def _ensure_worker() -> None:
    global _WORKER
    if _WORKER is not None and _WORKER.is_alive():
        return
    with _WORKER_LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return
        _WORKER = threading.Thread(target=_worker_loop, name="agent-ops-writer", daemon=True)
        _WORKER.start()


def _worker_loop() -> None:
    while True:
        item = _QUEUE.get()
        try:
            kind, payload = item
            if kind == "run_insert":
                _insert_run(payload)
            elif kind == "run_update":
                _update_run(payload)
            elif kind == "span_insert":
                _insert_span(payload)
        except Exception:  # noqa: BLE001
            logger.exception("agent ops write failed")
        finally:
            try:
                _QUEUE.task_done()
            except Exception:
                pass


def _insert_run(payload: dict) -> None:
    from app.models.agent_trace import AgentRunTrace

    db = _session_factory()()
    try:
        db.add(AgentRunTrace(**payload))
        db.commit()
    finally:
        db.close()


def _update_run(payload: dict) -> None:
    from sqlalchemy import update

    from app.models.agent_trace import AgentRunTrace

    run_id = payload.pop("run_id")
    db = _session_factory()()
    try:
        db.execute(update(AgentRunTrace).where(AgentRunTrace.run_id == run_id).values(**payload))
        db.commit()
    finally:
        db.close()


def _insert_span(payload: dict) -> None:
    from app.models.agent_trace import AgentRunSpan

    db = _session_factory()()
    try:
        db.add(AgentRunSpan(**payload))
        db.commit()
    finally:
        db.close()


def _put(kind: str, payload: dict) -> None:
    _ensure_worker()
    try:
        _QUEUE.put_nowait((kind, payload))
    except queue.Full:
        logger.warning("agent ops queue full, drop %s", kind)


def start_run(
    *,
    conversation_id=None,
    message_id=None,
    agent_id: str = "",
    user_id=None,
    owner_id=None,
    domain: str = "agent_teacher",
    intent: str = "unknown",
    intent_confidence: float = 0.0,
    intent_source: str = "rule",
    needs_rag: bool = False,
    rag_decision: str = "not_applicable",
    rag_skip_reason: str = "",
    task_kind: str = "chat",
    attributes: dict | None = None,
) -> str:
    run_id = new_run_id()
    if not _enabled() or _sample_out():
        return run_id
    _put("run_insert", {
        "run_id": run_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "agent_id": agent_id or "",
        "user_id": user_id,
        "owner_id": owner_id or user_id,
        "domain": domain or "agent_teacher",
        "intent": intent or "unknown",
        "intent_confidence": float(intent_confidence or 0.0),
        "intent_source": intent_source or "rule",
        "needs_rag": bool(needs_rag),
        "rag_decision": rag_decision or "not_applicable",
        "rag_skip_reason": (rag_skip_reason or "")[:128],
        "task_kind": task_kind or "chat",
        "status": "running",
        "attributes": attributes or {},
    })
    return run_id


def finish_run(run_id: str | None, *, status: str = "ok", **fields) -> None:
    if not run_id or not _enabled():
        return
    payload = {k: v for k, v in fields.items() if v is not None}
    payload["status"] = status
    payload["finished_at"] = datetime.now(UTC)
    _put("run_update", {"run_id": run_id, **payload})


def attach_message(run_id: str | None, message_id) -> None:
    if not run_id or not message_id:
        return
    update_run(run_id, message_id=message_id)


def update_run(run_id: str | None, **fields) -> None:
    if not run_id or not _enabled():
        return
    _put("run_update", {"run_id": run_id, **fields})


@contextlib.contextmanager
def run_scope(run_id: str | None):
    token = _CURRENT_RUN.set(run_id)
    try:
        yield run_id
    finally:
        _CURRENT_RUN.reset(token)


def current_run_id() -> str | None:
    return _CURRENT_RUN.get()


def push_run(run_id: str | None):
    return _CURRENT_RUN.set(run_id)


def pop_run(token) -> None:
    try:
        _CURRENT_RUN.reset(token)
    except Exception:
        pass


@dataclass
class SpanHandle:
    run_id: str
    span_id: str
    span_type: str
    name: str
    parent_span_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    t0: float = field(default_factory=time.monotonic)
    summary: str = ""
    error: str = ""
    status: str = "ok"
    attributes: dict = field(default_factory=dict)
    ended: bool = False

    def end(
        self,
        *,
        status: str | None = None,
        summary: str | None = None,
        error: str | None = None,
        model: str = "",
        provider: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_estimate: float = 0.0,
        attributes: dict | None = None,
    ) -> None:
        if self.ended:
            return
        self.ended = True
        if status is None:
            status = self.status
        if summary is not None:
            self.summary = summary
        if error is not None:
            self.error = error
            if status == "ok":
                status = "error"
        attrs = dict(self.attributes)
        if attributes:
            attrs.update(attributes)
        payload = {
            "run_id": self.run_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "span_type": self.span_type,
            "name": self.name[:128],
            "status": status,
            "started_at": self.started_at,
            "ended_at": datetime.now(UTC),
            "latency_ms": int((time.monotonic() - self.t0) * 1000),
            "model": (model or "")[:128],
            "provider": (provider or "")[:64],
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "cost_estimate": float(cost_estimate or 0.0),
            "summary": (self.summary or "")[:4000],
            "error": (self.error or "")[:2000],
            "attributes": attrs,
        }
        if _enabled():
            _put("span_insert", payload)


def start_span(
    *,
    span_type: str,
    name: str,
    run_id: str | None = None,
    parent_span_id: str | None = None,
    attributes: dict | None = None,
) -> SpanHandle:
    rid = run_id or current_run_id() or ""
    return SpanHandle(
        run_id=rid,
        span_id=new_span_id(),
        span_type=span_type,
        name=name,
        parent_span_id=parent_span_id,
        attributes=attributes or {},
    )


@contextlib.contextmanager
def span(
    *,
    span_type: str,
    name: str,
    run_id: str | None = None,
    parent_span_id: str | None = None,
    attributes: dict | None = None,
):
    handle = start_span(
        span_type=span_type,
        name=name,
        run_id=run_id,
        parent_span_id=parent_span_id,
        attributes=attributes,
    )
    try:
        yield handle
    except Exception as exc:
        handle.end(status="error", error=str(exc))
        raise
    else:
        if not handle.ended:
            handle.end()


def record_span(
    *,
    span_type: str,
    name: str,
    status: str = "ok",
    summary: str = "",
    error: str = "",
    model: str = "",
    provider: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_estimate: float = 0.0,
    latency_ms: int = 0,
    run_id: str | None = None,
    parent_span_id: str | None = None,
    attributes: dict | None = None,
) -> None:
    """直接写一个已完成 span（用于没有明确开始/结束边界的工具调用）。"""
    rid = run_id or current_run_id()
    if not rid or not _enabled():
        return
    now = datetime.now(UTC)
    payload = {
        "run_id": rid,
        "span_id": new_span_id(),
        "parent_span_id": parent_span_id,
        "span_type": span_type,
        "name": name[:128],
        "status": status,
        "started_at": now,
        "ended_at": now,
        "latency_ms": int(latency_ms or 0),
        "model": (model or "")[:128],
        "provider": (provider or "")[:64],
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cost_estimate": float(cost_estimate or 0.0),
        "summary": (summary or "")[:4000],
        "error": (error or "")[:2000],
        "attributes": attributes or {},
    }
    _put("span_insert", payload)


def flush(timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _QUEUE.empty():
            time.sleep(0.05)
            if _QUEUE.empty():
                return True
        time.sleep(0.05)
    return _QUEUE.empty()


def cleanup_expired() -> dict:
    from sqlalchemy import delete

    from app.core.config import get_settings
    from app.models.agent_trace import AgentRunSpan, AgentRunTrace

    days = int(get_settings().AGENT_RUN_RETENTION_DAYS or 30)
    before = datetime.now(UTC) - timedelta(days=days)
    db = _session_factory()()
    deleted = 0
    try:
        old_runs = db.execute(
            delete(AgentRunTrace).where(AgentRunTrace.created_at < before)
        ).rowcount or 0
        old_spans = db.execute(
            delete(AgentRunSpan).where(AgentRunSpan.created_at < before)
        ).rowcount or 0
        db.commit()
        deleted = int(old_runs) + int(old_spans)
    finally:
        db.close()
    return {"deleted": deleted}


__all__ = [
    "SpanHandle",
    "start_run",
    "finish_run",
    "attach_message",
    "update_run",
    "run_scope",
    "current_run_id",
    "push_run",
    "pop_run",
    "start_span",
    "span",
    "record_span",
    "flush",
    "cleanup_expired",
    "new_run_id",
]
