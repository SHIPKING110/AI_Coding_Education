"""Agent 对话意图分类：规则优先，低置信度再走轻量 LLM。

目的不是「给用户看分类标签」，而是为 RAG 观测提供正确口径：
- 寒暄/业务数据查询/PPT 任务本来就不需要 RAG，不应计入检索失败；
- 知识型问题才进入 RAG 需求量分母；
- 任务式对话（PPT/文档/MCP/Skill）单独统计调用链与产物对齐。
"""

from __future__ import annotations

import json
import re

CHITCHAT = "chitchat"
KNOWLEDGE_QA = "knowledge_qa"
BUSINESS_DATA = "business_data"
PPT_TASK = "ppt_task"
DOCUMENT_TASK = "document_task"
MCP_TASK = "mcp_task"
MIXED = "mixed"

VALID_INTENTS = {
    CHITCHAT, KNOWLEDGE_QA, BUSINESS_DATA, PPT_TASK, DOCUMENT_TASK, MCP_TASK, MIXED,
}

_GREETING_RE = re.compile(
    r"^(你好|您好|你们好|嗨|hi+|hello+|在吗|在么|在不在|谢谢|谢谢你|感谢|多谢|"
    r"再见|拜拜|辛苦了|好的|好嘞|收到|明白|嗯|嗯嗯|哦|哈哈+|ok+)[!！~～。.，,、\s]*$",
    re.IGNORECASE,
)

_PPT_HINTS = (
    "ppt", "幻灯片", "演示文稿", "课件", "出片", "加页", "插页", "删页", "补齐",
    "补页", "补全", "缺页", "页数", "大纲", "封面页", "母版", "排版", "pptx",
)
_DOC_HINTS = (
    "word", "docx", "pdf", "文档", "报告", "总结", "方案", "教案", "表格",
    "生成一份", "写一份", "整理成", "导出",
)
_TASK_VERBS = (
    "生成", "制作", "做一份", "做一套", "帮我写", "帮我做", "整理成", "导出",
    "修改", "调整", "补齐", "补页", "加页", "删页", "换主题", "重新生成",
)
_BUSINESS_HINTS = (
    "学员", "学生", "班级", "教师", "老师", "排课", "课表", "考勤", "课时",
    "余额", "消课", "订单", "缴费", "退费", "财务", "收入", "工资", "提成",
    "作业", "提交", "批改", "评估", "家长会", "邀约", "体验课",
)
_KNOWLEDGE_HINTS = (
    "制度", "流程", "政策", "规定", "手册", "规范", "标准", "要求", "注意事项",
    "怎么", "如何", "为什么", "什么是", "区别", "方法", "步骤", "原理", "案例",
    "课程体系", "教学方法", "培训", "教研", "知识库", "资料", "参考文档",
)
_RAG_HINTS = ("知识库", "资料", "文档里", "制度里", "手册里", "参考", "查一下资料", "引用")
_MCP_HINTS = ("mcp", "外部工具", "高德", "地图", "天气", "网页", "接口", "调用工具")


def _looks_like_question(text: str) -> bool:
    return text.endswith(("?", "？")) or any(
        k in text for k in ("什么", "怎么", "如何", "为什么", "哪", "是否", "能不能", "可不可以", "多少")
    )


def _result(intent: str, *, confidence: float, reason: str, needs_rag: bool, task_kind: str = "chat",
            source: str = "rule") -> dict:
    return {
        "intent": intent,
        "intent_confidence": round(float(confidence), 3),
        "intent_source": source,
        "needs_rag": bool(needs_rag),
        "task_kind": task_kind,
        "reason": reason,
    }


def _rule_classify(
    text: str,
    *,
    agent_id: str = "",
    stage: str = "",
    has_docs: bool = True,
    rag_enabled: bool = False,
    recent_tools: list[str] | None = None,
) -> dict:
    t = (text or "").strip()
    if not t:
        return _result(CHITCHAT, confidence=1.0, reason="empty", needs_rag=False)

    if len(t) <= 16 and _GREETING_RE.match(t):
        return _result(CHITCHAT, confidence=1.0, reason="greeting", needs_rag=False)

    recent_tools = recent_tools or []
    lower = t.lower()
    has_ppt = any(k in lower for k in _PPT_HINTS)
    has_doc = any(k in lower for k in _DOC_HINTS)
    has_task_verb = any(k in lower for k in _TASK_VERBS)
    has_business = any(k in t for k in _BUSINESS_HINTS)
    has_knowledge = any(k in t for k in _KNOWLEDGE_HINTS)
    has_rag_hint = any(k in t for k in _RAG_HINTS)
    has_mcp = any(k in lower for k in _MCP_HINTS)

    # 已有 PPT 项目/最近调用过 Skill：短确认句和页级改动都归到同一任务
    recent_ppt = any(
        x in {"write_skill_file", "delete_skill_file", "run_skill_script", "read_skill_file"}
        for x in recent_tools
    )
    if (has_ppt or stage in {"outline", "copy", "layout", "export"} or recent_ppt) and (
        has_task_verb or has_ppt or recent_ppt
    ):
        return _result(
            PPT_TASK,
            confidence=0.95,
            reason="ppt_keyword" if has_ppt else "ppt_context",
            needs_rag=bool(has_rag_hint or rag_enabled),
            task_kind="ppt",
        )

    if has_doc and has_task_verb:
        return _result(
            DOCUMENT_TASK,
            confidence=0.9,
            reason="document_task",
            needs_rag=bool(has_rag_hint or rag_enabled),
            task_kind="document",
        )

    if has_mcp:
        return _result(MCP_TASK, confidence=0.8, reason="mcp_keyword", needs_rag=False, task_kind="mcp")

    # 业务数据查询走系统工具，不需要 RAG；但「制度/政策」和业务实体同时出现时优先知识问答
    if has_business and not (has_knowledge and _looks_like_question(t)):
        return _result(
            BUSINESS_DATA,
            confidence=0.85,
            reason="business_keyword",
            needs_rag=False,
            task_kind="business_data",
        )

    if has_rag_hint or has_knowledge or _looks_like_question(t):
        confidence = 0.9 if (has_rag_hint or has_knowledge) else 0.6
        return _result(
            KNOWLEDGE_QA,
            confidence=confidence,
            reason="knowledge_keyword" if has_knowledge else "question",
            needs_rag=bool(has_docs),
            task_kind="rag_qa",
        )

    if has_task_verb:
        return _result(
            MIXED,
            confidence=0.55,
            reason="task_verb",
            needs_rag=bool(has_docs or rag_enabled),
            task_kind="task",
        )

    return _result(
        MIXED,
        confidence=0.45,
        reason="fallback",
        needs_rag=bool(has_docs or rag_enabled),
        task_kind="chat",
    )


def _parse_llm_json(raw: str) -> dict | None:
    raw = (raw or "").strip()
    candidates = [raw]
    m = re.search(r"```json\s*([\s\S]*?)```", raw)
    if m:
        candidates.append(m.group(1))
    m2 = re.search(r"\{[\s\S]*\}", raw)
    if m2:
        candidates.append(m2.group(0))
    for c in candidates:
        try:
            data = json.loads(c)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _llm_classify(text: str, *, agent_id: str, stage: str) -> dict | None:
    try:
        from app.services import llm

        system = (
            "你是教务 Agent 的意图分类器。只输出 JSON，不要解释。"
            "intent 只能是 chitchat/knowledge_qa/business_data/ppt_task/document_task/mcp_task/mixed。"
            "needs_rag 表示回答这个问题是否真的需要查机构知识库；"
            "业务数据查询（学员/课时/排课/财务）和 PPT/文档生成任务通常不需要 RAG。"
        )
        prompt = (
            f"Agent={agent_id}，阶段={stage or '-'}。\n"
            f"用户消息：{text[:800]}\n"
            '输出：{"intent":"...","needs_rag":true/false,"confidence":0~1,"reason":"..."}'
        )
        raw = llm.invoke_text(system, prompt, temperature=0.0, timeout=30)
        data = _parse_llm_json(raw)
        if not data:
            return None
        intent = str(data.get("intent") or "").strip()
        if intent not in VALID_INTENTS:
            return None
        task_kind = {
            PPT_TASK: "ppt", DOCUMENT_TASK: "document", BUSINESS_DATA: "business_data",
            KNOWLEDGE_QA: "rag_qa", MCP_TASK: "mcp", CHITCHAT: "chat", MIXED: "chat",
        }.get(intent, "chat")
        return _result(
            intent,
            confidence=float(data.get("confidence") or 0.7),
            reason=str(data.get("reason") or "llm"),
            needs_rag=bool(data.get("needs_rag")),
            task_kind=task_kind,
            source="llm",
        )
    except Exception:
        return None


def classify(
    text: str,
    *,
    agent_id: str = "",
    stage: str = "",
    has_docs: bool = True,
    rag_enabled: bool = False,
    recent_tools: list[str] | None = None,
) -> dict:
    """返回 {intent, intent_confidence, intent_source, needs_rag, task_kind, reason}。"""
    rule = _rule_classify(
        text,
        agent_id=agent_id,
        stage=stage,
        has_docs=has_docs,
        rag_enabled=rag_enabled,
        recent_tools=recent_tools,
    )
    try:
        from app.core.config import get_settings

        threshold = float(get_settings().AGENT_INTENT_CONFIDENCE_THRESHOLD)
        allow_llm = bool(get_settings().AGENT_INTENT_LLM_FALLBACK)
    except Exception:
        threshold, allow_llm = 0.55, False
    if allow_llm and rule["intent_confidence"] < threshold:
        llm_result = _llm_classify(text, agent_id=agent_id, stage=stage)
        if llm_result is not None:
            return llm_result
    return rule


__all__ = [
    "CHITCHAT",
    "KNOWLEDGE_QA",
    "BUSINESS_DATA",
    "PPT_TASK",
    "DOCUMENT_TASK",
    "MCP_TASK",
    "MIXED",
    "VALID_INTENTS",
    "classify",
]
