import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles, require_teacher_permission
from app.core.database import get_db
from app.crud import attendance as attendance_crud
from app.crud import business as business_crud
from app.crud import lesson as lesson_crud
from app.crud import order as order_crud
from app.crud import schedule as schedule_crud
from app.crud import student as student_crud
from app.models.enrollment import LessonRecordType
from app.models.schedule import Attendance as AttendanceModel
from app.models.schedule import AttendanceStatus, Schedule, ScheduleStatus
from app.models.user import Role, User
from app.schemas.schedule import (
    AttendanceBatchIn,
    AttendanceBatchResult,
    AttendanceOut,
    ConflictOut,
    ScheduleCreate,
    ScheduleCreateResponse,
    ScheduleOut,
    ScheduleRecurringCreate,
    ScheduleRecurringResponse,
    ScheduleUpdate,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])

# 排课/考勤管理：admin / staff / teacher（教师可给自己班级排课、考勤）
MANAGE_ROLES = (Role.ADMIN, Role.STAFF, Role.TEACHER)


def _schedule_out(s: Schedule) -> ScheduleOut:
    return ScheduleOut(
        id=s.id,
        class_id=s.class_id,
        class_name=s.schedule_class.name if s.schedule_class else None,
        subject=s.schedule_class.subject if s.schedule_class else None,
        teacher_id=s.teacher_id,
        teacher_name=s.teacher.name if s.teacher else None,
        start_time=s.start_time,
        end_time=s.end_time,
        status=s.status,
        is_trial=s.is_trial,
        created_at=s.created_at,
    )


def _conflict_out(s: Schedule) -> ConflictOut:
    return ConflictOut(
        id=s.id,
        class_name=s.schedule_class.name if s.schedule_class else None,
        teacher_name=s.teacher.name if s.teacher else None,
        start_time=s.start_time,
        end_time=s.end_time,
        status=s.status,
    )


@router.get("", response_model=list[ScheduleOut])
def list_schedules(
    start: datetime | None = None,
    end: datetime | None = None,
    class_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
    campus: str | None = Query(default=None, description="按教师所属校区过滤课表"),
    status_filter: str | None = Query(
        default=None, alias="status", description="按状态过滤：scheduled/completed/cancelled"
    ),
    limit: int = Query(default=500, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("schedule_create")),
) -> list[ScheduleOut]:
    schedules = schedule_crud.list_all(
        db,
        start=start,
        end=end,
        class_id=class_id,
        teacher_id=teacher_id,
        campus=campus,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return [_schedule_out(s) for s in schedules]


@router.post("", response_model=ScheduleCreateResponse, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("schedule_create")),
) -> ScheduleCreateResponse:
    if payload.end_time <= payload.start_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="结束时间必须晚于开始时间"
        )
    # 教师新建排课只能排自己的课（管理员/教务可指定带教教师）
    teacher_id = payload.teacher_id
    if user.role == Role.TEACHER.value:
        teacher_id = user.id
    if payload.class_id is not None:
        from app.models.enrollment import Class as _Class

        if db.get(_Class, payload.class_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="班级不存在")

    conflicts = schedule_crud.find_conflicts(
        db,
        start=payload.start_time,
        end=payload.end_time,
        teacher_id=teacher_id,
        class_id=payload.class_id,
    )

    if conflicts and not payload.force:
        # 不强制：返回冲突列表，前端确认后 force=true 重试
        return ScheduleCreateResponse(
            created=False,
            conflicts=[_conflict_out(c) for c in conflicts],
        )

    s = schedule_crud.create(
        db,
        class_id=payload.class_id,
        teacher_id=teacher_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        is_trial=payload.is_trial,
    )
    return ScheduleCreateResponse(schedule=_schedule_out(s), created=True)


def _generate_recurring(
    *,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
    start_date: date,
    slots: list,
    total_lessons: int,
) -> list[tuple[datetime, datetime]]:
    """按 每周N节 × 连续周 生成 (start, end) 时间对，直到排满 total_lessons 节。

    规则：从 start_date 所在周开始；每节对应一个 slot；同一周内按 slot 顺序，
    依次推进后续周。weekday: 1=周一 ... 7=周日。
    """
    # 找 start_date 所在周的周一
    monday = start_date - timedelta(days=start_date.isoweekday() - 1)
    slots_sorted = sorted(slots, key=lambda s: s.weekday)

    result: list[tuple[datetime, datetime]] = []
    lesson_no = 0
    week_no = 0
    while lesson_no < total_lessons:
        week_monday = monday + timedelta(weeks=week_no)
        for slot in slots_sorted:
            if lesson_no >= total_lessons:
                break
            day = week_monday + timedelta(days=slot.weekday - 1)
            # 跳过起始日之前的日期（起始周内早于起始日的星期不排）
            if day < start_date:
                continue
            hh, mm = (int(x) for x in slot.start_time.split(":"))
            start = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)
            end = start + timedelta(minutes=slot.duration_min)
            result.append((start, end))
            lesson_no += 1
        week_no += 1
    return result


@router.post(
    "/recurring",
    response_model=ScheduleRecurringResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_recurring_schedules(
    payload: ScheduleRecurringCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("schedule_create")),
) -> ScheduleRecurringResponse:
    """循环排课：每周 N 节 × 连续周，直到排满 total_lessons 节。教师只能排自己的课。"""
    teacher_id = payload.teacher_id
    if user.role == Role.TEACHER.value:
        teacher_id = user.id
    generated = _generate_recurring(
        class_id=payload.class_id,
        teacher_id=payload.teacher_id,
        start_date=payload.start_date,
        slots=payload.slots,
        total_lessons=payload.total_lessons,
    )

    # 先做整体冲突检测（同一教师，含批次内部互检 + 与既有排课互检）
    conflicts: list[ConflictOut] = []
    for idx, (start, end) in enumerate(generated):
        existing = schedule_crud.find_conflicts(
            db, start=start, end=end, teacher_id=teacher_id, class_id=payload.class_id
        )
        for c in existing:
            item = _conflict_out(c)
            if item not in conflicts:
                conflicts.append(item)
        # 批次内部互检：与前面生成的排课比较
        for j in range(idx):
            s2, e2 = generated[j]
            if start < e2 and s2 < end:
                conflicts.append(
                    ConflictOut(
                        id=uuid.uuid4(),
                        class_name=payload.class_id.hex[:8],
                        teacher_name="本批次",
                        start_time=start,
                        end_time=end,
                        status=ScheduleStatus.SCHEDULED,
                    )
                )
                break

    if conflicts and not payload.force:
        return ScheduleRecurringResponse(created=False, conflicts=conflicts)

    created: list[Schedule] = []
    for start, end in generated:
        s = schedule_crud.create(
            db,
            class_id=payload.class_id,
            teacher_id=teacher_id,
            start_time=start,
            end_time=end,
        )
        created.append(s)
    return ScheduleRecurringResponse(
        created=True,
        created_count=len(created),
        schedules=[_schedule_out(s) for s in created],
    )


def _require_own_schedule(s, user: User) -> None:
    """教师只能操作本人所带班级的排课（管理员/教务不受限）。"""
    if user.role == Role.TEACHER.value and s.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能操作你自己所带班级的排课")


@router.get("/{schedule_id}", response_model=ScheduleOut)
def get_schedule(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScheduleOut:
    s = schedule_crud.get(db, schedule_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    _require_own_schedule(s, user)
    return _schedule_out(s)


@router.patch("/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
) -> ScheduleOut:
    s = schedule_crud.get(db, schedule_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    _require_own_schedule(s, user)
    # 教师改排课不能转给其他教师
    if user.role == Role.TEACHER.value and payload.teacher_id is not None and payload.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不能把排课转给其他教师")

    new_start = payload.start_time or s.start_time
    new_end = payload.end_time or s.end_time
    if new_end <= new_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="结束时间必须晚于开始时间"
        )

    # 若时间变更，检测冲突（同一教师，排除自身）
    new_teacher_id = payload.teacher_id or s.teacher_id
    if new_start != s.start_time or new_end != s.end_time or new_teacher_id != s.teacher_id:
        conflicts = schedule_crud.find_conflicts(
            db,
            start=new_start,
            end=new_end,
            teacher_id=new_teacher_id,
            class_id=s.class_id,
            exclude_schedule_id=s.id,
        )
        if conflicts and not payload.force:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"conflicts": [_conflict_out(c) for c in conflicts]},
            )

    s = schedule_crud.update(
        db,
        s,
        start_time=payload.start_time,
        end_time=payload.end_time,
        teacher_id=payload.teacher_id,
    )
    return _schedule_out(s)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_schedule(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("schedule_cancel")),
) -> None:
    s = schedule_crud.get(db, schedule_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    _require_own_schedule(s, user)
    # 对账门禁：已有学员操作（请假/已到）时不允许直接取消，否则账对不上
    if attendance_crud.acted_count(db, schedule_id) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该排课已有学员请假或考勤记录，无法直接取消；如需调整请先联系教务处理考勤后再试",
        )
    schedule_crud.cancel(db, s)


# ---------------- 考勤 / 划课时 ----------------


def _attendance_out(a: AttendanceModel) -> AttendanceOut:
    balance = a.student.lesson_balance if a.student else None
    return AttendanceOut(
        id=a.id,
        schedule_id=a.schedule_id,
        student_id=a.student_id,
        student_name=a.student.name if a.student else None,
        lesson_balance=balance,
        low_balance=(balance is not None and balance <= 10),
        status=a.status,
        is_trial=a.is_trial,
        trial_status=a.student.trial_status if a.student else "none",
        created_at=a.created_at,
    )


@router.get("/{schedule_id}/attendance", response_model=list[AttendanceOut])
def get_attendance(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
) -> list[AttendanceOut]:
    s = schedule_crud.get(db, schedule_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    _require_own_schedule(s, user)
    students = attendance_crud.all_students_for_schedule(db, s)
    by_sid = attendance_crud.ensure_for_students(db, schedule_id, [st.id for st in students])
    db.flush()
    return [_attendance_out(by_sid[st.id]) for st in students]


@router.post("/{schedule_id}/attendance", response_model=AttendanceBatchResult)
def submit_attendance(
    schedule_id: uuid.UUID,
    payload: AttendanceBatchIn,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(*MANAGE_ROLES)),
) -> AttendanceBatchResult:
    s = schedule_crud.get(db, schedule_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    _require_own_schedule(s, operator)

    # 未到上课时间不允许考勤（防止误操作）
    # 排课时间与当前时间均按本地语义比较（DB 返回 aware，datetime.now 用同一 tz）
    if s.start_time > datetime.now(s.start_time.tzinfo):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未到上课时间，暂不能签到/请假",
        )

    result = AttendanceBatchResult()
    for item in payload.items:
        try:
            att = attendance_crud.find_current_attendance(db, schedule_id, item.student_id)
            if att is None:
                att = AttendanceModel(
                    schedule_id=schedule_id,
                    student_id=item.student_id,
                    status=AttendanceStatus.UNMARKED,
                )
                db.add(att)
                db.flush()

            target = item.status.lower()
            if target not in (AttendanceStatus.ATTENDED, AttendanceStatus.LEAVE):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="状态必须为 attended 或 leave"
                )

            student = student_crud.get(db, item.student_id)
            if student is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="学员不存在")

            # 防重：已到/请假 后不允许再次变更（按钮置灰在前端，后端二次校验）
            if att.status != AttendanceStatus.UNMARKED:
                result.errors.append(
                    {"student_id": str(item.student_id), "reason": "该学员考勤已标记，不能重复操作"}
                )
                continue

            changed = False

            if target == AttendanceStatus.ATTENDED:
                # 划课时：按科目单次课时数扣除（乐高 1.5，其余默认 2，可在科目设置改）
                # 体验中学员免费上课：只记到场，不扣课时不计创收
                is_trial_attendance = (student.trial_status or "none") == "trial"
                if is_trial_attendance:
                    att.status = AttendanceStatus.ATTENDED
                    att.operator_id = operator.id
                    att.is_trial = True
                    result.lesson_records.append(
                        {
                            "student_id": str(item.student_id),
                            "delta": 0,
                            "balance_after": float(student.lesson_balance),
                            "is_trial": True,
                        }
                    )
                    db.flush()
                    continue
                subject_name = s.schedule_class.subject if s.schedule_class else ""
                subject = business_crud.find_subject_by_name(db, subject_name)
                per_session = (
                    Decimal(str(subject.per_session)) if subject else Decimal("2")
                )
                _cfg_max = business_crud.get_finance_setting(db).overdraft_max
                _cap = Decimal(str(_cfg_max)) if _cfg_max is not None else Decimal("10")
                if Decimal(str(student.lesson_balance)) - per_session < -_cap:
                    result.errors.append(
                        {
                            "student_id": str(item.student_id),
                            "reason": f"课时不足且已达透支上限（-{_cap}），请先续费",
                        }
                    )
                    continue
                # 创收定价：消耗瞬间 FIFO 加权单价快照（FIFO 不足部分按最近购包价兜底=欠费消耗）
                unit_price, lots = order_crud.price_for_consume(
                    db, student=student, lessons=per_session
                )
                overdraft_lessons = sum(
                    Decimal(str(lot.get("lessons", "0")))
                    for lot in lots
                    if lot.get("overdraft")
                )
                is_overdraft = overdraft_lessons > 0
                att.status = AttendanceStatus.ATTENDED
                att.operator_id = operator.id
                record = lesson_crud.add_record(
                    db,
                    student=student,
                    delta=-per_session,
                    record_type=LessonRecordType.CONSUME,
                    operator_id=operator.id,
                    ref_id=schedule_id,
                    remark=f"上课扣课时（{s.schedule_class.name if s.schedule_class else ''}，{per_session} 课时）"
                    + (
                        f"，含欠费 {overdraft_lessons} 节（应收，单价 ¥{unit_price}）"
                        if is_overdraft
                        else ""
                    ),
                    commit=False,
                )
                # 创收账本（单价/抽成快照固化，只写不改；欠费部分挂应收）
                business_crud.write_ledger(
                    db,
                    student_id=student.id,
                    lessons=per_session,
                    unit_price=unit_price,
                    subject=subject,
                    subject_name=subject_name or "未分类",
                    schedule_id=schedule_id,
                    teacher_id=s.teacher_id,
                    detail={"lots": lots, "overdraft": is_overdraft},
                    is_overdraft=is_overdraft,
                    commit=False,
                )
                result.lesson_records.append(
                    {
                        "student_id": str(item.student_id),
                        "delta": float(-per_session),
                        "balance_after": float(record.balance_after),
                    }
                )
                changed = True

            elif target == AttendanceStatus.LEAVE:
                att.status = AttendanceStatus.LEAVE
                att.operator_id = operator.id
                changed = True

            if changed:
                db.flush()

        except HTTPException as exc:
            db.rollback()
            result.errors.append({"student_id": str(item.student_id), "reason": exc.detail})

    db.commit()

    # 是否全部学员都已标记 -> 排课置为 completed
    # 注意：必须统计该排课班级的【全部】学员，而不是本次提交的 items
    # （否则先标记一个学员时会把整个排课锁成 completed，其他学员无法再操作）
    all_students = attendance_crud.all_students_for_schedule(db, s)
    all_marked = True
    if all_students:
        for st in all_students:
            att = attendance_crud.find_current_attendance(db, schedule_id, st.id)
            if att is None or att.status == AttendanceStatus.UNMARKED:
                all_marked = False
                break
    else:
        all_marked = False
    if all_marked:
        s.status = ScheduleStatus.COMPLETED
        db.commit()
        db.refresh(s)

    updated: list[AttendanceOut] = []
    for st_id in payload.items:
        att = attendance_crud.find_current_attendance(db, schedule_id, st_id.student_id)
        if att is not None:
            updated.append(_attendance_out(att))
    result.updated = _dedupe_out(updated)
    return result


def _dedupe_out(outs: list[AttendanceOut]) -> list[AttendanceOut]:
    seen: set = set()
    result: list[AttendanceOut] = []
    for o in outs:
        if o.student_id not in seen:
            seen.add(o.student_id)
            result.append(o)
    return result
