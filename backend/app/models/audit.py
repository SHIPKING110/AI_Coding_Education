"""操作审计日志：谁、在何时、对什么、做了什么（before/after 快照）。

覆盖范围（M-A 0.8）：账号创建/改密/重置、权限配置、系统设置、知识库删除。
写入失败绝不阻断业务（record 内部兜底）。
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 操作者（system/匿名操作为空）
    actor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    actor_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 动作标识（点分命名，如 user.create / permissions.update / settings.update）
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
