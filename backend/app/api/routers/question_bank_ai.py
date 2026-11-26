"""题库 AI 校准、知识点打标、结构化校验与能力评语 API。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routers.question_bank import _require_qb_permission
from app.api.routers.question_bank_practice import _collect_learning_stats, _resolve_owner
from app.core.database import get_db
from app.models.question_bank import (
    BankQuestionStatus,
    QuestionBankKpTaxonomy,
    QuestionBankQuestion,
    QuestionBankSet,
)
from app.models.user import User
from app.services import question_bank_ai
from app.services.llm import LLMConfigError, friendly_llm_error
from app.services.llm_context import require_llm
from app.services.question_bank_validation import validate_questions

router = APIRouter(prefix="/question-bank", tags=["question-bank-ai"])


def _q_out(q: QuestionBankQuestion) -> dict[str, Any]:
    return {
        "id": str(q.id),
        "order_no": q.order_no,
        "type": q.type,
        "stem": q.stem,
        "options": q.options,
        "answer": q.answer,
        "analysis": q.analysis,
        "difficulty": q.difficulty,
        "score": q.score,
        "language": q.language,
        "reference_code": q.reference_code,
        "test_cases": q.test_cases,
        "media": q.media,
        "knowledge_points": q.knowledge_points,
        "source_excerpt": q.source_excerpt,
        "status": q.status,
        "review_note": q.review_note,
    }


def _review_out(review, *, applied: bool = False, cached: bool = False) -> dict[str, Any]:
    return {
        "id": str(review.id),
        "question_id": str(review.question_id),
        "kind": review.kind,
        "status": review.status,
        "model": review.model,
        "confidence": review.confidence,
        "issues": review.issues,
        "before": review.before,
        "after": review.after,
        "reasons": review.reasons,
        "applied": applied,
        "cached": cached,
    }


class AiValidateIn(BaseModel):
    apply: bool = True


class AiValidateSetIn(BaseModel):
    question_ids: list[uuid.UUID] | None = None
    apply: bool = True


class AiTagIn(BaseModel):
    question_ids: list[uuid.UUID] | None = None


class AbilityCommentIn(BaseModel):
    student_id: uuid.UUID | None = None
    days: int = Field(default=30, ge=1, le=365)


class KpTaxonomyIn(BaseModel):
    subject: str
    level: str | None = None
    code: str
    name: str
    parent: str | None = None
    sort_order: int = 0
    status: str = "active"


@router.post("/questions/{question_id}/ai-validate")
def ai_validate_question(
    question_id: uuid.UUID,
    payload: AiValidateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_qb_permission(db, current_user, "question_bank_review")
    question = db.get(QuestionBankQuestion, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")
    try:
        review, applied = question_bank_ai.validate_question(db, current_user, question, apply=payload.apply)
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=friendly_llm_error(exc)) from exc
    return {"review": _review_out(review, applied=applied), "question": _q_out(question), "applied": applied}


@router.post("/questions/{question_id}/ai-validate/revert")
def ai_revert_question(
    question_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_qb_permission(db, current_user, "question_bank_review")
    question = db.get(QuestionBankQuestion, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")
    try:
        question_bank_ai.revert_question(db, question)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _q_out(question)


@router.post("/sets/{set_id}/ai-validate")
def ai_validate_set(
    set_id: uuid.UUID,
    payload: AiValidateSetIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_qb_permission(db, current_user, "question_bank_review")
    bank_set = db.get(QuestionBankSet, set_id)
    if not bank_set:
        raise HTTPException(status_code=404, detail="套卷不存在")
    # 前置解析「AI 习题」模块模型：未配置时立刻 503，避免批量跑到一半才中断
    try:
        require_llm(db, current_user.id, "assignment")
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    query = select(QuestionBankQuestion).where(QuestionBankQuestion.bank_set_id == set_id)
    if payload.question_ids:
        query = query.where(QuestionBankQuestion.id.in_(payload.question_ids))
    else:
        query = query.where(QuestionBankQuestion.status == BankQuestionStatus.DRAFT.value)
    questions = list(db.scalars(query.order_by(QuestionBankQuestion.order_no).limit(20)).all())
    items: list[dict[str, Any]] = []
    applied = 0
    failed = 0
    for question in questions:
        try:
            review, did_apply = question_bank_ai.validate_question(db, current_user, question, apply=payload.apply)
            applied += 1 if did_apply else 0
            items.append({"question_id": str(question.id), "review": _review_out(review, applied=did_apply)})
        except LLMConfigError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            failed += 1
            items.append({"question_id": str(question.id), "error": friendly_llm_error(exc)})
    return {"processed": len(questions), "applied": applied, "failed": failed, "items": items}


@router.get("/sets/{set_id}/validation")
def validate_set(
    set_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_qb_permission(db, current_user, "question_bank_review")
    questions = list(
        db.scalars(
            select(QuestionBankQuestion)
            .where(QuestionBankQuestion.bank_set_id == set_id)
            .order_by(QuestionBankQuestion.order_no)
        ).all()
    )
    issues = validate_questions([_q_out(q) for q in questions])
    return {"issues": issues, "total": len(questions)}


@router.post("/sets/{set_id}/ai-tag")
def ai_tag_set(
    set_id: uuid.UUID,
    payload: AiTagIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_qb_permission(db, current_user, "question_bank_review")
    bank_set = db.get(QuestionBankSet, set_id)
    if not bank_set:
        raise HTTPException(status_code=404, detail="套卷不存在")
    # 前置解析「AI 习题」模块模型：未配置时立刻 503，避免批量打到一半才中断
    try:
        require_llm(db, current_user.id, "assignment")
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    query = select(QuestionBankQuestion).where(QuestionBankQuestion.bank_set_id == set_id)
    if payload.question_ids:
        query = query.where(QuestionBankQuestion.id.in_(payload.question_ids))
    rows = list(db.scalars(query.order_by(QuestionBankQuestion.order_no)).all())
    questions = [q for q in rows if payload.question_ids or not q.knowledge_points][:10]
    candidates = question_bank_ai._kp_candidates(db, bank_set)
    items: list[dict[str, Any]] = []
    tagged = skipped = failed = 0
    for question in questions:
        if question.knowledge_points and not payload.question_ids:
            skipped += 1
            continue
        try:
            tags, _model = question_bank_ai.tag_question(db, current_user, bank_set, question, candidates)
            tagged += 1 if tags else 0
            skipped += 0 if tags else 1
            items.append({"question_id": str(question.id), "knowledge_points": tags})
        except LLMConfigError as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception:
            db.rollback()
            failed += 1
            items.append({"question_id": str(question.id), "knowledge_points": []})
    db.commit()
    return {
        "tagged": tagged,
        "skipped": skipped,
        "failed": failed,
        "items": items,
        "remaining": max(0, len(questions) - len(items)),
    }


@router.get("/kp-taxonomy")
def list_kp_taxonomy(
    subject: str | None = None,
    level: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = select(QuestionBankKpTaxonomy).order_by(QuestionBankKpTaxonomy.sort_order, QuestionBankKpTaxonomy.name)
    if subject:
        query = query.where(QuestionBankKpTaxonomy.subject == subject)
    if level:
        query = query.where(QuestionBankKpTaxonomy.level == level)
    rows = list(db.scalars(query.limit(500)).all())
    return {
        "items": [
            {
                "id": str(row.id),
                "subject": row.subject,
                "level": row.level,
                "code": row.code,
                "name": row.name,
                "parent": row.parent,
                "sort_order": row.sort_order,
                "status": row.status,
            }
            for row in rows
        ]
    }


@router.post("/kp-taxonomy", status_code=201)
def create_kp_taxonomy(
    payload: KpTaxonomyIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_qb_permission(db, current_user, "question_bank_review")
    existing = db.scalar(
        select(QuestionBankKpTaxonomy).where(
            QuestionBankKpTaxonomy.subject == payload.subject,
            QuestionBankKpTaxonomy.level == payload.level,
            QuestionBankKpTaxonomy.code == payload.code,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="该知识点已存在")
    row = QuestionBankKpTaxonomy(**payload.model_dump())
    db.add(row)
    db.commit()
    return {"id": str(row.id), "name": row.name, "code": row.code, "status": row.status}


@router.post("/ability-comment")
def ability_comment(
    payload: AbilityCommentIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stats = _collect_learning_stats(db, current_user, payload.student_id, payload.days)
    _, student_id = _resolve_owner(db, current_user, payload.student_id)
    content, model, cached = question_bank_ai.ability_comment(db, current_user, student_id, stats)
    return {"content": content, "model": model, "cached": cached, "stats": stats}
