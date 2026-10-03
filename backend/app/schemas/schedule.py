import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreate(BaseModel):
    class_id: uuid.UUID | None = Field(default=None, description="班级id；体验课排教师空余时段时可空")
    teacher_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    force: bool = Field(default=False, description="为 true 时忽略冲突强制创建")
    is_trial: bool = Field(default=False, description="体验课：空时段专排体验课时打标")


class RecurringSlot(BaseModel):
    weekday: int = Field(ge=1, le=7, description="1=周一 ... 7=周日")
    start_time: str = Field(description="HH:MM 本地时间")
    duration_min: int = Field(default=90, ge=30, le=240)


class ScheduleRecurringCreate(BaseModel):
    """循环排课：每周 N 节 × 连续周次，直到排满 total_lessons 节。"""

    class_id: uuid.UUID
    teacher_id: uuid.UUID
    start_date: date = Field(description="起始日（含），第一周从该日所在周的匹配星期开始")
    slots: list[RecurringSlot] = Field(min_length=1, description="每周的排课时间段")
    total_lessons: int = Field(gt=0, description="班级要排的总节数（含本周已排）")
    force: bool = False


class ScheduleRecurringResponse(BaseModel):
    created: bool
    created_count: int = 0
    conflicts: list["ConflictOut"] = Field(default_factory=list)
    schedules: list["ScheduleOut"] = Field(default_factory=list)


class ScheduleUpdate(BaseModel):
    start_time: datetime | None = None
    end_time: datetime | None = None
    teacher_id: uuid.UUID | None = None
    force: bool = False


class ConflictOut(BaseModel):
    id: uuid.UUID
    class_name: str | None = None
    teacher_name: str | None = None
    start_time: datetime
    end_time: datetime
    status: str

    model_config = ConfigDict(from_attributes=True)


class ScheduleCreateResponse(BaseModel):
    schedule: "ScheduleOut | None" = None
    conflicts: list[ConflictOut] = Field(default_factory=list)
    created: bool


class ScheduleOut(BaseModel):
    id: uuid.UUID
    class_id: uuid.UUID | None = None
    class_name: str | None = None
    subject: str | None = None
    teacher_id: uuid.UUID
    teacher_name: str | None = None
    start_time: datetime
    end_time: datetime
    status: str
    is_trial: bool = False
    trial_status: str = "none"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AttendanceItemIn(BaseModel):
    student_id: uuid.UUID
    status: str = Field(description="attended | leave")


class AttendanceBatchIn(BaseModel):
    items: list[AttendanceItemIn]


class AttendanceOut(BaseModel):
    id: uuid.UUID
    schedule_id: uuid.UUID
    student_id: uuid.UUID
    student_name: str | None = None
    lesson_balance: float | None = None
    low_balance: bool = False
    status: str
    is_trial: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AttendanceBatchResult(BaseModel):
    updated: list[AttendanceOut] = Field(default_factory=list)
    lesson_records: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
