import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PageOut[T](BaseModel):
    """统一分页响应：items + total。"""

    items: list[T]
    total: int
    limit: int
    offset: int


# ---------- 学员 ----------


class StudentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    campus: str | None = Field(default=None, max_length=64, description="所属校区")
    parent_user_id: uuid.UUID | None = None
    # 学员本人登录账号（M5 客户端：学员角色自己登录做题）
    student_user_id: uuid.UUID | None = None
    lesson_balance: float = Field(default=0, ge=0)
    # 新生入学选购课时包：传 package_id 则按课时包充值（生成已确认订单+充值流水，
    # 使排课扣课后财务账本能按 FIFO 单价计入创收）；此时忽略 lesson_balance
    package_id: uuid.UUID | None = Field(default=None, description="新生选购的课时包id")
    # 生源标记（报名时可标口碑+介绍人，转介绍提成依据）
    source: str | None = Field(default=None, description="normal/referral")
    referrer: str | None = Field(default=None, max_length=64, description="介绍人")
    class_ids: list[uuid.UUID] = Field(default_factory=list)


class StudentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    campus: str | None = Field(default=None, max_length=64)
    parent_user_id: uuid.UUID | None = None
    student_user_id: uuid.UUID | None = None
    class_ids: list[uuid.UUID] | None = None


class StudentClassesUpdate(BaseModel):
    """调整学员班级归属。教师调用时只影响本人所带班级的成员关系，其余保持不变。"""

    class_ids: list[uuid.UUID] = Field(default_factory=list)


class ClassBrief(BaseModel):
    id: uuid.UUID
    name: str
    subject: str
    teacher_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class StudentOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    campus: str | None = None
    parent_user_id: uuid.UUID | None
    student_user_id: uuid.UUID | None = None
    lesson_balance: float
    # 欠费估算（余额为负时：欠课时数与按最近购包价估算的欠款金额；路由层填充）
    arrears_lessons: float = 0
    arrears_amount: str | None = None
    # 体验标记/生源（体验课链路）
    trial_status: str = "none"
    source: str = "normal"
    referrer: str | None = None
    follow_up_status: str = "pending"
    follow_up_at: datetime | None = None
    follow_up_note: str | None = None
    stop_note: str | None = None
    status: str
    low_balance: bool = False  # 课时 <= 10 爆红标记（路由层计算填充）
    classes: list[ClassBrief] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StudentFollowUpUpdate(BaseModel):
    """催缴跟进状态更新：待跟进 -> 已续费 / 已停课。"""

    follow_up_status: str = Field(description="renewed | stopped | pending")
    note: str | None = Field(default=None, max_length=256)


class StudentStatusUpdate(BaseModel):
    """学员在读状态变更：停课 / 恢复在读。

    停课（stopped）必须填写备注（stop_note），便于教务与学生家长沟通恢复复课。
    """

    status: str = Field(description="active=恢复在读 | stopped=停课")
    stop_note: str | None = Field(
        default=None, max_length=256, description="停课备注（停课时必填）"
    )


class StudentRenewIn(BaseModel):
    """催缴续费：选择课时包（package_id）或自定义课时/金额（custom_*），二选一。"""

    package_id: uuid.UUID | None = Field(
        default=None, description="课时包 id（选择课包续费时必填）"
    )
    custom_lessons: float | None = Field(
        default=None, gt=0, description="自定义补充课时（不使用课包时必填）"
    )
    custom_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=10,
        decimal_places=2,
        description="自定义金额（元，机动定价）",
    )
    note: str | None = Field(default=None, max_length=256, description="跟进备注")


class StudentRefundIn(BaseModel):
    """学员退费：仅需备注，系统按 FIFO 自动计算退款明细。"""

    note: str = Field(min_length=1, max_length=256, description="退费备注")


# ---------- 班级 ----------


class ClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=64)
    teacher_id: uuid.UUID | None = None
    start_date: date | None = None


class ClassUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    subject: str | None = Field(default=None, min_length=1, max_length=64)
    teacher_id: uuid.UUID | None = None
    start_date: date | None = None


class ClassOut(BaseModel):
    id: uuid.UUID
    name: str
    subject: str
    teacher_id: uuid.UUID | None
    teacher_name: str | None = None
    start_date: date | None
    status: str
    student_count: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClassStudentOut(BaseModel):
    id: uuid.UUID
    name: str
    campus: str | None = None
    phone: str | None = None
    lesson_balance: float = 0
    status: str
    follow_up_status: str = "pending"
    classes: list[ClassBrief] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ClassDetailOut(ClassOut):
    students: list[ClassStudentOut] = Field(default_factory=list)


# ---------- 课时包 ----------


class LessonPackageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    total_lessons: int = Field(gt=0)
    cover_image: str | None = Field(default=None, max_length=255)
    subject_id: uuid.UUID | None = Field(default=None, description="学科科目")
    tag: str = Field(default="regular", description="regular=常规课 | activity=活动课")
    sale_start: datetime | None = Field(default=None, description="活动包售卖开始")
    sale_end: datetime | None = Field(default=None, description="活动包售卖结束")


class LessonPackageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    total_lessons: int | None = Field(default=None, gt=0)
    cover_image: str | None = Field(default=None, max_length=255)
    status: str | None = None
    subject_id: uuid.UUID | None = None
    subject_id_set: bool = Field(default=False, description="是否更新科目（含清空）")
    tag: str | None = None
    sale_start: datetime | None = None
    sale_end: datetime | None = None


class LessonPackageOut(BaseModel):
    id: uuid.UUID
    name: str
    price: Decimal
    total_lessons: int
    subject_id: uuid.UUID | None = None
    subject_name: str | None = None
    tag: str = "regular"
    sale_start: datetime | None = None
    sale_end: datetime | None = None
    published_at: datetime | None = None
    paid_students: int = 0
    cover_image: str | None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- 课时流水 ----------


class LessonRecordIn(BaseModel):
    """管理员/教务调整课时（充值入账或人工扣减，支持半课时）。"""

    delta: float = Field(description="正数=入账，负数=扣减，不可为 0")
    remark: str | None = None
    # 单价（元/课时）：调增补课时必填以计入财务；调减冲销可填（负金额冲账），不填则只调数量
    unit_price: float | None = Field(default=None, ge=0, description="单价元/课时")


class LessonRecordOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    record_type: str
    delta: float
    balance_after: float
    unit_price: float | None = None
    amount: float | None = None
    ref_id: uuid.UUID | None
    remark: str | None
    operator_name: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
