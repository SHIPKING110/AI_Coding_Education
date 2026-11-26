"""题库 AI 后台任务注册表单元测试（纯内存，无需数据库）。"""

import uuid

import pytest

from app.services import qb_ai_tasks


@pytest.mark.asyncio
async def test_task_create_update_get_lifecycle() -> None:
    user_id = uuid.uuid4()
    task = qb_ai_tasks.create_task(user_id, "validate", 10)
    assert task["status"] == "running"
    assert task["progress"] == 0
    assert task["total"] == 10

    qb_ai_tasks.update_task(task["id"], progress=3, message="进行中…")
    fetched = qb_ai_tasks.get_task(task["id"])
    assert fetched is not None
    assert fetched["progress"] == 3
    assert fetched["message"] == "进行中…"


def test_task_done_and_active_filter() -> None:
    user_id = uuid.uuid4()
    task = qb_ai_tasks.create_task(user_id, "tag", 2)
    qb_ai_tasks.update_task(task["id"], progress=2, status="done")
    fetched = qb_ai_tasks.get_task(task["id"])
    assert fetched["status"] == "done"

    active = qb_ai_tasks.active_tasks(user_id)
    assert all(t["status"] == "running" for t in active)


def test_spawn_worker_completion() -> None:
    user_id = uuid.uuid4()
    task = qb_ai_tasks.create_task(user_id, "validate", 2)

    def worker() -> dict:
        qb_ai_tasks.update_task(task["id"], progress=1)
        qb_ai_tasks.update_task(task["id"], progress=2)
        return {"processed": 2}

    qb_ai_tasks.spawn(task["id"], worker)
    import time

    for _ in range(100):
        fetched = qb_ai_tasks.get_task(task["id"])
        if fetched and fetched["status"] == "done":
            break
        time.sleep(0.05)
    fetched = qb_ai_tasks.get_task(task["id"])
    assert fetched is not None
    assert fetched["status"] == "done"
    assert fetched["result"]["processed"] == 2


def test_task_ttl_pruning() -> None:
    user_id = uuid.uuid4()
    old_task = qb_ai_tasks.create_task(user_id, "tag", 1)
    qb_ai_tasks.update_task(old_task["id"], status="done")
    # 直接改写时间戳模拟过期：6 h TTL 后任务会被清理（终态亦然，避免无限累积）
    qb_ai_tasks._TASKS[old_task["id"]]["created_at"] = "1970-01-01T00:00:00+00:00"
    qb_ai_tasks.active_tasks(user_id)  # 触发 prune
    assert qb_ai_tasks.get_task(old_task["id"]) is None
