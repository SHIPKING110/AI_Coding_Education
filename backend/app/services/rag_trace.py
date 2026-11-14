"""检索 trace：上下文、异步落库、采样与清理。

约束：
- trace 写入不得阻塞或影响检索主流程；写失败只记日志。
- 成功检索按采样率落库；错误/零结果强制落库。
- 只保存分片预览，不保存整篇文档。
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
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_SESSION_FACTORY = None
_QUEUE: queue.Queue = queue.Queue(maxsize=2000)
_WORKER: threading.Thread | None = None
_WORKER_LOCK = threading.Lock()


@dataclass
class TraceContext:
    trace_id: str
    domain: str = "unknown"
    user_id: str | None = None
    owner_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    route: str = ""
    started_at: float = field(default_factory=time.time)
    stage_timings: dict = field(default_factory=dict)

    def mark(self, stage: str, started: float) -> None:
        self.stage_timings[stage] = round((time.time() - started) * 1000, 2)


_CURRENT: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "rag_trace_ctx", default=None
)


def new_trace_id() -> str:
    return uuid.uuid4().hex


@contextlib.contextmanager
def trace_scope(
    *,
    domain: str,
    user_id=None,
    owner_id=None,
    conversation_id=None,
    message_id=None,
    route: str = "",
):
    ctx = TraceContext(
        trace_id=new_trace_id(),
        domain=domain,
        user_id=str(user_id) if user_id else None,
        owner_id=str(owner_id) if owner_id else None,
        conversation_id=str(conversation_id) if conversation_id else None,
        message_id=str(message_id) if message_id else None,
        route=route or domain,
    )
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)


def current_trace() -> TraceContext | None:
    return _CURRENT.get()


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
        _WORKER = threading.Thread(target=_worker_loop, name="rag-trace-writer", daemon=True)
        _WORKER.start()


def _worker_loop() -> None:
    while True:
        item = _QUEUE.get()
        try:
            kind = item[0]
            if kind == "insert":
                _write_row(item[1])
            elif kind == "message":
                _update_message(item[1], item[2])
        except Exception:  # noqa: BLE001 —— 观测写入失败不能影响主链路
            logger.exception("rag trace write failed")
        finally:
            try:
                _QUEUE.task_done()
            except Exception:
                pass


def _write_row(payload: dict) -> None:
    from app.models.rag_admin import RagRetrievalTrace

    factory = _session_factory()
    db = factory()
    try:
        db.add(RagRetrievalTrace(**payload))
        db.commit()
    finally:
        db.close()


def _update_message(trace_id: str, message_id: str) -> None:
    from sqlalchemy import update

    from app.models.rag_admin import RagRetrievalTrace

    factory = _session_factory()
    db = factory()
    try:
        db.execute(
            update(RagRetrievalTrace)
            .where(RagRetrievalTrace.trace_id == trace_id)
            .values(message_id=message_id)
        )
        db.commit()
    finally:
        db.close()


def _sampled_out(is_error: bool, zero_result: bool) -> bool:
    if is_error or zero_result:
        return False
    try:
        from app.services import rag_settings

        rate = float(rag_settings.get_config().get("trace_success_sample_rate", 1.0))
    except Exception:
        rate = 1.0
    return random.random() > max(0.0, min(1.0, rate))


def record(
    ctx: TraceContext | None,
    *,
    query: str,
    rewritten_query: str = "",
    filters: dict | None = None,
    embedding_fingerprint: str = "",
    vector_candidates: int = 0,
    keyword_candidates: int = 0,
    rerank_candidates: int = 0,
    gated_out: int = 0,
    vector_ok: bool = False,
    keyword_used: bool = False,
    rerank_ok: bool = False,
    rerank_model: str = "",
    zero_result: bool = False,
    is_error: bool = False,
    error: str | None = None,
    latency_ms: int = 0,
    stage_timings: dict | None = None,
    hits: list | None = None,
) -> str | None:
    """记录一次检索；返回 trace_id（未记录时返回 None）。"""
    if ctx is None:
        return None
    if _sampled_out(is_error, zero_result):
        return None
    payload = {
        "trace_id": ctx.trace_id,
        "domain": ctx.domain or "unknown",
        "user_id": ctx.user_id,
        "owner_id": ctx.owner_id,
        "conversation_id": ctx.conversation_id,
        "message_id": ctx.message_id,
        "route": ctx.route or ctx.domain,
        "query": (query or "")[:4000],
        "rewritten_query": (rewritten_query or query or "")[:4000],
        "filters": filters or {},
        "embedding_fingerprint": embedding_fingerprint or "",
        "vector_candidates": int(vector_candidates or 0),
        "keyword_candidates": int(keyword_candidates or 0),
        "rerank_candidates": int(rerank_candidates or 0),
        "gated_out": int(gated_out or 0),
        "vector_ok": bool(vector_ok),
        "keyword_used": bool(keyword_used),
        "rerank_ok": bool(rerank_ok),
        "rerank_model": (rerank_model or "")[:128],
        "zero_result": bool(zero_result),
        "is_error": bool(is_error),
        "error": (error or "")[:2000] if error else None,
        "latency_ms": int(latency_ms or 0),
        "stage_timings": stage_timings or {},
        "hits": hits or [],
    }
    _ensure_worker()
    try:
        _QUEUE.put_nowait(("insert", payload))
    except queue.Full:
        logger.warning("rag trace queue full, drop trace %s", ctx.trace_id)
        return None
    return ctx.trace_id


def attach_message(trace_id: str | None, message_id) -> None:
    """消息落库后补齐 message_id，便于从聊天直接跳到 trace。"""
    if not trace_id or not message_id:
        return
    _ensure_worker()
    try:
        _QUEUE.put_nowait(("message", trace_id, str(message_id)))
    except queue.Full:
        pass


def flush(timeout: float = 3.0) -> bool:
    """测试/运维用：等待队列写完。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _QUEUE.empty():
            # 给 writer 一点时间完成最后一个 task_done
            time.sleep(0.05)
            if _QUEUE.empty():
                return True
        time.sleep(0.05)
    return _QUEUE.empty()


def cleanup_expired() -> dict:
    """按配置保留期清理 trace。返回删除条数。"""
    from sqlalchemy import delete

    from app.models.rag_admin import RagRetrievalTrace
    from app.services import rag_settings

    cfg = rag_settings.get_config()
    now = datetime.now(timezone.utc)
    success_before = now - timedelta(days=int(cfg.get("trace_retention_days", 30)))
    error_before = now - timedelta(days=int(cfg.get("trace_error_retention_days", 90)))
    factory = _session_factory()
    db = factory()
    deleted = 0
    try:
        r1 = db.execute(
            delete(RagRetrievalTrace).where(
                RagRetrievalTrace.is_error.is_(False),
                RagRetrievalTrace.zero_result.is_(False),
                RagRetrievalTrace.created_at < success_before,
            )
        )
        r2 = db.execute(
            delete(RagRetrievalTrace).where(
                (RagRetrievalTrace.is_error.is_(True)) | (RagRetrievalTrace.zero_result.is_(True)),
                RagRetrievalTrace.created_at < error_before,
            )
        )
        db.commit()
        deleted = int((r1.rowcount or 0) + (r2.rowcount or 0))
    finally:
        db.close()
    return {"deleted": deleted}


__all__ = [
    "TraceContext",
    "trace_scope",
    "current_trace",
    "new_trace_id",
    "record",
    "attach_message",
    "flush",
    "cleanup_expired",
]
