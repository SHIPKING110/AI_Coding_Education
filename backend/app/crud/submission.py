"""作业提交 CRUD（M5）：客户端作答/保存进度/提交 + 教师端批改。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.assignment import (
    Assignment,
    Question,
    QuestionType,
    Submission,
    SubmissionStatus,
)
from app.models.enrollment import Student, StudentClass
from app.services import judge


def get(db: Session, submission_id: uuid.UUID) -> Submission | None:
    return db.get(Submission, submission_id)


def get_by_student_assignment(
    db: Session, *, assignment_id: uuid.UUID, student_id: uuid.UUID
) -> Submission | None:
    return db.scalar(
        select(Submission).where(
            Submission.assignment_id == assignment_id,
            Submission.student_id == student_id,
        )
    )


def get_or_create(
    db: Session, *, assignment_id: uuid.UUID, student_id: uuid.UUID
) -> Submission:
    """获取或创建学员对作业的提交记录（断点续做用，FR-CL-13）。"""
    sub = get_by_student_assignment(
        db, assignment_id=assignment_id, student_id=student_id
    )
    if sub is not None:
        return sub
    sub = Submission(
        assignment_id=assignment_id,
        student_id=student_id,
        answers={},
        status=SubmissionStatus.NOT_SUBMITTED.value,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def save_answers(
    db: Session, submission: Submission, answers: dict
) -> Submission:
    """保存作答进度（FR-CL-12/13：自动保存与手动保存共用）。

    提交状态保持当前（not_submitted/submitted/graded 均允许继续保存，
    修改窗口期=截止时间前均可修改并重新提交，PRD §3.14 默认策略）。
    """
    base = dict(submission.answers or {})
    for k, v in answers.items():
        base[str(k)] = v
    submission.answers = base
    db.commit()
    db.refresh(submission)
    return submission


def submit(
    db: Session,
    submission: Submission,
    answers: dict,
    questions: list[Question],
    *,
    deadline: datetime | None,
    type_scores: dict | None = None,
) -> tuple[Submission, list[int], int, int]:
    """提交作业（FR-CL-15/16/17）：

    - 空题校验：存在未作答题则返回空题号列表（前端跳转数值最小题号），不落提交态
    - 截止校验：已过 deadline 拒绝提交（BR-06，服务器时间判定）
    - 全部完成：客观题自动判题 + 编程题标记待人工批改，落提交态
    """
    now = datetime.now(UTC)
    # 截止时间以服务器为准；迟交直接抛出（由路由层拦截给出 400）
    if deadline is not None and now > deadline:
        raise ValueError("作业已截止，无法提交（未提交状态锁定）")

    submission.answers = {str(k): v for k, v in answers.items()}

    # 空题校验：题号字符串未作答（含 code_fill 空白）视为空题
    empty: list[int] = []
    order_by_no = {q.order_no: q for q in questions}
    for order_no in sorted(order_by_no):
        key = str(order_no)
        ans = submission.answers.get(key)
        qtype = order_by_no[order_no].type
        is_empty = ans is None
        if qtype == QuestionType.CODE_FILL.value and isinstance(ans, str):
            is_empty = not ans.strip()
        if qtype == QuestionType.PROGRAMMING.value and isinstance(ans, str):
            is_empty = not ans.strip()
        if isinstance(ans, (list, set)) and len(ans) == 0:
            is_empty = True
        if is_empty:
            empty.append(order_no)
    if empty:
        return submission, empty, 0, 0

    judge_results, auto_score, pending_manual, total = judge.judge_submission(
        questions,
        submission.answers or {},
        type_scores=type_scores,
    )
    submission.judge_results = judge_results
    submission.score = auto_score
    submission.total = total
    # 提交后统一 submitted（即使全客观题自动判完，也由教师确认批改后置 graded，FR-CL-18）
    submission.status = SubmissionStatus.SUBMITTED.value
    submission.submitted_at = now
    db.commit()
    db.refresh(submission)
    return submission, [], auto_score, pending_manual


def grade(
    db: Session,
    submission: Submission,
    *,
    scores: dict[str, int],
    comment: str | None,
) -> Submission:
    """教师批改（FR-CL-18）：对编程题（待人工批改的题）给定 0/1 分。

    - 更新 judge_results 中对应题的 score/correct/judged=True + comment
    - 重新累计 score（客观题得分 + 人工评分）
    - 状态：submitted -> graded
    """
    base_results = dict(submission.judge_results or {})
    total_score = 0
    total = 0
    for key, result in base_results.items():
        if key.startswith("_"):
            continue
        max_score = int(result.get("max_score") or 1)
        total += max_score
        # 客观题已自动判：得分保留
        if result.get("judged") and result.get("score") is not None:
            total_score += int(result["score"])
        elif key in scores:
            # 人工给分（编程题）：0/1 或按题型分值结算
            manual = max_score if scores.get(key) else 0
            result["score"] = manual
            result["correct"] = bool(manual)
            result["judged"] = True
            total_score += manual
    if comment:
        base_results["_comment"] = comment
    submission.judge_results = base_results
    submission.score = total_score
    submission.total = total or submission.total
    submission.status = SubmissionStatus.GRADED.value
    db.commit()
    db.refresh(submission)
    return submission


def list_by_assignment(
    db: Session, *, assignment_id: uuid.UUID, limit: int = 100, offset: int = 0
) -> list[Submission]:
    """某作业的全部提交（按学员名排序，教师批改用）。"""
    stmt = (
        select(Submission)
        .options(selectinload(Submission.student))
        .join(Student, Submission.student_id == Student.id)
        .where(Submission.assignment_id == assignment_id)
        .order_by(Student.name, Submission.created_at)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).unique().all())


def class_names_by_student(
    db: Session, student_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """批量查询学员所在班级名（教师批改列表展示「哪个班提交的」，一次查询避免 N+1）。"""
    if not student_ids:
        return {}
    from app.models.enrollment import Class

    rows = db.execute(
        select(StudentClass.student_id, Class.name)
        .join(Class, Class.id == StudentClass.class_id)
        .where(StudentClass.student_id.in_(student_ids))
    ).all()
    result: dict[uuid.UUID, list[str]] = {}
    for sid, name in rows:
        result.setdefault(sid, []).append(name)
    return result


def count_by_assignment(db: Session, *, assignment_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count(Submission.id)).where(
                Submission.assignment_id == assignment_id
            )
        )
        or 0
    )


def submission_stats(
    db: Session,
    *,
    assignment: Assignment,
) -> dict:
    """某作业的提交统计：应作答学员/已提交/已批改/待批改/未提交/平均分。

    应作答口径：
    - 定向作业（student_targets 非空：课堂按学员发布/补练）：定向学员数
    - 常规班级作业：已发布班级学员去重数
    待批改（pending_review）：已提交但未批改（submitted 状态）的提交数，教师端角标用。
    """
    targets = [link.student_id for link in assignment.student_targets]
    if targets:
        total_students = len({t for t in targets})
    else:
        class_ids = [link.class_id for link in assignment.class_links]
        student_stmt = (
            select(func.count(func.distinct(StudentClass.student_id)))
            .where(StudentClass.class_id.in_(class_ids))
            if class_ids
            else select(func.count()).where(False)  # 无发布班级：0 名应作答学员
        )
        total_students = db.scalar(student_stmt) or 0

    subs = list(
        db.scalars(
            select(Submission).where(Submission.assignment_id == assignment.id)
        ).all()
    )
    submitted = sum(1 for s in subs if s.status != SubmissionStatus.NOT_SUBMITTED.value)
    graded = sum(1 for s in subs if s.status == SubmissionStatus.GRADED.value)
    pending_review = sum(1 for s in subs if s.status == SubmissionStatus.SUBMITTED.value)
    scores = [
        s.score
        for s in subs
        if s.status == SubmissionStatus.GRADED.value and s.score is not None
    ]
    avg = round(sum(scores) / len(scores), 2) if scores else None
    passing_score = assignment.passing_score
    below_pass = 0
    if passing_score is not None:
        below_pass = sum(
            1
            for s in subs
            if s.status == SubmissionStatus.GRADED.value
            and s.score is not None
            and s.score < passing_score
        )
    return {
        "total_students": total_students,
        "submitted": submitted,
        "graded": graded,
        "pending_review": pending_review,
        "not_submitted": total_students - submitted,
        "avg_score": avg,
        "passing_score": passing_score,
        "below_pass": below_pass,
    }


def answered_count(db: Session, submission: Submission) -> int:
    """已作答题数（前端进度条）。"""
    if not submission.answers:
        return 0
    return len(
        [1 for k, v in (submission.answers or {}).items() if v is not None and v != ""]
    )
