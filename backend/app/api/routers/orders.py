"""课时订阅订单管理（M5，FR-CL-06 模拟支付 = 管理员确认到账）：

- GET /orders            订单列表（admin/staff，可按状态筛选）
- POST /orders/{id}/confirm   确认到账（课时入账 + 流水 + 通知家长）
- POST /orders/{id}/cancel    取消订单（待支付/已支付可取消）

OQ-06 决策：模拟支付阶段由管理员后台确认到账（PRD §3.13 默认）。
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_teacher_permission
from app.core.database import get_db
from app.crud import order as order_crud
from app.models.enrollment import Student
from app.models.user import Role, User
from app.schemas.client import OrderOut
from app.schemas.enrollment import PageOut
from app.services.report_feedback_notify import publish_order_confirmed_notification

router = APIRouter(prefix="/orders", tags=["orders"])

# 订单管理：admin/staff（模拟支付到账确认 OQ-06）
MANAGE_ROLES = (Role.ADMIN, Role.STAFF)


def _to_out(order) -> OrderOut:
    out = OrderOut.model_validate(order)
    if order.student:
        out.student_name = order.student.name
        out.student_campus = order.student.campus
    if order.package:
        out.package_name = order.package.name
    return out


@router.get("", response_model=PageOut[OrderOut])
def list_orders(
    student_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(
        default=None, alias="status", description="pending/paid/confirmed/cancelled/refunded"
    ),
    keyword: str | None = Query(default=None, description="按学员姓名搜索"),
    campus: str | None = Query(default=None, description="按校区筛选"),
    package_id: uuid.UUID | None = Query(default=None),
    date_from: str | None = Query(default=None, description="下单时间起始（ISO）"),
    date_to: str | None = Query(default=None, description="下单时间结束（ISO）"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("order_visible")),
) -> PageOut[OrderOut]:
    """订单列表（分页，可按状态/姓名/校区/课包/时间区间筛选）。教师需 order_visible 权限（默认关闭）。"""
    order_crud.expire_stale_orders(db)
    start = datetime.fromisoformat(date_from) if date_from else None
    end = datetime.fromisoformat(date_to) if date_to else None
    orders = order_crud.list_orders(
        db,
        student_id=student_id,
        status_filter=status_filter,
        keyword=keyword,
        campus=campus,
        package_id=package_id,
        date_from=start,
        date_to=end,
        limit=limit,
        offset=offset,
    )
    total = order_crud.count_orders(
        db,
        student_id=student_id,
        status_filter=status_filter,
        keyword=keyword,
        campus=campus,
        package_id=package_id,
        date_from=start,
        date_to=end,
    )
    return PageOut[OrderOut](
        items=[_to_out(o) for o in orders], total=total, limit=limit, offset=offset
    )


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("order_visible")),
) -> OrderOut:
    order = order_crud.get(db, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    return _to_out(order)


@router.post("/{order_id}/confirm", response_model=OrderOut)
def confirm_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    operator: User = Depends(require_teacher_permission("order_visible")),
) -> OrderOut:
    """确认到账：课时入账 + 流水 + 通知家长（模拟支付 OQ-06）。"""
    order = order_crud.get(db, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    try:
        confirmed, record = order_crud.confirm(db, order, operator_id=operator.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    # 通知家长/学员账号（到账提醒，FR-CL-06）
    student = db.get(Student, confirmed.student_id)
    if student is not None:
        publish_order_confirmed_notification(
            db,
            student=student,
            package_name=(confirmed.package.name if confirmed.package else "课时包"),
            lessons=float(record.delta) if record else 0,
        )
    return _to_out(confirmed)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("order_visible")),
) -> OrderOut:
    """取消订单（管理员：待支付/已支付可取消；已到账不可取消）。"""
    order = order_crud.get(db, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    try:
        return _to_out(order_crud.cancel(db, order))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
