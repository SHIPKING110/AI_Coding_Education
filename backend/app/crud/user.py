from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import Role, User, UserStatus


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_by_phone(db: Session, phone: str) -> User | None:
    return db.scalar(select(User).where(User.phone == phone))


def get_by_id(db: Session, user_id) -> User | None:
    return db.get(User, user_id)


def list_by_role(
    db: Session, *, role: str, keyword: str | None = None, limit: int = 200
) -> list[User]:
    """按角色列用户（权限管理页用）；keyword 匹配姓名/用户名。"""
    stmt = select(User).where(User.role == role).order_by(User.created_at.desc())
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(User.name.ilike(kw), User.username.ilike(kw)))
    return list(db.scalars(stmt.limit(max(1, min(limit, 500)))).all())


def verify_credentials(db: Session, username: str, password: str) -> User | None:
    user = get_by_username(db, username)
    if not user:
        return None
    if user.status != UserStatus.ACTIVE:
        return None
    from app.core.security import verify_password

    if not verify_password(password, user.password_hash):
        return None
    return user


def create_user(
    db: Session,
    *,
    role: Role,
    username: str,
    password: str,
    name: str,
    phone: str | None = None,
    campus: str | None = None,
    title: str | None = None,
) -> User:
    user = User(
        role=role.value,
        username=username,
        password_hash=hash_password(password),
        name=name,
        phone=phone,
        campus=campus,
        title=(title or None),
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    # 新建教师选定职务即套用该职务预设权限
    if user.role == Role.TEACHER.value and user.title:
        from app.models.job_title import JobTitle
        from app.models.permission import PERMISSION_KEYS, get_or_create

        preset = db.scalars(
            select(JobTitle).where(JobTitle.name == user.title)
        ).first()
        if preset is not None:
            row = get_or_create(db, user.id)
            perms = preset.permissions or {}
            for k in PERMISSION_KEYS:
                if k in perms:
                    setattr(row, k, bool(perms[k]))
            db.commit()
            db.refresh(user)
    return user


def apply_level_salary(db, user, *, teacher_level_id=None, base_salary=None):
    """设置教师级别（同步快照名）与基本工资。"""
    if teacher_level_id is not None:
        if teacher_level_id == '':
            user.teacher_level_id = None
            user.teacher_level_name = None
        else:
            from app.models.business import TeacherLevel as _TL
            lv = None
            try:
                import uuid as _uuid
                lv = db.get(_TL, _uuid.UUID(str(teacher_level_id)))
            except Exception:
                lv = None
            if lv is None:
                from sqlalchemy import select as _select
                lv = db.scalar(_select(_TL).where(_TL.name == str(teacher_level_id)))
            if lv is None:
                raise ValueError('教师级别不存在')
            user.teacher_level_id = str(lv.id)
            user.teacher_level_name = lv.name
    if base_salary is not None:
        from decimal import Decimal as _Dec
        user.base_salary = None if base_salary == '' else _Dec(str(base_salary))
    db.commit()
    db.refresh(user)
    return user


def update_profile(
    db: Session,
    user: User,
    *,
    name: str | None = None,
    phone: str | None = None,
    campus: str | None = None,
) -> User:
    """修改本人基本信息（name/phone/campus 按需更新）。"""
    if name is not None:
        user.name = name
    if phone is not None:
        user.phone = phone or None
    if campus is not None:
        user.campus = campus or None
    db.commit()
    db.refresh(user)
    return user


def set_password(db: Session, user: User, password: str) -> User:
    """设置（重置/修改）密码并持久化。"""
    user.password_hash = hash_password(password)
    db.commit()
    db.refresh(user)
    return user
