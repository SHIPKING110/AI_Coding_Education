"""业务基础资料（设置模块·业务功能设置 tab）：校区 / 科目 / 财务参数。

- 校区/科目/财务参数的读写：设置权限（settings_manage）
- 列表读取放宽到登录用户（各处下拉框数据源）
"""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_teacher_permission
from app.core.database import get_db
from app.crud import business as business_crud
from app.models.business import Campus
from app.models.user import User

router = APIRouter(prefix="/business", tags=["business"])


# ---------- 校区 ----------

class CampusIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class CampusUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    active: bool | None = None


class CampusReorderIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, description="按期望顺序排列的校区 id")


def _campus_out(row) -> dict:
    return {"id": str(row.id), "name": row.name, "active": row.active, "sort": row.sort}


@router.get("/campuses")
def list_campuses(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return {"items": [_campus_out(c) for c in business_crud.list_campuses(db, include_inactive=include_inactive)]}


@router.post("/campuses", status_code=status.HTTP_201_CREATED)
def create_campus(
    payload: CampusIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    if db.scalar(select(Campus.id).where(Campus.name == payload.name.strip())):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="校区名称已存在")
    return _campus_out(business_crud.create_campus(db, name=payload.name))


@router.post("/campuses/reorder")
def reorder_campuses(
    payload: CampusReorderIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    """校区排序：按 ids 顺序重写 sort，各处校区筛选下拉即时跟随。"""
    rows = business_crud.reorder_campuses(db, payload.ids)
    return {"items": [_campus_out(c) for c in rows]}


@router.patch("/campuses/{campus_id}")
def update_campus(
    campus_id: uuid.UUID,
    payload: CampusUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    row = db.get(Campus, campus_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="校区不存在")
    if payload.name and payload.name.strip() != row.name:
        dup = db.scalar(select(Campus.id).where(Campus.name == payload.name.strip()))
        if dup:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="校区名称已存在")
    return _campus_out(business_crud.update_campus(db, row, name=payload.name, active=payload.active))


# ---------- 科目 ----------

class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    per_session: Decimal = Field(default=Decimal("2"), gt=0, le=99, description="每次课消耗课时数")
    commission_rate: Decimal | None = Field(
        default=None, ge=0, le=1, description="教师抽成比例 0~1，为空用全局默认"
    )


class SubjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    per_session: Decimal | None = Field(default=None, gt=0, le=99)
    commission_rate: Decimal | None = Field(default=None, ge=0, le=1)
    commission_rate_set: bool = Field(default=False, description="是否更新抽成（含清空为全局默认）")
    active: bool | None = None


def _subject_out(row) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "per_session": str(row.per_session),
        "commission_rate": str(row.commission_rate) if row.commission_rate is not None else None,
        "active": row.active,
        "sort": row.sort,
    }


@router.get("/subjects")
def list_subjects(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return {
        "items": [
            _subject_out(s)
            for s in business_crud.list_subjects(db, include_inactive=include_inactive)
        ]
    }


@router.post("/subjects", status_code=status.HTTP_201_CREATED)
def create_subject(
    payload: SubjectIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    if business_crud.find_subject_by_name(db, payload.name.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="科目名称已存在")
    return _subject_out(
        business_crud.create_subject(
            db,
            name=payload.name,
            per_session=payload.per_session,
            commission_rate=payload.commission_rate,
        )
    )


@router.patch("/subjects/{subject_id}")
def update_subject(
    subject_id: uuid.UUID,
    payload: SubjectUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    row = business_crud.get_subject(db, subject_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="科目不存在")
    if payload.name and payload.name.strip() != row.name:
        if business_crud.find_subject_by_name(db, payload.name.strip()):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="科目名称已存在")
    rate = payload.commission_rate if payload.commission_rate_set else None
    if payload.commission_rate_set and payload.commission_rate is None:
        row.commission_rate = None
        db.commit()
        db.refresh(row)
        return _subject_out(
            business_crud.update_subject(
                db, row, name=payload.name, per_session=payload.per_session,
                commission_rate=row.commission_rate, active=payload.active,
            )
        )
    return _subject_out(
        business_crud.update_subject(
            db,
            row,
            name=payload.name,
            per_session=payload.per_session,
            commission_rate=rate,
            active=payload.active,
        )
    )


# ---------- 财务参数 ----------

class FinanceSettingUpdate(BaseModel):
    commission_default: Decimal | None = Field(default=None, ge=0, le=1)
    overdraft_max: Decimal | None = Field(default=None, ge=0, le=100, description="允许透支上限（课时）")
    note: str | None = Field(default=None, max_length=512)


@router.get("/finance-setting")
def get_finance_setting(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    row = business_crud.get_finance_setting(db)
    return {
        "commission_default": str(row.commission_default),
        "overdraft_max": str(row.overdraft_max),
        "note": row.note,
        "formula": {
            "revenue": "创收 = Σ 消耗课时 × 消耗瞬间FIFO单价",
            "commission": "教师绩效 = 消耗金额 × 科目抽成（未设科目用全局默认）",
            "net": "公司实收 = 创收 − 教师绩效 − 退款",
        },
    }


@router.put("/finance-setting")
def update_finance_setting(
    payload: FinanceSettingUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    row = business_crud.update_finance_setting(
        db, commission_default=payload.commission_default, note=payload.note,
        overdraft_max=payload.overdraft_max,
    )
    return {
        "commission_default": str(row.commission_default),
        "overdraft_max": str(row.overdraft_max),
        "note": row.note,
    }


__all__ = ["router"]


# ---------- 教师级别 ----------

class TeacherLevelIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    ratio: Decimal = Field(ge=0, le=1, description="单节课绩效比例 0~1")


class TeacherLevelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    ratio: Decimal | None = Field(default=None, ge=0, le=1)
    active: bool | None = None


def _level_out(row) -> dict:
    return {"id": str(row.id), "name": row.name, "ratio": str(row.ratio),
            "ratio_pct": str((Decimal(str(row.ratio)) * 100).quantize(Decimal("0.01"))),
            "active": row.active, "sort": row.sort}


@router.get("/teacher-levels")
def list_teacher_levels(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return {"items": [_level_out(r) for r in business_crud.list_levels(db, include_inactive=include_inactive)]}


@router.post("/teacher-levels", status_code=status.HTTP_201_CREATED)
def create_teacher_level(
    payload: TeacherLevelIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    from sqlalchemy import select as _select
    from app.models.business import TeacherLevel as _TL
    if db.scalar(_select(_TL.id).where(_TL.name == payload.name.strip())):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="级别名称已存在")
    return _level_out(business_crud.create_level(db, name=payload.name, ratio=payload.ratio))


@router.patch("/teacher-levels/{level_id}")
def update_teacher_level(
    level_id: uuid.UUID,
    payload: TeacherLevelUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    from app.models.business import TeacherLevel as _TL
    row = db.get(_TL, level_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="级别不存在")
    if payload.name and payload.name.strip() != row.name:
        from sqlalchemy import select as _select
        if db.scalar(_select(_TL.id).where(_TL.name == payload.name.strip())):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="级别名称已存在")
    updated = business_crud.update_level(db, row, name=payload.name, ratio=payload.ratio, active=payload.active)
    if payload.name and payload.name.strip() != row.name:
        pass
    # 同步教师快照名
    if payload.name and payload.name.strip():
        from app.models.user import User as _U
        for u in db.scalars(_select(_U).where(_U.teacher_level_id == str(row.id))).all():
            u.teacher_level_name = updated.name
        db.commit()
    return _level_out(updated)


@router.delete("/teacher-levels/{level_id}")
def delete_teacher_level(
    level_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    from sqlalchemy import select as _select
    from app.models.business import TeacherLevel as _TL
    from app.models.user import User as _U
    row = db.get(_TL, level_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="级别不存在")
    used = db.scalar(_select(_U.id).where(_U.teacher_level_id == str(row.id)))
    if used is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该级别仍被教师使用，先调整教师级别后再删除")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------- 提成规则 ----------

class CommissionRuleIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    amount: Decimal = Field(ge=0, le=1000000)
    unit: str | None = Field(default=None, max_length=32)


@router.get("/commission-rules")
def list_commission_rules(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    rows = business_crud.list_rules(db)
    return {"items": [{"id": str(r.id), "key": r.key, "label": r.label,
                       "amount": str(r.amount), "unit": r.unit, "active": r.active} for r in rows]}


@router.put("/commission-rules")
def update_commission_rules(
    payload: list[CommissionRuleIn],
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    rows = [business_crud.upsert_rule(db, key=r.key, label=r.label, amount=r.amount, unit=r.unit) for r in payload]
    return {"items": [{"key": r.key, "label": r.label, "amount": str(r.amount), "unit": r.unit} for r in rows]}


# ---------- 职务工资（与权限职务预设同源） ----------

class PostIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    base_salary: Decimal = Field(ge=0, le=1000000)


@router.get("/posts")
def list_posts(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    from sqlalchemy import select as _select
    from app.models.job_title import JobTitle as _JT
    rows = list(db.scalars(_select(_JT).order_by(_JT.name)).all())
    return {"items": [{"id": str(r.id), "name": r.name, "base_salary": str(r.base_salary or 0)} for r in rows]}


@router.post("/posts", status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    from sqlalchemy import select as _select
    from app.models.job_title import JobTitle as _JT
    name = payload.name.strip()
    if db.scalar(_select(_JT.id).where(_JT.name == name)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="职务已存在")
    row = _JT(name=name, permissions={}, base_salary=payload.base_salary)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "name": row.name, "base_salary": str(row.base_salary or 0),
            "hint": "新职务权限默认全关，请到权限管理-职务预设中授权"}


@router.patch("/posts/{post_id}")
def update_post(
    post_id: uuid.UUID,
    payload: PostIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("settings_manage")),
) -> dict:
    from app.models.job_title import JobTitle as _JT
    row = db.get(_JT, post_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职务不存在")
    if payload.name and payload.name.strip():
        row.name = payload.name.strip()
    row.base_salary = payload.base_salary
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "name": row.name, "base_salary": str(row.base_salary or 0)}


# ---------- 薪资核算 ----------

class PayrollIn(BaseModel):
    user_id: uuid.UUID
    month: str = Field(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM")
    invite_count: int = Field(default=0, ge=0)
    trial_count: int = Field(default=0, ge=0)
    convert_count: int = Field(default=0, ge=0)
    renew_count: int = Field(default=0, ge=0)
    refer_count: int = Field(default=0, ge=0)
    trial_lesson_count: int = Field(default=0, ge=0)
    lesson_commission: Decimal = Field(default=Decimal("0"), ge=0)


@router.post("/payroll/compute")
def compute_payroll_entry(
    payload: PayrollIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("finance_view")),
) -> dict:
    from app.models.user import User as _U
    user = db.get(_U, payload.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="人员不存在")
    return business_crud.compute_payroll(
        db, user=user, month=payload.month,
        counts={"invite_count": payload.invite_count, "trial_count": payload.trial_count,
                "convert_count": payload.convert_count, "renew_count": payload.renew_count,
                "refer_count": payload.refer_count, "trial_lesson_count": payload.trial_lesson_count},
        lesson_commission=payload.lesson_commission,
    )


@router.post("/payroll/auto-compute")
def auto_compute_payroll(
    month: str = Query(description="YYYY-MM"),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("finance_view")),
) -> dict:
    """薪资自动核算：进入工作台/切换月份时触发。手工确认锁定（auto=false）的不覆盖，其余按业务数据重算。"""
    from sqlalchemy import select as _select

    from app.api.routers.trials import compute_payroll_stats
    from app.models.business import PayrollEntry as _PE
    from app.models.user import Role as _Role, User as _U

    users = list(db.scalars(_select(_U).where(_U.role.in_([_Role.STAFF.value, _Role.TEACHER.value]))).all())
    existing = {
        e.user_id: e for e in db.scalars(_select(_PE).where(_PE.month == month)).all()
    }
    computed, skipped = 0, 0
    for u in users:
        e = existing.get(u.id)
        if e is not None and (e.detail or {}).get("auto", True) is False:
            skipped += 1
            continue
        stats = compute_payroll_stats(db, target_id=u.id, mon=month)
        business_crud.compute_payroll(
            db, user=u, month=month,
            counts={"invite_count": stats["invite_count"], "trial_count": stats["trial_count"],
                    "convert_count": stats["convert_count"], "renew_count": stats["renew_count"],
                    "refer_count": stats["refer_count"],
                    "trial_lesson_count": stats["trial_lesson_count"]},
            lesson_commission=Decimal(stats["lesson_commission"]),
            auto=True,
        )
        computed += 1
    return {"month": month, "computed": computed, "skipped": skipped}


@router.get("/payroll")
def list_payroll(
    month: str | None = Query(default=None, description="YYYY-MM"),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("finance_view")),
) -> dict:
    from sqlalchemy import select as _select
    from app.models.business import PayrollEntry as _PE
    from app.models.user import User as _U
    stmt = _select(_PE)
    if month:
        stmt = stmt.where(_PE.month == month)
    stmt = stmt.order_by(_PE.month.desc(), _PE.total.desc()).limit(200)
    rows = list(db.scalars(stmt).all())
    users = {u.id: u for u in db.scalars(_select(_U)).all()} if rows else {}
    items = []
    for r in rows:
        u = users.get(r.user_id)
        items.append({"id": str(r.id), "user_id": str(r.user_id),
                      "user_name": u.name if u else "?", "title": u.title if u else None,
                      "campus": u.campus if u else None, "month": r.month,
                      "auto": (r.detail or {}).get("auto", True),
                      "base_salary": str(r.base_salary), "lesson_commission": str(r.lesson_commission),
                      "invite_count": r.invite_count, "invite_bonus": str(r.invite_bonus),
                      "trial_count": r.trial_count, "trial_bonus": str(r.trial_bonus),
                      "convert_count": r.convert_count, "convert_bonus": str(r.convert_bonus),
                      "renew_count": r.renew_count, "renew_bonus": str(r.renew_bonus),
                      "refer_count": r.refer_count, "refer_bonus": str(r.refer_bonus),
                      "total": str(r.total)})
    return {"items": items}


@router.get("/workbench")
def workbench_overview(
    month: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("finance_view")),
) -> dict:
    """教务工作台：一线人员薪资总览（基本工资+各项提成），默认当月。"""
    from datetime import datetime as _dt
    from sqlalchemy import select as _select
    from app.models.business import PayrollEntry as _PE
    from app.models.user import Role as _Role
    from app.models.user import User as _U
    mon = month or _dt.now().strftime("%Y-%m")
    users = list(db.scalars(_select(_U).where(_U.role.in_([_Role.STAFF.value, _Role.TEACHER.value]))).all())
    entries = {e.user_id: e for e in db.scalars(_select(_PE).where(_PE.month == mon)).all()}
    rules = {r.key: str(r.amount) for r in business_crud.list_rules(db)}
    # 当月欠费消耗产生的绩效（学员未缴费，风险提示）
    from app.models.business import RevenueLedger as _RL

    y, m = int(mon.split("-")[0]), int(mon.split("-")[1])
    _ms = _dt(y, m, 1)
    _me = _dt(y + (m == 12), (m % 12) + 1, 1)
    _od_rows = list(
        db.execute(
            _select(_RL.teacher_id, _RL.commission).where(
                _RL.is_overdraft.is_(True),
                _RL.consumed_at >= _ms,
                _RL.consumed_at < _me,
                _RL.teacher_id.isnot(None),
            )
        ).all()
    )
    from decimal import Decimal as _Dec

    _od_map: dict = {}
    for _tid, _comm in _od_rows:
        _od_map[_tid] = _od_map.get(_tid, _Dec("0")) + _Dec(str(_comm or 0))
    items = []
    for u in users:
        e = entries.get(u.id)
        base = str(business_crud.base_salary_of(db, u))
        items.append({"user_id": str(u.id), "name": u.name, "role": u.role,
                      "title": u.title, "campus": u.campus,
                      "level": getattr(u, "teacher_level_name", None),
                      "base_salary": str(e.base_salary) if e else base,
                      "total": str(e.total) if e else base,
                      "overdraft_commission": str(_od_map.get(u.id, _Dec("0")).quantize(_Dec("0.01"))),
                      "has_entry": e is not None})
    items.sort(key=lambda x: float(x["total"]), reverse=True)
    return {"month": mon, "rules": rules, "items": items}

