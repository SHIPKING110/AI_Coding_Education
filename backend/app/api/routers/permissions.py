"""教师操作权限管理（管理员）：查看/设置教师权限、教师查看本人权限。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.job_title import JobTitle
from app.models.permission import (
    KEY_DEFAULTS,
    PERMISSION_KEYS,
    TeacherPermission,
    effective,
    get_or_create,
)
from app.models.user import Role, User

router = APIRouter(prefix="/permissions", tags=["permissions"])


class PermissionUpdate(BaseModel):
    student_create: bool | None = None
    student_edit: bool | None = None
    student_records: bool | None = None
    student_adjust: bool | None = None
    student_refund: bool | None = None
    student_stop: bool | None = None
    student_delete: bool | None = None
    class_unenroll: bool | None = None
    class_view: bool | None = None
    class_create: bool | None = None
    class_edit: bool | None = None
    class_delete: bool | None = None
    teacher_add: bool | None = None
    teacher_view: bool | None = None
    teacher_edit: bool | None = None
    teacher_delete: bool | None = None
    schedule_create: bool | None = None
    schedule_cancel: bool | None = None
    invitation_create: bool | None = None
    package_create: bool | None = None
    package_edit: bool | None = None
    package_off: bool | None = None
    assignment_ai: bool | None = None
    assignment_create: bool | None = None
    order_visible: bool | None = None
    settings_manage: bool | None = None
    settings_tab_personalize: bool | None = None
    settings_tab_model: bool | None = None
    settings_tab_business: bool | None = None
    finance_view: bool | None = None
    finance_revenue: bool | None = None
    finance_records: bool | None = None
    finance_salary: bool | None = None
    finance_salary_all: bool | None = None


def _row_out(teacher: User, row: TeacherPermission | None) -> dict:
    perms = (
        {k: bool(getattr(row, k, KEY_DEFAULTS[k])) for k in PERMISSION_KEYS}
        if row is not None
        else dict.fromkeys(PERMISSION_KEYS, True)
    )
    return {
        "teacher_id": str(teacher.id),
        "teacher_name": teacher.name,
        "username": teacher.username,
        "campus": teacher.campus,
        "title": teacher.title,
        "permissions": perms,
    }


@router.get("/keys")
def permission_keys(_: User = Depends(require_roles(Role.ADMIN))) -> dict:
    """权限键清单（含中文说明）。"""
    return {"keys": [{"key": k, "label": v} for k, v in PERMISSION_KEYS.items()]}


@router.get("/teachers")
def list_teacher_permissions(
    keyword: str | None = Query(default=None),
    limit: int = Query(default=200, le=500),
    _: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """教师权限一览（缺省全开）。"""
    from app.crud import user as user_crud

    teachers = user_crud.list_by_role(db, role=Role.TEACHER.value, keyword=keyword, limit=limit)
    rows = {r.teacher_id: r for r in db.query(TeacherPermission).all()}
    return {"items": [_row_out(t, rows.get(t.id)) for t in teachers]}


@router.put("/teachers/{teacher_id}")
def update_teacher_permissions(
    teacher_id: uuid.UUID,
    payload: PermissionUpdate,
    _: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """设置某教师权限（仅传入字段生效）。"""
    from app.crud import user as user_crud

    teacher = user_crud.get_by_id(db, str(teacher_id))
    if teacher is None or teacher.role != Role.TEACHER.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教师不存在")
    row = get_or_create(db, teacher.id)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if k in PERMISSION_KEYS:
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _row_out(teacher, row)


@router.get("/mine")
def my_permissions(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """当前用户生效权限（前端按此显隐按钮）。"""
    return {"permissions": effective(db, user)}


class JobTitleIn(BaseModel):
    name: str
    permissions: dict[str, bool] = {}
    base_salary: str | None = None


def _title_out(t: JobTitle) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "permissions": dict(t.permissions or {}),
        "base_salary": str(t.base_salary or 0),
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _clean_permissions(perms: dict) -> dict[str, bool]:
    """仅保留合法权限键；未知键 400。"""
    cleaned: dict[str, bool] = {}
    for k, v in (perms or {}).items():
        if k not in PERMISSION_KEYS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"未知权限键：{k}"
            )
        cleaned[k] = bool(v)
    return cleaned


@router.get("/job-titles")
def list_job_titles(
    _: User = Depends(require_roles(Role.ADMIN, Role.STAFF)), db: Session = Depends(get_db)
) -> dict:
    """职务预设一览（新建/编辑教师时选择职务用）。"""
    from sqlalchemy import select

    rows = list(db.scalars(select(JobTitle).order_by(JobTitle.name)).all())
    return {"items": [_title_out(t) for t in rows]}


@router.post("/job-titles", status_code=status.HTTP_201_CREATED)
def create_job_title(
    payload: JobTitleIn,
    _: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """新建职务预设。"""
    from sqlalchemy import select

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="职务名称不能为空")
    if db.scalars(select(JobTitle).where(JobTitle.name == name)).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="职务已存在")
    from decimal import Decimal as _Dec
    _sal = _Dec(str(payload.base_salary)) if payload.base_salary is not None else _Dec("0")
    row = JobTitle(name=name, permissions=_clean_permissions(payload.permissions), base_salary=_sal)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _title_out(row)


@router.put("/job-titles/{title_id}")
def update_job_title(
    title_id: uuid.UUID,
    payload: JobTitleIn,
    _: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """编辑职务预设（改名/改默认权限；不追溯已套用过的教师）。"""
    from sqlalchemy import select

    row = db.get(JobTitle, title_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职务不存在")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="职务名称不能为空")
    dup = db.scalars(select(JobTitle).where(JobTitle.name == name)).first()
    if dup is not None and dup.id != row.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="职务已存在")
    row.name = name
    row.permissions = _clean_permissions(payload.permissions)
    if payload.base_salary is not None:
        from decimal import Decimal as _Dec
        row.base_salary = _Dec(str(payload.base_salary))
    db.commit()
    db.refresh(row)
    return _title_out(row)


@router.delete("/job-titles/{title_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job_title(
    title_id: uuid.UUID,
    _: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    """å 删除职务预设（不影响已使用该职务名称的教师）。"""
    from sqlalchemy import select as _select
    from app.models.user import User as _U
    row = db.get(JobTitle, title_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职务不存在")
    if db.scalar(_select(_U.id).where(_U.title == row.name)) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该职务仍被人员使用，先调整后再删除")
    db.delete(row)
    db.commit()


class ApplyTitleIn(BaseModel):
    title: str


@router.post("/teachers/{teacher_id}/apply-title")
def apply_title_to_teacher(
    teacher_id: uuid.UUID,
    payload: ApplyTitleIn,
    _: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """一键应用：设置教师职务并套用该职务预设权限。"""
    from sqlalchemy import select

    from app.crud import user as user_crud

    teacher = user_crud.get_by_id(db, str(teacher_id))
    if teacher is None or teacher.role != Role.TEACHER.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="教师不存在")
    name = payload.title.strip()
    preset = db.scalars(select(JobTitle).where(JobTitle.name == name)).first()
    if preset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职务预设不存在")
    teacher.title = name
    row = get_or_create(db, teacher.id)
    perms = preset.permissions or {}
    for k in PERMISSION_KEYS:
        if k in perms:
            setattr(row, k, bool(perms[k]))
    db.commit()
    db.refresh(row)
    return _row_out(teacher, row)


@router.post("/job-titles/{title_id}/sync")
def sync_title_to_teachers(
    title_id: uuid.UUID,
    _: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """追溯同步：将该职务预设权限一键应用到所有在职同职务教师（覆盖其个人单独调整）。"""
    from sqlalchemy import select

    preset = db.get(JobTitle, title_id)
    if preset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职务不存在")
    teachers = db.scalars(
        select(User).where(User.role == Role.TEACHER.value, User.title == preset.name)
    ).all()
    perms = preset.permissions or {}
    count = 0
    for t in teachers:
        row = get_or_create(db, t.id)
        for k in PERMISSION_KEYS:
            if k in perms:
                setattr(row, k, bool(perms[k]))
        count += 1
    db.commit()
    return {"title": preset.name, "synced": count}


__all__ = ["router"]
