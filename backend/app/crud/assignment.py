import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.assignment import (
    Assignment,
    AssignmentClassLink,
    AssignmentFolder,
    AssignmentStatus,
    AssignmentStudentLink,
    Question,
)
from app.models.enrollment import Class, StudentClass


def get(db: Session, assignment_id: uuid.UUID) -> Assignment | None:
    """获取作业（含题目、已发布班级、定向学员与分组）。"""
    return db.scalars(
        select(Assignment)
        .options(
            selectinload(Assignment.questions),
            selectinload(Assignment.class_links).selectinload(AssignmentClassLink.cls),
            selectinload(Assignment.student_targets).selectinload(AssignmentStudentLink.student),
            selectinload(Assignment.folder),
        )
        .where(Assignment.id == assignment_id)
    ).first()


def list_assignments(
    db: Session,
    *,
    teacher_id: uuid.UUID | None = None,
    class_id: uuid.UUID | None = None,
    status: str | None = None,
    mode: str | None = None,
    keyword: str | None = None,
    folder_id: uuid.UUID | None = None,
    ungrouped: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Assignment], int]:
    """作业列表（分页）：按教师/班级/状态/模式/标题关键字/分组筛选，倒序返回（最新在前）。

    班级筛选：作业发布关联（含多班级）或主班级任一匹配即命中。
    分组筛选：folder_id 指定分组；ungrouped=True 时仅返回未分组作业。
    """
    stmt = select(Assignment)
    if teacher_id is not None:
        stmt = stmt.where(Assignment.teacher_id == teacher_id)
    if class_id is not None:
        linked_ids = select(AssignmentClassLink.assignment_id).where(
            AssignmentClassLink.class_id == class_id
        )
        stmt = stmt.where(
            or_(Assignment.class_id == class_id, Assignment.id.in_(linked_ids))
        )
    if status is not None:
        stmt = stmt.where(Assignment.status == status)
    if mode is not None:
        stmt = stmt.where(Assignment.mode == mode)
    if keyword:
        stmt = stmt.where(Assignment.title.ilike(f"%{keyword}%"))
    if ungrouped:
        stmt = stmt.where(Assignment.folder_id.is_(None))
    elif folder_id is not None:
        stmt = stmt.where(Assignment.folder_id == folder_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = (
        stmt.options(
            selectinload(Assignment.assignment_class),
            selectinload(Assignment.class_links).selectinload(AssignmentClassLink.cls),
            selectinload(Assignment.folder),
        )
        .order_by(Assignment.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.scalars(stmt).unique().all())
    return items, total


def create(
    db: Session,
    *,
    teacher_id: uuid.UUID,
    title: str,
    mode: str = "homework",
    description: str | None,
    class_id: uuid.UUID | None,
    deadline: datetime | None,
    type_scores: dict[str, int] | None,
    passing_score: int | None,
    review_mode: str = "auto",
    questions: list[dict],
) -> Assignment:
    """新建作业（草稿），题目按 order_no 顺序保存。"""
    if review_mode not in ("auto", "teacher_confirm"):
        raise ValueError("review_mode 非法")
    assignment = Assignment(
        teacher_id=teacher_id,
        title=title,
        mode=mode,
        description=description,
        class_id=class_id,
        type_scores=type_scores,
        passing_score=passing_score,
        review_mode=review_mode,
        deadline=deadline,
        status=AssignmentStatus.DRAFT.value,
    )
    db.add(assignment)
    db.flush()
    for idx, q in enumerate(questions):
        db.add(
            Question(
                assignment_id=assignment.id,
                order_no=idx + 1,
                type=q["type"],
                stem=q["stem"],
                options=q.get("options"),
                answer=q.get("answer"),
                analysis=q.get("analysis"),
                difficulty=q.get("difficulty", 1),
                test_cases=q.get("test_cases"),
                language=q.get("language"),
            )
        )
    db.commit()
    return get(db, assignment.id)


def update(
    db: Session,
    assignment: Assignment,
    *,
    title: str | None,
    mode: str | None = None,
    description: str | None,
    class_id: uuid.UUID | None,
    deadline: datetime | None,
    type_scores: dict[str, int] | None,
    passing_score: int | None,
) -> Assignment:
    """更新作业（草稿阶段）：字段仅当提供时更新（None 表示不修改，清空用显式空值）。"""
    if title is not None:
        assignment.title = title
    if mode is not None:
        if mode not in ("classwork", "homework"):
            raise ValueError("mode 非法")
        assignment.mode = mode
    if description is not None:
        assignment.description = description
    if class_id is not None:
        assignment.class_id = class_id
    if deadline is not None:
        assignment.deadline = deadline
    if type_scores is not None:
        assignment.type_scores = type_scores
    if passing_score is not None:
        assignment.passing_score = passing_score
    db.commit()
    return get(db, assignment.id)


def delete(db: Session, assignment: Assignment) -> None:
    """删除作业（仅草稿可删；已发布需先撤回）。题目级联删除。"""
    db.delete(assignment)
    db.commit()


def publish(
    db: Session,
    assignment: Assignment,
    *,
    class_ids: list[uuid.UUID],
    deadline: datetime | None,
    student_ids: list[uuid.UUID] | None = None,
) -> Assignment:
    """发布/追加发布作业到多个班级（M4.1 增强）。

    - 已存在发布记录的班级被跳过（不可重复发布）
    - 至少有一个新班级才会生效；作业状态置为 published（已发布时保持不变）
    - 主班级 class_id 指向第一个新发布班级（用于列表展示）
    - student_ids 非空时同步覆盖定向学员（课堂作业按学员发布场景）
    """
    already = {link.class_id for link in assignment.class_links}
    new_ids = [cid for cid in class_ids if cid not in already]
    for cid in new_ids:
        db.add(
            AssignmentClassLink(assignment_id=assignment.id, class_id=cid)
        )
    if new_ids:
        assignment.class_id = new_ids[0]
    if student_ids is not None:
        set_student_targets(db, assignment, student_ids)
    assignment.deadline = deadline
    if assignment.status != AssignmentStatus.PUBLISHED.value:
        assignment.status = AssignmentStatus.PUBLISHED.value
        assignment.published_at = datetime.now(UTC)
    db.commit()
    return get(db, assignment.id)


def unpublish(db: Session, assignment: Assignment) -> Assignment:
    """撤回作业：已发布 -> 草稿，清空发布班级记录与定向学员（供重新编辑/重新选班发布）。"""
    assignment.status = AssignmentStatus.DRAFT.value
    assignment.published_at = None
    for link in list(assignment.class_links):
        db.delete(link)
    for link in list(assignment.student_targets):
        db.delete(link)
    db.commit()
    return get(db, assignment.id)


def published_classes(
    assignment: Assignment,
) -> list[tuple[uuid.UUID, str]]:
    """已发布班级 [(class_id, class_name)]（按发布顺序）。"""
    return [
        (link.class_id, link.cls.name if link.cls else "（班级已删除）")
        for link in assignment.class_links
        if link.cls is not None
    ]


def add_questions(db: Session, assignment: Assignment, questions: list[dict]) -> Assignment:
    """向作业追加题目（order_no 从当前最大值续排）。"""
    base = (
        db.scalar(
            select(func.max(Question.order_no)).where(
                Question.assignment_id == assignment.id
            )
        )
        or 0
    )
    for idx, q in enumerate(questions):
        db.add(
            Question(
                assignment_id=assignment.id,
                order_no=base + idx + 1,
                type=q["type"],
                stem=q["stem"],
                options=q.get("options"),
                answer=q.get("answer"),
                analysis=q.get("analysis"),
                difficulty=q.get("difficulty", 1),
                test_cases=q.get("test_cases"),
                language=q.get("language"),
            )
        )
    db.commit()
    return get(db, assignment.id)


def list_question_bank(
    db: Session,
    *,
    teacher_ids: list[uuid.UUID] | None,
    query: str | None,
    qtype: str | None,
    difficulty: int | None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """历史题目库（M4.2 复用历史题）：教师自己的作业题目，按作业标题搜索 + 题型/难度筛选。

    返回题目 + 所属作业标题（供前端列表展示）；admin/staff 传 teacher_ids=None 看全量。
    """
    stmt = select(Question, Assignment).join(Assignment, Question.assignment_id == Assignment.id)
    if teacher_ids is not None:
        stmt = stmt.where(Assignment.teacher_id.in_(teacher_ids))
    if query and query.strip():
        stmt = stmt.where(Assignment.title.ilike(f"%{query.strip()}%"))
    if qtype is not None:
        stmt = stmt.where(Question.type == qtype)
    if difficulty is not None:
        stmt = stmt.where(Question.difficulty == difficulty)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(Question.created_at.desc()).limit(limit).offset(offset)
    ).all()
    items = [
        {
            "id": q.id,
            "assignment_id": assignment.id,
            "assignment_title": assignment.title,
            "order_no": q.order_no,
            "type": q.type,
            "stem": q.stem,
            "options": q.options,
            "answer": q.answer,
            "analysis": q.analysis,
            "difficulty": q.difficulty,
            "test_cases": q.test_cases,
            "language": q.language,
            "created_at": q.created_at,
            "updated_at": q.updated_at,
        }
        for q, assignment in rows
    ]
    return items, total


def get_question(db: Session, question_id: uuid.UUID) -> Question | None:
    return db.get(Question, question_id)


def update_question(
    db: Session,
    question: Question,
    *,
    type: str | None,
    stem: str | None,
    options: list | None,
    answer: object | None,
    analysis: str | None,
    difficulty: int | None,
    test_cases: list | None,
    language: str | None,
) -> Question:
    """编辑单题：仅更新提供的字段（None 表示不修改；显式空值清空时传空字符串/空列表）。"""
    if type is not None:
        question.type = type
    if stem is not None:
        question.stem = stem
    if options is not None:
        question.options = options
    if answer is not None:
        question.answer = answer
    if analysis is not None:
        question.analysis = analysis
    if difficulty is not None:
        question.difficulty = difficulty
    if test_cases is not None:
        question.test_cases = test_cases
    if language is not None:
        question.language = language
    db.commit()
    db.refresh(question)
    return question


def delete_question(db: Session, question: Question) -> None:
    """删除单题并重排其后题目的 order_no。"""
    assignment_id = question.assignment_id
    order = question.order_no
    db.delete(question)
    db.flush()
    later = list(
        db.scalars(
            select(Question)
            .where(Question.assignment_id == assignment_id, Question.order_no > order)
            .order_by(Question.order_no)
        )
    )
    for q in later:
        q.order_no -= 1
    db.commit()


def reorder_questions(
    db: Session, assignment: Assignment, question_ids: list[uuid.UUID]
) -> Assignment:
    """按给定 id 顺序重排题目（order_no = 下标 + 1）。"""
    by_id = {q.id: q for q in assignment.questions}
    if len(question_ids) != len(by_id) or any(qid not in by_id for qid in question_ids):
        raise ValueError("题目 id 与作业题目不匹配")
    for idx, qid in enumerate(question_ids):
        by_id[qid].order_no = idx + 1
    db.commit()
    return get(db, assignment.id)


def class_name(db: Session, class_id: uuid.UUID | None) -> str | None:
    if class_id is None:
        return None
    cls = db.get(Class, class_id)
    return cls.name if cls else None


def list_questions_pool(
    db: Session,
    *,
    keyword: str | None = None,
    types: list[str] | None = None,
    difficulty_min: int | None = None,
    difficulty_max: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """历史题目池：从已发布作业中查询题目，供教师复用。

    返回 dict 列表（含 assignment_title），前端按需展示。
    """
    stmt = (
        select(Question, Assignment.title.label("assignment_title"))
        .join(Assignment, Question.assignment_id == Assignment.id)
        .where(Assignment.status == AssignmentStatus.PUBLISHED.value)
    )
    if keyword:
        stmt = stmt.where(Assignment.title.ilike(f"%{keyword}%"))
    if types:
        stmt = stmt.where(Question.type.in_(types))
    if difficulty_min is not None:
        stmt = stmt.where(Question.difficulty >= difficulty_min)
    if difficulty_max is not None:
        stmt = stmt.where(Question.difficulty <= difficulty_max)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = (
        stmt.order_by(Assignment.created_at.desc(), Question.order_no)
        .limit(limit)
        .offset(offset)
    )
    rows = db.execute(stmt).all()
    items = []
    for q, assignment_title in rows:
        items.append({
            "id": q.id,
            "assignment_id": q.assignment_id,
            "assignment_title": assignment_title,
            "order_no": q.order_no,
            "type": q.type,
            "stem": q.stem,
            "options": q.options,
            "answer": q.answer,
            "analysis": q.analysis,
            "difficulty": q.difficulty,
            "test_cases": q.test_cases,
            "language": q.language,
            "created_at": q.created_at,
            "updated_at": q.updated_at,
        })
    return items, total


# ---------- 客户端作业（M5） ----------

def list_for_student(
    db: Session,
    *,
    student_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Assignment], int]:
    """客户端作业列表（FR-CL-09）：学员所在班级发布的作业，或补练定向作业。

    - 仅已发布（published）作业
    - 常规作业：命中任一发布班级（assignment_class_links）
    - 补练作业：命中 student_targets 中的定向学员，且对非定向学员不可见
    """
    from sqlalchemy import and_, exists

    class_ids = select(StudentClass.class_id).where(StudentClass.student_id == student_id)
    linked_ids = select(AssignmentClassLink.assignment_id).where(
        AssignmentClassLink.class_id.in_(class_ids)
    )
    is_targeted = exists().where(
        and_(
            AssignmentStudentLink.assignment_id == Assignment.id,
            AssignmentStudentLink.student_id == student_id,
        )
    )
    no_targets = ~exists().where(AssignmentStudentLink.assignment_id == Assignment.id)
    stmt = (
        select(Assignment)
        .options(
            selectinload(Assignment.teacher),
            selectinload(Assignment.class_links).selectinload(AssignmentClassLink.cls),
            selectinload(Assignment.student_targets).selectinload(AssignmentStudentLink.student),
        )
        .where(
            Assignment.status == AssignmentStatus.PUBLISHED.value,
            or_(
                is_targeted,
                and_(
                    no_targets,
                    or_(
                        Assignment.id.in_(linked_ids),
                        Assignment.class_id.in_(class_ids),
                    ),
                ),
            ),
        )
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(Assignment.published_at.desc()).limit(limit).offset(offset)
    items = list(db.scalars(stmt).unique().all())
    return items, total


def class_names_of(assignment: Assignment) -> list[str]:
    """已发布班级名列表（客户端展示）。"""
    return [link.cls.name for link in assignment.class_links if link.cls is not None]


def student_targets_of(assignment: Assignment) -> list[uuid.UUID]:
    """补练作业定向学员列表。"""
    return [link.student_id for link in assignment.student_targets]


def set_student_targets(
    db: Session, assignment: Assignment, student_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """覆盖设置补练作业的定向学员。"""
    for link in list(assignment.student_targets):
        db.delete(link)
    # 先执行删除再插入：否则同唯一键（assignment_id, student_id）的新行
    # 会先于旧行删除 flush，触发 UniqueViolation
    db.flush()
    seen: set[uuid.UUID] = set()
    for sid in student_ids:
        if sid in seen:
            continue
        seen.add(sid)
        db.add(AssignmentStudentLink(assignment_id=assignment.id, student_id=sid))
    db.commit()
    return list(seen)


# ---------- 自定义分组 ----------

def list_folders(db: Session, *, owner_id: uuid.UUID) -> list[tuple[AssignmentFolder, int]]:
    """教师的分组列表（按 sort_no/创建时间排序），附每组作业数。"""
    folders = list(
        db.scalars(
            select(AssignmentFolder)
            .where(AssignmentFolder.owner_id == owner_id)
            .order_by(AssignmentFolder.sort_no, AssignmentFolder.created_at)
        ).all()
    )
    if not folders:
        return []
    counts = dict(
        db.execute(
            select(Assignment.folder_id, func.count(Assignment.id))
            .where(Assignment.folder_id.in_([f.id for f in folders]))
            .group_by(Assignment.folder_id)
        ).all()
    )
    return [(f, int(counts.get(f.id, 0))) for f in folders]


def create_folder(
    db: Session, *, owner_id: uuid.UUID, name: str, sort_no: int = 0
) -> AssignmentFolder:
    folder = AssignmentFolder(owner_id=owner_id, name=name.strip(), sort_no=sort_no)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def get_folder(db: Session, folder_id: uuid.UUID) -> AssignmentFolder | None:
    return db.get(AssignmentFolder, folder_id)


def update_folder(
    db: Session,
    folder: AssignmentFolder,
    *,
    name: str | None = None,
    sort_no: int | None = None,
) -> AssignmentFolder:
    if name is not None and name.strip():
        folder.name = name.strip()
    if sort_no is not None:
        folder.sort_no = sort_no
    db.commit()
    db.refresh(folder)
    return folder


def delete_folder(db: Session, folder: AssignmentFolder) -> int:
    """删除分组：组内作业回到未分组（folder_id 置 NULL），返回受影响作业数。"""
    moved = (
        db.query(Assignment)
        .filter(Assignment.folder_id == folder.id)
        .update({"folder_id": None})  # type: ignore[arg-type]
    )
    db.delete(folder)
    db.commit()
    return int(moved)


def move_assignments_to_folder(
    db: Session,
    *,
    folder_id: uuid.UUID | None,
    assignment_ids: list[uuid.UUID],
    owner_id: uuid.UUID,
) -> int:
    """批量移动作业到分组（folder_id=None 表示移出分组）。校验作业归属当前教师。"""
    if not assignment_ids:
        return 0
    rows = (
        db.query(Assignment)
        .filter(
            Assignment.id.in_(assignment_ids),
            Assignment.teacher_id == owner_id,
        )
        .all()
    )
    for a in rows:
        a.folder_id = folder_id
    db.commit()
    return len(rows)
