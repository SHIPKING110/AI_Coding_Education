"""体验课域模型：邀约记录 + 体验排课标记。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, enum_values


class InvitationStatus(enum.StrEnum):
    INVITED = "invited"  # 已邀约（记录意向，待排体验课）
    SCHEDULED = "scheduled"  # 已排体验课（待上课）
    ARRIVED = "arrived"  # 已到场上体验课
    SIGNED = "signed"  # 体验后报名成功
    LOST = "lost"  # 体验后未报名，结束服务


class Invitation(Base):
    """教务邀约记录：约到有意向家长 → 排体验课 → 到场 → 报名/流失。"""

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 邀约教务
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    parent_name: Mapped[str] = mapped_column(String(64), default="")
    parent_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    student_name: Mapped[str] = mapped_column(String(64), default="")
    subject_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(
        Enum(InvitationStatus, native_enum=False, values_callable=enum_values, length=16),
        default=InvitationStatus.INVITED,
        index=True,
    )
    # 聊天截图（本地上传 URL 列表）+ 文字备注
    chat_images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 体验学员（复用学员表，trial_status=trial）与体验排课/班级/教师
    trial_student_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("students.id"), nullable=True
    )
    trial_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedules.id"), nullable=True
    )
    trial_class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classes.id"), nullable=True
    )
    trial_teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
