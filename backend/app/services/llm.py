"""LLM 服务层（M3+）：统一封装模型调用，供 AI 草稿/报告等生成类功能使用。

- 通过 LangChain OpenAI 兼容客户端对接模型（默认 DeepSeek，可由 .env 切换）
- **延迟导入** langchain 依赖：无 AI 依赖或未配置 LLM_API_KEY 时不阻塞应用启动
- 模型名/BaseURL/Key 全部来自配置，不硬编码（架构约束：模型可切换）
- 提示词模板由提示词模板表驱动，占位符替换后作为用户指令（模板与代码分离）
"""

import json
import re
from typing import Any

from app.core.config import get_settings

# 反馈模板可用占位符（与 prompt_templates 表内容约定一致）
FEEDBACK_PLACEHOLDERS = (
    "student_name",
    "class_name",
    "subject",
    "title",
    "topic",
    "content",
    "performance",
    "evaluation",
    "homework",
)


class LLMConfigError(RuntimeError):
    """LLM 未配置或调用失败，携带对用户友好的中文消息。"""


def is_llm_configured() -> bool:
    """是否已配置可用的 LLM（有 API Key 即视为配置，供调用方判断是否启用 AI）。"""
    return bool((get_settings().LLM_API_KEY or "").strip())


def _require_any_llm(fallback_message: str) -> None:
    """上下文感知门禁：当前请求有教师个人配置则放行，否则看全局 key。
    两者都没有时抛中文引导（前端弹 toast 指引去 设置→模型配置）。"""
    if _active_resolved() is not None:
        return
    if not is_llm_configured():
        raise LLMConfigError(fallback_message)


_client_cache: dict = {}


def _active_resolved():
    from app.services import llm_context as _ctx

    return _ctx.get_current()


def _build_chat(base_url: str, api_key: str, model: str, temperature: float, timeout: int, max_retries: int):
    from langchain_openai import ChatOpenAI

    key = (base_url or "", api_key or "", model or "", temperature, timeout, max_retries)
    client = _client_cache.get(key)
    if client is None:
        client = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            temperature=temperature,
            timeout=timeout,
            max_retries=max_retries,
        )
        _client_cache[key] = client
    return client


def _chat_model():
    resolved = _active_resolved()
    if resolved is not None:
        return _build_chat(resolved.base_url, resolved.api_key, resolved.model, 0.6, 60, 2)
    settings = get_settings()
    base_url = _normalized_base_url(settings.LLM_BASE_URL)
    return _build_chat(base_url or "", settings.LLM_API_KEY, settings.LLM_MODEL, 0.6, 60, 2)


def _plan_model():
    resolved = _active_resolved()
    if resolved is not None:
        return _build_chat(resolved.base_url, resolved.api_key, resolved.model, 0.0, 30, 0)
    settings = get_settings()
    base_url = _normalized_base_url(settings.LLM_BASE_URL)
    return _build_chat(base_url or "", settings.LLM_API_KEY, settings.LLM_MODEL, 0.0, 30, 0)


def ping(resolved=None) -> str:
    model = _build_chat(
        (resolved.base_url if resolved else ""),
        (resolved.api_key if resolved else get_settings().LLM_API_KEY),
        (resolved.model if resolved else get_settings().LLM_MODEL),
        0.0,
        15,
        0,
    )
    from langchain_core.messages import HumanMessage

    resp = model.invoke([HumanMessage(content="ping")])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return (text or "").strip()[:200] or "pong"


def _normalized_base_url(url: str | None) -> str:
    base_url = (url or "").rstrip("/")
    # DeepSeek 同时支持 https://api.deepseek.com 与 /v1；统一补全 /v1 以兼容 OpenAI 客户端
    if base_url and not base_url.endswith("/v1"):
        base_url += "/v1"
    return base_url


def fill_template(template_content: str, values: dict[str, str | None]) -> str:
    """把 {占位符} 替换为实际值；未提供的占位符以「（未填写）」占位。"""
    text = template_content
    for key, value in values.items():
        text = text.replace("{" + key + "}", (value or "").strip() or "（未填写）")
    return text


def friendly_llm_error(exc: BaseException) -> str:
    """把底层 LLM/网络异常翻译为用户可读的中文提示（供接口层以 502 透出）。"""
    name = exc.__class__.__name__.lower()
    text = f"{exc}".lower()
    if (
        "authentication" in name
        or "unauthorized" in text
        or "invalid api key" in text
        or "incorrect api key" in text
        or "model_not_found" in text
        or "model not found" in text
    ):
        return "AI 认证失败（API Key 无效、欠费或模型名错误），请联系管理员检查配置"
    if "timeout" in name or "timed out" in text or "timeout" in text:
        return "AI 生成超时（模型响应较慢），请稍后重试"
    if "429" in text or "rate limit" in text or "ratelimit" in name:
        return "AI 请求过于频繁（触发限流），请稍后再试"
    if any(
        k in text
        for k in (
            "connection", "connect", "network", "socket", "econn",
            "temporarily", "unavailable", "overloaded", "bad gateway",
            "service unavailable", "internal error",
        )
    ) or any(k in name for k in ("connection", "network", "apiconnection", "apitimeout")):
        return "AI 服务暂时不可用（网络波动），请稍后重试"
    msg = str(exc).strip().replace("\n", " ")
    if len(msg) > 120:
        msg = msg[:120] + "…"
    return f"AI 生成失败（{msg or exc.__class__.__name__}），请稍后重试"


def _invoke(prompt: str) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        model = _chat_model()
        sys_text = (
            "你是少儿编程培训机构的教务助手，负责撰写给家长看的课堂评价与课后反馈。"
            "文风亲切、具体、有条理，突出孩子本节课的收获、亮点与可提升之处，避免空话套话。"
            "只根据给定的信息撰写，不编造不存在的细节。"
        )
        resp = model.invoke([SystemMessage(content=sys_text), HumanMessage(content=prompt)])
    except LLMConfigError:
        raise
    except Exception as e:  # noqa: BLE001 —— 超时/认证/限流/断网统一转中文提示
        raise LLMConfigError(friendly_llm_error(e)) from e
    return (resp.content or "").strip()


def stream_text(system: str, prompt: str):
    """流式调用 LLM，逐段 yield 文本增量（供 SSE 对话式 PPT 定制使用）。

    未配置 LLM 时抛 LLMConfigError；调用异常时抛出，由调用方转为 SSE error 事件。
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI")
    model = _chat_model()
    for chunk in model.stream([SystemMessage(content=system), HumanMessage(content=prompt)]):
        piece = getattr(chunk, "content", "") or ""
        if isinstance(piece, list):
            piece = "".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in piece
            )
        if piece:
            yield piece


def plan_tool_calls(message: str, tools: list[dict]) -> list[dict]:
    """业务工具规划（单轮，兼容旧调用）：返回 [{name, arguments}]。"""
    content, calls = tool_step([_sys_msg(TOOL_PLANNER_SYS), _human_msg(message)], tools)
    _ = content
    return calls


# 规划器系统提示：只负责挑工具，不产出最终答案
TOOL_PLANNER_SYS = (
    "你是教务智能助手的「规划器」。根据用户问题与已获得的工具结果，"
    "决定下一步要调用哪些只读业务工具来补齐作答所需的事实。\n"
    "【优先用现成业务工具，它们更快更准】常见问法→工具：\n"
    "- '我带了哪些班/我有几个班/我的班级' → list_my_classes；\n"
    "- '我的学员/我带的学员/某个班的学员/这个班有哪些人' → find_students(class_name=班级名)；"
    "班级名不确定时先 list_my_classes 拿到班级名再查；\n"
    "- '某学员怎么样/考勤/课时余额' → student_progress(student_name=...)；\n"
    "- '课时不足/要催缴的学员' → find_students(low_balance_only=true)；\n"
    "- '某班学员评估是否完成/谁还没写评估' → class_evaluation_overview(class_name=班级名)；\n"
    "- '本周/本月排课考勤概况、达标率' → my_schedule_overview / my_teaching_stats。\n"
    "【只在现成工具覆盖不到时才用数据库工具】："
    "按 sql_list_tables → sql_describe_table → sql_query 顺序取数，必要时多轮修正 SQL。\n"
    "【硬性约束】：\n"
    "- 涉及'学员/名单/班级/课时/考勤/评估'等问题，必须实际调用相应工具拿到实时数据后再作答，"
    "禁止凭已有信息或记忆臆测；一次没查全就再查一次；\n"
    "- 不确定班级名时，先 list_my_classes 确认，再把它传入 find_students/class_evaluation_overview；\n"
    "- 教师用 sql_query 查含教师归属的表必须带自己的 teacher_id；\n"
    "- 与业务数据无关（制度问答/闲聊）时不要调用任何工具。"
)


def tool_step(messages: list, tools: list[dict]) -> tuple[str, list[dict]]:
    """一次非流式 function-calling 步骤：返回 (文本内容, [{id, name, arguments}])。

    供规划层多轮循环使用：把上一轮工具结果以 HumanMessage 追加后再调用本函数即可。
    温度取 0（规划要确定性）。未配置 LLM 时返回 ("", [])。
    """
    if not is_llm_configured():
        return "", []
    model = _plan_model()
    bound = model.bind_tools(tools)
    resp = bound.invoke(messages)
    content = resp.content if isinstance(resp.content, str) else ""
    calls: list[dict] = []
    for tc in getattr(resp, "tool_calls", None) or []:
        calls.append(
            {"id": tc.get("id") or "", "name": tc.get("name"), "arguments": tc.get("args") or {}}
        )
    return content, calls


def _sys_msg(text: str):
    from langchain_core.messages import SystemMessage

    return SystemMessage(content=text)


def _human_msg(text: str):
    from langchain_core.messages import HumanMessage

    return HumanMessage(content=text)


def generate_feedback_evaluation(
    *,
    template_content: str,
    student_name: str,
    class_name: str,
    subject: str,
    title: str | None = None,
    topic: str | None,
    content: str | None,
    performance: str | None,
    evaluation: str | None,
    homework: str | None,
) -> str:
    """按提示词模板生成/润色课堂评价正文（纯文本，非 JSON）。

    已有 evaluation 时在其基础上润色完善；没有则按模板直接生成。
    未配置 LLM 时抛 LLMConfigError；调用失败时也抛 LLMConfigError。
    """
    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI 草稿")

    values = {
        "student_name": student_name,
        "class_name": class_name,
        "subject": subject,
        "title": title,
        "topic": topic,
        "content": content,
        "performance": performance,
        "evaluation": evaluation,
        "homework": homework,
    }
    prompt = fill_template(template_content, values)
    material = (
        "\n\n【本堂课素材（必须引用，禁止编造素材之外的事实）】"
        f"\n学员：{student_name or '（未填写）'}"
        f"\n班级：{class_name or '（未填写）'}｜科目：{subject or '（未填写）'}"
        f"\n课题：{topic or '（未填写）'}"
        f"\n课题内容：{content or '（未填写）'}"
        f"\n课堂表现：{performance or '（未填写）'}"
        f"\n今日作业：{homework or '（未填写）'}"
    )
    prompt += (
        material
        + "\n\n请直接输出课堂评价正文（100-300 字，1-3 段）："
        "开头必须点出本堂课的科目与课题，并引用 1-2 个上面素材中的课堂细节；"
        "如果已提供现有课堂评价，请在其基础上润色完善（保留事实、优化措辞、适当补充细节）；"
        "否则按模板要求直接生成。只输出评价正文，不要输出标题、JSON 或多余说明。"
    )
    return _invoke(prompt)


def generate_report_summary(
    *,
    report_type: str,
    material: str,
    extra_note: str | None = None,
    style_note: str | None = None,
) -> dict[str, Any]:
    """按报告类型生成日报/周报草稿（结构化 JSON）。

    基于当日/本周素材（排课/考勤/反馈摘要）生成，人工编辑后保存。
    未配置 LLM 时抛 LLMConfigError；调用失败时也抛 LLMConfigError。
    """
    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI 草稿")

    if report_type == "daily":
        schema_hint = (
            '{"title": "如：8月31日 工作日报", "work": "今日工作内容", '
            '"courses": "今日授课情况", "problems": "遇到的问题与处理", "plan": "明日计划"}'
        )
        instruction = (
            "你是少儿编程培训机构的教务助手，请根据今日排课/考勤情况撰写一份工作日报草稿。"
            "文风简洁、条理清晰，work 概括今日工作，courses 描述授课情况，"
            "problems 如有问题则说明并给处理方式（没有就写无），plan 给明日计划。"
        )
    else:
        schema_hint = (
            '{"title": "如：第35周 工作周报", "summary": "本周工作总结", '
            '"highlights": "本周亮点", "problems": "问题与改进", "next_plan": "下周计划"}'
        )
        instruction = (
            "你是少儿编程培训机构的教务助手，请根据本周统计指标与课程情况撰写一份工作周报草稿。"
            "文风简洁、数据驱动：summary 概括本周工作，highlights 突出亮点，"
            "problems 客观指出问题并给改进建议，next_plan 给下周计划。"
        )

    prompt = (
        f"{instruction}\n"
        f"只返回一个 JSON 对象，不要多余文字，结构如下：\n"
        f"{schema_hint}\n\n"
        f"素材信息：\n{material}\n"
        + (f"\n教师补充说明：{extra_note}\n" if extra_note else "")
        + (f"\n写作风格要求（来自所选提示词模板）：\n{style_note}\n" if style_note else "")
    )
    raw = _invoke(prompt)
    return _parse_report_json(raw, report_type)


def generate_period_summary(
    *,
    report_type: str,
    material: str,
    extra_note: str | None = None,
    from_quarters: bool = False,
    style_note: str | None = None,
) -> dict[str, Any]:
    """按季度/年度素材生成总结草稿（结构化 JSON）。

    素材：季度=周期统计指标 + 已发布周报摘要；年度=已选季度总结聚合（from_quarters）
    或回退的周报口径。人工编辑后保存、生成 PPT。
    """
    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI 总结")

    label = "季度" if report_type == "quarterly" else "年度"
    schema_hint = (
        '{"title": "如：2026年第三季度 工作总结", '
        '"summary": "总体情况总结", "highlights": "主要亮点/成绩", '
        '"problems": "问题与改进方向", "next_plan": "下阶段计划", '
        '"stats_notes": "数据体现的教学情况说明"}'
    )
    if report_type == "yearly" and from_quarters:
        instruction = (
            "你是少儿编程培训机构的教务助手，请综合以下各季度总结"
            "（每篇含总体情况/亮点/问题/下阶段），撰写一份年度工作总结草稿。"
            "要求：综合提炼而非简单拼接，点名写出 Q1-Q4 之间的变化与差异"
            "（如哪个季度达标率最高、亮点如何延续、问题是否改善）；"
            "summary 概括全年走势，highlights 只写有季度依据的成绩，"
            "problems 指出跨季度反复出现的问题并给改进方向，"
            "next_plan 给出下年度可执行计划，stats_notes 用年度聚合数据说话。"
            "禁止空话套话，每段都要有季度事实或数据支撑。"
        )
    else:
        instruction = (
            f"你是少儿编程培训机构的教务助手，请根据{label}内的统计数据与各周周报摘要，"
            "撰写一份工作总结草稿。文风正式、结构清晰、数据驱动：summary 概括总体，"
            "highlights 突出成绩与亮点（可含学员进步、成果），problems 客观指出问题与改进方向，"
            "next_plan 给出下阶段计划，stats_notes 结合数据说明教学情况。"
        )
    prompt = (
        f"{instruction}\n"
        f"只返回一个 JSON 对象，不要多余文字，结构如下：\n"
        f"{schema_hint}\n\n"
        f"素材信息：\n{material}\n"
        + (f"\n教师补充说明：{extra_note}\n" if extra_note else "")
        + (f"\n写作风格要求（来自所选提示词模板）：\n{style_note}\n" if style_note else "")
    )
    raw = _invoke(prompt)
    return _parse_report_json(raw, report_type)


def _parse_report_json(raw: str, report_type: str) -> dict[str, Any]:
    """从模型输出提取 JSON；剔除代码块杂质，解析失败时整体作为 summary 兜底。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    keys = [
        "title", "summary", "highlights", "problems", "next_plan", "work", "courses", "plan",
        "stats_notes",
    ]
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {k: _clean(data.get(k)) for k in keys}
    except json.JSONDecodeError:
        pass
    if report_type == "daily":
        return {"title": None, "work": text, "courses": None, "problems": None, "plan": None}
    return {
        "title": None,
        "summary": text,
        "highlights": None,
        "problems": None,
        "next_plan": None,
    }


# ---------------------------------------------------------------------------
# M6 学员评估：生成 / 对话优化（FR-EV-01 / FR-EV-03）
# ---------------------------------------------------------------------------

_EVALUATION_SCHEMA_HINT = (
    "{\n"
    '  "title": "如：王小明 2026年春季学习评估",\n'
    '  "summary": "综合表现总结（150-300字，写给家长，语气亲切、有事实依据）",\n'
    '  "subjects": [                        // 学科能力（2-4 项）\n'
    '    {"name": "编程思维", "level": 4, "comment": "一句话点评"},\n'
    '    {"name": "代码实践", "level": 3, "comment": "一句话点评"}\n'
    '  ],\n'
    '  "progress": "进步点（结合周期内课程事实，2-4 条，每条一句话）",\n'
    '  "to_improve": "待提升项（客观温和，2-3 条）",\n'
    '  "suggestions": "给家长的建议（家庭练习/学习习惯等，2-3 条）"\n'
    "}"
)

_EVALUATION_KEYS = ("title", "summary", "subjects", "progress", "to_improve", "suggestions")


def generate_evaluation(
    *,
    student_name: str,
    material: str,
    extra_note: str | None = None,
    style_guide: str | None = None,
) -> dict[str, Any]:
    """生成学员综合评估表草稿（FR-EV-01/02，结构化 JSON）。

    素材 = 周期统计 + 已发布课后反馈明细；subjects.level 为 1-5 整数。
    未配置 LLM 时抛 LLMConfigError；调用失败时也抛 LLMConfigError。
    """
    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI 评估")

    instruction = (
        f"你是少儿编程培训机构的资深教师，正在为学员 {student_name} 撰写家长会评估表"
        f"（每 3 个月一次，给家长看）。请基于本评估周期内的统计数据与课后反馈记录，"
        "撰写一份综合评估草稿：语气亲切真诚、有具体事实依据、突出孩子的成长，"
        "避免空话套话；待提升项客观温和并给出可操作的建议。"
    )
    prompt = (
        f"{instruction}\n"
        f"只返回一个 JSON 对象，不要多余文字，结构如下：\n"
        f"{_EVALUATION_SCHEMA_HINT}\n\n"
        "要求：\n"
        "1. subjects 中的 level 为 1-5 整数（5=非常优秀，4=优秀，3=良好，2=需加强，1=待观察），"
        "必须基于反馈中体现的真实水平评分；\n"
        "2. progress 用「；」分隔 2-4 条进步点（一段文本内）；"
        "to_improve / suggestions 同样一段文本内用「；」分隔条目；\n"
        "3. 所有内容必须引用周期内课程/作业中的真实细节，不要编造。\n\n"
        f"素材信息（学员：{student_name}）：\n{material}\n"
        + (f"\n教师补充说明/想强调的重点：{extra_note}\n" if extra_note else "")
        + (f"\n写作风格要求（教师所选提示词模板，请遵守）：\n{style_guide}\n" if style_guide else "")
    )
    raw = _invoke(prompt)
    return _parse_evaluation_json(raw)


def refine_evaluation(
    *,
    student_name: str,
    current: dict[str, Any],
    instruction: str,
) -> dict[str, Any]:
    """对话式优化评估（FR-EV-03）：基于现有评估 + 教师修改要求重写整份评估。"""
    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI 优化")

    prompt = (
        f"你是少儿编程培训机构的资深教师。下面是学员 {student_name} 的家长会评估表，"
        f"请根据教师的修改要求调整内容（保持整体结构与 JSON 格式不变）。\n\n"
        f"当前评估（JSON）：\n{json.dumps(current, ensure_ascii=False)}\n\n"
        f"教师的修改要求：{instruction}\n\n"
        f"只返回调整后的完整 JSON 对象，结构如下：\n"
        f"{_EVALUATION_SCHEMA_HINT}\n"
        "要求：未被要求调整的部分保持原意；语言仍需亲切自然、有事实依据。"
    )
    raw = _invoke(prompt)
    parsed = _parse_evaluation_json(raw)
    # 兜底：解析失败时保留原稿，避免覆盖丢内容
    if not parsed.get("summary"):
        return {k: current.get(k) for k in _EVALUATION_KEYS}
    return parsed


# ---------------------------------------------------------------------------
# M6 班级家长会 PPT：以班级为单位的汇报文案（结合全班学员评估提炼）
# ---------------------------------------------------------------------------

_CLASS_MEETING_SCHEMA_HINT = (
    "{\n"
    '  "title": "家长会标题，如：Scratch 启蒙班 阶段学习汇报家长会",\n'
    '  "class_summary": "班级整体学习情况总结（200-350字，面向全体家长，有数据支撑）",\n'
    '  "ability_comment": "能力培养点评（100-180字，结合各能力项班级平均分）",\n'
    '  "highlights": "班级亮点（2-4条，用「；」分隔；可点名表扬进步突出的学员）",\n'
    '  "to_improve": "班级共性问题与改进措施（2-3条，用「；」分隔）",\n'
    '  "next_plan": "下阶段教学安排（2-4条：教学内容/目标/活动，用「；」分隔）",\n'
    '  "home_suggestions": "给家长的建议（2-3条：家庭如何配合，用「；」分隔）"\n'
    "}"
)

# 写作规范：整段字段连贯成文；列表字段每条必须是完整的一句话（PPT 按句渲染编号卡片）
_CLASS_MEETING_WRITING_RULES = (
    "写作规范（务必遵守）：\n"
    "- class_summary 与 ability_comment 是**连贯的整段文字**：正常使用逗号衔接，"
    "只在语义完整处用句号，不要用「；」或换行把整段拆成小碎句；\n"
    "- highlights / to_improve / next_plan / home_suggestions 是**要点列表**："
    "每条以「；」分隔，且每条必须是一个语法完整的句子（有主语谓语，以句号结尾），"
    "一条只说一件事，不要在一条里塞多个主题，也不要每条只有几个字；\n"
    "- 不使用 Markdown 符号（*、-、#）或序号前缀（1. / ①）。\n"
)

_CLASS_MEETING_KEYS = (
    "title",
    "class_summary",
    "ability_comment",
    "highlights",
    "to_improve",
    "next_plan",
    "home_suggestions",
)


def generate_class_meeting(
    *,
    class_name: str,
    material: str,
    extra_note: str | None = None,
) -> dict[str, Any]:
    """生成班级家长会 PPT 文案（结合全班学员评估提炼，结构化 JSON）。

    与单学员评估不同：这里面向全体家长，输出班级共性内容 —— 整体学习情况、
    能力培养、班级亮点（可点名）、共性问题、下阶段教学安排与家庭配合建议。
    未配置 LLM 时抛 LLMConfigError；调用失败时也抛 LLMConfigError。
    """
    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI 生成家长会文案")

    instruction = (
        f"你是少儿编程培训机构的资深教师兼班主任，正在准备「{class_name}」的家长会 PPT"
        f"（面向全班家长汇报本阶段学习情况与下阶段安排）。请基于班级统计数据与全班学员的"
        "评估摘要，撰写班级层面的汇报内容：\n"
        "1. 提炼共性、有数据支撑，不要照搬任何单个学员的评估原文；\n"
        "2. highlights 可点名表扬进步突出的学员（基于其评估中的进步事实），"
        "其余内容以班级整体视角撰写；\n"
        "3. next_plan 要具体可落地（教什么、练什么、做什么活动、达到什么目标）；\n"
        "4. 语气亲切专业，家长能听懂，避免空话套话。\n"
        f"{_CLASS_MEETING_WRITING_RULES}"
    )
    prompt = (
        f"{instruction}\n"
        f"只返回一个 JSON 对象，不要多余文字，结构如下：\n"
        f"{_CLASS_MEETING_SCHEMA_HINT}\n\n"
        f"班级素材信息：\n{material}\n"
        + (f"\n教师补充说明/想强调的重点：{extra_note}\n" if extra_note else "")
    )
    raw = _invoke(prompt)
    return _parse_class_meeting_json(raw)


def generate_ppt_titles(
    *,
    class_name: str,
    material: str,
) -> list[str]:
    """为班级家长会拟 4 个标题（Agent Step 2，异步任务内使用）。"""
    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI 生成标题")
    return generate_ppt_titles_sync(class_name=class_name, material=material, style="")


def generate_ppt_titles_sync(
    *,
    class_name: str,
    material: str,
    style: str = "",
) -> list[str]:
    """为班级家长会拟标题（同步接口内使用，超时/失败由调用方兜底）。

    - prompts 按风格注入差异化要求：A 温馨故事感 / B 专业数据感 / C 活泼童趣 / D 简约现代
    - 解析宽容：严格 JSON → 宽松 [] 提取 → 按行/标点拆分兜底
    """
    from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

    style_hint = {
        "A": "温馨亲切、有故事感，突出陪伴与成长",
        "B": "专业严谨、有数据感，突出成果与规划",
        "C": "活泼童趣、面向孩子与家长共读，多用生动意象",
        "D": "简约现代、克制有力，突出关键词",
    }.get(style, "风格各异且不重复")
    prompt = (
        f"你是家长会标题策划。请为「{class_name}」基于以下班级素材拟 4 个家长会标题，"
        f"要求：12-18字、有记忆点、适合家长会封面，{style_hint}。\n"
        '只返回 JSON 数组 ["标题1","标题2","标题3","标题4"]，不要多余文字。\n\n'
        f"素材：\n{material}\n"
    )
    try:
        raw = _invoke_fast(prompt)
    except (APITimeoutError, APIConnectionError, RateLimitError, AuthenticationError) as e:
        raise RuntimeError(f"标题生成调用失败：{e}") from e
    text = raw.strip().strip("`")
    if text.startswith("json"):
        text = text[4:].strip()
    s, e = text.find("["), text.rfind("]")
    if s != -1 and e != -1 and e > s:
        text = text[s : e + 1]
    try:
        arr = json.loads(text)
        if isinstance(arr, list):
            titles = [str(x).strip().strip("「」\"'") for x in arr if str(x).strip()][:4]
            if len(titles) >= 2:
                return titles
    except json.JSONDecodeError:
        pass
    # 宽松兜底：模型没按 JSON 返回时，按行/标点拆分
    import re as _re

    parts = _re.split(r"[\n；;、]+", text.strip().strip("[]"))
    parts = [p.strip().strip("\"'「」1234567890.、 ") for p in parts if p.strip()]
    if len(parts) >= 2:
        return parts[:4]
    local = [
        f"{class_name} 阶段学习汇报",
        f"看见每一次进步 · {class_name}",
        f"一起见证成长 · {class_name}",
        f"{class_name} 家长会",
    ]
    return local if not parts else (parts + local)[:4]


def _invoke_fast(prompt: str) -> str:
    """同步接口用的快速调用：超时 25s + 不重试，避免前端 15s 超时先挂。"""
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    base_url = (settings.LLM_BASE_URL or "").rstrip("/")
    if base_url and not base_url.endswith("/v1"):
        base_url += "/v1"
    model = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=base_url or None,
        temperature=0.7,
        timeout=25,
        max_retries=0,
    )
    sys_text = "你是少儿编程培训机构的家长会标题策划，擅长起有记忆点的中文标题。只按要求返回结果，不解释。"
    resp = model.invoke([SystemMessage(content=sys_text), HumanMessage(content=prompt)])
    return (resp.content or "").strip()


def refine_ppt_content(
    *,
    current: dict[str, Any],
    instruction: str,
) -> dict[str, Any]:
    """对话式微调班级家长会文案（Agent 生成后二次编辑）。"""
    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI 微调")
    prompt = (
        "你是家长会PPT文案编辑。请基于当前文案按用户指令修改，未提及字段保持原意。\n"
        f"当前文案JSON：{json.dumps(current, ensure_ascii=False)}\n"
        f"用户指令：{instruction}\n\n"
        f"只返回完整JSON，结构如下：\n{_CLASS_MEETING_SCHEMA_HINT}\n"
        f"{_CLASS_MEETING_WRITING_RULES}"
    )
    raw = _invoke(prompt)
    parsed = _parse_class_meeting_json(raw)
    if not parsed.get("class_summary") and not parsed.get("highlights"):
        return current
    # 标题若被改为空则保留原标题
    if not parsed.get("title"):
        parsed["title"] = current.get("title")
    return parsed


def _parse_class_meeting_json(raw: str) -> dict[str, Any]:
    """从模型输出提取班级家长会 JSON；解析失败时把整段文本作为 class_summary 兜底。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {
                k: (clean_listish_text(data.get(k)) if k != "title" else _clean(data.get(k)))
                for k in _CLASS_MEETING_KEYS
            }
    except json.JSONDecodeError:
        pass
    fallback = _clean(text) or ""
    return {k: None for k in _CLASS_MEETING_KEYS} | {
        "class_summary": fallback[:1500] or None,
    }


def _parse_evaluation_json(raw: str) -> dict[str, Any]:
    """从模型输出提取评估 JSON；解析失败时把整段文本作为 summary 兜底。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return _normalize_evaluation(data)
    except json.JSONDecodeError:
        pass
    fallback = _clean(text) or ""
    return {k: None for k in _EVALUATION_KEYS} | {
        "summary": fallback[:1500] or None,
        "subjects": [],
    }


def _normalize_evaluation(data: dict[str, Any]) -> dict[str, Any]:
    """规范化评估字段：subjects 列表裁剪、level 限 1-5、文本字段清洗。"""
    subjects_raw = data.get("subjects")
    subjects: list[dict[str, Any]] = []
    if isinstance(subjects_raw, list):
        for item in subjects_raw[:6]:
            if not isinstance(item, dict):
                continue
            name = _clean(item.get("name"))
            if not name:
                continue
            try:
                level = int(item.get("level", 3))
            except (TypeError, ValueError):
                level = 3
            subjects.append(
                {
                    "name": name,
                    "level": max(1, min(5, level)),
                    "comment": _clean(item.get("comment")),
                }
            )

    return {
        "title": _clean(data.get("title")),
        "summary": clean_listish_text(data.get("summary")),
        "subjects": subjects,
        "progress": clean_listish_text(data.get("progress")),
        "to_improve": clean_listish_text(data.get("to_improve")),
        "suggestions": clean_listish_text(data.get("suggestions")),
    }


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


_LIST_SHAPED_RE = re.compile(r"^\[.*\]$", re.DOTALL)
_QUOTED_ITEM_RE = re.compile(r"['\"]([^'\"]+)['\"]")


def clean_listish_text(value: Any) -> str | None:
    """「多条目」文本字段清洗：LLM 偶尔把 progress 等字段输出为数组，需拼成一段文本。

    - list/tuple → 以「；」拼接
    - 历史脏数据（已被 str() 成 "['a', 'b']" 的字符串）→ 解析后同样拼接
    - 其余按普通文本去空白处理
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        parts = [p for p in (_clean(v) for v in value) if p]
        return "；".join(parts) if parts else None
    s = str(value).strip()
    if _LIST_SHAPED_RE.match(s):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                parts = [p for p in (_clean(v) for v in parsed) if p]
                if parts:
                    return "；".join(parts)
        except json.JSONDecodeError:
            pass
        items = [m.strip() for m in _QUOTED_ITEM_RE.findall(s) if m.strip()]
        if items:
            return "；".join(items)
    return s or None


# ---------------------------------------------------------------------------
# M4 AI 习题：举一反三 / 作业模式 / 对话优化
# ---------------------------------------------------------------------------

_QUESTION_TYPE_HINT = (
    '题型 type 取值："single_choice"（单选）、"multiple_choice"（多选）、'
    '"judgement"（判断）、"code_fill"（代码填空）、"programming"（编程题）'
)

_QUESTION_SCHEMA_HINT = (
    "{\n"
    '  "type": "single_choice|multiple_choice|judgement|code_fill|programming",\n'
    '  "stem": "题干（代码填空题/编程题请包含必要的代码或题目说明）",\n'
    '  "options": ["选项A", "选项B", "选项C", "选项D"],   // 仅选择题需要，其余题型为 null 或省略\n'
    '  "answer": 0,          // 单选=int（选项索引）；多选=[0,2]；'
    '判断=true/false；代码填空/编程题=参考代码文本\n'
    '  "analysis": "答案解析（代码填空题请先给出「填空对照：① = 答案（说明）；'
    '② = 答案（说明）」）",\n'
    '  "difficulty": 3,      // 1-10 整数（对应少儿编程考级等级，1=一级…10=十级）\n'
    '  "test_cases": null,   // 仅编程题：可给 [{"input": "1 2", "output": "3"}]，否则 null\n'
    '  "language": "python"  // 仅编程题：python / cpp，其余为 null\n'
    "}"
)

_QUESTION_KEYS = (
    "type", "stem", "options", "answer", "analysis", "difficulty",
    "test_cases", "language",
)


def generate_questions(
    *,
    mode: str,
    count: int,
    difficulty: int,
    source_question: str | None = None,
    source_answer: str | None = None,
    hint: str | None = None,
    types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """AI 出题（FR-AI-01 / FR-AI-04）：

    - mode=similar  举一反三：基于 source_question（可选 source_answer）生成 count 道相似题
    - mode=homework 作业模式：基于知识点 hint（提示语）生成 count 道整套题目

    返回题目列表（含答案/解析），由调用方回填模板窗口供人工编辑；
    未配置 LLM 时抛 LLMConfigError；调用失败时也抛 LLMConfigError。
    """
    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI 出题")

    if mode == "similar":
        if not source_question:
            raise LLMConfigError("举一反三模式需要提供原题题干")
        instruction = (
            f"你是少儿编程培训机构的资深出题老师。请根据下面这道原题，改编出 {count} 道"
            f"**知识点相同、情境不同**的相似练习题（举一反三），难度 {difficulty}/10 级"
            f"（少儿编程考级等级，1=一级最简单，10=十级最难）。\n"
            f"原题：\n{source_question}\n"
            + (
                f"原题参考答案/解析（仅供你把握考点，可参考不照抄）：\n{source_answer}\n"
                if source_answer
                else ""
            )
        )
    else:
        if not hint:
            raise LLMConfigError("作业模式需要填写知识点提示语")
        if types:
            total = count * len(types)
            type_hint = (
                f"指定题型与题数：**每种题型各 {count} 道**——"
                f"{'、'.join(f'{t} {count} 道' for t in types)}，"
                f"共 {total} 道。"
            )
        else:
            total = count
            type_hint = (
                "题型由你按知识点合理分配（建议混合单选/多选/判断，涉及编程再给编程题）。"
            )
        instruction = (
            f"你是少儿编程培训机构的资深出题老师。请围绕知识点「{hint}」设计适合少儿编程"
            f"课堂的练习题（作业模式），难度 {difficulty}/10 级"
            f"（少儿编程考级等级，1=一级最简单，10=十级最难）。{type_hint}"
        )

    prompt = (
        f"{instruction}\n\n"
        f"只返回一个 JSON 数组，不要多余文字。每个元素结构如下：\n"
        f"{_QUESTION_SCHEMA_HINT}\n\n"
        "要求：\n"
        "1. 题干面向小学生通俗易懂；选择题必须提供 4 个选项且 answer 为正确选项索引；"
        "判断题 answer 为 true/false；每道题必须附带解析（analysis）；"
        "所有题目的难度都为你被指定的难度。\n"
        "2. **参考代码必须按标准格式书写**：多行、4 空格缩进，**每一行都加上中文注释**"
        "（如 # 读取输入），严禁把多行代码压成一行。\n"
        "3. **代码填空题**：题干代码中的空格用 ①、②、③… 编号标出（每题至少 1 个空）；"
        "answer 为补全后的完整参考代码（同样多行+逐行注释）；"
        "analysis 必须先用「填空对照：① = 答案（说明）；② = 答案（说明）」逐空说明，再写解题思路。"
    )
    raw = _invoke(prompt)
    total_needed = count * len(types) if types else count
    return _parse_questions(raw, total_needed)


def refine_question(
    *,
    question: dict[str, Any],
    instruction: str,
) -> dict[str, Any]:
    """对话优化单题（FR-AI-05）：基于原题 + 教师修改要求重新生成一题。"""
    _require_any_llm("未配置 LLM_API_KEY，暂时无法使用 AI 优化")

    prompt = (
        f"你是少儿编程培训机构的资深出题老师。下面是作业中的一道题，请根据教师的修改要求"
        f"重新设计这道题（保持题型与知识点不变，除非要求里明确要求换题型）。\n\n"
        f"当前题目（JSON）：\n{json.dumps(question, ensure_ascii=False)}\n\n"
        f"教师的修改要求：{instruction}\n\n"
        f"只返回一个 JSON 对象，不要多余文字，结构如下：\n"
        f"{_QUESTION_SCHEMA_HINT}\n"
        "要求：保留原题知识点，按修改要求调整；选择题 4 个选项且 answer 为正确选项索引；"
        "每道题必须附带解析（analysis）。"
    )
    raw = _invoke(prompt)
    parsed = _parse_questions(raw, 1)
    return parsed[0] if parsed else dict(question)


def _parse_questions(raw: str, count: int) -> list[dict[str, Any]]:
    """从模型输出提取题目 JSON 数组；解析失败/缺字段的题目剔除，至少返回 1 题兜底。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError("not a list")
    except (json.JSONDecodeError, ValueError):
        # 兜底：把整段文本当作一道编程题/填空题，避免空结果
        return [_fallback_question(text, count)]

    questions: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        qtype = str(item.get("type") or "").strip()
        stem = _clean(item.get("stem"))
        if qtype not in _QUESTION_TYPE_VALUES or not stem:
            continue
        questions.append(_normalize_question(item, qtype))
        if len(questions) >= count:
            break
    if not questions:
        return [_fallback_question(text, count)]
    return questions


_QUESTION_TYPE_VALUES = {
    "single_choice", "multiple_choice", "judgement", "code_fill", "programming",
}


def _normalize_question(item: dict[str, Any], qtype: str) -> dict[str, Any]:
    """规范化单题字段：按题型补默认值、限定语言、规整答案类型。"""
    options = item.get("options")
    if qtype in ("single_choice", "multiple_choice"):
        if not isinstance(options, list) or not options:
            options = ["选项A", "选项B", "选项C", "选项D"]
        options = [str(o) for o in options[:6]]
    else:
        options = None

    answer = item.get("answer")
    if qtype == "judgement":
        if isinstance(answer, str):
            answer = answer.strip().lower() in ("true", "正确", "对", "√", "1")
        else:
            answer = bool(answer)
    elif qtype in ("single_choice", "multiple_choice"):
        if isinstance(answer, str) and answer.isdigit():
            answer = int(answer)
        if (
            qtype == "single_choice"
            and isinstance(answer, int)
            and not (0 <= answer < len(options))
        ):
            answer = 0
        if qtype == "multiple_choice" and isinstance(answer, list):
            answer = [
                int(a)
                for a in answer
                if isinstance(a, (int, str)) and str(a).lstrip("-").isdigit()
            ]
    else:
        answer = str(answer or "").strip() or None

    language = None
    test_cases = None
    if qtype == "programming":
        language = str(item.get("language") or "python").lower()
        if language not in ("python", "cpp"):
            language = "python"
        tc = item.get("test_cases")
        if isinstance(tc, list) and tc:
            test_cases = [
                {"input": str(t.get("input", "")), "output": str(t.get("output", ""))}
                for t in tc
                if isinstance(t, dict)
            ][:10]

    difficulty = item.get("difficulty", 3)
    try:
        difficulty = int(difficulty)
    except (TypeError, ValueError):
        difficulty = 3
    difficulty = max(1, min(10, difficulty))

    return {
        "type": qtype,
        "stem": str(item.get("stem", "")).strip(),
        "options": options,
        "answer": answer,
        "analysis": _clean(item.get("analysis")),
        "difficulty": difficulty,
        "test_cases": test_cases,
        "language": language,
    }


def _fallback_question(text: str, count: int) -> dict[str, Any]:
    """模型输出无法解析时兜底：生成一道代码填空题（人工可改题型）。"""
    return {
        "type": "code_fill",
        "stem": (
            "（AI 生成内容解析失败，请参考以下要点手动出题，或点击重试）\n\n"
            f"{text[:800]}"
        ),
        "options": None,
        "answer": None,
        "analysis": "请补充解析",
        "difficulty": 3,
        "test_cases": None,
        "language": None,
    }
