import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.enrollment import PageOut


class NotificationOut(BaseModel):
    """通知条目（FR-CL-03 应用内通知）。"""

    id: uuid.UUID
    user_id: uuid.UUID
    # schedule_reminder/low_balance/order_confirmed/feedback_published/
    # assignment_published/submission_graded
    type: str
    title: str
    content: str
    data: dict | None = None  # 关联数据（如 schedule_id, student_id, order_id, assignment_id）
    read_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationUnreadCount(BaseModel):
    """未读通知数（导航栏徽标）。"""

    count: int = 0


class NotificationMarkReadIn(BaseModel):
    """标记已读。"""

    pass


# 通知列表（分页）
NotificationPageOut = PageOut[NotificationOut]
