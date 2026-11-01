"""PPT 任务契约：把「计划多少页、每页是什么」持久化，生成/补齐都以契约为唯一事实源。

为什么需要独立表：
- 消息里的 outline/spec 会被多轮对话不断覆盖，无法回答「这一版 PPT 的目标页数是多少」；
- 同一会话可能产生多个 projects 目录，必须固定 active project，避免「补齐」时另起一版；
- 页级补丁需要按 page_id 对比目标页与实际页，而不是按标题猜。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentPptTask(Base):
    """一套 PPT 的任务契约（每个会话最多一个 active）。"""

    __tablename__ = "agent_ppt_tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(index=True)
    agent_id: Mapped[str] = mapped_column(String(64), default="assistant", index=True)

    skill_id: Mapped[str] = mapped_column(String(64), default="")
    skill_name: Mapped[str] = mapped_column(String(128), default="")
    project_key: Mapped[str] = mapped_column(String(512), default="")

    title: Mapped[str] = mapped_column(String(200), default="")
    theme: Mapped[str] = mapped_column(String(32), default="brand")
    status: Mapped[str] = mapped_column(String(24), default="outline", index=True)
    target_page_count: Mapped[int] = mapped_column(Integer, default=0)
    current_page_count: Mapped[int] = mapped_column(Integer, default=0)

    # [{page_id, order, title, kind, key_points, status, svg_file, actual_title, error}]
    outline: Mapped[list | None] = mapped_column(JSON, nullable=True)
    current_pptx_url: Mapped[str] = mapped_column(String(512), default="")
    last_build_id: Mapped[str] = mapped_column(String(64), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentPptTaskEvent(Base):
    """契约变更 / 补丁 / 校验事件，用于回放「这一版为什么变成这样」。"""

    __tablename__ = "agent_ppt_task_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(48), default="", index=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


__all__ = ["AgentPptTask", "AgentPptTaskEvent"]
