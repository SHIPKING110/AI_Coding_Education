import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_teacher_permission
from app.core.database import get_db
from app.crud import lesson as lesson_crud
from app.crud import student as student_crud
from app.models.enrollment import LessonRecordType
from app.models.user import Role, User
from app.schemas.enrollment import LessonRecordIn, LessonRecordOut

router = APIRouter(prefix="/students", tags=["lesson-records"])

MANAGE_ROLES = (Role.ADMIN, Role.STAFF)


def _to_out(record) -> LessonRecordOut:
    out = LessonRecordOut.model_validate(record)
    out.operator_name = record.operator.name if record.operator else None
    return out


@router.post(
    "/{student_id}/lesson-records",
    response_model=LessonRecordOut,
    status_code=status.HTTP_201_CREATED,
)
def adjust_lesson_balance(
    student_id: uuid.UUID,
    payload: LessonRecordIn,
    db: Session = Depends(get_db),
    operator: User = Depends(require_teacher_permission("student_adjust")),
) -> LessonRecordOut:
    """管理员/教务调整学员课时：delta>0 入账（充值/赠送），delta<0 人工扣减。

    人工扣减不允许使余额为负。
    """
    student = student_crud.get(db, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    if payload.delta == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="delta 不能为 0")
    delta = Decimal(str(payload.delta))
    if delta < 0 and Decimal(str(student.lesson_balance)) + delta < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="扣减后课时不能为负",
        )
    record = lesson_crud.add_record(
        db,
        student=student,
        delta=delta,
        record_type=LessonRecordType.ADJUST if payload.delta < 0 else LessonRecordType.RECHARGE,
        operator_id=operator.id,
        remark=payload.remark,
    )
    return _to_out(record)


@router.get("/{student_id}/lesson-records", response_model=list[LessonRecordOut])
def list_lesson_records(
    student_id: uuid.UUID,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("student_records")),
) -> list[LessonRecordOut]:
    student = student_crud.get(db, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    records = lesson_crud.list_records(db, student_id, limit=limit, offset=offset)
    return [_to_out(r) for r in records]
