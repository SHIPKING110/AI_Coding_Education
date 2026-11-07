"""用量与成本仪表盘 API（管理员/教务只读；价格、预算、对账仅管理员）。

- GET  /admin/usage/stats        聚合：总量/分日/分模块/分模型/分归属 + 估算与未定价提示
- GET  /admin/usage/events       明细列表（分页筛选）
- GET  /admin/usage/export       明细 CSV 导出
- GET  /admin/usage/monthly      月度汇总（保留期外的永久数据）
- GET  /admin/usage/prices       价格表；POST/PUT/DELETE 维护（版本化，调价请新增行）
- GET  /admin/usage/settings     预算；PUT 保存
- GET  /admin/usage/reconciliations?month=  对账（账本 vs 厂商账单差异）
- POST /admin/usage/reconciliations         录入/更新账单
- DELETE /admin/usage/reconciliations/{id}  删除账单
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles, require_teacher_permission
from app.core.database import get_db
from app.crud import usage as crud
from app.models.usage import LLMModelPrice, LLMUsageEvent
from app.models.user import Role, User

router = APIRouter(
    prefix="/admin/usage",
    tags=["usage"],
)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _event_out(ev: LLMUsageEvent, owner_names: dict[str, str]) -> dict:
    return {
        "id": str(ev.id),
        "created_at": _iso(ev.created_at),
        "kind": ev.kind,
        "module": ev.module,
        "owner_id": str(ev.owner_id) if ev.owner_id else None,
        "owner_name": owner_names.get(str(ev.owner_id), "") if ev.owner_id else "",
        "is_platform": bool(ev.is_platform),
        "provider_host": ev.provider_host,
        "model": ev.model,
        "input_tokens": ev.input_tokens,
        "output_tokens": ev.output_tokens,
        "cached_tokens": ev.cached_tokens,
        "source": ev.source,
        "cost": ev.cost,
        "currency": ev.currency,
        "priced_status": ev.priced_status,
        "latency_ms": ev.latency_ms,
        "status": ev.status,
        "run_id": ev.run_id,
        "price_snapshot": ev.price_snapshot or {},
        "meta": ev.meta or {},
    }


def _price_out(p: LLMModelPrice) -> dict:
    return {
        "id": str(p.id),
        "provider_host": p.provider_host,
        "model_pattern": p.model_pattern,
        "currency": p.currency,
        "input_per_1m": p.input_per_1m,
        "output_per_1m": p.output_per_1m,
        "cache_read_per_1m": p.cache_read_per_1m,
        "cache_write_per_1m": p.cache_write_per_1m,
        "tiers": p.tiers or [],
        "time_windows": p.time_windows or [],
        "effective_from": _iso(p.effective_from),
        "source_note": p.source_note,
        "created_at": _iso(p.created_at),
    }


class PriceIn(BaseModel):
    provider_host: str = ""
    model_pattern: str = ""
    currency: str = "CNY"
    input_per_1m: float = 0
    output_per_1m: float = 0
    cache_read_per_1m: float = 0
    cache_write_per_1m: float = 0
    tiers: list[dict] | None = None
    time_windows: list[dict] | None = None
    effective_from: datetime | None = None
    source_note: str = ""


class PriceUpdate(BaseModel):
    provider_host: str | None = None
    model_pattern: str | None = None
    currency: str | None = None
    input_per_1m: float | None = None
    output_per_1m: float | None = None
    cache_read_per_1m: float | None = None
    cache_write_per_1m: float | None = None
    tiers: list[dict] | None = None
    time_windows: list[dict] | None = None
    effective_from: datetime | None = None
    source_note: str | None = None


class BudgetIn(BaseModel):
    monthly_budget: float = 0
    alert_ratio: float = 0.8


class ReconIn(BaseModel):
    month: str
    provider: str = ""
    billed_amount: float = 0
    currency: str = "CNY"
    note: str = ""


@router.get("/stats", dependencies=[Depends(require_teacher_permission("usage_view", staff_allowed=False))])
def get_stats(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    data = crud.stats(db, since=since)
    data["days"] = days
    return data


@router.get("/events", dependencies=[Depends(require_teacher_permission("usage_view", staff_allowed=False))])
def list_events(
    days: int = Query(30, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    module: str | None = None,
    kind: str | None = None,
    model: str | None = None,
    owner_id: str | None = None,
    priced_status: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    result = crud.list_events(
        db,
        since=since,
        module=module,
        kind=kind,
        model=model,
        owner_id=owner_id,
        priced_status=priced_status,
        status=status,
        page=page,
        page_size=page_size,
    )
    return {
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "items": [_event_out(ev, result["owner_names"]) for ev in result["items"]],
    }


@router.get("/export", dependencies=[Depends(require_teacher_permission("usage_view", staff_allowed=False))])
def export_events(
    days: int = Query(30, ge=1, le=365),
    module: str | None = None,
    kind: str | None = None,
    model: str | None = None,
    owner_id: str | None = None,
    priced_status: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    since = datetime.now(UTC) - timedelta(days=days)
    rows: list[dict] = []
    page = 1
    while page <= 50:  # 上限 5000 行，够单机构月度导出
        result = crud.list_events(
            db,
            since=since,
            module=module,
            kind=kind,
            model=model,
            owner_id=owner_id,
            priced_status=priced_status,
            status=status,
            page=page,
            page_size=100,
        )
        names = result["owner_names"]
        rows.extend(_event_out(ev, names) for ev in result["items"])
        if len(result["items"]) < 100:
            break
        page += 1

    buf = io.StringIO()
    buf.write("\ufeff")  # BOM：Excel 打开中文不乱码
    writer = csv.writer(buf)
    writer.writerow(
        [
            "时间",
            "类型",
            "模块",
            "归属",
            "教师",
            "网关",
            "模型",
            "输入tokens",
            "输出tokens",
            "缓存tokens",
            "精度",
            "费用",
            "币种",
            "定价状态",
            "耗时ms",
            "状态",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                (r["created_at"] or "")[:19].replace("T", " "),
                r["kind"],
                r["module"],
                "平台" if r["is_platform"] else "教师",
                r["owner_name"],
                r["provider_host"],
                r["model"],
                r["input_tokens"],
                r["output_tokens"],
                r["cached_tokens"],
                "厂商" if r["source"] == "provider" else ("估算" if r["source"] == "estimated" else r["source"]),
                f"{r['cost']:.6f}",
                r["currency"],
                "已定价" if r["priced_status"] == "priced" else "未定价",
                r["latency_ms"],
                "成功" if r["status"] == "ok" else "失败",
            ]
        )
    buf.seek(0)
    filename = f"llm-usage-{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/monthly", dependencies=[Depends(require_teacher_permission("usage_view", staff_allowed=False))])
def list_monthly(db: Session = Depends(get_db)) -> dict:
    return {
        "items": [
            {
                "month": m.month,
                "currency": m.currency,
                "events": m.events,
                "input_tokens": m.input_tokens,
                "output_tokens": m.output_tokens,
                "cost_total": m.cost_total,
                "cost_platform": m.cost_platform,
                "cost_teacher": m.cost_teacher,
                "unpriced_events": m.unpriced_events,
                "updated_at": _iso(m.updated_at),
            }
            for m in crud.list_monthly(db)
        ]
    }


# ---------------- 价格表（仅管理员） ----------------


@router.get("/prices", dependencies=[Depends(require_teacher_permission("usage_view", staff_allowed=False))])
def list_prices(db: Session = Depends(get_db)) -> dict:
    return {"items": [_price_out(p) for p in crud.list_prices(db)]}


@router.post(
    "/reprice-unpriced",
    dependencies=[Depends(require_teacher_permission("usage_price_create", staff_allowed=False))],
)
def reprice_unpriced(
    since_days: int = Query(default=30, ge=1, le=366),
    db: Session = Depends(get_db),
) -> dict:
    """按当前价格表重算保留期内的未定价明细（不回溯已归档的月度汇总）。

    典型场景：同一模型换了网关域名，历史明细已记成 unpriced；补齐价格/改进匹配后
    用此操作把保留期内的明细按原调用时间重新计价。
    """
    from app.services import pricing

    cutoff = datetime.now(UTC) - timedelta(days=since_days)
    rows = db.scalars(
        select(LLMUsageEvent).where(
            LLMUsageEvent.priced_status == "unpriced",
            LLMUsageEvent.created_at >= cutoff,
        )
    ).all()
    repriced = 0
    skipped = 0
    for ev in rows:
        price = pricing.resolve_price(
            db,
            ev.provider_host or "",
            ev.model or "",
            ev.created_at,
            allow_host_mismatch=ev.kind in {"embedding", "rerank"},
        )
        if price is None:
            skipped += 1
            continue
        cost, snapshot = pricing.compute_cost(
            price,
            input_tokens=ev.input_tokens,
            output_tokens=ev.output_tokens,
            cached_tokens=ev.cached_tokens,
            at=ev.created_at,
        )
        ev.cost = cost
        ev.currency = price.currency or ev.currency
        ev.priced_status = "priced"
        ev.price_id = price.id
        ev.price_snapshot = snapshot
        repriced += 1
    db.commit()
    return {"scanned": len(rows), "repriced": repriced, "skipped": skipped}


@router.post(
    "/prices",
    status_code=201,
    dependencies=[Depends(require_teacher_permission("usage_price_create", staff_allowed=False))],
)
def create_price(
    payload: PriceIn,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    data = payload.model_dump()
    if not data["provider_host"].strip() and not data["model_pattern"].strip():
        raise HTTPException(status_code=400, detail="网关域名与模型匹配至少填一个（全通配会兜底所有模型）")
    row = crud.create_price(db, data)
    return _price_out(row)


@router.put(
    "/prices/{price_id}",
    dependencies=[Depends(require_teacher_permission("usage_price_create", staff_allowed=False))],
)
def update_price(
    price_id: str,
    payload: PriceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    try:
        pid = uuid.UUID(price_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="价格 ID 非法")
    row = crud.get_price(db, pid)
    if row is None:
        raise HTTPException(status_code=404, detail="价格不存在")
    row = crud.update_price(db, row, payload.model_dump(exclude_unset=True))
    return _price_out(row)


@router.delete(
    "/prices/{price_id}",
    dependencies=[Depends(require_teacher_permission("usage_price_create", staff_allowed=False))],
)
def delete_price(
    price_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    try:
        pid = uuid.UUID(price_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="价格 ID 非法")
    row = crud.get_price(db, pid)
    if row is None:
        raise HTTPException(status_code=404, detail="价格不存在")
    crud.delete_price(db, row)
    return {"deleted": True}


# ---------------- 预算 ----------------


@router.get("/settings", dependencies=[Depends(require_teacher_permission("usage_view", staff_allowed=False))])
def get_usage_settings(db: Session = Depends(get_db)) -> dict:
    return crud.get_budget(db)


@router.put("/settings", dependencies=[Depends(require_teacher_permission("usage_budget_save", staff_allowed=False))])
def update_usage_settings(
    payload: BudgetIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    if payload.monthly_budget < 0:
        raise HTTPException(status_code=400, detail="月度预算不能为负数")
    if not (0 <= payload.alert_ratio <= 1):
        raise HTTPException(status_code=400, detail="提醒阈值比例需在 0~1 之间")
    return crud.set_budget(
        db, monthly_budget=payload.monthly_budget, alert_ratio=payload.alert_ratio
    )


# ---------------- 月度对账 ----------------


def _recon_out(row, ledger: dict) -> dict:
    row_provider = (row.provider or "").lower()
    ledger_cost = 0.0
    for p in ledger.get("providers") or []:
        if (p.get("currency") or "CNY") != (row.currency or "CNY"):
            continue
        host = (p.get("provider_host") or "").lower()
        if not row_provider or row_provider in host:
            ledger_cost += float(p.get("cost") or 0)
    diff = float(row.billed_amount or 0) - ledger_cost
    ratio = (diff / ledger_cost) if ledger_cost else None
    return {
        "id": str(row.id),
        "month": row.month,
        "provider": row.provider,
        "billed_amount": row.billed_amount,
        "currency": row.currency,
        "note": row.note,
        "ledger_cost": round(ledger_cost, 8),
        "diff": round(diff, 8),
        "diff_ratio": ratio,
        "updated_at": _iso(row.updated_at),
    }


@router.get("/reconciliations", dependencies=[Depends(require_teacher_permission("usage_view", staff_allowed=False))])
def list_reconciliations(
    month: str | None = None, db: Session = Depends(get_db)
) -> dict:
    rows = crud.list_reconciliations(db, month)
    ledger = crud.month_ledger(db, month) if month else {"month": "", "providers": []}
    return {
        "items": [_recon_out(r, ledger) for r in rows],
        "ledger": ledger,
    }


@router.post(
    "/reconciliations",
    status_code=201,
    dependencies=[Depends(require_teacher_permission("usage_recon_upsert", staff_allowed=False))],
)
def upsert_reconciliation(
    payload: ReconIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    try:
        datetime.strptime(payload.month + "-01", "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="月份格式应为 YYYY-MM")
    row = crud.upsert_reconciliation(
        db,
        month=payload.month,
        provider=payload.provider.strip(),
        billed_amount=payload.billed_amount,
        currency=payload.currency or "CNY",
        note=payload.note,
    )
    ledger = crud.month_ledger(db, payload.month)
    return _recon_out(row, ledger)


@router.delete(
    "/reconciliations/{recon_id}",
    dependencies=[Depends(require_teacher_permission("usage_recon_upsert", staff_allowed=False))],
)
def delete_reconciliation(
    recon_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    try:
        rid = uuid.UUID(recon_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="对账 ID 非法")
    crud.delete_reconciliation(db, rid)
    return {"deleted": True}
