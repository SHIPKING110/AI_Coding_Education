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
    """已完成排课及其反馈状态（供排课下拉展示「待反馈/已反馈」标记）。"""
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

    result: list[dict] = []
    for s in schedules:
        attend_rows = list(
            db.scalars(
                select(Attendance).where(
                    Attendance.schedule_id == s.id,
                    Attendance.status == AttendanceStatus.ATTENDED.value,
                )
            )
            .unique()
            .all()
        )
        attended = len(attend_rows)
        saved = feedbacks_saved(db, s.id)
        published = feedbacks_published(db, s.id)
        result.append(
            {
                "id": s.id,
                "class_id": s.class_id,
                "class_name": s.schedule_class.name if s.schedule_class else None,
                "subject": s.schedule_class.subject if s.schedule_class else None,
                "teacher_name": s.teacher.name if s.teacher else None,
                "campus": (s.teacher.campus if s.teacher else None),
                "start_time": s.start_time,
                "end_time": s.end_time,
                "attended": attended,
                "feedback_done": published,
                "saved_draft": saved - published,
                "all_done": attended > 0 and published >= attended,
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
    - 已反馈(feedback_done): 这些排课的反馈条数
    - 待反馈(pending): 应到 − 已反馈（仍缺反馈的学员）
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

    feedback_done = (
        db.scalar(
            select(func.count(Feedback.id)).where(
                Feedback.schedule_id.in_(sids),
                Feedback.status == FeedbackStatus.PUBLISHED.value,
            )
        )
        or 0
    )

    # 待反馈 = 签到(attended) 但尚未【发送】反馈的学员；请假(leave)学员不计入待反馈（M3 增强）
    attended_ids = {
        r[0]
        for r in db.execute(
            select(Attendance.student_id).where(
                Attendance.schedule_id.in_(sids),
                Attendance.status == AttendanceStatus.ATTENDED.value,
            )
        )
    }
    feedback_student_ids = set(
        db.scalars(
            select(Feedback.student_id).where(
                Feedback.schedule_id.in_(sids),
                Feedback.status == FeedbackStatus.PUBLISHED.value,
            )
        ).all()
    )
    pending = len(attended_ids - feedback_student_ids)

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
