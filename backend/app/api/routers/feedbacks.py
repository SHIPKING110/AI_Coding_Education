import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.database import get_db
from app.crud import attendance as attendance_crud
from app.crud import feedback as feedback_crud
from app.crud import prompt as prompt_crud
from app.crud import schedule as schedule_crud
from app.models.enrollment import Student
from app.models.feedback import Feedback, FeedbackStatus
from app.models.prompt import PromptScope
from app.models.schedule import AttendanceStatus
from app.models.user import Role, User
from app.schemas.enrollment import PageOut
from app.schemas.feedback import (
    CompletedScheduleOut,
    FeedbackAIEnhanceIn,
    FeedbackCreate,
    FeedbackDraftOut,
    FeedbackEditorRow,
    FeedbackOut,
    FeedbackStats,
    FeedbackUpdate,
    UploadOut,
)
from app.services import llm

router = APIRouter(prefix="/feedbacks", tags=["feedbacks"])

# 反馈管理：admin/staff/teacher（教师发送给家长，教务/管理员可查）
FEEDBACK_ROLES = (Role.ADMIN, Role.STAFF, Role.TEACHER)

settings = get_settings()


def _to_out(fb: Feedback) -> FeedbackOut:
    out = FeedbackOut.model_validate(fb)
    if fb.student:
        out.student_name = fb.student.name
        out.class_name = ", ".join(c.name for c in fb.student.classes)
    if fb.schedule:
        out.schedule_time = fb.schedule.start_time
    return out


@router.get("", response_model=PageOut[FeedbackOut])
def list_feedbacks(
    student_id: uuid.UUID | None = Query(default=None),
    schedule_id: uuid.UUID | None = Query(default=None),
    keyword: str | None = Query(default=None, description="搜索标题/课题/内容"),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PageOut[FeedbackOut]:
    """历史反馈查询（FR-FB-06）：按学员 / 排课 / 关键词过滤。"""
    items = feedback_crud.list_history(
        db,
        student_id=student_id,
        schedule_id=schedule_id,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    total = len(feedback_crud.list_history(db, student_id=student_id, schedule_id=schedule_id))
    return PageOut[FeedbackOut](
        items=[_to_out(f) for f in items], total=total, limit=limit, offset=offset
    )


@router.get("/schedule/{schedule_id}", response_model=list[FeedbackOut])
def list_feedback_by_schedule(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[FeedbackOut]:
    """某次排课（班级学员）的反馈列表，前端按排课填写反馈使用。"""
    items = feedback_crud.list_by_schedule(db, schedule_id)
    return [_to_out(f) for f in items]


@router.get("/stats", response_model=FeedbackStats)
def feedback_stats(
    campus: str | None = Query(default=None, description="按教师所属校区过滤"),
    teacher_id: uuid.UUID | None = Query(default=None),
    class_id: uuid.UUID | None = Query(default=None),
    start: datetime | None = Query(default=None, description="日期区间起（按排课开始时间）"),
    end: datetime | None = Query(default=None, description="日期区间止"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FeedbackStats:
    """待反馈/已反馈/应到/签到/请假统计（FR 反馈统计，M3 增强）。"""
    return FeedbackStats(
        **feedback_crud.compute_stats(
            db,
            campus=campus,
            teacher_id=teacher_id,
            class_id=class_id,
            start=start,
            end=end,
        )
    )


@router.get("/completed-schedules", response_model=list[CompletedScheduleOut])
def completed_feedback_schedules(
    campus: str | None = Query(default=None, description="按教师所属校区过滤"),
    teacher_id: uuid.UUID | None = Query(default=None),
    class_id: uuid.UUID | None = Query(default=None),
    start: datetime | None = Query(default=None, description="日期区间起"),
    end: datetime | None = Query(default=None, description="日期区间止"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[CompletedScheduleOut]:
    """已完成排课列表 + 反馈状态（M3 增强：只有已上完的课进入反馈模块）。"""
    return [
        CompletedScheduleOut(**item)
        for item in feedback_crud.completed_schedules_with_status(
            db,
            campus=campus,
            teacher_id=teacher_id,
            class_id=class_id,
            start=start,
            end=end,
        )
    ]


@router.get("/schedule/{schedule_id}/editor", response_model=list[FeedbackEditorRow])
def feedback_editor_rows(
    schedule_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[FeedbackEditorRow]:
    """反馈编辑器行：该排课班级的全部学员 + 各自考勤状态 + 已有反馈。

    请假(leave)学员不需要反馈（前端置灰/变色）；签到(attended)学员展示反馈编辑区。
    同一班级同一天的多节课共用一次反馈：考勤/已有反馈按同组排课合并匹配
    （组内任一节签到即需反馈，任一节已发即算完成；新建落到组内最早一节）。
    """
    s = schedule_crud.get(db, schedule_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="排课不存在")

    students = attendance_crud.all_students_for_schedule(db, s)
    group_ids = feedback_crud.group_schedule_ids(db, s)
    attend_rows = attendance_crud.list_for_schedules(db, group_ids)
    attend_map: dict[uuid.UUID, str] = {}
    for a in attend_rows:
        # 组内任一节签到即视为签到；否则保留请假/未标记
        if a.status == "attended":
            attend_map[a.student_id] = a.status
        else:
            attend_map.setdefault(a.student_id, a.status)
    feedback_map: dict[uuid.UUID, Feedback] = {}
    for f in feedback_crud.list_by_schedules(db, group_ids):
        cur = feedback_map.get(f.student_id)
        if cur is None or (cur.status != "published" and f.status == "published"):
            feedback_map[f.student_id] = f

    rows: list[FeedbackEditorRow] = []
    for stu in students:
        status_val = attend_map.get(stu.id, AttendanceStatus.UNMARKED.value)
        fb = feedback_map.get(stu.id)
        rows.append(
            FeedbackEditorRow(
                student_id=stu.id,
                student_name=stu.name,
                attendance_status=status_val,
                feedback=_to_out(fb) if fb else None,
            )
        )
    return rows


@router.post("", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*FEEDBACK_ROLES)),
) -> FeedbackOut:
    s = schedule_crud.get(db, payload.schedule_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="排课不存在")
    student = db.get(Student, payload.student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="学员不存在")

    # 幂等：一次排课对一名学员仅一条反馈，重复创建则更新
    existed = next(
        (
            f
            for f in feedback_crud.list_by_schedule(db, payload.schedule_id)
            if f.student_id == payload.student_id
        ),
        None,
    )
    if existed:
        return _to_out(
            feedback_crud.update(
                db,
                existed,
                title=payload.title,
                topic=payload.topic,
                content=payload.content,
                performance=payload.performance,
                evaluation=payload.evaluation,
                homework=payload.homework,
                media_urls=payload.media_urls,
            )
        )
    return _to_out(
        feedback_crud.create(
            db,
            schedule_id=payload.schedule_id,
            student_id=payload.student_id,
            title=payload.title,
            topic=payload.topic,
            content=payload.content,
            performance=payload.performance,
            evaluation=payload.evaluation,
            homework=payload.homework,
            media_urls=payload.media_urls,
        )
    )


@router.patch("/{feedback_id}", response_model=FeedbackOut)
def update_feedback(
    feedback_id: uuid.UUID,
    payload: FeedbackUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*FEEDBACK_ROLES)),
) -> FeedbackOut:
    fb = feedback_crud.get(db, feedback_id)
    if fb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈不存在")
    return _to_out(
        feedback_crud.update(
            db,
            fb,
            title=payload.title,
            topic=payload.topic,
            content=payload.content,
            performance=payload.performance,
            evaluation=payload.evaluation,
            homework=payload.homework,
            media_urls=payload.media_urls,
        )
    )


@router.post("/{feedback_id}/publish", response_model=FeedbackOut)
def publish_feedback(
    feedback_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*FEEDBACK_ROLES)),
) -> FeedbackOut:
    """发布（发送给家长）：草稿 -> 已发布（FR-FB-05）。"""
    fb = feedback_crud.get(db, feedback_id)
    if fb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈不存在")
    if not (fb.topic or fb.performance or fb.content or fb.evaluation):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="反馈内容为空，请至少填写课题、课堂表现、课程内容或课堂评价后再发送给家长",
        )
    out_fb = feedback_crud.publish(db, fb)
    # 应用内通知家长/学员（FR-FB-05 应用内推送；微信推送 OQ-01 预留）
    from app.services.report_feedback_notify import publish_feedback_notification

    if fb.student is not None:
        publish_feedback_notification(
            db,
            student=fb.student,
            title=fb.title or fb.topic,
            extra={
                "feedback_id": str(fb.id),
                "schedule_id": str(fb.schedule_id),
            },
        )
    return _to_out(out_fb)


@router.post("/{feedback_id}/unpublish", response_model=FeedbackOut)
def unpublish_feedback(
    feedback_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*FEEDBACK_ROLES)),
) -> FeedbackOut:
    """撤回（重新编辑）：已发布 -> 草稿，清除发布时间。

    防止发错/误发：教师可撤回后修改内容，再重新发送（FR-FB-05 补充）。
    """
    fb = feedback_crud.get(db, feedback_id)
    if fb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈不存在")
    if fb.status != FeedbackStatus.PUBLISHED.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅已发送的反馈可撤回")
    return _to_out(feedback_crud.unpublish(db, fb))


@router.post("/{feedback_id}/ai-enhance", response_model=FeedbackDraftOut)
def ai_enhance_feedback(
    feedback_id: uuid.UUID,
    payload: FeedbackAIEnhanceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*FEEDBACK_ROLES)),
) -> FeedbackDraftOut:
    """AI 课堂评价（FR-FB-03）：按提示词模板生成/润色「课堂评价」。

    结合模板（template_id 指定，未传则用系统默认模板）+ 当前反馈内容生成评价正文，
    写入 ai_draft 供追溯并返回，由前端回填「课堂评价」输入框人工编辑；
    未配置 LLM 时降级：记录占位 ai_draft 并返回当前内容（不报错）。
    """
    fb = feedback_crud.get(db, feedback_id)
    if fb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈不存在")

    current = {
        "title": payload.title if payload.title is not None else fb.title,
        "topic": payload.topic if payload.topic is not None else fb.topic,
        "content": payload.content if payload.content is not None else fb.content,
        "performance": payload.performance if payload.performance is not None else fb.performance,
        "evaluation": payload.evaluation if payload.evaluation is not None else fb.evaluation,
        "homework": payload.homework if payload.homework is not None else fb.homework,
    }

    from app.services import llm_context as _llm_ctx
    fb_resolved = _llm_ctx.optional_resolved(db, user.id, "feedback")
    if fb_resolved is None:
        fb.ai_draft = {
            **current,
            "note": "未配置 LLM_API_KEY，AI 草稿暂不可用，返回当前内容占位",
        }
        db.commit()
        db.refresh(fb)
        return FeedbackDraftOut(**current)

    # 解析提示词模板：优先用户选择，其次系统默认；确保模板对当前用户可见
    template = None
    if payload.template_id is not None:
        t = prompt_crud.get(db, payload.template_id)
        if t is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提示词模板不存在")
        visible = t.scope in (PromptScope.SYSTEM.value, PromptScope.PUBLISHED.value) or (
            t.scope == PromptScope.PERSONAL.value
            and (t.owner_id == user.id or user.role == Role.ADMIN.value)
        )
        if not visible:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="无权使用该提示词模板"
            )
        template = t
    else:
        template = prompt_crud.get_default_system(db)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="没有可用的提示词模板，请先在「提示词模板」中新建",
        )

    student_name = fb.student.name if fb.student else ""
    schedule_class = fb.schedule.schedule_class if fb.schedule else None
    class_name = schedule_class.name if schedule_class else ""
    subject = schedule_class.subject if schedule_class else ""

    try:
        evaluation = _llm_ctx.run_with(fb_resolved, llm.generate_feedback_evaluation,
            template_content=template.content,
            student_name=student_name,
            class_name=class_name,
            subject=subject,
            **current,
        )
    except llm.LLMConfigError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    draft = {**current, "evaluation": evaluation}
    fb.ai_draft = {
        "evaluation": evaluation,
        "input": current,
        "template": {"id": str(template.id), "name": template.name},
        "model": settings.LLM_MODEL,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    db.commit()
    db.refresh(fb)
    return FeedbackDraftOut(**draft, model=settings.LLM_MODEL)


@router.post("/upload", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
def upload_media(
    file: UploadFile,
    _: User = Depends(require_roles(*FEEDBACK_ROLES)),
) -> UploadOut:
    """上传上课照片/视频（FR-FB-04）：本地磁盘存储。"""
    if not (file.content_type or "").startswith(("image/", "video/")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持图片或视频文件",
        )
    size_limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    suffix = Path(file.filename or "file").suffix or ""
    fname = f"{uuid.uuid4().hex}{suffix}"
    # 按日期分子目录，避免单个目录文件过多
    sub = Path("feedback")
    target_dir = Path(settings.UPLOAD_DIR) / sub
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

    url = f"/uploads/feedback/{fname}"
    return UploadOut(url=url, filename=file.filename or fname)
