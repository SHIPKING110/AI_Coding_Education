"""用量与成本查询/价格表/对账/预算（供 /admin/usage 路由使用）。

统计口径：
- 事件级账本 `llm_usage_events` 为唯一数据源，仪表盘所有数字都由它聚合而来；
- `cost` 是写入时按价格快照算好的金额（历史不随后续调价变化）；
- `is_platform` 拆分机构成本（平台共享 Key）与教师个人成本（教师 BYOK）；
- `source != provider` 为估算行，单独计数，供仪表盘展示估算占比。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.system_setting import SystemSetting
from app.models.usage import (
    LLMModelPrice,
    LLMUsageEvent,
    LLMUsageMonthly,
    LLMUsageReconciliation,
)
from app.models.user import User

DEFAULT_CURRENCY = "CNY"


def _range_conds(since: datetime, until: datetime | None) -> list:
    conds = [LLMUsageEvent.created_at >= since]
    if until is not None:
        conds.append(LLMUsageEvent.created_at < until)
    return conds


def _sum_cost(db: Session, conds: list) -> float:
    return float(
        db.scalar(select(func.coalesce(func.sum(LLMUsageEvent.cost), 0.0)).where(*conds)) or 0.0
    )


def stats(db: Session, *, since: datetime, until: datetime | None = None) -> dict:
    conds = _range_conds(since, until)
    input_tokens = int(
        db.scalar(select(func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0)).where(*conds)) or 0
    )
    output_tokens = int(
        db.scalar(select(func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0)).where(*conds)) or 0
    )
    cost_total = _sum_cost(db, conds)
    cost_platform = _sum_cost(db, [*conds, LLMUsageEvent.is_platform.is_(True)])
    cost_teacher = round(cost_total - cost_platform, 8)

    def _count(*extra) -> int:
        return int(
            db.scalar(
                select(func.count()).select_from(LLMUsageEvent).where(*conds, *extra)
            )
            or 0
        )

    events = _count()
    provider_events = _count(LLMUsageEvent.source == "provider")
    estimated_events = _count(LLMUsageEvent.source == "estimated")
    error_events = _count(LLMUsageEvent.status == "error")
    # 未定价告警只统计「成功且实际消耗 tokens」的调用：
    # 失败重试与空调用即使没有价格行也不应制造噪声。
    unpriced_conds = [
        LLMUsageEvent.priced_status == "unpriced",
        func.coalesce(LLMUsageEvent.status, "ok") == "ok",
        func.coalesce(LLMUsageEvent.input_tokens, 0)
        + func.coalesce(LLMUsageEvent.output_tokens, 0) > 0,
    ]
    unpriced_events = _count(*unpriced_conds)

    # 按天趋势（平台/教师分开，页面可叠加或切换）
    day = func.date(LLMUsageEvent.created_at)
    series_map: dict[str, dict] = {}
    for d, plat, it, ot, c, n in db.execute(
        select(
            day,
            LLMUsageEvent.is_platform,
            func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0),
            func.coalesce(func.sum(LLMUsageEvent.cost), 0.0),
            func.count(),
        )
        .where(*conds)
        .group_by(day, LLMUsageEvent.is_platform)
        .order_by(day)
    ).all():
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        item = series_map.setdefault(
            key,
            {
                "day": key,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "cost_platform": 0.0,
                "cost_teacher": 0.0,
                "events": 0,
            },
        )
        item["input_tokens"] += int(it or 0)
        item["output_tokens"] += int(ot or 0)
        item["cost"] = round(item["cost"] + float(c or 0), 8)
        if plat:
            item["cost_platform"] = round(item["cost_platform"] + float(c or 0), 8)
        else:
            item["cost_teacher"] = round(item["cost_teacher"] + float(c or 0), 8)
        item["events"] += int(n or 0)
    series = [series_map[k] for k in sorted(series_map)]

    def _group(col, label: str, limit: int | None = None) -> list[dict]:
        stmt = (
            select(
                col,
                func.coalesce(func.sum(LLMUsageEvent.cost), 0.0),
                func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0),
                func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0),
                func.count(),
            )
            .where(*conds)
            .group_by(col)
            .order_by(func.sum(LLMUsageEvent.cost).desc())
        )
        if limit:
            stmt = stmt.limit(limit)
        return [
            {
                label: key or "",
                "cost": round(float(c or 0), 8),
                "input_tokens": int(i or 0),
                "output_tokens": int(o or 0),
                "events": int(n or 0),
            }
            for key, c, i, o, n in db.execute(stmt).all()
        ]

    by_module = _group(LLMUsageEvent.module, "module")
    by_kind = _group(LLMUsageEvent.kind, "kind")
    by_model = _group(LLMUsageEvent.model, "model", limit=20)

    # 教师个人成本 Top（平台共享单独一行）
    by_owner: list[dict] = []
    for owner_id, name, c, i, o, n in db.execute(
        select(
            LLMUsageEvent.owner_id,
            User.name,
            func.coalesce(func.sum(LLMUsageEvent.cost), 0.0),
            func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0),
            func.count(),
        )
        .select_from(LLMUsageEvent)
        .outerjoin(User, User.id == LLMUsageEvent.owner_id)
        .where(*conds, LLMUsageEvent.is_platform.is_(False))
        .group_by(LLMUsageEvent.owner_id, User.name)
        .order_by(func.sum(LLMUsageEvent.cost).desc())
        .limit(12)
    ).all():
        by_owner.append(
            {
                "owner_id": str(owner_id) if owner_id else None,
                "owner_name": name or "未知教师",
                "cost": round(float(c or 0), 8),
                "input_tokens": int(i or 0),
                "output_tokens": int(o or 0),
                "events": int(n or 0),
            }
        )
    plat_tokens_in = int(
        db.scalar(
            select(func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0)).where(
                *conds, LLMUsageEvent.is_platform.is_(True)
            )
        )
        or 0
    )
    plat_tokens_out = int(
        db.scalar(
            select(func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0)).where(
                *conds, LLMUsageEvent.is_platform.is_(True)
            )
        )
        or 0
    )
    plat_events = _count(LLMUsageEvent.is_platform.is_(True))
    by_owner.insert(
        0,
        {
            "owner_id": None,
            "owner_name": "平台共享（机构成本）",
            "cost": round(cost_platform, 8),
            "input_tokens": plat_tokens_in,
            "output_tokens": plat_tokens_out,
            "events": plat_events,
        },
    )

    unpriced = [
        {"provider_host": host or "", "model": model or "", "events": int(n or 0)}
        for host, model, n in db.execute(
            select(
                LLMUsageEvent.provider_host,
                LLMUsageEvent.model,
                func.count(),
            )
            .where(*conds, *unpriced_conds)
            .group_by(LLMUsageEvent.provider_host, LLMUsageEvent.model)
            .order_by(func.count().desc())
            .limit(20)
        ).all()
    ]

    return {
        "events": events,
        "provider_events": provider_events,
        "estimated_events": estimated_events,
        "provider_ratio": (provider_events / events) if events else None,
        "estimated_ratio": (estimated_events / events) if events else None,
        "error_events": error_events,
        "unpriced_events": unpriced_events,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimate": round(cost_total, 8),
        "cost_platform": round(cost_platform, 8),
        "cost_teacher": cost_teacher,
        "currency": DEFAULT_CURRENCY,
        "series": series,
        "by_module": by_module,
        "by_kind": by_kind,
        "by_model": by_model,
        "by_owner": by_owner,
        "unpriced": unpriced,
    }


def list_events(
    db: Session,
    *,
    since: datetime,
    until: datetime | None = None,
    module: str | None = None,
    kind: str | None = None,
    model: str | None = None,
    owner_id: str | None = None,
    priced_status: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    conds = _range_conds(since, until)
    if module:
        conds.append(LLMUsageEvent.module == module)
    if kind:
        conds.append(LLMUsageEvent.kind == kind)
    if model:
        conds.append(LLMUsageEvent.model.ilike(f"%{model}%"))
    if owner_id:
        try:
            conds.append(LLMUsageEvent.owner_id == uuid.UUID(owner_id))
        except ValueError:
            pass
    if priced_status:
        conds.append(LLMUsageEvent.priced_status == priced_status)
    if status:
        conds.append(LLMUsageEvent.status == status)
    total = int(
        db.scalar(select(func.count()).select_from(LLMUsageEvent).where(*conds)) or 0
    )
    rows = list(
        db.scalars(
            select(LLMUsageEvent)
            .where(*conds)
            .order_by(LLMUsageEvent.created_at.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        ).all()
    )
    names = _owner_names(db, {r.owner_id for r in rows if r.owner_id})
    return {"total": total, "items": rows, "owner_names": names}


def _owner_names(db: Session, ids: set[uuid.UUID]) -> dict[str, str]:
    if not ids:
        return {}
    rows = db.execute(select(User.id, User.name).where(User.id.in_(ids))).all()
    return {str(uid): name for uid, name in rows}


def list_monthly(db: Session) -> list[LLMUsageMonthly]:
    return list(
        db.scalars(select(LLMUsageMonthly).order_by(LLMUsageMonthly.month.desc())).all()
    )


# ---------------- 价格表 ----------------


def list_prices(db: Session) -> list[LLMModelPrice]:
    return list(
        db.scalars(
            select(LLMModelPrice).order_by(
                LLMModelPrice.provider_host,
                LLMModelPrice.model_pattern,
                LLMModelPrice.effective_from.desc(),
            )
        ).all()
    )


def get_price(db: Session, price_id: uuid.UUID) -> LLMModelPrice | None:
    return db.get(LLMModelPrice, price_id)


def create_price(db: Session, data: dict) -> LLMModelPrice:
    row = LLMModelPrice(**{k: v for k, v in data.items() if hasattr(LLMModelPrice, k)})
    if row.effective_from is None:
        row.effective_from = datetime.now(UTC)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_price(db: Session, row: LLMModelPrice, data: dict) -> LLMModelPrice:
    for k, v in data.items():
        if v is None or not hasattr(row, k):
            continue
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


def delete_price(db: Session, row: LLMModelPrice) -> None:
    db.delete(row)
    db.commit()


# ---------------- 月度对账 ----------------


def list_reconciliations(db: Session, month: str | None = None) -> list[LLMUsageReconciliation]:
    stmt = select(LLMUsageReconciliation).order_by(LLMUsageReconciliation.month.desc())
    if month:
        stmt = stmt.where(LLMUsageReconciliation.month == month)
    return list(db.scalars(stmt).all())


def upsert_reconciliation(
    db: Session,
    *,
    month: str,
    provider: str,
    billed_amount: float,
    currency: str = DEFAULT_CURRENCY,
    note: str = "",
) -> LLMUsageReconciliation:
    row = db.scalar(
        select(LLMUsageReconciliation).where(
            LLMUsageReconciliation.month == month, LLMUsageReconciliation.provider == provider
        )
    )
    if row is None:
        row = LLMUsageReconciliation(month=month, provider=provider)
        db.add(row)
    row.billed_amount = float(billed_amount)
    row.currency = currency or DEFAULT_CURRENCY
    row.note = note or ""
    db.commit()
    db.refresh(row)
    return row


def delete_reconciliation(db: Session, recon_id: uuid.UUID) -> None:
    row = db.get(LLMUsageReconciliation, recon_id)
    if row is not None:
        db.delete(row)
        db.commit()


def count_unpriced(
    db: Session,
    *,
    since: datetime,
    provider_host: str | None = None,
    model: str | None = None,
) -> int:
    conds = [LLMUsageEvent.priced_status == "unpriced", LLMUsageEvent.created_at >= since]
    if provider_host:
        conds.append(LLMUsageEvent.provider_host == provider_host)
    if model:
        conds.append(LLMUsageEvent.model == model)
    return int(db.scalar(select(func.count()).select_from(LLMUsageEvent).where(*conds)) or 0)


def purge_unpriced(
    db: Session,
    *,
    since: datetime,
    provider_host: str | None = None,
    model: str | None = None,
) -> int:
    """删除保留期内匹配的未定价明细（费用恒为 0，不影响已定价账本与月度汇总）。

    典型用途：清理测试网关（如 example.com / model-a）或错误配置产生的噪声。
    """
    conds = [LLMUsageEvent.priced_status == "unpriced", LLMUsageEvent.created_at >= since]
    if provider_host:
        conds.append(LLMUsageEvent.provider_host == provider_host)
    if model:
        conds.append(LLMUsageEvent.model == model)
    result = db.execute(delete(LLMUsageEvent).where(*conds))
    db.commit()
    return int(result.rowcount or 0)


def month_ledger(db: Session, month: str) -> dict:
    """某月账本按 (provider_host, currency) 汇总，供与厂商账单对比。"""
    since = datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=UTC)
    if since.month == 12:
        until = since.replace(year=since.year + 1, month=1)
    else:
        until = since.replace(month=since.month + 1)
    conds = _range_conds(since, until)
    rows = db.execute(
        select(
            LLMUsageEvent.provider_host,
            LLMUsageEvent.currency,
            func.coalesce(func.sum(LLMUsageEvent.cost), 0.0),
            func.coalesce(func.sum(LLMUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(LLMUsageEvent.output_tokens), 0),
            func.count(),
        )
        .where(*conds)
        .group_by(LLMUsageEvent.provider_host, LLMUsageEvent.currency)
        .order_by(func.sum(LLMUsageEvent.cost).desc())
    ).all()
    return {
        "month": month,
        "providers": [
            {
                "provider_host": host or "",
                "currency": cur or DEFAULT_CURRENCY,
                "cost": round(float(c or 0), 8),
                "input_tokens": int(i or 0),
                "output_tokens": int(o or 0),
                "events": int(n or 0),
            }
            for host, cur, c, i, o, n in rows
        ],
    }


# ---------------- 预算（SystemSetting 上的两个字段） ----------------


def get_budget(db: Session) -> dict:
    row = db.get(SystemSetting, 1)
    return {
        "monthly_budget": float(getattr(row, "llm_monthly_budget", 0.0) or 0.0) if row else 0.0,
        "alert_ratio": float(getattr(row, "llm_budget_alert_ratio", 0.8) or 0.8) if row else 0.8,
    }


def set_budget(db: Session, *, monthly_budget: float, alert_ratio: float) -> dict:
    row = db.get(SystemSetting, 1)
    if row is None:
        row = SystemSetting(id=1)
        db.add(row)
    row.llm_monthly_budget = max(0.0, float(monthly_budget))
    row.llm_budget_alert_ratio = max(0.0, min(1.0, float(alert_ratio)))
    db.commit()
    db.refresh(row)
    return get_budget(db)


__all__ = [
    "count_unpriced",
    "create_price",
    "delete_price",
    "delete_reconciliation",
    "get_budget",
    "get_price",
    "list_events",
    "list_monthly",
    "list_prices",
    "list_reconciliations",
    "month_ledger",
    "purge_unpriced",
    "set_budget",
    "stats",
    "update_price",
    "upsert_reconciliation",
]
