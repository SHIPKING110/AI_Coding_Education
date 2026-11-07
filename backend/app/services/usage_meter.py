"""Token 记账（usage meter）：异步写入 `llm_usage_events`，不阻塞模型调用。

设计要点（与 agent_ops 同思路，但账本独立，保证可审计）：
- **记账在写队列消费时定价**：价格解析/成本计算都在后台 worker 里做，
  模型调用路径只投递原始 usage（provider 返回或本地估算）；
- **职责分离**：usage_meter 只负责「产生记账行」，统计/报表在 crud.usage；
- **归属**：默认从 llm_context 当前模型解析结果取 owner/module/is_platform，
  教师自配 Key 记个人成本，平台共享 Key（家长客服/系统级 embedding）记机构成本；
- **失败不影响业务**：任何异常只记日志。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

_QUEUE: queue.Queue = queue.Queue(maxsize=5000)
_WORKER: threading.Thread | None = None
_WORKER_LOCK = threading.Lock()


def enabled() -> bool:
    try:
        from app.core.config import get_settings

        return bool(get_settings().LLM_USAGE_TRACKING_ENABLED)
    except Exception:
        return True


def _session_factory():
    from app.core.database import SessionLocal

    return SessionLocal


def _ensure_worker() -> None:
    global _WORKER
    if _WORKER is not None and _WORKER.is_alive():
        return
    with _WORKER_LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return
        _WORKER = threading.Thread(target=_worker_loop, name="usage-meter-writer", daemon=True)
        _WORKER.start()


def _worker_loop() -> None:
    while True:
        payload = _QUEUE.get()
        try:
            _write_event(payload)
        except Exception:  # noqa: BLE001
            logger.exception("usage meter write failed")
        finally:
            try:
                _QUEUE.task_done()
            except Exception:
                pass


def _write_event(payload: dict) -> None:
    from app.models.usage import LLMUsageEvent
    from app.services import pricing

    SessionLocal = _session_factory()
    db = SessionLocal()
    try:
        at = payload.pop("at", None) or datetime.now(UTC)
        price = pricing.resolve_price(
            db,
            payload.get("provider_host") or "",
            payload.get("model") or "",
            at,
            allow_host_mismatch=payload.get("kind") in {"embedding", "rerank"},
        )
        if price is None:
            payload["priced_status"] = "unpriced"
            payload["cost"] = 0.0
            payload["price_id"] = None
            payload["price_snapshot"] = None
        else:
            cost, snapshot = pricing.compute_cost(
                price,
                input_tokens=payload.get("input_tokens", 0),
                output_tokens=payload.get("output_tokens", 0),
                cached_tokens=payload.get("cached_tokens", 0),
                at=at,
            )
            payload["priced_status"] = "priced"
            payload["cost"] = cost
            payload["price_id"] = price.id
            payload["price_snapshot"] = snapshot
            payload["currency"] = price.currency or payload.get("currency") or "CNY"
        payload["created_at"] = at
        db.add(LLMUsageEvent(**payload))
        db.commit()
    finally:
        db.close()


def _put(payload: dict) -> None:
    if not enabled():
        return
    _ensure_worker()
    try:
        _QUEUE.put_nowait(payload)
    except queue.Full:
        logger.warning("usage meter queue full, drop event")


def _current_ctx():
    try:
        from app.services import llm_context

        return llm_context.get_current()
    except Exception:
        return None


def record_chat(
    *,
    model: str,
    base_url: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    source: str = "provider",
    latency_ms: int = 0,
    status: str = "ok",
    module: str | None = None,
    owner_id: uuid.UUID | None = None,
    config_id: uuid.UUID | None = None,
    is_platform: bool | None = None,
    attempt: int = 1,
    run_id: str | None = None,
    meta: dict | None = None,
) -> None:
    """记一笔 chat 调用。未显式给出的归属字段从当前 llm_context 解析结果取。"""
    from app.services import pricing

    cur = _current_ctx()
    if module is None:
        module = getattr(cur, "module", "") or "agent"
    if owner_id is None:
        owner_id = getattr(cur, "owner_id", None)
    if config_id is None:
        config_id = getattr(cur, "config_id", None)
    if is_platform is None:
        is_platform = bool(getattr(cur, "is_platform", False)) if cur is not None else True
    if run_id is None:
        try:
            from app.services import agent_ops

            run_id = agent_ops.current_run_id()
        except Exception:
            run_id = None
    _put(
        {
            "at": datetime.now(UTC),
            "run_id": run_id,
            "kind": "chat",
            "module": (module or "")[:32],
            "owner_id": owner_id,
            "config_id": config_id,
            "is_platform": bool(is_platform),
            "provider_host": pricing.provider_host(base_url),
            "model": (model or "")[:128],
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "cached_tokens": int(cached_tokens or 0),
            "source": source,
            "cost": 0.0,
            "currency": "CNY",
            "priced_status": "unpriced",
            "latency_ms": int(latency_ms or 0),
            "status": status,
            "attempt": int(attempt or 1),
            "meta": meta or {},
        }
    )


def record_embedding(
    resolved,
    *,
    texts: list[str],
    latency_ms: int = 0,
    status: str = "ok",
    attempt: int = 1,
    module: str = "embedding",
) -> None:
    """记一笔 embedding 调用（系统级配置 → 平台成本；网关通常不返回 usage，按字符估算）。"""
    if resolved is None or getattr(resolved, "provider", "") == "local":
        return  # 本机模型无费用
    from app.services import pricing

    tokens = pricing.estimate_tokens_many(texts)
    _put(
        {
            "at": datetime.now(UTC),
            "kind": "embedding",
            "module": module,
            "owner_id": None,
            "config_id": None,
            "is_platform": True,
            "provider_host": pricing.provider_host(getattr(resolved, "base_url", "")),
            "model": (getattr(resolved, "model", "") or "")[:128],
            "input_tokens": tokens,
            "output_tokens": 0,
            "cached_tokens": 0,
            "source": "estimated",
            "cost": 0.0,
            "currency": "CNY",
            "priced_status": "unpriced",
            "latency_ms": int(latency_ms or 0),
            "status": status,
            "attempt": int(attempt or 1),
            "meta": {"texts": len(texts)},
        }
    )


def record_rerank(
    resolved,
    *,
    query: str,
    documents: list[str],
    owner_id: uuid.UUID | None = None,
    platform: bool = False,
    latency_ms: int = 0,
    status: str = "ok",
    module: str = "rerank",
) -> None:
    """记一笔 rerank 调用（教师自配 → 个人成本；家长客服共享 → 机构成本）。"""
    if resolved is None or getattr(resolved, "provider", "") == "local":
        return
    from app.services import pricing

    tokens = pricing.estimate_tokens(query) + pricing.estimate_tokens_many(documents)
    _put(
        {
            "at": datetime.now(UTC),
            "kind": "rerank",
            "module": module,
            "owner_id": None if platform else owner_id,
            "config_id": None,
            "is_platform": bool(platform),
            "provider_host": pricing.provider_host(getattr(resolved, "base_url", "")),
            "model": (getattr(resolved, "model", "") or "")[:128],
            "input_tokens": tokens,
            "output_tokens": 0,
            "cached_tokens": 0,
            "source": "estimated",
            "cost": 0.0,
            "currency": "CNY",
            "priced_status": "unpriced",
            "latency_ms": int(latency_ms or 0),
            "status": status,
            "attempt": 1,
            "meta": {"documents": len(documents)},
        }
    )


def flush(timeout: float = 3.0) -> bool:
    """等待队列消费完（测试/关停用）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _QUEUE.empty():
            time.sleep(0.05)
            if _QUEUE.empty():
                return True
        time.sleep(0.05)
    return _QUEUE.empty()


def cleanup_expired() -> dict:
    """保留期到期清理：先把过期月份汇总进 `llm_usage_monthly`（永久保留），再删明细。"""
    from sqlalchemy import delete, func, select

    from app.core.config import get_settings
    from app.models.usage import LLMUsageEvent, LLMUsageMonthly

    days = int(getattr(get_settings(), "LLM_USAGE_RETENTION_DAYS", 180) or 180)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    SessionLocal = _session_factory()
    db = SessionLocal()
    rolled = 0
    deleted = 0
    try:
        month_expr = func.to_char(LLMUsageEvent.created_at, "YYYY-MM")
        rows = db.execute(
            select(
                month_expr,
                LLMUsageEvent.currency,
                func.count(),
                func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0),
                func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0),
                func.coalesce(func.sum(LLMUsageEvent.cost), 0.0),
            )
            .where(LLMUsageEvent.created_at < cutoff)
            .group_by(month_expr, LLMUsageEvent.currency)
        ).all()
        split = {
            (m, cur): (float(plat or 0.0), float(teach or 0.0))
            for m, cur, plat, teach in db.execute(
                select(
                    month_expr,
                    LLMUsageEvent.currency,
                    func.coalesce(
                        func.sum(LLMUsageEvent.cost).filter(LLMUsageEvent.is_platform.is_(True)),
                        0.0,
                    ),
                    func.coalesce(
                        func.sum(LLMUsageEvent.cost).filter(LLMUsageEvent.is_platform.is_(False)),
                        0.0,
                    ),
                )
                .where(LLMUsageEvent.created_at < cutoff)
                .group_by(month_expr, LLMUsageEvent.currency)
            ).all()
        }
        unpriced = {
            (m, cur): int(n or 0)
            for m, cur, n in db.execute(
                select(month_expr, LLMUsageEvent.currency, func.count())
                .where(
                    LLMUsageEvent.created_at < cutoff,
                    LLMUsageEvent.priced_status == "unpriced",
                )
                .group_by(month_expr, LLMUsageEvent.currency)
            ).all()
        }
        for month, currency, events, tokens_in, tokens_out, cost_total in rows:
            row = db.scalar(
                select(LLMUsageMonthly).where(
                    LLMUsageMonthly.month == month, LLMUsageMonthly.currency == currency
                )
            )
            if row is None:
                row = LLMUsageMonthly(month=month or "", currency=currency or "CNY")
                db.add(row)
            plat, teach = split.get((month, currency), (0.0, 0.0))
            row.events = int(row.events or 0) + int(events or 0)
            row.input_tokens = int(row.input_tokens or 0) + int(tokens_in or 0)
            row.output_tokens = int(row.output_tokens or 0) + int(tokens_out or 0)
            row.cost_total = float(row.cost_total or 0.0) + float(cost_total or 0.0)
            row.cost_platform = float(row.cost_platform or 0.0) + plat
            row.cost_teacher = float(row.cost_teacher or 0.0) + teach
            row.unpriced_events = int(row.unpriced_events or 0) + unpriced.get(
                (month, currency), 0
            )
            rolled += 1
        result = db.execute(delete(LLMUsageEvent).where(LLMUsageEvent.created_at < cutoff))
        deleted = int(result.rowcount or 0)
        db.commit()
    finally:
        db.close()
    return {"rolled_months": rolled, "deleted": deleted}


def check_month_budget() -> dict | None:
    """月度预算检查：超过阈值时给所有管理员发一次站内通知（同月幂等，靠 reminder_key 去重）。"""
    from sqlalchemy import func, select

    from app.crud import notification as notification_crud
    from app.models.notification import Notification, NotificationType
    from app.models.system_setting import SystemSetting
    from app.models.usage import LLMUsageEvent
    from app.models.user import Role, User

    SessionLocal = _session_factory()
    db = SessionLocal()
    try:
        setting = db.get(SystemSetting, 1)
        if setting is None:
            return None
        budget = float(getattr(setting, "llm_monthly_budget", 0) or 0)
        ratio = float(getattr(setting, "llm_budget_alert_ratio", 0.8) or 0.8)
        if budget <= 0:
            return None
        now = datetime.now(UTC)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_key = now.strftime("%Y-%m")
        threshold = budget * max(0.0, min(1.0, ratio))
        cost = float(
            db.scalar(
                select(func.coalesce(func.sum(LLMUsageEvent.cost), 0.0)).where(
                    LLMUsageEvent.created_at >= month_start
                )
            )
            or 0
        )
        if cost < threshold:
            return None
        reminder_key = f"usage_budget:{month_key}"
        admins = list(db.scalars(select(User).where(User.role == Role.ADMIN.value)).all())
        sent = 0
        for admin in admins:
            exists = db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == admin.id,
                    Notification.data.op("->>")("reminder_key") == reminder_key,
                )
            )
            if exists:
                continue
            notification_crud.create(
                db,
                user_id=admin.id,
                type=NotificationType.USAGE_BUDGET.value,
                title="AI 费用预算提醒",
                content=(
                    f"{month_key} 本月 AI 调用费用 ¥{cost:.2f}，"
                    f"已达预算 ¥{budget:.2f} 的 {ratio * 100:.0f}% 阈值，"
                    "请到「用量与成本」查看明细。"
                ),
                data={"reminder_key": reminder_key, "month": month_key, "cost": cost},
            )
            sent += 1
        return {"month": month_key, "cost": cost, "budget": budget, "sent": sent}
    except Exception:
        logger.exception("usage budget check failed")
        return None
    finally:
        db.close()


__all__ = [
    "check_month_budget",
    "cleanup_expired",
    "enabled",
    "flush",
    "record_chat",
    "record_embedding",
    "record_rerank",
]
