"""默认 Agent 自动供给：每个教师/管理员账号默认拥有一个「PPT 生成助手」。

设计：
- 幂等：已存在同名「PPT生成助手」则不重复建（用户可改名/删，删了下次进入又补一个，符合"默认有一个"）。
- 绑定广场适配版 ppt-master（含 ppt_oneshot 快速通道 wrapper）：自动收录 + 物化，保证与管理员同款。
- 懒加载：在 list_agents 入口调用，开销极小（先查存在性，命中广场适配版才建）。
"""

from __future__ import annotations

DEFAULT_PPT_NAME = "PPT生成助手"

_DEFAULT_PROMPT = (
    "你是 PPT 生成专家。用户要做课件/汇报/方案时，用 ppt-master 快速通道一步出片：\n"
    "1) 先按用户主题规划页序与每页要点，简短确认（如信息足够则直接开做，不要反复追问）；\n"
    "2) 用 write_skill_file 把每页 SVG 写到 projects/<项目名>/svg_output/NN_标题.svg（NN 从 01 连续编号）；\n"
    "3) 用 run_skill_script 执行 ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py build projects/<项目名> 出片；\n"
    "4) 二次编辑（加页/删页/改字/调序）就在同一项目上改 SVG 后重新 build，产物自动刷新。\n"
    "务必真正落页并出片，不要只读文件或空口承诺；页数与正文章节保持一致。"
)


def _plaza_ppt_adapter(db):
    """找广场上架、启用的 ppt-master 适配版（含 ppt_oneshot wrapper）。无则返回 None。"""
    try:
        from app.crud import agent_ext as ext

        for s in ext.list_plaza_skills(db):
            name = (s.name or "").lower()
            if "ppt-master" not in name and "ppt匹配" not in name:
                continue
            files = [str(f) for f in (s.files or [])]
            if any(f.endswith("scripts/ppt_oneshot.py") for f in files) or any(
                "ppt_oneshot.py" in f for f in files
            ):
                return s
        # 退而求其次：任意广场 ppt-master（即便没 wrapper，也能读 SKILL.md 走多步）
        for s in ext.list_plaza_skills(db):
            if "ppt-master" in (s.name or "").lower():
                return s
    except Exception:
        pass
    return None


def ensure_default_ppt_agent(db, user) -> bool:
    """确保该用户有默认「PPT生成助手」。返回是否新建。幂等、失败静默。"""
    try:
        if getattr(user, "role", "") not in ("teacher", "admin"):
            return False
        from app.crud import agent_ext as ext

        # 已有同名 Agent → 不重复建
        for c in ext.list_custom_agents(db, owner_id=user.id):
            if (c.name or "").strip() == DEFAULT_PPT_NAME:
                return False
        adapter = _plaza_ppt_adapter(db)
        if adapter is None:
            return False  # 管理员还没发布适配版前不建（避免建个没能力的空助手）

        uid8 = str(user.id).replace("-", "")[:8]
        agent_id = f"custom_{uid8}_ppt"
        # 极端情况：agent_id 撞车（不同用户 uid8 相同概率极低），加后缀兜底
        if ext.get_custom_agent(db, owner_id=user.id, agent_id=agent_id) is not None:
            agent_id = f"custom_{uid8}_{adapter.id.hex[:6]}"

        ext.create_custom_agent(
            db,
            owner_id=user.id,
            agent_id=agent_id,
            name=DEFAULT_PPT_NAME,
            description="一键把主题/大纲做成可下载 PPTX：自动规划页序、生成每页 SVG、导出成品，支持加页/改页二次编辑。",
            system_prompt=_DEFAULT_PROMPT,
            supports_rag=True,
            icon="assistant",
            skill_ids=[str(adapter.id)],
            mcp_ids=[],
            stages=[{"key": "chat", "label": "课件生成", "desc": "说主题或大纲，直接出片", "prompt_stage": "chat"}],
        )
        # 自动收录 + 物化适配版（物化在首次执行时也会触发，这里先收录保证清单可见）
        try:
            ext.collect_skill(db, user_id=user.id, skill_id=adapter.id)
        except Exception:
            pass
        return True
    except Exception:
        return False


__all__ = ["ensure_default_ppt_agent", "DEFAULT_PPT_NAME"]
