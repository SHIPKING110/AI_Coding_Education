"""编程题 AI 客观评分：按题目要求与参考答案评估学员代码，返回得分与评语。

成本记账：评分经由 `app.services.llm.invoke_text` 调用，并在 `use_teacher_llm`
上下文中执行，用量会被自动写入 usage_meter，模块名为 "assignment"（AI 习题），
与出题/评语等其它 LLM 调用一致，可在「用量与成本」模块查看。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import llm
from app.services.llm import LLMConfigError
from app.services.llm_context import use_teacher_llm

_GRADE_SYSTEM = "你是一名严格的少儿编程阅卷老师，只输出 JSON，不要输出其它内容。"
_JSON_RE = re.compile(r"\{.*\}", re.S)


def _parse(raw: str) -> dict[str, Any]:
    match = _JSON_RE.search(raw or "")
    if not match:
        raise ValueError("评分结果无法解析")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError("评分结果不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("评分结果结构不正确")
    return data


def grade_programming(
    db: Session,
    user: User,
    item: dict[str, Any],
    answer: str,
) -> dict[str, Any]:
    """对一道编程题作答打分。

    返回 {"is_correct": bool, "score": int, "feedback": str}；
    LLM 未配置时抛 LLMConfigError，其它失败抛 ValueError，由调用方降级处理。
    """
    max_score = int(item.get("score") or 0)
    reference = item.get("reference_code") or item.get("answer") or "（无参考答案）"
    prompt = (
        "请根据题目要求与参考答案，对学员提交的代码进行客观评分。\n"
        f"题干：\n{item.get('stem') or ''}\n"
        f"参考答案/参考程序：\n{reference}\n"
        f"学员代码：\n```\n{answer}\n```\n"
        '只输出 JSON：{"score": 整数, "correct": true/false, "feedback": "面向学员的中文点评"}。'
        f"满分 {max_score} 分。核心逻辑满足题意即可判 correct=true（实现方式不同不影响）；"
        "逻辑有误但部分正确可给部分分（correct=false）。feedback 限 2 句以内，指出对错与改进点。"
    )
    with use_teacher_llm(db, user.id, "assignment") as resolved:
        raw = llm.invoke_text(system=_GRADE_SYSTEM, prompt=prompt, temperature=0.0, timeout=90)
    data = _parse(raw)
    try:
        score = int(data.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(max_score, score))
    correct_raw = data.get("correct")
    is_correct = bool(correct_raw) if correct_raw is not None else score >= max_score
    feedback = str(data.get("feedback") or "").strip() or None
    return {"is_correct": is_correct, "score": score, "feedback": feedback}
