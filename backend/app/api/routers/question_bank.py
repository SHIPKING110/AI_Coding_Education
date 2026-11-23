"""题库导入、审核、发布与基础组卷 API。"""
from __future__ import annotations

import random
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.database import get_db
from app.models.question_bank import (
    BankQuestionStatus,
    BankSetStatus,
    BankSourceStatus,
    QuestionBankQuestion,
    QuestionBankSet,
    QuestionBankSource,
)
from app.models.user import Role, User
from app.services.question_bank_parser import file_hash, parse_docx

router = APIRouter(prefix="/question-bank", tags=["question-bank"])


class BankQuestionUpdate(BaseModel):
    type: str | None = None
    stem: str | None = Field(default=None, min_length=1)
    options: list[str] | None = None
    answer: Any | None = None
    analysis: str | None = None
    difficulty: int | None = Field(default=None, ge=1, le=10)
    score: int | None = Field(default=None, ge=1)
    language: str | None = None
    reference_code: str | None = None
    knowledge_points: list[str] | None = None
    status: str | None = None
    review_note: str | None = None


class BankSetMetaUpdate(BaseModel):
    name: str | None = None
    institution: str | None = None
    exam_year: int | None = None
    subject: str | None = None
    level: str | None = None


class BankImportOut(BaseModel):
    source_id: uuid.UUID
    set_id: uuid.UUID
    question_count: int
    warnings: list[str]


def _serialize_question(q: QuestionBankQuestion, *, include_answer: bool = True) -> dict[str, Any]:
    data = {
        "id": str(q.id),
        "order_no": q.order_no,
        "type": q.type,
        "stem": q.stem,
        "options": q.options,
        "analysis": q.analysis,
        "difficulty": q.difficulty,
        "score": q.score,
        "language": q.language,
        "reference_code": q.reference_code,
        "test_cases": q.test_cases,
        "media": q.media,
        "knowledge_points": q.knowledge_points,
        "status": q.status,
        "review_note": q.review_note,
    }
    if include_answer:
        data["answer"] = q.answer
    return data


def _serialize_set(bank_set: QuestionBankSet, include_questions: bool = False) -> dict[str, Any]:
    data = {
        "id": str(bank_set.id),
        "source_id": str(bank_set.source_id),
        "name": bank_set.name,
        "institution": bank_set.institution,
        "exam_year": bank_set.exam_year,
        "subject": bank_set.subject,
        "level": bank_set.level,
        "total_score": bank_set.total_score,
        "status": bank_set.status,
        "question_count": len(bank_set.questions) if bank_set.questions is not None else None,
        "import_meta": bank_set.import_meta,
        "created_at": bank_set.created_at,
    }
    if include_questions:
        data["questions"] = [_serialize_question(q) for q in bank_set.questions]
    return data


def _ensure_docx(file: UploadFile) -> str:
    filename = (file.filename or "").lower()
    if not filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="题库暂只支持 DOCX 文件")
    return Path(filename).name


@router.post("/imports", response_model=BankImportOut, status_code=status.HTTP_201_CREATED)
def import_docx(
    file: UploadFile = File(...),
    current_user: User = Depends(require_roles(Role.ADMIN, Role.STAFF)),
    db: Session = Depends(get_db),
) -> BankImportOut:
    """上传并解析 DOCX。解析结果永远是草稿，须人工审核后发布。"""
    filename = _ensure_docx(file)
    settings = get_settings()
    root = Path(settings.UPLOAD_DIR) / "question_bank" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / filename
    with source_path.open("wb") as target:
        shutil.copyfileobj(file.file, target)
    digest = file_hash(source_path)
    duplicate = db.scalar(select(QuestionBankSource).where(QuestionBankSource.file_hash == digest))
    if duplicate:
        source_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="该文档已经导入过，请在已有套卷中审核")

    source = QuestionBankSource(
        filename=filename,
        storage_path=str(source_path),
        file_hash=digest,
        status=BankSourceStatus.PARSING,
        uploaded_by=current_user.id,
    )
    db.add(source)
    db.flush()
    try:
        paper = parse_docx(source_path, media_dir=root / "media", media_url_prefix=f"/uploads/question_bank/{root.name}/media")
        bank_set = QuestionBankSet(
            source_id=source.id,
            name=paper.name,
            institution=paper.institution,
            exam_year=paper.exam_year,
            subject=paper.subject,
            level=paper.level,
            total_score=paper.total_score,
            status=BankSetStatus.DRAFT,
            import_meta={"sections": paper.sections, "warnings": paper.warnings, "parser": "rules-v1"},
        )
        db.add(bank_set)
        db.flush()
        for parsed in paper.questions:
            db.add(
                QuestionBankQuestion(
                    bank_set_id=bank_set.id,
                    order_no=parsed.order_no,
                    type=parsed.type,
                    stem=parsed.stem or "待补充题干",
                    options=parsed.options,
                    answer=parsed.answer,
                    analysis=parsed.analysis,
                    difficulty=parsed.difficulty,
                    score=parsed.score,
                    language=parsed.language,
                    reference_code=parsed.reference_code,
                    media=parsed.media,
                    source_excerpt=parsed.source_excerpt,
                    knowledge_points=parsed.knowledge_points,
                    status=BankQuestionStatus.DRAFT,
                )
            )
        source.status = BankSourceStatus.REVIEW_REQUIRED
        db.commit()
        return BankImportOut(source_id=source.id, set_id=bank_set.id, question_count=len(paper.questions), warnings=paper.warnings)
    except Exception as exc:
        db.rollback()
        source.status = BankSourceStatus.FAILED
        source.error_message = str(exc)[:1000]
        db.add(source)
        db.commit()
        raise HTTPException(status_code=422, detail=f"文档解析失败：{exc}") from exc


@router.get("/sets")
def list_sets(
    institution: str | None = None,
    subject: str | None = None,
    level: str | None = None,
    exam_year: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = select(QuestionBankSet).options(selectinload(QuestionBankSet.questions)).order_by(QuestionBankSet.created_at.desc())
    if institution:
        query = query.where(QuestionBankSet.institution == institution)
    if subject:
        query = query.where(QuestionBankSet.subject == subject)
    if level:
        query = query.where(QuestionBankSet.level == level)
    if exam_year:
        query = query.where(QuestionBankSet.exam_year == exam_year)
    if status_filter:
        query = query.where(QuestionBankSet.status == status_filter)
    items = db.scalars(query).all()
    if _user.role in {Role.PARENT.value, Role.STUDENT.value}:
        items = [x for x in items if x.status == BankSetStatus.PUBLISHED.value]
    return {"items": [_serialize_set(x) for x in items], "total": len(items)}


@router.get("/sets/{set_id}")
def get_set(set_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    bank_set = db.scalar(select(QuestionBankSet).options(selectinload(QuestionBankSet.questions)).where(QuestionBankSet.id == set_id))
    if not bank_set:
        raise HTTPException(status_code=404, detail="套卷不存在")
    if bank_set.status != BankSetStatus.PUBLISHED.value and current_user.role in {Role.PARENT.value, Role.STUDENT.value}:
        raise HTTPException(status_code=404, detail="套卷不存在")
    include_answer = current_user.role not in {Role.PARENT.value, Role.STUDENT.value}
    data = _serialize_set(bank_set, include_questions=False)
    data["questions"] = [_serialize_question(q, include_answer=include_answer) for q in bank_set.questions]
    return data


@router.patch("/sets/{set_id}")
def update_set(set_id: uuid.UUID, payload: BankSetMetaUpdate, db: Session = Depends(get_db), _user: User = Depends(require_roles(Role.ADMIN, Role.STAFF))):
    bank_set = db.get(QuestionBankSet, set_id)
    if not bank_set:
        raise HTTPException(status_code=404, detail="套卷不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(bank_set, key, value)
    db.commit()
    return _serialize_set(bank_set)


@router.patch("/sets/{set_id}/questions/{question_id}")
def update_question(set_id: uuid.UUID, question_id: uuid.UUID, payload: BankQuestionUpdate, db: Session = Depends(get_db), _user: User = Depends(require_roles(Role.ADMIN, Role.STAFF))):
    q = db.scalar(select(QuestionBankQuestion).where(QuestionBankQuestion.id == question_id, QuestionBankQuestion.bank_set_id == set_id))
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("status") not in {None, *(x.value for x in BankQuestionStatus)}:
        raise HTTPException(status_code=422, detail="题目状态无效")
    for key, value in changes.items():
        setattr(q, key, value)
    if changes.get("status") == BankQuestionStatus.REVIEWED.value:
        q.reviewed_by = _user.id
        q.reviewed_at = datetime.now(UTC)
    db.commit()
    return _serialize_question(q)


@router.post("/sets/{set_id}/publish")
def publish_set(set_id: uuid.UUID, db: Session = Depends(get_db), _user: User = Depends(require_roles(Role.ADMIN, Role.STAFF))):
    bank_set = db.scalar(select(QuestionBankSet).options(selectinload(QuestionBankSet.questions)).where(QuestionBankSet.id == set_id))
    if not bank_set:
        raise HTTPException(status_code=404, detail="套卷不存在")
    incomplete = [q.order_no for q in bank_set.questions if q.status not in {BankQuestionStatus.REVIEWED.value, BankQuestionStatus.PUBLISHED.value}]
    if incomplete:
        raise HTTPException(status_code=409, detail={"message": "仍有题目未审核", "question_numbers": incomplete})
    for q in bank_set.questions:
        q.status = BankQuestionStatus.PUBLISHED
    bank_set.status = BankSetStatus.PUBLISHED
    if bank_set.source:
        bank_set.source.status = BankSourceStatus.PUBLISHED
    db.commit()
    return _serialize_set(bank_set)


@router.post("/sets/{set_id}/archive")
def archive_set(set_id: uuid.UUID, db: Session = Depends(get_db), _user: User = Depends(require_roles(Role.ADMIN, Role.STAFF))):
    bank_set = db.get(QuestionBankSet, set_id)
    if not bank_set:
        raise HTTPException(status_code=404, detail="套卷不存在")
    bank_set.status = BankSetStatus.ARCHIVED
    db.commit()
    return _serialize_set(bank_set)


@router.get("/stats")
def stats(db: Session = Depends(get_db), _user: User = Depends(require_roles(Role.ADMIN, Role.STAFF, Role.TEACHER))):
    sets = db.scalar(select(func.count()).select_from(QuestionBankSet)) or 0
    questions = db.scalar(select(func.count()).select_from(QuestionBankQuestion)) or 0
    pending = db.scalar(select(func.count()).select_from(QuestionBankQuestion).where(QuestionBankQuestion.status == BankQuestionStatus.DRAFT)) or 0
    return {"sets": sets, "questions": questions, "pending_review": pending}


@router.post("/sets/{set_id}/random")
def random_questions(
    set_id: uuid.UUID,
    count: int = Query(default=10, ge=1, le=100),
    question_type: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(Role.ADMIN, Role.STAFF, Role.TEACHER)),
):
    query = select(QuestionBankQuestion).where(QuestionBankQuestion.bank_set_id == set_id, QuestionBankQuestion.status == BankQuestionStatus.PUBLISHED)
    if question_type:
        query = query.where(QuestionBankQuestion.type == question_type)
    questions = list(db.scalars(query).all())
    if len(questions) < count:
        raise HTTPException(status_code=409, detail=f"题库库存不足：需要 {count} 题，当前 {len(questions)} 题")
    return {"items": [_serialize_question(q) for q in random.sample(questions, count)]}
