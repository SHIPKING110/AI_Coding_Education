import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_teacher_permission
from app.core.database import get_db
from app.crud import lesson as lesson_crud
from app.models.user import Role, User
from app.schemas.enrollment import (
    LessonPackageCreate,
    LessonPackageOut,
    LessonPackageUpdate,
    PageOut,
)

router = APIRouter(prefix="/lesson-packages", tags=["lesson-packages"])

# 课时包发布为高权限管理员专属（PRD FR-PK-01）
ADMIN_ONLY = (Role.ADMIN,)

ALLOWED_TAGS = ("regular", "activity")


def _to_out(db: Session, p) -> LessonPackageOut:
    out = LessonPackageOut.model_validate(p)
    out.subject_name = p.subject.name if p.subject else None
    out.paid_students = lesson_crud.package_paid_count(db, p.id)
    return out


@router.get("", response_model=PageOut[LessonPackageOut])
def list_packages(
    include_inactive: bool = False,
    subject_id: uuid.UUID | None = Query(default=None, description="按学科科目筛选"),
    tag: str | None = Query(default=None, description="regular=常规课 | activity=活动课"),
    price_min: Decimal | None = Query(default=None, description="售价下限"),
    price_max: Decimal | None = Query(default=None, description="售价上限"),
    limit: int = Query(default=12, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PageOut[LessonPackageOut]:
    packages = lesson_crud.list_packages(
        db,
        include_inactive=include_inactive,
        subject_id=subject_id,
        tag=tag,
        price_min=price_min,
        price_max=price_max,
        limit=limit,
        offset=offset,
    )
    total = lesson_crud.count_packages(
        db,
        include_inactive=include_inactive,
        subject_id=subject_id,
        tag=tag,
        price_min=price_min,
        price_max=price_max,
    )
    return PageOut[LessonPackageOut](
        items=[_to_out(db, p) for p in packages],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=LessonPackageOut, status_code=status.HTTP_201_CREATED)
def create_package(
    payload: LessonPackageCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("package_create", staff_allowed=False)),
) -> LessonPackageOut:
    if payload.tag not in ALLOWED_TAGS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tag 非法")
    if payload.tag == "activity" and (
        payload.sale_start is None or payload.sale_end is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="活动课包需设置售卖时间范围"
        )
    if (
        payload.sale_start is not None
        and payload.sale_end is not None
        and payload.sale_start >= payload.sale_end
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="售卖开始时间须早于结束时间"
        )
    package = lesson_crud.create_package(
        db,
        name=payload.name,
        price=payload.price,
        total_lessons=payload.total_lessons,
        cover_image=payload.cover_image,
        subject_id=payload.subject_id,
        tag=payload.tag,
        sale_start=payload.sale_start,
        sale_end=payload.sale_end,
    )
    return _to_out(db, package)


@router.patch("/{package_id}", response_model=LessonPackageOut)
def update_package(
    package_id: uuid.UUID,
    payload: LessonPackageUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("package_create", staff_allowed=False)),
) -> LessonPackageOut:
    package = lesson_crud.get_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")
    locked = lesson_crud.package_has_paid_orders(db, package_id)
    if locked and (
        (payload.price is not None and payload.price != package.price)
        or (payload.total_lessons is not None and payload.total_lessons != package.total_lessons)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该课时包已有支付订单，售价与总课时不可再改（可改名称/科目/标签/上下架）",
        )
    new_tag = payload.tag if payload.tag is not None else package.tag
    new_start = payload.sale_start if payload.sale_start is not None else package.sale_start
    new_end = payload.sale_end if payload.sale_end is not None else package.sale_end
    if new_tag not in ALLOWED_TAGS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tag 非法")
    if new_tag == "activity" and (new_start is None or new_end is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="活动课包需设置售卖时间范围"
        )
    if new_start is not None and new_end is not None and new_start >= new_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="售卖开始时间须早于结束时间"
        )
    package = lesson_crud.update_package(
        db,
        package,
        name=payload.name,
        price=payload.price,
        total_lessons=payload.total_lessons,
        cover_image=payload.cover_image,
        status=payload.status,
        subject_id=payload.subject_id,
        tag=payload.tag,
        sale_start=payload.sale_start,
        sale_end=payload.sale_end,
        subject_id_set=payload.subject_id_set,
    )
    # 缺 published_at 的老数据回填（发布时间展示用）
    if package.published_at is None:
        package.published_at = package.created_at or datetime.now()
        db.commit()
        db.refresh(package)
    return _to_out(db, package)


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_package(
    package_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("package_off", staff_allowed=False)),
) -> None:
    """下架课时包（软下架，保留历史订单）。"""
    package = lesson_crud.get_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")
    lesson_crud.update_package(
        db,
        package,
        name=None,
        price=None,
        total_lessons=None,
        cover_image=None,
        status="inactive",
    )
