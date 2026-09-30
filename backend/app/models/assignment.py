import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enrollment import Student
from app.models.user import User

if TYPE_CHECKING:
    from app.models.enrollment import Class, Student


class AssignmentStatus(enum.StrEnum):
    DRAFT = "draft"            # 草稿（未发布，可编辑）
    PUBLISHED = "published"    # 已发布（待作答/进行中/已截止按提交进度动态判定）


class AssignmentMode(enum.StrEnum):
    CLASSWORK = "classwork"    # 课堂作业（随堂练习：答案默认收起，仅发到学员账号）
    HOMEWORK = "homework"      # 课后作业（常规：发布到班级，家长/学员均可见）


class QuestionType(enum.StrEnum):
    SINGLE_CHOICE = "single_choice"      # 单选题
    MULTIPLE_CHOICE = "multiple_choice"  # 多选题
    JUDGEMENT = "judgement"              # 判断题（√/×）
    CODE_FILL = "code_fill"              # 代码填空题（输入框）
    PROGRAMMING = "programming"          # 编程题（Python/C++ 代码编写）


class SubmissionStatus(enum.StrEnum):
    NOT_SUBMITTED = "not_submitted"  # 未提交（截止后锁定）
    SUBMITTED = "submitted"          # 已提交（待批改/自动判题）
    GRADED = "graded"                # 已批改（含自动判题/人工打分）


class AssignmentFolder(Base):
    """教师自定义作业分组。"""

    __tablename__ = "assignment_folders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    sort_no: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    owner: Mapped["User"] = relationship()


class Assignment(Base):
    """作业：教师出题后发布到班级，对应班级学员在客户端接收作答（M5）。

    - 状态机（教师端）：draft（草稿）→ published（已发布）
    - deadline 为可选完成时间；截止后客户端锁定作答（BR-06，服务器时间判定）
    - 发布时可同时发布到多个班级（class_links）；class_id 为主目标班级（用于列表展示）
    - 已发布的班级不可重复发布；撤回后清空发布记录，可重新选择
    """

    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classes.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    # 作业模式：classwork=课堂作业（答案默认收起，仅发学员账号）/ homework=课后作业（常规班级发布）
    mode: Mapped[str] = mapped_column(
        Enum(AssignmentMode, native_enum=False, length=16),
        default=AssignmentMode.HOMEWORK,
        index=True,
    )
    # 作业说明/知识点（作业模式 AI 出题的提示语会写入此处）
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 每种题型分值配置（如单选=2、多选=3、编程=5）；未配置时默认 1 分/题
    type_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 达标分数（教师批改后用于判定是否达标，客户端/教师端分别绿/红展示）
    passing_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 批改模式：auto=提交后直接公布答案解析；teacher_confirm=教师批改后才公布
    review_mode: Mapped[str] = mapped_column(String(16), default="auto")
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assignment_folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    folder: Mapped["AssignmentFolder | None"] = relationship()
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(AssignmentStatus, native_enum=False, length=16),
        default=AssignmentStatus.DRAFT,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
    assignment_class: Mapped["Class | None"] = relationship(foreign_keys=[class_id])
    class_links: Mapped[list["AssignmentClassLink"]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="AssignmentClassLink.published_at",
    )
    student_targets: Mapped[list["AssignmentStudentLink"]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="Question.order_no",
    )


class AssignmentClassLink(Base):
    """作业 → 班级 发布关联（M4.1 增强）：一份作业可同时发布到多个班级。

    - 同一 (assignment_id, class_id) 唯一：已发布的班级不可重复发布
    - 撤回作业时级联清空（重新发布时可再选）
    """

    __tablename__ = "assignment_class_links"
    __table_args__ = (UniqueConstraint("assignment_id", "class_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), index=True
    )
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id"), index=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    assignment: Mapped["Assignment"] = relationship(back_populates="class_links")
    cls: Mapped["Class"] = relationship()


class AssignmentStudentLink(Base):
    """作业 → 学员 定向关联（补练作业，M5 增强）。

    - 用于「仅对未达标学员可见」的补练作业：拥有定向学员的作业不再按班级公开
    - 同一 (assignment_id, student_id) 唯一
    """

    __tablename__ = "assignment_students"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)

    assignment: Mapped["Assignment"] = relationship(back_populates="student_targets")
    student: Mapped["Student"] = relationship()


class Question(Base):
    """题目：属于某份作业，按 order_no 排序。

    - type：single_choice / multiple_choice / judgement / code_fill / programming
    - options：选择题选项列表（list[str]），其他题型为空
    - answer：答案。单选=int（选项索引）；多选=list[int]；判断=bool；
      代码填空/编程题=str（参考答案/参考代码）
    - test_cases：编程题自动判题用例 `[{"input": "...", "output": "..."}]`（OQ-03=自动判题）
    - analysis：答案解析（教师端默认折叠展示）
    """

    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), index=True
    )
    order_no: Mapped[int] = mapped_column(Integer, default=1)
    type: Mapped[str] = mapped_column(
        Enum(QuestionType, native_enum=False, length=24), index=True
    )
    stem: Mapped[str] = mapped_column(Text)  # 题干
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 选择题选项
    answer: Mapped[object | None] = mapped_column(JSON, nullable=True)  # 参考答案
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)  # 解析
    difficulty: Mapped[int] = mapped_column(Integer, default=1)  # 1-10
    test_cases: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 编程题用例
    # 编程题语言：python / cpp（仅 programming 题型使用，供沙箱判题选择解释器/编译器）
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    assignment: Mapped["Assignment"] = relationship(back_populates="questions")


class Submission(Base):
    """作业提交（学员维度，M5 客户端作答使用；M4 建表预留）。

    - answers：学员答案（题号 → 答案），如 `{"1": 2, "2": [0, 2], "3": true, ...}`
    - judge_results：自动判题结果（题号 → {correct, actual, ...}），人工批改后含 score
    - 作答进度持久化于 answers，支持断点续做（FR-CL-12/13）
    """

    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id"), index=True
    )
    answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 题号 → 答案
    judge_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 满分（题目数×1，或自定义）
    status: Mapped[str] = mapped_column(
        Enum(SubmissionStatus, native_enum=False, length=24),
        default=SubmissionStatus.NOT_SUBMITTED,
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    assignment: Mapped["Assignment"] = relationship()
    student: Mapped["Student"] = relationship()


__all__ = [
    "Assignment",
    "AssignmentFolder",
    "AssignmentClassLink",
    "AssignmentStudentLink",
    "AssignmentMode",
    "AssignmentStatus",
    "Question",
    "QuestionType",
    "Submission",
    "SubmissionStatus",
]
