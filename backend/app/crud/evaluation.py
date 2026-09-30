"""学员评估 CRUD + 周期素材收集（M6，FR-EV-01~05）。

素材 = 评估周期内该学员的全部教学足迹：
- 已发布课后反馈（课题/内容/课堂表现/作业）——评估内容的事实来源
- 考勤（上课人次/请假）+ 课时消耗
- 已批改作业得分率（若有）

评估记录：同一学员同一周期唯一（幂等创建 = 更新），BR-05 草稿→人工审核→发布。
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.assignment import Assignment, Submission, SubmissionStatus
from app.models.enrollment import Class, LessonRecord, Student, StudentStatus
from app.models.evaluation import ClassPpt, Evaluation, EvaluationStatus
from app.models.feedback import Feedback, FeedbackStatus
from app.models.schedule import Attendance, AttendanceStatus, Schedule, ScheduleStatus
from app.services.llm import clean_listish_text


def get(db: Session, evaluation_id: uuid.UUID) -> Evaluation | None:
    return db.get(Evaluation, evaluation_id)


def _find_existing(
    db: Session,
    *,
    student_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> Evaluation | None:
    return db.scalars(
        select(Evaluation).where(
            Evaluation.student_id == student_id,
            Evaluation.period_start == period_start,
            Evaluation.period_end == period_end,
        )
    ).first()


def upsert(
    db: Session,
    *,
    student_id: uuid.UUID,
    teacher_id: uuid.UUID,
    period_start: date,
    period_end: date,
    title: str | None,
    content: dict,
    stats: dict | None,
) -> Evaluation:
    """同一学员同周期仅一份：存在则更新，否则新建（幂等）。"""
    existing = _find_existing(
        db, student_id=student_id, period_start=period_start, period_end=period_end
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
    ev = Evaluation(
        student_id=student_id,
        teacher_id=teacher_id,
        period_start=period_start,
        period_end=period_end,
        title=title,
        content=content,
        stats=stats,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def update(
    db: Session,
    ev: Evaluation,
    *,
    title: str | None,
    content: dict | None,
    stats: dict | None = None,
) -> Evaluation:
    if title is not None:
        ev.title = title
    if content is not None:
        ev.content = {**ev.content, **content}
    if stats is not None:
        ev.stats = stats
    db.commit()
    db.refresh(ev)
    return ev


def set_ai_draft(db: Session, ev: Evaluation, draft: dict, model: str | None) -> Evaluation:
    """保存 AI 草稿：正文回填 content，原始稿快照存 ai_draft（审计/回填）。"""
    ev.content = {**(ev.content or {}), **{k: v for k, v in draft.items() if v is not None}}
    ev.ai_draft = {
        "content": draft,
        "model": model,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    db.commit()
    db.refresh(ev)
    return ev


def publish(db: Session, ev: Evaluation) -> Evaluation:
    """发布（随家长会发送家长端）：草稿 -> 已发布，可重复发布。"""
    ev.status = EvaluationStatus.PUBLISHED.value
    ev.published_at = datetime.now(UTC)
    db.commit()
    db.refresh(ev)
    return ev


def unpublish(db: Session, ev: Evaluation) -> Evaluation:
    """撤回：已发布 -> 草稿，供重新编辑。"""
    ev.status = EvaluationStatus.DRAFT.value
    ev.published_at = None
    db.commit()
    db.refresh(ev)
    return ev


def delete(db: Session, ev: Evaluation) -> None:
    db.delete(ev)
    db.commit()


def list_evaluations(
    db: Session,
    *,
    teacher_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    status: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Evaluation], int]:
    """评估列表（教师默认只看自己的；student/status/keyword 过滤，分页）。"""
    stmt = select(Evaluation)
    count_stmt = select(func.count(Evaluation.id))
    conds = []
    if teacher_id is not None:
        conds.append(Evaluation.teacher_id == teacher_id)
    if student_id is not None:
        conds.append(Evaluation.student_id == student_id)
    if status is not None:
        conds.append(Evaluation.status == status)
    if keyword:
        like = f"%{keyword}%"
        conds.append(Evaluation.title.ilike(like))
    if conds:
        stmt = stmt.where(*conds)
        count_stmt = count_stmt.where(*conds)
    stmt = (
        stmt.options(selectinload(Evaluation.student))
        .order_by(Evaluation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).unique().all())
    total = db.scalar(count_stmt) or 0
    return items, total


# ---------------------------------------------------------------------------
# 周期素材收集（评估 AI 生成的事实基础，FR-EV-01）
# ---------------------------------------------------------------------------

def _day_bounds(d: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(d, time.min, tzinfo=UTC),
        datetime.combine(d, time.max, tzinfo=UTC),
    )


def collect_period_stats(db: Session, *, student: Student, start: date, end: date) -> dict:
    """学员周期统计快照：上课人次/请假/出勤率/课时消耗/反馈数/作业得分率。"""
    start_dt, end_dt = _day_bounds(start)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)

    class_ids = [c.id for c in student.classes]

    # 考勤：该学员在周期内排课（限其班级）的出勤
    attended = leave = 0
    if class_ids:
        rows = db.execute(
            select(Attendance.status)
            .join(Schedule, Attendance.schedule_id == Schedule.id)
            .where(
                Attendance.student_id == student.id,
                Schedule.class_id.in_(class_ids),
                Schedule.start_time >= start_dt,
                Schedule.start_time < end_dt,
                Schedule.status != ScheduleStatus.CANCELLED.value,
            )
        ).all()
        for (st,) in rows:
            if st == AttendanceStatus.ATTENDED.value:
                attended += 1
            elif st == AttendanceStatus.LEAVE.value:
                leave += 1

    # 课时消耗
    consumed = (
        db.scalar(
            select(func.coalesce(func.sum(LessonRecord.delta), 0)).where(
                LessonRecord.student_id == student.id,
                LessonRecord.record_type == "consume",
                LessonRecord.created_at >= start_dt,
                LessonRecord.created_at < end_dt,
            )
        )
        or 0
    )

    # 已发布反馈
    feedbacks = list(
        db.scalars(
            select(Feedback)
            .where(
                Feedback.student_id == student.id,
                Feedback.status == FeedbackStatus.PUBLISHED.value,
                Feedback.created_at >= start_dt,
                Feedback.created_at < end_dt,
            )
            .order_by(Feedback.created_at)
        )
        .unique()
        .all()
    )

    # 已批改作业得分率（若有）
    homework_count = 0
    homework_score_total = 0
    homework_score_max = 0
    if class_ids:
        subs = list(
            db.scalars(
                select(Submission)
                .join(Assignment, Submission.assignment_id == Assignment.id)
                .where(
                    Submission.student_id == student.id,
                    Submission.status == SubmissionStatus.GRADED.value,
                    Assignment.class_id.in_(class_ids),
                    Submission.submitted_at.is_not(None),
                    Submission.submitted_at >= start_dt,
                    Submission.submitted_at < end_dt,
                )
            ).all()
        )
        homework_count = len(subs)
        for s in subs:
            homework_score_total += s.score or 0
            homework_score_max += s.total or 0

    total_attendance = attended + leave
    return {
        "attended": attended,
        "leave": leave,
        "attendance_rate": round(attended / total_attendance, 4) if total_attendance else 0.0,
        "consumed_lessons": abs(int(consumed)),
        "feedback_count": len(feedbacks),
        "homework_count": homework_count,
        "homework_score_rate": (
            round(homework_score_total / homework_score_max, 4) if homework_score_max else None
        ),
    }


def collect_material(db: Session, *, student: Student, start: date, end: date) -> dict:
    """组装评估素材：统计快照 + 班级 + 周期内已发布反馈明细（课题/内容/表现/作业）。

    供前端预览与 LLM prompt 使用；反馈缺失时提示教师先完善课后反馈。
    """
    stats = collect_period_stats(db, student=student, start=start, end=end)
    classes = [
        {
            "name": c.name,
            "subject": c.subject,
            "teacher_name": c.teacher.name if c.teacher else None,
        }
        for c in student.classes
    ]

    start_dt, _ = _day_bounds(start)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    feedbacks = list(
        db.scalars(
            select(Feedback)
            .options(selectinload(Feedback.schedule).selectinload(Schedule.schedule_class))
            .where(
                Feedback.student_id == student.id,
                Feedback.status == FeedbackStatus.PUBLISHED.value,
                Feedback.created_at >= start_dt,
                Feedback.created_at < end_dt,
            )
            .order_by(Feedback.created_at)
        )
        .unique()
        .all()
    )
    items = []
    for fb in feedbacks:
        class_name = (
            fb.schedule.schedule_class.name if fb.schedule and fb.schedule.schedule_class else None
        )
        items.append(
            {
                "date": fb.created_at.strftime("%Y-%m-%d"),
                "class_name": class_name,
                "topic": fb.topic,
                "content": fb.content,
                "performance": fb.performance,
                "evaluation": fb.evaluation,
                "homework": fb.homework,
            }
        )
    return {
        "student_name": student.name,
        "classes": classes,
        "stats": stats,
        "feedbacks": items,
    }


# ---------------------------------------------------------------------------
# 班级维度素材收集（M6 班级家长会 PPT：以班级为单位汇报全学员学习情况）
# ---------------------------------------------------------------------------

def collect_class_roster(
    db: Session, *, cls: Class, start: date, end: date
) -> dict:
    """班级学员名单 + 每人在该周期的评估生成状态（草稿/已发布/未生成）。

    周期按「重叠」匹配（评估覆盖期与所选周期有交集即视为已生成）；
    同一学员有多份重叠评估时优先展示已发布，其次最近更新的。
    未生成的学员供前端一键跳转评估编辑器补录。
    """
    students = [s for s in cls.students if s.status != StudentStatus.ARCHIVED.value]
    by_id: dict[uuid.UUID, dict] = {}
    if students:
        evals = list(
            db.scalars(
                select(Evaluation).where(
                    Evaluation.student_id.in_([s.id for s in students]),
                    Evaluation.period_start <= end,
                    Evaluation.period_end >= start,
                )
            ).all()
        )
        evals.sort(
            key=lambda e: (
                e.status != EvaluationStatus.PUBLISHED.value,
                -(e.updated_at.timestamp() if e.updated_at else 0),
            )
        )
        for ev in evals:
            by_id.setdefault(
                ev.student_id,
                {
                    "id": ev.id,
                    "title": ev.title,
                    "status": ev.status,
                    "published_at": ev.published_at,
                },
            )
    rows = []
    for s in students:
        rows.append(
            {
                "student_id": s.id,
                "name": s.name,
                "campus": s.campus,
                "lesson_balance": s.lesson_balance,
                "evaluation": by_id.get(s.id),
            }
        )
    rows.sort(key=lambda r: r["name"])
    generated = sum(1 for r in rows if r["evaluation"] is not None)
    published = sum(
        1
        for r in rows
        if r["evaluation"] is not None
        and r["evaluation"]["status"] == EvaluationStatus.PUBLISHED.value
    )
    return {
        "class_name": cls.name,
        "subject": cls.subject,
        "teacher_name": cls.teacher.name if cls.teacher else None,
        "students": rows,
        "total": len(rows),
        "generated": generated,
        "published": published,
    }


def collect_class_material(
    db: Session, *, cls: Class, start: date, end: date
) -> dict:
    """收集班级家长会素材：班级信息 + 全体学员周期统计 + 班级内已发布反馈。

    - 学员为班级在册（含停课，不含归档），逐人收集 collect_period_stats
    - 反馈为该班级排课下、周期内已发布的全部课后反馈（教师课堂视角）
    - evaluations：学员名下与周期重叠的评估（草稿/已发布均可），供 AI 提炼共性/亮点
    """
    from app.models.feedback import Feedback as FeedbackModel

    start_dt, _ = _day_bounds(start)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)

    students = [s for s in cls.students if s.status != StudentStatus.ARCHIVED.value]

    student_rows: list[dict] = []
    for s in students:
        stats = collect_period_stats(db, student=s, start=start, end=end)
        evals = list(
            db.scalars(
                select(Evaluation).where(
                    Evaluation.student_id == s.id,
                    Evaluation.period_start <= end,
                    Evaluation.period_end >= start,
                )
            ).all()
        )
        evals.sort(
            key=lambda e: (
                e.status != EvaluationStatus.PUBLISHED.value,
                -(e.updated_at.timestamp() if e.updated_at else 0),
            )
        )
        student_rows.append(
            {
                "name": s.name,
                "status": s.status,
                "lesson_balance": s.lesson_balance,
                "classes_count": len(s.classes),
                "stats": stats,
                "evaluations": [
                    {
                        "status": ev.status,
                        "title": ev.title,
                        "summary": clean_listish_text(ev.content.get("summary")),
                        "progress": clean_listish_text(ev.content.get("progress")),
                        "subjects": ev.content.get("subjects") or [],
                    }
                    for ev in evals
                ],
            }
        )

    # 班级层面已发布反馈（该班排课产生的反馈，覆盖全体学员的课堂事实）
    feedbacks = list(
        db.scalars(
            select(FeedbackModel)
            .options(
                selectinload(FeedbackModel.student),
                selectinload(FeedbackModel.schedule).selectinload(Schedule.schedule_class),
            )
            .join(Schedule, FeedbackModel.schedule_id == Schedule.id)
            .where(
                Schedule.class_id == cls.id,
                FeedbackModel.status == FeedbackStatus.PUBLISHED.value,
                FeedbackModel.created_at >= start_dt,
                FeedbackModel.created_at < end_dt,
            )
            .order_by(FeedbackModel.created_at)
        )
        .unique()
        .all()
    )
    feedback_items = [
        {
            "date": fb.created_at.strftime("%m-%d"),
            "student_name": fb.student.name if fb.student else "（未知学员）",
            "topic": fb.topic,
            "performance": fb.performance,
            "evaluation": fb.evaluation,
        }
        for fb in feedbacks
    ]

    # 班级聚合统计
    n = max(1, len(student_rows))
    rates = [r["stats"].get("attendance_rate") or 0 for r in student_rows]
    hw_rates = [r["stats"].get("homework_score_rate") for r in student_rows]
    hw_rates = [x for x in hw_rates if x is not None]
    class_stats = {
        "student_count": len(student_rows),
        "active_count": sum(1 for r in student_rows if r["status"] == "active"),
        "total_lessons": sum(r["stats"].get("consumed_lessons", 0) for r in student_rows),
        "avg_attendance_rate": round(sum(rates) / n, 4) if rates else 0.0,
        "total_feedbacks": sum(r["stats"].get("feedback_count", 0) for r in student_rows),
        "total_homework": sum(r["stats"].get("homework_count", 0) for r in student_rows),
        "avg_homework_score_rate": (
            round(sum(hw_rates) / len(hw_rates), 4) if hw_rates else None
        ),
        "low_balance_count": sum(1 for r in student_rows if r["lesson_balance"] <= 10),
    }

    return {
        "class_name": cls.name,
        "subject": cls.subject,
        "teacher_name": cls.teacher.name if cls.teacher else None,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "stats": class_stats,
        "students": student_rows,
        "feedbacks": feedback_items,
    }


# ---------------------------------------------------------------------------
# 班级家长会 PPT 生成记录（文案落库：预览 / 编辑 / 秒级重排版）
# ---------------------------------------------------------------------------

CLASS_PPT_CONTENT_KEYS = (
    "title",
    "class_summary",
    "ability_comment",
    "highlights",
    "to_improve",
    "next_plan",
    "home_suggestions",
)


def upsert_class_ppt(
    db: Session,
    *,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
    period_start: date,
    period_end: date,
    title: str | None,
    content: dict,
    stats: dict | None,
    averages: list | None,
    honor_roll: list | None,
    ppt_url: str | None,
    material_hash: str | None = None,
) -> ClassPpt:
    """同一班级同周期仅一份：存在则覆盖文案与快照，否则新建。"""
    existing = db.scalars(
        select(ClassPpt).where(
            ClassPpt.class_id == class_id,
            ClassPpt.period_start == period_start,
            ClassPpt.period_end == period_end,
        )
    ).first()
    if existing is None:
        existing = ClassPpt(
            class_id=class_id,
            teacher_id=teacher_id,
            period_start=period_start,
            period_end=period_end,
        )
        db.add(existing)
    existing.teacher_id = teacher_id
    existing.title = title
    existing.content = {k: content.get(k) for k in CLASS_PPT_CONTENT_KEYS}
    existing.stats = stats
    existing.averages = averages
    existing.honor_roll = honor_roll
    existing.ppt_url = ppt_url
    if material_hash is not None:
        existing.material_hash = material_hash
    db.commit()
    db.refresh(existing)
    return existing


def get_latest_class_ppt(db: Session, *, class_id: uuid.UUID) -> ClassPpt | None:
    """某班级最近一次生成的家长会 PPT 记录（按更新时间倒序）。"""
    return db.scalars(
        select(ClassPpt)
        .where(ClassPpt.class_id == class_id)
        .order_by(ClassPpt.updated_at.desc())
        .limit(1)
    ).first()
