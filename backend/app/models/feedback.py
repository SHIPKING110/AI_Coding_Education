import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, enum_values
from app.models.enrollment import Student
from app.models.schedule import Schedule


class FeedbackStatus(enum.StrEnum):
    DRAFT = "draft"          # 草稿（未发送）
    PUBLISHED = "published"  # 已发布（已推送给家长）


class Feedback(Base):
    """课后反馈：每节课程按学员逐一生成，记录课题/内容/表现/作业/上课照片视频。

    一次课程（Schedule）对一名学员仅一条有效反馈（唯一约束），可覆盖编辑。
    """

    __tablename__ = "feedbacks"
    __table_args__ = (
        UniqueConstraint("schedule_id", "student_id", name="uq_feedback_schedule_student"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedules.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    # 反馈标题（可选，如「Python 入门 · 第3次课」）
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)       # 课题
    content: Mapped[str | None] = mapped_column(Text, nullable=True)     # 课程大致内容
    performance: Mapped[str | None] = mapped_column(Text, nullable=True)  # 课堂表现
    # 课堂评价（AI 草稿写入位置）
    evaluation: Mapped[str | None] = mapped_column(Text, nullable=True)
    homework: Mapped[str | None] = mapped_column(Text, nullable=True)    # 今日作业
    media_urls: Mapped[list[str]] = mapped_column(JSON, default=list)    # 上课照片/视频
    status: Mapped[str] = mapped_column(
        Enum(FeedbackStatus, native_enum=False, values_callable=enum_values, length=16), default=FeedbackStatus.DRAFT
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # AI 草稿预留（M3+：AI 生成反馈初稿，人工编辑后发布）
    ai_draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    schedule: Mapped["Schedule"] = relationship()
    student: Mapped["Student"] = relationship(back_populates="feedbacks")


__all__ = ["Feedback", "FeedbackStatus"]
