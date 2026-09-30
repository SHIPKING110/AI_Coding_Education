import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Role(enum.StrEnum):
    ADMIN = "admin"      # 高权限管理员
    STAFF = "staff"      # 教务
    TEACHER = "teacher"  # 教师
    PARENT = "parent"    # 家长
    STUDENT = "student"  # 学员


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(Enum(Role, native_enum=False, length=16), index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(255))
    # 校区/分支机构标签（多校区区分，如 一校/二校/三校，可自定义）
    campus: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 职务标签（可自定义，如 主教/助教/班主任；也可在权限管理中按职务预设权限）
    title: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 教师级别（关联 teacher_levels.id 字符串存档，删除级别时置空）
    teacher_level_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    teacher_level_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 基本工资（为空时取职务基本工资）
    base_salary: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(UserStatus, native_enum=False, length=16), default=UserStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
