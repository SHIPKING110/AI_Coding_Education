"""职务预设：管理员在权限管理中维护职务及其默认权限，新建/调整教师职务时一键套用。

权限以 {key: bool} 存于 permissions JSON；换职务时自动覆盖该教师的 TeacherPermission 行
（教师个人单独调整过的开关会被职务预设覆盖——职务绑定语义）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from decimal import Decimal

from sqlalchemy import JSON, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobTitle(Base):
    __tablename__ = "job_titles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    permissions: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    base_salary: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["JobTitle"]
