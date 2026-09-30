"""通知路由（M5）：站内通知 + 提醒生成。

- 所有登录角色可读取自己的通知
- 通知类型：上课提醒/低余量/订单到账/反馈发布/作业发布/批改完成
- 微信推送预留（OQ-01）：后续可扩展为微信模板消息
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.crud import notification as notification_crud
from app.models.user import User
from app.schemas.notification import (
    NotificationOut,
    NotificationPageOut,
    NotificationUnreadCount,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPageOut)
def list_notifications(
    unread_only: bool = Query(default=False, description="仅未读通知"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationPageOut:
    """我的通知列表（新在前）。"""
    items = notification_crud.list_for_user(
        db, user_id=current_user.id, unread_only=unread_only, limit=limit, offset=offset
    )
    total = notification_crud.count_for_user(
        db, user_id=current_user.id, unread_only=unread_only
    )
    return NotificationPageOut(
        items=[NotificationOut.model_validate(n) for n in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{notification_id}/read",
    response_model=NotificationOut,
    status_code=status.HTTP_200_OK,
)
def mark_notification_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationOut:
    """标记单条通知为已读。"""
    notification = notification_crud.get(db, notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在")
    if notification.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作他人通知")
    return NotificationOut.model_validate(notification_crud.mark_read(db, notification))


@router.post(
    "/read-all",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """标记我的全部通知为已读。"""
    count = notification_crud.mark_all_read(db, user_id=current_user.id)
    return {"marked_count": count, "message": f"已标记 {count} 条通知为已读"}


@router.get("/unread-count", response_model=NotificationUnreadCount)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationUnreadCount:
    """未读通知数（导航栏徽标）。"""
    count = notification_crud.count_unread(db, user_id=current_user.id)
    return NotificationUnreadCount(count=count)
