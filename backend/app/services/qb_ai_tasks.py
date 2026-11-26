"""题库 AI 批量任务：进程内任务注册表 + 后台线程执行，前端可轮询进度。

用于「AI 校准疑点题 / AI 校准本卷 / AI 知识点打标」这类耗时较长（逐题调用 LLM）
的操作：请求立即返回 task_id，执行进度与结果通过轮询获得，切换页面不丢失。
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

_TASK_TTL_SECONDS = 6 * 3600

_LOCK = threading.Lock()
_TASKS: dict[str, dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _prune_locked() -> None:
    cutoff = _now().timestamp() - _TASK_TTL_SECONDS
    stale = [
        task_id
        for task_id, task in _TASKS.items()
        if datetime.fromisoformat(task["created_at"]).timestamp() < cutoff
    ]
    for task_id in stale:
        _TASKS.pop(task_id, None)


def create_task(
    user_id: uuid.UUID,
    kind: str,
    total: int,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "status": "running",
        "progress": 0,
        "total": total,
        "message": "",
        "result": None,
        "error": None,
        "user_id": str(user_id),
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
        "meta": meta or {},
    }
    with _LOCK:
        _prune_locked()
        _TASKS[task["id"]] = task
    return dict(task)


def update_task(task_id: str, **fields: Any) -> None:
    with _LOCK:
        task = _TASKS.get(task_id)
        if task is None:
            return
        task.update(fields)
        task["updated_at"] = _now().isoformat()


def get_task(task_id: str) -> dict[str, Any] | None:
    with _LOCK:
        task = _TASKS.get(task_id)
        return dict(task) if task else None


def active_tasks(user_id: uuid.UUID) -> list[dict[str, Any]]:
    with _LOCK:
        _prune_locked()
        mine = [dict(t) for t in _TASKS.values() if t["user_id"] == str(user_id)]
    return [t for t in mine if t["status"] == "running"]


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
