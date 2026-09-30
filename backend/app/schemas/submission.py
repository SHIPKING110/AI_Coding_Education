import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.assignment import QuestionOut


class SubmissionListItem(BaseModel):
    """教师端：某作业的提交列表项（FR-CL-18 批改入口）。"""

    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str | None = None
    # 学员归属信息（教师直接看到是谁/哪个班提交的）
    campus: str | None = None
    class_names: list[str] = Field(default_factory=list)
    status: str  # not_submitted/submitted/graded
    score: int | None = None
    total: int | None = None
    submitted_at: datetime | None = None
    # 客观题自动判得分 + 待人工批改题数
    auto_score: int = 0
    pending_manual: int = 0
    # 达标判定（设置了达标线的作业才有值）
    passing_score: int | None = None
    passed: bool | None = None

    model_config = ConfigDict(from_attributes=True)


class SubmissionDetail(BaseModel):
    """教师端：提交详情（学员答案 + 自动判题结果 + 题目，供批改）。"""

    id: uuid.UUID
    assignment_id: uuid.UUID
    student_id: uuid.UUID
    student_name: str | None = None
    answers: dict | None = None
    judge_results: dict | None = None
    score: int | None = None
    total: int | None = None
    passed: bool | None = None
    passing_score: int | None = None
    status: str
    submitted_at: datetime | None = None
    questions: list[QuestionOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SubmissionGradeIn(BaseModel):
    """教师批改：对编程题（及需要人工改的题）给定分数。

    scores: 题号(字符串) -> 分数（0 或 1，每题满分 1 分的整数给分）。
    """

    scores: dict[str, int] = Field(default_factory=dict, description="题号 -> 0 或 1")
    comment: str | None = Field(default=None, max_length=1000, description="整体批改评语")


class SubmissionGradeResult(BaseModel):
    """批改完成后的提交摘要。"""

    submission: SubmissionDetail
    score: int
    total: int
    status: str
    message: str = ""


class SubmissionStats(BaseModel):
    """教师端作业的提交统计（批改进度）。"""

    total_students: int = 0      # 该作业应作答学员总数（定向作业=定向学员数，常规=发布班级学员去重）
    submitted: int = 0           # 已提交
    graded: int = 0              # 已批改
    pending_review: int = 0      # 待批改（已提交未批改，教师端角标用）
    not_submitted: int = 0       # 未提交
    avg_score: float | None = None
    passing_score: int | None = None   # 达标线（未设置=None）
    below_pass: int = 0               # 已批改中未达标人数


class GradingCenterItem(BaseModel):
    """批改中心条目（跨作业聚合）：一行展示一份作业的提交/批改进度。"""

    assignment_id: uuid.UUID
    title: str
    mode: str = "homework"
    teacher_id: uuid.UUID | None = None
    teacher_name: str | None = None
    class_names: list[str] = Field(default_factory=list)
    deadline: datetime | None = None
    published_at: datetime | None = None
    total_students: int = 0      # 应作答学员数（定向=定向学员数，常规=发布班级去重）
    submitted: int = 0           # 已提交份数
    pending_review: int = 0      # 待批改份数
    graded: int = 0              # 已批改份数
    latest_submitted_at: datetime | None = None  # 最新一份提交时间（排序用）

    model_config = ConfigDict(from_attributes=True)
