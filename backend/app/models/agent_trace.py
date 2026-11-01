"""Agent 任务全链路观测模型：一次对话轮次 = 一个 run，内部模型/工具/RAG/MCP/Skill = span。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentRunTrace(Base):
    """一次用户消息触发的 Agent 运行（对话轮次 / 任务运行）。"""

    __tablename__ = "agent_run_traces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    domain: Mapped[str] = mapped_column(String(32), default="agent_teacher", index=True)

    intent: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    intent_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    intent_source: Mapped[str] = mapped_column(String(16), default="rule")
    needs_rag: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rag_decision: Mapped[str] = mapped_column(String(32), default="not_applicable", index=True)
    rag_skip_reason: Mapped[str] = mapped_column(String(128), default="")
    retrieval_trace_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)

    task_kind: Mapped[str] = mapped_column(String(32), default="chat", index=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    first_token_ms: Mapped[int] = mapped_column(Integer, default=0)

    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    rag_calls: Mapped[int] = mapped_column(Integer, default=0)
    mcp_calls: Mapped[int] = mapped_column(Integer, default=0)
    skill_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)

    # PPT 任务对齐（任务式对话观测的核心指标）
    ppt_target_pages: Mapped[int] = mapped_column(Integer, default=0)
    ppt_current_pages: Mapped[int] = mapped_column(Integer, default=0)
    ppt_aligned: Mapped[bool] = mapped_column(Boolean, default=False)
    ppt_project_key: Mapped[str] = mapped_column(String(512), default="")
    artifact_url: Mapped[str] = mapped_column(String(512), default="")

    error_code: Mapped[str] = mapped_column(String(64), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AgentRunSpan(Base):
    """run 内部的一个执行片段（模型 / 工具 / RAG / MCP / Skill / 产物）。"""

    __tablename__ = "agent_run_spans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str] = mapped_column(String(48), index=True)
    span_id: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    span_type: Mapped[str] = mapped_column(String(24), default="tool", index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="ok", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    model: Mapped[str] = mapped_column(String(128), default="")
    provider: Mapped[str] = mapped_column(String(64), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0)

    summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


__all__ = ["AgentRunTrace", "AgentRunSpan"]
