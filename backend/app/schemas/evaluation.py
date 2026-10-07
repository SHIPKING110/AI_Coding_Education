import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EvaluationStatusLit = Literal["draft", "published"]


class EvaluationCreate(BaseModel):
    """新建/幂等创建评估：同一学员同一周期仅一份（重复创建 = 更新）。"""

    student_id: uuid.UUID
    period_start: date
    period_end: date
    title: str | None = Field(default=None, max_length=160)
    content: dict = Field(default_factory=dict)
    stats: dict | None = None


class EvaluationUpdate(BaseModel):
    """编辑评估（status/周期/学员不可改，发布/撤回由专用接口负责）。"""

    title: str | None = Field(default=None, max_length=160)
    content: dict | None = None
    stats: dict | None = None


class EvaluationOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str | None = None
    student_campus: str | None = None
    teacher_id: uuid.UUID
    teacher_name: str | None = None
    period_start: date
    period_end: date
    title: str | None
    content: dict
    stats: dict | None
    ai_draft: dict | None = None
    ppt_url: str | None = None
    status: str
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvaluationStatsOut(BaseModel):
    """学员周期统计（评估依据）：出勤/课时/反馈/作业，供素材预览卡展示。"""

    attended: int = 0
    leave: int = 0
    attendance_rate: float = 0.0
    consumed_lessons: int = 0
    feedback_count: int = 0
    homework_count: int = 0
    homework_score_rate: float | None = None


class EvaluationFeedbackItem(BaseModel):
    """素材中的已发布反馈条目（供预览核对 AI 依据）。"""

    date: str
    class_name: str | None = None
    topic: str | None = None
    content: str | None = None
    performance: str | None = None
    evaluation: str | None = None
    homework: str | None = None


class EvaluationMaterialOut(BaseModel):
    """评估素材预览：学员 + 周期统计 + 已发布反馈明细。"""

    student_id: uuid.UUID
    student_name: str
    classes: list[dict[str, Any]] = Field(default_factory=list)
    start: date
    end: date
    stats: EvaluationStatsOut
    feedbacks: list[EvaluationFeedbackItem] = Field(default_factory=list)


class EvaluationAiDraftIn(BaseModel):
    """AI 生成评估草稿（FR-EV-01）：基于周期素材，extra_note 供教师补充重点。"""

    extra_note: str | None = Field(
        default=None, max_length=1000, description="教师补充说明/想强调的重点"
    )
    style_guide: str | None = Field(
        default=None, max_length=8000, description="所选提示词模板正文，作为写作风格要求"
    )


class EvaluationAiRefineIn(BaseModel):
    """对话式优化（FR-EV-03）：提出修改要求，AI 在现有评估基础上重写。"""

    instruction: str = Field(min_length=1, max_length=1000, description="修改要求（可多轮追问）")


class EvaluationPptOut(BaseModel):
    """家长会 PPT 产物。"""

    ppt_url: str
    title: str | None = None


class ClassPptCreateIn(BaseModel):
    """班级家长会 PPT 生成入参：以班级为单位、结合全班学员评估生成。

    - force=false（默认）：素材无变化时直接 409 提示（需二次确认后 force=true 重提）
    - force=true：明确要求重提炼（会覆盖手工编辑内容），跳过去重拦截
    """

    class_id: uuid.UUID
    period_start: date
    period_end: date
    extra_note: str | None = Field(default=None, max_length=1000)
    force: bool = Field(default=False, description="素材无变化时是否强制重新提炼")


class ClassPptUpdateIn(BaseModel):
    """班级家长会 PPT 文案编辑：字段可选，保存后只需重排版，不再调用 LLM。"""

    title: str | None = Field(default=None, max_length=160)
    class_summary: str | None = None
    ability_comment: str | None = None
    highlights: str | None = None
    to_improve: str | None = None
    next_plan: str | None = None
    home_suggestions: str | None = None


class ClassPptOut(BaseModel):
    """班级家长会 PPT 落库记录：供预览 / 编辑 / 秒级重建。"""

    id: uuid.UUID
    class_id: uuid.UUID
    teacher_id: uuid.UUID
    period_start: date
    period_end: date
    title: str | None = None
    content: dict = Field(default_factory=dict)
    stats: dict | None = None
    averages: list | None = None
    honor_roll: list | None = None
    ppt_url: str | None = None
    material_hash: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClassRosterEvaluationOut(BaseModel):
    """班级名单中某学员在当前周期已生成的评估（状态摘要，供前端判断是否已生成）。"""

    id: uuid.UUID
    title: str | None
    status: str
    published_at: datetime | None = None


class ClassRosterStudentOut(BaseModel):
    """班级学员 + 该周期评估生成情况。"""

    student_id: uuid.UUID
    name: str
    campus: str | None = None
    lesson_balance: int = 0
    evaluation: ClassRosterEvaluationOut | None = None


class ClassRosterOut(BaseModel):
    """班级 + 周期学员名单：逐人标注是否已生成评估（草稿/已发布），供家长会 PPT 前查漏。"""

    class_id: uuid.UUID
    class_name: str
    subject: str
    teacher_name: str | None = None
    period_start: date
    period_end: date
    total: int
    generated: int = 0
    published: int = 0
    students: list[ClassRosterStudentOut] = Field(default_factory=list)
