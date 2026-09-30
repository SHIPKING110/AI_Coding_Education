import uuid
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from app.models.schedule import Schedule, ScheduleStatus
from app.models.user import User


def get(db: Session, schedule_id: uuid.UUID) -> Schedule | None:
    stmt = (
        select(Schedule)
        .options(
            selectinload(Schedule.schedule_class),
            selectinload(Schedule.teacher),
        )
        .where(Schedule.id == schedule_id)
    )
    return db.scalar(stmt)


def list_all(
    db: Session,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    class_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
    campus: str | None = None,
    status: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[Schedule]:
    """排课列表；campus 按教师所属校区过滤（多校区课表区分）。"""
    stmt = (
        select(Schedule)
        .options(selectinload(Schedule.schedule_class), selectinload(Schedule.teacher))
        .where(Schedule.status != ScheduleStatus.CANCELLED)
    )
    if start is not None:
        stmt = stmt.where(Schedule.end_time >= start)
    if end is not None:
        stmt = stmt.where(Schedule.start_time <= end)
    if class_id is not None:
        stmt = stmt.where(Schedule.class_id == class_id)
    if teacher_id is not None:
        stmt = stmt.where(Schedule.teacher_id == teacher_id)
    if status:
        stmt = stmt.where(Schedule.status == status)
    if campus:
        stmt = stmt.join(User, Schedule.teacher_id == User.id).where(User.campus == campus)
    # 周课表按时间早晚升序排列（同一列内 9:00 在上、14:30 在下）
    stmt = stmt.order_by(Schedule.start_time.asc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).unique().all())


def find_conflicts(
    db: Session,
    *,
    start: datetime,
    end: datetime,
    teacher_id: uuid.UUID,
    exclude_schedule_id: uuid.UUID | None = None,
) -> list[Schedule]:
    """按教师检测冲突：同一教师的其他排课在 [start,end) 时间段重叠即冲突。

    业务口径（OQ-05 澄清）：
    - 只有【同一教师】的排课在时间上重叠才算冲突；
    - 不同教师在同时段分别开班不冲突；
    - 互相冲突的课程不允许同时排出来（除非 force 强制）。
    """
    stmt = select(Schedule).options(
        selectinload(Schedule.schedule_class), selectinload(Schedule.teacher)
    )
    overlap = Schedule.status != ScheduleStatus.CANCELLED
    overlap = and_(
        overlap,
        Schedule.teacher_id == teacher_id,
        Schedule.start_time < end,
        Schedule.end_time > start,
    )
    stmt = stmt.where(overlap)
    if exclude_schedule_id is not None:
        stmt = stmt.where(Schedule.id != exclude_schedule_id)
    return list(db.scalars(stmt).unique().all())


def create(
    db: Session,
    *,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
) -> Schedule:
    s = Schedule(
        class_id=class_id,
        teacher_id=teacher_id,
        start_time=start_time,
        end_time=end_time,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def update(
    db: Session,
    schedule: Schedule,
    *,
    start_time: datetime | None,
    end_time: datetime | None,
    teacher_id: uuid.UUID | None,
) -> Schedule:
    if start_time is not None:
        schedule.start_time = start_time
    if end_time is not None:
        schedule.end_time = end_time
    if teacher_id is not None:
        schedule.teacher_id = teacher_id
    db.commit()
    db.refresh(schedule)
    return schedule


def mark_completed(db: Session, schedule: Schedule) -> None:
    schedule.status = ScheduleStatus.COMPLETED
    db.commit()


def cancel(db: Session, schedule: Schedule) -> None:
    schedule.status = ScheduleStatus.CANCELLED
    db.commit()
