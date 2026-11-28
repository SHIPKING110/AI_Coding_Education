"""可审核、可复用的题库领域模型。"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, enum_values
from app.models.user import User


class BankSourceStatus(enum.StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    REVIEW_REQUIRED = "review_required"
    PUBLISHED = "published"
    FAILED = "failed"


class BankSetStatus(enum.StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class BankQuestionStatus(enum.StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class PracticeMode(enum.StrEnum):
    PRACTICE = "practice"
    EXAM = "exam"


class AttemptStatus(enum.StrEnum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    EVALUATED = "evaluated"


class QuestionBankSource(Base):
    __tablename__ = "question_bank_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(
        Enum(BankSourceStatus, native_enum=False, values_callable=enum_values, length=24),
        default=BankSourceStatus.UPLOADED,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    uploader: Mapped["User"] = relationship()
    bank_set: Mapped["QuestionBankSet | None"] = relationship(
        back_populates="source", uselist=False, cascade="all, delete-orphan"
    )


class QuestionBankSet(Base):
    __tablename__ = "question_bank_sets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_bank_sources.id", ondelete="CASCADE"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    institution: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    exam_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    exam_month: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)
    subject: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    level: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    total_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(BankSetStatus, native_enum=False, values_callable=enum_values, length=16),
        default=BankSetStatus.DRAFT,
        index=True,
    )
    import_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    source: Mapped["QuestionBankSource"] = relationship(back_populates="bank_set")
    questions: Mapped[list["QuestionBankQuestion"]] = relationship(
        back_populates="bank_set", cascade="all, delete-orphan", order_by="QuestionBankQuestion.order_no"
    )


class QuestionBankQuestion(Base):
    __tablename__ = "question_bank_questions"
    __table_args__ = (UniqueConstraint("bank_set_id", "order_no"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    bank_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question_bank_sets.id", ondelete="CASCADE"), index=True)
    order_no: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(24), index=True)
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    score: Mapped[int] = mapped_column(Integer, default=1)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reference_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_cases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    media: Mapped[list | None] = mapped_column(JSON, nullable=True)
    knowledge_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(BankQuestionStatus, native_enum=False, values_callable=enum_values, length=16),
        default=BankQuestionStatus.DRAFT,
        index=True,
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    bank_set: Mapped["QuestionBankSet"] = relationship(back_populates="questions")


class QuestionBankBlueprint(Base):
    __tablename__ = "question_bank_blueprints"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    level: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    rules: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionBankUserMark(Base):
    __tablename__ = "question_bank_user_marks"
    __table_args__ = (UniqueConstraint("user_id", "student_id", "question_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=True, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_bank_questions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PracticeAttempt(Base):
    __tablename__ = "question_bank_attempts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("students.id"), nullable=True, index=True)
    bank_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("question_bank_sets.id"), nullable=True, index=True
    )
    # practice=即时反馈；exam=交卷后统一评分。kind 细分来源：quick/aggregate/marked/exam_set/exam_random/set_practice
    mode: Mapped[str] = mapped_column(Enum(PracticeMode, native_enum=False, values_callable=enum_values, length=12))
    kind: Mapped[str] = mapped_column(String(24), default="set_practice", index=True)
    status: Mapped[str] = mapped_column(
        Enum(AttemptStatus, native_enum=False, values_callable=enum_values, length=16),
        default=AttemptStatus.IN_PROGRESS,
        index=True,
    )
    paper_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    paper_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    question_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    question_results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuestionBankAiReview(Base):
    """AI 校准/打标审计记录：保留修改前后快照，支持回滚并避免重复计费。"""

    __tablename__ = "question_bank_ai_reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_bank_questions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), index=True)  # validate / tag / clean
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="suggested", index=True)  # suggested/applied/reverted/error
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    issues: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionBankKpTaxonomy(Base):
    """知识点受控词表：AI 打标优先从候选词中选，未知项落为候选待审。"""

    __tablename__ = "question_bank_kp_taxonomy"
    __table_args__ = (UniqueConstraint("subject", "level", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    subject: Mapped[str] = mapped_column(String(80), index=True)
    level: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    parent: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active/candidate
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PracticeAbilityReport(Base):
    """能力评语缓存：同一用户/学员+统计指纹只生成一次，避免重复消耗 Token。"""

    __tablename__ = "practice_ability_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=True, index=True
    )
    stats_hash: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionBankAiTask(Base):
    """题库 AI 批量任务：持久化到数据库，进程重启/滚动部署后进度仍可查询与继续展示。"""

    __tablename__ = "question_bank_ai_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # validate / tag
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)  # running/done/error
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(255), default="")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
