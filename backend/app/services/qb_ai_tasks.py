"""题库 AI 批量任务：数据库持久化 + 后台线程执行，前端可轮询进度。

用于「AI 校准疑点题 / AI 校准本卷 / AI 知识点打标」这类耗时较长（逐题调用 LLM）
的操作：请求立即返回 task_id，执行进度与结果通过轮询获得；任务状态落库，
进程重启/滚动部署后进度不丢失（原实现为纯内存注册表）。
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.question_bank import QuestionBankAiTask

_TASK_TTL = timedelta(hours=6)


def _serialize(task: QuestionBankAiTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "progress": task.progress,
        "total": task.total,
        "message": task.message or "",
        "result": task.result,
        "error": task.error,
        "user_id": str(task.user_id),
        "created_at": (task.created_at or datetime.now(UTC)).isoformat(),
        "updated_at": (task.updated_at or datetime.now(UTC)).isoformat(),
        "meta": task.meta or {},
    }


def _prune(db: Session) -> None:
    cutoff = datetime.now(UTC) - _TASK_TTL
    db.execute(delete(QuestionBankAiTask).where(QuestionBankAiTask.created_at < cutoff))
    db.commit()


def create_task(
    db: Session,
    user_id: uuid.UUID,
    kind: str,
    total: int,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _prune(db)
    task = QuestionBankAiTask(
        id=uuid.uuid4().hex,
        user_id=user_id,
        kind=kind,
        status="running",
        progress=0,
        total=total,
        message="",
        meta=meta or {},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _serialize(task)


def update_task(task_id: str, *, db: Session | None = None, **fields: Any) -> None:
    """worker 线程内更新任务状态；若传入 db 则复用该会话（测试/同会话场景），
    否则开独立短会话（生产后台线程场景），保证每步更新立即可见。"""

    def _update(session: Session) -> None:
        task = session.get(QuestionBankAiTask, task_id)
        if task is None:
            return
        for key, value in fields.items():
            setattr(task, key, value)
        session.commit()

    if db is not None:
        _update(db)
        return
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        _update(session)
    finally:
        session.close()


def get_task(db: Session, task_id: str) -> dict[str, Any] | None:
    task = db.get(QuestionBankAiTask, task_id)
    return _serialize(task) if task else None


def active_tasks(db: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    _prune(db)
    rows = db.scalars(
        select(QuestionBankAiTask).where(
            QuestionBankAiTask.user_id == user_id,
            QuestionBankAiTask.status == "running",
        )
    ).all()
    return [_serialize(row) for row in rows]


def spawn(task_id: str, worker: Callable[[], dict[str, Any]]) -> None:
    """在线程中执行 worker，结束时将任务标记 done/error。"""

    def _runner() -> None:
        try:
            result = worker()
        except Exception as exc:  # noqa: BLE001 - 错误要回传给前端任务卡片
            update_task(task_id, status="error", error=str(exc) or exc.__class__.__name__)
            return
        update_task(task_id, status="done", result=result, message="完成")

    threading.Thread(target=_runner, daemon=True, name=f"qb-ai-task-{task_id}").start()
