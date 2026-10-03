import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enrollment import Student, StudentClass
from app.models.schedule import Attendance, AttendanceStatus, Schedule


def list_for_schedule(db: Session, schedule_id: uuid.UUID) -> list[Attendance]:
    return list(
        db.scalars(select(Attendance).where(Attendance.schedule_id == schedule_id)).unique().all()
    )


def ensure_for_students(
    db: Session, schedule_id: uuid.UUID, student_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Attendance]:
    """为指定排课学员集合确保 Attendance 行存在，返回 student_id -> Attendance。"""
    existing = list_for_schedule(db, schedule_id)
    by_sid = {a.student_id: a for a in existing}
    for sid in student_ids:
        if sid not in by_sid:
            row = Attendance(
                schedule_id=schedule_id, student_id=sid, status=AttendanceStatus.UNMARKED
            )
            db.add(row)
            by_sid[sid] = row
    return by_sid


def find_current_attendance(
    db: Session, schedule_id: uuid.UUID, student_id: uuid.UUID
) -> Attendance | None:
    return db.scalar(
        select(Attendance).where(
            Attendance.schedule_id == schedule_id, Attendance.student_id == student_id
        )
    )


def class_student_ids(db: Session, class_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(select(StudentClass.student_id).where(StudentClass.class_id == class_id)).all()
    )


def all_students_for_schedule(db: Session, schedule: Schedule) -> list[Student]:
    sids = class_student_ids(db, schedule.class_id) if schedule.class_id else []
    # 体验学员：通过邀约关联到本节排课（不占班级名额，考勤时单独列出）
    from app.models.trial import Invitation

    trial_ids = list(
        db.scalars(
            select(Invitation.trial_student_id).where(
                Invitation.trial_schedule_id == schedule.id,
                Invitation.trial_student_id.isnot(None),
            )
        ).all()
    )
    all_ids = list(dict.fromkeys([*(sids or []), *trial_ids]))
    if not all_ids:
        return []
    return list(db.scalars(select(Student).where(Student.id.in_(all_ids))).all())
