"""题库综合练习/错题本/收藏 API

权限边界：
- 已登录用户均可进入已发布题库的综合练习；
- 家长/学员练习关联学员（学生端取自身学员，家长端取当前选中学员）；
- 教师端练习以教师本人为进度归属，不计入学生学习数据；
- 错题/收藏按用户+题目唯一保存，教师端错题独立于学员错题。
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.enrollment import Student
from app.models.question_bank import (
    BankQuestionStatus,
    BankSetStatus,
    QuestionBankQuestion,
    QuestionBankSet,
    QuestionBankUserMark,
)
from app.models.user import Role, User

router = APIRouter(prefix="/question-bank", tags=["question-bank-practice"])

MARK_KINDS = {"favorite", "wrong"}


class MarkIn(BaseModel):
    kind: str
    enabled: bool


class AggregatePracticeIn(BaseModel):
    subject: str | None = None
    level: str | None = None
    institution: str | None = None
    exam_year: int | None = None
    mark_kind: str | None = None  # 'favorite' | 'wrong'：只练该用户已标记的题目
    rules: dict[str, int] = Field(default_factory=dict)  # {"single_choice": 3, "multiple_choice": 2}
    exclude_ids: list[uuid.UUID] = Field(default_factory=list)


def _grade_one(item: dict[str, Any], answer: Any) -> tuple[bool | None, int]:
    qtype = item.get("type")
    correct = item.get("answer")
    max_score = int(item.get("score") or 0)
    if qtype == "programming":
        return None, max_score
    try:
        if qtype == "single_choice":
            ok = answer is not None and correct is not None and int(answer) == int(correct)
        elif qtype == "multiple_choice":
            ok = isinstance(answer, list) and sorted(int(x) for x in answer) == sorted(int(x) for x in (correct or []))
        elif qtype == "judgement":
            ok = answer is not None and bool(answer) == bool(correct)
        else:
            ok = isinstance(answer, str) and isinstance(correct, str) and answer.strip() == correct.strip()
    except (TypeError, ValueError):
        ok = False
    return ok, max_score if ok else 0


@router.post("/aggregates/check")
def check_answer(
    payload: CheckIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.get(QuestionBankQuestion, payload.question_id)
    if not q or q.status != BankQuestionStatus.PUBLISHED.value:
        raise HTTPException(status_code=404, detail="题目不存在或未发布")
    item = {
        "id": str(q.id),
        "type": q.type,
        "answer": q.answer,
        "score": q.score,
    }
    is_correct, got = _grade_one(item, payload.answer)
    if is_correct is False:
        user_id, student_id = _mark_scope(db, current_user)
        mark = db.scalar(
            select(QuestionBankUserMark).where(
                QuestionBankUserMark.user_id == user_id,
                QuestionBankUserMark.student_id == student_id,
                QuestionBankUserMark.question_id == q.id,
                QuestionBankUserMark.kind == "wrong",
            )
        )
        if not mark:
            db.add(
                QuestionBankUserMark(
                    user_id=user_id,
                    student_id=student_id,
                    question_id=q.id,
                    kind="wrong",
                )
            )
        db.commit()
    elif is_correct is True:
        user_id, student_id = _mark_scope(db, current_user)
        mark = db.scalar(
            select(QuestionBankUserMark).where(
                QuestionBankUserMark.user_id == user_id,
                QuestionBankUserMark.student_id == student_id,
                QuestionBankUserMark.question_id == q.id,
                QuestionBankUserMark.kind == "wrong",
            )
        )
        if mark:
            db.delete(mark)
            db.commit()
    return {
        "is_correct": is_correct,
        "correct_answer": q.answer,
        "analysis": q.analysis,
        "reference_code": q.reference_code,
        "score": got,
        "max_score": q.score,
    }


class CheckIn(BaseModel):
    question_id: uuid.UUID
    answer: Any = None


class UserMarkOut(BaseModel):
    kind: str
    question_id: str


class AggregateQuestionOut(BaseModel):
    id: str
    order_no: int
    type: str
    stem: str
    options: list[str] | None
    difficulty: int
    score: int
    language: str | None
    media: list[dict[str, Any]] | None
    knowledge_points: list[str] | None
    favorite: bool = False
    wrong: bool = False


def _visible_user_student(db: Session, user: User) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """返回 (user_id, student_id)。教师端以本人归属；家长/学生端取可见学员。"""
    if user.role == Role.TEACHER.value:
        return user.id, None
    if user.role == Role.STUDENT.value:
        return user.id, None
    # 家长：当前前端没有学生上下文时，取该家长下第一个可用学员作为练习归属
    stu = db.scalars(select(Student).where(Student.parent_user_id == user.id)).first()
    if not stu:
        raise HTTPException(status_code=404, detail="请先绑定学员后再练习")
    return user.id, stu.id


def _mark_scope(db: Session, user: User) -> tuple[uuid.UUID, uuid.UUID | None]:
    """错题/收藏归属。家长端跟随其学员；教师/学员端仅按登录账号隔离。"""
    if user.role == Role.PARENT.value:
        stu = db.scalars(select(Student).where(Student.parent_user_id == user.id)).first()
        return user.id, stu.id if stu else None
    return user.id, None


def _aggregate_base(db: Session, payload: AggregatePracticeIn):
    base = select(QuestionBankQuestion).join(QuestionBankSet).where(
        QuestionBankQuestion.status == BankQuestionStatus.PUBLISHED.value,
        QuestionBankSet.status == BankSetStatus.PUBLISHED.value,
    )
    if payload.subject:
        base = base.where(QuestionBankSet.subject == payload.subject)
    if payload.level:
        base = base.where(QuestionBankSet.level == payload.level)
    if payload.institution:
        base = base.where(QuestionBankSet.institution == payload.institution)
    if payload.exam_year:
        base = base.where(QuestionBankSet.exam_year == payload.exam_year)
    if payload.exclude_ids:
        base = base.where(QuestionBankQuestion.id.notin_(payload.exclude_ids))
    return base


@router.get("/aggregates/subjects")
def aggregate_subjects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subject_rows = db.scalars(
        select(QuestionBankSet.subject).distinct().where(QuestionBankSet.status == BankSetStatus.PUBLISHED.value)
    ).all()
    level_rows = db.scalars(
        select(QuestionBankSet.level).distinct().where(QuestionBankSet.status == BankSetStatus.PUBLISHED.value)
    ).all()
    return {
        "subjects": [s for s in subject_rows if s],
        "levels": [level for level in level_rows if level],
    }


@router.post("/aggregates/practice", response_model=list[AggregateQuestionOut])
def aggregate_practice(
    payload: AggregatePracticeIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _visible_user_student(db, current_user)
    user_id, student_id = _mark_scope(db, current_user)
    base = _aggregate_base(db, payload)
    if payload.mark_kind:
        if payload.mark_kind not in MARK_KINDS:
            raise HTTPException(status_code=422, detail="不支持的标记类型")
        mark_subq = select(QuestionBankUserMark.question_id).where(
            QuestionBankUserMark.user_id == current_user.id,
            QuestionBankUserMark.student_id == student_id,
            QuestionBankUserMark.kind == payload.mark_kind,
        )
        base = base.where(QuestionBankQuestion.id.in_(mark_subq))
    rules = {}
    for key, value in (payload.rules or {}).items():
        if key not in {"single_choice", "multiple_choice", "judgement", "code_fill", "programming"}:
            continue
        count = int(value)
        if count > 0:
            rules[key] = count
    if not rules:
        # 未限定题型时，取全部已发布题目（不超过 100 题），保证“综合练习”可进入
        rows = list(db.scalars(base.order_by(QuestionBankQuestion.created_at.desc()).limit(100)).all())
    else:
        picked: list[QuestionBankQuestion] = []
        for qtype, count in rules.items():
            rows = list(db.scalars(base.where(QuestionBankQuestion.type == qtype)).all())
            if len(rows) < count:
                raise HTTPException(
                    status_code=409,
                    detail={"message": "题库库存不足", "gaps": {qtype: f"需要 {count} 题，库存仅 {len(rows)} 题"}},
                )
            import random

            picked.extend(random.sample(rows, count))
        random.shuffle(picked)
        rows = picked

    user_id, student_id = current_user.id, None
    if current_user.role == Role.PARENT.value:
        stu = db.scalars(select(Student).where(Student.parent_user_id == current_user.id)).first()
        if stu:
            student_id = stu.id
    marks: dict[str, set[str]] = {}
    if rows:
        mark_rows = db.scalars(
            select(QuestionBankUserMark).where(
                QuestionBankUserMark.user_id == user_id,
                QuestionBankUserMark.student_id == student_id,
                QuestionBankUserMark.question_id.in_([q.id for q in rows]),
                QuestionBankUserMark.kind.in_(MARK_KINDS),
            )
        ).all()
        for mark in mark_rows:
            marks.setdefault(str(mark.question_id), set()).add(mark.kind)
    return [
        AggregateQuestionOut(
            id=str(q.id),
            order_no=q.order_no,
            type=q.type,
            stem=q.stem,
            options=q.options,
            difficulty=q.difficulty,
            score=q.score,
            language=q.language,
            media=q.media,
            knowledge_points=q.knowledge_points,
            favorite="favorite" in marks.get(str(q.id), set()),
            wrong="wrong" in marks.get(str(q.id), set()),
        )
        for q in rows
    ]


@router.post("/aggregates/{question_id}/mark")
def toggle_mark(
    question_id: uuid.UUID,
    payload: MarkIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.kind not in MARK_KINDS:
        raise HTTPException(status_code=422, detail="不支持的标记类型")
    q = db.get(QuestionBankQuestion, question_id)
    if not q or q.status != BankQuestionStatus.PUBLISHED.value:
        raise HTTPException(status_code=404, detail="题目不存在或未发布")
    user_id = current_user.id
    _, student_id = _mark_scope(db, current_user)
    mark = db.scalar(
        select(QuestionBankUserMark).where(
            QuestionBankUserMark.user_id == user_id,
            QuestionBankUserMark.student_id == student_id,
            QuestionBankUserMark.question_id == question_id,
            QuestionBankUserMark.kind == payload.kind,
        )
    )
    if payload.enabled:
        if not mark:
            db.add(
                QuestionBankUserMark(
                    user_id=user_id,
                    student_id=student_id,
                    question_id=question_id,
                    kind=payload.kind,
                )
            )
    else:
        if mark:
            db.delete(mark)
    db.commit()
    return {"saved": True, "kind": payload.kind, "enabled": payload.enabled}


@router.get("/aggregates/marks", response_model=list[UserMarkOut])
def list_marks(
    kind: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if kind and kind not in MARK_KINDS:
        raise HTTPException(status_code=422, detail="不支持的标记类型")
    stmt = select(QuestionBankUserMark).where(QuestionBankUserMark.user_id == current_user.id)
    if kind:
        stmt = stmt.where(QuestionBankUserMark.kind == kind)
    else:
        stmt = stmt.where(QuestionBankUserMark.kind.in_(MARK_KINDS))
    if current_user.role == Role.PARENT.value:
        _, student_id = _mark_scope(db, current_user)
        if student_id:
            stmt = stmt.where(QuestionBankUserMark.student_id == student_id)
        else:
            stmt = stmt.where(QuestionBankUserMark.student_id.is_(None))
    else:
        stmt = stmt.where(QuestionBankUserMark.student_id.is_(None))
    rows = db.scalars(stmt).all()
    return [{"kind": r.kind, "question_id": str(r.question_id)} for r in rows]


@router.post("/aggregates/wrong/{question_id}")
def add_wrong(
    question_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return toggle_mark(question_id, MarkIn(kind="wrong", enabled=True), db=db, current_user=current_user)


@router.get("/aggregates/wrong", response_model=list[UserMarkOut])
def list_wrong(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_marks(kind="wrong", db=db, current_user=current_user)


@router.post("/aggregates/favorite/{question_id}")
def add_favorite(
    question_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return toggle_mark(question_id, MarkIn(kind="favorite", enabled=True), db=db, current_user=current_user)


@router.get("/aggregates/favorites", response_model=list[UserMarkOut])
def list_favorites(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_marks(kind="favorite", db=db, current_user=current_user)
