"""智能助手「本地工具（Skill）」层：把结构化业务数据以只读方式喂给 Agent。

设计见 docs/adr/adr-0001-assistant-business-tools.md。要点：
- 每个工具声明 name / description / 参数 schema + 只读处理函数；
- 处理函数一律按「当前 user」作用域取数，教师只见本人数据，管理员/教务见全局聚合；
- 供对话前「规划 → 执行 → 注入」使用，模型只能决定调哪个工具/传什么参数，无法越权。

全部工具均为**只读**，不做任何写操作。
"""

from __future__ import annotations

import pathlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enrollment import Class, Student, StudentClass, StudentStatus
from app.models.evaluation import Evaluation, EvaluationStatus
from app.models.schedule import Attendance, AttendanceStatus, Schedule, ScheduleStatus
from app.models.user import Role, User
from app.services import agent_sql

# ---------------------------------------------------------------------------
# 时间范围解析：把自然语言周期映射为 [start, end)
# ---------------------------------------------------------------------------

_PERIODS = {
    "today": "今天",
    "this_week": "本周",
    "last_week": "上周",
    "this_month": "本月",
    "last_month": "上月",
    "this_quarter": "本季度",
    "this_year": "本年度",
    "recent_7d": "近 7 天",
    "recent_30d": "近 30 天",
}


def parse_period(period: str | None) -> tuple[datetime, datetime]:
    """返回 [start, end)（UTC）。未知/缺省按「本周」。"""
    now = datetime.now(UTC)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    key = (period or "this_week").strip().lower()
    if key == "today":
        return day0, day0 + timedelta(days=1)
    if key == "last_week":
        monday = day0 - timedelta(days=day0.weekday())
        return monday - timedelta(days=7), monday
    if key == "this_month":
        first = day0.replace(day=1)
        return first, _add_month(first)
    if key == "last_month":
        first = day0.replace(day=1)
        prev = first - timedelta(days=1)
        return prev.replace(day=1), first
    if key == "this_quarter":
        q = (day0.month - 1) // 3
        first = day0.replace(month=q * 3 + 1, day=1)
        return first, _add_month(first, 3)
    if key == "this_year":
        return day0.replace(month=1, day=1), day0.replace(month=1, day=1, year=day0.year + 1)
    if key == "recent_7d":
        return day0 - timedelta(days=6), day0 + timedelta(days=1)
    if key == "recent_30d":
        return day0 - timedelta(days=29), day0 + timedelta(days=1)
    # this_week（默认）
    monday = day0 - timedelta(days=day0.weekday())
    return monday, monday + timedelta(days=7)


def _add_month(dt: datetime, months: int = 1) -> datetime:
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    return dt.replace(year=year, month=month, day=1)


def _scope_teacher_id(user: User) -> uuid.UUID | None:
    """教师 → 仅本人；管理员/教务 → None（全局）。"""
    return user.id if user.role == Role.TEACHER else None


def _period_label(period: str | None) -> str:
    return _PERIODS.get((period or "this_week").strip().lower(), "本周")


# ---------------------------------------------------------------------------
# 工具实现（只读）
# ---------------------------------------------------------------------------

def _tool_my_schedule_overview(db: Session, user: User, *, period: str = "this_week") -> dict:
    """我的排课与考勤概览。"""
    start, end = parse_period(period)
    tid = _scope_teacher_id(user)
    stmt = select(Schedule).where(
        Schedule.status != ScheduleStatus.CANCELLED,
        Schedule.start_time >= start,
        Schedule.start_time < end,
    )
    if tid:
        stmt = stmt.where(Schedule.teacher_id == tid)
    schedules = list(db.scalars(stmt).all())
    sched_ids = [s.id for s in schedules]
    attended = leave = 0
    absent_ids: set[uuid.UUID] = set()
    if sched_ids:
        rows = db.execute(
            select(Attendance.student_id, Attendance.status).where(
                Attendance.schedule_id.in_(sched_ids),
                Attendance.status.in_(
                    [AttendanceStatus.ATTENDED.value, AttendanceStatus.LEAVE.value]
                ),
            )
        )
        for sid, st in rows:
            if st == AttendanceStatus.ATTENDED.value:
                attended += 1
            else:
                leave += 1
                absent_ids.add(sid)
    total = attended + leave
    absent_students: list[str] = []
    if absent_ids:
        absent_students = list(
            db.scalars(select(Student.name).where(Student.id.in_(absent_ids)).order_by(Student.name))
        )
    completed = sum(1 for s in schedules if s.status == ScheduleStatus.COMPLETED.value)
    return {
        "周期": _period_label(period),
        "排课节数": len(schedules),
        "已完成": completed,
        "上课人次": attended,
        "缺课人次": leave,
        "出勤率": f"{(attended / total * 100):.1f}%" if total else "无考勤数据",
        "缺课学员": absent_students[:20] or "无",
    }


def _tool_my_teaching_stats(db: Session, user: User, *, period: str = "this_month") -> dict:
    """我的教学数据（课时/达标/学员）。"""
    start, end = parse_period(period)
    tid = _scope_teacher_id(user)
    stmt = select(Schedule).where(
        Schedule.status == ScheduleStatus.COMPLETED,
        Schedule.start_time >= start,
        Schedule.start_time < end,
    )
    if tid:
        stmt = stmt.where(Schedule.teacher_id == tid)
    sched_ids = [s.id for s in db.scalars(stmt).all()]
    attended = leave = 0
    if sched_ids:
        rows = db.execute(
            select(Attendance.status).where(
                Attendance.schedule_id.in_(sched_ids),
                Attendance.status.in_(
                    [AttendanceStatus.ATTENDED.value, AttendanceStatus.LEAVE.value]
                ),
            )
        )
        for (st,) in rows:
            if st == AttendanceStatus.ATTENDED.value:
                attended += 1
            else:
                leave += 1
    # 应到人次 = 各 completed 排课对应班级在册学员数之和
    expected = _expected_attendance(db, sched_ids)
    expected_lessons = expected * 2
    consumed_lessons = attended * 2
    current_students = _current_student_count(db, tid)
    return {
        "周期": _period_label(period),
        "已完成排课": len(sched_ids),
        "上课人次": attended,
        "缺课人次": leave,
        "应消耗课时": expected_lessons,
        "实际消耗课时": consumed_lessons,
        "达标率": f"{(consumed_lessons / expected_lessons * 100):.1f}%" if expected_lessons else "无数据",
        "当前学员数": current_students,
    }


def _expected_attendance(db: Session, sched_ids: list[uuid.UUID]) -> int:
    if not sched_ids:
        return 0
    class_ids = list(
        db.scalars(select(Schedule.class_id).where(Schedule.id.in_(sched_ids)))
    )
    if not class_ids:
        return 0
    return int(
        db.scalar(
            select(func.count(StudentClass.student_id)).where(
                StudentClass.class_id.in_(class_ids)
            )
        )
        or 0
    )


def _current_student_count(db: Session, teacher_id: uuid.UUID | None) -> int:
    stmt = select(func.count(func.distinct(Student.id))).where(
        Student.status == StudentStatus.ACTIVE.value
    )
    if teacher_id:
        stmt = stmt.join(StudentClass, StudentClass.student_id == Student.id).join(
            Class, Class.id == StudentClass.class_id
        ).where(Class.teacher_id == teacher_id)
    return int(db.scalar(stmt) or 0)


def _tool_list_my_classes(db: Session, user: User, *, limit: int = 30) -> dict:
    """我的班级列表（名称/科目/学员数）。"""
    tid = _scope_teacher_id(user)
    stmt = select(Class).options(selectinload(Class.students)).where(
        Class.status == StudentStatus.ACTIVE.value
    )
    if tid:
        stmt = stmt.where(Class.teacher_id == tid)
    stmt = stmt.order_by(Class.created_at.desc()).limit(max(1, min(limit, 50)))
    rows = list(db.scalars(stmt).unique().all())
    return {
        "班级数": len(rows),
        "班级": [
            {"名称": c.name, "科目": c.subject, "学员数": len(c.students)} for c in rows
        ]
        or "暂无班级",
    }


def _tool_find_students(
    db: Session,
    user: User,
    *,
    keyword: str = "",
    low_balance_only: bool = False,
    class_name: str = "",
) -> dict:
    """按姓名/关键词查学员（课时余额、状态、班级）。教师只返回本人班级的学员。

    - class_name：限定某个班级的学员（用于"这个班有哪些学员"）；
    - 返回真实总数与可见条数；超过可见上限时给出明确提示，避免模型把"截断"误报为完整名单。
    """
    max_show = 100
    stmt = select(Student).options(selectinload(Student.classes)).where(
        Student.status != StudentStatus.ARCHIVED.value
    )
    if user.role == Role.TEACHER:
        # 教师作用域：学员所在（在教）班级的带教教师为该教师（与学员管理的教师筛选一致）
        stmt = stmt.where(
            Student.classes.any(
                and_(Class.teacher_id == user.id, Class.status == StudentStatus.ACTIVE.value)
            )
        )
    if class_name.strip():
        cls = _find_class_by_name(db, user, class_name)
        if cls is None:
            return {"错误": f"未找到班级「{class_name}」（或不在你的班级中）"}
        stmt = stmt.where(Student.classes.any(Class.id == cls.id))
    if keyword.strip():
        stmt = stmt.where(Student.name.ilike(f"%{keyword.strip()}%"))
    if low_balance_only:
        stmt = stmt.where(Student.lesson_balance <= 10)
    total = int(db.scalar(stmt.with_only_columns(func.count(func.distinct(Student.id)))) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(Student.lesson_balance.asc(), Student.name.asc()).limit(max_show)
        ).unique().all()
    )
    out: dict = {
        "总数": total,
        "返回条数": len(rows),
        "学员": [
            {
                "姓名": s.name,
                "课时余额": s.lesson_balance,
                "状态": s.status,
                "班级": [c.name for c in s.classes] or "未分班",
            }
            for s in rows
        ]
        or "未找到匹配学员",
    }
    if len(rows) < total:
        out["提示"] = f"仅显示前 {len(rows)} 条，共 {total} 条；如需继续可用 keyword 再查。"
    return out


def _tool_student_progress(
    db: Session, user: User, *, student_name: str, period: str = "this_month"
) -> dict:
    """某学员的学习情况（考勤/课时/反馈数）。"""
    student = _find_student_by_name(db, user, student_name)
    if student is None:
        return {"错误": f"未找到学员「{student_name}」"}
    start, end = parse_period(period)
    class_ids = [c.id for c in student.classes]
    attended = leave = 0
    if class_ids:
        rows = db.execute(
            select(Attendance.status)
            .join(Schedule, Attendance.schedule_id == Schedule.id)
            .where(
                Attendance.student_id == student.id,
                Schedule.class_id.in_(class_ids),
                Schedule.start_time >= start,
                Schedule.start_time < end,
                Schedule.status != ScheduleStatus.CANCELLED.value,
            )
        )
        for (st,) in rows:
            if st == AttendanceStatus.ATTENDED.value:
                attended += 1
            elif st == AttendanceStatus.LEAVE.value:
                leave += 1
    total = attended + leave
    return {
        "学员": student.name,
        "状态": student.status,
        "课时余额": student.lesson_balance,
        "班级": [c.name for c in student.classes] or "未分班",
        "周期": _period_label(period),
        "上课人次": attended,
        "请假人次": leave,
        "出勤率": f"{(attended / total * 100):.1f}%" if total else "无考勤数据",
    }


def _tool_student_evaluations(
    db: Session, user: User, *, student_name: str = "", limit: int = 5
) -> dict:
    """学员评估报告（按学员名筛选，缺省列最近）。"""
    stmt = (
        select(Evaluation)
        .options(selectinload(Evaluation.student))
        .order_by(Evaluation.updated_at.desc())
        .limit(max(1, min(limit, 20)))
    )
    if user.role == Role.TEACHER:
        stmt = stmt.where(Evaluation.teacher_id == user.id)
    if student_name.strip():
        student = _find_student_by_name(db, user, student_name)
        if student is None:
            return {"错误": f"未找到学员「{student_name}」"}
        stmt = stmt.where(Evaluation.student_id == student.id)
    rows = list(db.scalars(stmt).unique().all())
    return {
        "评估数": len(rows),
        "评估": [
            {
                "学员": e.student.name if e.student else "",
                "标题": e.title or "未命名",
                "周期": f"{e.period_start} ~ {e.period_end}",
                "状态": e.status,
            }
            for e in rows
        ]
        or "暂无评估报告",
    }


def _find_class_by_name(db: Session, user: User, name: str) -> Class | None:
    """按班级名查班级，且遵循教师作用域。"""
    if not name.strip():
        return None
    stmt = (
        select(Class)
        .options(selectinload(Class.students))
        .where(Class.name.ilike(f"%{name.strip()}%"), Class.status == StudentStatus.ACTIVE.value)
        .limit(1)
    )
    if user.role == Role.TEACHER:
        stmt = stmt.where(Class.teacher_id == user.id)
    return db.scalars(stmt).first()


def _tool_class_evaluation_overview(
    db: Session, user: User, *, class_name: str = ""
) -> dict:
    """某班的学员评估完成情况：逐学员标注 已完成 / 草稿·未完成 / 未写评估。

    解决旧工具只能列出"已存在的评估"、无法判断未写学员完成状态的问题。
    已完成 = 有已发布(published)的评估；未完成 = 未写评估 或 评估仍为草稿(draft)。
    """
    cls = _find_class_by_name(db, user, class_name)
    if cls is None:
        return {"错误": f"未找到班级「{class_name}」（或不在你的班级中）"}
    ev_stmt = select(Evaluation)
    if user.role == Role.TEACHER:
        ev_stmt = ev_stmt.where(Evaluation.teacher_id == user.id)
    ev_by_student: dict = {}
    for ev in db.scalars(ev_stmt).unique().all():
        ev_by_student.setdefault(ev.student_id, ev)

    done = 0
    detail = []
    for s in sorted(cls.students, key=lambda stu: stu.name):
        ev = ev_by_student.get(s.id)
        if ev is None:
            state = "未写评估"
        elif ev.status == EvaluationStatus.PUBLISHED.value:
            state, done = "已完成", done + 1
        else:
            state = "草稿·未完成"
        detail.append(
            {
                "学员": s.name,
                "状态": state,
                "标题": ev.title if ev else "",
                "周期": f"{ev.period_start} ~ {ev.period_end}" if ev else "",
            }
        )
    return {
        "班级": cls.name,
        "学员数": len(detail),
        "已完成": done,
        "未完成": len(detail) - done,
        "明细": detail or "该班暂无学员",
        "提示": "未完成=未写评估或评估仍为草稿(draft)；已完成=已有已发布(published)评估。",
    }


def _find_student_by_name(db: Session, user: User, name: str) -> Student | None:
    """按姓名查学员，且遵循教师作用域（教师只能查到本人班级的学员）。"""
    if not name.strip():
        return None
    stmt = (
        select(Student)
        .options(selectinload(Student.classes))
        .where(Student.name.ilike(f"%{name.strip()}%"))
        .limit(1)
    )
    if user.role == Role.TEACHER:
        stmt = stmt.where(
            Student.classes.any(
                and_(Class.teacher_id == user.id, Class.status == StudentStatus.ACTIVE.value)
            )
        )
    return db.scalars(stmt).first()


# ---------------------------------------------------------------------------
# 数据库查询工具（只读 SQL，多步取数）：实现见 agent_sql
# ---------------------------------------------------------------------------

def _tool_sql_list_tables(db: Session, user: User) -> dict:
    return agent_sql.list_tables(user)


def _tool_sql_describe_table(db: Session, user: User, *, table: str = "") -> dict:
    return agent_sql.describe_table(db, user, table)


def _tool_sql_query(db: Session, user: User, *, sql: str = "") -> dict:
    return agent_sql.run_query(db, user, sql)


# ---------------------------------------------------------------------------
# 联网搜索工具（Tavily）：补充「公网外部事实」，不用于内部政策/数据问答
# ---------------------------------------------------------------------------

def _tool_web_search(
    db: Session, user: User, *, query: str = "", max_results: int = 5,
    topic: str = "general", time_range: str = "",
) -> dict:
    """联网检索公开信息（行业动态/竞品/通用知识/公开资料）。

    安全边界：只补充**外部公开信息**；本校的学员/课时/排课/收费/政策一律以内部数据与
    知识库为准，不得用联网结果回答。未配置 Tavily 时返回明确提示（不报错）。
    """
    from app.crud import search_config as _sc
    from app.services import web_search as _ws

    resolved = _sc.resolve_search(db)
    if resolved is None:
        return {
            "来源": "公网",
            "错误": "联网搜索未启用（管理员尚未在设置中配置 Tavily），本次只能依据系统内部数据与知识库作答",
        }
    return _ws.search_web(
        resolved,
        query=query,
        max_results=max_results,
        topic=topic or "general",
        time_range=(time_range or "").strip() or None,
    )


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

def _parse_run_hint(stderr: str) -> tuple[str, list[str]] | None:
    """从脚本 stderr 提取 "Run: python3 <脚本> <参数>" 形式的自修复提示。"""
    import re
    import shlex

    m = re.search(r"Run:\s*python3\s+(\S+)\s*([^\n]*)", stderr or "")
    if not m:
        return None
    script = m.group(1).strip().strip("\"'")
    try:
        rest = shlex.split(m.group(2).strip())
    except ValueError:
        rest = m.group(2).split()
    return script, rest


def _locate_script(target, hint_path: str) -> str | None:
    """把提示里的脚本路径匹配到包内真实路径（前缀可能不同，如 ppt-master-main/）。"""
    files = [str(f) for f in (target.files or [])]
    hint = hint_path.replace("\\", "/").lstrip("./")
    for f in files:
        if f.endswith(hint) or f.endswith("/" + hint):
            return f
    base = hint.rsplit("/", 1)[-1]
    return next((f for f in files if f.rsplit("/", 1)[-1] == base), None)


def _tool_run_skill_script(db: Session, user: User, *, skill: str = "", path: str = "", args: list | None = None) -> dict:
    """执行用户 Skill 包内脚本（走用户沙箱配置：本地/百炼；产物自动取回给下载链接）。"""
    from app.crud import agent_ext as _ext
    from app.services import skill_exec as _exec

    ref = (skill or "").strip()
    rel = (path or "").strip().replace("\\", "/")
    if not ref or not rel:
        return {"错误": "需提供 skill（Skill 名或 id）与 path（包内脚本路径）"}
    skills = [s for s in _ext.list_skills(db, owner_id=user.id) if s.enabled]
    target = None
    for s in skills:
        sid = str(s.id)
        if ref == sid or ref == sid[:8] or ref in (s.name or ""):
            target = s
            break
    if target is None:
        return {"错误": f"找不到启用的 Skill：{ref}（可用：{('、'.join(s.name for s in skills[:10])) or '无'}）"}
    if rel not in list(target.files or []):
        cands = [f for f in (target.files or []) if str(f).lower().endswith((".py", ".js", ".sh"))]
        return {"错误": f"{target.name} 包内无此文件：{rel}（可执行：{'、'.join(cands[:10]) or '无'}）"}
    if pathlib.PurePosixPath(rel).suffix.lower() not in (".py", ".js", ".sh"):
        return {"错误": f"仅支持运行 .py/.js/.sh 脚本：{rel}"}
    sb = _ext.get_sandbox_setting(db, owner_id=user.id)

    def _call(r: str, a: list) -> dict:
        return _exec.dispatch(
            user.id, target.id, r, a,
            provider=sb.provider if sb and sb.enabled else "local",
            endpoint=sb.endpoint if sb else "", token=sb.token if sb else "",
            timeout_s=sb.timeout_s if sb else 30,
            workspace_id=sb.workspace_id if sb else "", region=sb.region if sb else "cn-beijing",
            template_code=sb.template_code if sb else "",
        )

    try:
        result = _call(rel, list(args or [])[:8])
        fixed: dict | None = None
        # 自愈：脚本多以 stderr 里 "Run: python3 <脚本> <参数>" 给出前置修复命令
        # （如 svg_to_pptx 要求先跑质量检查器）。失败时按其提示补跑前置步骤，再重试一次。
        if not result.get("ok"):
            hint = _parse_run_hint(str(result.get("stderr") or ""))
            if hint:
                hint_rel = _locate_script(target, hint[0])
                if hint_rel and hint_rel != rel:
                    fixed = _call(hint_rel, hint[1][:8])
                    if fixed.get("ok"):
                        result = _call(rel, list(args or [])[:8])
    except (ValueError, TimeoutError) as e:
        return {"错误": str(e)}
    # 键顺序刻意把「生成文件」放最前：前端摘要/模型观察都会按字符截断，
    # 下载链接必须在截断线之内，否则模型看不到链接、用户拿不到文件。
    out: dict = {"skill": target.name, "成功": result.get("ok", False),
                 "退出码": result.get("code")}
    fnames = result.get("files") or []
    if fnames:
        out["生成文件"] = [{"名": f["name"], "下载": f["url"], "字节": f["bytes"]} for f in fnames]
        out["提示"] = "生成的文件已有下载链接，请把链接直接给用户，不要只描述内容"
    if fixed is not None:
        out["自动前置"] = {
            "成功": fixed.get("ok", False),
            "退出码": fixed.get("code"),
        }
    out["脚本"] = rel
    out["stdout"] = str(result.get("stdout", ""))[:1200]
    out["stderr"] = str(result.get("stderr", ""))[:1200]
    if result.get("deps"):
        out["依赖"] = result["deps"]
    return out


def _tool_write_skill_file(db: Session, user: User, *, skill: str = "", path: str = "", content: str = "") -> dict:
    """把文本写入 Skill 包内（如手写 SVG/JSON 工程文件），供后续脚本（svg_to_pptx 等）消费。

    用途：ppt-master 这类 Skill 需要 agent 先产出 SVG 源文件，再跑转换脚本；
    本工具就是"手"——写进包内并登记到 files，之后 run_skill_script 才能读到/执行。
    """
    from app.crud import agent_ext as _ext
    from app.services import skill_bundle as _bundle

    ref = (skill or "").strip()
    rel = (path or "").strip().replace("\\", "/")
    if not ref or not rel:
        return {"错误": "需提供 skill（Skill 名或 id）与 path（包内相对路径）"}
    pp = pathlib.PurePosixPath(rel)
    if pp.is_absolute() or ".." in pp.parts:
        return {"错误": f"非法路径：{rel}"}
    allow = {".svg", ".json", ".md", ".txt", ".xml", ".html", ".yaml", ".yml", ".csv", ".css"}
    if pp.suffix.lower() not in allow:
        return {"错误": f"仅支持写入文本文件（{'、'.join(sorted(allow))}）：{rel}"}
    body = content if isinstance(content, str) else str(content)
    if not body:
        return {"错误": "content 不能为空"}
    if len(body.encode("utf-8")) > 512 * 1024:
        return {"错误": "单文件上限 512KB"}
    target = None
    for s in _ext.list_skills(db, owner_id=user.id):
        sid = str(s.id)
        if ref == sid or ref == sid[:8] or ref in (s.name or ""):
            target = s
            break
    if target is None:
        return {"错误": f"找不到 Skill：{ref}"}
    dest = _bundle.skill_dir(user.id, target.id)
    fp = (dest / rel).resolve()
    if dest.resolve() not in fp.parents:
        return {"错误": f"非法路径：{rel}"}
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(body, encoding="utf-8")
    except OSError as e:
        return {"错误": f"写入失败：{e}"}
    files = list(target.files or [])
    if rel not in files:
        files.append(rel)
        _ext.update_skill(db, target, files=files)
    return {"skill": target.name, "已写入": rel, "字节": len(body.encode("utf-8")),
            "提示": "文件已就位，可继续写其余页面，然后用 run_skill_script 跑该 Skill 的转换脚本生成 PPTX"}


def _tool_list_skill_files(db: Session, user: User, *, skill: str = "", path: str = "") -> dict:
    """列出 Skill 包内某个目录下的文件（用于发现已生成的项目、找到正确的脚本/源文件路径）。"""
    from app.crud import agent_ext as _ext
    from app.services import skill_bundle as _bundle

    ref = (skill or "").strip()
    if not ref:
        return {"错误": "需提供 skill（Skill 名或 id）"}
    prefix = (path or "").strip().replace("\\", "/").strip("/")
    target = None
    for s in _ext.list_skills(db, owner_id=user.id):
        sid = str(s.id)
        if ref == sid or ref == sid[:8] or ref in (s.name or ""):
            target = s
            break
    if target is None:
        return {"错误": f"找不到 Skill：{ref}"}
    dest = _bundle.skill_dir(user.id, target.id)
    base = dest / prefix if prefix else dest
    if not base.exists() or not base.is_dir():
        # 兜底：把包内所有目录一级列一下，帮助模型导航
        tops = sorted({str(p.relative_to(dest)).replace("\\", "/").split("/")[0] for p in dest.iterdir()})[:30]
        return {"错误": f"目录不存在：{prefix or '/'}", "包内顶层": tops}
    dirs: list[str] = []
    files: list[str] = []
    for p in sorted(base.iterdir()):
        rel = str(p.relative_to(dest)).replace("\\", "/")
        if p.is_dir():
            dirs.append(rel + "/")
        else:
            files.append(rel)
    return {"skill": target.name, "目录": (prefix + "/") if prefix else "（包根）",
            "子目录": dirs[:50], "文件": files[:80],
            "提示": "用这里列出的真实路径调用 read_skill_file / run_skill_script / write_skill_file"}


def _tool_read_skill_file(db: Session, user: User, *, skill: str = "", path: str = "") -> dict:
    """读用户 Skill 包内文本文件（先读 SKILL.md/入口脚本/参考资料，再决定跑哪个脚本、传什么参）。"""
    from app.crud import agent_ext as _ext
    from app.services import skill_bundle as _bundle

    ref = (skill or "").strip()
    rel = (path or "").strip().replace("\\", "/")
    if not ref or not rel:
        return {"错误": "需提供 skill（Skill 名或 id）与 path（包内文件路径）"}
    target = None
    for s in _ext.list_skills(db, owner_id=user.id):
        sid = str(s.id)
        if ref == sid or ref == sid[:8] or ref in (s.name or ""):
            target = s
            break
    if target is None:
        return {"错误": f"找不到 Skill：{ref}"}
    if rel not in list(target.files or []):
        base = rel.rsplit("/", 1)[-1].lower()
        same = [f for f in (target.files or []) if str(f).rsplit("/", 1)[-1].lower() == base][:3]
        hint = f"（同名文件：{'、'.join(same)}，请用完整包内路径）" if same else ""
        return {"错误": f"{target.name} 包内无此文件：{rel}{hint}"}
    try:
        text = _bundle.read_text_file(user.id, target.id, rel)
    except ValueError as e:
        return {"错误": str(e)}
    return {"skill": target.name, "文件": rel, "内容": text[:3000]}


_TOOL_FUNCS: dict[str, Callable[..., dict]] = {
    "my_schedule_overview": _tool_my_schedule_overview,
    "my_teaching_stats": _tool_my_teaching_stats,
    "list_my_classes": _tool_list_my_classes,
    "find_students": _tool_find_students,
    "student_progress": _tool_student_progress,
    "student_evaluations": _tool_student_evaluations,
    "class_evaluation_overview": _tool_class_evaluation_overview,
    "sql_list_tables": _tool_sql_list_tables,
    "sql_describe_table": _tool_sql_describe_table,
    "sql_query": _tool_sql_query,
    "web_search": _tool_web_search,
    "run_skill_script": _tool_run_skill_script,
    "write_skill_file": _tool_write_skill_file,
    "read_skill_file": _tool_read_skill_file,
    "list_skill_files": _tool_list_skill_files,
}

# OpenAI 兼容 function-calling 的 tools schema
TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "my_schedule_overview",
            "description": "查询当前用户的排课与考勤概览（排课节数、上课/缺课人次、出勤率、缺课学员）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": list(_PERIODS.keys()),
                        "description": "时间范围，如 today/this_week/last_week/this_month",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_teaching_stats",
            "description": "查询当前用户的教学数据（已完成排课、课时消耗、达标率、当前学员数）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": list(_PERIODS.keys())}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_classes",
            "description": "查询当前用户负责的班级列表（名称、科目、学员数）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_students",
            "description": "按姓名/关键词或班级查询学员，返回课时余额、状态、班级；也可用于查课时不足需催缴的学员。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "学员姓名关键词，可空"},
                    "class_name": {
                        "type": "string",
                        "description": "限定某个班级的学员（班级名可模糊），问'这个班有哪些学员'时使用",
                    },
                    "low_balance_only": {
                        "type": "boolean",
                        "description": "仅返回课时不足（≤10）需催缴的学员",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "student_progress",
            "description": "查询某个学员的学习情况（考勤、课时余额、班级）。需提供学员姓名。",
            "parameters": {
                "type": "object",
                "properties": {
                    "student_name": {"type": "string", "description": "学员姓名"},
                    "period": {"type": "string", "enum": list(_PERIODS.keys())},
                },
                "required": ["student_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "student_evaluations",
            "description": "查询学员评估报告列表，可按学员姓名筛选。",
            "parameters": {
                "type": "object",
                "properties": {
                    "student_name": {"type": "string", "description": "学员姓名，可空"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "class_evaluation_overview",
            "description": (
                "某班的学员评估完成情况：逐学员标注已完成/草稿·未完成/未写评估，并给出完成数。"
                "问'班里哪些学员评估还没完成/没有写评估'这类问题时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "class_name": {"type": "string", "description": "班级名称（可模糊）"}
                },
                "required": ["class_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sql_list_tables",
            "description": (
                "列出可查询的业务表及用途。当既有工具无法回答、需要灵活统计（如分组/排序/自定义维度）时，"
                "先用它了解有哪些表，再 sql_describe_table 看结构，最后 sql_query 执行只读 SQL。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sql_describe_table",
            "description": "查看某张业务表的列与类型，写 SQL 前调用。",
            "parameters": {
                "type": "object",
                "properties": {"table": {"type": "string", "description": "表名"}},
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sql_query",
            "description": (
                "执行一条只读 SELECT 查询取数（系统仅允许 SELECT，自动限行数，带超时）。"
                "仅当既有工具不足以回答问题、需要自定义统计时才用。教师查询含 teacher_id 的表必须带 "
                "teacher_id 过滤。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "单条 SELECT 语句"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "联网检索公开信息（Tavily），返回标题/链接/摘要/日期。"
                "仅用于需要**外部公开事实**的问题：行业动态、竞品/同行做法、公开资料、通用知识、"
                "最新政策或新闻等。凡涉及本校的学员、课时、排课、收费、退费、请假制度等，"
                "必须用内部工具或知识库回答，**绝不可用联网结果代替**。"
                "若已有内部数据或知识库片段能回答，就不要调用本工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词（用自然语言，中文即可）"},
                    "max_results": {
                        "type": "integer",
                        "description": "返回条数（1-10，默认5）",
                    },
                    "topic": {
                        "type": "string",
                        "enum": ["general", "news", "finance"],
                        "description": "检索主题：general=通用、news=新闻资讯、finance=财经",
                    },
                    "time_range": {
                        "type": "string",
                        "enum": ["day", "week", "month", "year"],
                        "description": "只看最近一段时间的结果（可选）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_skill_script",
            "description": (
                "执行用户 Skill 包内的 .py/.js/.sh 脚本（走沙箱：本地或阿里云百炼，依赖自动安装）。"
                "用户要求生成文件/跑脚本/用 Skill 干活时用它：读完 SKILL.md 确认入口后立即执行，"
                "不要继续读文件浪费次数。执行环境：沙箱工作区根目录即包根，包内相对路径不变，"
                "args 为命令行参数数组；返回含 stdout/stderr 与生成文件的下载链接，拿到链接后必须直接给用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "description": "Skill 名（或 id）"},
                    "path": {"type": "string", "description": "包内脚本路径，如 skills/ppt-master/scripts/build.py"},
                    "args": {"type": "array", "items": {"type": "string"}, "description": "命令行参数数组"},
                },
                "required": ["skill", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_skill_file",
            "description": (
                "读取用户 Skill 包内的文本文件（SKILL.md、脚本源码、references 参考资料）。"
                "跑脚本之前先用它读 SKILL.md 确认入口与参数，不要凭文件名猜。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "description": "Skill 名（或 id）"},
                    "path": {"type": "string", "description": "包内文件路径，如 SKILL.md"},
                },
                "required": ["skill", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skill_files",
            "description": (
                "列出 Skill 包内某个目录下的子目录与文件。"
                "当需要找已有项目/源文件、或不确定脚本真实路径时先用它（例如列出 projects/ 看已生成的项目）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "description": "Skill 名（或 id）"},
                    "path": {"type": "string", "description": "包内目录路径，留空列包根，如 projects"},
                },
                "required": ["skill"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_skill_file",
            "description": (
                "把文本写入某个 Skill 包内（如手写 SVG/JSON 工程文件）。"
                "当 Skill 需要 agent 先产出源文件再跑转换脚本时（例如 ppt-master 手写 SVG 后用 svg_to_pptx 导出），"
                "用它逐页写入；每页一次调用，之后再用 run_skill_script 执行转换脚本。"
                "只支持文本文件（.svg/.json/.md/.txt/.xml/.html/.yaml/.yml/.csv/.css），单文件≤512KB。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string", "description": "Skill 名（或 id）"},
                    "path": {"type": "string", "description": "包内相对路径，如 projects/demo/svg_output/01_cover.svg"},
                    "content": {"type": "string", "description": "文件文本内容"},
                },
                "required": ["skill", "path", "content"],
            },
        },
    },
]


def execute_tool(db: Session, user: User, name: str, args: dict) -> dict:
    """按名执行工具（参数做白名单过滤，防止模型塞入未声明参数）。"""
    fn = _TOOL_FUNCS.get(name)
    if fn is None:
        return {"错误": f"未知工具 {name}"}
    return fn(db, user, **{k: v for k, v in (args or {}).items() if k != "db"})


# ---------------------------------------------------------------------------
# 规划 + 执行 + 注入
# ---------------------------------------------------------------------------

# 业务意图关键词门控：命中才触发一次 LLM 规划，避免非业务消息多一次往返
_BIZ_KEYWORDS = (
    "排课", "课表", "考勤", "出勤", "缺课", "请假", "课时", "余额", "催缴", "达标",
    "班级", "学员", "学生", "评估", "报告", "教学", "上课", "教师", "老师", "数据",
    "统计", "本周", "上周", "本月", "上月", "今天", "进度", "多少人", "几个班",
    "多少", "几个", "平均", "排名", "排行", "明细", "记录", "占比", "比例", "趋势",
    "哪个班", "哪些", "谁", "名单", "个人", "带了", "带我", "班里", "班上",
)


def looks_like_business(message: str) -> bool:
    t = (message or "").strip()
    if not t:
        return False
    return any(k in t for k in _BIZ_KEYWORDS)


_SKILL_KEYWORDS = ("生成", "创建", "制作", "运行", "执行", "脚本", "PPT", "ppt", "pptx", "下载", "导出")


def looks_like_skill_task(message: str) -> bool:
    """像是在让 Skill 干活（生成文件/跑脚本）：命中动词即放行 Planner，模型再按 Skill 清单决定。"""
    t = (message or "").strip()
    if not t:
        return False
    return any(k in t for k in _SKILL_KEYWORDS)


# 联网搜索触发词：命中性问题让「规划器有机会运行」，是否真搜仍由模型判断。
# 只覆盖"明显需要外部/时效信息"的信号，避免每句闲聊都触发规划（省一次 LLM 往返）。
_WEB_SEARCH_KEYWORDS = (
    "最新", "近期", "最近", "今年", "现在", "当前", "近日", "实时", "新出的", "新版",
    "新闻", "资讯", "动态", "趋势", "业内", "行业", "同行", "竞品", "别家", "其他机构",
    "外面", "网上", "联网", "搜一下", "搜索", "查一下网上", "帮我查", "调研",
    "政策", "规定", "法规", "标准", "指南", "教程", "文档", "官网", "资料",
    "什么是", "是什么", "什么是", "了解一下", "科普", "原理", "怎么用", "如何用",
)


def looks_like_web_search(message: str) -> bool:
    """是否可能需要联网检索（仅作规划放行信号；真正的检索决策交给模型）。

    注意：与 looks_like_business 并列——业务问题走内部工具，外部/时效问题才可能联网。
    本校政策/收费/退费/课时规则等即使命中关键词，也应由内部工具/知识库回答，
    模型侧由 web_search 工具描述与注入块约束兜底，这里不拦截（否则会误伤通用知识问答）。
    """
    t = (message or "").strip()
    if not t:
        return False
    return any(k in t for k in _WEB_SEARCH_KEYWORDS)


def heuristic_skill_calls(db, user) -> list[dict]:
    """Skill 兜底：规划器零工具调用时，强制先读第一个可执行 Skill 的 SKILL.md。

    保证执行链路非空（用户能看到读了什么），模型也能拿到入口脚本与参数说明再决策。
    """
    try:
        from app.crud import agent_ext as _ext

        for s in _ext.list_skills(db, owner_id=user.id):
            if not s.enabled:
                continue
            files = [str(f) for f in (s.files or [])]
            if not any(f.lower().endswith((".py", ".js", ".sh")) for f in files):
                continue
            doc = next((f for f in files if f.lower().endswith("skill.md")), None)
            if doc:
                return [{"name": "read_skill_file", "arguments": {"skill": s.name, "path": doc}}]
    except Exception:
        pass
    return []


def _heuristic_calls(message: str) -> list[dict]:
    """无 LLM 规划时的关键词直连路由。"""
    t = message
    calls: list[dict] = []
    period = _guess_period(t)
    if any(k in t for k in ("排课", "课表", "考勤", "出勤", "缺课", "请假", "上课")):
        calls.append({"name": "my_schedule_overview", "arguments": {"period": period}})
    if any(k in t for k in ("课时", "达标", "教学数据", "统计", "数据", "消耗")):
        calls.append({"name": "my_teaching_stats", "arguments": {"period": period}})
    if any(k in t for k in ("班级", "几个班")):
        calls.append({"name": "list_my_classes", "arguments": {}})
    if any(k in t for k in ("余额", "催缴", "课时不足")):
        calls.append({"name": "find_students", "arguments": {"low_balance_only": True}})
    if "评估" in t:
        calls.append({"name": "student_evaluations", "arguments": {}})
    return calls


def _guess_period(text: str) -> str:
    mapping = [
        ("今天", "today"), ("今日", "today"),
        ("昨天", "last_week"), ("上周", "last_week"),
        ("本周", "this_week"), ("这周", "this_week"),
        ("上月", "last_month"), ("上个月", "last_month"),
        ("本月", "this_month"), ("这个月", "this_month"),
        ("季度", "this_quarter"), ("年", "this_year"),
        ("近7天", "recent_7d"), ("近 7 天", "recent_7d"),
        ("近30天", "recent_30d"),
    ]
    for kw, key in mapping:
        if kw in text:
            return key
    return "this_week"


def _to_text(obj: Any) -> str:
    import json

    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


__all__ = [
    "TOOLS_SCHEMA", "parse_period", "looks_like_business", "execute_tool",
]
