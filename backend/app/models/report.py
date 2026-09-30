import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import User


class ReportType(enum.StrEnum):
    DAILY = "daily"       # 日报：按天归档，记录当日工作内容
    WEEKLY = "weekly"     # 周报：统计本周指标（上课人次/出勤率/缺课/新增学员）+ 文字总结
    QUARTERLY = "quarterly"  # 季度总结：基于季度内周报/日报聚合 + AI 生成 PPT
    YEARLY = "yearly"     # 年度总结：基于整年周报/日报聚合 + AI 生成 PPT


class ReportStatus(enum.StrEnum):
    DRAFT = "draft"          # 草稿（未提交）
    PUBLISHED = "published"  # 已发布（教师确认后归档，可重新编辑）


class Report(Base):
    """报告（日报/周报/季度/年度）：教师周期工作报告。

    - content：结构化正文（JSON）。日报 `{work, courses, problems, plan}`；
      周报 `{summary, highlights, problems, next_plan}`；
      季度/年度 `{summary, highlights, problems, next_plan, stats_notes}`
      （由周期内已发布周报聚合 + AI 生成，人工审核修改）
    - stats：自动统计快照（JSON）。
    - ppt_url：季度/年度生成的 PPT 文件相对路径（uploads/ppt/）；其他类型为空
    - 唯一约束：同一教师同类型同一周期仅一份（幂等创建 = 更新）
    """

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint(
            "type", "teacher_id", "period_start", "period_end", name="uq_report_period"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(
        Enum(ReportType, native_enum=False, length=16), index=True
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    # 周期：日报=当日（start==end）；周报=周一~周日；季度/年度=起止日期
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ppt_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(ReportStatus, native_enum=False, length=16), default=ReportStatus.DRAFT
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    teacher: Mapped["User"] = relationship()


__all__ = ["Report", "ReportType", "ReportStatus"]
