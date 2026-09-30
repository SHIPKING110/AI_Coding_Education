import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FeedbackCreate(BaseModel):
    """新增课后反馈（单学员）。"""

    schedule_id: uuid.UUID
    student_id: uuid.UUID
    title: str | None = Field(default=None, max_length=280)
    topic: str | None = Field(default=None)
    content: str | None = Field(default=None)
    performance: str | None = Field(default=None)
    evaluation: str | None = Field(default=None)
    homework: str | None = Field(default=None)
    media_urls: list[str] = Field(default_factory=list)


class FeedbackUpdate(BaseModel):
    """编辑课后反馈（含批量学员时共享的课程字段）。"""

    title: str | None = Field(default=None, max_length=280)
    topic: str | None = None
    content: str | None = None
    performance: str | None = None
    evaluation: str | None = None
    homework: str | None = None
    media_urls: list[str] | None = None


class FeedbackPublishIn(BaseModel):
    """发布（发送给家长）：草稿 -> 已发布。"""

    pass


class FeedbackAIEnhanceIn(BaseModel):
    """调用 AI 基于当前内容生成/润色反馈草稿。字段为当前已有内容，作为生成输入。"""

    title: str | None = None
    topic: str | None = None
    content: str | None = None
    performance: str | None = None
    evaluation: str | None = None
    homework: str | None = None
    template_id: uuid.UUID | None = None  # 选用的提示词模板；不传则用系统默认模板


class FeedbackDraftOut(BaseModel):
    """AI 生成的反馈草稿（各维度文案），前端回填输入框供人工编辑。"""

    title: str | None = None
    topic: str | None = None
    content: str | None = None
    performance: str | None = None
    evaluation: str | None = None
    homework: str | None = None
    model: str | None = None  # 生成所用模型名


class FeedbackOut(BaseModel):
    id: uuid.UUID
    schedule_id: uuid.UUID
    student_id: uuid.UUID
    student_name: str | None = None
    class_name: str | None = None
    schedule_time: datetime | None = None
    title: str | None
    topic: str | None
    content: str | None
    performance: str | None
    evaluation: str | None = None
    homework: str | None
    media_urls: list[str]
    status: str
    published_at: datetime | None = None
    ai_draft: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UploadOut(BaseModel):
    url: str
    filename: str


class FeedbackEditorRow(BaseModel):
    """反馈编辑器的一行：某学员的考勤状态 + 已存在的反馈。"""

    student_id: uuid.UUID
    student_name: str | None = None
    attendance_status: str = "unmarked"  # attended | leave | unmarked
    feedback: FeedbackOut | None = None


class FeedbackStats(BaseModel):
    """反馈统计（按校区/教师/班级/日期区间聚合）。"""

    schedule_count: int = 0  # 匹配的已完成排课数
    expected: int = 0  # 应到学员数量（考勤行数）
    attended: int = 0  # 签到学员数量
    leave: int = 0  # 请假学员数量
    feedback_done: int = 0  # 已反馈学员数量
    pending: int = 0  # 待反馈学员数量（签到但未反馈，请假不计入）


class CompletedScheduleOut(BaseModel):
    """已完成排课 + 反馈完成状态（用于排课下拉「待反馈/已反馈」标记）。"""

    id: uuid.UUID
    class_id: uuid.UUID
    class_name: str | None = None
    subject: str | None = None
    teacher_name: str | None = None
    campus: str | None = None
    start_time: datetime
    end_time: datetime
    attended: int = 0  # 签到学员数
    feedback_done: int = 0  # 已发送数（仅 published）
    saved_draft: int = 0  # 草稿数（draft）
    all_done: bool = False  # 是否全部签到学员均已发送

    model_config = ConfigDict(from_attributes=True)
