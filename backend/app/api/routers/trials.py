"""体验课域：邀约记录 / 聊天截图上传 / 薪资统计自动带出。"""

import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles, require_teacher_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.models.enrollment import LessonRecord, Student
from app.models.schedule import Attendance, AttendanceStatus
from app.models.trial import Invitation, InvitationStatus
from app.models.user import Role, User

router = APIRouter(prefix="/trials", tags=["trials"])

MANAGE_ROLES = (Role.ADMIN, Role.STAFF)
TEACH_ROLES = (Role.ADMIN, Role.STAFF, Role.TEACHER)


# ---------- 聊天截图上传 ----------

class UploadOut(BaseModel):
    url: str
    filename: str


@router.post("/upload", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
def upload_chat_image(
    file: UploadFile,
    _: User = Depends(require_roles(*TEACH_ROLES)),
) -> UploadOut:
    """邀约聊天截图上传：仅图片，本地磁盘存储，前端直接展示。"""
    settings = get_settings()
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持图片文件")
    size_limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    suffix = Path(file.filename or "file").suffix or ".jpg"
    fname = f"{uuid.uuid4().hex}{suffix}"
    target_dir = Path(settings.UPLOAD_DIR) / "invitations"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / fname
    written = 0
    with open(target, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > size_limit:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"文件过大，最大 {settings.MAX_UPLOAD_SIZE_MB}MB",
                )
            out.write(chunk)
    return UploadOut(url=f"/uploads/invitations/{fname}", filename=file.filename or fname)


# ---------- 邀约记录 ----------

class InvitationIn(BaseModel):
    parent_name: str = Field(min_length=1, max_length=64)
    parent_phone: str | None = Field(default=None, max_length=20)
    student_name: str = Field(min_length=1, max_length=64)
    subject_id: uuid.UUID | None = None
    subject_name: str | None = Field(default=None, max_length=64)
    chat_images: list[str] | None = None
    remark: str | None = None


class InvitationUpdate(BaseModel):
    status: str | None = None
    parent_name: str | None = Field(default=None, max_length=64)
    parent_phone: str | None = Field(default=None, max_length=20)
    student_name: str | None = Field(default=None, max_length=64)
    chat_images: list[str] | None = None
    remark: str | None = None
    subject_id: uuid.UUID | None = None
    subject_name: str | None = None
    trial_student_id: uuid.UUID | None = None
    trial_schedule_id: uuid.UUID | None = None
    trial_class_id: uuid.UUID | None = None
    trial_teacher_id: uuid.UUID | None = None


def _trial_student_has_financial_trace(db: Session, student_id: uuid.UUID) -> bool:
    """体验学员是否有资金痕迹（充值/扣课流水、订单）：有则不可自动清档。"""
    from app.models.enrollment import LessonRecord, Order

    rec = db.scalar(select(LessonRecord.id).where(LessonRecord.student_id == student_id).limit(1))
    if rec is not None:
        return True
    order = db.scalar(select(Order.id).where(Order.student_id == student_id).limit(1))
    return order is not None


def _delete_trial_student(db: Session, stu: Student) -> None:
    """删除体验中学员档案（含考勤占位；账本/订单由调用方先检查）。

    邀约侧的外键先置空（邀约记录本身保留备查），分班关联由数据库级联删除。
    """
    from app.models.schedule import Attendance as _Att

    db.execute(delete(_Att).where(_Att.student_id == stu.id))
    db.execute(
        Invitation.__table__.update()
        .where(Invitation.trial_student_id == stu.id)
        .values(trial_student_id=None)
    )
    db.delete(stu)


def _inv_out(inv: Invitation, db: Session) -> dict:
    from app.models.business import Subject as _Subject

    staff = db.get(User, inv.staff_id) if inv.staff_id else None
    teacher = db.get(User, inv.trial_teacher_id) if inv.trial_teacher_id else None
    subject = db.get(_Subject, inv.subject_id) if inv.subject_id else None
    # 排课后显示排课班级：优先取排课关联的班级名，回退到邀约直连的班级
    trial_class_name: str | None = None
    if inv.trial_schedule_id:
        from app.models.schedule import Schedule as _Sched

        sched = db.get(_Sched, inv.trial_schedule_id)
        if sched is not None and getattr(sched, "schedule_class", None) is not None:
            trial_class_name = sched.schedule_class.name
    if trial_class_name is None and inv.trial_class_id:
        from app.models.enrollment import Class as _Class

        cls = db.get(_Class, inv.trial_class_id)
        trial_class_name = cls.name if cls else None
    return {
        "id": str(inv.id),
        "staff_id": str(inv.staff_id) if inv.staff_id else None,
        "staff_name": staff.name if staff else None,
        "staff_campus": staff.campus if staff else None,
        "parent_name": inv.parent_name,
        "parent_phone": inv.parent_phone,
        "student_name": inv.student_name,
        "subject_id": str(inv.subject_id) if inv.subject_id else None,
        "subject_name": subject.name if subject else (inv.subject_name or ""),
        "status": inv.status,
        "chat_images": inv.chat_images or [],
        "remark": inv.remark,
        "trial_student_id": str(inv.trial_student_id) if inv.trial_student_id else None,
        "trial_schedule_id": str(inv.trial_schedule_id) if inv.trial_schedule_id else None,
        "trial_class_id": str(inv.trial_class_id) if inv.trial_class_id else None,
        "trial_teacher_id": str(inv.trial_teacher_id) if inv.trial_teacher_id else None,
        "trial_teacher_name": teacher.name if teacher else None,
        "trial_class_name": trial_class_name,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


@router.post("/invitations", status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InvitationIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("invitation_create")),
) -> dict:
    """新建邀约记录：教务约到有意向家长，保存信息与聊天截图。"""
    inv = Invitation(
        staff_id=user.id,
        parent_name=payload.parent_name,
        parent_phone=payload.parent_phone,
        student_name=payload.student_name,
        subject_id=payload.subject_id,
        subject_name=payload.subject_name or "",
        status=InvitationStatus.INVITED.value,
        chat_images=payload.chat_images,
        remark=payload.remark,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return _inv_out(inv, db)


@router.get("/invitations")
def list_invitations(
    staff_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None),
    subject_id: uuid.UUID | None = Query(default=None),
    trial_teacher_id: uuid.UUID | None = Query(default=None, description="体验教师"),
    campus: str | None = Query(default=None, description="邀约人所属校区"),
    date_from: str | None = Query(default=None, description="记录日期起 YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="记录日期止 YYYY-MM-DD"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """邀约记录列表：状态/关键字/科目/邀约人/体验教师/邀约人校区/时间范围筛选。教师仅看与自己相关的。"""
    from datetime import datetime as _dt

    stmt = select(Invitation).outerjoin(User, Invitation.staff_id == User.id)
    count_stmt = select(func.count(Invitation.id)).outerjoin(User, Invitation.staff_id == User.id)
    if staff_id:
        stmt = stmt.where(Invitation.staff_id == staff_id)
        count_stmt = count_stmt.where(Invitation.staff_id == staff_id)
    if status_filter:
        stmt = stmt.where(Invitation.status == status_filter)
        count_stmt = count_stmt.where(Invitation.status == status_filter)
    if subject_id:
        stmt = stmt.where(Invitation.subject_id == subject_id)
        count_stmt = count_stmt.where(Invitation.subject_id == subject_id)
    if trial_teacher_id:
        stmt = stmt.where(Invitation.trial_teacher_id == trial_teacher_id)
        count_stmt = count_stmt.where(Invitation.trial_teacher_id == trial_teacher_id)
    if campus:
        stmt = stmt.where(User.campus == campus)
        count_stmt = count_stmt.where(User.campus == campus)
    if date_from:
        try:
            _from = _dt.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_from 格式应为 YYYY-MM-DD")
        stmt = stmt.where(Invitation.created_at >= _from)
        count_stmt = count_stmt.where(Invitation.created_at >= _from)
    if date_to:
        try:
            _to = _dt.strptime(date_to, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_to 格式应为 YYYY-MM-DD")
        stmt = stmt.where(Invitation.created_at < _to + timedelta(days=1))
        count_stmt = count_stmt.where(Invitation.created_at < _to + timedelta(days=1))
    if keyword:
        kw = f"%{keyword.strip()}%"
        cond = (
            Invitation.student_name.like(kw)
            | Invitation.parent_name.like(kw)
            | Invitation.parent_phone.like(kw)
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if user.role == Role.TEACHER.value:
        cond = Invitation.trial_teacher_id == user.id
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = db.scalar(count_stmt) or 0
    rows = list(db.scalars(stmt.order_by(Invitation.created_at.desc()).limit(limit).offset(offset)).all())
    return {"items": [_inv_out(r, db) for r in rows], "total": total}


@router.patch("/invitations/{inv_id}")
def update_invitation(
    inv_id: uuid.UUID,
    payload: InvitationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*TEACH_ROLES)),
) -> dict:
    """推进邀约状态：排体验课（关联排课/班级/教师并通知教师）→ 到场 → 报名/流失。"""
    inv = db.get(Invitation, inv_id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀约记录不存在")
    if user.role == Role.TEACHER.value and inv.trial_teacher_id != user.id and inv.staff_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作他人邀约")
    if payload.status is not None:
        if payload.status not in [s.value for s in InvitationStatus]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="状态非法")
        inv.status = payload.status
    if payload.parent_name is not None:
        if not payload.parent_name.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="家长姓名不能为空")
        inv.parent_name = payload.parent_name.strip()
    if payload.parent_phone is not None:
        inv.parent_phone = payload.parent_phone.strip() or None
    if payload.student_name is not None:
        if not payload.student_name.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="学员姓名不能为空")
        inv.student_name = payload.student_name.strip()
    if payload.chat_images is not None:
        inv.chat_images = payload.chat_images
    if payload.remark is not None:
        inv.remark = payload.remark
    if payload.subject_id is not None:
        inv.subject_id = payload.subject_id
    if payload.subject_name is not None:
        inv.subject_name = payload.subject_name
    if payload.trial_student_id is not None:
        inv.trial_student_id = payload.trial_student_id
    if payload.trial_schedule_id is not None:
        inv.trial_schedule_id = payload.trial_schedule_id
    if payload.trial_class_id is not None:
        inv.trial_class_id = payload.trial_class_id
    if payload.trial_teacher_id is not None:
        inv.trial_teacher_id = payload.trial_teacher_id
    # 排上体验课 → 通知教师（写清班级时间）
    if payload.trial_schedule_id is not None and inv.trial_teacher_id:
        from app.crud import notification as notif_crud
        from app.models.schedule import Schedule as _Sched

        sched = db.get(_Sched, inv.trial_schedule_id)
        if sched is not None:
            cname = sched.schedule_class.name if sched.schedule_class else ""
            st = sched.start_time.strftime("%m-%d %H:%M") if sched.start_time else ""
            notif_crud.create(
                db,
                user_id=inv.trial_teacher_id,
                type="trial_assigned",
                title="您有新的体验课安排",
                content=f"体验学员「{inv.student_name}」已安排到 {cname}（{st}），请准时上课",
                data={
                    "invitation_id": str(inv.id),
                    "schedule_id": str(sched.id),
                    "student_name": inv.student_name,
                },
            )
    db.commit()
    db.refresh(inv)
    return _inv_out(inv, db)


@router.delete("/invitations/{inv_id}")
def delete_invitation(
    inv_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*TEACH_ROLES)),
) -> dict:
    """删除邀约记录：已报名转正的不允许删；仍处于体验中的学员档案连带清档（有资金痕迹的不删）。"""
    inv = db.get(Invitation, inv_id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀约记录不存在")
    if user.role == Role.TEACHER.value and inv.trial_teacher_id != user.id and inv.staff_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作他人邀约")
    cleaned_student = False
    if inv.trial_student_id:
        stu = db.get(Student, inv.trial_student_id)
        if stu is not None:
            if (stu.trial_status or "none") == "signed":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="该学员已报名转正，不可删除邀约记录",
                )
            if _trial_student_has_financial_trace(db, stu.id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="关联学员已有缴费/课时记录，不可删除，请先处理账务",
                )
            _delete_trial_student(db, stu)
            cleaned_student = True
    db.delete(inv)
    db.commit()
    return {"deleted": True, "cleaned_student": cleaned_student}


@router.post("/invitations/{inv_id}/trial-student", status_code=status.HTTP_201_CREATED)
def create_trial_student(
    inv_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*TEACH_ROLES)),
) -> dict:
    """为邀约建体验学员档案（复用学员表，trial_status=trial，不占正式名额）。"""
    inv = db.get(Invitation, inv_id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀约记录不存在")
    if inv.trial_student_id:
        stu = db.get(Student, inv.trial_student_id)
        if stu is not None:
            from app.api.routers.students import _to_out as _sout

            return _sout(stu, db).model_dump()
    stu = Student(
        name=inv.student_name,
        phone=inv.parent_phone,
        lesson_balance=Decimal("0"),
        trial_status="trial",
        source="normal",
    )
    db.add(stu)
    db.flush()
    inv.trial_student_id = stu.id
    if inv.status == InvitationStatus.INVITED.value:
        inv.status = InvitationStatus.SCHEDULED.value
    db.commit()
    db.refresh(stu)
    from app.api.routers.students import _to_out as _sout

    return _sout(stu, db).model_dump()


class TrialStatusUpdate(BaseModel):
    trial_status: str
    source: str | None = None
    referrer: str | None = None


@router.patch("/students/{student_id}/trial-status")
def update_trial_status(
    student_id: uuid.UUID,
    payload: TrialStatusUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("student_edit")),
) -> dict:
    """体验收尾：signed=报名成功转正式（计转化提成），lost=未报名结束服务并自动清档。报名时可标口碑来源。"""
    from app.api.routers.students import _to_out as _sout
    from app.crud import student as student_crud

    if payload.trial_status not in ("trial", "signed", "lost", "none"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="状态非法")
    stu = student_crud.get(db, student_id)
    if stu is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="学员不存在")
    cleaned = False
    inv = db.scalar(select(Invitation).where(Invitation.trial_student_id == stu.id))
    if payload.trial_status == "lost" and (stu.trial_status or "none") == "trial":
        # 未报名结束：自动删除体验档案（邀约记录保留备查）；有资金痕迹的不删
        if _trial_student_has_financial_trace(db, stu.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该学员已有缴费/课时记录，不可直接结束，请先处理账务",
            )
        _delete_trial_student(db, stu)
        cleaned = True
    else:
        stu.trial_status = payload.trial_status
    if payload.source is not None:
        if payload.source not in ("normal", "referral"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="生源非法")
        if not cleaned:
            stu.source = payload.source
    if payload.referrer is not None and not cleaned:
        stu.referrer = payload.referrer
    # 同步邀约记录状态
    if inv is not None:
        if payload.trial_status == "signed":
            inv.status = InvitationStatus.SIGNED.value
        elif payload.trial_status == "lost":
            inv.status = InvitationStatus.LOST.value
    db.commit()
    if cleaned:
        return {"deleted_student": True, "student_id": str(student_id)}
    db.refresh(stu)
    return _sout(stu, db).model_dump()


# ---------- 薪资统计自动带出 ----------

def _month_range(mon: str) -> tuple:
    from datetime import datetime as _dt

    try:
        y, m = int(mon.split("-")[0]), int(mon.split("-")[1])
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="月份格式应为 YYYY-MM")
    ms = _dt(y, m, 1)
    me = _dt(y + (m == 12), (m % 12) + 1, 1)
    return ms, me


@router.get("/payroll-evidence")
def payroll_evidence(
    kind: str = Query(description="invite|arrived|trial|convert|renew|refer|commission"),
    month: str | None = Query(default=None, description="YYYY-MM"),
    user_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """薪资溯源明细：每一项提成数量点开看具体名单（人/时间/金额），错了可追溯。"""
    from datetime import datetime as _dt

    from app.models.business import RevenueLedger as _RL
    from app.models.schedule import Schedule as _Sched

    mon = month or _dt.now().strftime("%Y-%m")
    target_id = user_id or user.id
    if user.role == Role.TEACHER.value and target_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="教师只能查看本人明细")
    ms, me = _month_range(mon)
    items: list[dict] = []
    if kind in ("invite", "arrived"):
        invs = list(
            db.scalars(
                select(Invitation).where(
                    Invitation.staff_id == target_id,
                    Invitation.created_at >= ms,
                    Invitation.created_at < me,
                )
            ).all()
        )
        if kind == "arrived":
            invs = [i for i in invs if i.status in ("arrived", "signed")]
        teacher_of = {}
        for i in invs:
            items.append(
                {
                    "id": str(i.id),
                    "student_name": i.student_name,
                    "parent": f"{i.parent_name or ''}{(' · ' + i.parent_phone) if i.parent_phone else ''}",
                    "subject": i.subject_name or "—",
                    "status": i.status,
                    "teacher": teacher_of.get(i.trial_teacher_id) if i.trial_teacher_id else None,
                    "time": i.created_at.strftime("%m-%d %H:%M") if i.created_at else "—",
                }
            )
            if i.trial_teacher_id and i.trial_teacher_id not in teacher_of:
                t = db.get(User, i.trial_teacher_id)
                teacher_of[i.trial_teacher_id] = t.name if t else "—"
                items[-1]["teacher"] = teacher_of[i.trial_teacher_id]
    elif kind == "trial":
        atts = list(
            db.scalars(
                select(Attendance).where(
                    Attendance.is_trial.is_(True),
                    Attendance.status == AttendanceStatus.ATTENDED.value,
                    Attendance.created_at >= ms,
                    Attendance.created_at < me,
                )
            ).all()
        )
        for a in atts:
            sched = db.get(_Sched, a.schedule_id)
            if sched is None or sched.teacher_id != target_id:
                continue
            stu = db.get(Student, a.student_id)
            cname = sched.schedule_class.name if sched.schedule_class else "体验课（无班级）"
            items.append(
                {
                    "id": str(a.id),
                    "student_name": stu.name if stu else "—",
                    "class": cname,
                    "time": sched.start_time.strftime("%m-%d %H:%M") if sched.start_time else "—",
                }
            )
    elif kind in ("convert", "refer"):
        studs = list(
            db.scalars(
                select(Student).where(
                    Student.trial_status == "signed",
                    Student.updated_at >= ms,
                    Student.updated_at < me,
                )
            ).all()
        )
        for s in studs:
            inv = db.scalar(select(Invitation).where(Invitation.trial_student_id == s.id))
            if inv is None or inv.trial_teacher_id != target_id:
                continue
            if kind == "refer" and s.source != "referral":
                continue
            items.append(
                {
                    "id": str(s.id),
                    "student_name": s.name,
                    "source": "口碑" if s.source == "referral" else "自然",
                    "referrer": s.referrer or "—",
                    "time": s.updated_at.strftime("%m-%d %H:%M") if s.updated_at else "—",
                }
            )
    elif kind == "renew":
        from app.models.enrollment import Class as _Class

        taught: set = set()
        for c in db.scalars(select(_Class)).all():
            if getattr(c, "teacher_id", None) == target_id:
                for s in c.students:
                    taught.add(s.id)
        recs = list(
            db.scalars(
                select(LessonRecord).where(
                    LessonRecord.record_type == "recharge",
                    LessonRecord.delta > 0,
                    LessonRecord.created_at >= ms,
                    LessonRecord.created_at < me,
                    LessonRecord.student_id.in_(taught) if taught else False,
                )
            ).all()
        )
        for r in recs:
            stu = db.get(Student, r.student_id)
            items.append(
                {
                    "id": str(r.id),
                    "student_name": stu.name if stu else "—",
                    "lessons": str(r.delta),
                    "amount": str(r.amount or "—"),
                    "time": r.created_at.strftime("%m-%d %H:%M") if r.created_at else "—",
                }
            )
    elif kind == "commission":
        for r in db.scalars(
            select(_RL).where(
                _RL.teacher_id == target_id,
                _RL.consumed_at >= ms,
                _RL.consumed_at < me,
            )
        ).all():
            stu = db.get(Student, r.student_id)
            items.append(
                {
                    "id": str(r.id),
                    "student_name": stu.name if stu else "—",
                    "subject": r.subject_name or "—",
                    "lessons": str(r.lessons),
                    "amount": str(r.amount),
                    "commission": str(r.commission),
                    "overdraft": bool(r.is_overdraft),
                    "time": r.consumed_at.strftime("%m-%d %H:%M") if r.consumed_at else "—",
                }
            )
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kind 非法")
    return {"kind": kind, "month": mon, "count": len(items), "items": items}


@router.get("/payroll-stats")
def payroll_stats(
    month: str | None = Query(default=None, description="YYYY-MM"),
    user_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """薪资核算自动统计：各项提成数量 + 证据链（ids），核算弹窗直接带出免手填。"""
    from datetime import datetime as _dt

    mon = month or _dt.now().strftime("%Y-%m")
    target_id = user_id or user.id
    if user.role == Role.TEACHER.value and target_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="教师只能查看本人统计")
    return compute_payroll_stats(db, target_id=target_id, mon=mon)


def compute_payroll_stats(db: Session, *, target_id: uuid.UUID, mon: str) -> dict:
    """薪资核算自动统计（可复用）：各项提成数量 + 证据链 ids + 课时绩效。"""
    from app.models.business import RevenueLedger as _RL

    ms, me = _month_range(mon)

    # 邀约/到场（按邀约教务）
    inv_q = select(Invitation).where(
        Invitation.staff_id == target_id,
        Invitation.created_at >= ms,
        Invitation.created_at < me,
    )
    invs = list(db.scalars(inv_q).all())
    arrived = [i for i in invs if i.status in ("arrived", "signed")]
    # 体验课节数（按体验教师：免费考勤到场）
    trial_atts = list(
        db.scalars(
            select(Attendance).where(
                Attendance.is_trial.is_(True),
                Attendance.status == AttendanceStatus.ATTENDED.value,
                Attendance.created_at >= ms,
                Attendance.created_at < me,
            )
        ).all()
    )
    from app.models.schedule import Schedule as _Sched

    trial_lessons = 0
    trial_ids: list[str] = []
    for a in trial_atts:
        sched = db.get(_Sched, a.schedule_id)
        if sched is not None and sched.teacher_id == target_id:
            trial_lessons += 1
            trial_ids.append(str(a.id))
    # 转化报名（体验教师名下 signed 学员）
    conv_q = list(
        db.scalars(
            select(Student).where(
                Student.trial_status == "signed",
                Student.updated_at >= ms,
                Student.updated_at < me,
            )
        ).all()
    )
    convert_ids: list[str] = []
    for s in conv_q:
        inv = db.scalar(select(Invitation).where(Invitation.trial_student_id == s.id))
        if inv is not None and inv.trial_teacher_id == target_id:
            convert_ids.append(str(s.id))
    # 续费单数（该教师所带在读学员当月充值次数）
    from app.models.enrollment import Class as _Class

    taught_ids: set = set()
    for c in db.scalars(select(_Class)).all():
        if getattr(c, "teacher_id", None) == target_id:
            for s in c.students:
                taught_ids.add(s.id)
    renew_recs = list(
        db.scalars(
            select(LessonRecord).where(
                LessonRecord.record_type == "recharge",
                LessonRecord.delta > 0,
                LessonRecord.created_at >= ms,
                LessonRecord.created_at < me,
                LessonRecord.student_id.in_(taught_ids) if taught_ids else False,
            )
        ).all()
    )
    # 口碑转介绍（该教师体验课上报名且来源=referral）
    _signed = {str(s.id): s for s in conv_q}
    refer_ids = [sid for sid in convert_ids if _signed.get(sid) is not None and _signed[sid].source == "referral"]
    # 课时绩效（账本提成求和）
    ledgers = list(
        db.scalars(
            select(_RL).where(
                _RL.teacher_id == target_id,
                _RL.consumed_at >= ms,
                _RL.consumed_at < me,
            )
        ).all()
    )
    commission = sum((Decimal(str(r.commission)) for r in ledgers), Decimal("0"))
    return {
        "month": mon,
        "user_id": str(target_id),
        "invite_count": len(invs),
        "invite_ids": [str(i.id) for i in invs],
        "trial_count": len(arrived),
        "arrived_ids": [str(i.id) for i in arrived],
        "trial_lesson_count": trial_lessons,
        "trial_attendance_ids": trial_ids,
        "convert_count": len(convert_ids),
        "convert_ids": convert_ids,
        "renew_count": len(renew_recs),
        "renew_ids": [str(r.id) for r in renew_recs],
        "refer_count": len(refer_ids),
        "refer_ids": refer_ids,
        "lesson_commission": str(commission.quantize(Decimal("0.01"))),
    }
