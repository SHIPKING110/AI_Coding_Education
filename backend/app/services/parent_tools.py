"""家长客服查询工具（P1 只读三件套）：课时余额 / 未来课表 / 最近课后反馈。

数据权限（硬性，逐条）：
- 学生范围永远从登录家长反查（students_for_user），**绝不接受前端传 student_id**；
- 匿名用户不挂任何工具（路由层拦截）；
- 只 select 家长该看的字段：余额/消耗、课表时间地点教师、已 published 反馈；
  教师薪资、其他学员、内部备注、成本价不可达（本模块根本不 import 相关 crud）；
- 每次调用落账本 retrieval_diag（工具名+耗时），出事可回溯。

数字幻觉对策：工具返回确定性数字，生成层 prompt 要求原样透出，
输出后再校验答案数字 ⊆ 工具结果数字，否则作废转人工。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enrollment import StudentStatus
from app.models.feedback import Feedback, FeedbackStatus
from app.models.schedule import Schedule, ScheduleStatus
from app.models.user import User
from app.services import reminders


def _own_students(db: Session, user: User):
    """家长名下在读学员（归属反查；空 = 未绑定，不能查任何数据）。"""
    return reminders.students_for_user(db, user)


def tool_balance(db: Session, user: User) -> dict:
    """课时余额：每学员 姓名/校区/余额/低余额标记。"""
    t0 = time.time()
    rows = []
    for s in _own_students(db, user):
        rows.append({
            "student": s.name, "campus": s.campus or "",
            "balance": float(s.lesson_balance or 0),
            "low": bool((s.lesson_balance or 0) <= 10),
        })
    return {"tool": "balance", "ms": int((time.time() - t0) * 1000), "students": rows}


def tool_schedule(db: Session, user: User, *, days: int = 7) -> dict:
    """未来 N 天课表：学员/班级/科目/教师/起止时间（不含已取消）。"""
    t0 = time.time()
    out: list[dict] = []
    now = datetime.now()
    end = now + timedelta(days=max(1, min(days, 30)))
    for s in _own_students(db, user):
        class_ids = [c.id for c in (s.classes or [])]
        if not class_ids:
            continue
        rows = db.scalars(
            select(Schedule).where(
                Schedule.class_id.in_(class_ids),
                Schedule.status != ScheduleStatus.CANCELLED.value,
                Schedule.start_time >= now,
                Schedule.start_time <= end,
            ).order_by(Schedule.start_time.asc()).limit(20)
        ).all()
        for r in rows:
            out.append({
                "student": s.name,
                "class": r.schedule_class.name if r.schedule_class else "",
                "subject": r.schedule_class.subject if r.schedule_class else "",
                "teacher": r.teacher.name if r.teacher else "",
                "start": r.start_time.isoformat() if r.start_time else "",
                "end": r.end_time.isoformat() if r.end_time else "",
            })
    return {"tool": "schedule", "ms": int((time.time() - t0) * 1000), "items": out}


def tool_feedbacks(db: Session, user: User, *, limit: int = 3) -> dict:
    """最近已发布课后反馈摘要：学员/课程时间/老师评语前200字（仅 published）。"""
    t0 = time.time()
    out: list[dict] = []
    for s in _own_students(db, user):
        rows = db.scalars(
            select(Feedback).where(
                Feedback.student_id == s.id,
                Feedback.status == FeedbackStatus.PUBLISHED.value,
            ).order_by(Feedback.created_at.desc()).limit(limit)
        ).all()
        for fb in rows:
            text = (fb.content or "")[:200]
            out.append({
                "student": s.name,
                "time": fb.created_at.isoformat() if fb.created_at else "",
                "summary": text,
            })
        if len(out) >= limit * 2:
            break
    return {"tool": "feedbacks", "ms": int((time.time() - t0) * 1000), "items": out[: limit * 2]}


# —— 规则路由：问题 → 工具（快、准、零 token；LLM 规划是 P1 后半的可选项） ——

_BALANCE_HINTS = ("课时", "余额", "还剩", "剩余", "消耗", "欠费")
_SCHEDULE_HINTS = ("课表", "上课时间", "什么时候上课", "这周", "下周", "排课", "补课时间")
_FEEDBACK_HINTS = ("反馈", "老师怎么说", "评价", "表现怎么样", "学得怎么样")


def pick_tool(content: str) -> str | None:
    """返回 balance / schedule / feedbacks / None（RAG）。多命中按余额>课表>反馈优先级。"""
    t = content or ""
    if any(h in t for h in _BALANCE_HINTS):
        return "balance"
    if any(h in t for h in _SCHEDULE_HINTS):
        return "schedule"
    if any(h in t for h in _FEEDBACK_HINTS):
        return "feedbacks"
    return None


def run_tool(db: Session, user: User, name: str) -> dict:
    if name == "balance":
        return tool_balance(db, user)
    if name == "schedule":
        return tool_schedule(db, user)
    if name == "feedbacks":
        return tool_feedbacks(db, user)
    return {"tool": name, "ms": 0, "error": "unknown tool"}


_NUM_RE = None


def _numbers(text: str) -> set[str]:
    """答案中的数字集合（防幻觉校验用）。"""
    import re

    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


def tool_numbers(result: dict) -> set[str]:
    """工具结果中的数字集合：balance 余额 / schedule 时间 / feedbacks 无数字。"""
    import re

    nums: set[str] = set()
    for s in (result.get("students") or []):
        nums |= set(re.findall(r"\d+(?:\.\d+)?", str(s.get("balance", ""))))
    for it in (result.get("items") or []):
        nums |= set(re.findall(r"\d+(?:\.\d+)?", f"{it.get('start','')} {it.get('end','')}"))
    return nums


def answer_numbers_safe(answer: str, result: dict) -> bool:
    """答案数字 ⊆ 工具数字（日期数字如2026/10宽松放行：只校验小数余额类精确数字）。"""
    import re

    precise = set(re.findall(r"\d+\.\d+", answer or ""))
    if not precise:
        return True
    allowed = tool_numbers(result)
    return precise <= allowed


__all__ = [
    "answer_numbers_safe",
    "pick_tool",
    "run_tool",
    "tool_balance",
    "tool_feedbacks",
    "tool_numbers",
    "tool_schedule",
]
