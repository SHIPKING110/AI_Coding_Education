"""判题引擎（M5，OQ-03 决策 = 客观题自动判 + 编程题教师人工批改）

- 客观题（单选题/多选题/判断题/代码填空题）提交时自动判题，写入 judge_results
- 编程题（programming）不做沙箱执行（安全考虑），标记「待教师批改」
- 每题满分 = 该题型分值（作业 type_scores 配置，未配置默认 1 分）；
  得分累计为 submission.score，满分 total = 各题分值之和
- expected/actual 存可读文本（选择题选项转 "A. xxx"，判断转 √/×），
  家长/学员端直接展示无需再转换
"""

import re

from app.models.assignment import Question, QuestionType


def _normalize_code(text: str) -> str:
    s = (text or "").strip()
    return re.sub(r"\s+", " ", s)


def question_points(type_scores: dict | None, qtype: str) -> int:
    """按作业题型分值配置取单题满分（未配置/非法值回退 1 分）。"""
    if not type_scores:
        return 1
    try:
        return max(1, int(type_scores.get(qtype, 1) or 1))
    except (TypeError, ValueError):
        return 1


def judge_question(
    question: Question, answer: object, points: int = 1
) -> dict:
    """判单题，返回 judge_results 条目（score/max_score 按题型分值）。"""
    qtype = question.type
    expected = question.answer
    options = question.options or []

    def _choice_text(idx) -> str:
        """选项下标 -> 可读文本（如 "A. printf"）。"""
        if isinstance(idx, int) and 0 <= idx < len(options):
            return f"{'ABCDEFGH'[idx]}. {options[idx]}"
        return str(idx)

    if qtype == QuestionType.SINGLE_CHOICE.value:
        correct = isinstance(answer, int) and answer == expected
        return {
            "correct": bool(correct),
            "expected": _choice_text(expected) if isinstance(expected, int) else str(expected),
            "actual": _choice_text(answer) if isinstance(answer, int) else str(answer),
            "score": points if correct else 0,
            "max_score": points,
            "judged": True,
        }
    if qtype == QuestionType.MULTIPLE_CHOICE.value:
        exp_set = set(expected) if isinstance(expected, (list, set)) else set()
        act_set = set(answer) if isinstance(answer, (list, set)) else set()
        correct = len(exp_set) > 0 and exp_set == act_set
        return {
            "correct": bool(correct),
            "expected": "、".join(_choice_text(i) for i in sorted(exp_set)),
            "actual": "、".join(_choice_text(i) for i in sorted(act_set)),
            "score": points if correct else 0,
            "max_score": points,
            "judged": True,
        }
    if qtype == QuestionType.JUDGEMENT.value:
        correct = isinstance(answer, bool) and answer == expected
        return {
            "correct": bool(correct),
            "expected": "√ 正确" if expected else "× 错误",
            "actual": (
                "√ 正确" if answer else "× 错误"
            ) if isinstance(answer, bool) else str(answer),
            "score": points if correct else 0,
            "max_score": points,
            "judged": True,
        }
    if qtype == QuestionType.CODE_FILL.value:
        exp_norm = _normalize_code(str(expected or ""))
        act_norm = _normalize_code(str(answer or ""))
        correct = bool(exp_norm) and exp_norm == act_norm
        return {
            "correct": bool(correct),
            "expected": exp_norm,
            "actual": act_norm,
            "score": points if correct else 0,
            "max_score": points,
            "judged": True,
        }
    # programming：待教师批改；expected 展示参考代码
    return {
        "correct": None,
        "expected": str(expected) if expected else "待教师批改",
        "actual": answer if answer is not None else None,
        "score": None,
        "max_score": points,
        "judged": False,
    }


def judge_submission(
    questions: list[Question],
    answers: dict,
    type_scores: dict | None = None,
) -> tuple[dict, int, int, int]:
    """整体判题。返回 (judge_results, score, pending_manual_count, total)。"""
    judge_results = {}
    auto_score = 0
    pending_manual = 0
    total = 0
    for q in questions:
        key = str(q.order_no)
        points = question_points(type_scores, q.type)
        total += points
        ans = answers.get(key)
        if ans is None:
            is_prog = q.type == QuestionType.PROGRAMMING.value
            judge_results[key] = {
                "correct": False,
                "expected": "未作答",
                "actual": None,
                "score": None if is_prog else 0,
                "max_score": points,
                "judged": not is_prog,
            }
            if is_prog:
                pending_manual += 1
            continue
        result = judge_question(q, ans, points)
        judge_results[key] = result
        if result.get("score") is not None:
            auto_score += result["score"]
        else:
            pending_manual += 1
    return judge_results, auto_score, pending_manual, total
