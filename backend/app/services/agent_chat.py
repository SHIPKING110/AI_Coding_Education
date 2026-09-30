"""统一流式协议：对话 + 可执行 options + phase，支持双 Agent，注入长短期记忆。

- report_ppt：复用 ppt_chat 的阶段 prompt，叠加记忆块。
- class_parent_ppt：家长会 Agent（原固定点选）重写为统一协议：
  风格 → 标题 → 大纲 → 侧重 → 建议 → 导出，旧点选步骤转为选项气泡。
"""

from __future__ import annotations

import json

from app.services import ppt_chat
from app.services.agent_registry import get_agent as _get_agent
from app.services.ppt_agent import FOCUS_OPTIONS, STYLE_OPTIONS, SUGGESTION_OPTIONS

PARENT_STAGES = ("style", "title", "outline", "focus", "suggestion", "export", "chat")


def prompt_stage_for(agent_id: str, stage: str) -> str:
    """路线图 key → prompt 模板 key（确认类步骤复用同阶段模板）。"""
    agent = _get_agent(agent_id) or {}
    for s in agent.get("stages", []):
        if s.get("key") == stage:
            return s.get("prompt_stage", stage)
    return stage


def extract_options(text: str) -> list[dict]:
    """从模型输出的 ```json 代码块中提取 options（首个含 options 键的块）。"""
    import re

    out: list[dict] = []
    for m in re.finditer(r"```json\s*([\s\S]*?)```", text):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("options"), list):
            return [o for o in data["options"] if isinstance(o, dict)]
    return out


def extract_spec(text: str) -> dict:
    """从模型输出的 ```json 代码块中提取 PPT 规格（outline/sections/theme/slides）。

    只收录结构合法的字段，供工作区预览/编辑与一键生成 PPT 使用。
    """
    import re

    spec: dict = {}
    for m in re.finditer(r"```json\s*([\s\S]*?)```", text):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("outline"), list) and data["outline"]:
            spec["outline"] = [o for o in data["outline"] if isinstance(o, dict)]
        if isinstance(data.get("sections"), list) and data["sections"]:
            spec["sections"] = [s for s in data["sections"] if isinstance(s, dict)]
        if isinstance(data.get("theme"), str):
            spec["theme"] = data["theme"]
        if isinstance(data.get("slides"), list) and data["slides"]:
            spec["slides"] = [s for s in data["slides"] if isinstance(s, dict)]
    return spec


def parent_prompt(*, stage: str, context_ref: dict, state: dict, user_message: str, memory_block: str = "") -> str:
    styles = json.dumps(
        [{"id": s["id"], "label": s["label"], "desc": s["desc"]} for s in STYLE_OPTIONS], ensure_ascii=False
    )
    focus = json.dumps(FOCUS_OPTIONS, ensure_ascii=False)
    sugg = json.dumps(SUGGESTION_OPTIONS, ensure_ascii=False)
    mem = f"\n\n{memory_block}" if memory_block else ""
    base = (
        f"你是班级家长会 PPT 策划师。班级上下文：{json.dumps(context_ref, ensure_ascii=False)}。\n"
        f"当前状态：{json.dumps(state, ensure_ascii=False)}\n"
        f"用户消息：{user_message or '（请按当前阶段推进）'}\n{mem}\n"
        "请用 Markdown 简洁回应，并在 ```json 代码块中给出可执行 options（沿用报告 Agent 的动作目录："
        "apply_theme/apply_outline/apply_sections/add_page/remove_page/go_stage/build_ppt/regen/send）。"
        "恰好 1 个 recommended=true，且必须是系统真能执行的下一步。"
        "重要：用户一旦确认某阶段（如选定风格/标题），绝不再重复该阶段的内容，直接推进到下一阶段；"
        "同一阶段最多追问一次，避免让用户反复确认。"
    )
    hints = {
        "style": f"当前是【风格】阶段。可选风格：{styles}。请推荐一种并给出 options（含确认风格进入标题阶段）。",
        "title": "当前是【标题】阶段。请给 3 个备选标题（A/B/C），options 支持选择标题（send）与重新生成。",
        "outline": "当前是【大纲】阶段。请给出 8-11 页大纲（含封面/数据/亮点/改进/建议/结尾）。",
        "focus": f"当前是【侧重】阶段。可选：{focus}。请推荐一个，options 支持确认并进入建议阶段。",
        "suggestion": f"当前是【建议】阶段。可选：{sugg}。请推荐一个，options 支持确认并进入导出（build_ppt）。",
        "export": "当前是【导出】阶段。请确认已就绪，给出 build_ppt（recommended）与返回修改的 options。",
        "chat": "请针对用户消息自由回应，涉及调整时同样给出可执行 options。",
    }
    return base + "\n" + hints.get(stage, hints["chat"])


def build_unified_prompt(
    *,
    agent_id: str,
    stage: str,
    user_message: str,
    state: dict,
    context_ref: dict,
    memory_block: str = "",
    material: dict | None = None,
) -> tuple[str, str]:
    """返回 (system_prompt, user_prompt)。"""
    if agent_id == "class_parent_ppt":
        system = "你是班级家长会 PPT 策划师，用亲切、专业的语言帮助教师准备家长会。回答用 Markdown。"
        user = parent_prompt(
            stage=stage, context_ref=context_ref, state=state, user_message=user_message, memory_block=memory_block
        )
        return system, user
    if agent_id == "assistant":
        # 智能助手：RAG 问答 + 只读业务工具；片段与业务数据均已注入 memory_block
        system = (
            "你是教师的智能协作助手，熟悉公司制度、工作流程与企业文化，"
            "也能查询系统内的排课考勤、教学数据、班级与学员、学员评估等业务数据。"
            "回答用 Markdown，准确简洁。"
        )
        user = (
            f"用户问题：{user_message or '（请打招呼并介绍你能帮什么忙）'}\n"
            f"{memory_block}\n"
            "回答要求：\n"
            "1. 若提供了【业务数据】，优先依据它作答，并注明数据对应的周期；数据里没有的不要编造；"
            "【业务数据】是最新实时查询结果，**优先级高于历史对话与长期记忆**——若二者冲突，一律以【业务数据】为准；\n"
            "2. 名单/明细类数据要**逐条完整列出**（如班级的每位学员都要列出），不要只列前几条或用『等/省略』概括；"
            "若业务数据注明了总数与返回条数，如实汇报（如'共 N 人，已列出前 M 条'），"
            "不要把截断后的列表当成完整名单，也不要断言系统里只有这些；\n"
            "3. 优先依据【知识库引用片段】回答制度/流程类问题，并在关键结论后标注来源"
            "（如：——依据《员工手册》）；\n"
            "4. 两类资料都没有相关内容时，明确说明系统内没有查到，再给出通用性建议，不要编造。"
        )
        return system, user
    # report_ppt：复用现有阶段 prompt + 记忆块
    mat = material or {}
    if mat:
        base = ppt_chat.build_prompt(
            stage=stage if stage in ("outline", "copy", "layout", "chat") else "chat",
            material=mat,
            user_message=user_message,
            outline=state.get("outline", []),
            sections=state.get("sections", []),
        )
    else:
        base = f"用户消息：{user_message}\n当前状态：{json.dumps(state, ensure_ascii=False)}"
    if memory_block:
        base = base + f"\n\n{memory_block}"
    return ppt_chat.SYSTEM_PROMPT, base


__all__ = [
    "PARENT_STAGES", "parent_prompt", "build_unified_prompt",
    "prompt_stage_for", "extract_options", "extract_spec",
]
