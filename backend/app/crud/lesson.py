import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enrollment import (
    LessonPackage,
    LessonRecord,
    LessonRecordType,
    Order,
    OrderStatus,
    PackageStatus,
    Student,
)

# ---------- 课时流水 ----------

def add_record(
    db: Session,
    *,
    student: Student,
    delta,
    record_type: LessonRecordType,
    operator_id: uuid.UUID | None,
    ref_id: uuid.UUID | None = None,
    remark: str | None = None,
    commit: bool = True,
) -> LessonRecord:
    """追加流水并同步学员余额（同事务，delta 支持小数）。"""
    delta_dec = Decimal(str(delta))
    student.lesson_balance = Decimal(str(student.lesson_balance)) + delta_dec
    record = LessonRecord(
        student_id=student.id,
        record_type=record_type.value,
        delta=delta_dec,
        balance_after=student.lesson_balance,
        ref_id=ref_id,
        remark=remark,
        operator_id=operator_id,
    )
    db.add(record)
    if commit:
        db.commit()
        db.refresh(record)
    return record


def list_records(
    db: Session, student_id: uuid.UUID, *, limit: int = 100, offset: int = 0
) -> list[LessonRecord]:
    stmt = (
        select(LessonRecord)
        .options(selectinload(LessonRecord.operator))
        .where(LessonRecord.student_id == student_id)
        .order_by(LessonRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).unique().all())


# ---------- 课时包 ----------

def get_package(db: Session, package_id: uuid.UUID) -> LessonPackage | None:
    return db.get(LessonPackage, package_id)


def _package_stmt(
    include_inactive: bool,
    *,
    subject_id: uuid.UUID | None = None,
    tag: str | None = None,
    price_min=None,
    price_max=None,
):
    stmt = select(LessonPackage).options(selectinload(LessonPackage.subject))
    if not include_inactive:
        stmt = stmt.where(LessonPackage.status == PackageStatus.ACTIVE)
    if subject_id is not None:
        stmt = stmt.where(LessonPackage.subject_id == subject_id)
    if tag is not None:
        stmt = stmt.where(LessonPackage.tag == tag)
    if price_min is not None:
        stmt = stmt.where(LessonPackage.price >= price_min)
    if price_max is not None:
        stmt = stmt.where(LessonPackage.price <= price_max)
    return stmt


def count_packages(
    db: Session,
    *,
    include_inactive: bool = False,
    subject_id: uuid.UUID | None = None,
    tag: str | None = None,
    price_min=None,
    price_max=None,
) -> int:
    stmt = _package_stmt(
        include_inactive,
        subject_id=subject_id,
        tag=tag,
        price_min=price_min,
        price_max=price_max,
    )
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def list_packages(
    db: Session,
    *,
    include_inactive: bool = False,
    subject_id: uuid.UUID | None = None,
    tag: str | None = None,
    price_min=None,
    price_max=None,
    limit: int = 100,
    offset: int = 0,
) -> list[LessonPackage]:
    stmt = (
        _package_stmt(
            include_inactive,
            subject_id=subject_id,
            tag=tag,
            price_min=price_min,
            price_max=price_max,
        )
        .order_by(LessonPackage.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).unique().all())


def package_paid_count(db: Session, package_id: uuid.UUID) -> int:
    """某课时包的支付人数（paid + confirmed 去重学员数）。"""
    stmt = (
        select(func.count(func.distinct(Order.student_id)))
        .where(Order.package_id == package_id)
        .where(Order.status.in_([OrderStatus.PAID.value, OrderStatus.CONFIRMED.value]))
    )
    return db.scalar(stmt) or 0


def package_has_paid_orders(db: Session, package_id: uuid.UUID) -> bool:
    stmt = (
        select(func.count(Order.id))
        .where(Order.package_id == package_id)
        .where(Order.status.in_([OrderStatus.PAID.value, OrderStatus.CONFIRMED.value]))
    )
    return bool(db.scalar(stmt))


def is_on_sale(package: LessonPackage, now: datetime | None = None) -> bool:
    """活动包是否在售卖时间窗内（常规包恒为 True）。"""
    if package.tag != "activity":
        return True
    now = now or datetime.now(UTC)
    if package.sale_start is not None:
        start = package.sale_start
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        if now < start:
            return False
    if package.sale_end is not None:
        end = package.sale_end
        end = end if end.tzinfo else end.replace(tzinfo=UTC)
        if now > end:
            return False
    return True


def create_package(
    db: Session,
    *,
    name: str,
    price,
    total_lessons: int,
    cover_image: str | None,
    subject_id: uuid.UUID | None = None,
    tag: str = "regular",
    sale_start=None,
    sale_end=None,
) -> LessonPackage:
    package = LessonPackage(
        name=name,
        price=price,
        total_lessons=total_lessons,
        cover_image=cover_image,
        subject_id=subject_id,
        tag=tag,
        sale_start=sale_start,
        sale_end=sale_end,
        published_at=datetime.now(UTC),
    )
    db.add(package)
    db.commit()
    db.refresh(package)
    return package


def update_package(
    db: Session,
    package: LessonPackage,
    *,
    name: str | None,
    price,
    total_lessons: int | None,
    cover_image: str | None,
    status: str | None,
    subject_id: uuid.UUID | None = None,
    tag: str | None = None,
    sale_start=None,
    sale_end=None,
    subject_id_set: bool = False,
) -> LessonPackage:
    if name is not None:
        package.name = name
    if price is not None:
        package.price = price
    if total_lessons is not None:
        package.total_lessons = total_lessons
    if cover_image is not None:
        package.cover_image = cover_image
    if status is not None:
        if status == PackageStatus.ACTIVE.value and package.published_at is None:
            package.published_at = datetime.now(UTC)
        package.status = status
    if subject_id_set:
        package.subject_id = subject_id
    if tag is not None:
        package.tag = tag
    if sale_start is not None:
        package.sale_start = sale_start
    if sale_end is not None:
        package.sale_end = sale_end
    db.commit()
    db.refresh(package)
    return package
