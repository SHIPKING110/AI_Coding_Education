import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, enum_values
from app.models.user import User


class NotificationType(enum.StrEnum):
    SCHEDULE_REMINDER = "schedule_reminder"  # 上课提醒（FR-CL-03）
    LOW_BALANCE = "low_balance"              # 课时低余量提醒（FR-CL-01）
    ORDER_CONFIRMED = "order_confirmed"    # 订单到账确认（FR-CL-06）
    REFUND = "refund"                      # 退费通知
    FEEDBACK_PUBLISHED = "feedback_published"  # 课后反馈已发布（FR-FB-05）
    ASSIGNMENT_PUBLISHED = "assignment_published"  # 作业已发布
    SUBMISSION_SUBMITTED = "submission_submitted"  # 学员提交作业（提醒教师批改）
    SUBMISSION_GRADED = "submission_graded"  # 作业已批改（FR-CL-18）
    EVALUATION_PUBLISHED = "evaluation_published"  # 学员评估已发布（FR-EV-04，M6）
    KNOWLEDGE_INDEXED = "knowledge_indexed"  # 知识库文档索引落定（成功/失败）
    TRIAL_ASSIGNED = "trial_assigned"  # 教师被安排体验课（写明班级时间）


class Notification(Base):
    """站内通知（FR-CL-03 应用内通知 + OQ-01 微信推送预留）。

    - 通知类型：上课提醒/低余量/订单到账/反馈发布/作业发布/批改完成
    - 所有角色均可接收通知（家长/学员/教师/教务/管理员）
    - 微信推送预留：后续可扩展为微信模板消息（需商户资质，OQ-01）
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(
        Enum(NotificationType, native_enum=False, values_callable=enum_values, length=32), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    # 关联数据（如 schedule_id, student_id, order_id, assignment_id 等，JSONB 存储）
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship()


__all__ = ["Notification", "NotificationType"]
