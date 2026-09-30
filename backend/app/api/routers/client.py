"""客户端 API（M5，家长/学员端）：

- GET  /client/me                        客户端首页（账号 + 名下学员，含课时余额/班级/上课提醒）
- GET  /client/students/{sid}            学员详情
- GET  /client/students/{sid}/lesson-records  课时流水（家长查看学习消耗）
- GET  /client/students/{sid}/feedbacks  已发布课后反馈（FR-CL-02）
- GET  /client/students/{sid}/schedules  学员课表（上课安排/上课提醒，FR-CL-03）
- GET  /client/packages                  在售课时包（FR-CL-04）
- POST /client/orders                    订阅下单（FR-CL-05）
- GET  /client/orders                    我的订单（FR-CL-08）
- POST /client/orders/{oid}/pay          模拟支付（FR-CL-06 提交支付）
- POST /client/orders/{oid}/cancel       取消订单
- GET  /client/assignments               我的作业列表（FR-CL-09）
- GET  /client/assignments/{aid}         作业详情（题目不含答案，防作弊）+ 我的作答
- POST /client/assignments/{aid}/answers 保存答案进度（FR-CL-12/13 自动/手动保存）
- POST /client/assignments/{aid}/submit  提交作业（FR-CL-15/16 空题校验 + 自动判题）

权限：parent（家长）/student（学员）角色；家长可访问 parent_user_id=自己的学员（多孩），
学员可访问 student_user_id=自己的学员（本人）。

将客户端权限设为仅 parent/student 时，其他角色一律 403（客户端属于家长/学员）。
"""

import uuid
from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.crud import assignment as assignment_crud
from app.crud import order as order_crud
from app.crud import submission as submission_crud
from app.models.assignment import Assignment, SubmissionStatus
from app.models.enrollment import (
    Class,
    LessonPackage,
    PackageStatus,
    Student,
    StudentClass,
    StudentStatus,
)
from app.models.evaluation import Evaluation, EvaluationStatus
from app.models.feedback import Feedback, FeedbackStatus
from app.models.schedule import Schedule, ScheduleStatus
from app.models.user import Role, User
from app.schemas.client import (
    ClientAnswersSave,
    ClientAssignmentDetail,
    ClientAssignmentListItem,
    ClientEvaluationOut,
    ClientLessonRecordOut,
    ClientMeOut,
    ClientPackageOut,
    ClientQuestionOut,
    ClientScheduleBrief,
    ClientStudentOut,
    ClientSubmissionOut,
    ClientSubmitIn,
    ClientSubmitOut,
    OrderCreate,
    OrderOut,
)
from app.schemas.enrollment import ClassBrief, PageOut
from app.schemas.feedback import FeedbackOut

router = APIRouter(prefix="/client", tags=["client"])

# 客户端角色：家长 / 学员（其他角色 403）
CLIENT_ROLES = (Role.PARENT, Role.STUDENT)


def _ensure_visible_student(db: Session, student: Student, user: User) -> Student:
    """校验当前账号可访问该学员（parent 管孩子 / student 本人）。"""
    if user.role == Role.PARENT.value:
        if student.parent_user_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该学员")
    elif user.role == Role.STUDENT.value:
        if student.student_user_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该学员")
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="客户端仅家长/学员可用")
    return student


def _get_student_or_404(db: Session, student_id: uuid.UUID) -> Student:
    student = db.get(Student, student_id)
    if student is None or student.status == StudentStatus.ARCHIVED.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="学员不存在")
    return student


def _student_out(db: Session, student: Student) -> ClientStudentOut:
    out = ClientStudentOut.model_validate(student)
    out.low_balance = student.lesson_balance <= 10
    out.has_student_account = student.student_user_id is not None
    out.classes = [
        ClassBrief(
            id=c.id,
            name=c.name,
            subject=c.subject,
            teacher_name=c.teacher.name if c.teacher else None,
        )
        for c in student.classes
    ]
    # 下一节即将开始的课（客户端首页上课提醒卡）
    class_ids = [c.id for c in student.classes]
    if class_ids:
        next_sched = db.scalars(
            select(Schedule)
            .where(
                Schedule.class_id.in_(class_ids),
                Schedule.status == ScheduleStatus.SCHEDULED.value,
                Schedule.start_time >= func.now(),
            )
            .order_by(Schedule.start_time)
            .limit(1)
        ).first()
        if next_sched is not None:
            out.next_schedule = ClientScheduleBrief(
                id=next_sched.id,
                class_name=next_sched.schedule_class.name if next_sched.schedule_class else None,
                subject=next_sched.schedule_class.subject if next_sched.schedule_class else None,
                teacher_name=next_sched.teacher.name if next_sched.teacher else None,
                start_time=next_sched.start_time,
                end_time=next_sched.end_time,
                status=next_sched.status,
            )
    return out


# ---------- 首页 ----------

@router.get("/me", response_model=ClientMeOut)
def client_me(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> ClientMeOut:
    from app.crud import notification as notification_crud
    from app.services import reminders

    # 登录即生成提醒（上课前一天 + 低课时，幂等同日不重复）
    reminders.ensure_reminders_for_user(db, user)

    students = reminders.students_for_user(db, user)
    out = ClientMeOut(
        id=user.id,
        role=user.role,
        name=user.name,
        username=user.username,
        campus=user.campus,
        students=[_student_out(db, s) for s in students],
        unread_notifications=notification_crud.count_unread(db, user_id=user.id),
    )
    return out


@router.get("/students/{student_id}", response_model=ClientStudentOut)
def client_student_detail(
    student_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> ClientStudentOut:
    student = _get_student_or_404(db, student_id)
    _ensure_visible_student(db, student, user)
    return _student_out(db, student)


# ---------- 课时流水 / 反馈 / 课表 ----------

@router.get(
    "/students/{student_id}/lesson-records", response_model=list[ClientLessonRecordOut]
)
def client_lesson_records(
    student_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> list[ClientLessonRecordOut]:
    """课时流水（家长查看孩子课时消耗/充值，FR-CL-01 辅助）。"""
    student = _get_student_or_404(db, student_id)
    _ensure_visible_student(db, student, user)
    from app.crud import lesson as lesson_crud

    records = lesson_crud.list_records(db, student_id, limit=limit, offset=offset)
    return [ClientLessonRecordOut.model_validate(r) for r in records]


@router.get(
    "/students/{student_id}/feedbacks", response_model=PageOut[FeedbackOut]
)
def client_feedbacks(
    student_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> PageOut[FeedbackOut]:
    """已发布课后反馈（FR-CL-02，仅 published，家长/学员可见）。"""
    student = _get_student_or_404(db, student_id)
    _ensure_visible_student(db, student, user)
    stmt = (
        select(Feedback)
        .where(
            Feedback.student_id == student_id,
            Feedback.status == FeedbackStatus.PUBLISHED.value,
        )
        .order_by(Feedback.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).unique().all())
    total = (
        db.scalar(
            select(func.count(Feedback.id)).where(
                Feedback.student_id == student_id,
                Feedback.status == FeedbackStatus.PUBLISHED.value,
            )
        )
        or 0
    )
    result = []
    for fb in items:
        out = FeedbackOut.model_validate(fb)
        if fb.schedule:
            out.schedule_time = fb.schedule.start_time
        result.append(out)
    return PageOut[FeedbackOut](items=result, total=total, limit=limit, offset=offset)


@router.get("/students/{student_id}/evaluations", response_model=PageOut[ClientEvaluationOut])
def client_evaluations(
    student_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> PageOut[ClientEvaluationOut]:
    """已发布学员评估（FR-EV-04，M6 家长会场景）：仅 published，家长/学员可见。

    返回精简视图（ClientEvaluationOut）：剔除 teacher_id/student_id/ai_draft 内部字段。
    """
    student = _get_student_or_404(db, student_id)
    _ensure_visible_student(db, student, user)
    from app.crud import evaluation as evaluation_crud

    items, total = evaluation_crud.list_evaluations(
        db,
        student_id=student_id,
        status=EvaluationStatus.PUBLISHED.value,
        limit=limit,
        offset=offset,
    )
    result = [
        ClientEvaluationOut(
            id=ev.id,
            title=ev.title,
            teacher_name=ev.teacher.name if ev.teacher else None,
            period_start=ev.period_start.isoformat(),
            period_end=ev.period_end.isoformat(),
            content=ev.content or {},
            stats=ev.stats,
            ppt_url=ev.ppt_url,
            status=ev.status,
            published_at=ev.published_at,
        )
        for ev in items
    ]
    return PageOut[ClientEvaluationOut](items=result, total=total, limit=limit, offset=offset)


@router.get("/students/{student_id}/evaluations/{evaluation_id}/pdf", include_in_schema=False)
def client_evaluation_pdf(
    student_id: uuid.UUID,
    evaluation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> Response:
    """导出已发布评估报告 PDF（家长/学员端）：仅本人可见学员的已发布评估。

    返回服务端渲染的 A4 报告单（无浏览器页眉/页脚/网址痕迹）。
    """
    from app.services import pdf_builder

    student = _get_student_or_404(db, student_id)
    _ensure_visible_student(db, student, user)
    ev = db.get(Evaluation, evaluation_id)
    if ev is None or ev.student_id != student.id or ev.status != EvaluationStatus.PUBLISHED.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评估不存在或未发布")
    try:
        pdf_bytes = pdf_builder.render_evaluation_pdf(db, ev)
    except Exception as e:  # noqa: BLE001 - 渲染异常转可读错误
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"PDF 生成失败：{e}"
        )
    filename = f"{student.name} 学习评估报告.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get(
    "/students/{student_id}/schedules", response_model=list[ClientScheduleBrief]
)
def client_schedules(
    student_id: uuid.UUID,
    start: str | None = Query(default=None, description="起始时间（ISO，可选）"),
    end: str | None = Query(default=None, description="结束时间（ISO，可选）"),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> list[ClientScheduleBrief]:
    """学员课表（上课安排，FR-CL-03 上课提醒依据；含已完成/未开始，不含已取消）。"""
    student = _get_student_or_404(db, student_id)
    _ensure_visible_student(db, student, user)
    from datetime import datetime

    class_ids = [c.id for c in student.classes]

    def _parse(s: str | None):
        try:
            return datetime.fromisoformat(s) if s else None
        except ValueError:
            return None

    from app.crud import schedule as schedule_crud

    scheds = schedule_crud.list_all(
        db,
        start=_parse(start),
        end=_parse(end),
        class_id=None,
        teacher_id=None,
        campus=None,
        limit=limit,
    )
    scheds = [s for s in scheds if s.class_id in class_ids]
    result = []
    for s in sorted(scheds, key=lambda x: x.start_time):
        result.append(
            ClientScheduleBrief(
                id=s.id,
                class_name=s.schedule_class.name if s.schedule_class else None,
                subject=s.schedule_class.subject if s.schedule_class else None,
                teacher_name=s.teacher.name if s.teacher else None,
                start_time=s.start_time,
                end_time=s.end_time,
                status=s.status,
            )
        )
    return result


# ---------- 课时包 / 订阅订单 ----------

@router.get("/packages", response_model=list[ClientPackageOut])
def client_packages(
    subject_id: uuid.UUID | None = Query(default=None, description="按学科科目筛选"),
    tag: str | None = Query(default=None, description="regular=常规课 | activity=活动课"),
    price_min: Decimal | None = Query(default=None, description="售价下限"),
    price_max: Decimal | None = Query(default=None, description="售价上限"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.PARENT)),
) -> list[ClientPackageOut]:
    """在售课时包（仅家长端可见；学员端不展示课时包模块）。"""
    from app.crud import lesson as lesson_crud

    packages = lesson_crud.list_packages(
        db,
        include_inactive=False,
        subject_id=subject_id,
        tag=tag,
        price_min=price_min,
        price_max=price_max,
        limit=500,
    )
    out = []
    for p in packages:
        if not lesson_crud.is_on_sale(p):
            continue
        item = ClientPackageOut.model_validate(p)
        item.subject_name = p.subject.name if p.subject else None
        item.paid_students = lesson_crud.package_paid_count(db, p.id)
        out.append(item)
    return out


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def client_create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> OrderOut:
    """订阅下单（FR-CL-05）：家长为孩子选课时包下单。"""
    student = _get_student_or_404(db, payload.student_id)
    _ensure_visible_student(db, student, user)
    package = db.get(LessonPackage, payload.package_id)
    if package is None or package.status != PackageStatus.ACTIVE.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="课时包不存在或已下架")
    from app.crud import lesson as lesson_crud

    if not lesson_crud.is_on_sale(package):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该活动课包不在售卖时间内")
    order = order_crud.create(db, student_id=student.id, package_id=package.id)
    out = OrderOut.model_validate(order)
    out.student_name = student.name
    out.student_campus = student.campus
    out.package_name = package.name
    return out


@router.get("/orders", response_model=PageOut[OrderOut])
def client_list_orders(
    student_id: uuid.UUID | None = Query(default=None, description="指定孩子（家长多孩时）"),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> PageOut[OrderOut]:
    """我的订单（FR-CL-08）。"""
    order_crud.expire_stale_orders(db)
    if student_id is not None:
        stu = _get_student_or_404(db, student_id)
        _ensure_visible_student(db, stu, user)
    # 家长可看多个孩子的订单；学员只看自己
    if user.role == Role.PARENT.value:
        sids = [
            sid
            for (sid,) in db.execute(
                select(Student.id).where(Student.parent_user_id == user.id)
            ).all()
        ]
    else:
        sids = [
            sid
            for (sid,) in db.execute(
                select(Student.id).where(Student.student_user_id == user.id)
            ).all()
        ]
    if student_id is not None:
        sids = [sid for sid in sids if sid == student_id]
    if not sids:
        return PageOut[OrderOut](items=[], total=0, limit=limit, offset=offset)

    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import selectinload

    from app.models.enrollment import Order as OrderModel

    base = sa_select(OrderModel).options(
        selectinload(OrderModel.student), selectinload(OrderModel.package)
    )
    q = base.where(OrderModel.student_id.in_(sids))
    if status_filter:
        q = q.where(OrderModel.status == status_filter)
    total = db.scalar(sa_select(func.count()).select_from(q.subquery())) or 0
    rows = (
        db.scalars(
            q.order_by(OrderModel.created_at.desc()).limit(limit).offset(offset)
        )
        .unique()
        .all()
    )
    items = []
    for o in rows:
        out = OrderOut.model_validate(o)
        if o.student:
            out.student_name = o.student.name
            out.student_campus = o.student.campus
        if o.package:
            out.package_name = o.package.name
        items.append(out)
    return PageOut[OrderOut](items=items, total=total, limit=limit, offset=offset)


@router.post("/orders/{order_id}/pay", response_model=OrderOut)
def client_pay_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> OrderOut:
    """模拟支付（FR-CL-06）：pending -> paid（已支付待确认到账）。"""
    order = order_crud.get(db, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    stu = _get_student_or_404(db, order.student_id)
    _ensure_visible_student(db, stu, user)
    if order.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅待支付订单可支付")
    try:
        paid = order_crud.pay(db, order)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    out = OrderOut.model_validate(paid)
    out.student_name = stu.name
    out.student_campus = stu.campus
    if paid.package:
        out.package_name = paid.package.name
    return out


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def client_cancel_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> OrderOut:
    """取消订单（parent/student 自己的未到账订单）。"""
    order = order_crud.get(db, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    stu = _get_student_or_404(db, order.student_id)
    _ensure_visible_student(db, stu, user)
    try:
        cancelled = order_crud.cancel(db, order)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    out = OrderOut.model_validate(cancelled)
    out.student_name = stu.name
    out.student_campus = stu.campus
    if cancelled.package:
        out.package_name = cancelled.package.name
    return out


class SelfRefundIn(BaseModel):
    """家长自助退款：原因复选 + 其他原因文本。"""

    reason_key: str = Field(
        description="wrong_package=买错课包 | busy=有其他安排不再续费 | other=其他原因"
    )
    reason_text: str | None = Field(default=None, max_length=256)


SELF_REFUND_REASONS = {
    "wrong_package": "买错课包了",
    "busy": "有其他安排不打算再续费",
    "other": "其他原因",
}


@router.get("/orders/{order_id}/refund-check")
def client_refund_check(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.PARENT)),
) -> dict:
    """自助退款前置检查（仅家长）：返回是否可退 + 提示文案。"""
    order = order_crud.get(db, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    stu = _get_student_or_404(db, order.student_id)
    _ensure_visible_student(db, stu, user)
    return order_crud.self_refund_check(db, student=stu, order=order)


@router.post("/orders/{order_id}/refund", response_model=OrderOut)
def client_self_refund(
    order_id: uuid.UUID,
    payload: SelfRefundIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.PARENT)),
) -> OrderOut:
    """家长自助退款（仅家长）：未消耗 + 7 天内，全额退款并扣减该单课时。

    退款记录进入订单管理（status=refunded，channel=parent_self）。
    """
    order = order_crud.get(db, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    stu = _get_student_or_404(db, order.student_id)
    _ensure_visible_student(db, stu, user)
    if payload.reason_key not in SELF_REFUND_REASONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="退款原因非法")
    reason = SELF_REFUND_REASONS[payload.reason_key]
    if payload.reason_key == "other":
        extra = (payload.reason_text or "").strip()
        if not extra:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="选择“其他原因”请填写具体原因"
            )
        reason = f"其他原因：{extra}"
    try:
        refunded, _ = order_crud.self_refund(db, student=stu, order=order, reason=reason)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    out = OrderOut.model_validate(refunded)
    out.student_name = stu.name
    out.student_campus = stu.campus
    if refunded.package:
        out.package_name = refunded.package.name
    return out


# ---------- 在线作业（FR-CL-09 ~ FR-CL-18） ----------

def _assignment_visible(db: Session, assignment_id: uuid.UUID, student_id: uuid.UUID) -> bool:
    """作业对学员可见：已发布且（发布到学员所在班级 或 定向补练给该学员）。"""
    assignment = assignment_crud.get(db, assignment_id)
    if assignment is None or assignment.status != "published":
        return False
    class_ids = set(
        db.scalars(
            select(StudentClass.class_id).where(StudentClass.student_id == student_id)
        ).all()
    )
    link_ids = {link.class_id for link in assignment.class_links}
    target_ids = {link.student_id for link in assignment.student_targets}
    if target_ids:
        return student_id in target_ids
    return bool(class_ids and link_ids & class_ids) or (assignment.class_id in class_ids)


def _is_passed(assignment: Assignment, score: int | None, status_val: str | None) -> bool | None:
    """达标判定：设置了达标线且已出分才判定，否则 None（前端不显示达标标识）。"""
    if assignment.passing_score is None or score is None:
        return None
    if status_val not in (SubmissionStatus.SUBMITTED.value, SubmissionStatus.GRADED.value):
        return None
    return score >= assignment.passing_score


def _list_item(db: Session, assignment, student_id: uuid.UUID) -> ClientAssignmentListItem:
    sub = submission_crud.get_by_student_assignment(
        db, assignment_id=assignment.id, student_id=student_id
    )
    answered = 0
    if sub and sub.answers:
        answered = sum(1 for v in (sub.answers or {}).values() if v not in (None, "", []))
    return ClientAssignmentListItem(
        id=assignment.id,
        title=assignment.title,
        mode=assignment.mode or "homework",
        description=assignment.description,
        deadline=assignment.deadline,
        teacher_name=assignment.teacher.name if assignment.teacher else None,
        class_names=assignment_crud.class_names_of(assignment),
        question_count=len(assignment.questions),
        passing_score=assignment.passing_score,
        my_status=sub.status if sub else SubmissionStatus.NOT_SUBMITTED.value,
        my_score=sub.score if sub else None,
        my_total=sub.total if sub else None,
        my_passed=_is_passed(assignment, sub.score if sub else None, sub.status if sub else None),
        submitted_at=sub.submitted_at if sub else None,
        answered_count=answered,
        published_at=assignment.published_at,
    )


@router.get("/assignments", response_model=PageOut[ClientAssignmentListItem])
def client_assignments(
    student_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> PageOut[ClientAssignmentListItem]:
    """我的作业列表（FR-CL-09）：发布给本班、未过截止时间优先展示。"""
    student = _get_student_or_404(db, student_id)
    _ensure_visible_student(db, student, user)
    assignments, total = assignment_crud.list_for_student(
        db, student_id=student_id, limit=limit, offset=offset
    )
    items = [_list_item(db, a, student_id) for a in assignments]
    return PageOut[ClientAssignmentListItem](
        items=items, total=total, limit=limit, offset=offset
    )


def _question_to_client_out(q, submitted: bool, reveal: bool = True) -> ClientQuestionOut:
    """题目转客户端输出：作答前不泄露答案；提交后返回可读的参考答案与解析。

    - reveal=False（teacher_confirm 未批改）：即使已提交也不公布答案解析
    - 选择题/判断题：答案下标转成选项文字（如 "A. printf"）或 √/×
    - 多选题：多个选项文字拼接
    - 代码填空/编程题：直接给参考代码
    - 解析为空时给一句通用鼓励语，保证家长/孩子总能看到解释
    """
    show = submitted and reveal
    ref: object | None = None
    if show:
        ans = q.answer
        if q.type in ("single_choice", "multiple_choice") and isinstance(ans, (int, list)):
            idxs = ans if isinstance(ans, list) else [ans]
            letters = []
            for i in idxs:
                if isinstance(i, int) and q.options and 0 <= i < len(q.options):
                    letters.append(f"{'ABCDEFGH'[i]}. {q.options[i]}")
                else:
                    letters.append(str(i))
            ref = letters if isinstance(ans, list) else letters[0]
        elif q.type == "judgement":
            ref = "√ 正确" if ans else "× 错误"
        else:
            ref = ans or "（老师未提供参考答案）"

    analysis = (q.analysis or "").strip() or (
        "老师稍后补充这道题的讲解，先看看自己的答案想一想哦！"
        if q.type == "programming"
        else "认真对照参考答案，看看自己哪里想得不一样吧！"
    )
    return ClientQuestionOut(
        order_no=q.order_no,
        type=q.type,
        stem=q.stem,
        options=q.options,
        difficulty=q.difficulty,
        language=q.language,
        reference_answer=ref if show else None,
        reference_analysis=analysis if show else None,
    )


@router.get("/assignments/{assignment_id}", response_model=ClientAssignmentDetail)
def client_assignment_detail(
    assignment_id: uuid.UUID,
    student_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> ClientAssignmentDetail:
    """作业详情（FR-CL-10）：作答前题目不含答案/解析（防作弊）；
    提交/批改后展示参考答案（选项转文字）与通俗解析。"""
    student = _get_student_or_404(db, student_id)
    _ensure_visible_student(db, student, user)
    if not _assignment_visible(db, assignment_id, student_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="作业不可作答")
    assignment = assignment_crud.get(db, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="作业不存在")

    sub = submission_crud.get_by_student_assignment(
        db, assignment_id=assignment.id, student_id=student_id
    )
    submitted = sub is not None and sub.status in (
        SubmissionStatus.SUBMITTED.value,
        SubmissionStatus.GRADED.value,
    )
    graded = sub is not None and sub.status == SubmissionStatus.GRADED.value
    # teacher_confirm 模式：教师批改前不公布答案解析
    reveal = graded if getattr(assignment, "review_mode", "auto") == "teacher_confirm" else True
    questions = [_question_to_client_out(q, submitted, reveal) for q in assignment.questions]
    submitted_score = sub.score if sub else None
    submission_out = ClientSubmissionOut.model_validate(sub) if sub else None
    if submission_out is not None:
        submission_out.passed = (
            assignment.passing_score is not None
            and submitted_score is not None
            and submitted_score >= assignment.passing_score
        )
        submission_out.passing_score = assignment.passing_score
    return ClientAssignmentDetail(
        id=assignment.id,
        title=assignment.title,
        mode=assignment.mode or "homework",
        description=assignment.description,
        deadline=assignment.deadline,
        published_at=assignment.published_at,
        teacher_name=assignment.teacher.name if assignment.teacher else None,
        class_names=assignment_crud.class_names_of(assignment),
        questions=questions,
        submission=submission_out,
    )


@router.post(
    "/assignments/{assignment_id}/answers",
    response_model=ClientSubmissionOut,
)
def client_save_answers(
    assignment_id: uuid.UUID,
    student_id: uuid.UUID,
    payload: ClientAnswersSave,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> ClientSubmissionOut:
    """保存答案进度（FR-CL-12 自动保存 / FR-CL-13 手动保存，断点续做）。

    请求体：{"answers": {题号: 答案}}。deadline 已过则拒绝保存（BR-06）。
    """
    from datetime import UTC, datetime

    student = _get_student_or_404(db, student_id)
    _ensure_visible_student(db, student, user)
    if not _assignment_visible(db, assignment_id, student_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="作业不可作答")
    assignment = assignment_crud.get(db, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="作业不存在")
    if assignment.deadline is not None and datetime.now(UTC) > assignment.deadline:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="作业已截止，无法保存答案"
        )

    answers = payload.answers or {}
    sub = submission_crud.get_or_create(
        db, assignment_id=assignment.id, student_id=student.id
    )
    sub = submission_crud.save_answers(db, sub, answers)
    return ClientSubmissionOut.model_validate(sub)


@router.post(
    "/assignments/{assignment_id}/submit",
    response_model=ClientSubmitOut,
)
def client_submit(
    assignment_id: uuid.UUID,
    student_id: uuid.UUID,
    payload: ClientSubmitIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CLIENT_ROLES)),
) -> ClientSubmitOut:
    """提交作业（FR-CL-15/16/17）：

    - 空题校验：存在空题则返回空题号列表（前端跳转最小题号），不落提交态
    - 全部完成：客观题自动判题 + 编程题待教师批改（OQ-03 决策）
    - deadline 校验：截止后锁定（BR-06）
    """
    student = _get_student_or_404(db, student_id)
    _ensure_visible_student(db, student, user)
    if not _assignment_visible(db, assignment_id, student_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="作业不可作答")
    assignment = assignment_crud.get(db, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="作业不存在")

    sub = submission_crud.get_or_create(
        db, assignment_id=assignment.id, student_id=student.id
    )
    try:
        submitted, empty, auto_score, pending_manual = submission_crud.submit(
            db,
            sub,
            answers=payload.answers,
            questions=assignment.questions,
            deadline=assignment.deadline,
            type_scores=assignment.type_scores,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    judged_count = len(submitted.judge_results or {})
    message = (
        f"已提交，自动判题 {judged_count} 题"
        + (f"，{pending_manual} 题待教师批改" if pending_manual else "，等待教师确认成绩")
        if not empty
        else "存在空题，请先完成全部题目"
    )
    # 学员真正提交（非空题拦截）→ 通知出题教师（教师端可直接看到谁/哪个班提交的）
    # data 携带 submission_id：教师点击通知可精确定位到该学生提交，批改后再次点击同通知不再报错
    if not empty:
        from app.services.report_feedback_notify import publish_submitted_notification

        class_names = list(
            db.scalars(
                select(Class.name)
                .join(StudentClass, StudentClass.class_id == Class.id)
                .where(StudentClass.student_id == student.id)
            ).all()
        )
        publish_submitted_notification(
            db,
            student=student,
            assignment_id=assignment.id,
            assignment_title=assignment.title,
            teacher_id=assignment.teacher_id,
            class_names=class_names,
            pending_manual=pending_manual,
            submission_id=submitted.id,
        )
    submission_out = ClientSubmissionOut.model_validate(submitted)
    submission_out.passed = (
        assignment.passing_score is not None
        and submitted.score is not None
        and submitted.score >= assignment.passing_score
    )
    submission_out.passing_score = assignment.passing_score
    return ClientSubmitOut(
        submission=submission_out,
        empty_questions=empty,
        judged_count=judged_count,
        pending_manual=pending_manual,
        message=message,
    )
