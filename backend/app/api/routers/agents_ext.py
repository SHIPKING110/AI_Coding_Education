"""Agent 扩展 API：自定义 Agent / MCP / Skill / 全局设置（owner 维度）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_teacher_permission
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


def _mcp_out(m, *, collected: bool = False, mine: bool = False) -> dict:
    out = {
        "id": str(m.id), "name": m.name, "kind": m.kind, "endpoint": m.endpoint,
        "description": m.description, "config": m.config or {}, "enabled": m.enabled,
        "visibility": getattr(m, "visibility", "private") or "private",
        "collected": collected, "mine": mine,
        "collected_from_plaza": bool(getattr(m, "source_mcp_id", None)),
    }
    # 隐私保护：非发布者一律不下发 endpoint / config（广场上别人只能收录为模板，接入地址与密钥由收录者自己填）
    if not mine:
        has_ep = bool((m.endpoint or "").strip())
        out["endpoint"] = ""
        out["config"] = {}
        out["endpoint_hidden"] = has_ep
    return out


def _skill_out(s, *, collected: bool = False, mine: bool = False) -> dict:
    return {
        "id": str(s.id), "name": s.name, "description": s.description,
        "content": s.content, "files": list(s.files or []), "enabled": s.enabled,
        "visibility": getattr(s, "visibility", "private") or "private",
        "collected": collected, "mine": mine,
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
    kind: str = Field(default="streamable_http", max_length=32, description="streamable_http | http")
    endpoint: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=256)
    config: dict = Field(default_factory=dict, description="可选 headers，如 {headers: {Authorization: 'Bearer x'}}")
    enabled: bool = True


@router.get("/mcps")
def list_mcps(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": [_mcp_out(m, mine=True) for m in ext_crud.list_mcps(db, owner_id=user.id)]}


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


@router.post("/mcps/{mcp_id}/publish")
def publish_mcp(mcp_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """发布 MCP 到广场：其他教师可收录引用（直接用同一 endpoint/config）。"""
    m = ext_crud.get_mcp(db, owner_id=user.id, mcp_id=mcp_id)
    if m is None:
        raise HTTPException(status_code=404, detail="MCP 不存在")
    if not (m.endpoint or "").strip():
        raise HTTPException(status_code=400, detail="MCP 未填写 endpoint，暂不能发布")
    return _mcp_out(ext_crud.set_mcp_visibility(db, m, "plaza"), mine=True)


@router.post("/mcps/{mcp_id}/unpublish")
def unpublish_mcp(mcp_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = ext_crud.get_mcp(db, owner_id=user.id, mcp_id=mcp_id)
    if m is None:
        raise HTTPException(status_code=404, detail="MCP 不存在")
    return _mcp_out(ext_crud.set_mcp_visibility(db, m, "private"), mine=True)


@router.get("/mcps/plaza")
def list_plaza_mcps(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """广场 MCP 模板列表：已发布 + 启用中；附「是否已收录」与是否自己发布。"""
    return {"items": [
        _mcp_out(m, collected=ext_crud.has_adopted_mcp(db, user_id=user.id, source_mcp_id=m.id), mine=(m.owner_id == user.id))
        for m in ext_crud.list_plaza_mcps(db)
    ]}


@router.post("/mcps/plaza/{mcp_id}/collect")
def collect_plaza_mcp(mcp_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """收录广场 MCP：复制为本人私有 MCP（不含作者的 endpoint/config，需本人自行填写）。"""
    m = ext_crud.get_mcp_any(db, mcp_id=mcp_id)
    if m is None or getattr(m, "visibility", "private") != "plaza" or not m.enabled:
        raise HTTPException(status_code=404, detail="广场 MCP 不存在或已下架")
    if m.owner_id == user.id:
        return {"ok": True, "mine": True}
    copy = ext_crud.adopt_plaza_mcp(db, user_id=user.id, source=m)
    return {"ok": True, "item": _mcp_out(copy, mine=True)}


@router.delete("/mcps/plaza/{mcp_id}/collect")
def uncollect_plaza_mcp(mcp_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """取消收录：删除由该广场 MCP 复制而来的副本（含本人填写的配置）。"""
    ext_crud.remove_adopted_mcp(db, user_id=user.id, source_mcp_id=mcp_id)
    return {"ok": True}


# ---------------- Skill ----------------

class SkillIn(BaseModel):
    name: str = Field(max_length=64)
    description: str = Field(default="", max_length=256)
    content: str = Field(default="")
    enabled: bool = True


@router.get("/skills")
def list_skills(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    collected = set(str(x) for x in ext_crud.collected_skill_ids(db, user_id=user.id))
    return {"items": [
        _skill_out(s, collected=(str(s.id) in collected), mine=True)
        for s in ext_crud.list_skills(db, owner_id=user.id)
    ]}


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
    try:
        from app.services import skill_bundle as _bundle

        _bundle.remove_bundle(user.id, skill_id)
    except Exception:
        pass
    return {"ok": True}


@router.post("/skills/{skill_id}/publish")
def publish_skill(skill_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """发布 Skill 到广场：其他教师可收录引用（指令 + 文件清单，文件仍读作者目录）。"""
    s = ext_crud.get_skill(db, owner_id=user.id, skill_id=skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    if not ((s.content or "").strip() or (s.files or [])):
        raise HTTPException(status_code=400, detail="Skill 暂无可用内容（指令与文件包均为空），暂不能发布")
    return _skill_out(ext_crud.set_skill_visibility(db, s, "plaza"), mine=True)


@router.post("/skills/{skill_id}/unpublish")
def unpublish_skill(skill_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = ext_crud.get_skill(db, owner_id=user.id, skill_id=skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return _skill_out(ext_crud.set_skill_visibility(db, s, "private"), mine=True)


@router.get("/skills/plaza")
def list_plaza_skills(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """广场 Skill 列表：已发布 + 启用中；附收录态与是否自己发布。"""
    collected = set(str(x) for x in ext_crud.collected_skill_ids(db, user_id=user.id))
    return {"items": [
        _skill_out(s, collected=(str(s.id) in collected), mine=(s.owner_id == user.id))
        for s in ext_crud.list_plaza_skills(db)
    ]}


@router.post("/skills/plaza/{skill_id}/collect")
def collect_plaza_skill(skill_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = ext_crud.get_skill_any(db, skill_id=skill_id)
    if s is None or getattr(s, "visibility", "private") != "plaza" or not s.enabled:
        raise HTTPException(status_code=404, detail="广场 Skill 不存在或已下架")
    if s.owner_id == user.id:
        return {"ok": True, "mine": True}
    ext_crud.collect_skill(db, user_id=user.id, skill_id=s.id)
    return {"ok": True}


@router.delete("/skills/plaza/{skill_id}/collect")
def uncollect_plaza_skill(skill_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ext_crud.uncollect_skill(db, user_id=user.id, skill_id=skill_id)
    # 取消收录顺带从全局默认里摘掉，避免悬空 id 常驻
    try:
        g = ext_crud.get_global_setting(db, owner_id=user.id)
        if g is not None and str(skill_id) in list(g.default_skill_ids or []):
            ext_crud.upsert_global_setting(
                db, owner_id=user.id,
                default_skill_ids=[x for x in (g.default_skill_ids or []) if str(x) != str(skill_id)],
            )
    except Exception:
        pass
    return {"ok": True}


@router.post("/skills/{skill_id}/upload")
async def upload_skill_bundle(
    skill_id: uuid.UUID, file: UploadFile = File(...),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """上传 Skill 文件包（zip，含 SKILL.md + 脚本/资源）：解压落盘隔离目录，文件清单写回 files。"""
    from app.services import skill_bundle as _bundle

    s = ext_crud.get_skill(db, owner_id=user.id, skill_id=skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    data = await file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大（zip 需 ≤100MB，解压后总量需 ≤80MB、单文件 ≤10MB、≤200 个文件）。请精简后重试。")
    try:
        info = _bundle.save_bundle(user.id, skill_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    update: dict = {"files": info["files"]}
    # 包内 SKILL.md：frontmatter 的 name/description 回填名称/描述（仅当为空或默认值时），正文追加到指令内容
    if info["skill_md"]:
        meta = _bundle.parse_skill_md(info["skill_md"])
        manual = (s.content or "").strip()
        body = meta["body"] or info["skill_md"]
        update["content"] = (manual + "\n\n" + body).strip()[:8000] if manual and body not in manual else (manual or body)
        if meta["name"] and (not (s.name or "").strip() or (s.name or "").startswith("从 ")):
            update["name"] = meta["name"]
        if meta["description"] and not (s.description or "").strip():
            update["description"] = meta["description"]
    s = ext_crud.update_skill(db, s, **update)
    return _skill_out(s)


@router.get("/skills/{skill_id}/files")
def list_skill_files(skill_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = ext_crud.get_skill(db, owner_id=user.id, skill_id=skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return {"files": list(s.files or [])}


@router.get("/skills/{skill_id}/files/preview")
def preview_skill_file(skill_id: uuid.UUID, path: str = Query(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services import skill_bundle as _bundle

    s = ext_crud.get_skill(db, owner_id=user.id, skill_id=skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    if path not in list(s.files or []):
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        return {"path": path, "text": _bundle.read_text_file(user.id, skill_id, path)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


@router.post("/skills/import", status_code=status.HTTP_201_CREATED)
def import_skill_bundle(
    file: UploadFile = File(...), db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("agent_skill_import")),
):
    """直接上传 zip 建 Skill（免预建）：校验→建记录→解压落盘→SKILL.md 回填 content。"""
    from app.services import skill_bundle as _bundle

    data = file.file.read() if hasattr(file.file, "read") else b""
    # UploadFile 在新版 Starlette 下需 await；此处为同步路由，用 file.file 读取
    if not data:
        try:
            file.file.seek(0)
            data = file.file.read() or b""
        except Exception:
            data = b""
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大（zip 需 ≤100MB，解压后总量需 ≤80MB、单文件 ≤10MB、≤2000 个文件）。请精简后重试。")
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 .zip 包")
    name = (file.filename or "imported-skill").rsplit(".", 1)[0][:64] or "imported-skill"
    s = ext_crud.create_skill(db, owner_id=user.id, name=name, description="zip 导入", content="")
    try:
        info = _bundle.save_bundle(user.id, s.id, data)
    except ValueError as e:
        ext_crud.delete_skill(db, s)
        raise HTTPException(status_code=400, detail=str(e))
    update: dict = {"files": info["files"]}
    if info["skill_md"]:
        # SKILL.md frontmatter(name/description)分别落到名称/描述，正文落到指令内容
        meta = _bundle.parse_skill_md(info["skill_md"])
        update["content"] = meta["body"] or info["skill_md"]
        update["name"] = meta["name"] or name
        update["description"] = meta["description"] or f"从 {file.filename} 导入"
    s = ext_crud.update_skill(db, s, **update)
    return _skill_out(s)


@router.post("/skills/{skill_id}/run")
def run_skill_script(
    skill_id: uuid.UUID, body: dict | None = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """受控执行 Skill 内白名单脚本：仅 .py/.js/.sh，无网络、5s 超时、只读技能目录、禁 env。"""
    from app.services import skill_exec as _exec

    s = ext_crud.get_skill(db, owner_id=user.id, skill_id=skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    rel = str((body or {}).get("path", ""))
    args = (body or {}).get("args", [])
    if rel not in list(s.files or []):
        raise HTTPException(status_code=404, detail="文件不在 Skill 包内")
    try:
        sb = ext_crud.get_sandbox_setting(db, owner_id=user.id)
        return _exec.dispatch(
            user.id, skill_id, rel, args if isinstance(args, list) else [],
            provider=sb.provider if sb and sb.enabled else "local",
            endpoint=sb.endpoint if sb else "", token=sb.token if sb else "",
            timeout_s=sb.timeout_s if sb else 30,
            workspace_id=sb.workspace_id if sb else "", region=sb.region if sb else "cn-beijing",
            template_code=sb.template_code if sb else "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError:
        raise HTTPException(status_code=408, detail="执行超时（5s），已终止")


# ---------------- 沙箱设置（本地 / 阿里云函数计算） ----------------

class SandboxIn(BaseModel):
    provider: str = "local"
    endpoint: str = ""
    token: str = ""
    timeout_s: int = 30
    enabled: bool = True
    workspace_id: str = ""
    region: str = "cn-beijing"
    template_code: str = ""


def _sandbox_out(row) -> dict:
    return {
        "provider": row.provider if row else "local",
        "endpoint": row.endpoint if row else "",
        "has_token": bool(row and row.token),
        "timeout_s": row.timeout_s if row else 30,
        "enabled": row.enabled if row is not None else True,
        "workspace_id": row.workspace_id if row else "",
        "region": (row.region if row else "") or "cn-beijing",
        "template_code": row.template_code if row else "",
    }


@router.get("/sandbox")
def get_sandbox(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _sandbox_out(ext_crud.get_sandbox_setting(db, owner_id=user.id))


@router.put("/sandbox")
def put_sandbox(body: SandboxIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    provider = (body.provider or "local").strip()
    if provider not in ("local", "bailian"):
        raise HTTPException(status_code=400, detail="provider 仅支持 local / bailian")
    if provider == "bailian":
        if not (body.workspace_id or "").strip():
            raise HTTPException(status_code=400, detail="百炼沙箱需填写工作空间ID")
        if not (body.template_code or "").strip():
            raise HTTPException(status_code=400, detail="百炼沙箱需填写模板 code")
    timeout_s = max(10, min(int(body.timeout_s or 30), 120))
    row = ext_crud.upsert_sandbox_setting(
        db, owner_id=user.id, provider=provider,
        endpoint=(body.endpoint or "").strip(), timeout_s=timeout_s, enabled=body.enabled,
        workspace_id=(body.workspace_id or "").strip(),
        region=(body.region or "cn-beijing").strip() or "cn-beijing",
        template_code=(body.template_code or "").strip(),
        **({"token": body.token} if body.token else {}),
    )
    return _sandbox_out(row)


@router.post("/sandbox/test")
def test_sandbox(body: SandboxIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """测试百炼沙箱连通性（用表单里的配置，不落库；为空的项自动回退到已保存配置，方便保存后直接点测试）。"""
    from app.services import skill_exec as _exec

    if (body.provider or "local") != "bailian":
        return {"ok": True, "detail": "本地沙箱无需测试"}
    saved = ext_crud.get_sandbox_setting(db, owner_id=user.id)
    return _exec.test_remote(
        endpoint=(body.endpoint or "").strip() or (saved.endpoint if saved else ""),
        token=body.token or (saved.token if saved else ""),
        timeout_s=body.timeout_s or (saved.timeout_s if saved else 30),
        workspace_id=(body.workspace_id or "").strip() or (saved.workspace_id if saved else ""),
        region=(body.region or "").strip() or (saved.region if saved else "") or "cn-beijing",
        template_code=(body.template_code or "").strip() or (saved.template_code if saved else ""),
    )


@router.post("/mcps/{mcp_id}/test")
def test_mcp(mcp_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """测试 MCP 连接：握手 + tools/list，返回工具清单与 trace，前端直接展示。"""
    from app.services import mcp_runner as _mcp

    return _mcp.test_connection(db, user.id, mcp_id)
