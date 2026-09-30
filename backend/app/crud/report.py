import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enrollment import Class, Student, StudentClass, StudentStatus
from app.models.report import Report, ReportStatus, ReportType
from app.models.schedule import Attendance, AttendanceStatus, Schedule, ScheduleStatus
from app.models.user import Role, User, UserStatus

# 业务时间语义：前端全程传本地 naive（北京时间 wall-clock），后端区间查询
# 必须按北京时间解释 naive 入参。此前默认 UTC，导致 Q1（01-01 00:00+08
# 落到 12-31 16:00Z）小于 01-01 00:00Z 下界被丢掉——年度 AI 只剩 Q2-Q4 的根因。
BEIJING = timezone(timedelta(hours=8))


def _day_start(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), time.min, tzinfo=dt.tzinfo or BEIJING)


def _day_end(dt: datetime) -> datetime:
    return datetime.combine(dt.date(), time.max, tzinfo=dt.tzinfo or BEIJING)


def get(db: Session, report_id: uuid.UUID) -> Report | None:
    return db.get(Report, report_id)


def _find_existing(
    db: Session,
    *,
    type: str,
    teacher_id: uuid.UUID,
    period_start: datetime,
    period_end: datetime,
) -> Report | None:
    return db.scalars(
        select(Report).where(
            Report.type == type,
            Report.teacher_id == teacher_id,
            Report.period_start == period_start,
            Report.period_end == period_end,
        )
    ).first()


def upsert(
    db: Session,
    *,
    type: str,
    teacher_id: uuid.UUID,
    period_start: datetime,
    period_end: datetime,
    title: str | None,
    content: dict,
    stats: dict | None,
) -> Report:
    """同一教师同类型同周期仅一份：存在则更新，否则新建。"""
    existing = _find_existing(
        db, type=type, teacher_id=teacher_id, period_start=period_start, period_end=period_end
    )
    if existing:
        if title is not None:
            existing.title = title
        if content:
            existing.content = {**existing.content, **content}
        if stats is not None:
            existing.stats = stats
        db.commit()
        db.refresh(existing)
        return existing
    rep = Report(
        type=type,
        teacher_id=teacher_id,
        period_start=period_start,
        period_end=period_end,
        title=title,
        content=content,
        stats=stats,
    )
    db.add(rep)
    db.commit()
    db.refresh(rep)
    return rep


def update(
    db: Session,
    rep: Report,
    *,
    title: str | None,
    content: dict | None,
    stats: dict | None,
) -> Report:
    if title is not None:
        rep.title = title
    if content is not None:
        rep.content = {**rep.content, **content}
    if stats is not None:
        rep.stats = stats
    db.commit()
    db.refresh(rep)
    return rep


def publish(db: Session, rep: Report) -> Report:
    """发布（提交归档）：草稿 -> 已发布，记录发布时间。可重复发布（重新编辑后再次提交）。"""
    rep.status = ReportStatus.PUBLISHED.value
    rep.published_at = datetime.now(BEIJING)
    db.commit()
    db.refresh(rep)
    return rep


def unpublish(db: Session, rep: Report) -> Report:
    """撤回：已发布 -> 草稿，清除发布时间，供重新编辑。"""
    rep.status = ReportStatus.DRAFT.value
    rep.published_at = None
    db.commit()
    db.refresh(rep)
    return rep


def delete(db: Session, rep: Report) -> None:
    """删除报告（含已发布）。同时清理落盘的 PPT 文件，避免残留。"""
    from pathlib import Path

    from app.core.config import get_settings

    if rep.ppt_url:
        try:
            upload_dir = Path(get_settings().UPLOAD_DIR)
            target = (upload_dir / rep.ppt_url).resolve()
            if target.is_file() and str(target).startswith(str(upload_dir.resolve())):
                target.unlink(missing_ok=True)
        except OSError:
            pass
    db.delete(rep)
    db.commit()


def list_reports(
    db: Session,
    *,
    type: str | None,
    teacher_id: uuid.UUID | None,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    offset: int,
) -> list[Report]:
    stmt = select(Report)
    if type:
        stmt = stmt.where(Report.type == type)
    if teacher_id:
        stmt = stmt.where(Report.teacher_id == teacher_id)
    if start is not None:
        stmt = stmt.where(Report.period_start >= _day_start(start))
    if end is not None:
        stmt = stmt.where(Report.period_start <= _day_end(end))
    stmt = stmt.order_by(Report.period_start.desc(), Report.created_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(db.scalars(stmt.limit(limit).offset(offset)).unique().all())
    return items, total


def list_board_reports(
    db: Session,
    *,
    type: str | None,
    teacher_id: uuid.UUID | None,
    campus: str | None,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    offset: int,
) -> list[Report]:
    """公栏报告：仅已发布（published），可按类型/教师/校区/周期筛选。"""
    stmt = (
        select(Report)
        .join(User, Report.teacher_id == User.id)
        .where(Report.status == ReportStatus.PUBLISHED.value)
    )
    if type:
        stmt = stmt.where(Report.type == type)
    if teacher_id:
        stmt = stmt.where(Report.teacher_id == teacher_id)
    if campus:
        stmt = stmt.where(User.campus == campus)
    if start is not None:
        stmt = stmt.where(Report.period_start >= _day_start(start))
    if end is not None:
        stmt = stmt.where(Report.period_start <= _day_end(end))
    stmt = stmt.order_by(
        Report.period_start.desc(), Report.published_at.desc(), Report.created_at.desc()
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(db.scalars(stmt.limit(limit).offset(offset)).unique().all())
    return items, total


def board_report_stats(
    db: Session,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    campus: str | None = None,
) -> dict:
    """公栏数据统计（按在职教师 + 周期）。

    应提交数量 = 在职教师数 × 应提交天数/周数；已提交数量 = 周期内经发布（published）的报告条数。
    - daily_due / daily_submitted 日报应提交/已提交
    - weekly_due / weekly_submitted 周报应提交/已提交
    - teacher_count 在职教师数
    """
    teacher_stmt = select(User.id).where(
        User.role == Role.TEACHER.value,
        User.status == UserStatus.ACTIVE.value,
    )
    if campus:
        teacher_stmt = teacher_stmt.where(User.campus == campus)
    teacher_ids = list(db.scalars(teacher_stmt))
    teacher_count = len(teacher_ids)

    s_start = _day_start(start) if start is not None else None
    s_end = _day_end(end) if end is not None else None

    def _published_count(report_type: str) -> int:
        stmt = select(func.count(Report.id)).where(
            Report.type == report_type,
            Report.status == ReportStatus.PUBLISHED.value,
        )
        if teacher_ids:
            stmt = stmt.where(Report.teacher_id.in_(teacher_ids))
        if s_start is not None:
            stmt = stmt.where(Report.period_start >= s_start)
        if s_end is not None:
            stmt = stmt.where(Report.period_start <= s_end)
        return db.scalar(stmt) or 0

    daily_submitted = _published_count(ReportType.DAILY.value)
    weekly_submitted = _published_count(ReportType.WEEKLY.value)

    # 应提交天数/周数：周期内按周（start~end）计算——日报按自然日、周报按周一为周期单元
    if start is not None and end is not None and teacher_count:
        day_count = (s_end.date() - s_start.date()).days + 1
        daily_due = teacher_count * day_count
        # 周报：周期内周一（每天被视为其所在周）数，约等于天数/7 向上取整
        week_count = max(1, (day_count + 6) // 7)
        weekly_due = teacher_count * week_count
    else:
        daily_due = weekly_due = 0

    return {
        "teacher_count": teacher_count,
        "daily_due": daily_due,
        "daily_submitted": daily_submitted,
        "weekly_due": weekly_due,
        "weekly_submitted": weekly_submitted,
    }


def compute_weekly_stats(
    db: Session, *, teacher_id: uuid.UUID, start: datetime, end: datetime
) -> dict:
    """周报自动统计（整周口径，与排课/考勤模块数据一致）。

    - 排课节数 schedules = 本周非取消排课数（待上 + 已完成）
    - 应到学员人次 expected_attendance = 本周各排课对应班级的在册学员数之和
    - 上课人次 attended = 本周排课中「已到」人数
    - 缺课人次 leave = 本周排课中「请假」人数
    - 出勤率 = 上课人次 / 应到人次
    - 应消耗课时 = 应到人次×2；实际消耗课时 = 已到人次×2（同考勤划课时，请假不计）
    - 达标率 = 实际消耗课时 / 应消耗课时
    - 缺课学员 = 本周有请假记录的去重学员名
    - 新增学员 = 本周创建且状态为在读/停课的学员数
    """
    s_start, s_end = _day_start(start), _day_end(end)
    sched_ids = _period_sched_ids(
        db, teacher_id=teacher_id, s_start=s_start, s_end=s_end
    )
    attended = 0
    leave = 0
    absent_student_ids: set[uuid.UUID] = set()
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
                absent_student_ids.add(sid)
    absent_students: list[str] = []
    if absent_student_ids:
        absent_students = list(
            db.scalars(
                select(Student.name).where(Student.id.in_(absent_student_ids)).order_by(Student.name)
            )
        )
    new_students = (
        db.scalar(
            select(func.count(Student.id)).where(
                Student.created_at >= s_start,
                Student.created_at <= s_end,
                Student.status.in_([StudentStatus.ACTIVE.value, StudentStatus.STOPPED.value]),
            )
        )
        or 0
    )
    expected_attendance = _expected_attendance(db, sched_ids)
    expected_lessons = expected_attendance * 2
    consumed_lessons = attended * 2
    return {
        "schedules": len(sched_ids),
        "expected_attendance": expected_attendance,
        "attended": attended,
        "leave": leave,
        "attendance_rate": round(attended / expected_attendance, 4) if expected_attendance else 0.0,
        "absent_students": absent_students,
        "new_students": new_students,
        # 课时口径（每节排课扣 2 课时）：
        # 应消耗课时 = 排课应到学员人次 × 2；实际消耗课时 = 已到学员人次 × 2（请假不计）
        "expected_lessons": expected_lessons,
        "consumed_lessons": consumed_lessons,
        "achievement_rate": (
            round(consumed_lessons / expected_lessons, 4) if expected_lessons else 0.0
        ),
    }


def compute_daily_stats(
    db: Session, *, teacher_id: uuid.UUID, day: datetime
) -> dict:
    """日报统计（单日，口径同周报）：排课节数/应到/上课/缺课/出勤/达标/应耗与实耗课时。"""
    s_start, s_end = _day_start(day), _day_end(day)
    sched_ids = _period_sched_ids(
        db, teacher_id=teacher_id, s_start=s_start, s_end=s_end
    )
    attended = 0
    leave = 0
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
    expected_attendance = _expected_attendance(db, sched_ids)
    expected_lessons = expected_attendance * 2
    consumed_lessons = attended * 2
    return {
        "schedules": len(sched_ids),
        "expected_attendance": expected_attendance,
        "attended": attended,
        "leave": leave,
        "attendance_rate": (
            round(attended / expected_attendance, 4) if expected_attendance else 0.0
        ),
        "expected_lessons": expected_lessons,
        "consumed_lessons": consumed_lessons,
        "achievement_rate": (
            round(consumed_lessons / expected_lessons, 4) if expected_lessons else 0.0
        ),
    }


def _period_sched_ids(
    db: Session, *, teacher_id: uuid.UUID, s_start: datetime, s_end: datetime
) -> list[uuid.UUID]:
    """期间教师的所有非取消排课 id（待上 scheduled + 已完成 completed，不含已取消）。"""
    return list(
        db.scalars(
            select(Schedule.id).where(
                Schedule.teacher_id == teacher_id,
                Schedule.status != ScheduleStatus.CANCELLED.value,
                Schedule.start_time >= s_start,
                Schedule.start_time <= s_end,
            )
        )
    )


def _expected_attendance(db: Session, sched_ids: list[uuid.UUID]) -> int:
    """应到学员数（人次）= 各排课对应班级的在册学员数之和（按节累计）。"""
    if not sched_ids:
        return 0
    rows = db.execute(
        select(Schedule.class_id).where(Schedule.id.in_(sched_ids))
    ).all()
    class_ids = [cid for (cid,) in rows]
    if not class_ids:
        return 0
    uniq_class_ids = list(dict.fromkeys(class_ids))
    counts = db.execute(
        select(StudentClass.class_id, func.count(StudentClass.student_id))
        .where(StudentClass.class_id.in_(uniq_class_ids))
        .group_by(StudentClass.class_id)
    ).all()
    by_class = {cid: n for cid, n in counts}
    return sum(by_class.get(cid, 0) for cid in class_ids)


def _lesson_volumes(
    db: Session, *, teacher_id: uuid.UUID, s_start: datetime, s_end: datetime
) -> tuple[int, int]:
    """课时量口径（供季度/年度/月度等复用，与日报/周报一致）：

    - 应消耗课时 = 期间非取消排课班级在册学员总数 × 2（应到 × 2）
    - 实际消耗课时 = 期间排课中「已到」学员数 × 2（请假/未标不计，同考勤划课时）
    """
    sched_ids = _period_sched_ids(
        db, teacher_id=teacher_id, s_start=s_start, s_end=s_end
    )
    expected_lessons = _expected_attendance(db, sched_ids) * 2
    attended = (
        db.scalar(
            select(func.count()).where(
                Attendance.schedule_id.in_(sched_ids),
                Attendance.status == AttendanceStatus.ATTENDED.value,
            )
        )
        if sched_ids
        else 0
    ) or 0
    return expected_lessons, attended * 2


def collect_daily_material(
    db: Session, *, teacher_id: uuid.UUID, day: datetime
) -> dict:
    """日报 AI 素材：当日该教师的全部非取消排课（含未上/已完成）及考勤统计。

    与日报统计口径一致：排课节数 = 非取消排课数，未上课的课程 attended/leave 为 0。
    """
    s_start, s_end = _day_start(day), _day_end(day)
    scheds = list(
        db.scalars(
            select(Schedule)
            .where(
                Schedule.status != ScheduleStatus.CANCELLED.value,
                Schedule.teacher_id == teacher_id,
                Schedule.start_time >= s_start,
                Schedule.start_time <= s_end,
            )
            .order_by(Schedule.start_time)
        )
    )
    courses = []
    for s in scheds:
        sched_id = s.id
        attend_rows = db.execute(
            select(Attendance.status, func.count()).where(
                Attendance.schedule_id == sched_id
            ).group_by(Attendance.status)
        ).all()
        status_counts = {st: n for st, n in attend_rows}
        courses.append(
            {
                "time": s.start_time.strftime("%H:%M"),
                "class_name": s.schedule_class.name if s.schedule_class else "",
                "subject": s.schedule_class.subject if s.schedule_class else "",
                "attended": status_counts.get(AttendanceStatus.ATTENDED.value, 0),
                "leave": status_counts.get(AttendanceStatus.LEAVE.value, 0),
            }
        )
    return {"courses": courses}


def compute_period_stats(
    db: Session, *, teacher_id: uuid.UUID, start: datetime, end: datetime
) -> dict:
    """季度/年度总结聚合统计。

    - 教学量：期间已完成排课数、上课人次、缺课人次、出勤率
    - 课时与达标：应耗课时（应开庭次）、消耗课时（已上庭次）、达标率
    - 当前学员数：该教师名下班级在读学员数（去重）
    - 周报：期间已发布周报数（作为文字素材来源）
    - 新增学员、缺课学员名单
    """
    s_start, s_end = _day_start(start), _day_end(end)

    # 该教师名下班级的学员（去重）
    own_class_ids = list(
        db.scalars(
            select(Class.id).where(
                Class.teacher_id == teacher_id, Class.status == StudentStatus.ACTIVE.value
            )
        )
    )
    student_ids: set[uuid.UUID] = set()
    if own_class_ids:
        student_ids.update(
            db.scalars(
                select(StudentClass.student_id).where(
                    StudentClass.class_id.in_(own_class_ids)
                )
            ).all()
        )
    # 补充：期间该教师已带教（有考勤）的学员（班级未分配教师时也能统计到）
    taught_sched_ids = list(
        db.scalars(
            select(Schedule.id).where(
                Schedule.teacher_id == teacher_id,
                Schedule.status == ScheduleStatus.COMPLETED.value,
                Schedule.start_time >= s_start,
                Schedule.start_time <= s_end,
            )
        )
    )
    if taught_sched_ids:
        student_ids.update(
            db.scalars(
                select(Attendance.student_id).where(
                    Attendance.schedule_id.in_(taught_sched_ids)
                )
            ).all()
        )
    current_students = len(student_ids)

    # 应耗课时 = 期间应开庭次应到学员数×2（请假不计）；消耗课时 = 已完成排课「已到」学员数×2
    expected_lessons, consumed_lessons = _lesson_volumes(
        db, teacher_id=teacher_id, s_start=s_start, s_end=s_end
    )

    sched_ids = list(
        db.scalars(
            select(Schedule.id).where(
                Schedule.status == ScheduleStatus.COMPLETED.value,
                Schedule.teacher_id == teacher_id,
                Schedule.start_time >= s_start,
                Schedule.start_time <= s_end,
            )
        )
    )
    attended = 0
    leave = 0
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
    total_att = attended + leave
    absent_students: list[str] = []
    if absent_ids:
        absent_students = list(
            db.scalars(
                select(Student.name).where(Student.id.in_(absent_ids)).order_by(Student.name)
            )
        )
    new_students = (
        db.scalar(
            select(func.count(Student.id)).where(
                Student.created_at >= s_start,
                Student.created_at <= s_end,
                Student.status.in_([StudentStatus.ACTIVE.value, StudentStatus.STOPPED.value]),
            )
        )
        or 0
    )
    weekly_count = (
        db.scalar(
            select(func.count(Report.id)).where(
                Report.type == ReportType.WEEKLY.value,
                Report.teacher_id == teacher_id,
                Report.status == ReportStatus.PUBLISHED.value,
                Report.period_start >= s_start,
                Report.period_start <= s_end,
            )
        )
        or 0
    )
    return {
        "schedules": len(sched_ids),
        "attended": attended,
        "leave": leave,
        "attendance_rate": round(attended / total_att, 4) if total_att else 0.0,
        "absent_students": absent_students,
        "new_students": new_students,
        "weekly_count": weekly_count,
        # 新增：当前学员/应耗课时/消耗课时/达标率
        "current_students": current_students,
        "expected_lessons": expected_lessons,
        "consumed_lessons": consumed_lessons,
        "achievement_rate": round(consumed_lessons / expected_lessons, 4)
        if expected_lessons
        else 0.0,
    }


def collect_period_material(
    db: Session, *, teacher_id: uuid.UUID, start: datetime, end: datetime
) -> list[dict]:
    """季度/年度总结素材：周期内已发布周报（总结/亮点/计划）。"""
    items = list_published_weeklies(db, teacher_id=teacher_id, start=start, end=end)
    return [
        {
            "week": f"{r.period_start.strftime('%m-%d')}~{r.period_end.strftime('%m-%d')}",
            "summary": (r.content or {}).get("summary"),
            "highlights": (r.content or {}).get("highlights"),
            "problems": (r.content or {}).get("problems"),
            "next_plan": (r.content or {}).get("next_plan"),
        }
        for r in items
    ]


def list_published_weeklies(
    db: Session, *, teacher_id: uuid.UUID, start: datetime, end: datetime
) -> list[Report]:
    """周期内已发布周报（按 period_start 落入区间），供季/年 rollup 与素材使用。"""
    s_start, s_end = _day_start(start), _day_end(end)
    return list(
        db.scalars(
            select(Report).where(
                Report.type == ReportType.WEEKLY.value,
                Report.teacher_id == teacher_id,
                Report.status == ReportStatus.PUBLISHED.value,
                Report.period_start >= s_start,
                Report.period_start <= s_end,
            ).order_by(Report.period_start)
        )
    )


def list_published_quarterlies(
    db: Session, *, teacher_id: uuid.UUID, start: datetime, end: datetime
) -> list[Report]:
    """年度周期内已发布季度总结（按 period_start 落入区间），供年度 AI 聚合与 PPT 门禁使用。

    区间两侧各放宽 1 天：naive 入参与 timestamptz 存量在 PG session 时区解释下
    可能差出数小时（如 Q1 的 01-01 00:00），放宽后 Q1/Q4 边界不再被丢掉。
    年度窗口本身是整年，多 1 天不影响正确性。
    """
    s_start, s_end = _day_start(start) - timedelta(days=1), _day_end(end) + timedelta(days=1)
    return list(
        db.scalars(
            select(Report).where(
                Report.type == ReportType.QUARTERLY.value,
                Report.teacher_id == teacher_id,
                Report.status == ReportStatus.PUBLISHED.value,
                Report.period_start >= s_start,
                Report.period_start <= s_end,
            ).order_by(Report.period_start)
        )
    )


def rollup_weekly_to_period(
    weeklies: list[Report], *, current_students: int = 0
) -> dict:
    """把一批已发布周报的 stats 聚合成期间统计（季度/年度口径）。

    - 教学量/课时直接求和；出勤率/达标率按总量重算（不平均平均值）
    - 缺课名单按出现频次取 Top5；weekly_count = 周报篇数
    - current_students 无法从周报推导，由调用方传入（种子/预览用真实值）
    """
    from collections import Counter

    schedules = 0
    expected = 0
    attended = 0
    leave = 0
    expected_lessons = 0
    consumed_lessons = 0
    new_students = 0
    absent_counter: Counter[str] = Counter()
    for r in weeklies:
        s = r.stats or {}
        schedules += int(s.get("schedules") or 0)
        expected += int(s.get("expected_attendance") or 0)
        attended += int(s.get("attended") or 0)
        leave += int(s.get("leave") or 0)
        expected_lessons += int(s.get("expected_lessons") or 0)
        consumed_lessons += int(s.get("consumed_lessons") or 0)
        new_students += int(s.get("new_students") or 0)
        for name in s.get("absent_students") or []:
            if name:
                absent_counter[str(name)] += 1
    total_att = attended + leave
    return {
        "schedules": schedules,
        "attended": attended,
        "leave": leave,
        "attendance_rate": round(attended / expected, 4) if expected else (
            round(attended / total_att, 4) if total_att else 0.0
        ),
        "absent_students": [n for n, _ in absent_counter.most_common(5)],
        "new_students": new_students,
        "weekly_count": len(weeklies),
        "current_students": current_students,
        "expected_lessons": expected_lessons,
        "consumed_lessons": consumed_lessons,
        "achievement_rate": round(consumed_lessons / expected_lessons, 4)
        if expected_lessons
        else 0.0,
    }


def rollup_period_to_annual(
    quarters: list[Report], *, current_students: int = 0
) -> dict:
    """把季度总结的 stats 聚合成年度统计（年度只读季度，不直接读周）。

    - quarters 按时间升序传入（Q1..Q4）；current_students 取期末值（最后一篇非零值），
      无有效值时回退到调用方传入值（语义：年末在读规模，而非年内峰值）。
    """
    from collections import Counter

    schedules = 0
    attended = 0
    leave = 0
    expected_lessons = 0
    consumed_lessons = 0
    new_students = 0
    weekly_count = 0
    absent_counter: Counter[str] = Counter()
    terminal_current = current_students
    for r in quarters:
        s = r.stats or {}
        schedules += int(s.get("schedules") or 0)
        attended += int(s.get("attended") or 0)
        leave += int(s.get("leave") or 0)
        expected_lessons += int(s.get("expected_lessons") or 0)
        consumed_lessons += int(s.get("consumed_lessons") or 0)
        new_students += int(s.get("new_students") or 0)
        weekly_count += int(s.get("weekly_count") or 0)
        if int(s.get("current_students") or 0):
            terminal_current = int(s.get("current_students") or 0)
        for name in s.get("absent_students") or []:
            if name:
                absent_counter[str(name)] += 1
    total_att = attended + leave
    return {
        "schedules": schedules,
        "attended": attended,
        "leave": leave,
        "attendance_rate": round(attended / total_att, 4) if total_att else 0.0,
        "absent_students": [n for n, _ in absent_counter.most_common(5)],
        "new_students": new_students,
        "weekly_count": weekly_count,
        "current_students": terminal_current,
        "expected_lessons": expected_lessons,
        "consumed_lessons": consumed_lessons,
        "achievement_rate": round(consumed_lessons / expected_lessons, 4)
        if expected_lessons
        else 0.0,
    }


def rollup_weekly_monthly(weeklies: list[Report]) -> list[dict]:
    """把周报按 period_start 所在月归集为月度折线点（整周归属起始月，不拆分）。"""
    from collections import defaultdict

    buckets: dict[str, list[Report]] = defaultdict(list)
    for r in weeklies:
        buckets[r.period_start.strftime("%Y-%m")].append(r)
    points: list[dict] = []
    for month in sorted(buckets):
        expected_lessons = 0
        consumed_lessons = 0
        new_students = 0
        attendance = 0
        for r in buckets[month]:
            s = r.stats or {}
            expected_lessons += int(s.get("expected_lessons") or 0)
            consumed_lessons += int(s.get("consumed_lessons") or 0)
            new_students += int(s.get("new_students") or 0)
            attendance += int(s.get("attended") or 0)
        points.append(
            {
                "month": month,
                "expected_lessons": expected_lessons,
                "consumed_lessons": consumed_lessons,
                "new_students": new_students,
                "attendance": attendance,
            }
        )
    return points


def _prev_equal_window(
    s_start: datetime, s_end: datetime
) -> tuple[datetime, datetime]:
    """上一对等期间窗口（季度=往前推同月数；年度=上一年同窗口）。"""
    n_months = max(1, (s_end.year - s_start.year) * 12 + (s_end.month - s_start.month) + 1)
    prev_end = s_start - timedelta(seconds=1)
    prev_start_month = prev_end.replace(day=1)
    for _ in range(n_months - 1):
        if prev_start_month.month == 1:
            prev_start_month = prev_start_month.replace(year=prev_start_month.year - 1, month=12)
        else:
            prev_start_month = prev_start_month.replace(month=prev_start_month.month - 1)
    return _day_start(prev_start_month), prev_end


def _month_bounds(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """将期间按自然月切分为 (月初, 月末) 区间列表（闭区间起止）。"""
    months: list[tuple[datetime, datetime]] = []
    cur = datetime(start.year, start.month, 1, tzinfo=start.tzinfo or BEIJING)
    stop = datetime(end.year, end.month, 1, tzinfo=end.tzinfo or BEIJING)
    while cur <= stop:
        if cur.month == 12:
            nxt = datetime(cur.year + 1, 1, 1, tzinfo=cur.tzinfo)
        else:
            nxt = datetime(cur.year, cur.month + 1, 1, tzinfo=cur.tzinfo)
        month_start = max(cur, _day_start(start))
        month_end = min(nxt - timedelta(seconds=1), _day_end(end))
        months.append((month_start, month_end))
        cur = nxt
    return months


def compute_period_monthly(
    db: Session, *, teacher_id: uuid.UUID, start: datetime, end: datetime
) -> list[dict]:
    """折线图数据：期间内每个月应耗课时/消耗课时/新增学员/上课人次。"""
    s_start, s_end = _day_start(start), _day_end(end)
    results: list[dict] = []
    for m_start, m_end in _month_bounds(s_start, s_end):
        expected_lessons, consumed_lessons = _lesson_volumes(
            db, teacher_id=teacher_id, s_start=m_start, s_end=m_end
        )
        sched_ids = list(
            db.scalars(
                select(Schedule.id).where(
                    Schedule.status == ScheduleStatus.COMPLETED.value,
                    Schedule.teacher_id == teacher_id,
                    Schedule.start_time >= m_start,
                    Schedule.start_time <= m_end,
                )
            )
        )
        attendance = 0
        if sched_ids:
            attendance = (
                db.scalar(
                    select(func.count()).where(
                        Attendance.schedule_id.in_(sched_ids),
                        Attendance.status == AttendanceStatus.ATTENDED.value,
                    )
                )
                or 0
            )
        new_students = (
            db.scalar(
                select(func.count(Student.id)).where(
                    Student.created_at >= m_start,
                    Student.created_at <= m_end,
                    Student.status.in_(
                        [StudentStatus.ACTIVE.value, StudentStatus.STOPPED.value]
                    ),
                )
            )
            or 0
        )
        results.append(
            {
                "month": m_start.strftime("%Y-%m"),
                "expected_lessons": expected_lessons,
                "consumed_lessons": consumed_lessons,
                "new_students": new_students,
                "attendance": attendance,
            }
        )
    return results


def compute_period_comparison(
    db: Session, *, teacher_id: uuid.UUID, start: datetime, end: datetime
) -> dict:
    """柱状图数据（课时消耗对比）：

    - labels：当前期间各月份标签（如 1月 / 2月 …）
    - current：当前期间每个月消耗课时
    - previous：上一对等期间（季度=上一季度；年度=上一年）每个月消耗课时
    """
    s_start, s_end = _day_start(start), _day_end(end)
    # 上一对等期间：以相同月数为窗口，结束于 s_start 前一天
    prev_start, prev_end = _prev_equal_window(s_start, s_end)

    def consumed_by_month(begin: datetime, stop: datetime) -> tuple[list[str], list[int]]:
        labels: list[str] = []
        values: list[int] = []
        for m_start, m_end in _month_bounds(begin, stop):
            _, consumed = _lesson_volumes(db, teacher_id=teacher_id, s_start=m_start, s_end=m_end)
            labels.append(f"{m_start.month}月")
            values.append(consumed)
        return labels, values

    _, cur_values = consumed_by_month(s_start, s_end)
    prev_labels, prev_values = consumed_by_month(prev_start, prev_end)
    # 当前标签用当前期间的月份（保持与 prev 窗口一致取月数）
    cur_labels = [f"{m_start.month}月" for m_start, _ in _month_bounds(s_start, s_end)]
    return {
        "labels": cur_labels,
        "current": cur_values,
        "previous_labels": prev_labels,
        "previous": prev_values,
    }


def compute_period_comparison_from_weeklies(
    db: Session, *, teacher_id: uuid.UUID, start: datetime, end: datetime
) -> dict:
    """柱状图数据（周报口径）：当前 vs 上一对等期间逐月消耗课时，按周报落点月份归集。"""
    from collections import defaultdict

    s_start, s_end = _day_start(start), _day_end(end)
    prev_start, prev_end = _prev_equal_window(s_start, s_end)

    def consumed_map(begin: datetime, stop: datetime) -> dict[str, int]:
        weeklies = list_published_weeklies(
            db, teacher_id=teacher_id, start=begin, end=stop
        )
        acc: dict[str, int] = defaultdict(int)
        for r in weeklies:
            s = r.stats or {}
            acc[r.period_start.strftime("%Y-%m")] += int(s.get("consumed_lessons") or 0)
        return acc

    cur_map = consumed_map(s_start, s_end)
    prev_map = consumed_map(prev_start, prev_end)
    cur_labels = [f"{m_start.month}月" for m_start, _ in _month_bounds(s_start, s_end)]
    prev_labels = [f"{m_start.month}月" for m_start, _ in _month_bounds(prev_start, prev_end)]
    cur_keys = [m_start.strftime("%Y-%m") for m_start, _ in _month_bounds(s_start, s_end)]
    prev_keys = [m_start.strftime("%Y-%m") for m_start, _ in _month_bounds(prev_start, prev_end)]
    return {
        "labels": cur_labels,
        "current": [cur_map.get(k, 0) for k in cur_keys],
        "previous_labels": prev_labels,
        "previous": [prev_map.get(k, 0) for k in prev_keys],
    }
