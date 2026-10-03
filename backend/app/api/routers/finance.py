"""财务管理（财务 tab）：创收/绩效/退款聚合（只读账本 + 订单），图表数据源。

口径：
- 创收 = 消耗课时 × 消耗瞬间 FIFO 单价（RevenueLedger，只读）
- 教师绩效 = 消耗金额 × 快照抽成比例
- 退款 = 订单 refund_amount（按 refunded_at 落期）
- 公司实收 = 创收 − 绩效 − 退款
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_teacher_permission
from app.core.database import get_db
from app.models.business import RevenueLedger
from app.models.enrollment import Order, OrderStatus
from app.models.user import User

router = APIRouter(prefix="/finance", tags=["finance"])


def _parse_day(s: str | None, default: date) -> date:
    if not s:
        return default
    return date.fromisoformat(s[:10])


def _range(date_from: str | None, date_to: str | None) -> tuple[datetime, datetime]:
    today = datetime.now(UTC).date()
    start_d = _parse_day(date_from, today - timedelta(days=29))
    end_d = _parse_day(date_to, today)
    start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=UTC)
    end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=UTC) + timedelta(days=1)
    return start, end


def _bucket_key(dt: datetime, granularity: str) -> str:
    d = dt.date() if isinstance(dt, datetime) else dt
    if granularity == "year":
        return f"{d.year}"
    if granularity == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if granularity == "month":
        return f"{d.year}-{d.month:02d}"
    return f"{d.year}-{d.month:02d}-{d.day:02d}"


def _zero() -> dict:
    return {"revenue": Decimal("0"), "commission": Decimal("0"), "refunds": Decimal("0")}


@router.get("/records")
def finance_records(
    keyword: str | None = Query(default=None, description="学员姓名/电话"),
    campus: str | None = Query(default=None, description="按校区筛选（学员校区）"),
    record_type: str | None = Query(default=None, description="recharge/consume/adjust/refund"),
    date_from: str | None = Query(default=None, description="YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("finance_view")),
) -> dict:
    """总流水：全学员课时流水 + 金额汇总（调课时带单价的计入金额）。"""
    from app.models.enrollment import LessonRecord as _LR
    from app.models.enrollment import Student as _ST

    stmt = select(_LR).join(_ST, _ST.id == _LR.student_id)
    count_stmt = select(func.count(_LR.id)).join(_ST, _ST.id == _LR.student_id)
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where((_ST.name.like(kw)) | (_ST.phone.like(kw)))
        count_stmt = count_stmt.where((_ST.name.like(kw)) | (_ST.phone.like(kw)))
    if campus:
        stmt = stmt.where(_ST.campus == campus)
        count_stmt = count_stmt.where(_ST.campus == campus)
    if record_type:
        stmt = stmt.where(_LR.record_type == record_type)
        count_stmt = count_stmt.where(_LR.record_type == record_type)
    start, end = _range(date_from, date_to) if (date_from or date_to) else (None, None)
    if start is not None:
        stmt = stmt.where(_LR.created_at >= start)
        count_stmt = count_stmt.where(_LR.created_at >= start)
    if end is not None:
        stmt = stmt.where(_LR.created_at < end)
        count_stmt = count_stmt.where(_LR.created_at < end)
    total = db.scalar(count_stmt) or 0
    records = list(
        db.scalars(stmt.order_by(_LR.created_at.desc()).limit(limit).offset(offset)).unique().all()
    )
    items = []
    sum_in = Decimal("0")
    sum_out = Decimal("0")
    for rec in records:
        stu = rec.student
        op_name = rec.operator.name if rec.operator else None
        items.append(
            {
                "id": str(rec.id),
                "student_id": str(rec.student_id),
                "student_name": stu.name if stu else "—",
                "campus": stu.campus if stu else None,
                "record_type": rec.record_type,
                "delta": str(rec.delta),
                "balance_after": str(rec.balance_after),
                "unit_price": str(rec.unit_price) if rec.unit_price is not None else None,
                "amount": str(rec.amount) if rec.amount is not None else None,
                "remark": rec.remark,
                "operator_name": op_name,
                "created_at": rec.created_at.isoformat() if rec.created_at else None,
            }
        )
    sum_rows = list(db.execute(stmt.with_only_columns(_LR.amount, _LR.delta)).all())
    for amt, delta in sum_rows:
        if amt is None:
            continue
        if Decimal(str(delta)) >= 0:
            sum_in += Decimal(str(amt))
        else:
            sum_out += Decimal(str(amt))
    return {
        "items": items,
        "total": total,
        "summary": {
            "amount_in": str(sum_in.quantize(Decimal("0.01"))),
            "amount_out": str(sum_out.quantize(Decimal("0.01"))),
            "amount_net": str((sum_in + sum_out).quantize(Decimal("0.01"))),
        },
    }


@router.get("/overview")
def finance_overview(
    granularity: str = Query(default="day", description="day|month|quarter|year"),
    date_from: str | None = Query(default=None, description="YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD"),
    campus: str | None = Query(default=None, description="按校区筛选（学员校区）"),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("finance_view")),
) -> dict:
    """创收总览：按粒度分桶的创收/绩效/退款/实收 + 合计。"""
    if granularity not in ("day", "month", "quarter", "year"):
        granularity = "day"
    start, end = _range(date_from, date_to)

    from app.models.enrollment import Student as _Student

    def _campus_ids():
        if not campus:
            return None
        return set(
            db.scalars(select(_Student.id).where(_Student.campus == campus)).all()
        )

    _cids = _campus_ids()
    _stmt = select(RevenueLedger).where(
        RevenueLedger.consumed_at >= start, RevenueLedger.consumed_at < end
    )
    if _cids is not None:
        _stmt = _stmt.where(RevenueLedger.student_id.in_(_cids) if _cids else False)
    rows = list(db.scalars(_stmt).all())
    refunds = list(
        db.scalars(
            select(Order).where(
                Order.status == OrderStatus.REFUNDED.value,
                Order.refunded_at.isnot(None),
                Order.refunded_at >= start,
                Order.refunded_at < end,
            )
        ).all()
    )

    buckets: dict[str, dict] = {}
    for r in rows:
        key = _bucket_key(r.consumed_at, granularity)
        b = buckets.setdefault(key, _zero())
        b["revenue"] += Decimal(str(r.amount))
        b["commission"] += Decimal(str(r.commission))
    for o in refunds:
        key = _bucket_key(o.refunded_at, granularity)
        b = buckets.setdefault(key, _zero())
        b["refunds"] += Decimal(str(o.refund_amount or 0))
    _rate_note = "支付转化率 = 已支付单数 / 下单总数"

    items = []
    totals = {"revenue": Decimal("0"), "commission": Decimal("0"), "refunds": Decimal("0")}
    for key in sorted(buckets):
        b = buckets[key]
        net = b["revenue"] - b["commission"] - b["refunds"]
        items.append(
            {
                "label": key,
                "revenue": str(b["revenue"].quantize(Decimal("0.01"))),
                "commission": str(b["commission"].quantize(Decimal("0.01"))),
                "refunds": str(b["refunds"].quantize(Decimal("0.01"))),
                "net": str(net.quantize(Decimal("0.01"))),
            }
        )
        totals["revenue"] += b["revenue"]
        totals["commission"] += b["commission"]
        totals["refunds"] += b["refunds"]
    total_net = totals["revenue"] - totals["commission"] - totals["refunds"]
    return {
        "granularity": granularity,
        "items": items,
        "totals": {
            "revenue": str(totals["revenue"].quantize(Decimal("0.01"))),
            "commission": str(totals["commission"].quantize(Decimal("0.01"))),
            "refunds": str(totals["refunds"].quantize(Decimal("0.01"))),
            "net": str(total_net.quantize(Decimal("0.01"))),
        },
    }


@router.get("/by-subject")
def finance_by_subject(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("finance_view")),
) -> dict:
    """按科目：消耗课时/创收/绩效。"""
    start, end = _range(date_from, date_to)
    rows = db.execute(
        select(
            RevenueLedger.subject_name,
            func.sum(RevenueLedger.lessons),
            func.sum(RevenueLedger.amount),
            func.sum(RevenueLedger.commission),
            func.count(RevenueLedger.id),
        )
        .where(RevenueLedger.consumed_at >= start, RevenueLedger.consumed_at < end)
        .group_by(RevenueLedger.subject_name)
        .order_by(func.sum(RevenueLedger.amount).desc())
    ).all()
    return {
        "items": [
            {
                "subject": r[0] or "未分类",
                "lessons": str(r[1] or 0),
                "revenue": str((r[2] or Decimal("0")).quantize(Decimal("0.01"))),
                "commission": str((r[3] or Decimal("0")).quantize(Decimal("0.01"))),
                "sessions": r[4] or 0,
            }
            for r in rows
        ]
    }


@router.get("/by-teacher")
def finance_by_teacher(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("finance_view")),
) -> dict:
    """按教师：带课节数/消耗课时/绩效工资。"""
    from app.models.user import User as UserModel

    start, end = _range(date_from, date_to)
    rows = db.execute(
        select(
            RevenueLedger.teacher_id,
            func.sum(RevenueLedger.lessons),
            func.sum(RevenueLedger.amount),
            func.sum(RevenueLedger.commission),
            func.count(RevenueLedger.id),
        )
        .where(RevenueLedger.consumed_at >= start, RevenueLedger.consumed_at < end)
        .group_by(RevenueLedger.teacher_id)
        .order_by(func.sum(RevenueLedger.commission).desc())
    ).all()
    teachers = {}
    if rows:
        ids = [r[0] for r in rows if r[0] is not None]
        if ids:
            teachers = {
                u.id: u
                for u in db.scalars(
                    select(UserModel).where(UserModel.id.in_(ids))
                ).all()
            }
    return {
        "items": [
            {
                "teacher_id": str(r[0]) if r[0] else None,
                "teacher_name": teachers[r[0]].name if r[0] in teachers else "未分配",
                "lessons": str(r[1] or 0),
                "revenue": str((r[2] or Decimal("0")).quantize(Decimal("0.01"))),
                "commission": str((r[3] or Decimal("0")).quantize(Decimal("0.01"))),
                "sessions": r[4] or 0,
            }
            for r in rows
        ]
    }


@router.get("/order-stats")
def finance_order_stats(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    campus: str | None = Query(default=None, description="按校区筛选"),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("finance_view")),
) -> dict:
    """订单管理 tab 图表：按下单日期的各状态订单数/金额 + 退款金额。"""
    start, end = _range(date_from, date_to)
    from app.models.enrollment import Student as _Student2

    _stmt = select(Order).where(Order.created_at >= start, Order.created_at < end)
    if campus:
        _stmt = _stmt.join(_Student2, _Student2.id == Order.student_id).where(
            _Student2.campus == campus
        )
    rows = list(db.scalars(_stmt).all())
    refunds = list(
        db.scalars(
            select(Order).where(
                Order.status == OrderStatus.REFUNDED.value,
                Order.refunded_at.isnot(None),
                Order.refunded_at >= start,
                Order.refunded_at < end,
            )
        ).all()
    )
    buckets: dict[str, dict] = {}

    def _new_bucket():
        return {
            "orders": 0, "order_amount": Decimal("0"), "paid": 0,
            "unpaid": 0, "refunded_count": 0, "paid_amount": Decimal("0"),
            "refunds": Decimal("0"),
        }

    for o in rows:
        key = _bucket_key(o.created_at, "day")
        b = buckets.setdefault(key, _new_bucket())
        b["orders"] += 1
        b["order_amount"] += Decimal(str(o.amount or 0))
        if o.status in (OrderStatus.PAID.value, OrderStatus.CONFIRMED.value):
            b["paid"] += 1
            b["paid_amount"] += Decimal(str(o.amount or 0))
        elif o.status == OrderStatus.PENDING.value:
            b["unpaid"] += 1
        if o.status == OrderStatus.REFUNDED.value:
            b["refunded_count"] += 1
    for o in refunds:
        key = _bucket_key(o.refunded_at, "day")
        b = buckets.setdefault(key, _new_bucket())
        b["refunds"] += Decimal(str(o.refund_amount or 0))
    _items = []
    _t = {"orders": 0, "paid": 0, "unpaid": 0, "refunded_count": 0,
          "order_amount": Decimal("0"), "paid_amount": Decimal("0"), "refunds": Decimal("0")}
    for key, b in sorted(buckets.items()):
        for k in ("orders", "paid", "unpaid", "refunded_count"):
            _t[k] += b[k]
        for k in ("order_amount", "paid_amount", "refunds"):
            _t[k] += b[k]
        _items.append(
            {
                "label": key,
                "orders": b["orders"],
                "order_amount": str(b["order_amount"].quantize(Decimal("0.01"))),
                "paid": b["paid"],
                "unpaid": b["unpaid"],
                "refunded_count": b["refunded_count"],
                "paid_amount": str(b["paid_amount"].quantize(Decimal("0.01"))),
                "refunds": str(b["refunds"].quantize(Decimal("0.01"))),
            }
        )
    _rate = round(_t["paid"] / _t["orders"] * 100, 1) if _t["orders"] else 0
    return {
        "items": _items,
        "summary": {
            "orders": _t["orders"],
            "paid": _t["paid"],
            "unpaid": _t["unpaid"],
            "refunded_count": _t["refunded_count"],
            "pay_rate": _rate,
            "order_amount": str(_t["order_amount"].quantize(Decimal("0.01"))),
            "paid_amount": str(_t["paid_amount"].quantize(Decimal("0.01"))),
            "refunds": str(_t["refunds"].quantize(Decimal("0.01"))),
        },
    }


@router.get("/lesson-stats")
def finance_lesson_stats(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    campus: str | None = Query(default=None, description="按校区筛选"),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("finance_view")),
) -> dict:
    """课时创收：应耗课时（排课计划）/消耗课时（考勤账本）/课耗率/创收/绩效/盈收。"""
    from app.models.business import Subject as _Subject
    from app.models.enrollment import Class as _Class
    from app.models.schedule import Schedule as _Schedule

    start, end = _range(date_from, date_to)
    _sched_stmt = select(_Schedule).where(_Schedule.start_time >= start, _Schedule.start_time < end)
    if campus:
        _sched_stmt = _sched_stmt.join(_Class, _Class.id == _Schedule.class_id).join(
            User, User.id == _Schedule.teacher_id
        ).where(User.campus == campus)
    schedules = list(db.scalars(_sched_stmt).all())
    subjects = {s.id: s for s in db.scalars(select(_Subject)).all()}
    planned = Decimal("0")
    for s in schedules:
        subj = None
        try:
            subj = subjects.get(s.schedule_class.subject_id) if hasattr(s.schedule_class, "subject_id") else None
        except Exception:
            subj = None
        per = Decimal(str(subj.per_session)) if subj and subj.per_session else Decimal("2")
        planned += per
    _led_stmt = select(RevenueLedger).where(
        RevenueLedger.consumed_at >= start, RevenueLedger.consumed_at < end
    )
    if campus:
        from app.models.enrollment import Student as _St

        _ids = set(db.scalars(select(_St.id).where(_St.campus == campus)).all())
        _led_stmt = _led_stmt.where(RevenueLedger.student_id.in_(_ids) if _ids else False)
    ledgers = list(db.scalars(_led_stmt).all())
    consumed = sum((Decimal(str(r.lessons)) for r in ledgers), Decimal("0"))
    revenue = sum((Decimal(str(r.amount)) for r in ledgers), Decimal("0"))
    commission = sum((Decimal(str(r.commission)) for r in ledgers), Decimal("0"))
    overdraft_revenue = sum(
        (Decimal(str(r.amount)) for r in ledgers if r.is_overdraft), Decimal("0")
    )
    overdraft_lessons = sum(
        (Decimal(str(r.lessons)) for r in ledgers if r.is_overdraft), Decimal("0")
    )
    profit = revenue - commission
    rate = float((consumed / planned * 100).quantize(Decimal("0.1"))) if planned else 0
    # 应收欠款（当前时点）：所有负余额学员的欠课时 × 各自最近购包价
    from app.crud import order as _order_crud
    from app.models.enrollment import Student as _Stu

    receivable = Decimal("0")
    debtors = list(
        db.scalars(select(_Stu).where(_Stu.lesson_balance < 0)).all()
    )
    for stu in debtors:
        price, _, _ = _order_crud.last_package_price(db, student=stu)
        receivable += (-Decimal(str(stu.lesson_balance))) * price
    # 按天消耗趋势
    by_day: dict[str, Decimal] = {}
    for r in ledgers:
        k = _bucket_key(r.consumed_at, "day")
        by_day[k] = by_day.get(k, Decimal("0")) + Decimal(str(r.lessons))
    return {
        "planned_lessons": str(planned),
        "consumed_lessons": str(consumed),
        "consume_rate": rate,
        "revenue": str(revenue.quantize(Decimal("0.01"))),
        "commission": str(commission.quantize(Decimal("0.01"))),
        "profit": str(profit.quantize(Decimal("0.01"))),
        "overdraft_lessons": str(overdraft_lessons),
        "overdraft_revenue": str(overdraft_revenue.quantize(Decimal("0.01"))),
        "receivable": str(receivable.quantize(Decimal("0.01"))),
        "debtors": len(debtors),
        "sessions": len(schedules),
        "daily": [{"label": k, "lessons": str(v)} for k, v in sorted(by_day.items())],
    }


__all__ = ["router"]
