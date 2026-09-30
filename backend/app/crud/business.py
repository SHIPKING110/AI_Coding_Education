"""业务基础资料 CRUD：校区 / 科目 / 财务参数（含首次seed）。"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.business import Campus, FinanceSetting, RevenueLedger, Subject

# 首次 seed：沿用业务约定的科目与默认课时口径（乐高 1.5，其余 2）
SEED_SUBJECTS: list[tuple[str, str]] = [
    ("乐高", "1.5"),
    ("9686", "2"),
    ("Scratch", "2"),
    ("EV3", "2"),
    ("Arduino", "2"),
    ("Python", "2"),
    ("C++", "2"),
]
SEED_CAMPUSES = ("一校", "二校", "总部")


# ---------- 校区 ----------

def list_campuses(db: Session, *, include_inactive: bool = False) -> list[Campus]:
    _seed_campuses(db)
    stmt = select(Campus).order_by(Campus.sort.asc(), Campus.created_at.asc())
    if not include_inactive:
        stmt = stmt.where(Campus.active.is_(True))
    return list(db.scalars(stmt).all())


def _seed_campuses(db: Session) -> None:
    if db.scalar(select(func.count(Campus.id))) or 0:
        return
    for i, name in enumerate(SEED_CAMPUSES):
        db.add(Campus(name=name, sort=i))
    db.commit()


def create_campus(db: Session, *, name: str) -> Campus:
    row = Campus(name=name.strip(), sort=(db.scalar(select(func.count(Campus.id))) or 0))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_campus(db: Session, row: Campus, *, name: str | None, active: bool | None) -> Campus:
    if name is not None and name.strip():
        row.name = name.strip()
    if active is not None:
        row.active = active
    db.commit()
    db.refresh(row)
    return row


def reorder_campuses(db: Session, ids: list) -> list[Campus]:
    """按给定 id 顺序重排校区 sort（决定各处校区筛选下拉的顺序）。"""
    rows = {str(r.id): r for r in db.scalars(select(Campus)).all()}
    for i, cid in enumerate(ids):
        row = rows.get(str(cid))
        if row is not None:
            row.sort = i
    db.commit()
    return list_campuses(db, include_inactive=True)


# ---------- 科目 ----------

def list_subjects(db: Session, *, include_inactive: bool = False) -> list[Subject]:
    _seed_subjects(db)
    stmt = select(Subject).order_by(Subject.sort.asc(), Subject.created_at.asc())
    if not include_inactive:
        stmt = stmt.where(Subject.active.is_(True))
    return list(db.scalars(stmt).all())


def get_subject(db: Session, subject_id: uuid.UUID) -> Subject | None:
    return db.get(Subject, subject_id)


def find_subject_by_name(db: Session, name: str | None) -> Subject | None:
    if not name:
        return None
    return db.scalar(
        select(Subject).where(Subject.name == name, Subject.active.is_(True))
    )


def _seed_subjects(db: Session) -> None:
    if db.scalar(select(func.count(Subject.id))) or 0:
        return
    for i, (name, per) in enumerate(SEED_SUBJECTS):
        db.add(Subject(name=name, per_session=Decimal(per), sort=i))
    db.commit()


def create_subject(
    db: Session,
    *,
    name: str,
    per_session: Decimal,
    commission_rate: Decimal | None,
) -> Subject:
    row = Subject(
        name=name.strip(),
        per_session=per_session,
        commission_rate=commission_rate,
        sort=(db.scalar(select(func.count(Subject.id))) or 0),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_subject(
    db: Session,
    row: Subject,
    *,
    name: str | None,
    per_session: Decimal | None,
    commission_rate: Decimal | None,
    active: bool | None,
) -> Subject:
    if name is not None and name.strip():
        row.name = name.strip()
    if per_session is not None:
        row.per_session = per_session
    if commission_rate is not None:
        # 空字符串/None 表示清空为全局默认由路由层转 None；此处保留显式值
        row.commission_rate = commission_rate
    if active is not None:
        row.active = active
    db.commit()
    db.refresh(row)
    return row


# ---------- 财务参数 ----------

def get_finance_setting(db: Session) -> FinanceSetting:
    row = db.get(FinanceSetting, 1)
    if row is None:
        row = FinanceSetting(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update_finance_setting(
    db: Session, *, commission_default: Decimal | None, note: str | None
) -> FinanceSetting:
    row = get_finance_setting(db)
    if commission_default is not None:
        row.commission_default = commission_default
    if note is not None:
        row.note = note
    db.commit()
    db.refresh(row)
    return row


def effective_commission_rate(
    db: Session, subject: Subject | None, teacher_id=None
) -> Decimal:
    """抽成优先级：教师级别比例 > 科目比例 > 全局默认。"""
    if teacher_id is not None:
        try:
            from app.models.business import TeacherLevel
            from app.models.user import User

            t = db.get(User, teacher_id) if not isinstance(teacher_id, User) else teacher_id
            if t is not None and getattr(t, "teacher_level_id", None):
                lv = db.scalar(
                    select(TeacherLevel).where(
                        TeacherLevel.name == getattr(t, "teacher_level_name", None)
                    )
                ) if getattr(t, "teacher_level_name", None) else None
                if lv is None:
                    lv = db.get(TeacherLevel, t.teacher_level_id) if len(str(t.teacher_level_id)) > 20 else None
                if lv is not None and getattr(lv, "active", True):
                    return Decimal(str(lv.ratio))
        except Exception:
            pass
    if subject is not None and subject.commission_rate is not None:
        return Decimal(str(subject.commission_rate))
    return Decimal(str(get_finance_setting(db).commission_default))


# ---------- 账本写入 ----------

def write_ledger(
    db: Session,
    *,
    student_id: uuid.UUID,
    lessons: Decimal,
    unit_price: Decimal,
    subject: Subject | None,
    subject_name: str,
    schedule_id: uuid.UUID | None,
    teacher_id: uuid.UUID | None,
    detail: dict | None = None,
    consumed_at: datetime | None = None,
    commit: bool = True,
) -> RevenueLedger:
    rate = effective_commission_rate(db, subject, teacher_id)
    amount = (lessons * unit_price).quantize(Decimal("0.01"))
    commission = (amount * rate).quantize(Decimal("0.01"))
    row = RevenueLedger(
        student_id=student_id,
        schedule_id=schedule_id,
        teacher_id=teacher_id,
        subject_id=subject.id if subject else None,
        subject_name=subject_name,
        lessons=lessons,
        unit_price=unit_price.quantize(Decimal("0.0001")),
        amount=amount,
        commission_rate=rate,
        commission=commission,
        detail=detail,
        consumed_at=consumed_at or datetime.now(UTC),
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    return row


ORDER_EXPIRE_MINUTES = 5


def default_expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=ORDER_EXPIRE_MINUTES)


# ---------- 教师级别 ----------

def list_levels(db, *, include_inactive=False):
    from app.models.business import TeacherLevel
    stmt = select(TeacherLevel).order_by(TeacherLevel.sort.asc(), TeacherLevel.created_at.asc())
    if not include_inactive:
        stmt = stmt.where(TeacherLevel.active.is_(True))
    return list(db.scalars(stmt).all())


def create_level(db, *, name, ratio):
    from app.models.business import TeacherLevel
    row = TeacherLevel(name=name.strip(), ratio=ratio,
                       sort=(db.scalar(select(func.count(TeacherLevel.id))) or 0))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_level(db, row, *, name=None, ratio=None, active=None):
    if name is not None and name.strip():
        row.name = name.strip()
    if ratio is not None:
        row.ratio = ratio
    if active is not None:
        row.active = active
    db.commit()
    db.refresh(row)
    return row


# ---------- 提成规则 ----------

DEFAULT_RULES = [
    ("invite", "电话意向人头奖", "5", "元/人"),
    ("trial", "邀约到场体验课提成", "30", "元/人"),
    ("convert", "体验课转化报名提成", "100", "元/单"),
    ("renew", "续费提成", "80", "元/单"),
    ("refer", "口碑转介绍奖", "50", "元/人"),
    ("trial_lesson", "体验课课时提成", "20", "元/人"),
]


def list_rules(db):
    from app.models.business import CommissionRule
    rows = list(db.scalars(select(CommissionRule).order_by(CommissionRule.key)).all())
    if not rows:
        for key, label, amount, unit in DEFAULT_RULES:
            db.add(CommissionRule(key=key, label=label, amount=Decimal(amount), unit=unit))
        db.commit()
        rows = list(db.scalars(select(CommissionRule).order_by(CommissionRule.key)).all())
    return rows


def upsert_rule(db, *, key, label, amount, unit):
    from app.models.business import CommissionRule
    row = db.scalar(select(CommissionRule).where(CommissionRule.key == key))
    if row is None:
        row = CommissionRule(key=key, label=label or key, amount=amount, unit=unit or "元")
        db.add(row)
    else:
        if label is not None:
            row.label = label
        row.amount = amount
        if unit is not None:
            row.unit = unit
    db.commit()
    db.refresh(row)
    return row


def rule_map(db):
    return {r.key: Decimal(str(r.amount)) for r in list_rules(db)}


# ---------- 薪资核算 ----------

def base_salary_of(db, user):
    if getattr(user, "base_salary", None) is not None:
        return Decimal(str(user.base_salary))
    if getattr(user, "title", None):
        from app.models.job_title import JobTitle
        jt = db.scalar(select(JobTitle).where(JobTitle.name == user.title))
        if jt is not None and jt.base_salary is not None:
            return Decimal(str(jt.base_salary))
    return Decimal("0")


def compute_payroll(db, *, user, month, counts, lesson_commission=Decimal("0")):
    from app.models.business import PayrollEntry
    rules = rule_map(db)
    base = base_salary_of(db, user)

    def bonus(key, count):
        return (Decimal(str(count or 0)) * rules.get(key, Decimal("0"))).quantize(Decimal("0.01"))

    invite_b = bonus("invite", counts.get("invite_count"))
    trial_b = bonus("trial", counts.get("trial_count"))
    convert_b = bonus("convert", counts.get("convert_count"))
    renew_b = bonus("renew", counts.get("renew_count"))
    refer_b = bonus("refer", counts.get("refer_count"))
    trial_lesson_b = bonus("trial_lesson", counts.get("trial_lesson_count"))
    lesson_c = Decimal(str(lesson_commission or 0))
    total = (base + lesson_c + invite_b + trial_b + convert_b + renew_b + refer_b + trial_lesson_b).quantize(Decimal("0.01"))
    row = db.scalar(select(PayrollEntry).where(PayrollEntry.user_id == user.id, PayrollEntry.month == month))
    payload = dict(base_salary=base, lesson_commission=lesson_c,
                   invite_count=int(counts.get("invite_count") or 0), invite_bonus=invite_b,
                   trial_count=int(counts.get("trial_count") or 0), trial_bonus=(trial_b + trial_lesson_b),
                   convert_count=int(counts.get("convert_count") or 0), convert_bonus=convert_b,
                   renew_count=int(counts.get("renew_count") or 0), renew_bonus=renew_b,
                   refer_count=int(counts.get("refer_count") or 0), refer_bonus=refer_b,
                   total=total, detail={"rules": {k: str(v) for k, v in rules.items()}})
    if row is None:
        row = PayrollEntry(user_id=user.id, month=month, **payload)
        db.add(row)
    else:
        for k, v in payload.items():
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "user_id": str(user.id), "month": month,
            "base_salary": str(base), "lesson_commission": str(lesson_c),
            "invite_bonus": str(invite_b), "trial_bonus": str(trial_b + trial_lesson_b),
            "convert_bonus": str(convert_b), "renew_bonus": str(renew_b),
            "refer_bonus": str(refer_b), "total": str(total)}
