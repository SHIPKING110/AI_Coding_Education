import enum
import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, enum_values
from app.models.enrollment import Class, Student
from app.models.user import User


class EvaluationStatus(enum.StrEnum):
    DRAFT = "draft"          # 草稿（教师审核编辑中，BR-05）
    PUBLISHED = "published"  # 已发布（随家长会发送给家长，可撤回重编辑）


class Evaluation(Base):
    """学员评估表（M6 家长会场景，FR-EV-01~05）。

    - 每学期/季度家长会前，教师基于学员近 3 个月已发布课后反馈 + 考勤/课时/作业数据
      生成综合评估（AI 草稿 + 人工审核修改 + 对话式优化）
    - content 结构化（JSON）：
      `{summary, subjects: [{name, level, comment}], progress, to_improve, suggestions}`
      subjects 为学科能力条目（level 1-5，前端星级/进度条展示，PPT 渲染能力条）
    - stats：生成时的数据快照（出勤/课时/反馈数/作业得分率），评估依据可追溯
    - ai_draft：AI 原始草稿快照（content + model + generated_at）
    - 唯一约束：同一学员同一评估周期仅一份（幂等创建 = 更新）
    """

    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint("student_id", "period_start", "period_end", name="uq_evaluation_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    # 评估周期（默认近 3 个月：家长会每 3 个月一次）
    period_start: Mapped[date] = mapped_column(Date())
    period_end: Mapped[date] = mapped_column(Date())
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 家长会 PPT（FR-EV-05，uploads/ppt/ 相对路径）
    ppt_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(EvaluationStatus, native_enum=False, values_callable=enum_values, length=16), default=EvaluationStatus.DRAFT
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    student: Mapped["Student"] = relationship()
    teacher: Mapped["User"] = relationship()


class ClassPpt(Base):
    """班级家长会 PPT 生成记录：AI 提炼的班级文案落库，支持预览/编辑/秒级重排版。

    - content：AI 提炼/教师编辑后的班级汇报文案
      `{title, class_summary, ability_comment, highlights, to_improve, next_plan, home_suggestions}`
    - stats/averages/honor_roll：生成时的班级素材快照（统计/能力均分/进步之星），
      编辑文案后重排版无需重算素材、也不再调用 LLM
    - ppt_url：最近一次排版的 PPT 文件（uploads/ppt/ 相对路径）
    - 唯一约束：同一班级同一周期仅一份（重新生成 = 覆盖更新）
    """

    __tablename__ = "class_ppts"
    __table_args__ = (
        UniqueConstraint("class_id", "period_start", "period_end", name="uq_class_ppt_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id"), index=True)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date())
    period_end: Mapped[date] = mapped_column(Date())
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    averages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    honor_roll: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ppt_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cls: Mapped["Class"] = relationship()
    teacher: Mapped["User"] = relationship()
    # 素材指纹（regen-dedup）：提交时对班级素材快照取哈希，
    # 重提炼前比对，无变化则提示并要求二次确认（force=true 才放行）
    material_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


__all__ = ["ClassPpt", "Evaluation", "EvaluationStatus"]
