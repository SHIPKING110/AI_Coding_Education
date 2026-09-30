"""通知 CRUD（M5）：按用户列出/未读计数/标记已读/创建。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.notification import Notification, NotificationType


def get(db: Session, notification_id: uuid.UUID) -> Notification | None:
    return db.get(Notification, notification_id)


def list_for_user(
    db: Session,
    *,
    user_id: uuid.UUID,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    """某用户的通知列表（新在前，可选只看未读）。"""
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def count_unread(db: Session, *, user_id: uuid.UUID) -> int:
    """未读通知数（导航栏徽标）。"""
    return (
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
        or 0
    )


def count_for_user(
    db: Session,
    *,
    user_id: uuid.UUID,
    unread_only: bool = False,
) -> int:
    stmt = select(func.count(Notification.id)).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return db.scalar(stmt) or 0


def create(
    db: Session,
    *,
    user_id: uuid.UUID,
    type: str,
    title: str,
    content: str,
    data: dict | None = None,
) -> Notification:
    """创建通知（供 提醒服务/订单确认/反馈发布/作业发布/批改 使用）。"""
    n = Notification(
        user_id=user_id,
        type=type,
        title=title,
        content=content,
        data=data,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def mark_read(db: Session, notification: Notification) -> Notification:
    """标记已读（幂等）。"""
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()
        db.refresh(notification)
    return notification


def mark_assignment_submissions_handled(
    db: Session,
    *,
    teacher_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> int:
    """把某教师「某作业」的提交通知标记为已处理（已读 + data.handled=True）。

    教师批改该作业的提交后调用：老通知不再作为「待办跳转」展示/点击，
    避免批改完成后重复跳到批改页。
    """
    now = datetime.now(UTC)
    items = list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == teacher_id,
                Notification.type == NotificationType.SUBMISSION_SUBMITTED.value,
                Notification.read_at.is_(None),
            )
        )
    )
    marked = 0
    for n in items:
        if (n.data or {}).get("assignment_id") != str(assignment_id):
            continue
        n.read_at = now
        n.data = {**(n.data or {}), "handled": True}
        marked += 1
    if marked:
        db.commit()
    return marked


def mark_all_read(db: Session, *, user_id: uuid.UUID) -> int:
    """将该用户全部未读通知标记为已读，返回更新的条数。"""
    items = list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
    )
    for n in items:
        n.read_at = datetime.now(UTC)
    db.commit()
    return len(items)
