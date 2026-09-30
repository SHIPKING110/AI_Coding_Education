import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReportTypeLit = Literal["daily", "weekly", "quarterly", "yearly"]


class ReportCreate(BaseModel):
    """新建/幂等创建报告（日报：period_start==period_end 为当日；周报：周一~周日）。"""

    type: ReportTypeLit
    period_start: datetime
    period_end: datetime
    title: str | None = Field(default=None, max_length=160)
    content: dict = Field(default_factory=dict)
    stats: dict | None = None


class ReportUpdate(BaseModel):
    """编辑报告内容（status/周期不可改，由专用接口负责发布/撤回）。"""

    title: str | None = Field(default=None, max_length=160)
    content: dict | None = None
    stats: dict | None = None


class ReportOut(BaseModel):
    id: uuid.UUID
    type: str
    teacher_id: uuid.UUID
    teacher_name: str | None = None
    period_start: datetime
    period_end: datetime
    title: str | None
    content: dict
    stats: dict | None
    ppt_url: str | None = None
    status: str
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WeeklyStatsOut(BaseModel):
    """周报自动统计指标（FR-WR-01/02）：与排课/考勤/学员数据口径一致。

    - 排课节数 schedules = 本周非取消排课数（含待上/已完成）
    - 应到学员人次 expected_attendance = 本周各排课对应班级在册学员数之和
    - 上课人次 attended / 缺课人次 leave（按本周排课中的考勤标记统计）
    - 出勤率 attendance_rate = 上课人次 / 应到人次
    - 应消耗课时 expected_lessons = 应到人次×2（请假不计入实耗）
    - 消耗课时 consumed_lessons = 已到人次×2（同考勤划课时）
    - 达标率 achievement_rate = 消耗课时 / 应消耗课时
    """

    schedules: int = 0  # 本周排课节数（非取消，含待上/已完成）
    expected_attendance: int = 0  # 应到学员人次（各排课班级在册学员数之和）
    attended: int = 0  # 上课人次
    leave: int = 0  # 缺课人次（请假）
    attendance_rate: float = 0.0  # 出勤率 = attended / expected_attendance
    absent_students: list[str] = Field(default_factory=list)  # 缺课学员名单（去重）
    new_students: int = 0  # 新增学员数（本周创建，在读）
    expected_lessons: int = 0  # 应消耗课时（应到人次×2）
    consumed_lessons: int = 0  # 实际消耗课时（已到人次×2，请假不计）
    achievement_rate: float = 0.0  # 达标率 = consumed_lessons / expected_lessons


class DailyStatsOut(BaseModel):
    """日报自动统计（单日，口径同周报）：排课/应到/到课/缺课/出勤/达标/应耗与实耗课时。"""

    schedules: int = 0  # 当日排课节数（非取消，含待上/已完成）
    expected_attendance: int = 0  # 应到学员人数（各排课班级在册学员数之和）
    attended: int = 0  # 上课学员人数
    leave: int = 0  # 缺课人次（请假）
    attendance_rate: float = 0.0  # 出勤率 = attended / expected_attendance
    expected_lessons: int = 0  # 应消耗课时（应到人数×2）
    consumed_lessons: int = 0  # 实际消耗课时（已到人数×2，请假不计）
    achievement_rate: float = 0.0  # 达标率 = consumed_lessons / expected_lessons


class PeriodStatsOut(BaseModel):
    """季度/年度总结自动统计（FR-QS/FR-YS）。

    - 教学量：schedules/attended/leave/attendance_rate
    - 规模：current_students 当前学员数；new_students 新增学员数
    - 课时与达标：expected_lessons 应耗课时 / consumed_lessons 消耗课时 / achievement_rate 达标率
    - 其他：weekly_count 已发布周报数
    说明：缺课学员明细不再进入期间统计（放回日报/周报展示），保留字段仅用于素材/兼容。
    """

    schedules: int = 0  # 期间已完成排课数
    attended: int = 0  # 上课人次
    leave: int = 0  # 缺课人次
    attendance_rate: float = 0.0  # 出勤率
    absent_students: list[str] = Field(default_factory=list)  # 缺课学员名单（兼容，日报/周报展示）
    new_students: int = 0  # 新增学员数
    weekly_count: int = 0  # 期间已发布周报数
    current_students: int = 0  # 期间末该教师名下班在读学员数
    expected_lessons: int = 0  # 应耗课时（应开庭次）
    consumed_lessons: int = 0  # 消耗课时（已上庭次）
    achievement_rate: float = 0.0  # 达标率 = 消耗课时 / 应耗课时
    quarterly_count: int = 0  # 年度口径：已纳入聚合的已发布季度总结篇数（季度口径为 0）


class ReportBoardItemOut(BaseModel):
    """公栏报告条目：已发布报告 + 汇报教师姓名/校区/教师ID。"""

    id: uuid.UUID
    type: str
    teacher_id: uuid.UUID
    teacher_name: str | None = None
    campus: str | None = None
    period_start: datetime
    period_end: datetime
    title: str | None
    content: dict
    stats: dict | None
    ppt_url: str | None = None
    published_at: datetime | None = None


class ReportBoardStatsOut(BaseModel):
    """公栏数据统计：按在职教师 + 周期。"""

    teacher_count: int = 0  # 在职教师数（统计口径）
    daily_due: int = 0  # 日报应提交（教师数 × 天数）
    daily_submitted: int = 0  # 日报已提交（published）
    weekly_due: int = 0  # 周报应提交（教师数 × 周数）
    weekly_submitted: int = 0  # 周报已提交（published）


class PeriodMonthlyPoint(BaseModel):
    """期间逐月数据（折线图）：应耗课时/消耗课时/新增学员/上课人次。"""

    month: str  # YYYY-MM
    expected_lessons: int = 0
    consumed_lessons: int = 0
    new_students: int = 0
    attendance: int = 0


class PeriodComparison(BaseModel):
    """期间课时消耗对比（柱状图）：当前 vs 上一对等期间逐月。"""

    labels: list[str] = Field(default_factory=list)  # 当前期间月份标签
    current: list[int] = Field(default_factory=list)  # 当前逐月消耗课时
    previous_labels: list[str] = Field(default_factory=list)  # 上一期间月份标签
    previous: list[int] = Field(default_factory=list)  # 上一期间逐月消耗课时


class ReportPptOut(BaseModel):
    """生成季度/年度 PPT 草稿的产物信息。"""

    ppt_url: str
    title: str | None = None


class ReportPptIn(BaseModel):
    """PPT 生成选项：按需勾选正文要点入页（默认全选）。

    - include_sections：要点类字段（highlights/problems/next_plan）中勾选入页的条目下标；
      key 不存在表示该字段全部入页；空列表表示该字段整段跳过。
    - 散文类（summary/stats_notes）始终整段入页；数字类始终走表与图。
    """

    include_sections: dict[str, list[int]] | None = Field(
        default=None, description="要点字段 -> 勾选入页的条目下标（从 0 起）"
    )


class ReportAiDraftIn(BaseModel):
    """AI 生成报告草稿（日报：基于当日排课/考勤/反馈；周报：基于本周汇总）。

    年度总结可选 `source_quarter_ids`：指定参与聚合的已发布季度总结 id；
    不传则自动取本年度全部已发布季度总结。
    """

    extra_note: str | None = Field(default=None, max_length=1000, description="教师补充说明/重点")
    source_quarter_ids: list[uuid.UUID] | None = Field(
        default=None, description="年度总结素材来源：已发布季度总结 id 列表（仅 yearly 有效）"
    )


class ReportAiDraftOut(BaseModel):
    """AI 生成的报告草稿：回填对应字段，人工编辑后保存。"""

    title: str | None = None
    content: dict = Field(default_factory=dict)
    model: str | None = None


class AiDraftJobOut(BaseModel):
    """提交 AI 草稿异步任务后的返回：凭 job_id 轮询任务状态。"""

    job_id: str
    status: str = "pending"


class AiDraftJobStatusOut(BaseModel):
    """AI 草稿任务状态：pending/running/succeeded/failed，成功时带 draft。"""

    job_id: str
    report_id: uuid.UUID
    report_type: str
    status: str
    title: str | None = None
    content: dict | None = None
    model: str | None = None
    error: str | None = None
    created_at: float
    finished_at: float | None = None
    elapsed_seconds: float = 0.0


class PptChatIn(BaseModel):
    """对话式 PPT 定制：一轮请求的上下文（会话状态由前端持有并回传）。"""

    stage: Literal["outline", "copy", "layout", "chat"] = "chat"
    message: str = Field(default="", max_length=2000)
    outline: list[dict] = Field(default_factory=list)
    sections: list[dict] = Field(default_factory=list)
    conversation_id: str | None = Field(default=None, description="绑定工作台会话则持久化消息并注入记忆")


class PptBuildIn(BaseModel):
    """按对话确认的规格构建 PPT。"""

    title: str | None = Field(default=None, max_length=160)
    theme: Literal["brand", "cyan", "deep"] = "brand"
    slides: list[dict] = Field(default_factory=list)
