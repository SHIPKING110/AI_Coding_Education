"""题库结构化校验：零成本规则先行，AI 校准只处理规则发现的问题题。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

OBJECTIVE_TYPES = {"single_choice", "multiple_choice", "judgement", "code_fill"}


def question_content_hash(item: dict[str, Any]) -> str:
    payload = {
        "type": item.get("type"),
        "stem": item.get("stem") or "",
        "options": item.get("options"),
        "answer": item.get("answer"),
        "analysis": item.get("analysis") or "",
        "reference_code": item.get("reference_code") or "",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_question(item: dict[str, Any], *, order_no: int | None = None) -> list[dict[str, Any]]:
    """返回结构化问题：code/level/message/question_no。"""
    issues: list[dict[str, Any]] = []
    no = order_no if order_no is not None else item.get("order_no")

    def add(code: str, message: str, level: str = "warning") -> None:
        issues.append({"code": code, "level": level, "message": message, "question_no": no})

    qtype = item.get("type")
    stem = (item.get("stem") or "").strip()
    options = item.get("options")
    answer = item.get("answer")
    analysis = (item.get("analysis") or "").strip()
    score = int(item.get("score") or 0)

    if not stem or stem == "待补充题干":
        add("empty_stem", f"第 {no} 题题干为空")
    if qtype in {"single_choice", "multiple_choice"}:
        if not options:
            add("missing_options", f"第 {no} 题缺少选项")
        else:
            if any((opt or "").strip() == "" for opt in options):
                add("empty_option", f"第 {no} 题存在空选项")
            if qtype == "single_choice" and isinstance(answer, int):
                if not 0 <= answer < len(options):
                    add("answer_out_of_range", f"第 {no} 题答案 {answer + 1} 超出选项范围", "error")
            if qtype == "multiple_choice" and isinstance(answer, list):
                if any((not isinstance(x, int)) or x < 0 or x >= len(options) for x in answer):
                    add("answer_out_of_range", f"第 {no} 题多选答案超出选项范围", "error")
    if qtype in {"single_choice", "multiple_choice", "judgement"} and answer is None:
        add("missing_answer", f"第 {no} 题缺少可识别答案")
    if qtype in {"programming", "code_fill"} and not (item.get("reference_code") or "").strip():
        add("missing_reference_code", f"第 {no} 题缺少参考代码")
    if qtype in OBJECTIVE_TYPES and not analysis:
        add("missing_analysis", f"第 {no} 题缺少解析")
    if score <= 0:
        add("invalid_score", f"第 {no} 题分值无效")
    return issues


def validate_questions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """整卷校验：题号连续性 + 每题字段完整性。"""
    issues: list[dict[str, Any]] = []
    expected: int | None = None
    for idx, item in enumerate(items, start=1):
        no = int(item.get("order_no") or idx)
        if expected is not None and no != expected:
            issues.append(
                {
                    "code": "number_gap",
                    "level": "warning",
                    "message": f"题号从 {expected} 跳到 {no}，请核对是否漏题",
                    "question_no": no,
                }
            )
        expected = no + 1
        issues.extend(validate_question(item, order_no=no))
    return issues
