"""提醒通知服务（M5，FR-CL-03 / FR-CL-01）：

- 上课前一天提醒：当天为学生生成「明天上课」站内通知（FR-CL-03）
- 课时低余量提醒：课时 <= 10 的学生生成「课时不足」通知（FR-CL-01）

提醒在客户端登录/拉取时按账号惰性生成（幂等：同日不重复），
避免常驻后台任务；微信推送（OQ-01）预留为「应用内通知 + 微信推送接口位」。
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.crud import notification as notification_crud
from app.models.enrollment import Student, StudentStatus
from app.models.notification import Notification, NotificationType
from app.models.schedule import Schedule, ScheduleStatus
from app.models.user import Role, User


def _local_midnight(now: datetime) -> datetime:
    """本机时区的当日 00:00（服务器本地时区）。"""
    return datetime.combine(now.date(), datetime.min.time()).astimezone()


def students_for_user(db: Session, user: User) -> list[Student]:
    """当前账号可访问的学员：

    - parent 角色：parent_user_id == user.id 的在读学员（可多孩）
    - student 角色：student_user_id == user.id 的本人学员
    - 其他角色：空（教师端不感知客户端提醒）
    """
    if user.role == Role.PARENT.value:
        stmt = (
            select(Student)
            .options(selectinload(Student.classes))
            .where(
                Student.parent_user_id == user.id,
                Student.status != StudentStatus.ARCHIVED.value,
            )
        )
    elif user.role == Role.STUDENT.value:
        stmt = (
            select(Student)
            .options(selectinload(Student.classes))
            .where(Student.student_user_id == user.id)
        )
    else:
        return []
    return list(db.scalars(stmt).unique().all())


def _existing_reminder_keys(db: Session, user_id: uuid.UUID, since: datetime) -> set[str]:
    """当天已给该账号发送过的提醒 key（用于幂等去重）。"""
    rows = db.execute(
        select(Notification.data).where(
            Notification.user_id == user_id,
            Notification.created_at >= since,
        )
    ).all()
    keys: set[str] = set()
    for (data,) in rows:
        if isinstance(data, dict) and data.get("reminder_key"):
            keys.add(data["reminder_key"])
    return keys


def _send(
    db: Session,
    *,
    user_id: uuid.UUID,
    type: str,
    title: str,
    content: str,
    data: dict,
) -> None:
    notification_crud.create(
        db,
        user_id=user_id,
        type=type,
        title=title,
        content=content,
        data=data,
    )


def _ensure_for_student(db: Session, student: Student) -> int:
    """为该学员的家长/本人账号幂等发送提醒，返回新发条数。"""
    sent = 0
    account_ids: set[uuid.UUID] = set()
    if student.parent_user_id is not None:
        account_ids.add(student.parent_user_id)
    if student.student_user_id is not None:
        account_ids.add(student.student_user_id)
    if not account_ids:
        return 0

    now = datetime.now().astimezone()
    today_start = _local_midnight(now)
    tomorrow_start = today_start + timedelta(days=1)
    tomorrow_end = tomorrow_start + timedelta(days=1)

    # 明天的排课（班级维度）
    class_ids = [c.id for c in student.classes]
    schedules: list[Schedule] = []
    if class_ids:
        stmt = (
            select(Schedule)
            .options(selectinload(Schedule.schedule_class))
            .where(
                Schedule.class_id.in_(class_ids),
                Schedule.status == ScheduleStatus.SCHEDULED.value,
                Schedule.start_time >= tomorrow_start,
                Schedule.start_time < tomorrow_end,
            )
            .order_by(Schedule.start_time)
        )
        schedules = list(db.scalars(stmt).unique().all())

    for account_id in account_ids:
        keys = _existing_reminder_keys(db, account_id, today_start)

        # 低余量提醒（FR-CL-01）：课时 <= 10 爆红，每天最多提醒一次
        if student.lesson_balance <= 10:
            key = f"low_balance:{student.id}:{now.date().isoformat()}"
            if key not in keys:
                _send(
                    db,
                    user_id=account_id,
                    type=NotificationType.LOW_BALANCE.value,
                    title="课时提醒",
                    content=(
                        f"{student.name} 的剩余课时仅 {student.lesson_balance} 节"
                        "（≤10 节），请及时续费避免影响上课。"
                    ),
                    data={
                        "student_id": str(student.id),
                        "student_name": student.name,
                        "reminder_key": key,
                    },
                )
                sent += 1

        # 上课提醒（FR-CL-03）：明天的课
        for sched in schedules:
            key = f"schedule_reminder:{student.id}:{sched.id}"
            if key in keys:
                continue
            cls_name = sched.schedule_class.name if sched.schedule_class else "班级"
            start_text = sched.start_time.astimezone().strftime("%m月%d日 %H:%M")
            _send(
                db,
                user_id=account_id,
                type=NotificationType.SCHEDULE_REMINDER.value,
                title="明天的课来啦",
                content=(
                    f"{student.name} 明天 {start_text} 有「{cls_name}」的课，"
                    "请提前预习、准时上课。"
                ),
                data={
                    "student_id": str(student.id),
                    "schedule_id": str(sched.id),
                    "class_name": cls_name,
                    "start_time": sched.start_time.isoformat(),
                    "reminder_key": key,
                },
            )
            sent += 1
    return sent


def ensure_reminders_for_user(db: Session, user: User) -> int:
    """登录/查看首页时调用：为该账号的学员生成提醒（幂等，同日不重复）。"""
    students = students_for_user(db, user)
    total = 0
    for s in students:
        total += _ensure_for_student(db, s)
    return total


def ensure_reminders_for_students(db: Session, student_ids: list[uuid.UUID]) -> int:
    """按学员 id 批量生成提醒（作业发布/订单确认等联动场景使用）。"""
    total = 0
    for sid in student_ids:
        student = db.get(Student, sid)
        if student is not None:
            total += _ensure_for_student(db, student)
    return total
