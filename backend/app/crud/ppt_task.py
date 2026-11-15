"""PPT 任务契约数据访问。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ppt_task import AgentPptTask, AgentPptTaskEvent


def get_active(db: Session, *, conversation_id: uuid.UUID) -> AgentPptTask | None:
    return db.scalar(
        select(AgentPptTask)
        .where(
            AgentPptTask.conversation_id == conversation_id,
            AgentPptTask.status != "archived",
        )
        .order_by(AgentPptTask.updated_at.desc())
        .limit(1)
    )


def get_by_id(db: Session, task_id: uuid.UUID) -> AgentPptTask | None:
    return db.get(AgentPptTask, task_id)


def create_task(db: Session, **kwargs) -> AgentPptTask:
    task = AgentPptTask(**kwargs)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, task: AgentPptTask, **kwargs) -> AgentPptTask:
    for key, value in kwargs.items():
        if hasattr(task, key):
            setattr(task, key, value)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def archive_active(db: Session, *, conversation_id: uuid.UUID, except_id=None) -> None:
    stmt = select(AgentPptTask).where(
        AgentPptTask.conversation_id == conversation_id,
        AgentPptTask.status != "archived",
    )
    if except_id is not None:
        stmt = stmt.where(AgentPptTask.id != except_id)
    for task in db.scalars(stmt).all():
        task.status = "archived"
    db.commit()


def add_event(db: Session, *, task_id: uuid.UUID, action: str, detail: dict | None = None) -> None:
    db.add(AgentPptTaskEvent(task_id=task_id, action=action, detail=detail or {}))
    db.commit()


__all__ = [
    "get_active",
    "get_by_id",
    "create_task",
    "update_task",
    "archive_active",
    "add_event",
]
