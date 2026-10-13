"""Agent 扩展 API：自定义 Agent / MCP / Skill / 全局设置（owner 维度）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.crud import agent_ext as ext_crud
from app.models.user import User
from app.services import agent_registry

router = APIRouter(prefix="/agents/ext", tags=["agents-ext"])

BUILTIN_IDS = {a["id"] for a in agent_registry.AGENTS}


def _agent_out(c) -> dict:
    return {
        "agent_id": c.agent_id, "name": c.name, "description": c.description,
        "system_prompt": c.system_prompt, "supports_rag": c.supports_rag,
        "icon": c.icon, "stages": c.stages or [], "mcp_ids": c.mcp_ids or [],
        "skill_ids": c.skill_ids or [], "custom": True,
    }


def _mcp_out(m) -> dict:
    return {
        "id": str(m.id), "name": m.name, "kind": m.kind, "endpoint": m.endpoint,
        "description": m.description, "config": m.config or {}, "enabled": m.enabled,
    }


def _skill_out(s) -> dict:
    return {
        "id": str(s.id), "name": s.name, "description": s.description,
        "content": s.content, "enabled": s.enabled,
    }


# ---------------- 自定义 Agent ----------------

class AgentIn(BaseModel):
    name: str = Field(max_length=64)
    description: str = Field(default="", max_length=256)
    system_prompt: str = Field(default="")
    supports_rag: bool = True
    icon: str = Field(default="assistant", max_length=32)
    stages: list[dict] = Field(default_factory=list)
    mcp_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)


@router.get("/agents")
def list_custom_agents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": [_agent_out(c) for c in ext_crud.list_custom_agents(db, owner_id=user.id)]}


@router.post("/agents", status_code=status.HTTP_201_CREATED)
def create_custom_agent(body: AgentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = len(ext_crud.list_custom_agents(db, owner_id=user.id))
    agent_id = f"custom_{str(user.id).replace('-', '')[:8]}_{n + 1}"
    while agent_id in BUILTIN_IDS or ext_crud.get_custom_agent(db, owner_id=user.id, agent_id=agent_id):
        n += 1
        agent_id = f"custom_{str(user.id).replace('-', '')[:8]}_{n + 1}"
    c = ext_crud.create_custom_agent(db, owner_id=user.id, agent_id=agent_id, **body.model_dump())
    return _agent_out(c)


@router.get("/agents/{agent_id}")
def get_custom_agent(agent_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = ext_crud.get_custom_agent(db, owner_id=user.id, agent_id=agent_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return _agent_out(c)


@router.patch("/agents/{agent_id}")
def patch_custom_agent(agent_id: str, body: AgentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = ext_crud.get_custom_agent(db, owner_id=user.id, agent_id=agent_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    c = ext_crud.update_custom_agent(db, c, **body.model_dump())
    return _agent_out(c)


@router.delete("/agents/{agent_id}")
def delete_custom_agent(agent_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = ext_crud.get_custom_agent(db, owner_id=user.id, agent_id=agent_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    ext_crud.delete_custom_agent(db, c)
    return {"ok": True}


# ---------------- MCP ----------------

class McpIn(BaseModel):
    name: str = Field(max_length=64)
    kind: str = Field(default="http", max_length=32)
    endpoint: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=256)
    config: dict = Field(default_factory=dict)
    enabled: bool = True


@router.get("/mcps")
def list_mcps(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": [_mcp_out(m) for m in ext_crud.list_mcps(db, owner_id=user.id)]}


@router.post("/mcps", status_code=status.HTTP_201_CREATED)
def create_mcp(body: McpIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _mcp_out(ext_crud.create_mcp(db, owner_id=user.id, **body.model_dump()))


@router.patch("/mcps/{mcp_id}")
def patch_mcp(mcp_id: uuid.UUID, body: McpIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = ext_crud.get_mcp(db, owner_id=user.id, mcp_id=mcp_id)
    if m is None:
        raise HTTPException(status_code=404, detail="MCP 不存在")
    return _mcp_out(ext_crud.update_mcp(db, m, **body.model_dump()))


@router.delete("/mcps/{mcp_id}")
def delete_mcp(mcp_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = ext_crud.get_mcp(db, owner_id=user.id, mcp_id=mcp_id)
    if m is None:
        raise HTTPException(status_code=404, detail="MCP 不存在")
    ext_crud.delete_mcp(db, m)
    return {"ok": True}


# ---------------- Skill ----------------

class SkillIn(BaseModel):
    name: str = Field(max_length=64)
    description: str = Field(default="", max_length=256)
    content: str = Field(default="")
    enabled: bool = True


@router.get("/skills")
def list_skills(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": [_skill_out(s) for s in ext_crud.list_skills(db, owner_id=user.id)]}


@router.post("/skills", status_code=status.HTTP_201_CREATED)
def create_skill(body: SkillIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _skill_out(ext_crud.create_skill(db, owner_id=user.id, **body.model_dump()))


@router.patch("/skills/{skill_id}")
def patch_skill(skill_id: uuid.UUID, body: SkillIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = ext_crud.get_skill(db, owner_id=user.id, skill_id=skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return _skill_out(ext_crud.update_skill(db, s, **body.model_dump()))


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = ext_crud.get_skill(db, owner_id=user.id, skill_id=skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    ext_crud.delete_skill(db, s)
    return {"ok": True}


# ---------------- 全局设置 ----------------

class GlobalIn(BaseModel):
    default_mcp_ids: list[str] = Field(default_factory=list)
    default_skill_ids: list[str] = Field(default_factory=list)


@router.get("/global")
def get_global(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    g = ext_crud.get_global_setting(db, owner_id=user.id)
    return {"default_mcp_ids": list(g.default_mcp_ids) if g else [], "default_skill_ids": list(g.default_skill_ids) if g else []}


@router.put("/global")
def put_global(body: GlobalIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    g = ext_crud.upsert_global_setting(
        db, owner_id=user.id, default_mcp_ids=body.default_mcp_ids, default_skill_ids=body.default_skill_ids
    )
    return {"default_mcp_ids": list(g.default_mcp_ids or []), "default_skill_ids": list(g.default_skill_ids or [])}
