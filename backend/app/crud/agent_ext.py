"""Agent 扩展 CRUD：自定义 Agent / MCP / Skill / 全局设置（owner 维度隔离）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_ext import AgentGlobalSetting, AgentMCP, AgentSkill, AgentSkillCollection, CustomAgent, SandboxSetting


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


def get_mcp_any(db: Session, *, mcp_id) -> AgentMCP | None:
    """跨 owner 取 MCP（仅广场链路使用，调用方自行校验 visibility）。"""
    return db.scalars(select(AgentMCP).where(AgentMCP.id == mcp_id)).first()


def set_mcp_visibility(db: Session, row: AgentMCP, visibility: str) -> AgentMCP:
    row.visibility = visibility
    db.commit()
    db.refresh(row)
    return row


def list_plaza_mcps(db: Session) -> list[AgentMCP]:
    """广场 MCP：已发布 + 启用的（下架/停用即消失）。"""
    return list(
        db.scalars(
            select(AgentMCP)
            .where(AgentMCP.visibility == "plaza", AgentMCP.enabled == True)  # noqa: E712
            .order_by(AgentMCP.created_at.desc())
        ).all()
    )


def has_adopted_mcp(db: Session, *, user_id, source_mcp_id) -> bool:
    """我是否已收录（复制）过某广场 MCP。"""
    return (
        db.scalars(
            select(AgentMCP.id).where(
                AgentMCP.owner_id == user_id, AgentMCP.source_mcp_id == source_mcp_id
            )
        ).first()
        is not None
    )


def adopt_plaza_mcp(db: Session, *, user_id, source: AgentMCP) -> AgentMCP:
    """收录广场 MCP：复制为本人私有 MCP（endpoint/config 留空，由本人自行填写）。"""
    row = db.scalars(
        select(AgentMCP).where(AgentMCP.owner_id == user_id, AgentMCP.source_mcp_id == source.id)
    ).first()
    if row is not None:
        return row
    row = AgentMCP(
        owner_id=user_id,
        name=source.name,
        description=source.description,
        kind=source.kind,
        endpoint="",
        config={},
        enabled=True,
        visibility="private",
        source_mcp_id=source.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def remove_adopted_mcp(db: Session, *, user_id, source_mcp_id) -> None:
    """取消收录：删除本人由该广场 MCP 复制而来的副本。"""
    rows = list(
        db.scalars(
            select(AgentMCP).where(AgentMCP.owner_id == user_id, AgentMCP.source_mcp_id == source_mcp_id)
        ).all()
    )
    for r in rows:
        db.delete(r)
    db.commit()


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


def get_skill_any(db: Session, *, skill_id) -> AgentSkill | None:
    """跨 owner 取 Skill（仅广场链路使用，调用方自行校验 visibility）。"""
    return db.scalars(select(AgentSkill).where(AgentSkill.id == skill_id)).first()


def set_skill_visibility(db: Session, row: AgentSkill, visibility: str) -> AgentSkill:
    row.visibility = visibility
    db.commit()
    db.refresh(row)
    return row


def list_plaza_skills(db: Session) -> list[AgentSkill]:
    """广场 Skill：已发布 + 启用的（按下架/停用即消失）。"""
    return list(
        db.scalars(
            select(AgentSkill)
            .where(AgentSkill.visibility == "plaza", AgentSkill.enabled == True)  # noqa: E712
            .order_by(AgentSkill.created_at.desc())
        ).all()
    )


def collected_skill_ids(db: Session, *, user_id) -> list:
    return list(db.scalars(select(AgentSkillCollection.skill_id).where(AgentSkillCollection.user_id == user_id)).all())


def is_skill_collected(db: Session, *, user_id, skill_id) -> bool:
    return (
        db.scalars(
            select(AgentSkillCollection.id).where(
                AgentSkillCollection.user_id == user_id, AgentSkillCollection.skill_id == skill_id
            )
        ).first()
        is not None
    )


def collect_skill(db: Session, *, user_id, skill_id) -> None:
    if not is_skill_collected(db, user_id=user_id, skill_id=skill_id):
        db.add(AgentSkillCollection(user_id=user_id, skill_id=skill_id))
        db.commit()


def uncollect_skill(db: Session, *, user_id, skill_id) -> None:
    row = db.scalars(
        select(AgentSkillCollection).where(
            AgentSkillCollection.user_id == user_id, AgentSkillCollection.skill_id == skill_id
        )
    ).first()
    if row is not None:
        db.delete(row)
        db.commit()


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
    "list_mcps", "get_mcp", "get_mcp_any", "create_mcp", "update_mcp", "delete_mcp",
    "set_mcp_visibility", "list_plaza_mcps",
    "has_adopted_mcp", "adopt_plaza_mcp", "remove_adopted_mcp",
    "list_skills", "get_skill", "get_skill_any", "create_skill", "update_skill", "delete_skill",
    "set_skill_visibility", "list_plaza_skills",
    "collected_skill_ids", "is_skill_collected", "collect_skill", "uncollect_skill",
    "get_global_setting", "upsert_global_setting",
    "get_sandbox_setting", "upsert_sandbox_setting",
]
