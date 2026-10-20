"""家长端 AI 客服账本（P0）：会话头 + 消息（不可丢，可审计）。

- ParentServiceThread：一次会话（open=进行中 / closed=已解决 / escalated=已转人工）。
- ParentServiceMessage：完整消息记录；assistant 行含 tokens 与 retrieval_diag（费用归因 + 引用备查）。
- Redis 只存可重建的热窗口（P1），账本唯一真相源是这两张表。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

THREAD_OPEN = "open"
THREAD_CLOSED = "closed"
THREAD_ESCALATED = "escalated"

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_STAFF = "staff"


class ParentServiceThread(Base):
    __tablename__ = "parent_service_threads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 家长用户（匿名会话为空，用 anon_key 区分）
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    anon_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default=THREAD_OPEN, index=True)
    risk_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ParentServiceMessage(Base):
    __tablename__ = "parent_service_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parent_service_threads.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user / assistant / staff
    content: Mapped[str] = mapped_column(Text, default="")
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieval_diag: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "ROLE_ASSISTANT",
    "ROLE_STAFF",
    "ROLE_USER",
    "THREAD_CLOSED",
    "THREAD_ESCALATED",
    "THREAD_OPEN",
    "ParentServiceMessage",
    "ParentServiceThread",
]
