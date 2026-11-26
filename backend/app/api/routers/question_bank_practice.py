"""题库 P2/P3：组卷蓝图、练习/模考 attempt、即时反馈与学习数据。"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.assignment import Assignment, Question
from app.models.enrollment import Student
from app.models.permission import check as permission_check
from app.models.question_bank import (
    AttemptStatus,
    BankQuestionStatus,
    BankSetStatus,
    PracticeAttempt,
    PracticeMode,
    QuestionBankBlueprint,
    QuestionBankQuestion,
    QuestionBankSet,
    QuestionBankUserMark,
)
from app.models.user import Role, User

router = APIRouter(prefix="/question-bank", tags=["question-bank-practice"])


def _require_qb_permission(db: Session, user: User, key: str) -> None:
    if user.role in {Role.ADMIN.value, Role.STAFF.value}:
        return
    if user.role != Role.TEACHER.value or not permission_check(db, user, key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无该题库操作权限，请联系管理员")


OBJECTIVE_TYPES = {"single_choice", "multiple_choice", "judgement", "code_fill"}
ALL_TYPES = OBJECTIVE_TYPES | {"programming"}
MAX_QUESTIONS = 100
ATTEMPT_KINDS = {"quick", "aggregate", "marked", "set_practice", "exam_set", "exam_random"}
EXAM_KINDS = {"exam_set", "exam_random"}


class BlueprintIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    subject: str | None = None
    level: str | None = None
    rules: dict[str, int] = Field(default_factory=dict)


class ComposeIn(BaseModel):
    rules: dict[str, int] = Field(default_factory=dict)
    set_id: uuid.UUID | None = None
    subject: str | None = None
    level: str | None = None
    institution: str | None = None
    exam_year: int | None = None
    exclude_ids: list[uuid.UUID] = Field(default_factory=list)


class AttemptStartIn(BaseModel):
    student_id: uuid.UUID | None = None
    mode: Literal["practice", "exam"] | None = None
    kind: str | None = None
    set_id: uuid.UUID | None = None
    blueprint_id: uuid.UUID | None = None
    rules: dict[str, int] | None = None
    subject: str | None = None
    level: str | None = None
    institution: str | None = None
    exam_year: int | None = None
    mark_kind: str | None = None


class AnswerIn(BaseModel):
    question_id: uuid.UUID
    answer: Any = None


class SelfEvalIn(BaseModel):
    question_id: uuid.UUID
    correct: bool


class ToAssignmentIn(BaseModel):
    title: str | None = None
    class_id: uuid.UUID | None = None
    question_ids: list[uuid.UUID] = Field(default_factory=list)


def _visible_student(db: Session, student_id: uuid.UUID, user: User) -> Student:
    stu = db.get(Student, student_id)
    if stu is None:
        raise HTTPException(status_code=404, detail="学员不存在")
    if user.role == Role.PARENT.value and stu.parent_user_id != user.id:
        raise HTTPException(status_code=403, detail="只能查看自己孩子的练习记录")
    if user.role == Role.STUDENT.value and stu.student_user_id != user.id:
        raise HTTPException(status_code=403, detail="只能查看自己的练习记录")
    return stu


def _resolve_owner(db: Session, user: User, student_id: uuid.UUID | None) -> tuple[uuid.UUID, uuid.UUID | None]:
    """教师/管理员以本人身份记录；家长/学员绑定可见学员。"""
    if user.role in {Role.ADMIN.value, Role.STAFF.value, Role.TEACHER.value}:
        return user.id, None
    if student_id is not None:
        stu = _visible_student(db, student_id, user)
        return user.id, stu.id
    if user.role == Role.STUDENT.value:
        stu = db.scalar(select(Student).where(Student.student_user_id == user.id))
    else:
        stu = db.scalar(select(Student).where(Student.parent_user_id == user.id).order_by(Student.created_at))
    if stu is None:
        raise HTTPException(status_code=422, detail="请先绑定学员后再开始练习")
    return user.id, stu.id


def _visible_attempt(db: Session, attempt: PracticeAttempt, user: User) -> None:
    if attempt.user_id and attempt.user_id == user.id:
        return
    if user.role in {Role.ADMIN.value, Role.STAFF.value}:
        return
    if attempt.student_id:
        _visible_student(db, attempt.student_id, user)
        return
    raise HTTPException(status_code=404, detail="练习记录不存在")


def _mark_wrong_question(
    db: Session,
    user: User,
    question_id: uuid.UUID,
    wrong: bool,
    student_id: uuid.UUID | None = None,
) -> None:
    user_id, scoped_student_id = _resolve_owner(db, user, student_id)
    mark = db.scalar(
        select(QuestionBankUserMark).where(
            QuestionBankUserMark.user_id == user_id,
            QuestionBankUserMark.student_id == scoped_student_id,
            QuestionBankUserMark.question_id == question_id,
            QuestionBankUserMark.kind == "wrong",
        )
    )
    if wrong and mark is None:
        db.add(
            QuestionBankUserMark(
                user_id=user_id,
                student_id=scoped_student_id,
                question_id=question_id,
                kind="wrong",
            )
        )
    elif not wrong and mark is not None:
        db.delete(mark)


def _normalize_rules(rules: dict[str, int]) -> dict[str, int]:
    clean: dict[str, int] = {}
    for key, value in (rules or {}).items():
        if key not in ALL_TYPES:
            raise HTTPException(status_code=422, detail=f"未知题型：{key}")
        count = int(value)
        if count <= 0:
            continue
        clean[key] = count
    if not clean:
        raise HTTPException(status_code=422, detail="组卷规则不能为空")
    if sum(clean.values()) > MAX_QUESTIONS:
        raise HTTPException(status_code=422, detail=f"单次组卷不能超过 {MAX_QUESTIONS} 题")
    return clean


def _compose_questions(
    db: Session,
    rules: dict[str, int],
    *,
    set_id: uuid.UUID | None = None,
    subject: str | None = None,
    level: str | None = None,
    institution: str | None = None,
    exam_year: int | None = None,
    exclude_ids: list[uuid.UUID] | None = None,
) -> list[QuestionBankQuestion]:
    rules = _normalize_rules(rules)
    exclude = set(exclude_ids or [])
    base = (
        select(QuestionBankQuestion)
        .join(QuestionBankSet)
        .where(
            QuestionBankQuestion.status == BankQuestionStatus.PUBLISHED.value,
            QuestionBankSet.status == BankSetStatus.PUBLISHED.value,
        )
    )
    if set_id:
        base = base.where(QuestionBankQuestion.bank_set_id == set_id)
    if subject:
        base = base.where(QuestionBankSet.subject == subject)
    if level:
        base = base.where(QuestionBankSet.level == level)
    if institution:
        base = base.where(QuestionBankSet.institution == institution)
    if exam_year:
        base = base.where(QuestionBankSet.exam_year == exam_year)
    if exclude:
        base = base.where(QuestionBankQuestion.id.notin_(exclude))
    picked: list[QuestionBankQuestion] = []
    gaps: dict[str, str] = {}
    for qtype, count in rules.items():
        rows = list(db.scalars(base.where(QuestionBankQuestion.type == qtype)).all())
        if len(rows) < count:
            gaps[qtype] = f"需要 {count} 题，库存仅 {len(rows)} 题"
            continue
        picked.extend(random.sample(rows, count))
    if gaps:
        raise HTTPException(status_code=409, detail={"message": "题库库存不足", "gaps": gaps})
    random.shuffle(picked)
    return picked


def _snapshot(q: QuestionBankQuestion) -> dict[str, Any]:
    return {
        "id": str(q.id),
        "order_no": q.order_no,
        "type": q.type,
        "stem": q.stem,
        "options": q.options,
        "analysis": q.analysis,
        "answer": q.answer,
        "reference_code": q.reference_code,
        "difficulty": q.difficulty,
        "score": q.score,
        "language": q.language,
        "media": q.media,
        "knowledge_points": q.knowledge_points,
    }


def _public_question(item: dict[str, Any], *, reveal: bool) -> dict[str, Any]:
    data = {
        "id": item.get("id"),
        "order_no": item.get("order_no"),
        "type": item.get("type"),
        "stem": item.get("stem"),
        "options": item.get("options"),
        "difficulty": item.get("difficulty"),
        "score": item.get("score"),
        "language": item.get("language"),
        "media": item.get("media"),
        "knowledge_points": item.get("knowledge_points"),
    }
    if reveal:
        data["analysis"] = item.get("analysis")
        data["answer"] = item.get("answer")
        data["reference_code"] = item.get("reference_code")
    return data


def _grade_one(item: dict[str, Any], answer: Any, self_correct: bool = False) -> tuple[bool | None, int]:
    qtype = item.get("type")
    correct = item.get("answer")
    max_score = int(item.get("score") or 0)
    if qtype == "programming":
        if self_correct:
            return True, max_score
        return None, 0
    if qtype == "single_choice":
        ok = answer is not None and correct is not None and int(answer) == int(correct)
    elif qtype == "multiple_choice":
        ok = isinstance(answer, list) and sorted(int(x) for x in answer) == sorted(int(x) for x in (correct or []))
    elif qtype == "judgement":
        ok = answer is not None and bool(answer) == bool(correct)
    else:
        ok = isinstance(answer, str) and isinstance(correct, str) and answer.strip() == correct.strip()
    return ok, max_score if ok else 0


def _evaluate(attempt: PracticeAttempt) -> dict[str, Any]:
    answers = attempt.answers or {}
    items: list[dict[str, Any]] = []
    type_stats: dict[str, dict[str, int]] = {}
    score = 0
    correct_count = 0
    for item in attempt.question_snapshot or []:
        qid = str(item.get("id"))
        answer = answers.get(qid)
        self_correct = bool(answers.get(f"__self__:{qid}"))
        is_correct, got = _grade_one(item, answer, self_correct)
        max_score = int(item.get("score") or 0)
        score += got
        if is_correct:
            correct_count += 1
        stat = type_stats.setdefault(
            item.get("type") or "unknown", {"total": 0, "correct": 0, "score": 0, "max_score": 0}
        )
        stat["total"] += 1
        stat["correct"] += 1 if is_correct else 0
        stat["score"] += got
        stat["max_score"] += max_score
        items.append(
            {
                "id": qid,
                "order_no": item.get("order_no"),
                "type": item.get("type"),
                "user_answer": answer,
                "correct_answer": item.get("answer"),
                "analysis": item.get("analysis"),
                "reference_code": item.get("reference_code"),
                "is_correct": is_correct,
                "score": got,
                "max_score": max_score,
                "knowledge_points": item.get("knowledge_points") or [],
            }
        )
    total_score = sum(int(i.get("score") or 0) for i in (attempt.question_snapshot or []))
    normalized = round(score / total_score * 100) if total_score else 0
    for stat in type_stats.values():
        stat["correct_rate"] = round(stat["correct"] / stat["total"], 4) if stat["total"] else 0
    return {
        "items": items,
        "score": score,
        "total_score": total_score,
        "normalized_score": normalized,
        "rating": ("达标" if normalized >= 60 else "未达标") if attempt.mode == PracticeMode.EXAM.value else None,
        "correct_count": correct_count,
        "question_count": len(items),
        "type_stats": type_stats,
    }


def _attempt_out(attempt: PracticeAttempt, *, reveal: bool) -> dict[str, Any]:
    evaluated = attempt.status == AttemptStatus.EVALUATED.value
    answered_ids = set((attempt.question_results or {}).keys())
    questions = []
    for item in attempt.question_snapshot or []:
        item_reveal = bool(
            evaluated or reveal or (attempt.mode == PracticeMode.PRACTICE.value and str(item.get("id")) in answered_ids)
        )
        questions.append(_public_question(item, reveal=item_reveal))
    return {
        "id": str(attempt.id),
        "user_id": str(attempt.user_id) if attempt.user_id else None,
        "student_id": str(attempt.student_id) if attempt.student_id else None,
        "bank_set_id": str(attempt.bank_set_id) if attempt.bank_set_id else None,
        "mode": attempt.mode,
        "kind": attempt.kind or ("exam_random" if attempt.mode == PracticeMode.EXAM.value else "set_practice"),
        "paper_title": attempt.paper_title,
        "paper_meta": attempt.paper_meta,
        "status": attempt.status,
        "score": attempt.score,
        "total_score": attempt.total_score,
        "started_at": attempt.started_at,
        "submitted_at": attempt.submitted_at,
        "result": attempt.result if evaluated else None,
        "answers": attempt.answers or {},
        "question_results": attempt.question_results or {},
        "questions": questions,
    }


@router.get("/blueprints")
def list_blueprints(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_qb_permission(db, current_user, "question_bank_blueprint")
    rows = db.scalars(select(QuestionBankBlueprint).order_by(QuestionBankBlueprint.created_at.desc())).all()
    return [
        {
            "id": str(b.id),
            "name": b.name,
            "subject": b.subject,
            "level": b.level,
            "rules": b.rules,
            "created_at": b.created_at,
        }
        for b in rows
    ]


@router.post("/blueprints", status_code=status.HTTP_201_CREATED)
def create_blueprint(
    payload: BlueprintIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_qb_permission(db, user, "question_bank_blueprint")
    rules = _normalize_rules(payload.rules)
    bp = QuestionBankBlueprint(
        name=payload.name,
        subject=payload.subject,
        level=payload.level,
        rules=rules,
        created_by=user.id,
    )
    db.add(bp)
    db.commit()
    return {"id": str(bp.id), "name": bp.name, "subject": bp.subject, "level": bp.level, "rules": bp.rules}


@router.patch("/blueprints/{blueprint_id}")
def update_blueprint(
    blueprint_id: uuid.UUID,
    payload: BlueprintIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_qb_permission(db, current_user, "question_bank_blueprint")
    bp = db.get(QuestionBankBlueprint, blueprint_id)
    if not bp:
        raise HTTPException(status_code=404, detail="组卷规则不存在")
    bp.name = payload.name
    bp.subject = payload.subject
    bp.level = payload.level
    bp.rules = _normalize_rules(payload.rules)
    db.commit()
    return {"id": str(bp.id), "name": bp.name, "subject": bp.subject, "level": bp.level, "rules": bp.rules}


@router.delete("/blueprints/{blueprint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_blueprint(
    blueprint_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_qb_permission(db, current_user, "question_bank_blueprint")
    bp = db.get(QuestionBankBlueprint, blueprint_id)
    if not bp:
        raise HTTPException(status_code=404, detail="组卷规则不存在")
    db.delete(bp)
    db.commit()


@router.post("/compose")
def compose(
    payload: ComposeIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(Role.ADMIN, Role.STAFF, Role.TEACHER)),
):
    picked = _compose_questions(
        db,
        payload.rules,
        set_id=payload.set_id,
        subject=payload.subject,
        level=payload.level,
        institution=payload.institution,
        exam_year=payload.exam_year,
        exclude_ids=payload.exclude_ids,
    )
    return {"questions": [_public_question(_snapshot(q), reveal=True) for q in picked]}


@router.get("/compose/availability")
def compose_availability(
    subject: str | None = None,
    level: str | None = None,
    institution: str | None = None,
    exam_year: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """开考前预检：按题型返回已发布题库库存，前端据此提示题量缺口。"""
    query = (
        select(QuestionBankQuestion.type, func.count())
        .join(QuestionBankSet)
        .where(
            QuestionBankQuestion.status == BankQuestionStatus.PUBLISHED.value,
            QuestionBankSet.status == BankSetStatus.PUBLISHED.value,
        )
    )
    if subject:
        query = query.where(QuestionBankSet.subject == subject)
    if level:
        query = query.where(QuestionBankSet.level == level)
    if institution:
        query = query.where(QuestionBankSet.institution == institution)
    if exam_year:
        query = query.where(QuestionBankSet.exam_year == exam_year)
    query = query.group_by(QuestionBankQuestion.type)
    counts: dict[str, int] = {qtype: 0 for qtype in ALL_TYPES}
    for qtype, cnt in db.execute(query).all():
        counts[str(qtype)] = int(cnt)
    return counts


@router.post("/attempts", status_code=status.HTTP_201_CREATED)
def start_attempt(
    payload: AttemptStartIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kind = payload.kind or ("exam_random" if payload.mode == "exam" else "set_practice")
    if kind not in ATTEMPT_KINDS:
        raise HTTPException(status_code=422, detail=f"未知的练习类型：{kind}")
    mode = PracticeMode.EXAM.value if (kind in EXAM_KINDS or payload.mode == "exam") else PracticeMode.PRACTICE.value
    user_id, student_id = _resolve_owner(db, user, payload.student_id)
    bank_set_id: uuid.UUID | None = None
    title: str | None = None
    meta: dict[str, Any] = {"kind": kind}

    if kind in {"quick", "set_practice", "exam_set"}:
        if not payload.set_id:
            raise HTTPException(status_code=422, detail="套卷练习需要指定套卷")
        bank_set = db.scalar(
            select(QuestionBankSet)
            .options(selectinload(QuestionBankSet.questions))
            .where(QuestionBankSet.id == payload.set_id)
        )
        if not bank_set:
            raise HTTPException(status_code=404, detail="套卷不存在")
        if bank_set.status != BankSetStatus.PUBLISHED.value and user.role not in {Role.ADMIN.value, Role.STAFF.value}:
            raise HTTPException(status_code=404, detail="套卷不存在或未发布")
        allowed_status: set[str] = {BankQuestionStatus.PUBLISHED.value}
        if user.role in {Role.ADMIN.value, Role.STAFF.value}:
            allowed_status |= {BankQuestionStatus.DRAFT.value, BankQuestionStatus.REVIEWED.value}
        questions = [q for q in bank_set.questions if q.status in allowed_status]
        if not questions:
            raise HTTPException(status_code=409, detail="该套卷暂无可用题目")
        bank_set_id = bank_set.id
        title = bank_set.name
        meta.update(
            {
                "set_id": str(bank_set.id),
                "subject": bank_set.subject,
                "level": bank_set.level,
                "institution": bank_set.institution,
                "exam_month": bank_set.exam_month,
            }
        )
    elif kind == "marked":
        mark_kind = payload.mark_kind if payload.mark_kind in {"favorite", "wrong"} else "wrong"
        mark_query = select(QuestionBankUserMark).where(
            QuestionBankUserMark.user_id == user_id,
            QuestionBankUserMark.kind == mark_kind,
        )
        if student_id:
            mark_query = mark_query.where(QuestionBankUserMark.student_id == student_id)
        else:
            mark_query = mark_query.where(QuestionBankUserMark.student_id.is_(None))
        question_ids = [m.question_id for m in db.scalars(mark_query).all()]
        questions = (
            list(
                db.scalars(
                    select(QuestionBankQuestion)
                    .where(
                        QuestionBankQuestion.id.in_(question_ids),
                        QuestionBankQuestion.status == BankQuestionStatus.PUBLISHED.value,
                    )
                    .order_by(QuestionBankQuestion.order_no)
                ).all()
            )
            if question_ids
            else []
        )
        if not questions:
            raise HTTPException(status_code=409, detail="错题本还是空的" if mark_kind == "wrong" else "还没有收藏题目")
        title = "错题本" if mark_kind == "wrong" else "我的收藏"
        meta.update({"mark_kind": mark_kind})
    else:
        rules = payload.rules
        if payload.blueprint_id:
            bp = db.get(QuestionBankBlueprint, payload.blueprint_id)
            if not bp:
                raise HTTPException(status_code=404, detail="组卷规则不存在")
            rules = bp.rules
            payload.subject = payload.subject or bp.subject
            payload.level = payload.level or bp.level
        if not rules:
            raise HTTPException(status_code=422, detail="抽题练习需要组卷规则")
        questions = _compose_questions(
            db,
            rules,
            subject=payload.subject,
            level=payload.level,
            institution=payload.institution,
            exam_year=payload.exam_year,
        )
        title = "综合练习" if kind == "aggregate" else "模拟考试"
        meta.update(
            {
                "rules": rules,
                "subject": payload.subject,
                "level": payload.level,
                "institution": payload.institution,
                "exam_year": payload.exam_year,
            }
        )

    snapshot = [_snapshot(q) for q in questions]
    meta["question_count"] = len(snapshot)
    meta["total_score"] = sum(int(i.get("score") or 0) for i in snapshot)
    attempt = PracticeAttempt(
        user_id=user_id,
        student_id=student_id,
        bank_set_id=bank_set_id,
        mode=mode,
        kind=kind,
        paper_title=title,
        paper_meta=meta,
        status=AttemptStatus.IN_PROGRESS,
        question_snapshot=snapshot,
        answers={},
        question_results={},
    )
    db.add(attempt)
    db.commit()
    return _attempt_out(attempt, reveal=False)


def _get_attempt(db: Session, attempt_id: uuid.UUID, user: User) -> PracticeAttempt:
    attempt = db.get(PracticeAttempt, attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="练习记录不存在")
    _visible_attempt(db, attempt, user)
    return attempt


@router.get("/attempts")
def list_attempts(
    student_id: uuid.UUID | None = None,
    kind: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(PracticeAttempt)
    if user.role in {Role.ADMIN.value, Role.STAFF.value, Role.TEACHER.value}:
        query = query.where(PracticeAttempt.user_id == user.id)
    else:
        _, student_id = _resolve_owner(db, user, student_id)
        query = query.where(PracticeAttempt.student_id == student_id)
    if kind:
        query = query.where(PracticeAttempt.kind == kind)
    if status_filter:
        query = query.where(PracticeAttempt.status == status_filter)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(PracticeAttempt.started_at.desc()).limit(limit).offset(offset)).all()
    items = []
    for a in rows:
        result = a.result or {}
        items.append(
            {
                "id": str(a.id),
                "mode": a.mode,
                "kind": a.kind,
                "paper_title": a.paper_title,
                "status": a.status,
                "score": a.score,
                "total_score": a.total_score,
                "normalized_score": result.get("normalized_score"),
                "rating": result.get("rating"),
                "correct_count": result.get("correct_count"),
                "question_count": result.get("question_count"),
                "correct_rate": (
                    round((result.get("correct_count") or 0) / result["question_count"], 4)
                    if result.get("question_count")
                    else None
                ),
                "started_at": a.started_at,
                "submitted_at": a.submitted_at,
            }
        )
    return {"items": items, "total": total}


@router.get("/attempts/trend")
def attempt_trend(
    days: int = Query(default=56, ge=7, le=365),
    student_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按周聚合已完成作答的平均得分率，用于能力趋势图。"""
    since = datetime.now(UTC) - timedelta(days=days)
    query = select(PracticeAttempt).where(
        PracticeAttempt.status == AttemptStatus.EVALUATED.value,
        PracticeAttempt.started_at >= since,
    )
    if student_id is not None:
        _visible_student(db, student_id, user)
        query = query.where(PracticeAttempt.student_id == student_id)
    else:
        query = query.where(PracticeAttempt.user_id == user.id)
    rows = list(db.scalars(query).all())
    buckets: dict[str, list[float]] = {}
    for row in rows:
        if row.started_at is None:
            continue
        week_start = (row.started_at - timedelta(days=row.started_at.weekday())).date().isoformat()
        score: float | None = None
        if isinstance(row.result, dict):
            value = row.result.get("normalized_score")
            if value is not None:
                score = float(value)
        if score is None and row.mode != PracticeMode.EXAM.value:
            total = int(row.total_score or 0)
            if total > 0:
                score = float(row.score or 0) / total * 100
        if score is None:
            continue
        buckets.setdefault(week_start, []).append(score)
    weeks = [
        {"week_start": key, "avg_score": round(sum(values) / len(values)), "attempts": len(values)}
        for key, values in sorted(buckets.items())
    ]
    return {"weeks": weeks}


@router.get("/attempts/{attempt_id}")
def get_attempt(
    attempt_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    attempt = _get_attempt(db, attempt_id, user)
    return _attempt_out(attempt, reveal=False)


@router.post("/attempts/{attempt_id}/answers")
def save_answer(
    attempt_id: uuid.UUID,
    payload: AnswerIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    attempt = _get_attempt(db, attempt_id, user)
    if attempt.status != AttemptStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=409, detail="本次练习已交卷")
    qid = str(payload.question_id)
    item = next((i for i in (attempt.question_snapshot or []) if str(i.get("id")) == qid), None)
    if not item:
        raise HTTPException(status_code=404, detail="本次练习不包含该题")
    answers = dict(attempt.answers or {})
    results = dict(attempt.question_results or {})
    if payload.answer is None:
        answers.pop(qid, None)
        results.pop(qid, None)
        attempt.answers = answers
        attempt.question_results = results
        # 清空作答同步移除该题的错题标记，避免错题本残留已撤销的错题
        _mark_wrong_question(db, user, payload.question_id, False, attempt.student_id)
        db.commit()
        return {"saved": True, "cleared": True}

    answers[qid] = payload.answer
    attempt.answers = answers
    if attempt.mode == PracticeMode.PRACTICE.value:
        is_correct, got = _grade_one(item, payload.answer, bool(answers.get(f"__self__:{qid}")))
        results[qid] = {
            "is_correct": is_correct,
            "score": got,
            "max_score": int(item.get("score") or 0),
        }
        attempt.question_results = results
        if is_correct is not None:
            _mark_wrong_question(db, user, payload.question_id, is_correct is False, attempt.student_id)
        db.commit()
        return {
            "saved": True,
            "is_correct": is_correct,
            "correct_answer": item.get("answer"),
            "analysis": item.get("analysis"),
            "reference_code": item.get("reference_code"),
            "score": got,
            "max_score": int(item.get("score") or 0),
        }
    db.commit()
    return {"saved": True}


@router.post("/attempts/{attempt_id}/self-evaluate")
def self_evaluate(
    attempt_id: uuid.UUID,
    payload: SelfEvalIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    attempt = _get_attempt(db, attempt_id, user)
    if attempt.status != AttemptStatus.IN_PROGRESS.value:
        raise HTTPException(status_code=409, detail="本次练习已交卷")
    item = next((i for i in (attempt.question_snapshot or []) if str(i.get("id")) == str(payload.question_id)), None)
    if not item or item.get("type") != "programming":
        raise HTTPException(status_code=404, detail="仅编程题支持自评")
    answers = dict(attempt.answers or {})
    answers[f"__self__:{payload.question_id}"] = bool(payload.correct)
    attempt.answers = answers
    if attempt.mode == PracticeMode.PRACTICE.value:
        results = dict(attempt.question_results or {})
        results[str(payload.question_id)] = {
            "is_correct": bool(payload.correct),
            "score": int(item.get("score") or 0) if payload.correct else 0,
            "max_score": int(item.get("score") or 0),
        }
        attempt.question_results = results
    _mark_wrong_question(db, user, payload.question_id, not payload.correct, attempt.student_id)
    db.commit()
    return {"saved": True, "self_correct": bool(payload.correct)}


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(
    attempt_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    attempt = _get_attempt(db, attempt_id, user)
    if attempt.status == AttemptStatus.EVALUATED.value:
        return _attempt_out(attempt, reveal=True)
    result = _evaluate(attempt)
    attempt.result = result
    attempt.score = result["score"]
    attempt.total_score = result["total_score"]
    attempt.status = AttemptStatus.EVALUATED
    attempt.submitted_at = datetime.now(UTC)
    # 交卷后把逐题判定固化，记录详情/回看直接使用，无需再请求判题
    attempt.question_results = {
        str(item["id"]): {
            "is_correct": item["is_correct"],
            "score": item["score"],
            "max_score": item["max_score"],
        }
        for item in result["items"]
    }
    db.commit()
    return _attempt_out(attempt, reveal=True)


@router.post("/attempts/{attempt_id}/close")
def close_attempt(
    attempt_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """结束练习会话：保留已作答判定的同时生成总结，便于做题记录回看。"""
    attempt = _get_attempt(db, attempt_id, user)
    if attempt.status == AttemptStatus.EVALUATED.value:
        return _attempt_out(attempt, reveal=True)
    result = _evaluate(attempt)
    attempt.result = result
    attempt.score = result["score"]
    attempt.total_score = result["total_score"]
    attempt.status = AttemptStatus.EVALUATED
    attempt.submitted_at = datetime.now(UTC)
    attempt.question_results = {
        str(item["id"]): {
            "is_correct": item["is_correct"],
            "score": item["score"],
            "max_score": item["max_score"],
        }
        for item in result["items"]
    }
    db.commit()
    return _attempt_out(attempt, reveal=True)


@router.get("/attempts/{attempt_id}/result")
def attempt_result(
    attempt_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    attempt = _get_attempt(db, attempt_id, user)
    if attempt.status != AttemptStatus.EVALUATED.value:
        raise HTTPException(status_code=409, detail="尚未交卷")
    return _attempt_out(attempt, reveal=True)


def _collect_learning_stats(db: Session, user: User, student_id: uuid.UUID | None, days: int) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    query = select(PracticeAttempt).where(PracticeAttempt.started_at >= since)
    if user.role in {Role.ADMIN.value, Role.STAFF.value, Role.TEACHER.value}:
        query = query.where(PracticeAttempt.user_id == user.id)
    else:
        _, scoped_student_id = _resolve_owner(db, user, student_id)
        query = query.where(PracticeAttempt.student_id == scoped_student_id)
    rows = list(db.scalars(query.order_by(PracticeAttempt.started_at.desc())).all())
    submitted = [a for a in rows if a.status == AttemptStatus.EVALUATED.value]
    total_questions = sum((a.result or {}).get("question_count", 0) for a in submitted)
    correct = sum((a.result or {}).get("correct_count", 0) for a in submitted)
    type_stats: dict[str, dict[str, int]] = {}
    knowledge_stats: dict[str, dict[str, int]] = {}
    weak_points: dict[str, int] = {}
    for a in submitted:
        for item in (a.result or {}).get("items", []):
            st = type_stats.setdefault(item.get("type") or "unknown", {"total": 0, "correct": 0})
            st["total"] += 1
            st["correct"] += 1 if item.get("is_correct") else 0
            for kp in item.get("knowledge_points") or []:
                ks = knowledge_stats.setdefault(kp, {"total": 0, "correct": 0})
                ks["total"] += 1
                ks["correct"] += 1 if item.get("is_correct") else 0
            if item.get("is_correct") is False:
                for kp in item.get("knowledge_points") or []:
                    weak_points[kp] = weak_points.get(kp, 0) + 1
    by_day = {a.started_at.date().isoformat() for a in rows if a.started_at}
    streak = 0
    cursor = date.today()
    while cursor.isoformat() in by_day:
        streak += 1
        cursor -= timedelta(days=1)
    rates = [(a.score or 0) / a.total_score for a in submitted if a.total_score]
    knowledge_rows = [
        {
            "name": name,
            **stat,
            "correct_rate": round(stat["correct"] / stat["total"], 4) if stat["total"] else 0,
        }
        for name, stat in knowledge_stats.items()
    ]
    knowledge_rows.sort(key=lambda row: (row["total"], row["correct_rate"]), reverse=True)
    return {
        "attempts": len(rows),
        "submitted": len(submitted),
        "total_questions": total_questions,
        "correct_rate": round(correct / total_questions, 4) if total_questions else 0,
        "avg_score_rate": round(sum(rates) / len(rates), 4) if rates else 0,
        "best_score_rate": round(max(rates), 4) if rates else 0,
        "type_stats": {
            k: {**v, "correct_rate": round(v["correct"] / v["total"], 4) if v["total"] else 0}
            for k, v in type_stats.items()
        },
        "knowledge_stats": knowledge_rows,
        "radar": knowledge_rows[:8],
        "weak_points": sorted(
            [{"name": k, "wrong": v} for k, v in weak_points.items()],
            key=lambda x: x["wrong"],
            reverse=True,
        )[:5],
        "streak_days": streak,
        "recent": [
            {
                "id": str(a.id),
                "mode": a.mode,
                "kind": a.kind,
                "paper_title": a.paper_title,
                "score": a.score,
                "total_score": a.total_score,
                "normalized_score": (a.result or {}).get("normalized_score"),
                "rating": (a.result or {}).get("rating"),
                "submitted_at": a.submitted_at,
            }
            for a in submitted[:10]
        ],
    }


@router.get("/learning-stats")
def learning_stats(
    student_id: uuid.UUID | None = None,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _collect_learning_stats(db, user, student_id, days)


@router.post("/sets/{set_id}/to-assignment", status_code=status.HTTP_201_CREATED)
def bank_to_assignment(
    set_id: uuid.UUID,
    payload: ToAssignmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_qb_permission(db, user, "question_bank_assignment")
    bank_set = db.get(QuestionBankSet, set_id)
    if not bank_set or bank_set.status != BankSetStatus.PUBLISHED.value:
        raise HTTPException(status_code=404, detail="套卷不存在或未发布")
    query = select(QuestionBankQuestion).where(
        QuestionBankQuestion.bank_set_id == set_id,
        QuestionBankQuestion.status == BankQuestionStatus.PUBLISHED.value,
    )
    if payload.question_ids:
        query = query.where(QuestionBankQuestion.id.in_(payload.question_ids))
    questions = list(db.scalars(query.order_by(QuestionBankQuestion.order_no)).all())
    if not questions:
        raise HTTPException(status_code=409, detail="没有可组卷的已发布题目")
    assignment = Assignment(
        teacher_id=user.id,
        class_id=payload.class_id,
        title=payload.title or bank_set.name,
        mode="homework",
        description=f"来源题库：{bank_set.name}",
        status="draft",
    )
    db.add(assignment)
    db.flush()
    for idx, q in enumerate(questions, start=1):
        answer = q.answer
        if answer is None and q.type == "programming":
            answer = q.reference_code
        db.add(
            Question(
                assignment_id=assignment.id,
                order_no=idx,
                type=q.type,
                stem=q.stem,
                options=q.options,
                answer=answer,
                analysis=q.analysis,
                difficulty=q.difficulty,
                test_cases=q.test_cases,
                language=q.language,
            )
        )
    db.commit()
    return {"assignment_id": str(assignment.id), "title": assignment.title, "question_count": len(questions)}
