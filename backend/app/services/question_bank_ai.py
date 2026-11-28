"""题库 AI 校准/打标/能力评语：全部调用归入 assignment（AI 习题）模块。"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.question_bank import (
    BankQuestionStatus,
    PracticeAbilityReport,
    QuestionBankAiReview,
    QuestionBankKpTaxonomy,
    QuestionBankQuestion,
    QuestionBankSet,
)
from app.models.user import User
from app.services import llm
from app.services.llm import LLMConfigError, friendly_llm_error
from app.services.llm_context import use_teacher_llm
from app.services.question_bank_validation import question_content_hash

VALID_TYPES = {"single_choice", "multiple_choice", "judgement", "code_fill", "programming"}


def _extract_json(raw: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise ValueError("AI 未返回可解析的 JSON")
    return json.loads(match.group(0))


def _answer_text(item: dict[str, Any]) -> str:
    qtype = item.get("type")
    answer = item.get("answer")
    if qtype == "single_choice" and isinstance(answer, int):
        return chr(ord("A") + answer) if 0 <= answer < 26 else str(answer)
    if qtype == "multiple_choice" and isinstance(answer, list):
        return ",".join(chr(ord("A") + int(x)) for x in answer if isinstance(x, int))
    if qtype == "judgement":
        return "正确" if answer else "错误"
    if isinstance(answer, list):
        return ",".join(str(x) for x in answer)
    return "" if answer is None else str(answer)


def _answer_from_text(value: Any, qtype: str, options: list[str] | None) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if qtype == "multiple_choice":
        letters = re.findall(r"[A-H]", text.upper())
        if letters:
            return sorted({ord(ch) - ord("A") for ch in letters})
        numbers = re.findall(r"\d+", text)
        if numbers:
            return sorted({int(n) - 1 for n in numbers if int(n) > 0})
        return value
    if qtype == "single_choice":
        letters = re.findall(r"[A-H]", text.upper())
        if letters:
            return ord(letters[0]) - ord("A")
        number_match = re.search(r"\d+", text)
        if number_match and options:
            return int(number_match.group(0)) - 1
        return value
    if qtype == "judgement":
        if text in {"正确", "对", "true", "True", "是", "√"}:
            return True
        if text in {"错误", "错", "false", "False", "否", "×"}:
            return False
        return value
    return value


def _before(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": item.get("type"),
        "stem": item.get("stem"),
        "options": item.get("options"),
        "answer": item.get("answer"),
        "analysis": item.get("analysis"),
        "reference_code": item.get("reference_code"),
        "knowledge_points": item.get("knowledge_points") or [],
    }


def _item_dict(q: QuestionBankQuestion) -> dict[str, Any]:
    return {
        "id": str(q.id),
        "order_no": q.order_no,
        "type": q.type,
        "stem": q.stem,
        "options": q.options,
        "answer": q.answer,
        "analysis": q.analysis,
        "reference_code": q.reference_code,
        "score": q.score,
        "media": q.media or [],
        "knowledge_points": q.knowledge_points or [],
        "source_excerpt": q.source_excerpt,
    }


def _call_json(db: Session, user: User, system: str, prompt: str) -> tuple[dict[str, Any], str]:
    with use_teacher_llm(db, user.id, "assignment") as resolved:
        raw = llm.invoke_text(system, prompt, temperature=0.0, timeout=90)
        model = resolved.model
    return _extract_json(raw), model


def latest_review(db: Session, question_id: uuid.UUID, kind: str) -> QuestionBankAiReview | None:
    return db.scalar(
        select(QuestionBankAiReview)
        .where(QuestionBankAiReview.question_id == question_id, QuestionBankAiReview.kind == kind)
        .order_by(QuestionBankAiReview.created_at.desc())
    )


def validate_question(
    db: Session,
    user: User,
    question: QuestionBankQuestion,
    *,
    apply: bool,
    force: bool = False,
) -> tuple[QuestionBankAiReview, bool]:
    """AI 校验单题。apply=True 且置信度达阈值时直接落库修复。

    force=True 会忽略已有「suggested」校验记录，重新调用模型，
    用于「AI 一键修复」此类被用户主动触发的重跑；已「applied」且
    内容哈希未变的记录始终命中缓存，避免重复计费。
    """
    item = _item_dict(question)
    content_hash = question_content_hash(item)
    if not force:
        cached = db.scalar(
            select(QuestionBankAiReview).where(
                QuestionBankAiReview.question_id == question.id,
                QuestionBankAiReview.kind == "validate",
                QuestionBankAiReview.content_hash == content_hash,
                QuestionBankAiReview.status.in_(["applied", "suggested"]),
            )
        )
        if cached:
            return cached, False

    prompt = (
        "你是少儿编程考级题库审校专家。请检查题目是否与原始试卷一致、答案是否正确、解析是否充分。"
        "source_excerpt 是该题在原试卷中的原文，可据此补全缺失的答案/选项/解析/参考代码。"
        "只输出严格 JSON："
        '{"aligned":true/false,"confidence":0到1,'
        '"issues":[{"code":"answer_error|analysis_missing|options_incomplete|type_error|stem_mismatch|other","message":"..."}],'
        '"fixes":{"type":"可选题型","answer":"可选答案（单选A/B/C；多选A,C；判断正确/错误）",'
        '"options":["可选完整选项"],"analysis":"可选解析","reference_code":"编程题可选参考代码"},'
        '"reasons":["判定依据"]}。没有需要修改的字段就不要放在 fixes 中。题目数据：'
        + json.dumps(
            {
                "order_no": item["order_no"],
                "type": item["type"],
                "stem": item["stem"][:1600],
                "options": item["options"],
                "answer_display": _answer_text(item),
                "analysis": (item["analysis"] or "")[:1200],
                "reference_code": (item["reference_code"] or "")[:1200],
                "source_excerpt": (item.get("source_excerpt") or "")[:1500],
            },
            ensure_ascii=False,
        )
    )
    before = _before(item)
    try:
        data, model = _call_json(db, user, "你是严谨的题库审校助手，只输出 JSON。", prompt)
    except LLMConfigError:
        raise
    except Exception as exc:
        review = QuestionBankAiReview(
            question_id=question.id,
            kind="validate",
            content_hash=content_hash,
            status="error",
            before=before,
            reasons=[friendly_llm_error(exc)],
            created_by=user.id,
        )
        db.add(review)
        db.commit()
        raise

    FIELD_LABELS = {
        "type": "题型",
        "options": "选项",
        "answer": "答案",
        "analysis": "解析",
        "reference_code": "参考代码",
    }

    fixes = data.get("fixes") if isinstance(data.get("fixes"), dict) else {}
    after = dict(before)
    if fixes.get("type") in VALID_TYPES:
        after["type"] = fixes["type"]
    if isinstance(fixes.get("options"), list) and fixes["options"]:
        after["options"] = [str(x) for x in fixes["options"]]
    if fixes.get("answer") is not None:
        after["answer"] = _answer_from_text(fixes["answer"], str(after.get("type")), after.get("options"))
    if isinstance(fixes.get("analysis"), str) and fixes["analysis"].strip():
        after["analysis"] = fixes["analysis"].strip()
    if isinstance(fixes.get("reference_code"), str) and fixes["reference_code"].strip():
        after["reference_code"] = fixes["reference_code"].strip()

    def _blank(val: Any) -> bool:
        if val is None:
            return True
        if isinstance(val, str):
            return not val.strip()
        if isinstance(val, (list, dict)):
            return not val
        return False

    def _answer_invalid(qtype: str | None, ans: Any, opts: Any) -> bool:
        if qtype == "single_choice":
            return not isinstance(ans, int) or not isinstance(opts, list) or not (0 <= ans < len(opts))
        if qtype == "multiple_choice":
            if not isinstance(ans, list) or not isinstance(opts, list):
                return True
            return any(not isinstance(x, int) or x < 0 or x >= len(opts) for x in ans)
        if qtype == "judgement":
            return not isinstance(ans, bool)
        return _blank(ans)

    confidence = float(data.get("confidence") or 0)
    issues = data.get("issues") if isinstance(data.get("issues"), list) else []
    issue_codes = {str(i.get("code")) for i in issues if isinstance(i, dict)}

    # 缺失/无效字段（填补）只需中等置信；覆盖已有内容（修正）需高置信，避免误改原有正确内容
    structural = {"options_incomplete", "answer_error", "stem_mismatch", "type_error"}
    fill_threshold = 0.3 if issue_codes & structural else 0.45
    override_threshold = 0.85
    qtype_after = str(after.get("type") or before.get("type") or "")
    apply_fields: list[str] = []
    for field in ("type", "options", "answer", "analysis", "reference_code"):
        old_val = before.get(field)
        new_val = after.get(field)
        if new_val == old_val:
            continue
        if field == "type":
            missing = old_val not in VALID_TYPES
        elif field == "options":
            missing = not isinstance(old_val, list) or any(not str(o or "").strip() for o in old_val)
        elif field == "answer":
            missing = _answer_invalid(qtype_after, old_val, after.get("options"))
        else:
            missing = _blank(old_val)
        if confidence >= (fill_threshold if missing else override_threshold):
            apply_fields.append(field)

    auto_apply = bool(
        apply
        and apply_fields
        and question.status in (BankQuestionStatus.DRAFT.value, BankQuestionStatus.REVIEWED.value)
    )
    if auto_apply:
        if after.get("type") in VALID_TYPES:
            question.type = after["type"]
        if after.get("options") is not None:
            question.options = after["options"]
        if after.get("answer") is not None:
            question.answer = after["answer"]
        if after.get("analysis") is not None:
            question.analysis = after["analysis"]
        if after.get("reference_code") is not None:
            question.reference_code = after["reference_code"]
        names = [FIELD_LABELS[f] for f in apply_fields]
        question.review_note = (
            "AI 校准已应用：" + "、".join(names) + f"（置信度 {confidence:.2f}），请人工复核"
        )

    review = QuestionBankAiReview(
        question_id=question.id,
        kind="validate",
        content_hash=content_hash,
        status="applied" if auto_apply else "suggested",
        model=model,
        confidence=confidence,
        issues=issues,
        before=before,
        after=after,
        reasons=[str(x) for x in (data.get("reasons") or [])],
        created_by=user.id,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review, auto_apply


def revert_question(db: Session, question: QuestionBankQuestion) -> QuestionBankQuestion:
    review = latest_review(db, question.id, "validate")
    if not review or review.status != "applied" or not review.before:
        raise ValueError("没有可撤销的 AI 校准")
    before = review.before
    if before.get("type"):
        question.type = before["type"]
    question.options = before.get("options")
    question.answer = before.get("answer")
    question.analysis = before.get("analysis")
    question.reference_code = before.get("reference_code")
    question.review_note = "已撤销 AI 校准，请人工复核"
    review.status = "reverted"
    db.commit()
    return question


def _kp_candidates(db: Session, bank_set: QuestionBankSet) -> list[str]:
    taxonomy = list(
        db.scalars(
            select(QuestionBankKpTaxonomy)
            .where(
                QuestionBankKpTaxonomy.status == "active",
                QuestionBankKpTaxonomy.subject == (bank_set.subject or ""),
            )
            .order_by(QuestionBankKpTaxonomy.sort_order)
            .limit(60)
        ).all()
    )
    if taxonomy:
        return [t.name for t in taxonomy]
    rows = db.scalars(
        select(QuestionBankQuestion.knowledge_points).where(
            QuestionBankQuestion.bank_set_id == bank_set.id,
            QuestionBankQuestion.knowledge_points.is_not(None),
        )
    ).all()
    seen: list[str] = []
    for tags in rows:
        for tag in tags or []:
            if tag and tag not in seen:
                seen.append(tag)
    if seen:
        return seen[:60]
    # 全局已有标签兜底，让模型优先复用已有粒度
    others = db.scalars(
        select(QuestionBankQuestion.knowledge_points)
        .where(QuestionBankQuestion.knowledge_points.is_not(None))
        .limit(200)
    ).all()
    for tags in others:
        for tag in tags or []:
            if tag and tag not in seen:
                seen.append(tag)
    return seen[:60]


def _ensure_taxonomy(db: Session, bank_set: QuestionBankSet, names: list[str], *, source_status: str) -> None:
    for name in names:
        code = name.strip()[:80]
        if not code:
            continue
        exists = db.scalar(
            select(QuestionBankKpTaxonomy).where(
                QuestionBankKpTaxonomy.subject == (bank_set.subject or ""),
                QuestionBankKpTaxonomy.level == bank_set.level,
                QuestionBankKpTaxonomy.code == code,
            )
        )
        if exists:
            continue
        db.add(
            QuestionBankKpTaxonomy(
                subject=bank_set.subject or "未分类",
                level=bank_set.level,
                code=code,
                name=name.strip(),
                status=source_status,
            )
        )


def tag_question(
    db: Session,
    user: User,
    bank_set: QuestionBankSet,
    question: QuestionBankQuestion,
    candidates: list[str],
) -> tuple[list[str], str | None]:
    item = _item_dict(question)
    content_hash = question_content_hash(item)
    prompt = (
        "你是少儿编程知识点标注助手。只能从候选知识点中选择 1-3 个最贴切的；"
        "若候选都不合适，可提出 1 个新知识点，但需保持与考纲粒度一致。只输出 JSON："
        '{"knowledge_points":["..."],"confidence":0到1}。候选：'
        + json.dumps(candidates, ensure_ascii=False)
        + "\n题目："
        + json.dumps(
            {"type": item["type"], "stem": item["stem"][:1200], "analysis": (item["analysis"] or "")[:600]},
            ensure_ascii=False,
        )
    )
    data, model = _call_json(db, user, "你是严谨的知识点标注助手，只输出 JSON。", prompt)
    tags = [str(x).strip() for x in (data.get("knowledge_points") or []) if str(x).strip()][:3]
    if not tags:
        return [], model
    before = _before(item)
    after = dict(before)
    after["knowledge_points"] = tags
    question.knowledge_points = tags
    _ensure_taxonomy(db, bank_set, tags, source_status="active" if all(t in candidates for t in tags) else "candidate")
    review = QuestionBankAiReview(
        question_id=question.id,
        kind="tag",
        content_hash=content_hash,
        status="applied",
        model=model,
        confidence=float(data.get("confidence") or 0),
        before=before,
        after=after,
        reasons=["AI 知识点打标"],
        created_by=user.id,
    )
    db.add(review)
    return tags, model


def stats_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached_comment(
    db: Session, user_id: uuid.UUID, student_id: uuid.UUID | None, digest: str
) -> PracticeAbilityReport | None:
    query = select(PracticeAbilityReport).where(
        PracticeAbilityReport.user_id == user_id,
        PracticeAbilityReport.stats_hash == digest,
    )
    if student_id:
        query = query.where(PracticeAbilityReport.student_id == student_id)
    else:
        query = query.where(PracticeAbilityReport.student_id.is_(None))
    return db.scalar(query.order_by(PracticeAbilityReport.created_at.desc()))


def ability_comment(
    db: Session, user: User, student_id: uuid.UUID | None, stats: dict[str, Any]
) -> tuple[str, str | None, bool]:
    digest = stats_hash(
        {
            "submitted": stats.get("submitted"),
            "correct_rate": stats.get("correct_rate"),
            "knowledge_stats": stats.get("knowledge_stats"),
            "weak_points": stats.get("weak_points"),
        }
    )
    cached = get_cached_comment(db, user.id, student_id, digest)
    if cached:
        return cached.content, cached.model, True

    if not stats.get("submitted"):
        return "还没有已完成的练习或考试。先完成一套练习，系统会结合错题知识点生成针对性的下一步建议。", None, False

    prompt = (
        "你是少儿编程学习规划师。基于下面的练习数据，用中文写 3-5 条简短建议（每条一行，以“-”开头），"
        "包含优势、薄弱知识点和下一步可执行练习。不要编造数据。学习数据："
        + json.dumps(
            {
                "submitted": stats.get("submitted"),
                "correct_rate": stats.get("correct_rate"),
                "avg_score_rate": stats.get("avg_score_rate"),
                "type_stats": stats.get("type_stats"),
                "knowledge_stats": stats.get("knowledge_stats"),
                "weak_points": stats.get("weak_points"),
            },
            ensure_ascii=False,
        )[:4000]
    )
    model: str | None = None
    try:
        with use_teacher_llm(db, user.id, "assignment") as resolved:
            content = llm.invoke_text("你是严谨的学习规划助手。", prompt, temperature=0.4, timeout=90).strip()
            model = resolved.model
    except Exception:
        content = _fallback_comment(stats)
    report = PracticeAbilityReport(
        user_id=user.id,
        student_id=student_id,
        stats_hash=digest,
        content=content,
        model=model,
    )
    db.add(report)
    db.commit()
    return content, model, False


def _fallback_comment(stats: dict[str, Any]) -> str:
    lines = [
        f"- 已完成 {stats.get('submitted', 0)} 次练习，整体正确率约 {round((stats.get('correct_rate') or 0) * 100)}%。"
    ]
    weak = stats.get("weak_points") or []
    if weak:
        lines.append("- 优先复习：" + "、".join(item.get("name", "") for item in weak[:3]) + "。")
    knowledge = stats.get("knowledge_stats") or []
    if knowledge:
        lowest = min(knowledge, key=lambda row: row.get("correct_rate", 0))
        lines.append(f"- 「{lowest.get('name')}」掌握度较低，建议先做 5-10 道同类题并逐题看解析。")
    lines.append("- 保持每次练习后回看错题解析，再间隔 2-3 天重做一次。")
    return "\n".join(lines)
