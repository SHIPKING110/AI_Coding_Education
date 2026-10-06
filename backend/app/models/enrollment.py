import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import User

if TYPE_CHECKING:
    from app.models.business import Subject
    from app.models.feedback import Feedback


class StudentStatus(enum.StrEnum):
    ACTIVE = "active"    # 在读
    STOPPED = "stopped"  # 已停课（特殊原因停课，备注见 stop_note，可恢复在读）
    ARCHIVED = "archived"  # 已归档（软删除）


class FollowUpStatus(enum.StrEnum):
    PENDING = "pending"    # 待跟进（课时 <= 10 自动进入催缴名单）
    RENEWED = "renewed"    # 已续费
    STOPPED = "stopped"    # 已停课（不再催缴）


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    campus: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 家长账号（M5 客户端绑定）；本期可为空
    parent_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # 学员本人登录账号（M5 客户端：学员角色自己登录做题）；一个账号只能绑定一个学员
    student_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, unique=True, index=True
    )
    lesson_balance: Mapped[Decimal] = mapped_column(Numeric(10, 1), default=Decimal("0"), index=True)
    # 体验状态：none 普通学员 / trial 体验中 / signed 体验后已报名 / lost 体验未报名结束服务
    gender: Mapped[str] = mapped_column(String(8), default="", index=True)
    trial_status: Mapped[str] = mapped_column(String(16), default="none", index=True)
    # 生源：normal 自然到访 / referral 口碑转介绍（报名时标记）
    source: Mapped[str] = mapped_column(String(16), default="normal", index=True)
    referrer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 催缴跟进状态（M2 催缴名单）：课时<=10 进入待跟进，教务处理后标 已续费/已停课
    follow_up_status: Mapped[str] = mapped_column(
        Enum(FollowUpStatus, native_enum=False, length=16),
        default=FollowUpStatus.PENDING,
        index=True,
    )
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    follow_up_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 停课备注（status=stopped 时必填；恢复在读后保留供沟通参考）
    stop_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(StudentStatus, native_enum=False, length=16), default=StudentStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    classes: Mapped[list["Class"]] = relationship(
        secondary="student_classes", back_populates="students"
    )
    feedbacks: Mapped[list["Feedback"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), index=True)
    subject: Mapped[str] = mapped_column(String(64))
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(StudentStatus, native_enum=False, length=16), default=StudentStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    teacher: Mapped["User | None"] = relationship(foreign_keys=[teacher_id])
    students: Mapped[list["Student"]] = relationship(
        secondary="student_classes", back_populates="classes"
    )


class StudentClass(Base):
    __tablename__ = "student_classes"

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), primary_key=True
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PackageStatus(enum.StrEnum):
    ACTIVE = "active"      # 在售
    INACTIVE = "inactive"  # 下架


class PackageTag(enum.StrEnum):
    REGULAR = "regular"    # 常规课
    ACTIVITY = "activity"  # 活动课（可设售卖时间范围）


class LessonPackage(Base):
    __tablename__ = "lesson_packages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total_lessons: Mapped[int] = mapped_column()
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subjects.id"), nullable=True, index=True
    )
    tag: Mapped[str] = mapped_column(String(16), default=PackageTag.REGULAR.value, index=True)
    sale_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sale_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cover_image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped["Subject | None"] = relationship()
    status: Mapped[str] = mapped_column(
        Enum(PackageStatus, native_enum=False, length=16), default=PackageStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LessonRecordType(enum.StrEnum):
    RECHARGE = "recharge"   # 充值入账（购买课时包 / 管理员调整）
    CONSUME = "consume"     # 上课扣减（M2 划课时使用）
    ADJUST = "adjust"       # 人工调整
    REFUND = "refund"       # 退费扣减（按 FIFO 计算剩余课时）


class LessonRecord(Base):
    __tablename__ = "lesson_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id"), index=True
    )
    record_type: Mapped[str] = mapped_column(
        Enum(LessonRecordType, native_enum=False, length=16), index=True
    )
    delta: Mapped[Decimal] = mapped_column(Numeric(10, 1))  # 正=入账，负=扣减（支持半课时）
    balance_after: Mapped[Decimal] = mapped_column(Numeric(10, 1))
    # 计价口径（人工调整/充值补课时用；为空表示无金额、不进财务账本）
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)  # 关联排课/订单（M2/M5 填充）
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped["Student"] = relationship()
    operator: Mapped["User | None"] = relationship()


class OrderStatus(enum.StrEnum):
    PENDING = "pending"        # 待支付
    PAID = "paid"              # 已支付（待确认到账，模拟支付）
    CONFIRMED = "confirmed"    # 已到账（课时已入账）
    CANCELLED = "cancelled"    # 已取消
    REFUNDED = "refunded"      # 已退款


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lesson_packages.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(
        Enum(OrderStatus, native_enum=False, length=16), default=OrderStatus.PENDING, index=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 待支付过期时间（下单 +5 分钟）；过期未支付自动撤销
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped["Student"] = relationship()
    package: Mapped["LessonPackage | None"] = relationship()
    refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    refund_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
