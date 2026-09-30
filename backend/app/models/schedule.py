import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enrollment import Class, Student
from app.models.user import User


class ScheduleStatus(enum.StrEnum):
    SCHEDULED = "scheduled"    # 已排期（未上）
    COMPLETED = "completed"    # 已上课（考勤/划课时完成）
    CANCELLED = "cancelled"    # 已取消


class AttendanceStatus(enum.StrEnum):
    UNMARKED = "unmarked"      # 未标记
    ATTENDED = "attended"      # 已到（扣 2 课时）
    LEAVE = "leave"            # 请假（不扣）


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id"), index=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Enum(ScheduleStatus, native_enum=False, length=16), default=ScheduleStatus.SCHEDULED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系（读取时按需 eager load）
    schedule_class: Mapped["Class"] = relationship(foreign_keys=[class_id])
    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])


class Attendance(Base):
    __tablename__ = "attendances"
    __table_args__ = (UniqueConstraint("schedule_id", "student_id", name="uq_schedule_student"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedules.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    status: Mapped[str] = mapped_column(
        Enum(AttendanceStatus, native_enum=False, length=16), default=AttendanceStatus.UNMARKED
    )
    operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped["Student"] = relationship()
