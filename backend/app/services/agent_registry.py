"""Agent 注册表：工作台可用的 Agent 清单。

id / 名称 / 所需上下文类型 / 系统提示词 / 可用动作集 / 是否支持 RAG / 图标。
内置 1 个通用助手 + 用户自定义 Agent（custom_agents 表，list 时合并）。
说明：原「工作报告 PPT Agent」「家长会 PPT Agent」已下线——PPT 生成统一改由
通用助手 + ppt-master Skill 完成，不再需要专用内置 Agent。
"""

from __future__ import annotations

AGENTS: list[dict] = [
    {
        "id": "assistant",
        "name": "智能助手",
        "description": "教师协作助手：制度 / 流程 / 文化问答，引用知识库并给出依据；也可调用 Skill 生成 PPT/文档等文件",
        "context_types": [],
        "system_prompt": "你是教师的智能协作助手，熟悉公司制度、工作流程与文化，回答准确、引用明确。",
        "actions": ["send"],
        "supports_rag": True,
        "icon": "assistant",
        "stages": [
            {"key": "chat", "label": "智能问答", "desc": "直接提问，自动引用知识库作答", "prompt_stage": "chat"},
        ],
    },
]

BY_ID = {a["id"]: a for a in AGENTS}


def get_agent(agent_id: str) -> dict | None:
    return BY_ID.get(agent_id)


def list_for_owner(db, owner_id) -> list[dict]:
    """内置 + 该用户的自定义 Agent 合并清单（自定义覆盖同名内置不可能，id 全局唯一）。"""
    items = list(AGENTS)
    try:
        from app.crud import agent_ext as _ext

        for c in _ext.list_custom_agents(db, owner_id=owner_id):
            items.append({
                "id": c.agent_id,
                "name": c.name,
                "description": c.description or "自定义 Agent",
                "context_types": [],
                "system_prompt": c.system_prompt or "",
                "actions": ["send"],
                "supports_rag": bool(c.supports_rag),
                "icon": c.icon or "assistant",
                "stages": c.stages or [{"key": "chat", "label": "智能问答", "desc": "直接提问", "prompt_stage": "chat"}],
                "custom": True,
            })
    except Exception:
        pass
    return items


def resolve_agent(db, owner_id, agent_id: str) -> dict | None:
    """先查内置，再查自定义（含 system_prompt / stages 覆盖）。"""
    hit = BY_ID.get(agent_id)
    if hit is not None:
        return hit
    try:
        from app.crud import agent_ext as _ext

        c = _ext.get_custom_agent(db, owner_id=owner_id, agent_id=agent_id)
        if c is None:
            return None
        return {
            "id": c.agent_id,
            "name": c.name,
            "description": c.description or "自定义 Agent",
            "context_types": [],
            "system_prompt": c.system_prompt or "",
            "actions": ["send"],
            "supports_rag": bool(c.supports_rag),
            "icon": c.icon or "assistant",
            "stages": c.stages or [{"key": "chat", "label": "智能问答", "desc": "直接提问", "prompt_stage": "chat"}],
            "custom": True,
        }
    except Exception:
        return None


def effective_skill_ids(db, owner_id, agent_id: str) -> list[str]:
    """某 Agent 生效可用的 Skill id 列表（供权限白名单用）。

    含「绑定 id 漂移」自愈：用户对某 Agent 勾选的 skill id，若因发布/下架导致该 id 对本人不可用，
    但存在**同名且本人可用**的 skill，则用同名可用者的 id 接续（勾选语义是「这个 skill」而非「这个 id」）。
    返回本人实际可用的 skill id 列表（own 或 plaza）。
    """
    from app.crud import agent_ext as _ext

    def _is_uuid(v) -> bool:
        try:
            import uuid as _uuid

            _uuid.UUID(str(v))
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    glob = _ext.get_global_setting(db, owner_id=owner_id)
    per_skill: list = []
    c = _ext.get_custom_agent(db, owner_id=owner_id, agent_id=agent_id)
    if c is not None:
        per_skill = list(c.skill_ids or [])
    want = [str(x) for x in (per_skill + list((glob.default_skill_ids if glob else []) or []))]

    own = {str(s.id): s for s in _ext.list_skills(db, owner_id=owner_id)}
    plaza = {str(s.id): s for s in _ext.list_plaza_skills(db)}

    def _usable(s) -> bool:
        if s is None or not s.enabled:
            return False
        sid = str(s.id)
        if sid not in own and getattr(s, "visibility", "private") != "plaza":
            return False
        return bool((s.content or "").strip()) or bool(s.files)

    by_name: dict[str, object] = {}
    for s in list(own.values()) + list(plaza.values()):
        if _usable(s):
            by_name.setdefault(s.name, s)

    out: list[str] = []
    for sid in want:
        s = own.get(sid) or plaza.get(sid)
        if not _usable(s):
            # id 在本人的 own/plaza 里不可用：用跨 owner 查询拿到它的「名字」再按名自愈
            nm = getattr(s, "name", None)
            if nm is None:
                try:
                    from app.crud import agent_ext as _e2

                    any_row = _e2.get_skill_any(db, skill_id=sid) if _is_uuid(sid) else None
                    nm = getattr(any_row, "name", None)
                except Exception:
                    nm = None
            if nm is not None and _usable(by_name.get(nm)):
                s = by_name.get(nm)
                sid = str(s.id)
        if _usable(s) and sid not in out:
            out.append(sid)
    return out


def effective_capabilities(db, owner_id, agent_id: str) -> dict:
    """某 Agent 生效的 MCP/Skill：per-agent 绑定 ∪ 全局默认（仅 enabled 的）。"""
    mcp_ids: list[str] = []
    skill_blocks: list[str] = []
    try:
        from app.crud import agent_ext as _ext

        glob = _ext.get_global_setting(db, owner_id=owner_id)
        per_mcp: list = []
        per_skill: list = []
        c = _ext.get_custom_agent(db, owner_id=owner_id, agent_id=agent_id)
        if c is not None:
            per_mcp = list(c.mcp_ids or [])
            per_skill = list(c.skill_ids or [])
        want_mcp = [str(x) for x in (per_mcp + list((glob.default_mcp_ids if glob else []) or []))]
        want_skill = [str(x) for x in (per_skill + list((glob.default_skill_ids if glob else []) or []))]
        seen: set[str] = set()
        # MCP 仅用本人名下（收录的广场 MCP 已复制成本人私有副本，含本人填写的 endpoint/凭据）
        for m in _ext.list_mcps(db, owner_id=owner_id):
            sid = str(m.id)
            if m.enabled and sid in want_mcp and sid not in seen:
                seen.add(sid)
                mcp_ids.append(m.name or sid)
        # 自有 Skill ∪ 广场 Skill（后者含自己发布的与收录引用的，支持跨 owner 绑定）：
        # 生效条件 = 在绑定名单里 + 启用中 + 有实质内容 +（非自有则必须仍在广场上架）
        own = {str(s.id): s for s in _ext.list_skills(db, owner_id=owner_id)}
        plaza = {str(s.id): s for s in _ext.list_plaza_skills(db)}

        def _usable(s) -> bool:
            if s is None or not s.enabled:
                return False
            sid = str(s.id)
            if sid not in own and getattr(s, "visibility", "private") != "plaza":
                return False
            return bool((s.content or "").strip()) or bool(s.files)

        # 名字 → 本人可用 skill（own 优先，其次广场）用于「绑定 id 漂移」时的自愈：
        # 用户勾选的是「ppt-master」这个意图；发布/下架导致 id 变了，仍按同名可用的接续。
        by_name: dict[str, object] = {}
        for s in list(own.values()) + list(plaza.values()):
            if _usable(s):
                by_name.setdefault(s.name, s)

        for sid in want_skill:
            s = own.get(sid) or plaza.get(sid)
            if not _usable(s):
                # id 已漂移/不可用：用跨 owner 名字自愈到本人可用的同名 skill
                nm = getattr(s, "name", None)
                if nm is None:
                    try:
                        from app.crud import agent_ext as _e2

                        any_row = _e2.get_skill_any(db, skill_id=sid)
                        nm = getattr(any_row, "name", None)
                    except Exception:
                        nm = None
                if nm is not None and _usable(by_name.get(nm)):
                    s = by_name.get(nm)
                    sid = str(s.id)
            if not _usable(s):
                continue
            if sid in seen:
                continue
            seen.add(sid)
            # 文件包注入：SKILL.md 摘要 + 文件清单（脚本默认不执行、仅引用）；
            # 广场 Skill 的文件读作者目录（取 s.owner_id），引用不复制
            try:
                from app.services import skill_bundle as _bundle

                skill_blocks.append(_bundle.skill_context_block(
                    s.owner_id, sid, s.name, s.content or "", list(s.files or [])))
            except Exception:
                skill_blocks.append(f"【Skill·{s.name}】\n{(s.content or '').strip()}")
    except Exception:
        pass
    return {"mcp_names": mcp_ids, "skill_blocks": skill_blocks}


__all__ = ["AGENTS", "BY_ID", "get_agent", "list_for_owner", "resolve_agent", "effective_capabilities"]
