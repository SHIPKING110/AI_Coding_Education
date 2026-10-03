import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_teacher_permission
from app.core.database import get_db
from app.crud import classroom as class_crud
from app.models.enrollment import Class
from app.models.user import Role, User
from app.schemas.enrollment import ClassCreate, ClassDetailOut, ClassOut, ClassUpdate, PageOut

router = APIRouter(prefix="/classes", tags=["classes"])

MANAGE_ROLES = (Role.ADMIN, Role.STAFF)


def _to_out_with_count(db: Session, cls: Class) -> ClassOut:
    out = ClassOut.model_validate(cls)
    out.teacher_name = cls.teacher.name if cls.teacher else None
    out.student_count = class_crud.student_count(db, cls.id)
    return out


@router.get("", response_model=PageOut[ClassOut])
def list_classes(
    keyword: str | None = Query(default=None, description="搜索班级名称/科目/教师"),
    teacher_id: uuid.UUID | None = Query(default=None, description="精确按带教教师过滤"),
    teacher_unassigned: bool = Query(default=False, description="只看未分配带教教师的班级"),
    campus: str | None = Query(default=None, description="按带教教师所属校区过滤"),
    campus_unassigned: bool = Query(
        default=False, description="只看未分配教师或教师未填校区的班级"
    ),
    start_date_from: date | None = Query(default=None, description="开班日期起始"),
    start_date_to: date | None = Query(default=None, description="开班日期结束"),
    subject: str | None = Query(default=None, description="按科目精确过滤"),
    limit: int = Query(default=12, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> PageOut[ClassOut]:
    classes = class_crud.list_all(
        db,
        keyword=keyword,
        teacher_id=teacher_id,
        teacher_unassigned=teacher_unassigned,
        campus=campus,
        campus_unassigned=campus_unassigned,
        start_date_from=start_date_from,
        start_date_to=start_date_to,
        subject=subject,
        limit=limit,
        offset=offset,
    )
    total = class_crud.count_all(
        db,
        keyword=keyword,
        teacher_id=teacher_id,
        teacher_unassigned=teacher_unassigned,
        campus=campus,
        campus_unassigned=campus_unassigned,
        start_date_from=start_date_from,
        start_date_to=start_date_to,
        subject=subject,
    )
    return PageOut[ClassOut](
        items=[_to_out_with_count(db, c) for c in classes], total=total, limit=limit, offset=offset
    )


@router.post("", response_model=ClassOut, status_code=status.HTTP_201_CREATED)
def create_class(
    payload: ClassCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("class_create")),
) -> ClassOut:
    # 教师新建班级只能归到自己名下（管理员/教务可指定带教教师）
    teacher_id = payload.teacher_id
    if user.role == Role.TEACHER.value:
        teacher_id = user.id
    cls = class_crud.create(
        db,
        name=payload.name,
        subject=payload.subject,
        teacher_id=teacher_id,
        start_date=payload.start_date,
    )
    return _to_out_with_count(db, cls)


@router.get("/{class_id}", response_model=ClassDetailOut)
def get_class(
    class_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_teacher_permission("class_view")),
) -> ClassDetailOut:
    cls = class_crud.get(db, class_id)
    if cls is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
    out = ClassDetailOut.model_validate(cls)
    out.teacher_name = cls.teacher.name if cls.teacher else None
    out.student_count = class_crud.student_count(db, cls.id)
    out.students = [
        {
            "id": s.id,
            "name": s.name,
            "campus": s.campus,
            "phone": s.phone,
            "lesson_balance": s.lesson_balance,
            "status": s.status,
            "follow_up_status": s.follow_up_status,
            "classes": [
                {
                    "id": c.id,
                    "name": c.name,
                    "subject": c.subject,
                    "teacher_name": c.teacher.name if c.teacher else None,
                }
                for c in s.classes
            ],
        }
        for s in cls.students
    ]
    return out


@router.patch("/{class_id}", response_model=ClassOut)
def update_class(
    class_id: uuid.UUID,
    payload: ClassUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("class_edit")),
) -> ClassOut:
    cls = class_crud.get(db, class_id)
    if cls is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
    # 教师只能编辑本人所带班级，且不能把班级转给其他教师
    if user.role == Role.TEACHER.value:
        if cls.teacher_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能编辑你自己所带的班级")
        if payload.teacher_id is not None and payload.teacher_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不能把班级转给其他教师")
    cls = class_crud.update(
        db,
        cls,
        name=payload.name,
        subject=payload.subject,
        teacher_id=payload.teacher_id,
        start_date=payload.start_date,
    )
    return _to_out_with_count(db, cls)


@router.delete("/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_class(
    class_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("class_delete")),
) -> None:
    cls = class_crud.get(db, class_id)
    if cls is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found")
    # 教师只能删除本人所带班级
    if user.role == Role.TEACHER.value and cls.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能删除你自己所带的班级")
    # 只有空班级才能删除：有在册学员时先退班/转班
    if class_crud.student_count(db, cls.id) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该班级还有在册学员，只有空班级才能删除；请先为学员退班或转班",
        )
    class_crud.archive(db, cls)
