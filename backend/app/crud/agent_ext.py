"""Agent 扩展 CRUD：自定义 Agent / MCP / Skill / 全局设置（owner 维度隔离）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_ext import AgentGlobalSetting, AgentMCP, AgentSkill, CustomAgent, SandboxSetting


# ---------------- 自定义 Agent ----------------

def list_custom_agents(db: Session, *, owner_id) -> list[CustomAgent]:
    return list(
        db.scalars(
            select(CustomAgent).where(CustomAgent.owner_id == owner_id).order_by(CustomAgent.created_at.desc())
        ).all()
    )


def get_custom_agent(db: Session, *, owner_id, agent_id: str) -> CustomAgent | None:
    return db.scalars(
        select(CustomAgent).where(CustomAgent.owner_id == owner_id, CustomAgent.agent_id == agent_id)
    ).first()


def create_custom_agent(db: Session, *, owner_id, agent_id: str, **fields) -> CustomAgent:
    row = CustomAgent(owner_id=owner_id, agent_id=agent_id, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_sandbox_setting(db: Session, *, owner_id) -> SandboxSetting | None:
    return db.scalars(select(SandboxSetting).where(SandboxSetting.owner_id == owner_id)).first()


def upsert_sandbox_setting(db: Session, *, owner_id, **fields) -> SandboxSetting:
    row = get_sandbox_setting(db, owner_id=owner_id)
    if row is None:
        row = SandboxSetting(owner_id=owner_id, **{k: v for k, v in fields.items() if v is not None})
        db.add(row)
    else:
        for k, v in fields.items():
            if hasattr(row, k) and v is not None:
                setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


def update_custom_agent(db: Session, row: CustomAgent, **fields) -> CustomAgent:
    for k, v in fields.items():
        if hasattr(row, k) and v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


def delete_custom_agent(db: Session, row: CustomAgent) -> None:
    db.delete(row)
    db.commit()


# ---------------- MCP ----------------

def list_mcps(db: Session, *, owner_id) -> list[AgentMCP]:
    return list(
        db.scalars(select(AgentMCP).where(AgentMCP.owner_id == owner_id).order_by(AgentMCP.created_at.desc())).all()
    )


def get_mcp(db: Session, *, owner_id, mcp_id) -> AgentMCP | None:
    return db.scalars(select(AgentMCP).where(AgentMCP.owner_id == owner_id, AgentMCP.id == mcp_id)).first()


def create_mcp(db: Session, *, owner_id, **fields) -> AgentMCP:
    row = AgentMCP(owner_id=owner_id, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_mcp(db: Session, row: AgentMCP, **fields) -> AgentMCP:
    for k, v in fields.items():
        if hasattr(row, k) and v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


def delete_mcp(db: Session, row: AgentMCP) -> None:
    db.delete(row)
    db.commit()


# ---------------- Skill ----------------

def list_skills(db: Session, *, owner_id) -> list[AgentSkill]:
    return list(
        db.scalars(select(AgentSkill).where(AgentSkill.owner_id == owner_id).order_by(AgentSkill.created_at.desc())).all()
    )


def get_skill(db: Session, *, owner_id, skill_id) -> AgentSkill | None:
    return db.scalars(select(AgentSkill).where(AgentSkill.owner_id == owner_id, AgentSkill.id == skill_id)).first()


def create_skill(db: Session, *, owner_id, **fields) -> AgentSkill:
    row = AgentSkill(owner_id=owner_id, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_skill(db: Session, row: AgentSkill, **fields) -> AgentSkill:
    for k, v in fields.items():
        if hasattr(row, k) and v is not None:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


def delete_skill(db: Session, row: AgentSkill) -> None:
    db.delete(row)
    db.commit()


# ---------------- 全局设置 ----------------

def get_global_setting(db: Session, *, owner_id) -> AgentGlobalSetting | None:
    return db.scalars(select(AgentGlobalSetting).where(AgentGlobalSetting.owner_id == owner_id)).first()


def upsert_global_setting(db: Session, *, owner_id, default_mcp_ids=None, default_skill_ids=None) -> AgentGlobalSetting:
    row = get_global_setting(db, owner_id=owner_id)
    if row is None:
        row = AgentGlobalSetting(owner_id=owner_id, default_mcp_ids=default_mcp_ids or [], default_skill_ids=default_skill_ids or [])
        db.add(row)
    else:
        if default_mcp_ids is not None:
            row.default_mcp_ids = default_mcp_ids
        if default_skill_ids is not None:
            row.default_skill_ids = default_skill_ids
    db.commit()
    db.refresh(row)
    return row


__all__ = [
    "list_custom_agents", "get_custom_agent", "create_custom_agent", "update_custom_agent", "delete_custom_agent",
    "list_mcps", "get_mcp", "create_mcp", "update_mcp", "delete_mcp",
    "list_skills", "get_skill", "create_skill", "update_skill", "delete_skill",
    "get_global_setting", "upsert_global_setting",
    "get_sandbox_setting", "upsert_sandbox_setting",
]
