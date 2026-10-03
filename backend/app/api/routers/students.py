import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_teacher_permission
from app.core.database import get_db
from app.crud import lesson as lesson_crud
from app.crud import order as order_crud
from app.crud import student as student_crud
from app.models.enrollment import (
    FollowUpStatus,
    PackageStatus,
    StudentStatus,
)
from app.models.user import Role, User
from app.schemas.enrollment import (
    ClassBrief,
    PageOut,
    StudentClassesUpdate,
    StudentCreate,
    StudentFollowUpUpdate,
    StudentOut,
    StudentRefundIn,
    StudentRenewIn,
    StudentStatusUpdate,
    StudentUpdate,
)

router = APIRouter(prefix="/students", tags=["students"])

# 学员管理写操作：admin / staff（教务）；教师只读
MANAGE_ROLES = (Role.ADMIN, Role.STAFF)


def _to_out(student, db=None) -> StudentOut:
    out = StudentOut.model_validate(student)
    out.low_balance = student.lesson_balance <= 10
    if student.lesson_balance < 0 and db is not None:
        from decimal import Decimal as _Dec

        price, _, _ = order_crud.last_package_price(db, student=student)
        out.arrears_lessons = float(-student.lesson_balance)
        out.arrears_amount = str(
            (_Dec(str(-student.lesson_balance)) * price).quantize(_Dec("0.01"))
        )
    out.classes = [
        ClassBrief(
            id=c.id,
            name=c.name,
            subject=c.subject,
            teacher_name=c.teacher.name if c.teacher else None,
        )
        for c in student.classes
    ]
    return out


@router.get("", response_model=PageOut[StudentOut])
def list_students(
    keyword: str | None = Query(default=None),
    class_id: uuid.UUID | None = Query(default=None),
    class_unassigned: bool = Query(default=False, description="只看未加入任何班级的学员"),
    campus: str | None = Query(default=None),
    campus_unassigned: bool = Query(default=False, description="只看未填校区的学员"),
    status: str | None = Query(default=None, pattern="^(active|stopped|archived)$"),
    lesson_balance_min: int | None = Query(default=None, ge=0),
    lesson_balance_max: int | None = Query(default=None, ge=0),
    low_balance_only: bool = Query(default=False, description="催缴名单：课时<=10 或已跟进"),
    follow_up: str | None = Query(
        default=None, description="按跟进状态筛选：pending/renewed/stopped"
    ),
    teacher_id: uuid.UUID | None = Query(
        default=None, description="带教教师筛选：学员所在任意班级的带教教师"
    ),
    teacher_unassigned: bool = Query(
        default=False, description="只看班级未分配教师的学员（含未加入班级）"
    ),
    account: str | None = Query(
        default=None,
        pattern="^(unbound_student|unbound_parent)$",
        description="账号筛选：unbound_student=未绑定学员账号 / unbound_parent=未绑定家长账号",
    ),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageOut[StudentOut]:
    """查询学员（分页）。low_balance_only=true 返回催缴名单（课时<=10 或已进入跟进流程）。"""
    students = student_crud.list_all(
        db,
        keyword=keyword,
        class_id=class_id,
        class_unassigned=class_unassigned,
        campus=campus,
        campus_unassigned=campus_unassigned,
        status=status,
        lesson_balance_min=lesson_balance_min,
        lesson_balance_max=lesson_balance_max,
        low_balance_only=low_balance_only,
        follow_up=follow_up,
        teacher_id=teacher_id,
        teacher_unassigned=teacher_unassigned,
        account=account,
        limit=limit,
        offset=offset,
    )
    total = student_crud.count_all(
        db,
        keyword=keyword,
        class_id=class_id,
        class_unassigned=class_unassigned,
        campus=campus,
        campus_unassigned=campus_unassigned,
        status=status,
        lesson_balance_min=lesson_balance_min,
        lesson_balance_max=lesson_balance_max,
        low_balance_only=low_balance_only,
        follow_up=follow_up,
        teacher_id=teacher_id,
        teacher_unassigned=teacher_unassigned,
        account=account,
    )

    return PageOut[StudentOut](
        items=[_to_out(s, db) for s in students], total=total, limit=limit, offset=offset
    )


@router.post("", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("student_create")),
) -> StudentOut:
    if payload.package_id is not None:
        from app.models.enrollment import LessonPackage, PackageStatus

        package = db.get(LessonPackage, payload.package_id)
        if package is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课时包不存在")
        if package.status != PackageStatus.ACTIVE.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="课时包已下架")
    student = student_crud.create(
        db,
        name=payload.name,
        phone=payload.phone,
        lesson_balance=0 if payload.package_id is not None else payload.lesson_balance,
        campus=payload.campus,
        parent_user_id=payload.parent_user_id,
        student_user_id=payload.student_user_id,
        class_ids=payload.class_ids,
        source=payload.source,
        referrer=payload.referrer,
    )
    if payload.package_id is not None:
        try:
            order_crud.create_confirmed(
                db,
                student_id=student.id,
                package_id=payload.package_id,
                operator_id=user.id,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        db.refresh(student)
    return _to_out(student, db)


@router.get("/{student_id}/last-price")
def get_last_package_price(
    student_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("student_adjust")),
) -> dict:
    """该学员最近一次已确认购包的单价（元/课时），供调课时默认带出，可手工改。"""
    from decimal import Decimal as _Dec

    from sqlalchemy import select as _select

    from app.models.enrollment import LessonPackage as _PKG
    from app.models.enrollment import Order as _Order
    from app.models.enrollment import OrderStatus as _OS

    student = student_crud.get(db, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    order = db.scalar(
        _select(_Order)
        .where(_Order.student_id == student.id, _Order.status == _OS.CONFIRMED.value)
        .order_by(_Order.confirmed_at.desc().nullslast(), _Order.created_at.desc())
    )
    if order is None:
        return {"price": None, "package_name": None}
    package = db.get(_PKG, order.package_id) if order.package_id else None
    lessons = _Dec(str(package.total_lessons)) if package and package.total_lessons else _Dec("0")
    price = (_Dec(str(order.amount)) / lessons).quantize(_Dec("0.01")) if lessons > 0 else _Dec("0")
    return {
        "price": str(price),
        "package_name": package.name if package else None,
        "order_id": str(order.id),
    }


@router.get("/{student_id}", response_model=StudentOut)
def get_student(
    student_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> StudentOut:
    student = student_crud.get(db, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return _to_out(student, db)


@router.patch("/{student_id}", response_model=StudentOut)
def update_student(
    student_id: uuid.UUID,
    payload: StudentUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("student_edit")),
) -> StudentOut:
    student = student_crud.get(db, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    student = student_crud.update(
        db,
        student,
        name=payload.name,
        phone=payload.phone,
        campus=payload.campus,
        parent_user_id=payload.parent_user_id,
        student_user_id=payload.student_user_id,
        class_ids=payload.class_ids,
    )
    return _to_out(student, db)


@router.patch("/{student_id}/classes", response_model=StudentOut)
def update_student_classes(
    student_id: uuid.UUID,
    payload: StudentClassesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StudentOut:
    """调整学员班级。

    - 管理员/教务：可调整到任意班级；
    - 教师：需 student_classes 权限，只能把学员调整到「本人所带」的班级，
      其他教师的班级归属保持不变。
    """
    student = student_crud.get(db, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    if user.role == Role.TEACHER.value:
        from app.models.permission import check as _perm_check

        if not _perm_check(db, user, "class_unenroll"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="暂无该操作权限，请联系管理员开通")
    restrict = user.id if user.role == Role.TEACHER else None
    try:
        student = student_crud.set_classes(
            db, student, payload.class_ids, restrict_teacher_id=restrict
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return _to_out(student, db)


@router.patch("/{student_id}/status", response_model=StudentOut)
def update_student_status(
    student_id: uuid.UUID,
    payload: StudentStatusUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("student_stop")),
) -> StudentOut:
    """学员停课 / 恢复在读。停课必须填写备注（便于后续教务与家长沟通恢复复课）。"""
    if payload.status not in (StudentStatus.ACTIVE.value, StudentStatus.STOPPED.value):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="状态非法")
    if payload.status == StudentStatus.STOPPED.value and not (payload.stop_note or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="停课需填写备注，以便后续教务与学生家长沟通恢复复课",
        )
    student = student_crud.set_status(
        db,
        student_id,
        status=payload.status,
        stop_note=payload.stop_note,
    )
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return _to_out(student, db)


@router.patch("/{student_id}/follow-up", response_model=StudentOut)
def update_student_follow_up(
    student_id: uuid.UUID,
    payload: StudentFollowUpUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("student_stop")),
) -> StudentOut:
    """维护催缴跟进状态：待跟进 -> 已续费/已停课；已停课学员可恢复为待跟进。"""
    if payload.follow_up_status not in (
        FollowUpStatus.PENDING.value,
        FollowUpStatus.RENEWED.value,
        FollowUpStatus.STOPPED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="跟进状态非法"
        )
    student = student_crud.set_follow_up(
        db,
        student_id,
        follow_up_status=payload.follow_up_status,
        note=payload.note,
    )
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return _to_out(student, db)


@router.post("/{student_id}/renew", response_model=StudentOut)
def renew_student(
    student_id: uuid.UUID,
    payload: StudentRenewIn,
    db: Session = Depends(get_db),
    operator: User = Depends(require_teacher_permission("student_refund")),
) -> StudentOut:
    """催缴续费入账：选择课时包 或 自定义补课时+金额。

    校验 package_id 与 custom_lessons 二选一；课时包必须为在售状态。
    """
    if (payload.package_id is None) == (payload.custom_lessons is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请二选一：选择课时包 或 填写自定义补充课时",
        )
    if payload.package_id is not None:
        package = lesson_crud.get_package(db, payload.package_id)
        if package is None or package.status != PackageStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="课时包不存在或已下架"
            )

    student = student_crud.get(db, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    student, _record, _order = student_crud.renew(
        db,
        student,
        package_id=payload.package_id,
        custom_lessons=payload.custom_lessons,
        custom_amount=payload.custom_amount,
        note=payload.note,
        operator_id=operator.id,
    )
    return _to_out(student, db)


@router.get("/{student_id}/refund-preview")
def refund_preview_student(
    student_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("student_refund")),
) -> dict:
    """学员退费预览：仅计算 FIFO 明细，不落库。"""
    student = student_crud.get(db, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    detail, total_amount, total_lessons = order_crud.refund_fifo_preview(db, student=student)
    return {"items": detail, "total_amount": str(total_amount), "total_lessons": float(total_lessons)}


@router.post("/{student_id}/refund")
def refund_student(
    student_id: uuid.UUID,
    payload: StudentRefundIn,
    db: Session = Depends(get_db),
    operator: User = Depends(require_teacher_permission("student_refund")),
) -> dict:
    """学员退费：备注必填，系统按 FIFO 自动计算退费明细。"""
    student = student_crud.get(db, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    try:
        orders, records, detail, total_amount, total_lessons = order_crud.refund_fifo(
            db,
            student=student,
            operator_id=operator.id,
            note=payload.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    from app.services.report_feedback_notify import publish_refund_notification

    publish_refund_notification(
        db,
        student=student,
        amount=str(total_amount),
        detail_lines=[
            f"{d['package_name']}：剩余 {d['remaining_lessons']} 课时，¥{d['refund_amount']}"
            for d in detail
        ],
    )
    return {
        "student": _to_out(student, db),
        "orders": [o.id for o in orders],
        "records": [r.id for r in records],
        "detail": detail,
        "total_amount": str(total_amount),
        "total_lessons": float(total_lessons),
    }


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_student(
    student_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("student_delete")),
) -> None:
    """删除学员（软删除归档，历史数据保留）。教师需 student_delete 权限（默认关闭）。"""
    student = student_crud.get(db, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    student_crud.archive(db, student)
