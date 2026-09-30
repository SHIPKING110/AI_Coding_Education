"""课时订阅订单 CRUD（M5，FR-CL-04~08 模拟支付）：

- 家长/学员客户端下单（选择课时包）→ pending（待支付）
- 提交支付 → paid（已支付待确认，simulate pay）
- 管理员确认到账 → confirmed（课时入账 + 流水 + 通知）
- 取消订单 → cancelled
- 订单状态：pending / paid / confirmed / cancelled / refunded（预留）
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.crud import business as business_crud
from app.models.enrollment import (
    LessonPackage,
    LessonRecord,
    LessonRecordType,
    Order,
    OrderStatus,
    Student,
)


def get(db: Session, order_id: uuid.UUID) -> Order | None:
    return db.scalar(
        select(Order)
        .options(selectinload(Order.student), selectinload(Order.package))
        .where(Order.id == order_id)
    )


def create(
    db: Session,
    *,
    student_id: uuid.UUID,
    package_id: uuid.UUID,
) -> Order:
    """创建订单（待支付，+5 分钟过期）。"""
    package = db.get(LessonPackage, package_id)
    order = Order(
        student_id=student_id,
        package_id=package_id,
        amount=package.price if package else Decimal("0"),
        status=OrderStatus.PENDING.value,
        expires_at=business_crud.default_expires_at(),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def expire_stale_orders(db: Session) -> int:
    """撤销所有过期的待支付订单（pending 且 expires_at 已过）。返回撤销数。"""
    now = datetime.now(UTC)
    stale = list(
        db.scalars(
            select(Order).where(
                Order.status == OrderStatus.PENDING.value,
                Order.expires_at.isnot(None),
                Order.expires_at <= now,
            )
        ).all()
    )
    for order in stale:
        order.status = OrderStatus.CANCELLED.value
    if stale:
        db.commit()
    return len(stale)


def ensure_not_expired(db: Session, order: Order) -> None:
    """支付/确认前校验：过期则就地撤销并抛错。"""
    if (
        order.status == OrderStatus.PENDING.value
        and order.expires_at is not None
        and order.expires_at <= datetime.now(UTC)
    ):
        order.status = OrderStatus.CANCELLED.value
        db.commit()
        raise ValueError("订单已超时未支付，自动撤销，请重新下单")


def pay(db: Session, order: Order) -> Order:
    """模拟支付：pending -> paid（已支付待确认到账）。过期订单自动撤销。"""
    ensure_not_expired(db, order)
    order.status = OrderStatus.PAID.value
    order.paid_at = datetime.now(UTC)
    db.commit()
    db.refresh(order)
    return order


def cancel(db: Session, order: Order) -> Order:
    """取消订单（仅 pending/paid 可取消）。"""
    if order.status not in (OrderStatus.PENDING.value, OrderStatus.PAID.value):
        raise ValueError("当前状态不可取消")
    order.status = OrderStatus.CANCELLED.value
    db.commit()
    db.refresh(order)
    return order


def confirm(
    db: Session,
    order: Order,
    *,
    operator_id: uuid.UUID,
) -> tuple[Order, LessonRecord]:
    """管理员确认到账：订单 confirmed + 课时入账 + 流水（同事务，BR-08/BR-10）。

    - 只有 paid（已支付待确认）状态可确认
    - 到账后自动累加学员课时（LessonPackage.total_lessons）并写流水 ref_id=订单
    """
    if order.status != OrderStatus.PAID.value:
        raise ValueError("仅「已支付（待确认）」的订单可确认到账")
    package = db.get(LessonPackage, order.package_id) if order.package_id else None
    lessons = package.total_lessons if package else 0
    order.status = OrderStatus.CONFIRMED.value
    order.confirmed_at = datetime.now(UTC)
    db.flush()

    student = db.get(Student, order.student_id)
    record = None
    if lessons > 0 and student is not None:
        lessons_dec = Decimal(str(lessons))
        student.lesson_balance = Decimal(str(student.lesson_balance)) + lessons_dec
        record = LessonRecord(
            student_id=student.id,
            record_type=LessonRecordType.RECHARGE.value,
            delta=lessons_dec,
            balance_after=student.lesson_balance,
            ref_id=order.id,
            remark=(
                f"课时包订阅到账：{package.name}（{lessons} 课时）" if package else "课时订阅到账"
            ),
            operator_id=operator_id,
        )
        db.add(record)
    db.commit()
    db.refresh(order)
    if record is not None:
        db.refresh(record)
    return order, record


def _filter_stmt(
    stmt,
    *,
    student_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    keyword: str | None = None,
    campus: str | None = None,
    package_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    """订单筛选：学员/状态/姓名关键字/校区/课时包/下单时间区间。

    keyword 与 campus 都基于 Student 表，合并为一次 join 防止重复 join 报错/行翻倍。
    """
    if student_id is not None:
        stmt = stmt.where(Order.student_id == student_id)
    if status_filter is not None:
        stmt = stmt.where(Order.status == status_filter)
    if keyword or campus:
        stmt = stmt.join(Student, Order.student_id == Student.id)
        if keyword:
            stmt = stmt.where(Student.name.ilike(f"%{keyword}%"))
        if campus:
            stmt = stmt.where(Student.campus == campus)
    if package_id is not None:
        stmt = stmt.where(Order.package_id == package_id)
    if date_from is not None:
        stmt = stmt.where(Order.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Order.created_at <= date_to)
    return stmt


def list_orders(
    db: Session,
    *,
    student_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    keyword: str | None = None,
    campus: str | None = None,
    package_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Order]:
    """订单列表（可按学员/状态/姓名/校区/课包/时间区间筛选）。"""
    stmt = select(Order).options(
        selectinload(Order.student),
        selectinload(Order.package),
    )
    stmt = _filter_stmt(
        stmt,
        student_id=student_id,
        status_filter=status_filter,
        keyword=keyword,
        campus=campus,
        package_id=package_id,
        date_from=date_from,
        date_to=date_to,
    )
    stmt = stmt.order_by(Order.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).unique().all())


def count_orders(
    db: Session,
    *,
    student_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    keyword: str | None = None,
    campus: str | None = None,
    package_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> int:
    stmt = select(func.count(Order.id))
    stmt = _filter_stmt(
        stmt,
        student_id=student_id,
        status_filter=status_filter,
        keyword=keyword,
        campus=campus,
        package_id=package_id,
        date_from=date_from,
        date_to=date_to,
    )
    return db.scalar(stmt) or 0


def list_for_student(db: Session, student_id: uuid.UUID) -> list[Order]:
    """某学员全部订单。"""
    return list_orders(db, student_id=student_id)


# ---------- 退费（FIFO 计算） ----------

# 消耗记录类型：上课扣减 + 人工扣减（退费记录本身不参与复算，避免重复扣减）
_CONSUME_TYPES = (LessonRecordType.CONSUME.value, LessonRecordType.ADJUST.value)


def allocate_fifo_lots(db: Session, *, student: Student) -> list[dict]:
    """FIFO 课时批次分配（只读，不落库）：

    - 已到账订单的入账流水按时间入队（批次：purchased/price）
    - 上课/人工扣减按时间从队首扣除
    - 返回每个批次的 purchased/remaining/price（含 REFUND 流水不参与复算）
    """
    orders = {
        o.id: o
        for o in db.scalars(
            select(Order)
            .options(selectinload(Order.package))
            .where(Order.student_id == student.id)
        ).all()
    }
    recharge_ids = [oid for oid, o in orders.items() if o.status == OrderStatus.CONFIRMED.value]
    if not recharge_ids:
        return []

    recharges = list(
        db.scalars(
            select(LessonRecord)
            .where(
                LessonRecord.student_id == student.id,
                LessonRecord.record_type == LessonRecordType.RECHARGE.value,
                LessonRecord.delta > 0,
                LessonRecord.ref_id.in_(recharge_ids),
            )
            .order_by(LessonRecord.created_at.asc(), LessonRecord.id.asc())
        ).all()
    )
    pool: list[dict] = []
    for rec in recharges:
        order = orders.get(rec.ref_id)
        if order is None:
            continue
        lessons = Decimal(str(rec.delta))
        if lessons <= 0:
            continue
        price = (
            (Decimal(str(order.amount)) / lessons).quantize(Decimal("0.0001"))
            if Decimal(str(order.amount)) > 0
            else Decimal("0")
        )
        pool.append(
            {
                "order_id": order.id,
                "package_name": order.package.name if order.package else "补录课时",
                "purchased": lessons,
                "remaining": lessons,
                "price": price,
            }
        )

    consumes = list(
        db.scalars(
            select(LessonRecord)
            .where(
                LessonRecord.student_id == student.id,
                LessonRecord.record_type.in_(_CONSUME_TYPES),
                LessonRecord.delta < 0,
            )
            .order_by(LessonRecord.created_at.asc(), LessonRecord.id.asc())
        ).all()
    )
    for rec in consumes:
        need = -Decimal(str(rec.delta))
        for lot in pool:
            if need <= 0:
                break
            take = min(lot["remaining"], need)
            lot["remaining"] -= take
            need -= take
    return pool


def price_for_consume(
    db: Session, *, student: Student, lessons: Decimal
) -> tuple[Decimal, list[dict]]:
    """按 FIFO 为本次消耗定价：返回（加权单价, 涉及批次明细）。"""
    need = Decimal(str(lessons))
    total_cost = Decimal("0")
    taken = Decimal("0")
    lots: list[dict] = []
    for lot in allocate_fifo_lots(db, student=student):
        if need <= 0:
            break
        if lot["remaining"] <= 0 or lot["price"] <= 0:
            continue
        take = min(lot["remaining"], need)
        total_cost += take * lot["price"]
        taken += take
        need -= take
        lots.append(
            {
                "order_id": str(lot["order_id"]),
                "package_name": lot["package_name"],
                "lessons": str(take),
                "unit_price": str(lot["price"]),
            }
        )
    if taken <= 0:
        return Decimal("0"), []
    return (total_cost / taken).quantize(Decimal("0.0001")), lots


def _num(x: Decimal) -> int | float:
    """课时数 JSON 友好值：整数返回 int（如 5），小数返回 float（如 1.5）。"""
    f = float(x)
    return int(f) if f.is_integer() else f


def _refund_plan(
    db: Session,
    *,
    student: Student,
) -> tuple[list[dict], Decimal, Decimal]:
    """FIFO 退费计划（只读，不落库）：剩余课时按对应订单单价折算。"""
    items: list[dict] = []
    total_amount = Decimal("0")
    total_lessons = Decimal("0")
    for lot in allocate_fifo_lots(db, student=student):
        if lot["remaining"] <= 0 or lot["price"] <= 0:
            continue
        amount = (lot["price"] * lot["remaining"]).quantize(Decimal("0.01"))
        items.append(
            {
                "order_id": str(lot["order_id"]),
                "package_name": lot["package_name"],
                "purchased_lessons": _num(lot["purchased"]),
                "remaining_lessons": _num(lot["remaining"]),
                "unit_price": str(lot["price"]),
                "refund_amount": str(amount),
            }
        )
        total_amount += amount
        total_lessons += lot["remaining"]
    return items, total_amount, total_lessons


def refund_fifo_preview(db: Session, *, student: Student) -> tuple[list[dict], Decimal, Decimal]:
    """FIFO 退费预览（不落库）：返回 (items, total_amount, total_lessons)。"""
    return _refund_plan(db, student=student)


def refund_fifo(
    db: Session,
    *,
    student: Student,
    operator_id: uuid.UUID,
    note: str,
) -> tuple[list[Order], list[LessonRecord], list[dict], Decimal, Decimal]:
    """执行 FIFO 退费（同一事务）：

    - 原订单标记 refunded 并记录退款金额/明细/备注/时间
    - 学员课时余额按剩余课时扣减，同时写 REFUND 流水（家长端可看明细）
    """
    note = (note or "").strip()
    if not note:
        raise ValueError("请填写退费备注")
    items, total_amount, total_lessons = _refund_plan(db, student=student)
    if not items:
        raise ValueError("没有可退费的课时（需先确认到账且尚有剩余课时）")
    if total_lessons > Decimal(str(student.lesson_balance)):
        raise ValueError("课时余额与订单流水不一致，请先核对课时流水")

    balance = Decimal(str(student.lesson_balance))
    refunded_orders: list[Order] = []
    records: list[LessonRecord] = []
    for item in items:
        order = db.get(Order, item["order_id"])
        if order is None:
            continue
        order.status = OrderStatus.REFUNDED.value
        order.refund_amount = Decimal(item["refund_amount"])
        order.refund_note = note
        order.refund_detail = {
            "package_name": item["package_name"],
            "remaining_lessons": item["remaining_lessons"],
            "unit_price": item["unit_price"],
            "refund_amount": item["refund_amount"],
            "note": note,
        }
        order.refunded_at = datetime.now(UTC)
        refunded_orders.append(order)

        balance -= Decimal(str(item["remaining_lessons"]))
        records.append(
            LessonRecord(
                student_id=student.id,
                record_type=LessonRecordType.REFUND.value,
                delta=-Decimal(str(item["remaining_lessons"])),
                balance_after=balance,
                ref_id=order.id,
                remark=(
                    f"退费：{item['package_name']} 剩余 {item['remaining_lessons']} 课时"
                    f"（¥{item['unit_price']}/课时，共 ¥{item['refund_amount']}）"
                ),
                operator_id=operator_id,
            )
        )
    student.lesson_balance = balance
    db.add_all(records)
    db.commit()
    for order in refunded_orders:
        db.refresh(order)
    for rec in records:
        db.refresh(rec)
    db.refresh(student)
    return refunded_orders, records, items, total_amount, total_lessons


# ---------- 家长自助单笔退款 ----------

SELF_REFUND_DAYS = 7


def order_lot_status(db: Session, *, student: Student, order_id: uuid.UUID) -> dict | None:
    """某订单在 FIFO 批次中的状态：{purchased, remaining}；无批次返回 None。"""
    for lot in allocate_fifo_lots(db, student=student):
        if str(lot["order_id"]) == str(order_id):
            return {"purchased": lot["purchased"], "remaining": lot["remaining"]}
    return None


def self_refund_check(
    db: Session, *, student: Student, order: Order, now: datetime | None = None
) -> dict:
    """家长自助退款闸门检查（不落库）：返回 {ok, code, message}。

    - 仅 confirmed 可退；其余状态给对应提示
    - 下单超 7 天（按 confirmed_at，无则 created_at）→ 联系教务
    - 批次有消耗（remaining < purchased）→ 联系教务；耗尽则前端不展示按钮
    """
    now = now or datetime.now(UTC)
    if order.status != OrderStatus.CONFIRMED.value:
        return {"ok": False, "code": "status", "message": "该订单当前状态不支持自助退款"}
    base = order.confirmed_at or order.created_at
    if base is not None:
        base_aware = base if base.tzinfo else base.replace(tzinfo=UTC)
        if (now - base_aware).days >= SELF_REFUND_DAYS:
            return {
                "ok": False,
                "code": "overdue",
                "message": "课时包下单超过 7 天，需要退款请联系教务老师",
            }
    lot = order_lot_status(db, student=student, order_id=order.id)
    if lot is None:
        return {"ok": False, "code": "lot", "message": "未找到该订单的课时批次，请联系教务老师"}
    if lot["remaining"] <= 0:
        return {"ok": False, "code": "empty", "message": "该课时包已消耗完"}
    if lot["remaining"] < lot["purchased"]:
        return {
            "ok": False,
            "code": "consumed",
            "message": "该课时包已被消耗，需要退款请联系教务老师",
        }
    return {"ok": True, "code": "ok", "message": "可退款"}


def self_refund(
    db: Session,
    *,
    student: Student,
    order: Order,
    reason: str,
) -> tuple[Order, LessonRecord]:
    """执行家长自助单笔退款（同一事务）：全额退款 + 扣减该单全部课时。

    前置 self_refund_check 必须通过；余额不足（课时已被其他方式扣减）则拒绝。
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("请选择退款原因")
    check = self_refund_check(db, student=student, order=order)
    if not check["ok"]:
        raise ValueError(check["message"])
    lot = order_lot_status(db, student=student, order_id=order.id)
    assert lot is not None
    lessons = Decimal(str(lot["purchased"]))
    balance = Decimal(str(student.lesson_balance))
    if lessons > balance:
        raise ValueError("课时余额不足以退还该订单课时，请联系教务老师")

    order.status = OrderStatus.REFUNDED.value
    order.refund_amount = Decimal(str(order.amount))
    order.refund_note = reason
    order.refund_detail = {
        "package_name": order.package.name if order.package else "课时包",
        "remaining_lessons": str(lessons),
        "unit_price": str(
            (Decimal(str(order.amount)) / lessons).quantize(Decimal("0.0001"))
            if lessons > 0
            else Decimal("0")
        ),
        "refund_amount": str(order.amount),
        "note": reason,
        "channel": "parent_self",
    }
    order.refunded_at = datetime.now(UTC)

    balance -= lessons
    record = LessonRecord(
        student_id=student.id,
        record_type=LessonRecordType.REFUND.value,
        delta=-lessons,
        balance_after=balance,
        ref_id=order.id,
        remark=f"家长自助退款：{order.package.name if order.package else '课时包'}（{reason}）",
        operator_id=None,
    )
    student.lesson_balance = balance
    db.add(record)
    db.commit()
    db.refresh(order)
    db.refresh(record)
    db.refresh(student)
    return order, record
