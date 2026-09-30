import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.prompt import PromptScope, PromptTemplate


def list_visible(
    db: Session, user_id: uuid.UUID, *, is_admin: bool = False
) -> list[PromptTemplate]:
    """当前用户可见模板。

    普通用户：system + published + 本人 personal（账号隔离）；
    管理员：额外可见全部 personal（便于管理/发布优秀模板）。
    """
    conditions = [
        (PromptTemplate.scope == PromptScope.SYSTEM.value)
        | (PromptTemplate.scope == PromptScope.PUBLISHED.value)
    ]
    if is_admin:
        conditions.append(PromptTemplate.scope == PromptScope.PERSONAL.value)
    else:
        conditions.append(
            (PromptTemplate.scope == PromptScope.PERSONAL.value)
            & (PromptTemplate.owner_id == user_id)
        )
    stmt = (
        select(PromptTemplate)
        .where(or_(*conditions))
        .order_by(
            PromptTemplate.scope.desc(),
            PromptTemplate.created_at.desc(),
        )
    )
    return list(db.scalars(stmt).unique().all())


def get(db: Session, template_id: uuid.UUID) -> PromptTemplate | None:
    return db.get(PromptTemplate, template_id)


def get_default_system(db: Session) -> PromptTemplate | None:
    """系统默认模板（优先「通用鼓励型」，其次任意 system 模板）。"""
    stmt = (
        select(PromptTemplate)
        .where(PromptTemplate.scope == PromptScope.SYSTEM.value)
        .order_by(PromptTemplate.created_at.asc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def create(
    db: Session,
    *,
    name: str,
    content: str,
    scope: PromptScope,
    owner_id: uuid.UUID | None,
) -> PromptTemplate:
    t = PromptTemplate(
        name=name,
        content=content,
        scope=scope.value,
        owner_id=owner_id,
        created_by=owner_id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def update(
    db: Session, t: PromptTemplate, *, name: str | None, content: str | None
) -> PromptTemplate:
    if name is not None:
        t.name = name
    if content is not None:
        t.content = content
    db.commit()
    db.refresh(t)
    return t


def set_scope(db: Session, t: PromptTemplate, scope: PromptScope) -> PromptTemplate:
    t.scope = scope.value
    db.commit()
    db.refresh(t)
    return t


def delete(db: Session, t: PromptTemplate) -> None:
    db.delete(t)
    db.commit()
