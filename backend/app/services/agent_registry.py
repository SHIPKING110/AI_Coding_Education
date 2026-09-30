"""Agent 注册表：工作台可用的 Agent 清单。

id / 名称 / 所需上下文类型 / 系统提示词 / 可用动作集 / 是否支持 RAG / 图标。
"""

from __future__ import annotations

AGENTS: list[dict] = [
    {
        "id": "assistant",
        "name": "智能助手",
        "description": "教师协作助手：制度 / 流程 / 文化问答，引用知识库并给出依据",
        "context_types": [],
        "system_prompt": "你是教师的智能协作助手，熟悉公司制度、工作流程与文化，回答准确、引用明确。",
        "actions": ["send"],
        "supports_rag": True,
        "icon": "assistant",
        "stages": [
            {"key": "chat", "label": "智能问答", "desc": "直接提问，自动引用知识库作答", "prompt_stage": "chat"},
        ],
    },
    {
        "id": "report_ppt",
        "name": "工作报告 PPT Agent",
        "description": "基于报告总结生成工作报告 PPT：大纲 → 文案 → 排版 → 导出",
        "context_types": ["report"],
        "system_prompt": "你是资深演示文稿设计师，帮助教师把教学总结做成简洁、数据驱动的 PPT。",
        "actions": [
            "apply_theme",
            "apply_outline",
            "apply_sections",
            "add_page",
            "remove_page",
            "go_stage",
            "build_ppt",
            "regen",
            "send",
        ],
        "supports_rag": True,
        "icon": "report",
        # 执行链路：step.key 为会话 stage；prompt_stage 映射到 prompt 模板
        "stages": [
            {"key": "data", "label": "获取报告数据", "desc": "读取报告内容与关键数据", "prompt_stage": "chat"},
            {"key": "outline", "label": "规划大纲", "desc": "生成 8-11 页大纲", "prompt_stage": "outline"},
            {"key": "outline_confirm", "label": "确认大纲", "desc": "确认或调整大纲", "prompt_stage": "outline"},
            {"key": "copy", "label": "内容文案", "desc": "逐页生成讲解文案", "prompt_stage": "copy"},
            {"key": "theme", "label": "确定模板", "desc": "选择整体视觉模板", "prompt_stage": "layout"},
            {"key": "layout", "label": "PPT 排版", "desc": "配色与版式排版", "prompt_stage": "layout"},
            {"key": "layout_confirm", "label": "确认排版", "desc": "确认排版效果", "prompt_stage": "layout"},
            {"key": "export", "label": "生成 PPT", "desc": "导出最终文件", "prompt_stage": "chat"},
        ],
    },
    {
        "id": "class_parent_ppt",
        "name": "家长会 PPT Agent",
        "description": "基于班级评估生成家长会 PPT：风格 → 标题 → 大纲 → 侧重 → 建议 → 导出",
        "context_types": ["class_ppt"],
        "system_prompt": "你是班级家长会 PPT 策划师，用亲切、专业的语言帮助教师准备家长会。",
        "actions": [
            "apply_theme",
            "apply_outline",
            "apply_sections",
            "add_page",
            "remove_page",
            "go_stage",
            "build_ppt",
            "regen",
            "send",
        ],
        "supports_rag": True,
        "icon": "parents",
        "stages": [
            {"key": "data", "label": "获取班级数据", "desc": "读取季度数据与评估报告", "prompt_stage": "chat"},
            {"key": "style", "label": "选择风格", "desc": "确定整体语言风格", "prompt_stage": "style"},
            {"key": "title", "label": "确定标题", "desc": "三选一确定主标题", "prompt_stage": "title"},
            {"key": "outline", "label": "规划大纲", "desc": "生成 8-11 页大纲", "prompt_stage": "outline"},
            {"key": "outline_confirm", "label": "确认大纲", "desc": "确认或调整大纲", "prompt_stage": "outline"},
            {"key": "focus", "label": "内容侧重", "desc": "选择讲解侧重点", "prompt_stage": "focus"},
            {"key": "suggestion", "label": "家庭建议", "desc": "选择给家长的建议", "prompt_stage": "suggestion"},
            {"key": "theme", "label": "确定模板", "desc": "选择整体视觉模板", "prompt_stage": "chat"},
            {"key": "layout", "label": "PPT 排版", "desc": "配色与版式排版", "prompt_stage": "chat"},
            {"key": "export", "label": "生成 PPT", "desc": "导出最终文件", "prompt_stage": "export"},
        ],
    },
]

BY_ID = {a["id"]: a for a in AGENTS}


def get_agent(agent_id: str) -> dict | None:
    return BY_ID.get(agent_id)


__all__ = ["AGENTS", "BY_ID", "get_agent"]
