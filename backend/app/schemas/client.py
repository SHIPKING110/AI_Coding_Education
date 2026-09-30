import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enrollment import ClassBrief, PageOut
from app.schemas.feedback import FeedbackOut

# ---------- 客户端·主页/学员 ----------

class ClientStudentOut(BaseModel):
    """客户端视角的学员（家长=绑定全部孩子；学员账号=自己）。"""

    id: uuid.UUID
    name: str
    phone: str | None
    lesson_balance: float
    low_balance: bool = False  # 课时 <= 10 爆红提醒（FR-CL-01）
    status: str
    classes: list[ClassBrief] = Field(default_factory=list)
    # 最近一节即将开始的课（上课提醒卡）
    next_schedule: "ClientScheduleBrief | None" = None
    # 课堂作业入学提醒：未绑定学员账号时客户端引导联系教务补建
    has_student_account: bool = True

    model_config = ConfigDict(from_attributes=True)


class ClientScheduleBrief(BaseModel):
    """排课摘要（客户端展示：上课提醒/课表）。"""

    id: uuid.UUID
    class_name: str | None = None
    subject: str | None = None
    teacher_name: str | None = None
    start_time: datetime
    end_time: datetime
    status: str

    model_config = ConfigDict(from_attributes=True)


class ClientMeOut(BaseModel):
    """客户端首页：当前账号 + 名下学员（家长/学员视角）。"""

    id: uuid.UUID
    role: str
    name: str
    username: str
    campus: str | None = None
    students: list[ClientStudentOut] = Field(default_factory=list)
    unread_notifications: int = 0


# ---------- 客户端·课时流水 ----------

class ClientLessonRecordOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    record_type: str  # recharge/consume/adjust
    delta: float
    balance_after: float
    ref_id: uuid.UUID | None
    remark: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- 客户端·课时包/订单 ----------

class ClientPackageOut(BaseModel):
    """客户端展示的课时包（仅上架 active，FR-CL-04）。"""

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
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    """客户端订阅下单（FR-CL-05）：选择孩子 + 课时包。"""

    student_id: uuid.UUID
    package_id: uuid.UUID


class OrderOut(BaseModel):
    """订单（FR-CL-08：待支付/已支付(待确认)/已到账/已取消/已退款）。"""

    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str | None = None
    student_campus: str | None = None
    package_id: uuid.UUID | None = None
    package_name: str | None = None
    amount: Decimal
    status: str
    paid_at: datetime | None = None
    confirmed_at: datetime | None = None
    expires_at: datetime | None = None
    refund_amount: Decimal | None = None
    refund_note: str | None = None
    refunded_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- 客户端·作业 ----------

class ClientQuestionOut(BaseModel):
    """客户端看到的题目。

    作答前不含 answer/analysis（防作弊）；提交/批改后按题型返回
    可读的参考答案（选项转文字）与解析（reference_answer/reference_analysis）。
    """

    order_no: int
    type: str
    stem: str
    options: list | None
    difficulty: int
    language: str | None = None
    # 提交后展示（未提交为 None）：
    reference_answer: object | None = None      # 参考答案（选项已转为可读文本）
    reference_analysis: str | None = None       # 答案解析（通俗易懂）


class ClientSubmissionOut(BaseModel):
    """我的作答/提交（断点续做，FR-CL-12/13；判题结果 FR-CL-18）。"""

    id: uuid.UUID
    assignment_id: uuid.UUID
    student_id: uuid.UUID
    answers: dict | None = None          # 题号(字符串) -> 答案
    judge_results: dict | None = None    # 题号 -> {correct, expected, actual, ...}
    score: int | None = None
    total: int | None = None
    passed: bool | None = None
    passing_score: int | None = None
    status: str  # not_submitted/submitted/graded
    submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClientAssignmentListItem(BaseModel):
    """客户端作业列表项（FR-CL-09：已发布给本班、未过截止时间；附我的作答状态）。"""

    id: uuid.UUID
    title: str
    mode: str = "homework"
    description: str | None
    deadline: datetime | None
    teacher_name: str | None = None
    class_names: list[str] = Field(default_factory=list)
    question_count: int = 0
    passing_score: int | None = None
    # 我的作答状态（无提交记录时 status=not_submitted）
    my_status: str = "not_submitted"
    my_score: int | None = None
    my_total: int | None = None
    my_passed: bool | None = None
    submitted_at: datetime | None = None
    answered_count: int = 0
    published_at: datetime | None = None


class ClientAssignmentDetail(BaseModel):
    """客户端作业详情：题目清单（无答案）+ 我的提交进度。"""

    id: uuid.UUID
    title: str
    mode: str = "homework"
    description: str | None
    deadline: datetime | None
    published_at: datetime | None
    teacher_name: str | None = None
    class_names: list[str] = Field(default_factory=list)
    questions: list[ClientQuestionOut] = Field(default_factory=list)
    submission: ClientSubmissionOut | None = None


class ClientAnswersSave(BaseModel):
    """客户端保存答案（FR-CL-12 自动保存 / FR-CL-13 手动保存）。"""

    answers: dict[str, object]
    # 若 deadline 已过则拒绝保存（后端判定，BR-06）


class ClientSubmitIn(BaseModel):
    """客户端提交（FR-CL-16）：全部题目作答完成才可提交。

    空题由后端校验并返回未作答题号（最小题号优先跳转，FR-CL-15）。
    """

    answers: dict[str, object]


class ClientSubmitOut(BaseModel):
    """提交结果：判题汇总（客观题自动判，编程题待教师批改）。"""

    submission: ClientSubmissionOut
    empty_questions: list[int] = Field(default_factory=list)   # 未作答题号
    judged_count: int = 0               # 自动判题完成题数
    pending_manual: int = 0             # 待教师批改题数（编程题）
    message: str = ""


# ---------- 客户端·通知 ----------

class ClientUnreadOut(BaseModel):
    count: int = 0


class ClientEvaluationOut(BaseModel):
    """客户端（家长/学员）看到的学员评估（仅 published，剔除内部字段）。

    不含 teacher_id/student_id/ai_draft 等内部数据；content/stats/ppt_url 供
    评估详情弹窗（EvaluationDetailDialog）与家长会 PPT 下载展示。
    """

    id: uuid.UUID
    title: str | None = None
    teacher_name: str | None = None
    period_start: str
    period_end: str
    content: dict
    stats: dict | None = None
    ppt_url: str | None = None
    status: str
    published_at: datetime | None = None


# 分页别名
ClientFeedbackPage = PageOut[FeedbackOut]
ClientOrderPage = PageOut[OrderOut]
ClientEvaluationPage = PageOut[ClientEvaluationOut]
