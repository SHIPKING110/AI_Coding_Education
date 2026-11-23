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
    status: Mapped[str] = mapped_column(Enum(BankSourceStatus, native_enum=False, values_callable=enum_values, length=24), default=BankSourceStatus.UPLOADED, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    uploader: Mapped["User"] = relationship()
    bank_set: Mapped["QuestionBankSet | None"] = relationship(back_populates="source", uselist=False, cascade="all, delete-orphan")


class QuestionBankSet(Base):
    __tablename__ = "question_bank_sets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question_bank_sources.id", ondelete="CASCADE"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    institution: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    exam_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    subject: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    level: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    total_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Enum(BankSetStatus, native_enum=False, values_callable=enum_values, length=16), default=BankSetStatus.DRAFT, index=True)
    import_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    source: Mapped["QuestionBankSource"] = relationship(back_populates="bank_set")
    questions: Mapped[list["QuestionBankQuestion"]] = relationship(back_populates="bank_set", cascade="all, delete-orphan", order_by="QuestionBankQuestion.order_no")


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
    status: Mapped[str] = mapped_column(Enum(BankQuestionStatus, native_enum=False, values_callable=enum_values, length=16), default=BankQuestionStatus.DRAFT, index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
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


class PracticeAttempt(Base):
    __tablename__ = "question_bank_attempts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    bank_set_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("question_bank_sets.id"), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(Enum(PracticeMode, native_enum=False, values_callable=enum_values, length=12))
    status: Mapped[str] = mapped_column(Enum(AttemptStatus, native_enum=False, values_callable=enum_values, length=16), default=AttemptStatus.IN_PROGRESS, index=True)
    question_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
