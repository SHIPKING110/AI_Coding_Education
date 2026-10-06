import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.enrollment import (
    Class,
    FollowUpStatus,
    LessonPackage,
    LessonRecord,
    LessonRecordType,
    Order,
    OrderStatus,
    Student,
    StudentClass,
    StudentStatus,
)
from app.models.user import User


def get(db: Session, student_id: uuid.UUID) -> Student | None:
    """按 id 查询学员（在读 + 停课，已归档不可查）。"""
    return db.scalar(
        select(Student)
        .options(selectinload(Student.classes))
        .where(Student.id == student_id, Student.status != StudentStatus.ARCHIVED)
    )


def _apply_filters(
    stmt,
    *,
    keyword: str | None,
    class_id: uuid.UUID | None,
    class_unassigned: bool,
    campus: str | None,
    campus_unassigned: bool,
    status: str | None,
    lesson_balance_min: int | None,
    lesson_balance_max: int | None,
    low_balance_only: bool,
    follow_up: str | None,
    teacher_id: uuid.UUID | None = None,
    teacher_unassigned: bool = False,
    account: str | None = None,
):
    if keyword:
        stmt = stmt.where(Student.name.ilike(f"%{keyword}%"))
    if campus:
        stmt = stmt.where(Student.campus == campus)
    elif campus_unassigned:
        # 校区「未分配」：学员未填校区
        stmt = stmt.where(Student.campus.is_(None))
    if status:
        stmt = stmt.where(Student.status == status)
    else:
        stmt = stmt.where(Student.status != StudentStatus.ARCHIVED)
    if lesson_balance_min is not None:
        stmt = stmt.where(Student.lesson_balance >= lesson_balance_min)
    if lesson_balance_max is not None:
        stmt = stmt.where(Student.lesson_balance <= lesson_balance_max)
    if low_balance_only:
        # 催缴名单：课时<=10 自动进入；已跟进（续费/停课）保留展示其跟进状态
        stmt = stmt.where(
            or_(
                Student.lesson_balance <= 10,
                Student.follow_up_status != FollowUpStatus.PENDING.value,
            )
        )
    if follow_up:
        stmt = stmt.where(Student.follow_up_status == follow_up)
    if class_unassigned:
        # 班级「未分配」：未加入任何班级的学员
        stmt = stmt.where(~Student.classes.any())
    elif class_id:
        stmt = stmt.join(StudentClass, StudentClass.student_id == Student.id).where(
            StudentClass.class_id == class_id
        )
    if teacher_unassigned:
        # 教师「未分配」：所在班级均没有带教教师（含未加入班级的学员）
        stmt = stmt.where(~Student.classes.any(Class.teacher_id.isnot(None)))
    elif teacher_id:
        # 带教教师筛选：学员所在任意（在教）班级的带教教师为该教师（EXISTS 避免 join 翻倍）
        stmt = stmt.where(
            Student.classes.any(
                and_(Class.teacher_id == teacher_id, Class.status == StudentStatus.ACTIVE.value)
            )
        )
    if account == "unbound_student":
        # 学员账号「未绑定」：学员本人登录账号为空的学员
        stmt = stmt.where(Student.student_user_id.is_(None))
    elif account == "unbound_parent":
        # 家长账号「未绑定」：家长账号为空的学员
        stmt = stmt.where(Student.parent_user_id.is_(None))
    return stmt


def list_all(
    db: Session,
    *,
    keyword: str | None = None,
    class_id: uuid.UUID | None = None,
    class_unassigned: bool = False,
    campus: str | None = None,
    campus_unassigned: bool = False,
    status: str | None = None,
    lesson_balance_min: int | None = None,
    lesson_balance_max: int | None = None,
    low_balance_only: bool = False,
    follow_up: str | None = None,
    teacher_id: uuid.UUID | None = None,
    teacher_unassigned: bool = False,
    account: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Student]:
    stmt = select(Student).options(selectinload(Student.classes))
    stmt = _apply_filters(
        stmt,
        keyword=keyword,
        class_id=class_id,
        class_unassigned=class_unassigned,
        campus=campus,
        campus_unassigned=campus_unassigned,
        status=status,
        lesson_balance_min=lesson_balance_min,
        lesson_balance_max=lesson_balance_max,
        low_balance_only=low_balance_only,
        follow_up=follow_up,
        teacher_id=teacher_id,
        teacher_unassigned=teacher_unassigned,
        account=account,
    )
    stmt = stmt.order_by(Student.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).unique().all())


def count_all(
    db: Session,
    *,
    keyword: str | None = None,
    class_id: uuid.UUID | None = None,
    class_unassigned: bool = False,
    campus: str | None = None,
    campus_unassigned: bool = False,
    status: str | None = None,
    lesson_balance_min: int | None = None,
    lesson_balance_max: int | None = None,
    low_balance_only: bool = False,
    follow_up: str | None = None,
    teacher_id: uuid.UUID | None = None,
    teacher_unassigned: bool = False,
    account: str | None = None,
) -> int:
    """与 list_all 相同筛选条件下的总数（分页用）。"""
    stmt = select(func.count(func.distinct(Student.id)))
    stmt = _apply_filters(
        stmt,
        keyword=keyword,
        class_id=class_id,
        class_unassigned=class_unassigned,
        campus=campus,
        campus_unassigned=campus_unassigned,
        status=status,
        lesson_balance_min=lesson_balance_min,
        lesson_balance_max=lesson_balance_max,
        low_balance_only=low_balance_only,
        follow_up=follow_up,
        teacher_id=teacher_id,
        teacher_unassigned=teacher_unassigned,
        account=account,
    )
    return db.scalar(stmt) or 0


def create(
    db: Session,
    *,
    name: str,
    phone: str | None,
    campus: str | None,
    lesson_balance: int,
    parent_user_id: uuid.UUID | None,
    student_user_id: uuid.UUID | None,
    class_ids: list[uuid.UUID],
    source: str | None = None,
    referrer: str | None = None,
    gender: str | None = None,
) -> Student:
    student = Student(
        name=name,
        phone=phone,
        campus=campus,
        gender=(gender or ""),
        lesson_balance=lesson_balance,
        parent_user_id=parent_user_id,
        student_user_id=student_user_id,
        source=source or "normal",
        referrer=referrer,
    )
    if class_ids:
        classes = db.scalars(
            select(Class).where(Class.id.in_(class_ids), Class.status == StudentStatus.ACTIVE)
        ).all()
        student.classes = list(classes)
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def update(
    db: Session,
    student: Student,
    *,
    name: str | None,
    phone: str | None,
    campus: str | None,
    parent_user_id: uuid.UUID | None,
    student_user_id: uuid.UUID | None,
    class_ids: list[uuid.UUID] | None,
    gender: str | None = None,
) -> Student:
    if name is not None:
        student.name = name
    if gender is not None:
        student.gender = gender
    if phone is not None:
        student.phone = phone
    if campus is not None:
        student.campus = campus
    if parent_user_id is not None:
        student.parent_user_id = parent_user_id
    if student_user_id is not None:
        student.student_user_id = student_user_id
    if class_ids is not None:
        classes = db.scalars(
            select(Class).where(Class.id.in_(class_ids), Class.status == StudentStatus.ACTIVE)
        ).all()
        student.classes = list(classes)
    db.commit()
    db.refresh(student)
    return student


def set_classes(
    db: Session,
    student: Student,
    class_ids: list[uuid.UUID],
    *,
    restrict_teacher_id: uuid.UUID | None = None,
) -> Student:
    """调整学员班级归属。

    - restrict_teacher_id 为 None（管理员/教务）：直接以给定集合替换全部班级归属；
    - restrict_teacher_id 为某教师（教师自助调整）：只能调整「本人所带班级」的成员关系，
      请求中的班级必须都属于该教师；学生属于其他教师的班级保持不变。
    """
    requested = db.scalars(
        select(Class).where(Class.id.in_(class_ids), Class.status == StudentStatus.ACTIVE)
    ).all()
    if len(requested) != len(set(class_ids)):
        raise ValueError("存在无效或已归档的班级")
    if restrict_teacher_id is not None:
        current_ids = {c.id for c in student.classes}
        # 教师只能"新增"本人所带班级；已归属其他教师班级的保留（支持退班时原样回传）。
        for c in requested:
            if c.teacher_id != restrict_teacher_id and c.id not in current_ids:
                raise ValueError("只能把学员调整到你自己所带的班级")
        kept = [c for c in student.classes if c.teacher_id != restrict_teacher_id]
        requested = [c for c in requested if c.teacher_id == restrict_teacher_id]
    else:
        kept = []
    # 去重合并（保持稳定顺序）
    merged: list[Class] = list(kept)
    for c in requested:
        if all(existing.id != c.id for existing in merged):
            merged.append(c)
    student.classes = merged
    db.commit()
    db.refresh(student)
    return student


def unbind_account(db: Session, student: Student, kind: str) -> Student:
    """手动解绑家长/学员登录账号（User 行保留，可重新绑定）。"""
    if kind == "parent":
        student.parent_user_id = None
    elif kind == "student":
        student.student_user_id = None
    else:
        raise ValueError("kind 须为 parent 或 student")
    db.commit()
    db.refresh(student)
    return student


def archive(db: Session, student: Student) -> None:
    """软删除→归档：历史数据保留，不再出现在活跃列表；同时清空在读班级（自动退班）。"""
    student.status = StudentStatus.ARCHIVED
    student.classes = []
    # 归档同时解绑家长/学员登录账号：User 行保留，账号名可被重新绑定（不再占着）
    student.parent_user_id = None
    student.student_user_id = None
    db.commit()


def archive_block_reason(student: Student) -> str | None:
    """余额非零（未消耗完或欠课时）时禁止归档，返回中文原因；可归档返回 None。"""
    try:
        balance = float(student.lesson_balance or 0)
    except (TypeError, ValueError):
        balance = 0.0
    if abs(balance) >= 0.05:
        if balance > 0:
            return f"该学员还有 {balance:g} 节课时未消耗，无法直接删除；请先退费/消耗完课时后再删除"
        return f"该学员欠 {abs(balance):g} 节课时，无法直接删除；请先结清欠费后再删除"
    return None




def set_follow_up(
    db: Session,
    student_id: uuid.UUID,
    *,
    follow_up_status: str,
    note: str | None = None,
) -> Student | None:
    """维护催缴跟进状态：待跟进 -> 已续费 / 已停课，并记录跟进时间与备注。

    停课与学员在读状态联动：标记「已停课」时学员同步停课；
    标记「待跟进/已续费」时视为恢复在读。
    """
    student = get(db, student_id)
    if student is None:
        return None
    student.follow_up_status = follow_up_status
    student.follow_up_at = datetime.now(UTC)
    if note is not None:
        student.follow_up_note = note
    if follow_up_status == FollowUpStatus.STOPPED.value:
        student.status = StudentStatus.STOPPED
        if note is not None:
            student.stop_note = note
    else:
        student.status = StudentStatus.ACTIVE
    db.commit()
    db.refresh(student)
    return student


def set_status(
    db: Session,
    student_id: uuid.UUID,
    *,
    status: str,
    stop_note: str | None = None,
) -> Student | None:
    """学员在读状态变更：停课（stopped）/ 恢复在读（active）。

    - 停课：必须填写备注，同步跟进状态为「已停课」（不再催缴）；
    - 恢复在读：同步跟进状态为「待跟进」（重新进入催缴名单）。
    """
    student = get(db, student_id)
    if student is None:
        return None
    if status == StudentStatus.STOPPED.value:
        student.status = StudentStatus.STOPPED
        if stop_note is not None:
            student.stop_note = stop_note
            student.follow_up_note = stop_note
        student.follow_up_status = FollowUpStatus.STOPPED.value
        student.follow_up_at = datetime.now(UTC)
    elif status == StudentStatus.ACTIVE.value:
        student.status = StudentStatus.ACTIVE
        student.stop_note = None
        student.follow_up_status = FollowUpStatus.PENDING.value
        student.follow_up_at = datetime.now(UTC)
    db.commit()
    db.refresh(student)
    return student


def renew(
    db: Session,
    student: Student,
    *,
    package_id: uuid.UUID | None,
    custom_lessons: int | None,
    custom_amount: Decimal | None,
    note: str | None,
    operator_id: uuid.UUID | None,
) -> tuple[Student, LessonRecord, Order]:
    """催缴续费入账：补课时 + 记订单 + 标记已续费（同一事务）。

    返回 (student, lesson_record, order)。调用方负责校验课包存在/参数互斥。
    """
    if package_id is not None:
        package: LessonPackage | None = db.get(LessonPackage, package_id)
        lessons = package.total_lessons if package else custom_lessons or 0
        amount = package.price if package else Decimal("0")
        remark = f"催缴续费：{package.name}（{lessons} 课时）" if package else "催缴续费"
    else:
        lessons = custom_lessons or 0
        amount = custom_amount or Decimal("0")
        remark = f"催缴续费：自定义补录 {lessons} 课时" + (f"，金额 {amount} 元" if amount else "")
    lessons_dec = Decimal(str(lessons))

    # 欠费自动抵扣：先填负数，剩余才是可用课时
    arrears_before = -min(Decimal(str(student.lesson_balance)), Decimal("0"))
    repaid = min(arrears_before, lessons_dec)
    if repaid > 0:
        remark += f"，其中还欠款 {repaid.normalize()} 节"

    order = Order(
        student_id=student.id,
        package_id=package_id,
        amount=amount,
        status=OrderStatus.CONFIRMED.value,
        paid_at=datetime.now(UTC),
        confirmed_at=datetime.now(UTC),
    )
    db.add(order)
    db.flush()

    record = LessonRecord(
        student_id=student.id,
        record_type=LessonRecordType.RECHARGE.value,
        delta=lessons_dec,
        balance_after=Decimal(str(student.lesson_balance)) + lessons_dec,
        ref_id=order.id,
        remark=remark,
        operator_id=operator_id,
    )
    student.lesson_balance = Decimal(str(student.lesson_balance)) + lessons_dec
    db.add(record)

    student.follow_up_status = FollowUpStatus.RENEWED.value
    student.follow_up_at = datetime.now(UTC)
    if note is not None:
        student.follow_up_note = note
    # 续费即视为恢复在读
    student.status = StudentStatus.ACTIVE
    student.stop_note = None

    db.commit()
    db.refresh(student)
    db.refresh(record)
    db.refresh(order)
    return student, record, order


def teacher_name_of(user: User | None) -> str | None:
    return user.name if user else None
