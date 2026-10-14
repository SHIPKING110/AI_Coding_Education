"""Agent 扩展模型：自定义 Agent / MCP / Skill / 全局作用设置。

- 自定义 Agent：owner 维度，agent_id 全局唯一（custom_{owner末8}+序号防冲）。
- MCP：外部工具接入点（HTTP endpoint + headers + 描述），enabled 开关。
- Skill：本地技能（system 追加指令/话术），enabled 开关。
- 全局设置：每 owner 一行，default_mcp_ids / default_skill_ids 全局作用于该账户所有 Agent；
  单个 Agent 的 mcp_ids/skill_ids 字段做 per-agent 绑定（与全局取并集）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CustomAgent(Base):
    __tablename__ = "custom_agents"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), default="自定义 Agent")
    description: Mapped[str] = mapped_column(String(256), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    supports_rag: Mapped[bool] = mapped_column(Boolean, default=True)
    icon: Mapped[str] = mapped_column(String(32), default="assistant")
    stages: Mapped[list] = mapped_column(JSON, default=list)
    mcp_ids: Mapped[list] = mapped_column(JSON, default=list)
    skill_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentMCP(Base):
    __tablename__ = "agent_mcps"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="MCP 服务")
    kind: Mapped[str] = mapped_column(String(32), default="streamable_http")
    endpoint: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(String(256), default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentSkill(Base):
    __tablename__ = "agent_skills"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="Skill")
    description: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    files: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentGlobalSetting(Base):
    __tablename__ = "agent_global_settings"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    default_mcp_ids: Mapped[list] = mapped_column(JSON, default=list)
    default_skill_ids: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["CustomAgent", "AgentMCP", "AgentSkill", "AgentGlobalSetting", "SandboxSetting"]


class SandboxSetting(Base):
    """Skill 脚本沙箱配置（按用户）：本地受控执行 或 阿里云函数计算远程沙箱。"""

    __tablename__ = "sandbox_settings"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(16), default="local")
    endpoint: Mapped[str] = mapped_column(String(512), default="")
    token: Mapped[str] = mapped_column(String(256), default="")
    timeout_s: Mapped[int] = mapped_column(default=25)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
