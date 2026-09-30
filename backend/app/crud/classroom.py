import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.enrollment import Class, StudentClass, StudentStatus
from app.models.user import User


def get(db: Session, class_id: uuid.UUID) -> Class | None:
    return db.scalar(
        select(Class)
        .options(selectinload(Class.students), selectinload(Class.teacher))
        .where(Class.id == class_id, Class.status == StudentStatus.ACTIVE)
    )


def _filter_stmt(
    keyword: str | None,
    teacher_id: uuid.UUID | None = None,
    campus: str | None = None,
    teacher_unassigned: bool = False,
    campus_unassigned: bool = False,
    start_date_from=None,
    start_date_to=None,
):
    stmt = (
        select(Class)
        .outerjoin(User, Class.teacher_id == User.id)
        .where(Class.status == StudentStatus.ACTIVE)
    )
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(Class.name.ilike(like), Class.subject.ilike(like), User.name.ilike(like))
        )
    if teacher_unassigned:
        # 教师「未分配」：尚未安排带教教师的班级
        stmt = stmt.where(Class.teacher_id.is_(None))
    elif teacher_id is not None:
        # 精确按带教教师过滤（与 keyword 可叠加，区别于姓名模糊匹配）
        stmt = stmt.where(Class.teacher_id == teacher_id)
    if campus:
        # 按带教教师所属校区过滤（筛选联动：选校区后班级只显示该校区教师所带班级）
        stmt = stmt.where(User.campus == campus)
    elif campus_unassigned:
        # 校区「未分配」：未安排教师或教师未填校区的班级
        stmt = stmt.where(or_(Class.teacher_id.is_(None), User.campus.is_(None)))
    if start_date_from:
        stmt = stmt.where(Class.start_date >= start_date_from)
    if start_date_to:
        stmt = stmt.where(Class.start_date <= start_date_to)
    return stmt


def list_all(
    db: Session,
    *,
    keyword: str | None = None,
    teacher_id: uuid.UUID | None = None,
    teacher_unassigned: bool = False,
    campus: str | None = None,
    campus_unassigned: bool = False,
    start_date_from=None,
    start_date_to=None,
    limit: int = 100,
    offset: int = 0,
) -> list[Class]:
    """班级列表：keyword 匹配名称/科目/教师；teacher_id/campus 精确过滤；start_date 区间筛选。"""
    stmt = (
        _filter_stmt(
            keyword,
            teacher_id,
            campus,
            teacher_unassigned=teacher_unassigned,
            campus_unassigned=campus_unassigned,
            start_date_from=start_date_from,
            start_date_to=start_date_to,
        )
        .order_by(Class.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).unique().all())


def count_all(
    db: Session,
    *,
    keyword: str | None = None,
    teacher_id: uuid.UUID | None = None,
    teacher_unassigned: bool = False,
    campus: str | None = None,
    campus_unassigned: bool = False,
    start_date_from=None,
    start_date_to=None,
) -> int:
    """与 list_all 相同筛选条件下的总数（分页用）。"""
    stmt = _filter_stmt(
        keyword,
        teacher_id,
        campus,
        teacher_unassigned=teacher_unassigned,
        campus_unassigned=campus_unassigned,
        start_date_from=start_date_from,
        start_date_to=start_date_to,
    )
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def create(
    db: Session,
    *,
    name: str,
    subject: str,
    teacher_id: uuid.UUID | None,
    start_date,
) -> Class:
    cls = Class(
        name=name,
        subject=subject,
        teacher_id=teacher_id,
        start_date=start_date,
    )
    db.add(cls)
    db.commit()
    db.refresh(cls)
    return cls


def update(
    db: Session,
    cls: Class,
    *,
    name: str | None,
    subject: str | None,
    teacher_id: uuid.UUID | None,
    start_date,
) -> Class:
    if name is not None:
        cls.name = name
    if subject is not None:
        cls.subject = subject
    if teacher_id is not None:
        cls.teacher_id = teacher_id
    if start_date is not None:
        cls.start_date = start_date
    db.commit()
    db.refresh(cls)
    return cls


def archive(db: Session, cls: Class) -> None:
    cls.status = StudentStatus.ARCHIVED
    db.commit()


def student_count(db: Session, class_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(StudentClass).where(StudentClass.class_id == class_id)
        )
        or 0
    )
