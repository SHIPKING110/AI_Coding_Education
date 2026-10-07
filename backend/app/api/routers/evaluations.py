"""学员评估（M6，FR-EV-01~05）：评估表 CRUD / 素材预览 / AI 生成与对话优化 / 家长会 PPT。

- 教师（admin/staff/teacher）管理评估：同一学员同一周期仅一份（幂等创建=更新）
- AI 生成/优化均为异步任务（复用 ai_tasks，前端轮询），素材在提交时收集（后台线程无 DB）
- 发布（BR-05 草稿→人工审核→发布）→ 通知家长/学员账号
- 家长会 PPT（FR-EV-05）：基于评估 content+stats 一键生成，落盘 uploads/ppt/
"""

import uuid
from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel as AgentBaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.crud import evaluation as evaluation_crud
from app.models.enrollment import Class, Student, StudentStatus
from app.models.evaluation import ClassPpt, Evaluation, EvaluationStatus
from app.models.user import Role, User
from app.schemas.enrollment import PageOut
from app.schemas.evaluation import (
    ClassPptCreateIn,
    ClassPptOut,
    ClassPptUpdateIn,
    ClassRosterOut,
    ClassRosterStudentOut,
    EvaluationAiDraftIn,
    EvaluationAiRefineIn,
    EvaluationCreate,
    EvaluationMaterialOut,
    EvaluationOut,
    EvaluationPptOut,
    EvaluationStatsOut,
    EvaluationUpdate,
)
from app.services import ai_tasks, llm, pdf_builder, ppt_agent, pptx_builder
from app.services.llm import clean_listish_text
from app.services.report_feedback_notify import publish_evaluation_notification

router = APIRouter(prefix="/evaluations", tags=["evaluations"])

# 评估管理：admin/staff/teacher（教师是主要使用方）
EVALUATION_ROLES = (Role.ADMIN, Role.STAFF, Role.TEACHER)

settings = get_settings()


def _to_out(ev: Evaluation) -> EvaluationOut:
    out = EvaluationOut.model_validate(ev)
    if ev.student:
        out.student_name = ev.student.name
        out.student_campus = ev.student.campus
    if ev.teacher:
        out.teacher_name = ev.teacher.name
    return out


def _get_or_404(db: Session, evaluation_id: uuid.UUID) -> Evaluation:
    ev = evaluation_crud.get(db, evaluation_id)
    if ev is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评估不存在")
    return ev


def _ensure_visible(ev: Evaluation, user: User) -> Evaluation:
    """教师仅可操作自己的评估；管理员/教务可操作全部。"""
    if user.role in (Role.ADMIN.value, Role.STAFF.value):
        return ev
    if ev.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该评估")
    return ev


def _get_student_or_404(db: Session, student_id: uuid.UUID) -> Student:
    student = db.get(Student, student_id)
    if student is None or student.status == StudentStatus.ARCHIVED.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="学员不存在")
    return student


def _period_label(start: date | str, end: date | str) -> str:
    """周期标签：兼容 date 与 Agent 会话中的 ISO 字符串（内存会话存的是 str）。"""
    if isinstance(start, str):
        start = date.fromisoformat(start[:10])
    if isinstance(end, str):
        end = date.fromisoformat(end[:10])
    return f"{start.strftime('%Y年%m月')}~{end.strftime('%m月%d日')}"


def _agent_period(material: dict) -> tuple[date, date]:
    """从 Agent 会话素材解析周期（str ISO 或 date 均可），供落库使用。"""
    start = material.get("start")
    end = material.get("end")
    if isinstance(start, str):
        start = date.fromisoformat(start[:10])
    if isinstance(end, str):
        end = date.fromisoformat(end[:10])
    return start, end


def _material_text(student_name: str, classes: list[dict], material: dict) -> str:
    """把素材 dict 组装为 LLM 可读文本（与前端素材预览口径一致）。"""
    stats = material.get("stats") or {}
    rate = stats.get("attendance_rate") or 0
    score_rate = stats.get("homework_score_rate")
    lines = [
        f"- 学员：{student_name}",
        "- 班级："
        + (
            "、".join(
                f"{c.get('name')}（{c.get('subject')}，教师 {c.get('teacher_name') or '未指派'}）"
                for c in classes
            )
            or "（暂无班级）"
        ),
        f"- 出勤：到课 {stats.get('attended', 0)} 次，请假 {stats.get('leave', 0)} 次，"
        f"出勤率 {rate * 100:.1f}%",
        f"- 课时消耗：{stats.get('consumed_lessons', 0)} 节",
        f"- 已发布课后反馈：{stats.get('feedback_count', 0)} 篇",
        f"- 已批改作业：{stats.get('homework_count', 0)} 份"
        + (
            f"，平均得分率 {score_rate * 100:.0f}%"
            if score_rate is not None
            else ""
        ),
    ]
    feedbacks = material.get("feedbacks") or []
    if feedbacks:
        lines.append(
            "- 各次课已发布反馈摘录（日期 | 班级 | 课题 | 内容 | 课堂表现 | 课堂评价 | 作业）："
        )
        for fb in feedbacks:
            topic = fb.get("topic") or "（无）"
            content = (fb.get("content") or "（无）")[:120]
            performance = (fb.get("performance") or "（无）")[:120]
            evaluation = (fb.get("evaluation") or "（无）")[:120]
            homework = (fb.get("homework") or "（无）")[:80]
            lines.append(
                f"  · [{fb.get('date')}] {fb.get('class_name') or '未知班级'} | "
                f"课题：{topic} | 内容：{content} | 表现：{performance} | "
                f"评价：{evaluation} | 作业：{homework}"
            )
    else:
        lines.append(
            "- 提示：本周期内暂无已发布课后反馈，请仅基于统计数据分析，"
            "并建议教师先完善课后反馈。"
        )
    return "\n".join(lines)


# ---------- CRUD ----------

@router.get("", response_model=PageOut[EvaluationOut])
def list_evaluations(
    student_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status", pattern="^(draft|published)$"),
    keyword: str | None = Query(default=None, max_length=80, description="按评估标题模糊搜索"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PageOut[EvaluationOut]:
    """评估列表（分页）。教师默认只看自己的；管理员/教务可看全部。"""
    can_view_all = user.role in (Role.ADMIN.value, Role.STAFF.value)
    items, total = evaluation_crud.list_evaluations(
        db,
        teacher_id=None if can_view_all else user.id,
        student_id=student_id,
        status=status_filter,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    return PageOut[EvaluationOut](
        items=[_to_out(e) for e in items], total=total, limit=limit, offset=offset
    )


@router.post("", response_model=EvaluationOut, status_code=status.HTTP_201_CREATED)
def create_evaluation(
    payload: EvaluationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> EvaluationOut:
    """新建/幂等创建评估：同一学员同周期仅一份（重复创建 = 更新）。"""
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="周期结束不能早于开始")
    _get_student_or_404(db, payload.student_id)
    ev = evaluation_crud.upsert(
        db,
        student_id=payload.student_id,
        teacher_id=user.id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        title=payload.title,
        content=payload.content,
        stats=payload.stats,
    )
    return _to_out(ev)


@router.get("/material/preview", response_model=EvaluationMaterialOut)
def material_preview(
    student_id: uuid.UUID = Query(),
    start: date = Query(description="周期起（含）"),
    end: date = Query(description="周期止（含）"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> EvaluationMaterialOut:
    """评估素材预览（FR-EV-01）：学员班级 + 周期统计 + 已发布反馈明细（AI 依据）。"""
    student = _get_student_or_404(db, student_id)
    if end < start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="周期结束不能早于开始")
    material = evaluation_crud.collect_material(db, student=student, start=start, end=end)
    return EvaluationMaterialOut(
        student_id=student.id,
        student_name=student.name,
        classes=material["classes"],
        start=start,
        end=end,
        stats=EvaluationStatsOut(**material["stats"]),
        feedbacks=material["feedbacks"],
    )


# ---------- AI 任务（先于 /{evaluation_id} 注册，避免路径被 UUID 参数吞掉） ----------

def _can_view_all_tasks(user: User) -> bool:
    return user.role in (Role.ADMIN.value, Role.STAFF.value)


def _task_to_out(task: dict) -> dict:
    return {**task, "model": settings.LLM_MODEL}


@router.get("/ai-tasks")
def list_evaluation_ai_tasks(
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """最近 AI 评估任务（新在前）；教师仅自己的，admin/staff 全量。"""
    owner = None if _can_view_all_tasks(user) else str(user.id)
    return [
        _task_to_out(t)
        for t in ai_tasks.list_tasks(owner_id=owner, limit=limit)
        if str(t.get("kind", "")).startswith("evaluation")
        or t.get("kind") in ("class_parent_ppt", "class_parent_ppt_refine")
    ]


@router.get("/ai-tasks/{task_id}")
def get_evaluation_ai_task(
    task_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """轮询 AI 评估任务状态：pending → running → done（含 result）/ failed（含 error）/ cancelled。"""
    task = ai_tasks.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if not _can_view_all_tasks(user) and task["owner_id"] != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该任务")
    return _task_to_out(task)


@router.post("/ai-tasks/{task_id}/cancel")
def cancel_evaluation_ai_task(
    task_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """取消 AI 评估/PPT 任务（task-cancel-recover）：排队中直接取消，生成中标记后收敛。"""
    task = ai_tasks.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if not _can_view_all_tasks(user) and task["owner_id"] != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权取消该任务")
    owner_guard = None if _can_view_all_tasks(user) else str(user.id)
    cancelled = ai_tasks.cancel_task(task_id, owner_id=owner_guard)
    assert cancelled is not None
    return _task_to_out(cancelled)


# ---------- 班级家长会：名单与评估生成情况（先于 /{evaluation_id} 注册） ----------

def _get_class_or_404(db: Session, class_id: uuid.UUID) -> Class:
    cls = db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="班级不存在")
    return cls


def _ensure_class_visible(cls: Class, user: User) -> None:
    """教师仅可操作自己带教的班级；admin/staff 可操作全部。"""
    if user.role == Role.TEACHER.value and cls.teacher_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="仅可为自己带教的班级生成"
        )


@router.get("/class-roster", response_model=ClassRosterOut)
def class_evaluation_roster(
    class_id: uuid.UUID = Query(),
    period_start: date = Query(description="评估周期起（含）"),
    period_end: date = Query(description="评估周期止（含）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ClassRosterOut:
    """班级 + 周期学员名单：逐人标注评估生成情况（草稿/已发布/未生成）。"""
    if period_end < period_start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="周期结束不能早于开始")
    cls = _get_class_or_404(db, class_id)
    _ensure_class_visible(cls, user)
    roster = evaluation_crud.collect_class_roster(
        db, cls=cls, start=period_start, end=period_end
    )
    return ClassRosterOut(
        class_id=cls.id,
        class_name=roster["class_name"],
        subject=roster["subject"],
        teacher_name=roster["teacher_name"],
        period_start=period_start,
        period_end=period_end,
        total=roster["total"],
        generated=roster["generated"],
        published=roster["published"],
        students=[ClassRosterStudentOut(**s) for s in roster["students"]],
    )


@router.get("/{evaluation_id}", response_model=EvaluationOut)
def get_evaluation(
    evaluation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EvaluationOut:
    ev = _get_or_404(db, evaluation_id)
    _ensure_visible(ev, user)
    return _to_out(ev)


@router.patch("/{evaluation_id}", response_model=EvaluationOut)
def update_evaluation(
    evaluation_id: uuid.UUID,
    payload: EvaluationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> EvaluationOut:
    """编辑评估（发布后仍可编辑，重新发布即更新家长端所见）。"""
    ev = _get_or_404(db, evaluation_id)
    _ensure_visible(ev, user)
    return _to_out(
        evaluation_crud.update(
            db, ev, title=payload.title, content=payload.content, stats=payload.stats
        )
    )


@router.delete("/{evaluation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluation(
    evaluation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> None:
    """删除评估：仅草稿可删（已发布需先撤回）。"""
    ev = _get_or_404(db, evaluation_id)
    _ensure_visible(ev, user)
    if ev.status == EvaluationStatus.PUBLISHED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="已发布的评估请先撤回再删除"
        )
    evaluation_crud.delete(db, ev)


@router.post("/{evaluation_id}/publish", response_model=EvaluationOut)
def publish_evaluation(
    evaluation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> EvaluationOut:
    """发布评估（FR-EV-04）：草稿 -> 已发布，并通知家长/学员账号查看。"""
    ev = _get_or_404(db, evaluation_id)
    _ensure_visible(ev, user)
    published = evaluation_crud.publish(db, ev)
    student = db.get(Student, published.student_id)
    if student is not None:
        # 发布时刷新周期统计快照：家长端详情弹窗/评估页直接展示出勤、课时、作业数据
        published.stats = evaluation_crud.collect_period_stats(
            db, student=student, start=published.period_start, end=published.period_end
        )
        db.commit()
        db.refresh(published)
        publish_evaluation_notification(
            db,
            student=student,
            period_label=_period_label(published.period_start, published.period_end),
        )
        db.commit()
    return _to_out(published)


@router.post("/{evaluation_id}/unpublish", response_model=EvaluationOut)
def unpublish_evaluation(
    evaluation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> EvaluationOut:
    """撤回评估：已发布 -> 草稿，供重新编辑。"""
    ev = _get_or_404(db, evaluation_id)
    _ensure_visible(ev, user)
    if ev.status != EvaluationStatus.PUBLISHED.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅已发布的评估可撤回")
    return _to_out(evaluation_crud.unpublish(db, ev))


@router.get("/{evaluation_id}/pdf", include_in_schema=False)
def export_evaluation_pdf(
    evaluation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """导出评估报告 PDF（M6 后端化）：服务端渲染 A4 报告单，无浏览器页眉/页脚/网址。

    教师可导出自己的（含草稿）；admin/staff 可导出全部。
    """
    ev = _get_or_404(db, evaluation_id)
    _ensure_visible(ev, user)
    try:
        pdf_bytes = pdf_builder.render_evaluation_pdf(db, ev)
    except Exception as e:  # noqa: BLE001 - 渲染异常转可读错误
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"PDF 生成失败：{e}"
        )
    student_name = ev.student.name if ev.student else "学员"
    filename = f"{student_name} 学习评估报告.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                "attachment; "
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


# ---------- AI 生成 / 对话优化（异步任务，FR-EV-01 / FR-EV-03） ----------

@router.post("/{evaluation_id}/ai-draft", status_code=status.HTTP_202_ACCEPTED)
def ai_draft_evaluation(
    evaluation_id: uuid.UUID,
    payload: EvaluationAiDraftIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> dict:
    """AI 生成评估草稿（异步任务）：提交即返回 task，前端轮询结果后回填编辑器。

    素材（统计 + 已发布反馈）在提交时收集，后台线程仅调用 LLM（线程内无 DB）。
    """
    ev = _get_or_404(db, evaluation_id)
    _ensure_visible(ev, user)
    from app.services import llm_context as _llm_ctx
    llm_resolved = _llm_ctx.require_llm(db, user_id=user.id, module="evaluation")
    student = _get_student_or_404(db, ev.student_id)
    material = evaluation_crud.collect_material(
        db, student=student, start=ev.period_start, end=ev.period_end
    )
    text = _material_text(student.name, material.get("classes") or [], material)
    task = ai_tasks.create_task(
        owner_id=str(user.id),
        kind="evaluation_draft",
        summary=f"生成 {student.name} 的学习评估",
        runner=lambda: _llm_ctx.run_with(llm_resolved, llm.generate_evaluation,
            student_name=student.name, material=text, extra_note=payload.extra_note,
            style_guide=payload.style_guide
        ),
    )
    return _task_to_out(task)


@router.post("/{evaluation_id}/ai-refine", status_code=status.HTTP_202_ACCEPTED)
def ai_refine_evaluation(
    evaluation_id: uuid.UUID,
    payload: EvaluationAiRefineIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> dict:
    """对话式优化评估（FR-EV-03，异步任务）：按教师修改要求在现有评估基础上重写。"""
    ev = _get_or_404(db, evaluation_id)
    _ensure_visible(ev, user)
    from app.services import llm_context as _llm_ctx
    llm_resolved = _llm_ctx.require_llm(db, user_id=user.id, module="evaluation")
    if not (ev.content or {}).get("summary"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="评估内容为空，请先生成或填写综合表现",
        )
    student = _get_student_or_404(db, ev.student_id)
    current = {
        k: ev.content.get(k)
        for k in ("summary", "subjects", "progress", "to_improve", "suggestions")
    }
    instruction = payload.instruction.strip()
    task = ai_tasks.create_task(
        owner_id=str(user.id),
        kind="evaluation_refine",
        summary=f"优化 {student.name} 的评估（{instruction[:16]}…）",
        runner=lambda: _llm_ctx.run_with(llm_resolved, llm.refine_evaluation,
            student_name=student.name, current=current, instruction=instruction
        ),
    )
    return _task_to_out(task)


# ---------- 家长会 PPT（FR-EV-05） ----------

@router.post("/{evaluation_id}/ppt", response_model=EvaluationPptOut)
def generate_evaluation_ppt(
    evaluation_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> EvaluationPptOut:
    """生成家长会 PPT（单学员）：基于已保存 content+stats 构建，落盘 uploads/ppt/。"""
    ev = _get_or_404(db, evaluation_id)
    _ensure_visible(ev, user)
    if not (ev.content or {}).get("summary"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="评估内容为空，请先完善综合表现再生成 PPT",
        )
    student = db.get(Student, ev.student_id)
    student_name = student.name if student else "学员"
    class_label = "、".join(c.name for c in student.classes) if student else ""
    title = ev.title or f"{student_name} 学习评估"
    try:
        ppt_url = pptx_builder.build_parent_meeting_ppt(
            student_name=student_name,
            period_label=_period_label(ev.period_start, ev.period_end),
            class_label=class_label,
            teacher_name=ev.teacher.name if ev.teacher else "",
            created_at=datetime.now(),
            title=title,
            content=ev.content,
            stats=ev.stats,
        )
    except Exception as e:  # noqa: BLE001 - PPT 构建异常转可读错误
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"PPT 生成失败：{e}"
        )
    ev.ppt_url = ppt_url
    db.commit()
    db.refresh(ev)
    return EvaluationPptOut(ppt_url=ppt_url, title=title)


# ---------- 班级家长会 PPT（以班级为单位，结合全班学员评估生成） ----------

_CLASS_PPT_KEYS = (
    "title",
    "class_summary",
    "ability_comment",
    "highlights",
    "to_improve",
    "next_plan",
    "home_suggestions",
)


def _ability_averages(material: dict) -> list[tuple[str, float]]:
    """全班评估 subjects 按能力项求平均分（1-5，保留一位小数），降序取前 6。"""
    agg: dict[str, list[int]] = {}
    for s in material["students"]:
        for ev in s["evaluations"]:
            for sub in ev.get("subjects") or []:
                name = str(sub.get("name") or "").strip()
                if not name:
                    continue
                try:
                    level = int(sub.get("level", 3))
                except (TypeError, ValueError):
                    level = 3
                agg.setdefault(name, []).append(max(1, min(5, level)))
    pairs = [(name, round(sum(lv) / len(lv), 1)) for name, lv in agg.items()]
    pairs.sort(key=lambda x: (-x[1], x[0]))
    return pairs[:6]


def _honor_roll(material: dict) -> list[tuple[str, str]]:
    """进步之星提名：从每位学员评估的进步亮点提炼一句（隐私友好，仅家长会内部使用）。"""
    out: list[tuple[str, str]] = []
    for s in material["students"]:
        for ev in s["evaluations"]:
            progress = str(ev.get("progress") or "").strip()
            if progress:
                first = progress.split("；")[0].strip()
                out.append((s["name"], first[:30]))
                break
    return out


def _class_material_text(material: dict, averages: list[tuple[str, float]]) -> str:
    """把班级素材组装为 LLM 可读文本（班级统计 + 逐学员评估摘要 + 课堂反馈摘录）。"""
    stats = material["stats"]
    hw_line = ""
    if stats.get("avg_homework_score_rate") is not None:
        hw_line = f"，作业平均得分率 {stats['avg_homework_score_rate'] * 100:.0f}%"
    lines = [
        f"- 班级：{material['class_name']}（{material['subject']}，"
        f"教师 {material['teacher_name'] or '未指派'}）",
        f"- 周期：{material['start']} ~ {material['end']}",
        f"- 班级统计：学员 {stats['student_count']} 人（在读 {stats['active_count']} 人），"
        f"累计上课 {stats['total_lessons']} 人次·节，平均出勤率 "
        f"{stats['avg_attendance_rate'] * 100:.0f}%，已发布反馈 {stats['total_feedbacks']} 篇，"
        f"已批改作业 {stats['total_homework']} 份{hw_line}",
    ]
    if averages:
        lines.append(
            "- 能力项班级平均分（1-5）：" + "、".join(f"{n} {v}" for n, v in averages)
        )
    lines.append("- 各学员评估摘要（姓名 | 出勤 | 能力 | 总结 | 进步）：")
    for s in material["students"]:
        if not s["evaluations"]:
            lines.append(f"  · {s['name']}：本周期暂无学员评估")
            continue
        ev = s["evaluations"][0]
        st = s["stats"]
        subjects = "、".join(
            f"{x.get('name')} {x.get('level')}/5" for x in (ev.get("subjects") or [])[:4]
        )
        summary = (ev.get("summary") or "（无）")[:150]
        progress = (ev.get("progress") or "（无）")[:80]
        lines.append(
            f"  · {s['name']} | 出勤 {st.get('attendance_rate', 0) * 100:.0f}% | "
            f"能力：{subjects or '（无）'}\n"
            f"    总结：{summary}\n"
            f"    进步：{progress}"
        )
    if material.get("feedbacks"):
        lines.append("- 本周期班级课堂反馈摘录（日期 | 学员 | 课题 | 课堂评价）：")
        for fb in material["feedbacks"][:20]:
            excerpt = (fb.get("evaluation") or fb.get("performance") or "（无）")[:80]
            lines.append(
                f"  · {fb['date']} | {fb['student_name']} | {fb.get('topic') or '（无）'}"
                f" | {excerpt}"
            )
    return "\n".join(lines)


def _material_fingerprint(material: dict, averages: list) -> str:
    """班级素材指纹（regen-dedup）：全班评估内容 + 统计 + 反馈的稳定哈希。

    评估 updated_at 不参与（AI 无变化重跑会改时间但内容相同也应视为无变化）；
    content 只取正文 4 字段（summary/progress/subjects/to_improve），标题/排版字段忽略。
    """
    import hashlib
    import json

    students_fp = []
    for s in sorted(material.get("students") or [], key=lambda x: x.get("name") or ""):
        evs = []
        for ev in s.get("evaluations") or []:
            evs.append({
                "status": ev.get("status"),
                "summary": (ev.get("summary") or "").strip(),
                "progress": (ev.get("progress") or "").strip(),
                "to_improve": (ev.get("to_improve") or ""),
                "subjects": [
                    (str(x.get("name") or "").strip(), x.get("level"), (x.get("comment") or "").strip())
                    for x in (ev.get("subjects") or [])
                ],
            })
        students_fp.append({
            "name": s.get("name"),
            "stats": s.get("stats"),
            "evaluations": evs,
        })
    payload = {
        "students": students_fp,
        "stats": material.get("stats"),
        "feedbacks": material.get("feedbacks"),
        "averages": [[n, v] for n, v in (averages or [])],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _class_ppt_dedup_key(class_id: uuid.UUID, start: date, end: date) -> str:
    return f"{class_id}:{start.isoformat()}:{end.isoformat()}"


@router.post("/class-ppt", status_code=status.HTTP_202_ACCEPTED)
def create_class_ppt(
    payload: ClassPptCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> dict:
    """生成班级家长会 PPT（异步任务）：结合全班学员评估提炼班级共性内容。

    - 教师仅可为自己带教的班级生成；admin/staff 可为全部班级生成
    - 要求该班在所选周期内至少有 1 份学员评估（草稿/已发布均可；家长会前建议全部发布）
    - 内容不照搬个人评估原文：AI 结合全班评估提炼班级整体表现/亮点/下阶段安排
    - 重提炼去重（regen-dedup）：同班级同周期的并发任务仅允许一个（409 提示进行中）；
      素材无变化时直接 409 提示（需 force=true 二次确认后才重提炼，避免覆盖手工编辑）
    """
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="周期结束不能早于开始")
    cls = db.get(Class, payload.class_id)
    if cls is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="班级不存在")
    if user.role == Role.TEACHER.value and cls.teacher_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="仅可为自己带教的班级生成"
        )

    material = evaluation_crud.collect_class_material(
        db, cls=cls, start=payload.period_start, end=payload.period_end
    )
    evaluated = [s for s in material["students"] if s["evaluations"]]
    if not evaluated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该班级在所选周期内还没有学员评估，请先为学员生成评估",
        )
    averages = _ability_averages(material)
    material["averages"] = averages
    fingerprint = _material_fingerprint(material, averages)
    dedup_key = _class_ppt_dedup_key(cls.id, payload.period_start, payload.period_end)
    running = ai_tasks.find_running_by_dedup(
        owner_id=None, kind="class_parent_ppt", dedup_key=dedup_key
    )
    if running is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"该班级本周期已有生成任务在进行中（{running['stage'] or '排队中'}），请稍候再试",
        )
    existing = db.scalars(
        select(ClassPpt).where(
            ClassPpt.class_id == cls.id,
            ClassPpt.period_start == payload.period_start,
            ClassPpt.period_end == payload.period_end,
        )
    ).first()
    if existing is not None and existing.material_hash == fingerprint and not payload.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="全班学员评估与课堂数据自上次生成后无变化，无需重新提炼；如需强制重提炼请二次确认",
        )
    text = _class_material_text(material, averages)
    from app.services import llm_context as _llm_ctx
    ppt_resolved = _llm_ctx.optional_resolved(db, user.id, "evaluation")
    period_label = _period_label(payload.period_start, payload.period_end)
    class_id = cls.id
    class_name = cls.name
    subject = cls.subject
    teacher_name = material["teacher_name"] or ""
    honor_roll = _honor_roll(material)

    from app.services import llm_context as _llm_ctx
    _agent_ppt_resolved = _llm_ctx.optional_resolved(db, user.id, "evaluation")
    def _runner(report) -> dict:  # noqa: ANN001 - ai_tasks 回调，上报执行阶段
        if ppt_resolved is not None:
            report("AI 正在结合全班评估提炼汇报内容…（整体表现 / 亮点 / 下阶段安排，约 20-60 秒）")
            try:
                content = _llm_ctx.run_with(
                    ppt_resolved, llm.generate_class_meeting,
                    class_name=class_name, material=text, extra_note=payload.extra_note,
                )
            except llm.LLMConfigError:
                report("AI 调用失败，切换为模板生成…")
                content = pptx_builder.build_class_meeting_fallback(
                    class_name=class_name,
                    subject=subject,
                    class_stats=material["stats"],
                    averages=averages,
                    honor_roll=honor_roll,
                )
        else:
            report("未配置 AI，正在按模板聚合班级数据…")
            content = pptx_builder.build_class_meeting_fallback(
                class_name=class_name,
                subject=subject,
                class_stats=material["stats"],
                averages=averages,
                honor_roll=honor_roll,
            )
        report("汇报文案已就绪，正在排版生成 PPT 文件…")
        content = {k: content.get(k) for k in _CLASS_PPT_KEYS}
        title = content.get("title") or f"{class_name} 家长会"
        ppt_url = pptx_builder.build_class_meeting_ppt(
            class_name=class_name,
            subject=subject,
            period_label=period_label,
            teacher_name=teacher_name,
            created_at=datetime.now(),
            class_stats=material["stats"],
            averages=averages,
            honor_roll=honor_roll,
            content=content,
        )
        # 文案与素材快照落库：面板可预览/编辑，编辑后秒级重排版（不再调用 LLM）
        record_id = None
        with SessionLocal() as record_db:
            record = evaluation_crud.upsert_class_ppt(
                record_db,
                class_id=class_id,
                teacher_id=owner_uuid,
                period_start=payload.period_start,
                period_end=payload.period_end,
                title=title,
                content=content,
                stats=material["stats"],
                averages=averages,
                honor_roll=honor_roll,
                ppt_url=ppt_url,
                material_hash=fingerprint,
            )
            record_id = str(record.id)
        return {
            "ppt_url": ppt_url,
            "title": title,
            "record_id": record_id,
            "content": content,
            "class_id": str(class_id),
            "class_name": class_name,
            "student_count": material["stats"]["student_count"],
            "evaluated_count": len(evaluated),
            "period_start": payload.period_start.isoformat(),
            "period_end": payload.period_end.isoformat(),
        }

    owner_uuid = user.id
    task = ai_tasks.create_task(
        owner_id=str(user.id),
        kind="class_parent_ppt",
        summary=f"生成 {class_name} 家长会 PPT（{len(evaluated)} 份学员评估）",
        runner=_runner,
        dedup_key=dedup_key,
    )
    return _task_to_out(task)


def _class_ppt_record_out(record: ClassPpt) -> dict:
    """ClassPpt 记录 → 前端 latest 响应（averages/honor_roll 快照一并返回）。"""
    return {
        "source": "db",
        "record_id": str(record.id),
        "task_id": None,
        "class_id": str(record.class_id),
        "class_name": record.cls.name if record.cls else None,
        "subject": record.cls.subject if record.cls else None,
        "teacher_name": record.teacher.name if record.teacher else None,
        "period_start": record.period_start.isoformat(),
        "period_end": record.period_end.isoformat(),
        "title": record.title,
        "content": record.content or {},
        "stats": record.stats or {},
        "averages": record.averages or [],
        "honor_roll": record.honor_roll or [],
        "ppt_url": record.ppt_url,
        "material_hash": record.material_hash,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


@router.get("/class-ppt/fingerprint")
def class_ppt_fingerprint(
    class_id: uuid.UUID = Query(),
    period_start: date = Query(description="评估周期起（含）"),
    period_end: date = Query(description="评估周期止（含）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """重提炼去重预检（regen-dedup）：返回当前素材指纹与上次生成时的指纹是否一致。

    - has_record=false：该班该周期从未生成过，可直接生成
    - unchanged=true：素材无变化，直接点「AI 重新提炼」会被 409 拦截，需二次确认
    - running=true：已有同班同周期的任务在进行中，提示稍候（防重复提交）
    """
    if period_end < period_start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="周期结束不能早于开始")
    cls = db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="班级不存在")
    _ensure_class_visible(cls, user)
    material = evaluation_crud.collect_class_material(
        db, cls=cls, start=period_start, end=period_end
    )
    evaluated = [s for s in material["students"] if s["evaluations"]]
    if not evaluated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该班级在所选周期内还没有学员评估，请先为学员生成评估",
        )
    averages = _ability_averages(material)
    fingerprint = _material_fingerprint(material, averages)
    dedup_key = _class_ppt_dedup_key(cls.id, period_start, period_end)
    running = ai_tasks.find_running_by_dedup(
        owner_id=None, kind="class_parent_ppt", dedup_key=dedup_key
    )
    record = db.scalars(
        select(ClassPpt).where(
            ClassPpt.class_id == cls.id,
            ClassPpt.period_start == period_start,
            ClassPpt.period_end == period_end,
        )
    ).first()
    return {
        "has_record": record is not None,
        "record_id": str(record.id) if record is not None else None,
        "unchanged": bool(record is not None and record.material_hash == fingerprint),
        "running": running is not None,
        "running_stage": running["stage"] if running is not None else None,
        "evaluated_count": len(evaluated),
    }


@router.get("/class-ppt/latest")
def latest_class_ppt(
    class_id: uuid.UUID = Query(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """回查某班级最近一次生成的家长会 PPT。

    优先查 class_ppts 落库记录（可预览/编辑/秒级重建）；无记录时回退内存任务表
    （历史任务结果，仅可下载，不可编辑）。
    """
    record = evaluation_crud.get_latest_class_ppt(db, class_id=class_id)
    if record is not None:
        return _class_ppt_record_out(record)
    owner = None if _can_view_all_tasks(user) else str(user.id)
    for t in ai_tasks.list_tasks(owner_id=owner, limit=50):
        if t.get("kind") != "class_parent_ppt" or t.get("status") != "done":
            continue
        result = t.get("result")
        if isinstance(result, dict) and result.get("class_id") == str(class_id):
            return {"task_id": t["id"], "source": "task", **result}
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="该班级还没有生成过家长会 PPT"
    )


@router.patch("/class-ppt/{record_id}", response_model=ClassPptOut)
def update_class_ppt(
    record_id: uuid.UUID,
    payload: ClassPptUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> ClassPptOut:
    """编辑班级家长会文案并重排版：仅更新所填字段，用存量素材快照秒级重建 PPT（无 LLM）。"""
    record = db.get(ClassPpt, record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="生成记录不存在")
    cls = db.get(Class, record.class_id)
    _ensure_class_visible(cls, user)

    content = {**(record.content or {})}
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "title":
            continue
        content[key] = clean_listish_text(value) if value else value
    title = updates.get("title", record.title)
    if title is not None:
        title = title.strip()[:160] or None
    content["title"] = title

    try:
        ppt_url = pptx_builder.build_class_meeting_ppt(
            class_name=cls.name,
            subject=cls.subject,
            period_label=_period_label(record.period_start, record.period_end),
            teacher_name=record.teacher.name if record.teacher else "",
            created_at=datetime.now(),
            class_stats=record.stats or {},
            averages=[tuple(a) for a in (record.averages or [])],
            honor_roll=[tuple(h) for h in (record.honor_roll or [])],
            content=content,
        )
    except Exception as e:  # noqa: BLE001 - 排版异常转可读错误
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"PPT 生成失败：{e}"
        )
    record.title = title
    record.content = content
    record.ppt_url = ppt_url
    db.commit()
    db.refresh(record)
    return record


# ---------- 班级家长会 PPT · Agent 对话式定制（点选 ABCD + E 自定义输入） ----------


class AgentInitIn(AgentBaseModel):
    """Agent 会话初始化：班级 + 周期。"""

    class_id: uuid.UUID
    period_start: date
    period_end: date


class AgentTitlesIn(AgentBaseModel):
    """Agent 标题请求：style 为 A-D 或 custom:<自定义风格描述>。"""

    session_id: str
    style: str = "A"


class AgentOutlineIn(AgentBaseModel):
    """Agent 大纲提交：用户勾选/排序后的 outline 配置。"""

    session_id: str
    title: str = ""
    outline: list[dict]


class AgentBuildIn(AgentBaseModel):
    """Agent 构建：最终大纲 + 标题 + 焦点/建议侧重（可空）。"""

    session_id: str
    title: str
    outline: list[dict]
    focus: str | None = None
    suggestion_pref: str | None = None


@router.post("/class-ppt/agent/init")
def agent_init(
    payload: AgentInitIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> dict:
    """Agent 会话初始化：收集班级素材并返回 7 步向导的选项配置。"""
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="周期结束不能早于开始")
    cls = db.get(Class, payload.class_id)
    if cls is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="班级不存在")
    _ensure_class_visible(cls, user)
    material = evaluation_crud.collect_class_material(
        db, cls=cls, start=payload.period_start, end=payload.period_end
    )
    evaluated = [s for s in material["students"] if s["evaluations"]]
    if not evaluated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该班级在所选周期内还没有学员评估，请先为学员生成评估",
        )
    material["averages"] = _ability_averages(material)
    sid = ppt_agent.create_session(cls.id, material)
    return {
        "session_id": sid,
        "class_name": cls.name,
        "subject": cls.subject,
        "stats": material["stats"],
        "averages": material["averages"],
        "honor_roll": _honor_roll(material),
        "evaluated_count": len(evaluated),
        "style_options": ppt_agent.STYLE_OPTIONS,
        "focus_options": ppt_agent.FOCUS_OPTIONS,
        "suggestion_options": ppt_agent.SUGGESTION_OPTIONS,
        "outline_presets": ppt_agent.OUTLINE_PRESETS,
    }


@router.post("/class-ppt/agent/titles")
def agent_titles(
    payload: AgentTitlesIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> dict:
    """Agent Step2：根据风格返回 4 个标题建议；custom:xxx 直接回显自定义。"""
    sess = ppt_agent.SESSIONS.get(payload.session_id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或已过期")
    sess["style"] = payload.style
    material = sess["material"]
    text = _class_material_text(material, material.get("averages") or [])
    if payload.style.startswith("custom:"):
        return {"titles": [payload.style[7:].strip() or f"{material['class_name']} 家长会"], "is_custom": True}  # noqa: E501
    cn = material["class_name"]
    titles = [f"{cn} 阶段学习汇报", f"看见每一次进步 · {cn}", f"一起见证成长 · {cn}", f"{cn} 家长会"]
    from app.services import llm_context as _llm_ctx
    _titles_resolved = _llm_ctx.optional_resolved(db, user.id, "evaluation")
    if _titles_resolved is not None:
        try:
            titles = _llm_ctx.run_with(
                _titles_resolved, llm.generate_ppt_titles_sync,
                class_name=material["class_name"], material=text, style=payload.style,
            )
        except Exception:  # noqa: BLE001 - LLM 同步调用失败（超时/429/断网）时回退本地标题
            pass
    # 风格变标题修复（agent-theme-chat）：风格 label 绝不能成为 PPT 标题。
    # LLM 偶发把风格词原样返回（如“深色商务风格”），此处丢弃并用本地兜底。
    titles = _sanitize_agent_titles(titles, fallback_cn=cn, style=payload.style)
    return {"titles": titles, "is_custom": False}


def _sanitize_agent_titles(titles: list[str], *, fallback_cn: str, style: str) -> list[str]:
    """过滤风格词污染的标题：含风格 label 原样返回/过短/重复的全部丢弃，不足用本地兜底补齐。"""
    local = [
        f"{fallback_cn} 阶段学习汇报",
        f"看见每一次进步 · {fallback_cn}",
        f"一起见证成长 · {fallback_cn}",
        f"{fallback_cn} 家长会",
    ]
    style_labels = [o.get("label", "") for o in ppt_agent.STYLE_OPTIONS]
    style_labels += ["深色商务", "商务风", "风格", "style", "custom"]
    seen: set[str] = set()
    clean: list[str] = []
    for t in titles or []:
        s = str(t or "").strip().strip("「」\"'")
        if len(s) < 4 or len(s) > 30:
            continue
        if any(lbl and lbl in s for lbl in style_labels if lbl):
            continue
        if s.lower() == style.lower():
            continue
        if s in seen:
            continue
        seen.add(s)
        clean.append(s)
    for fb in local:
        if len(clean) >= 4:
            break
        if fb not in seen:
            seen.add(fb)
            clean.append(fb)
    return clean[:4]


@router.post("/class-ppt/agent/outline")
def agent_outline(
    payload: AgentOutlineIn,
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> dict:
    """Agent Step3：接收用户勾选/排序后的 outline，返回预览摘要（每页一句话）。"""
    sess = ppt_agent.SESSIONS.get(payload.session_id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或已过期")
    sess["outline"] = payload.outline
    if payload.title:
        sess["title"] = payload.title
    stats = sess["material"].get("stats") or {}
    preview = []
    for o in sorted(payload.outline, key=lambda x: x.get("order", 99)):
        if not o.get("enabled"):
            continue
        key = o.get("key")
        desc_map = {
            "cover": f"标题「{sess.get('title') or '未定'}」+ 班级/周期/教师",
            "data": f"在读 {stats.get('active_count', 0)}/{stats.get('student_count', 0)} 人 · 出勤率 {stats.get('avg_attendance_rate', 0) * 100:.0f}%",  # noqa: E501
            "overview": "AI 提炼的班级整体表现总结",
            "abilities": f"能力均分：{'、'.join(f'{n}{v}' for n, v in (sess['material'].get('averages') or [])[:4])}",  # noqa: E501
            "highlights": "2-4 条班级亮点（可点名表扬）",
            "honor": f"进步之星 {len(_honor_roll(sess['material']))} 位学员",
            "works": "本阶段学员代表作品展示",
            "to_improve": "共性问题与改进措施",
            "next_plan": "下阶段教学安排",
            "suggestions": "给家长的家庭配合建议",
            "ending": "结尾致谢页",
        }
        preview.append({
            "key": key,
            "title": str(o.get("title") or ""),
            "kicker": str(o.get("kicker") or ""),
            "desc": desc_map.get(key, ""),
        })
    return {"preview": preview, "total": len(preview)}


@router.post("/class-ppt/agent/build", status_code=status.HTTP_202_ACCEPTED)
def agent_build(
    payload: AgentBuildIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> dict:
    """Agent 最终构建（异步任务）：按用户定制的大纲/风格/标题/重点生成 PPT 并落库。"""
    sess = ppt_agent.SESSIONS.get(payload.session_id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或已过期")
    material = sess["material"]
    averages = material.get("averages") or _ability_averages(material)
    honor_roll = _honor_roll(material)
    period_start, period_end = _agent_period(material)
    period_label = _period_label(period_start, period_end)
    class_id = uuid.UUID(sess["class_id"])
    class_name = material["class_name"]
    subject = material["subject"]
    teacher_name = material["teacher_name"] or ""
    style = sess.get("style") or "A"
    text = _class_material_text(material, averages)
    extra_parts = []
    if payload.focus:
        extra_parts.append(f"重点突出：{payload.focus}")
    if payload.suggestion_pref:
        extra_parts.append(f"家长建议侧重：{payload.suggestion_pref}")
    enabled_keys = ",".join(o.get("key") for o in payload.outline if o.get("enabled"))
    extra_parts.append(f"PPT 大纲章节：{enabled_keys}")
    if isinstance(style, str) and style.startswith("custom:"):
        extra_parts.append(f"自定义风格要求：{style[7:]}")
    extra_note = "；".join(extra_parts) or None

    from app.services import llm_context as _llm_ctx
    _agent_ppt_resolved = _llm_ctx.optional_resolved(db, user.id, "evaluation")

    def _runner(report) -> dict:  # noqa: ANN001 - ai_tasks
        if _agent_ppt_resolved is not None:
            report("AI 正在按你的定制要求提炼班级文案…")
            try:
                content = _llm_ctx.run_with(
                    _agent_ppt_resolved, llm.generate_class_meeting,
                    class_name=class_name, material=text, extra_note=extra_note,
                )
            except llm.LLMConfigError:
                report("AI 调用失败，切换为模板生成…")
                content = pptx_builder.build_class_meeting_fallback(
                    class_name=class_name, subject=subject,
                    class_stats=material["stats"], averages=averages, honor_roll=honor_roll,
                )
        else:
            report("未配置 AI，正在按模板聚合班级数据…")
            content = pptx_builder.build_class_meeting_fallback(
                class_name=class_name, subject=subject,
                class_stats=material["stats"], averages=averages, honor_roll=honor_roll,
            )
        content = {k: content.get(k) for k in _CLASS_PPT_KEYS}
        content["title"] = payload.title or content.get("title") or f"{class_name} 家长会"
        report("汇报文案已就绪，正在按定制大纲排版…")
        ppt_url = pptx_builder.build_class_meeting_ppt_dynamic(
            class_name=class_name, subject=subject, period_label=period_label,
            teacher_name=teacher_name, created_at=datetime.now(),
            class_stats=material["stats"], averages=averages, honor_roll=honor_roll,
            content=content, outline=payload.outline, style=style,
        )
        record_id = None
        with SessionLocal() as record_db:
            record = evaluation_crud.upsert_class_ppt(
                record_db, class_id=class_id, teacher_id=user.id,
                period_start=period_start, period_end=period_end,
                title=content["title"], content=content, stats=material["stats"],
                averages=averages, honor_roll=honor_roll, ppt_url=ppt_url,
            )
            record_id = str(record.id)
        return {
            "ppt_url": ppt_url, "title": content["title"], "record_id": record_id,
            "content": content, "class_id": str(class_id), "class_name": class_name,
            "outline": payload.outline,
        }

    task = ai_tasks.create_task(
        owner_id=str(user.id), kind="class_parent_ppt",
        summary=f"Agent 定制 {class_name} 家长会 PPT", runner=_runner,
    )
    return _task_to_out(task)


@router.post("/class-ppt/agent/refine", status_code=status.HTTP_202_ACCEPTED)
def agent_refine(
    record_id: uuid.UUID = Query(...),
    instruction: str = Query(..., min_length=2, max_length=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EVALUATION_ROLES)),
) -> dict:
    """Agent 生成后对话微调：按用户指令用 LLM 重写文案并重排版（异步任务）。"""
    record = db.get(ClassPpt, record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="生成记录不存在")
    cls = db.get(Class, record.class_id)
    _ensure_class_visible(cls, user)
    from app.services import llm_context as _llm_ctx
    _refine_resolved = _llm_ctx.require_llm(db, user_id=user.id, module="evaluation")
    current = {**(record.content or {})}
    rec_id = record.id
    rec_stats = record.stats or {}
    rec_averages = [tuple(a) for a in (record.averages or [])]
    rec_honor = [tuple(h) for h in (record.honor_roll or [])]
    rec_period = _period_label(record.period_start, record.period_end)
    rec_class = cls.name
    rec_subject = cls.subject
    rec_teacher = record.teacher.name if record.teacher else ""

    def _runner(report) -> dict:  # noqa: ANN001
        report("正在按你的要求微调文案…")
        try:
            nxt = _llm_ctx.run_with(
                _refine_resolved, llm.refine_ppt_content,
                current=current, instruction=instruction,
            )
        except llm.LLMConfigError as e:
            raise RuntimeError(str(e)) from e
        report("文案已更新，正在重新排版…")
        ppt_url = pptx_builder.build_class_meeting_ppt(
            class_name=rec_class, subject=rec_subject, period_label=rec_period,
            teacher_name=rec_teacher, created_at=datetime.now(),
            class_stats=rec_stats, averages=rec_averages, honor_roll=rec_honor,
            content=nxt,
        )
        with SessionLocal() as record_db:
            rec = record_db.get(ClassPpt, rec_id)
            if rec is not None:
                rec.content = nxt
                rec.title = nxt.get("title")
                rec.ppt_url = ppt_url
                record_db.commit()
        return {"ppt_url": ppt_url, "title": nxt.get("title"), "content": nxt, "record_id": str(rec_id)}  # noqa: E501

    task = ai_tasks.create_task(
        owner_id=str(user.id), kind="class_parent_ppt_refine",
        summary=f"微调 {rec_class} 家长会 PPT（{instruction[:16]}…）", runner=_runner,
    )
    return _task_to_out(task)
