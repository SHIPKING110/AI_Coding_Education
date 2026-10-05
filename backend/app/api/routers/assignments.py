import uuid
from datetime import UTC
from datetime import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.database import get_db
from app.crud import assignment as assignment_crud
from app.crud import submission as submission_crud
from app.models.assignment import (
    Assignment,
    AssignmentClassLink,
    AssignmentFolder,
    AssignmentStatus,
    Question,
    Submission,
    SubmissionStatus,
)
from app.models.enrollment import Class, Student, StudentClass
from app.models.notification import Notification
from app.models.user import Role, User
from app.schemas.assignment import (
    AiGenerateIn,
    AiRefineIn,
    AiTaskOut,
    AssignmentCreate,
    AssignmentFolderCreate,
    AssignmentFolderMoveIn,
    AssignmentFolderOut,
    AssignmentFolderUpdate,
    AssignmentOut,
    AssignmentPublishIn,
    AssignmentUpdate,
    QuestionIn,
    QuestionOut,
    QuestionReorderIn,
    QuestionsPoolItem,
    QuestionUpdate,
)
from app.schemas.enrollment import PageOut
from app.schemas.submission import GradingCenterItem
from app.services import ai_tasks, llm

router = APIRouter(prefix="/assignments", tags=["assignments"])

# 出题/作业管理：admin/staff/teacher（教师是主要使用方）
ASSIGN_ROLES = (Role.ADMIN, Role.STAFF, Role.TEACHER)

settings = get_settings()


def _calc_total_score(assignment: Assignment) -> int:
    type_scores = assignment.type_scores or {}
    total = 0
    for q in assignment.questions:
        total += int(type_scores.get(q.type, 1) or 1)
    return total


def _pending_review_count(db: Session, assignment_id: uuid.UUID) -> int:
    """待批改份数（status=submitted），教师端列表角标用。"""
    return (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.assignment_id == assignment_id,
                Submission.status == SubmissionStatus.SUBMITTED.value,
            )
        )
        or 0
    )


def _submitted_count(db: Session, assignment_id: uuid.UUID) -> int:
    """已提交份数（submitted + graded），教师端列表聚合用。"""
    return (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.assignment_id == assignment_id,
                Submission.status.in_(
                    [SubmissionStatus.SUBMITTED.value, SubmissionStatus.GRADED.value]
                ),
            )
        )
        or 0
    )


def _to_out(db: Session, assignment: Assignment) -> AssignmentOut:
    out = AssignmentOut.model_validate(assignment)
    if assignment.teacher:
        out.teacher_name = assignment.teacher.name
    out.class_name = assignment_crud.class_name(db, assignment.class_id)
    out.question_count = len(assignment.questions)
    out.total_score = _calc_total_score(assignment)
    published = assignment_crud.published_classes(assignment)
    out.published_class_ids = [cid for cid, _name in published]
    out.published_class_names = [name for _cid, name in published]
    targets = assignment_crud.student_targets_of(assignment)
    out.target_student_ids = list(targets)
    out.target_student_names = [
        (link.student.name if link.student else "学员")
        for link in assignment.student_targets
    ]
    out.pending_review = _pending_review_count(db, assignment.id)
    out.pending_review_count = out.pending_review
    out.submitted_count = _submitted_count(db, assignment.id)
    if assignment.folder:
        out.folder_id = assignment.folder.id
        out.folder_name = assignment.folder.name
    return out


def _ensure_visible(assignment: Assignment, user: User) -> Assignment:
    """教师仅可操作自己的作业；管理员/教务可操作全部。"""
    if user.role in (Role.ADMIN.value, Role.STAFF.value):
        return assignment
    if assignment.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该作业")
    return assignment


def _get_or_404(db: Session, assignment_id: uuid.UUID) -> Assignment:
    assignment = assignment_crud.get(db, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="作业不存在")
    return assignment


# ---------- AI 出题（异步任务） ----------

def _can_view_all_tasks(user: User) -> bool:
    return user.role in (Role.ADMIN.value, Role.STAFF.value)


def _task_to_out(task: dict) -> AiTaskOut:
    return AiTaskOut(**task, model=settings.LLM_MODEL)


def _normalize_ai_questions(items: object) -> list[dict]:
    """AI 出题结果归一化：补齐可选字段默认值，保证下游统一结构。"""
    if not isinstance(items, list):
        return items  # type: ignore[return-value]
    out = []
    for q in items:
        if not isinstance(q, dict):
            out.append(q)
            continue
        q = dict(q)
        q.setdefault("options", None)
        q.setdefault("analysis", None)
        q.setdefault("test_cases", None)
        q.setdefault("language", None)
        q.setdefault("difficulty", 3)
        out.append(q)
    return out


@router.post("/ai-generate", response_model=AiTaskOut, status_code=status.HTTP_202_ACCEPTED)
def ai_generate(
    payload: AiGenerateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AiTaskOut:
    """AI 出题（FR-AI-01 / FR-AI-04），异步任务：

    - mode=similar  举一反三：基于原题生成相似练习题
    - mode=homework 作业模式：基于知识点提示语生成整套作业题目

    提交后立即返回任务（pending/running），后台线程执行；前端轮询
    `GET /assignments/ai-tasks/{id}` 获取 进度阶段/结果，期间可切换其他页面。
    未配置 LLM 时 400 降级提示。
    """
    from app.services import llm_context as _llm_ctx
    llm_resolved = _llm_ctx.require_llm(db, user_id=user.id, module="assignment")
    if payload.mode == "similar":
        if not (payload.source_question or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="举一反三模式请填写原题题干"
            )
        summary = f"举一反三 × {payload.count} 题（难度 {payload.difficulty}）"
    else:
        if not (payload.hint or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="作业模式请填写知识点提示语"
            )
        summary = f"作业模式「{(payload.hint or '').strip()[:20]}」× {payload.count} 题"
    task = ai_tasks.create_task(
        owner_id=str(user.id),
        kind="generate",
        summary=summary,
        runner=lambda: _normalize_ai_questions(_llm_ctx.run_with(llm_resolved, llm.generate_questions,
            mode=payload.mode,
            count=payload.count,
            difficulty=payload.difficulty,
            source_question=payload.source_question,
            source_answer=payload.source_answer,
            hint=payload.hint,
            types=payload.types,
        )),
    )
    return _task_to_out(task)


@router.post("/ai-refine", response_model=AiTaskOut, status_code=status.HTTP_202_ACCEPTED)
def ai_refine(
    payload: AiRefineIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AiTaskOut:
    """对话优化单题（FR-AI-05），异步任务：按教师修改要求重新生成题目。"""
    from app.services import llm_context as _llm_ctx
    llm_resolved = _llm_ctx.require_llm(db, user_id=user.id, module="assignment")
    task = ai_tasks.create_task(
        owner_id=str(user.id),
        kind="refine",
        summary=(
            "对话优化 1 题（修改要求："
            + (
                payload.instruction.strip()[:20] + "…"
                if len(payload.instruction) > 22
                else payload.instruction
            )
            + "）"
        ),
        runner=lambda: _llm_ctx.run_with(llm_resolved, llm.refine_question,
            question=payload.question.model_dump(),
            instruction=payload.instruction,
        ),
    )
    return _task_to_out(task)


@router.get("/ai-tasks", response_model=list[AiTaskOut])
def list_ai_tasks(
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AiTaskOut]:
    """最近 AI 生成任务（新在前）。

    - 教师：仅自己的任务
    - admin/staff：全部教师任务（便于教务查看/协助）
    """
    owner = None if _can_view_all_tasks(user) else str(user.id)
    tasks = [
        t for t in ai_tasks.list_tasks(owner_id=owner, limit=limit)
        if t.get("kind") in ("generate", "refine")
    ]
    return [_task_to_out(t) for t in tasks]


@router.get("/ai-tasks/{task_id}", response_model=AiTaskOut)
def get_ai_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiTaskOut:
    """轮询任务状态：pending → running → done（含 result）/ failed（含 error）/ cancelled。"""
    task = ai_tasks.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if not _can_view_all_tasks(user) and task["owner_id"] != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该任务")
    return _task_to_out(task)


@router.post("/ai-tasks/{task_id}/cancel", response_model=AiTaskOut)
def cancel_ai_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AiTaskOut:
    """取消 AI 任务（task-cancel-recover）：排队中直接取消，生成中标记后收敛。

    教师仅可取消自己的任务；admin/staff 可取消全部。已完成/失败/已取消幂等返回。
    """
    task = ai_tasks.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if not _can_view_all_tasks(user) and task["owner_id"] != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权取消该任务")
    owner_guard = None if _can_view_all_tasks(user) else str(user.id)
    cancelled = ai_tasks.cancel_task(task_id, owner_id=owner_guard)
    assert cancelled is not None
    return _task_to_out(cancelled)


# ---------- 历史题目池（复用已发布作业的题目） ----------

@router.get("/questions/pool", response_model=PageOut[QuestionsPoolItem])
def list_questions_pool(
    keyword: str | None = Query(default=None, max_length=160, description="按作业标题搜索"),
    types: str | None = Query(
        default=None,
        max_length=200,
        description=(
            "按题型筛选，多个题型用英文逗号分隔"
            "（single_choice/multiple_choice/judgement/code_fill/programming）"
        ),
    ),
    difficulty_min: int | None = Query(
        default=None, ge=0, le=10, description="难度下限 1-10（0/缺省=不限）"
    ),
    difficulty_max: int | None = Query(
        default=None, ge=0, le=10, description="难度上限 1-10（0/缺省=不限）"
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PageOut[QuestionsPoolItem]:
    """历史题目池：已发布作业中的全部题目（跨教师可见，便于复用优质题目）。

    支持按作业标题关键字 / 题型（可多选，逗号分隔）/ 难度区间筛选，分页返回。
    复用者把选中题目以 QuestionIn 形式追加到自己的作业（草稿）即可。
    """
    kw = keyword.strip() if keyword else None
    type_list = [t.strip() for t in types.split(",") if t.strip()] if types else None
    items, total = assignment_crud.list_questions_pool(
        db,
        keyword=kw,
        types=type_list,
        difficulty_min=difficulty_min or None,
        difficulty_max=difficulty_max or None,
        limit=limit,
        offset=offset,
    )
    return PageOut[QuestionsPoolItem](
        items=[QuestionsPoolItem(**item) for item in items], total=total, limit=limit, offset=offset
    )


# ---------- 作业分组 ----------


def _folder_out(folder: AssignmentFolder, count: int = 0) -> AssignmentFolderOut:
    out = AssignmentFolderOut.model_validate(folder)
    out.assignment_count = count
    return out


@router.get("/folders", response_model=list[AssignmentFolderOut])
def list_assignment_folders(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> list[AssignmentFolderOut]:
    return [_folder_out(folder, count) for folder, count in assignment_crud.list_folders(db, owner_id=user.id)]


@router.post("/folders", response_model=AssignmentFolderOut, status_code=status.HTTP_201_CREATED)
def create_assignment_folder(
    payload: AssignmentFolderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AssignmentFolderOut:
    return _folder_out(assignment_crud.create_folder(db, owner_id=user.id, name=payload.name, sort_no=payload.sort_no))


@router.patch("/folders/{folder_id}", response_model=AssignmentFolderOut)
def update_assignment_folder(
    folder_id: uuid.UUID,
    payload: AssignmentFolderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AssignmentFolderOut:
    folder = assignment_crud.get_folder(db, folder_id)
    if folder is None or folder.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分组不存在")
    return _folder_out(assignment_crud.update_folder(db, folder, name=payload.name, sort_no=payload.sort_no))


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment_folder(
    folder_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> None:
    folder = assignment_crud.get_folder(db, folder_id)
    if folder is None or folder.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分组不存在")
    assignment_crud.delete_folder(db, folder)


@router.post("/folders/ungrouped/assignments", response_model=dict)
def remove_assignments_from_assignment_folder(
    payload: AssignmentFolderMoveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> dict:
    """移出分组（静态路由必须先于 /folders/{folder_id}/assignments，避免 ungrouped 被当成 folder_id）。"""
    count = assignment_crud.move_assignments_to_folder(
        db, folder_id=None, assignment_ids=payload.assignment_ids, owner_id=user.id
    )
    return {"moved_count": count}


@router.post("/folders/{folder_id}/assignments", response_model=dict)
def move_assignments_to_assignment_folder(
    folder_id: uuid.UUID,
    payload: AssignmentFolderMoveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> dict:
    folder = assignment_crud.get_folder(db, folder_id)
    if folder is None or folder.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分组不存在")
    count = assignment_crud.move_assignments_to_folder(
        db, folder_id=folder_id, assignment_ids=payload.assignment_ids, owner_id=user.id
    )
    return {"moved_count": count}


# ---------- 批改中心（跨作业聚合，M6） ----------

def _grading_center_item(db: Session, assignment: Assignment) -> "GradingCenterItem":
    """单份作业的批改中心条目：应作答/已提交/待批改/已批改 + 最新提交时间。"""
    stats = submission_crud.submission_stats(db, assignment=assignment)
    latest = (
        db.scalar(
            select(func.max(Submission.submitted_at)).where(
                Submission.assignment_id == assignment.id,
                Submission.status != SubmissionStatus.NOT_SUBMITTED.value,
            )
        )
    )
    return GradingCenterItem(
        assignment_id=assignment.id,
        title=assignment.title,
        mode=assignment.mode or "homework",
        teacher_id=assignment.teacher_id,
        teacher_name=assignment.teacher.name if assignment.teacher else None,
        class_names=assignment_crud.class_names_of(assignment),
        deadline=assignment.deadline,
        published_at=assignment.published_at,
        total_students=stats["total_students"],
        submitted=stats["submitted"],
        pending_review=stats["pending_review"],
        graded=stats["graded"],
        latest_submitted_at=latest,
    )


@router.get("/grading-center", response_model=PageOut[GradingCenterItem])
def grading_center(
    pending_only: bool = Query(default=True, description="仅返回有待批改的作业"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> PageOut[GradingCenterItem]:
    """批改中心：教师视角跨作业聚合，按待批改数 + 最新提交时间排序。

    教师仅看自己的作业；admin/staff 可看全部。默认仅返回有待批改（pending_review>0）的作业。
    """
    can_view_all = user.role in (Role.ADMIN.value, Role.STAFF.value)
    stmt = (
        select(Assignment)
        .options(
            selectinload(Assignment.teacher),
            selectinload(Assignment.class_links).selectinload(AssignmentClassLink.cls),
        )
        .where(
            Assignment.status == AssignmentStatus.PUBLISHED.value,
            *([] if can_view_all else [Assignment.teacher_id == user.id]),
        )
    )
    items = list(db.scalars(stmt).unique().all())
    entries = [_grading_center_item(db, a) for a in items]
    if pending_only:
        entries = [e for e in entries if e.pending_review > 0]
    entries.sort(
        key=lambda e: (-e.pending_review, e.latest_submitted_at or datetime_min_utc())
    )
    total = len(entries)
    return PageOut[GradingCenterItem](
        items=entries[offset : offset + limit], total=total, limit=limit, offset=offset
    )


# ---------- 作业 CRUD ----------

@router.get("", response_model=PageOut[AssignmentOut])
def list_assignments(
    teacher_id: uuid.UUID | None = Query(default=None),
    class_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(draft|published)$"
    ),
    mode: str | None = Query(default=None, pattern="^(classwork|homework)$"),
    keyword: str | None = Query(default=None, max_length=160, description="按作业标题搜索"),
    folder_id: uuid.UUID | None = Query(default=None, description="按分组筛选"),
    ungrouped: bool = Query(default=False, description="仅看未分组作业"),
    pending_review: bool | None = Query(default=None, description="仅看有待批改的作业"),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PageOut[AssignmentOut]:
    """作业列表（分页）。教师默认只看自己的；管理员/教务可看全部。"""
    can_view_all = user.role in (Role.ADMIN.value, Role.STAFF.value)
    if teacher_id is not None and not can_view_all:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看他人作业")
    items, total = assignment_crud.list_assignments(
        db,
        teacher_id=teacher_id if can_view_all else user.id,
        class_id=class_id,
        status=status_filter,
        mode=mode,
        keyword=keyword.strip() if keyword else None,
        folder_id=folder_id,
        ungrouped=ungrouped,
        limit=limit,
        offset=offset,
    )
    outs = [_to_out(db, a) for a in items]
    if pending_review:
        outs = [o for o in outs if o.pending_review_count > 0]
        total = len(outs)
    return PageOut[AssignmentOut](items=outs, total=total, limit=limit, offset=offset)


@router.post("", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
def create_assignment(
    payload: AssignmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AssignmentOut:
    """新建作业（草稿）：标题 + 说明 + 题目列表（可选班级/截止时间）。"""
    assignment = assignment_crud.create(
        db,
        teacher_id=user.id,
        title=payload.title,
        mode=payload.mode or "homework",
        description=payload.description,
        class_id=payload.class_id,
        deadline=payload.deadline,
        type_scores=payload.type_scores,
        passing_score=payload.passing_score,
        review_mode=payload.review_mode or "auto",
        questions=[q.model_dump() for q in payload.questions],
    )
    return _to_out(db, assignment)


@router.get("/{assignment_id}", response_model=AssignmentOut)
def get_assignment(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AssignmentOut:
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    return _to_out(db, assignment)


@router.patch("/{assignment_id}", response_model=AssignmentOut)
def update_assignment(
    assignment_id: uuid.UUID,
    payload: AssignmentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AssignmentOut:
    """更新作业基本信息（草稿阶段）：标题/说明/班级/截止时间。"""
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    return _to_out(
        db,
        assignment_crud.update(
            db,
            assignment,
            title=payload.title,
            mode=payload.mode,
            description=payload.description,
            class_id=payload.class_id,
            deadline=payload.deadline,
            type_scores=payload.type_scores,
            passing_score=payload.passing_score,
        ),
    )


@router.delete("/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> None:
    """删除作业：仅草稿可删（已发布需先撤回），题目级联删除。"""
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    if assignment.status == AssignmentStatus.PUBLISHED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="已发布的作业请先撤回再删除"
        )
    assignment_crud.delete(db, assignment)


@router.post("/{assignment_id}/publish", response_model=AssignmentOut)
def publish_assignment(
    assignment_id: uuid.UUID,
    payload: AssignmentPublishIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AssignmentOut:
    """发布作业到班级（可多选，M4.1 增强）：支持同时发布到多个班级。

    - 至少包含 1 道题目才可发布
    - 已发布过的班级自动跳过；若所选班级全部已发布会返回 400 提示
    - 已发布作业再次调用 = 追加发布到新班级（已发布班级不可重复选）
    """
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    if not assignment.questions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="作业至少需要 1 道题目")
    if not payload.class_ids and not payload.target_student_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="请选择发布班级或发布学员"
        )

    # 校验班级存在（任一不存在即报错，避免产生脏发布记录）
    for cid in payload.class_ids:
        if db.get(Class, cid) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="目标班级不存在，请刷新后重试"
            )

    already = {link.class_id for link in assignment.class_links}
    new_ids = [cid for cid in payload.class_ids if cid not in already]
    # 纯班级发布时新班级不可全为已发布；定向学员发布允许无新班级（更新学员/截止时间）
    if payload.class_ids and not new_ids and not payload.target_student_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="所选班级均已发布过，请选择其他班级",
        )
    updated = assignment_crud.publish(
        db, assignment, class_ids=new_ids, deadline=payload.deadline,
        student_ids=payload.target_student_ids,
    )
    # 分值配置与达标线：发布时生效
    if payload.type_scores is not None:
        updated.type_scores = payload.type_scores
    if payload.passing_score is not None:
        updated.passing_score = payload.passing_score
    if payload.review_mode is not None:
        if payload.review_mode not in ("auto", "teacher_confirm"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="review_mode 非法"
            )
        updated.review_mode = payload.review_mode
    # 定向补练/课堂学员：仅这些学员可见（publish 已写入，targets 取最新快照）
    target_ids: list[uuid.UUID] = []
    if payload.target_student_ids is not None:
        target_ids = assignment_crud.set_student_targets(
            db, updated, payload.target_student_ids
        )

    # 通知（FR-CL-09 作业发布通知）：定向补练仅通知目标学员；常规作业通知班级学员；
    # 课堂作业默认仅通知学员账号（notify_parents=False 时跳过家长）
    from sqlalchemy import select as sa_select

    from app.models.enrollment import Student, StudentClass
    from app.services.report_feedback_notify import publish_assignment_notification

    only_student = assignment.mode == "classwork" and not payload.notify_parents
    if target_ids:
        student_ids = target_ids
    else:
        student_ids = list(
            db.scalars(
                sa_select(StudentClass.student_id).where(StudentClass.class_id.in_(new_ids))
            ).all()
        )
    for sid in student_ids:
        student = db.get(Student, sid)
        if student is not None:
            publish_assignment_notification(
                db,
                student=student,
                assignment_id=assignment.id,
                assignment_title=assignment.title,
                deadline=payload.deadline,
                only_student_account=only_student,
            )
    db.commit()
    return _to_out(db, assignment_crud.get(db, updated.id))


@router.post("/{assignment_id}/unpublish", response_model=AssignmentOut)
def unpublish_assignment(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AssignmentOut:
    """撤回作业：已发布 -> 草稿（供重新编辑/更换班级/截止时间）。"""
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    if assignment.status != AssignmentStatus.PUBLISHED.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅已发布的作业可撤回")
    return _to_out(db, assignment_crud.unpublish(db, assignment))


# ---------- 补练作业（对未达标学员定向发布） ----------

@router.post(
    "/{assignment_id}/makeup",
    response_model=AssignmentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_makeup_draft(
    assignment_id: uuid.UUID,
    student_ids: list[uuid.UUID],
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AssignmentOut:
    """为未达标学员生成补练草稿（仅对定向学员可见）。

    创建一份以原作业为蓝本的补练草稿（标题带「补练」后缀，继承班级/分值/达标线，
    并复制原作业全部题目），把指定学员设为定向可见；
    教师可在作业编辑器中继续用 AI 出题/手动改题后再发布。
    """
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    if not student_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择补练学员")
    if assignment.teacher_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="原作业无教师，无法生成补练"
        )

    copied_questions = [
        {
            "type": q.type,
            "stem": q.stem,
            "options": q.options,
            "answer": q.answer,
            "analysis": q.analysis,
            "difficulty": q.difficulty,
            "test_cases": q.test_cases,
            "language": q.language,
        }
        for q in sorted(assignment.questions, key=lambda q: q.order_no)
    ]
    draft = assignment_crud.create(
        db,
        teacher_id=assignment.teacher_id,
        title=f"{assignment.title} · 补练",
        description=assignment.description,
        class_id=assignment.class_id,
        deadline=None,
        type_scores=assignment.type_scores,
        passing_score=assignment.passing_score,
        questions=copied_questions,
    )
    assignment_crud.set_student_targets(db, draft, student_ids)
    return _to_out(db, assignment_crud.get(db, draft.id))


# ---------- 题目 CRUD ----------

@router.post("/{assignment_id}/questions", response_model=AssignmentOut)
def add_questions(
    assignment_id: uuid.UUID,
    payload: list[QuestionIn],
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AssignmentOut:
    """向作业追加题目（order_no 续排）。"""
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="题目列表不能为空")
    return _to_out(
        db, assignment_crud.add_questions(db, assignment, [q.model_dump() for q in payload])
    )


@router.patch("/{assignment_id}/questions/{question_id}", response_model=QuestionOut)
def update_question(
    assignment_id: uuid.UUID,
    question_id: uuid.UUID,
    payload: QuestionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> QuestionOut:
    """编辑单题（FR-AI-06）：实时修改题干/选项/答案/解析/难度/用例。"""
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    question = assignment_crud.get_question(db, question_id)
    if question is None or question.assignment_id != assignment.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    return QuestionOut.model_validate(
        assignment_crud.update_question(
            db,
            question,
            type=payload.type,
            stem=payload.stem,
            options=payload.options,
            answer=payload.answer,
            analysis=payload.analysis,
            difficulty=payload.difficulty,
            test_cases=payload.test_cases,
            language=payload.language,
        )
    )


@router.delete("/{assignment_id}/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(
    assignment_id: uuid.UUID,
    question_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> None:
    """删除单题（删除后其余题目自动重排序号）。"""
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    question = assignment_crud.get_question(db, question_id)
    if question is None or question.assignment_id != assignment.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    assignment_crud.delete_question(db, question)


@router.put("/{assignment_id}/questions/reorder", response_model=AssignmentOut)
def reorder_questions(
    assignment_id: uuid.UUID,
    payload: QuestionReorderIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> AssignmentOut:
    """题目排序：按前端拖拽/上下移动后的 id 顺序重排。"""
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    try:
        return _to_out(
            db, assignment_crud.reorder_questions(db, assignment, payload.question_ids)
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ---------- M5 教师批改 ----------

from app.schemas.submission import (  # noqa: E402
    SubmissionDetail,
    SubmissionGradeIn,
    SubmissionGradeResult,
    SubmissionListItem,
    SubmissionStats,
)


def datetime_min_utc():
    """排序兜底：无提交时间的作业排最后。"""
    return _dt.min.replace(tzinfo=UTC)


def _sub_stats(db: Session, assignment: Assignment) -> dict:
    return submission_crud.submission_stats(db, assignment=assignment)


def _grade_to_out(db: Session, submission) -> SubmissionDetail:
    out = SubmissionDetail.model_validate(submission)
    if submission.student:
        out.student_name = submission.student.name
    out.questions = [
        QuestionOut.model_validate(q)
        for q in db.scalars(
            select(Question).where(Question.assignment_id == submission.assignment_id)
        )
    ]
    return out


@router.get("/{assignment_id}/submission-stats", response_model=SubmissionStats)
def submission_stats(
    assignment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> SubmissionStats:
    """某作业提交统计（应作答/已提交/已批改/未提交/平均分）。"""
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    return _sub_stats(db, assignment)


@router.get("/{assignment_id}/submissions", response_model=list[SubmissionListItem])
def list_submissions(
    assignment_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> list[SubmissionListItem]:
    """该作业的提交列表（教师批改用，FR-CL-18）。"""
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    # 先确定应作答学员：定向发布取定向学员，常规发布取所有已发布班级学员去重。
    if assignment.student_targets:
        expected_ids = list(dict.fromkeys(link.student_id for link in assignment.student_targets))
    else:
        class_ids = [link.class_id for link in assignment.class_links]
        expected_ids = list(
            dict.fromkeys(
                db.scalars(
                    select(StudentClass.student_id).where(StudentClass.class_id.in_(class_ids))
                ).all()
            )
        ) if class_ids else []

    all_submissions = submission_crud.list_by_assignment(
        db, assignment_id=assignment_id, limit=500, offset=0
    )
    submission_map = {item.student_id: item for item in all_submissions}
    student_ids = list(dict.fromkeys(expected_ids + [s.student_id for s in all_submissions]))
    students = {
        student.id: student
        for student in db.scalars(select(Student).where(Student.id.in_(student_ids))).all()
    } if student_ids else {}
    class_map = submission_crud.class_names_by_student(db, student_ids)

    result: list[SubmissionListItem] = []
    for student_id in student_ids[offset : offset + limit]:
        student = students.get(student_id)
        submission = submission_map.get(student_id)
        if submission is None:
            result.append(
                SubmissionListItem(
                    id=uuid.uuid4(),
                    student_id=student_id,
                    student_name=student.name if student else "学员",
                    campus=student.campus if student else None,
                    class_names=class_map.get(student_id, []),
                    status=SubmissionStatus.NOT_SUBMITTED.value,
                    passing_score=assignment.passing_score,
                )
            )
            continue

        item = SubmissionListItem.model_validate(submission)
        item.student_name = student.name if student else "学员"
        item.campus = student.campus if student else None
        item.class_names = class_map.get(student_id, [])
        item.auto_score = sum(
            1
            for r in (submission.judge_results or {}).values()
            if isinstance(r, dict) and r.get("judged") and r.get("score") is not None
        )
        item.pending_manual = sum(
            1
            for r in (submission.judge_results or {}).values()
            if isinstance(r, dict) and not r.get("judged")
        )
        item.passing_score = assignment.passing_score
        if (
            assignment.passing_score is not None
            and submission.score is not None
            and submission.status == SubmissionStatus.GRADED.value
        ):
            item.passed = submission.score >= assignment.passing_score
        result.append(item)

    status_order = {
        SubmissionStatus.SUBMITTED.value: 0,
        SubmissionStatus.GRADED.value: 1,
        SubmissionStatus.NOT_SUBMITTED.value: 2,
    }
    return sorted(result, key=lambda item: (status_order.get(item.status, 3), item.student_name or ""))


@router.get(
    "/{assignment_id}/submissions/{submission_id}", response_model=SubmissionDetail
)
def get_submission(
    assignment_id: uuid.UUID,
    submission_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> SubmissionDetail:
    """提交详情：学员答案 + 自动判题结果 + 题目（教师批改前查看）。"""
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    submission = submission_crud.get(db, submission_id)
    if submission is None or submission.assignment_id != assignment.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交不存在")
    return _grade_to_out(db, submission)


@router.post(
    "/{assignment_id}/submissions/{submission_id}/grade",
    response_model=SubmissionGradeResult,
)
def grade_submission(
    assignment_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: SubmissionGradeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ASSIGN_ROLES)),
) -> SubmissionGradeResult:
    """教师批改打分（FR-CL-18）：对编程题（待人工批改的题）给 0/1 分 + 可选评语。

    - 批改后状态 submitted -> graded，学员端可见分数与结果
    - 客观题自动判定的分数保留
    """
    assignment = _get_or_404(db, assignment_id)
    _ensure_visible(assignment, user)
    submission = submission_crud.get(db, submission_id)
    if submission is None or submission.assignment_id != assignment.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交不存在")
    if submission.status != "submitted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="仅「已提交待批改」的作业可批改"
        )
    graded = submission_crud.grade(
        db, submission, scores=payload.scores, comment=payload.comment
    )
    # 通知学员/家长（FR-CL-18 查看批改结果）
    from app.models.enrollment import Student
    from app.models.notification import NotificationType
    from app.services.report_feedback_notify import publish_graded_notification

    student = db.get(Student, graded.student_id)
    if student is not None:
        publish_graded_notification(
            db,
            student=student,
            assignment_title=assignment.title,
            score=graded.score or 0,
            total=graded.total or 0,
            assignment_id=assignment.id,
        )
    # 同步更新提交通知状态：该学生该次提交的 submission_submitted 通知标记为 reviewed（已批改），
    # 教师再次点击同一通知时只进批改列表，不再尝试打开已批改/已消费的提交弹窗（避免「加载提交失败」）
    submission_notifications = list(
        db.scalars(
            select(Notification)
            .where(
                Notification.user_id == user.id,
                Notification.type == NotificationType.SUBMISSION_SUBMITTED.value,
            )
        )
    )
    for n in submission_notifications:
        data = dict(n.data or {})
        data_submission = data.get("submission_id")
        data_assignment = data.get("assignment_id")
        data_student = data.get("student_id")
        hit = (
            (data_submission is not None and str(data_submission) == str(submission.id))
            or (
                str(data_assignment or "") == str(assignment.id)
                and str(data_student or "") == str(submission.student_id)
            )
        )
        if hit:
            data["submission_status"] = "graded"
            data["reviewed_at"] = graded.updated_at.isoformat() if graded.updated_at else None
            n.data = data
    db.commit()
    return SubmissionGradeResult(
        submission=_grade_to_out(db, graded),
        score=graded.score or 0,
        total=graded.total or 0,
        status=graded.status,
        message="批改完成，学员端已可查看成绩",
    )
