"""Agent 工作台持久化模型：会话 / 消息 / 长期记忆 / 会话摘要。

短期记忆 = 当前会话滑动窗口 + agent_conversation_summaries 滚动摘要；
长期记忆 = agent_memories（owner + agent 维度）。
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    context_ref: Mapped[dict] = mapped_column(JSON, default=dict)
    title: Mapped[str] = mapped_column(String(160), default="新的对话")
    rag_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    stage: Mapped[str] = mapped_column(String(32), default="data")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    share_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentMemory(Base):
    __tablename__ = "agent_memories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text, default="")
    # —— 记忆生命周期（写入/强化/压缩/删除闭环所需）——
    # 分类：preference=偏好 / fact=事实知识 / experience=历史经验。
    # 一次性指令（“这次详细点”）不写入，仅作当轮上下文。
    category: Mapped[str] = mapped_column(String(16), default="preference", server_default="preference")
    importance: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")  # 重要度 0~1
    confidence: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")  # 置信度 0~1
    use_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 命中次数（强化信号）
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 最后命中（时间衰减）
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentConversationSummary(Base):
    __tablename__ = "agent_conversation_summaries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"), unique=True, index=True
    )
    summary: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentWorkingMemory(Base):
    """跨会话工作记忆：当前任务目标、已完成步骤、最近结果。

    作用域是 owner + agent（不是单个会话），新开对话仍能接着上次进度。
    同一用户同一 Agent 同时只保留一条 status=active。
    """

    __tablename__ = "agent_working_memories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    goal: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = [
    "AgentConversation",
    "AgentMessage",
    "AgentMemory",
    "AgentConversationSummary",
    "AgentWorkingMemory",
]
