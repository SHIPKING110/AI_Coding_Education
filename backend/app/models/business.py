"""业务基础资料：校区 / 科目 / 创收账本 / 财务参数。

- Campus：校区名称标签（替代写死的校区字符串，老数据字符串保留）
- Subject：科目名称标签 + 每次课消耗课时数 + 教师抽成比例（排课扣课时与绩效的唯一口径）
- RevenueLedger：不可变创收账本，考勤确认消耗瞬间写入（单价/比例快照固化）
- FinanceSetting：全局财务参数（默认抽成比例）
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Campus(Base):
    __tablename__ = "campuses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 每次课消耗课时数（排课考勤扣减口径，支持半课时如 1.5）
    per_session: Mapped[Decimal] = mapped_column(Numeric(4, 1), default=Decimal("2"))
    # 教师抽成比例（0~1，为空则用全局默认）
    commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RevenueLedger(Base):
    """创收账本（只写不改）：每次考勤消耗记一行。

    amount = lessons × unit_price（unit_price 为消耗瞬间 FIFO 加权单价快照）
    commission = amount × commission_rate（快照）
    """

    __tablename__ = "revenue_ledger"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedules.id"), nullable=True, index=True
    )
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subjects.id"), nullable=True, index=True
    )
    subject_name: Mapped[str] = mapped_column(String(64), default="")
    lessons: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    commission: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class FinanceSetting(Base):
    __tablename__ = "finance_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    # 全局默认抽成比例（科目未单独设置时使用）
    commission_default: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.30")
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TeacherLevel(Base):
    """教师级别：名称 + 单节课绩效比例（0~1）。消耗1课时按单价×比例计教师绩效，剩余为公司课时盈收。"""

    __tablename__ = "teacher_levels"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ratio: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.10"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommissionRule(Base):
    """教务/教师提成规则：按类型配置单价（key 唯一），薪资计算的唯一口径。"""

    __tablename__ = "commission_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(32), default="元/人次")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PayrollEntry(Base):
    """薪资核算条目：按人按月记录各项构成（教务/教师共用），明细存 detail JSON。"""

    __tablename__ = "payroll_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    base_salary: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    lesson_commission: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    invite_count: Mapped[int] = mapped_column(Integer, default=0)
    invite_bonus: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    trial_count: Mapped[int] = mapped_column(Integer, default=0)
    trial_bonus: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    convert_count: Mapped[int] = mapped_column(Integer, default=0)
    convert_bonus: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    renew_count: Mapped[int] = mapped_column(Integer, default=0)
    renew_bonus: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    refer_count: Mapped[int] = mapped_column(Integer, default=0)
    refer_bonus: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
