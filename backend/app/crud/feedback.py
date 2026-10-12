import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enrollment import Student
from app.models.feedback import Feedback, FeedbackStatus
from app.models.schedule import Attendance, AttendanceStatus, Schedule, ScheduleStatus


def get(db: Session, feedback_id: uuid.UUID) -> Feedback | None:
    return db.get(Feedback, feedback_id)


def feedbacks_saved(db: Session, schedule_id: uuid.UUID) -> int:
    """某次排课已有反馈条数（草稿或已发布均算，用于进度显示）。"""
    return (
        db.scalar(select(func.count(Feedback.id)).where(Feedback.schedule_id == schedule_id)) or 0
    )


def feedbacks_published(db: Session, schedule_id: uuid.UUID) -> int:
    """某次排课【已发送】反馈条数（仅 published 计入「已反馈」）。"""
    return (
        db.scalar(
            select(func.count(Feedback.id)).where(
                Feedback.schedule_id == schedule_id,
                Feedback.status == FeedbackStatus.PUBLISHED.value,
            )
        )
        or 0
    )


def all_saved_by_schedule(db: Session, schedule_id: uuid.UUID) -> bool:
    """某次排课是否全部【签到】学员都已有反馈。"""
    attend_rows = list(
        db.scalars(
            select(Attendance).where(
                Attendance.schedule_id == schedule_id,
                Attendance.status == AttendanceStatus.ATTENDED.value,
            )
        )
        .unique()
        .all()
    )
    if not attend_rows:
        return False
    saved_ids = set(
        db.scalars(select(Feedback.student_id).where(Feedback.schedule_id == schedule_id)).all()
    )
    return all(a.student_id in saved_ids for a in attend_rows)


def _completed_schedule_ids(
    db: Session,
    *,
    campus: str | None,
    teacher_id: uuid.UUID | None,
    class_id: uuid.UUID | None,
    start: datetime | None,
    end: datetime | None,
) -> list[uuid.UUID]:
    """符合筛选的【已完成】(completed) 排课 id。"""
    stmt = select(Schedule.id).where(Schedule.status == ScheduleStatus.COMPLETED.value)
    if start is not None:
        stmt = stmt.where(Schedule.start_time >= start)
    if end is not None:
        stmt = stmt.where(Schedule.start_time <= end)
    if class_id is not None:
        stmt = stmt.where(Schedule.class_id == class_id)
    if teacher_id is not None:
        stmt = stmt.where(Schedule.teacher_id == teacher_id)
    if campus:
        stmt = stmt.join(Schedule.teacher).where(Schedule.teacher.has(campus=campus))
    return list(db.scalars(stmt).unique().all())


def _group_key(s: Schedule) -> tuple:
    """同一班级同一天只反馈一次：分组键 (class_id, 日期)；无班级(体验课)按单节处理。"""
    if s.class_id is None:
        return ("single", s.id)
    st = s.start_time
    day = st.date().isoformat() if hasattr(st, "date") else str(st)[:10]
    return ("class-day", s.class_id, day)


def group_schedule_ids(db: Session, s: Schedule) -> list[uuid.UUID]:
    """与某排课同组（同一班级同一天、已完成）的排课 id 集合（含自身，按时间升序）。

    无班级(体验课)只返回自身，避免不同学员串户。
    """
    if s.class_id is None:
        return [s.id]
    day = s.start_time.date() if hasattr(s.start_time, "date") else None
    if day is None:
        return [s.id]
    rows = db.execute(
        select(Schedule.id, Schedule.start_time).where(
            Schedule.status == ScheduleStatus.COMPLETED.value,
            Schedule.class_id == s.class_id,
            func.date(Schedule.start_time) == day,
        )
    ).all()
    ordered = sorted(rows, key=lambda r: r[1])
    ids = [r[0] for r in ordered] or [s.id]
    if s.id not in ids:
        ids.append(s.id)
    return ids


def completed_schedules_with_status(
    db: Session,
    *,
    campus: str | None = None,
    teacher_id: uuid.UUID | None = None,
    class_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 200,
) -> list[dict]:
    """已完成排课及其反馈状态（供排课选择器展示「待反馈/已反馈」标记）。

    同一班级同一天的多节课合并为一条（一天只反馈一次）：attended/feedback_done/
    saved_draft 按组内去重后的学员集合计算；id 取组内最早一节（新建反馈落到该节）。
    """
    stmt = (
        select(Schedule)
        .options(selectinload(Schedule.schedule_class), selectinload(Schedule.teacher))
        .where(Schedule.status == ScheduleStatus.COMPLETED.value)
    )
    if start is not None:
        stmt = stmt.where(Schedule.start_time >= start)
    if end is not None:
        stmt = stmt.where(Schedule.start_time <= end)
    if class_id is not None:
        stmt = stmt.where(Schedule.class_id == class_id)
    if teacher_id is not None:
        stmt = stmt.where(Schedule.teacher_id == teacher_id)
    if campus:
        stmt = stmt.join(Schedule.teacher).where(Schedule.teacher.has(campus=campus))
    stmt = stmt.order_by(Schedule.start_time.desc()).limit(limit)
    schedules = list(db.scalars(stmt).unique().all())

    # 按 (班级, 天) 分组，保持时间倒序
    groups: dict[tuple, list[Schedule]] = {}
    for s in schedules:
        groups.setdefault(_group_key(s), []).append(s)

    result: list[dict] = []
    for _key, items in groups.items():
        ordered = sorted(items, key=lambda x: x.start_time)
        rep = ordered[0]
        gids = [x.id for x in ordered]
        attend_rows = list(
            db.scalars(
                select(Attendance).where(
                    Attendance.schedule_id.in_(gids),
                    Attendance.status == AttendanceStatus.ATTENDED.value,
                )
            )
            .unique()
            .all()
        )
        attended_ids = {a.student_id for a in attend_rows}
        published_ids = {
            r[0]
            for r in db.execute(
                select(Feedback.student_id).where(
                    Feedback.schedule_id.in_(gids),
                    Feedback.status == FeedbackStatus.PUBLISHED.value,
                )
            ).all()
        }
        draft_ids = {
            r[0]
            for r in db.execute(
                select(Feedback.student_id).where(
                    Feedback.schedule_id.in_(gids),
                    Feedback.status == FeedbackStatus.DRAFT.value,
                )
            ).all()
        } - published_ids
        result.append(
            {
                "id": rep.id,
                "class_id": rep.class_id,
                "class_name": rep.schedule_class.name if rep.schedule_class else None,
                "subject": rep.schedule_class.subject if rep.schedule_class else None,
                "teacher_name": rep.teacher.name if rep.teacher else None,
                "campus": (rep.teacher.campus if rep.teacher else None),
                "start_time": rep.start_time,
                "end_time": max(x.end_time for x in ordered),
                "attended": len(attended_ids),
                "feedback_done": len(published_ids),
                "saved_draft": len(draft_ids),
                "all_done": bool(attended_ids) and published_ids >= attended_ids,
                "group_count": len(ordered),
                "schedule_ids": gids,
                "day": rep.start_time.date().isoformat()
                if hasattr(rep.start_time, "date")
                else str(rep.start_time)[:10],
            }
        )
    return result


def compute_stats(
    db: Session,
    *,
    campus: str | None = None,
    teacher_id: uuid.UUID | None = None,
    class_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """反馈统计：应到/签到/请假/已反馈/待反馈，按 校区/教师/班级/日期区间 聚合。

    - 应到(expected): 这些已完成排课的考勤行总数（全体应出席学员）
    - 签到(attended): 考勤状态 = attended 的行数
    - 请假(leave):    考勤状态 = leave 的行数
    - 已反馈(feedback_done): 按 (班级, 天, 学员) 去重后的已发送数（同一班级一天多节只算一次）
    - 待反馈(pending): 按 (班级, 天, 学员) 去重后，签到但尚未【发送】反馈的学员；
      请假(leave)学员不计入待反馈
    """
    sids = _completed_schedule_ids(
        db,
        campus=campus,
        teacher_id=teacher_id,
        class_id=class_id,
        start=start,
        end=end,
    )
    if not sids:
        return {
            "schedule_count": 0,
            "expected": 0,
            "attended": 0,
            "leave": 0,
            "feedback_done": 0,
            "pending": 0,
        }

    attend_rows = db.execute(
        select(Attendance.status).where(Attendance.schedule_id.in_(sids))
    ).all()
    expected = len(attend_rows)
    attended = sum(1 for (st,) in attend_rows if st == AttendanceStatus.ATTENDED.value)
    leave = sum(1 for (st,) in attend_rows if st == AttendanceStatus.LEAVE.value)

    # 同一班级同一天多节课只反馈一次：已反馈/待反馈按 (班级, 天, 学员) 去重。
    # 无班级(体验课)按单节排课去重，避免不同学员串户。
    sched_rows = db.execute(
        select(Schedule.id, Schedule.class_id, Schedule.start_time).where(
            Schedule.id.in_(sids)
        )
    ).all()
    group_of: dict[uuid.UUID, tuple] = {}
    for sid, cid, st in sched_rows:
        if cid is None:
            group_of[sid] = ("single", sid)
        else:
            day = st.date().isoformat() if hasattr(st, "date") else str(st)[:10]
            group_of[sid] = ("class-day", cid, day)

    attended_keys = {
        (group_of.get(sid, ("single", sid)), stu)
        for (sid, stu) in db.execute(
            select(Attendance.schedule_id, Attendance.student_id).where(
                Attendance.schedule_id.in_(sids),
                Attendance.status == AttendanceStatus.ATTENDED.value,
            )
        ).all()
    }
    published_keys = {
        (group_of.get(sid, ("single", sid)), stu)
        for (sid, stu) in db.execute(
            select(Feedback.schedule_id, Feedback.student_id).where(
                Feedback.schedule_id.in_(sids),
                Feedback.status == FeedbackStatus.PUBLISHED.value,
            )
        ).all()
    }
    feedback_done = len(published_keys)

    # 待反馈 = 签到(attended) 但尚未【发送】反馈的学员；请假(leave)学员不计入待反馈（M3 增强）
    pending = len(attended_keys - published_keys)

    return {
        "schedule_count": len(sids),
        "expected": expected,
        "attended": attended,
        "leave": leave,
        "feedback_done": feedback_done,
        "pending": max(pending, 0),
    }


def list_by_schedule(
    db: Session, schedule_id: uuid.UUID, *, include_draft: bool = True
) -> list[Feedback]:
    stmt = select(Feedback).where(Feedback.schedule_id == schedule_id)
    if not include_draft:
        stmt = stmt.where(Feedback.status != FeedbackStatus.DRAFT.value)
    stmt = stmt.options(
        selectinload(Feedback.student),
        selectinload(Feedback.student).selectinload(Student.classes),
    )
    return list(db.scalars(stmt).unique().all())


def list_by_schedules(
    db: Session, schedule_ids: list[uuid.UUID], *, include_draft: bool = True
) -> list[Feedback]:
    """多节排课（同一班级同一天组）的全部反馈，用于编辑器跨节匹配。"""
    if not schedule_ids:
        return []
    stmt = select(Feedback).where(Feedback.schedule_id.in_(schedule_ids))
    if not include_draft:
        stmt = stmt.where(Feedback.status != FeedbackStatus.DRAFT.value)
    stmt = stmt.options(
        selectinload(Feedback.student),
        selectinload(Feedback.student).selectinload(Student.classes),
    )
    return list(db.scalars(stmt).unique().all())


def list_history(
    db: Session,
    *,
    student_id: uuid.UUID | None = None,
    schedule_id: uuid.UUID | None = None,
    keyword: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Feedback]:
    """历史反馈查询（FR-FB-06）：按学员 / 排课 / 关键词（课题/标题/内容）过滤。"""
    stmt = select(Feedback)
    if student_id is not None:
        stmt = stmt.where(Feedback.student_id == student_id)
    if schedule_id is not None:
        stmt = stmt.where(Feedback.schedule_id == schedule_id)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            Feedback.title.ilike(like) | Feedback.topic.ilike(like) | Feedback.content.ilike(like)
        )
    stmt = stmt.options(
        selectinload(Feedback.student),
        selectinload(Feedback.schedule),
    )
    stmt = stmt.order_by(Feedback.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).unique().all())


def create(
    db: Session,
    *,
    schedule_id: uuid.UUID,
    student_id: uuid.UUID,
    title: str | None,
    topic: str | None,
    content: str | None,
    performance: str | None,
    evaluation: str | None,
    homework: str | None,
    media_urls: list[str],
) -> Feedback:
    fb = Feedback(
        schedule_id=schedule_id,
        student_id=student_id,
        title=title,
        topic=topic,
        content=content,
        performance=performance,
        evaluation=evaluation,
        homework=homework,
        media_urls=media_urls,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return fb


def update(
    db: Session,
    fb: Feedback,
    *,
    title: str | None,
    topic: str | None,
    content: str | None,
    performance: str | None,
    evaluation: str | None,
    homework: str | None,
    media_urls: list[str] | None,
) -> Feedback:
    if title is not None:
        fb.title = title
    if topic is not None:
        fb.topic = topic
    if content is not None:
        fb.content = content
    if performance is not None:
        fb.performance = performance
    if evaluation is not None:
        fb.evaluation = evaluation
    if homework is not None:
        fb.homework = homework
    if media_urls is not None:
        fb.media_urls = media_urls
    db.commit()
    db.refresh(fb)
    return fb


def publish(db: Session, fb: Feedback) -> Feedback:
    """发布（发送给家长）：草稿 -> 已发布，记录发布时间。"""
    fb.status = FeedbackStatus.PUBLISHED.value
    fb.published_at = datetime.now(UTC)
    db.commit()
    db.refresh(fb)
    return fb


def unpublish(db: Session, fb: Feedback) -> Feedback:
    """撤回（重新编辑）：已发布 -> 草稿，清除发布时间，供编辑后重新发送。"""
    fb.status = FeedbackStatus.DRAFT.value
    fb.published_at = None
    db.commit()
    db.refresh(fb)
    return fb
