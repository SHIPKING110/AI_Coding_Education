import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles, require_teacher_permission
from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.crud import business as business_crud
from app.crud import user as user_crud
from app.models.user import Role, User, UserStatus
from app.schemas.auth import (
    AdminPasswordResetIn,
    ChangePasswordIn,
    UserOut,
    UserSelfUpdate,
    UserUpdate,
)
from app.schemas.enrollment import PageOut

router = APIRouter(prefix="/auth", tags=["auth"])

ADMIN_STAFF = (Role.ADMIN, Role.STAFF)
# 只读角色：教师可查看教师列表/校区（联系人信息），但不可写
READ_ROLES = (Role.ADMIN, Role.STAFF, Role.TEACHER)


@router.get("/me", response_model=UserOut)
def read_me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.get("/admin/example", dependencies=[Depends(require_roles(Role.ADMIN))])
def admin_example():
    """RBAC 示例：仅 admin 角色可访问。"""
    return {"message": "only admin can see this"}


@router.patch("/me", response_model=UserOut)
def update_my_profile(    payload: UserSelfUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserOut:
    """个人信息完善（本人）：修改姓名/电话/校区。"""
    return UserOut.model_validate(
        user_crud.update_profile(
            db,
            current_user,
            name=payload.name,
            phone=payload.phone,
            campus=payload.campus,
        )
    )


@router.post("/me/password", response_model=UserOut)
def change_my_password(
    payload: ChangePasswordIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserOut:
    """修改本人密码：校验原密码后设置新密码。"""
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")
    return UserOut.model_validate(user_crud.set_password(db, current_user, payload.new_password))


@router.patch("/users/{user_id}/password", response_model=UserOut)
def reset_user_password(
    user_id: uuid.UUID,
    payload: AdminPasswordResetIn,
    db: Session = Depends(get_db),
    operator: User = Depends(get_current_user),
) -> UserOut:
    """管理员重置他人密码（家长/学员/教师等）。

    权限：仅 admin。教师/教务等非管理员访问返回明确提示。
    """
    if operator.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可重置账号密码",
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    return UserOut.model_validate(user_crud.set_password(db, user, payload.new_password))


class TeacherCreateIn(BaseModel):
    username: str
    password: str
    name: str
    phone: str | None = None
    campus: str | None = None
    title: str | None = None
    teacher_level_id: str | None = None
    base_salary: str | None = None


@router.post("/teachers", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_teacher(
    payload: TeacherCreateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("teacher_add")),
) -> UserOut:
    """新增教师（管理端）。管理员/教务直接放行；教师需 teacher_add 权限。
    若填写职务且存在同名职务预设，自动套用其权限（职务绑定语义）。"""
    if user_crud.get_by_username(db, payload.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    if payload.phone and user_crud.get_by_phone(db, payload.phone):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone already exists")
    user = user_crud.create_user(
        db,
        role=Role.TEACHER,
        username=payload.username,
        password=payload.password,
        name=payload.name,
        phone=payload.phone,
        campus=payload.campus,
        title=(payload.title or "").strip() or None,
    )
    if payload.teacher_level_id or payload.base_salary is not None:
        try:
            user = user_crud.apply_level_salary(
                db, user,
                teacher_level_id=payload.teacher_level_id,
                base_salary=payload.base_salary,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if user.title:
        from app.models.job_title import JobTitle
        from app.models.permission import PERMISSION_KEYS, get_or_create

        preset = db.scalars(select(JobTitle).where(JobTitle.name == user.title)).first()
        if preset is not None:
            row = get_or_create(db, user.id)
            for k in PERMISSION_KEYS:
                if k in (preset.permissions or {}):
                    setattr(row, k, bool(preset.permissions[k]))
            db.commit()
            db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/teachers", response_model=PageOut[UserOut])
def list_teachers(
    keyword: str | None = Query(default=None),
    campus: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
    __: User = Depends(require_teacher_permission("teacher_view")),
) -> PageOut[UserOut]:
    """教师列表（分页；班级分配/排课下拉用活跃，管理页可 include_inactive 查看全部）。教师需 teacher_view 权限。"""
    stmt = select(User).where(User.role == Role.TEACHER.value)
    if not include_inactive:
        stmt = stmt.where(User.status == UserStatus.ACTIVE)
    if keyword:
        stmt = stmt.where(User.name.ilike(f"%{keyword}%"))
    if campus:
        stmt = stmt.where(User.campus == campus)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0
    users = db.scalars(stmt.order_by(User.name).limit(limit).offset(offset)).all()
    return PageOut[UserOut](
        items=[UserOut.model_validate(u) for u in users], total=total, limit=limit, offset=offset
    )


@router.get("/users", response_model=PageOut[UserOut])
def list_users(
    role: str | None = Query(
        default=None,
        description="按角色筛选：admin/staff/teacher/parent/student",
    ),
    keyword: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN, Role.STAFF)),
) -> PageOut[UserOut]:
    """用户列表（分页；按角色/关键字筛选，admin/staff 可用于学员绑定账号选择）。"""
    stmt = select(User)
    if not include_inactive:
        stmt = stmt.where(User.status == UserStatus.ACTIVE)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if keyword:
        stmt = stmt.where(User.name.ilike(f"%{keyword}%") | User.username.ilike(f"%{keyword}%"))
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(count_stmt) or 0
    users = db.scalars(stmt.order_by(User.name).limit(limit).offset(offset)).all()
    return PageOut[UserOut](
        items=[UserOut.model_validate(u) for u in users], total=total, limit=limit, offset=offset
    )


@router.get("/campuses", response_model=list[str])
def list_campuses(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
) -> list[str]:
    """校区列表（业务设置校区表顺序为准，兼容教师身上的历史校区字符串）。教师只读。"""
    ordered = [c.name for c in business_crud.list_campuses(db) if c.name]
    seen = set(ordered)
    stmt = select(User.campus).where(User.campus.isnot(None))
    for (v,) in db.execute(stmt).all():
        if v and v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


@router.get("/teachers/{teacher_id}", response_model=UserOut)
def get_teacher(
    teacher_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*READ_ROLES)),
    __: User = Depends(require_teacher_permission("teacher_view")),
) -> UserOut:
    user = db.get(User, teacher_id)
    if user is None or user.role != Role.TEACHER.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教师不存在")
    return UserOut.model_validate(user)


@router.patch("/teachers/{teacher_id}", response_model=UserOut)
def update_teacher(
    teacher_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("teacher_edit")),
) -> UserOut:
    user = db.get(User, teacher_id)
    if user is None or user.role != Role.TEACHER.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教师不存在")
    if payload.name is not None:
        user.name = payload.name
    if payload.phone is not None:
        user.phone = payload.phone
    if payload.campus is not None:
        user.campus = payload.campus or None
    if payload.title is not None:
        new_title = payload.title.strip() or None
        if new_title != user.title:
            user.title = new_title
            # 换职务自动套用该职务预设权限（职务绑定语义）
            if new_title:
                from app.models.job_title import JobTitle
                from app.models.permission import PERMISSION_KEYS, get_or_create

                preset = db.scalars(
                    select(JobTitle).where(JobTitle.name == new_title)
                ).first()
                if preset is not None:
                    row = get_or_create(db, user.id)
                    perms = preset.permissions or {}
                    for k in PERMISSION_KEYS:
                        if k in perms:
                            setattr(row, k, bool(perms[k]))
                    db.commit()
    if payload.teacher_level_id is not None or payload.base_salary is not None:
        try:
            user = user_crud.apply_level_salary(
                db, user,
                teacher_level_id=payload.teacher_level_id,
                base_salary=payload.base_salary,
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if payload.status is not None:
        if payload.status not in (UserStatus.ACTIVE.value, UserStatus.DISABLED.value):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="status 非法")
        user.status = payload.status
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.delete("/teachers/{teacher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_teacher(
    teacher_id: uuid.UUID,
    db: Session = Depends(get_db),
    operator: User = Depends(get_current_user),
) -> None:
    """删除教师（软停用）。管理员可删；教师需 teacher_delete 权限；教务不可删（保持现有行为）。"""
    if operator.role == Role.TEACHER.value:
        from app.models.permission import check as _perm_check

        if not _perm_check(db, operator, "teacher_delete"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="暂无该操作权限，请联系管理员开通")
    elif operator.role != Role.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    user = db.get(User, teacher_id)
    if user is None or user.role != Role.TEACHER.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教师不存在")
    user.status = UserStatus.DISABLED
    db.commit()
