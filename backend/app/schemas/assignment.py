import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

QuestionTypeLit = Literal[
    "single_choice", "multiple_choice", "judgement", "code_fill", "programming"
]

# 作业状态：draft=草稿（未发布，可编辑）/ published=已发布（M5 客户端接收作答）
# 提交状态（M5 用，M4 建表预留）：not_submitted/submitted/graded
AssignmentStatusLit = Literal["draft", "published"]

# 作业模式：classwork=课堂作业（答案默认收起，仅发学员账号）/ homework=课后作业（常规班级发布）
AssignmentModeLit = Literal["classwork", "homework"]


# ---------- 题目 ----------

class QuestionIn(BaseModel):
    """题目（创建/编辑共用）：type 题型枚举；不同题型字段约定见 Question 模型。"""

    type: QuestionTypeLit
    stem: str = Field(min_length=1, max_length=4000, description="题干")
    options: list[str] | None = Field(
        default=None, description="选择题选项（单选/多选用；其余题型为空）"
    )
    answer: object | None = Field(
        default=None,
        description="参考答案：单选=int（选项索引）；多选=list[int]；判断=bool；"
        "代码填空/编程题=str（参考答案/参考代码）",
    )
    analysis: str | None = Field(default=None, max_length=4000, description="答案解析")
    difficulty: int = Field(
        default=1, ge=1, le=10, description="难度 1-10（对应少儿编程考级等级）"
    )
    test_cases: list[dict] | None = Field(
        default=None,
        description="编程题自动判题用例 [{'input': '...', 'output': '...'}]"
        "（M4 仅录入，判题引擎 M5）",
    )
    language: str | None = Field(
        default=None, max_length=16, description="编程题语言：python / cpp"
    )


class QuestionOut(BaseModel):
    id: uuid.UUID
    order_no: int
    type: str
    stem: str
    options: list | None
    answer: object | None
    analysis: str | None
    difficulty: int
    test_cases: list | None
    language: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QuestionBankItem(BaseModel):
    """历史题库条目（M4.2 复用历史题）：题目 + 所属作业标题。

    供 AI 出题弹窗「复用历史题」搜索/筛选后勾选加入新作业。
    """

    id: uuid.UUID
    assignment_id: uuid.UUID
    assignment_title: str
    order_no: int
    type: str
    stem: str
    options: list | None
    answer: object | None
    analysis: str | None
    difficulty: int
    test_cases: list | None
    language: str | None
    created_at: datetime
    updated_at: datetime


class QuestionBankPage(BaseModel):
    items: list[QuestionBankItem]
    total: int


class QuestionUpdate(BaseModel):
    """编辑单题：全部字段可选，仅更新提供的字段。"""

    type: QuestionTypeLit | None = None
    stem: str | None = Field(default=None, min_length=1, max_length=4000)
    options: list[str] | None = None
    answer: object | None = None
    analysis: str | None = Field(default=None, max_length=4000)
    difficulty: int | None = Field(default=None, ge=1, le=10)
    test_cases: list[dict] | None = None
    language: str | None = Field(default=None, max_length=16)


class QuestionReorderIn(BaseModel):
    """题目排序：按 id 顺序重排（order_no = 列表下标 + 1）。"""

    question_ids: list[uuid.UUID] = Field(min_length=1)


class QuestionsPoolItem(BaseModel):
    """历史题目池条目：已发布作业中的一道题（含所属作业标题，供教师快速识别复用）。"""

    id: uuid.UUID
    assignment_id: uuid.UUID
    assignment_title: str
    order_no: int
    type: str
    stem: str
    options: list | None
    answer: object | None
    analysis: str | None
    difficulty: int
    test_cases: list | None
    language: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------- 作业 ----------

class AssignmentCreate(BaseModel):
    """新建作业（草稿）：标题 + 说明 + 可选班级/截止时间 + 题目列表。"""

    title: str = Field(min_length=1, max_length=160)
    mode: AssignmentModeLit = Field(default="homework", description="作业模式：classwork=课堂作业/homework=课后作业")
    description: str | None = Field(default=None, max_length=4000, description="作业说明/知识点")
    class_id: uuid.UUID | None = Field(default=None, description="发布目标班级（草稿可为空）")
    deadline: datetime | None = Field(default=None, description="完成时间（可选，服务器时间判定）")
    type_scores: dict[str, int] | None = Field(default=None, description="题型分值配置")
    passing_score: int | None = Field(default=None, ge=0, description="达标分数")
    review_mode: str | None = Field(default=None, description="批改模式覆盖：auto/teacher_confirm")
    review_mode: str = Field(default="auto", description="批改模式：auto直接公布/teacher_confirm批改后公布")
    questions: list[QuestionIn] = Field(default_factory=list)


class AssignmentUpdate(BaseModel):
    """更新作业（草稿）：标题/说明/班级/截止时间。题目单独管理。"""

    title: str | None = Field(default=None, min_length=1, max_length=160)
    mode: AssignmentModeLit | None = Field(default=None, description="作业模式：classwork=课堂作业/homework=课后作业")
    description: str | None = Field(default=None, max_length=4000)
    class_id: uuid.UUID | None = None
    deadline: datetime | None = None
    type_scores: dict[str, int] | None = None
    passing_score: int | None = Field(default=None, ge=0)


class AssignmentPublishIn(BaseModel):
    """发布作业（可多班级/按学员发布）：可同时发布到多个班级或定向学员。

    - 课堂作业（classwork）可仅指定学员发布，此时 class_ids 允许为空
    - 已发布过的班级自动跳过；若所选班级全部已发布且无定向学员变更会返回 400 提示
    - deadline 可选；已发布作业再次调用=追加发布新班级/学员
    - type_scores/passing_score：发布时生效的题型分值配置与达标线
    - target_student_ids：补练/课堂作业定向学员（仅对指定学员可见）
    """

    class_ids: list[uuid.UUID] = Field(
        default_factory=list, description="目标班级列表（课堂按学员发布时可为空）"
    )
    deadline: datetime | None = Field(default=None, description="完成时间（可选）")
    type_scores: dict[str, int] | None = Field(default=None, description="题型分值配置")
    passing_score: int | None = Field(default=None, ge=0, description="达标分数")
    review_mode: str | None = Field(default=None, description="批改模式覆盖：auto/teacher_confirm")
    target_student_ids: list[uuid.UUID] | None = Field(
        default=None, description="定向补练/课堂学员（仅这些学员可见）"
    )
    notify_parents: bool = Field(
        default=True, description="是否同时通知家长账号（课堂作业可关闭，仅通知学员）"
    )


class AssignmentOut(BaseModel):
    id: uuid.UUID
    teacher_id: uuid.UUID
    teacher_name: str | None = None
    class_id: uuid.UUID | None
    class_name: str | None = None
    title: str
    mode: str = "homework"
    description: str | None
    deadline: datetime | None
    status: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    question_count: int = 0
    type_scores: dict[str, int] | None = None
    passing_score: int | None = None
    review_mode: str = "auto"
    total_score: int | None = None
    passed: bool | None = None
    # 已发布班级（多班级发布，M4.1）：class_id 为主目标，published_class_ids 为全部已发布班级
    published_class_ids: list[uuid.UUID] = Field(default_factory=list)
    published_class_names: list[str] = Field(default_factory=list)
    # 定向补练作业（target_student_ids 非空时，仅这些学员可见）
    target_student_ids: list[uuid.UUID] = Field(default_factory=list)
    target_student_names: list[str] = Field(default_factory=list)
    # 教师端列表用：待批改份数（status=submitted）
    pending_review: int = 0
    pending_review_count: int = 0
    submitted_count: int = 0
    # 自定义分组（可为空 = 未分组）
    folder_id: uuid.UUID | None = None
    folder_name: str | None = None
    questions: list[QuestionOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AssignmentFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="分组名称")
    sort_no: int = Field(default=0, ge=0, le=9999, description="排序，越小越靠前")


class AssignmentFolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    sort_no: int | None = Field(default=None, ge=0, le=9999)


class AssignmentFolderOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    sort_no: int
    assignment_count: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssignmentFolderMoveIn(BaseModel):
    assignment_ids: list[uuid.UUID] = Field(min_length=1, description="要移入分组的作业 id 列表")


# ---------- AI 出题 ----------

class AiGenerateIn(BaseModel):
    """AI 出题参数（FR-AI-01/FR-AI-04）。

    - mode=similar 举一反三：基于 source_question 生成相似题
    - mode=homework 作业模式：基于知识点提示语 hint 生成整套题目
    """

    mode: Literal["similar", "homework"]
    count: int = Field(
        default=3, ge=1, le=10, description="题数：指定题型时每种题型各生成 count 题（作业模式）"
    )
    difficulty: int = Field(default=3, ge=1, le=10, description="难度 1-10（对应少儿编程考级等级）")
    source_question: str | None = Field(
        default=None, max_length=4000, description="举一反三：原题题干/参考题目"
    )
    source_answer: str | None = Field(
        default=None, max_length=4000, description="举一反三：原题参考答案/解析（可选）"
    )
    hint: str | None = Field(default=None, max_length=1000, description="提示语/知识点（作业模式）")
    types: list[QuestionTypeLit] | None = Field(
        default=None, description="指定题型（作业模式可选；不指定由 AI 按知识点合理分配）"
    )


class AiGenerateOut(BaseModel):
    """AI 生成结果：题目列表（含答案/解析，前端回填模板窗口人工编辑）。"""

    questions: list[QuestionIn]
    model: str | None = None


class AiTaskOut(BaseModel):
    """AI 生成/优化异步任务（M4 增强，task-cancel-recover 扩展终态）：

    - status: pending（排队）/ running（生成中）/ done（完成）/ failed（失败）/ cancelled（已取消）
    - stage: 当前阶段描述（前端任务卡展示）
    - result: 完成后的结果——generate 为题目列表，refine 为单题；未完成/失败为 null
    - 说明：result 放宽为 Any，避免班级 PPT 等其他任务类型复用同一内存任务表时
      因结构不同触发 500；习题前端仅消费 generate/refine 两种 kind
    """

    id: str
    owner_id: str
    kind: str  # generate | refine
    summary: str
    status: str
    stage: str | None
    result: Any | None = None
    model: str | None = None
    error: str | None = None
    created_at: str
    started_at: str | None
    finished_at: str | None


class AiRefineIn(BaseModel):
    """对话优化单题（FR-AI-05）：基于原题 + 教师修改要求重新生成。"""

    question: QuestionIn = Field(description="当前题目内容")
    instruction: str = Field(
        min_length=1, max_length=1000, description="修改要求，如：难度调低、换成生活中的例子"
    )


class AiRefineOut(BaseModel):
    """对话优化结果：重新生成的题目（同字段结构）。"""

    question: QuestionIn
    model: str | None = None
