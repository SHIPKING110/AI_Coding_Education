"""业务通知发布辅助（M5）：在关键业务动作发生时向家长/学员账号发送站内通知。"""

import uuid

from sqlalchemy.orm import Session

from app.crud import notification as notification_crud
from app.models.enrollment import Student
from app.models.notification import NotificationType


def _linked_users(db: Session, student: Student) -> list[uuid.UUID]:
    """学员关联的账号：家长 + 学员本人（均接收通知）。"""
    ids: set[uuid.UUID] = set()
    if student.parent_user_id is not None:
        ids.add(student.parent_user_id)
    if student.student_user_id is not None:
        ids.add(student.student_user_id)
    return list(ids)


def publish_feedback_notification(
    db: Session,
    *,
    student: Student,
    title: str | None,
    extra: dict | None = None,
) -> int:
    """课后反馈发布 → 通知学员的家长/本人（FR-FB-05）。"""
    sent = 0
    for uid in _linked_users(db, student):
        notification_crud.create(
            db,
            user_id=uid,
            type=NotificationType.FEEDBACK_PUBLISHED.value,
            title="新的课后反馈",
            content=f"老师为 {student.name} 发布了课后反馈：{title or '查看详情'}",
            data={
                "student_id": str(student.id),
                "student_name": student.name,
                **(extra or {}),
            },
        )
        sent += 1
    return sent


def publish_assignment_notification(
    db: Session,
    *,
    student: Student,
    assignment_id: uuid.UUID,
    assignment_title: str,
    deadline: object = None,
    only_student_account: bool = False,
) -> int:
    """作业发布 → 通知班级学员/家长（FR-CL-09）。

    data 携带 student_id + assignment_id：家长多孩时通知点击可自动切到对应学员，
    并可直接进入该作业详情（客户端路由按 student_id 过滤可见性）。

    only_student_account=True 时仅通知学员本人账号（课堂作业场景，不打扰家长）。
    """
    sent = 0
    targets = [student.student_user_id] if only_student_account else _linked_users(db, student)
    for uid in targets:
        if uid is None:
            continue
        notification_crud.create(
            db,
            user_id=uid,
            type=NotificationType.ASSIGNMENT_PUBLISHED.value,
            title="新作业已发布",
            content=(
                f"{student.name} 收到一份新作业《{assignment_title}》"
                + (f"，请在 {deadline} 前完成。" if deadline else "，请及时完成。")
            ),
            data={
                "student_id": str(student.id),
                "student_name": student.name,
                "assignment_id": str(assignment_id),
                "assignment_title": assignment_title,
            },
        )
        sent += 1
    return sent


def publish_order_confirmed_notification(
    db: Session,
    *,
    student: Student,
    package_name: str,
    lessons: int,
    extra: dict | None = None,
) -> int:
    """课时包到账 → 通知家长（FR-CL-06）。"""
    sent = 0
    for uid in _linked_users(db, student):
        notification_crud.create(
            db,
            user_id=uid,
            type=NotificationType.ORDER_CONFIRMED.value,
            title="课时已到账",
            content=f"「{package_name}」购买成功，已为 {student.name} 到账 {lessons} 课时。",
            data={
                "student_id": str(student.id),
                "package_name": package_name,
                "lessons": lessons,
                **(extra or {}),
            },
        )
        sent += 1
    return sent


def publish_submitted_notification(
    db: Session,
    *,
    student: Student,
    assignment_id: uuid.UUID,
    assignment_title: str,
    teacher_id: uuid.UUID | None,
    class_names: list[str] | None = None,
    pending_manual: int = 0,
    submission_id: uuid.UUID | None = None,
) -> int:
    """学员提交作业 → 通知出题教师（批改页可直接看到谁/哪个班提交的）。

    收件人：作业出题教师（teacher_id）；教师未配置时不发送。
    data 中携带 student_id/student_name/campus/class_names/assignment_id/submission_id，
    教师端通知列表可一键跳转批改页（定位到该学生的提交）。
    submission_id 为 None 时为历史通知（仅能跳转到作业批改列表）。
    """
    if teacher_id is None:
        return 0
    class_text = "、".join(class_names or []) or "未分班"
    campus_text = student.campus or "未填校区"
    content = (
        f"{student.name}（{campus_text} · {class_text}）提交了《{assignment_title}》"
        + (f"，其中 {pending_manual} 题待人工批改。" if pending_manual else "，请及时批改。")
    )
    notification_crud.create(
        db,
        user_id=teacher_id,
        type=NotificationType.SUBMISSION_SUBMITTED.value,
        title="学员提交了作业",
        content=content,
        data={
            "student_id": str(student.id),
            "student_name": student.name,
            "campus": student.campus,
            "class_names": class_names or [],
            "assignment_id": str(assignment_id),
            "assignment_title": assignment_title,
            "submission_id": str(submission_id) if submission_id else None,
            "pending_manual": pending_manual,
        },
    )
    return 1


def publish_graded_notification(
    db: Session,
    *,
    student: Student,
    assignment_title: str,
    score: int,
    total: int,
    assignment_id: uuid.UUID | None = None,
) -> int:
    """作业批改完成 → 通知学员/家长（FR-CL-18）。"""
    sent = 0
    for uid in _linked_users(db, student):
        notification_crud.create(
            db,
            user_id=uid,
            type=NotificationType.SUBMISSION_GRADED.value,
            title="作业已批改",
            content=(
                f"{student.name} 的《{assignment_title}》已批改完成，"
                f"得分 {score}/{total}，快去查看吧。"
            ),
            data={
                "student_id": str(student.id),
                "student_name": student.name,
                "assignment_id": str(assignment_id) if assignment_id else None,
                "assignment_title": assignment_title,
                "score": score,
                "total": total,
            },
        )
        sent += 1
    return sent


def publish_refund_notification(
    db: Session,
    *,
    student: Student,
    amount: str,
    detail_lines: list[str],
) -> int:
    """退费完成 → 通知家长/学员（含明细）。"""
    sent = 0
    for uid in _linked_users(db, student):
        detail_text = "\n" + "\n".join(detail_lines) if detail_lines else ""
        notification_crud.create(
            db,
            user_id=uid,
            type=NotificationType.REFUND.value,
            title="课时退费已完成",
            content=f"{student.name} 的退费已完成，合计退费 ¥{amount}。" + detail_text,
            data={"student_id": str(student.id), "amount": amount, "detail_lines": detail_lines},
        )
        sent += 1
    return sent


def publish_evaluation_notification(
    db: Session,
    *,
    student: Student,
    period_label: str,
) -> int:
    """学员评估发布 → 通知家长/学员（FR-EV-04，M6 家长会场景）。"""
    sent = 0
    for uid in _linked_users(db, student):
        notification_crud.create(
            db,
            user_id=uid,
            type=NotificationType.EVALUATION_PUBLISHED.value,
            title="新的学习评估",
            content=f"{student.name} 的「{period_label}」综合评估已发布，欢迎查看。",
            data={"student_id": str(student.id), "student_name": student.name},
        )
        sent += 1
    return sent
