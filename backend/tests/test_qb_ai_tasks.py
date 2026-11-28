"""题库 AI 后台任务注册表单元测试（数据库持久化）。"""

import time
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.user import Role, User
from app.services.qb_ai_tasks import active_tasks, create_task, get_task, spawn, update_task

TEST_DB_NAME = "child_code_qb_task_test"


@pytest.fixture(scope="session")
def test_engine():
    from app.core.config import get_settings

    base_url = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    except Exception:  # pragma: no cover - 测试环境无 PostgreSQL 时跳过
        pytest.skip("需要本地 PostgreSQL 才能运行任务持久化测试")
    admin_engine.dispose()
    engine = create_engine(base_url + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(test_engine: object, monkeypatch: pytest.MonkeyPatch):
    from sqlalchemy.orm import sessionmaker

    import app.core.database as dbmod

    test_session = sessionmaker(bind=test_engine)  # type: ignore[arg-type]
    # worker 线程内 update_task/spawn 通过 SessionLocal() 建会话；测试中改指向测试库
    monkeypatch.setattr(dbmod, "SessionLocal", test_session)
    session: Session = test_session()
    yield session
    session.close()


def _seed_user(db: Session) -> uuid.UUID:
    new_user_id = uuid.uuid4()
    db.add(
        User(
            id=new_user_id,
            role=Role.TEACHER.value,
            username=f"t{uuid.uuid4().hex[:10]}",
            name="测试教师",
            password_hash="x",
            status="active",
        )
    )
    db.commit()
    return new_user_id


def test_task_create_update_get_lifecycle(db: Session) -> None:
    user_id = _seed_user(db)
    task = create_task(db, user_id, "validate", 10)
    assert task["status"] == "running"
    assert task["progress"] == 0
    assert task["total"] == 10

    update_task(task["id"], db=db, progress=3, message="进行中…")
    fetched = get_task(db, task["id"])
    assert fetched is not None
    assert fetched["progress"] == 3
    assert fetched["message"] == "进行中…"


def test_task_done_and_active_filter(db: Session) -> None:
    user_id = _seed_user(db)
    task = create_task(db, user_id, "tag", 2)
    update_task(task["id"], db=db, progress=2, status="done")
    fetched = get_task(db, task["id"])
    assert fetched["status"] == "done"

    active = active_tasks(db, user_id)
    assert all(t["status"] == "running" for t in active)


def test_task_unknown_id_returns_none(db: Session) -> None:
    assert get_task(db, uuid.uuid4().hex) is None


def test_ttl_pruning_removes_old_task(db: Session) -> None:
    user_id = _seed_user(db)
    old_task = create_task(db, user_id, "tag", 1)
    update_task(old_task["id"], db=db, status="done")
    fetched_before = get_task(db, old_task["id"])
    assert fetched_before is not None  # 读取本身不清理
    db.execute(
        text(
            "UPDATE question_bank_ai_tasks SET created_at = '1970-01-01T00:00:00+00:00' WHERE id = :id"
        ),
        {"id": old_task["id"]},
    )
    db.commit()
    active_tasks(db, user_id)  # 触发 prune
    assert get_task(db, old_task["id"]) is None


def test_spawn_worker_completion(db: Session) -> None:
    user_id = _seed_user(db)
    task = create_task(db, user_id, "validate", 2)

    def worker() -> dict:
        # 独立会话：update_task/spawn 内部通过被 monkeypatch 的 SessionLocal 访问测试库
        for progress in (1, 2):
            update_task(task["id"], progress=progress)
        return {"processed": 2}

    spawn(task["id"], worker)
    for _ in range(100):
        fetched = get_task(db, task["id"])
        if fetched and fetched["status"] == "done":
            break
        time.sleep(0.05)
    fetched = get_task(db, task["id"])
    assert fetched is not None
    assert fetched["status"] == "done"
    assert fetched["result"]["processed"] == 2
