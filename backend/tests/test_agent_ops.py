"""Agent 任务观测：权限、空态统计、异步 run 落库、意图口径。"""

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.database import Base
from app.main import app

TEST_DB_NAME = "child_code_agent_ops_test"


@pytest.fixture(scope="session")
def test_engine():
    from app.core.config import get_settings

    base_url = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()
    engine = create_engine(base_url + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(test_engine, tmp_path_factory):
    from app.api import deps
    from app.api.routers import agent_ops as agent_ops_router
    from app.services import agent_ops, rag_trace

    TestSession = sessionmaker(bind=test_engine)
    agent_ops._SESSION_FACTORY = TestSession
    rag_trace._SESSION_FACTORY = TestSession
    agent_ops.flush(0.1)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    c = TestClient(app)
    c.test_session_factory = TestSession  # type: ignore[attr-defined]
    yield c
    app.dependency_overrides.clear()


def _register(client, role: str, tag: str) -> dict:
    username = f"{tag}-{uuid.uuid4().hex[:8]}"
    client.post(
        "/api/auth/register",
        json={"role": role, "username": username, "password": "123456", "name": tag},
    )
    login = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_agent_ops_requires_admin(client):
    teacher_h = _register(client, "teacher", "ops-t")
    admin_h = _register(client, "admin", "ops-a")
    assert client.get("/api/admin/agent-ops/stats", headers=teacher_h).status_code == 403
    assert client.get("/api/admin/agent-ops/stats", headers=admin_h).status_code == 200


def test_agent_ops_empty_stats(client):
    admin_h = _register(client, "admin", "ops-empty")
    r = client.get("/api/admin/agent-ops/stats", headers=admin_h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_runs"] == 0
    assert data["success_rate"] is None
    assert data["ppt_alignment_rate"] is None
    assert data["rag_miss_rate"] is None


def test_run_trace_persisted(client):
    admin_h = _register(client, "admin", "ops-run")
    from app.services import agent_ops

    run_id = agent_ops.start_run(
        conversation_id=None,
        agent_id="assistant",
        user_id=None,
        intent="knowledge_qa",
        needs_rag=True,
        rag_decision="used",
        task_kind="rag_qa",
    )
    agent_ops.finish_run(run_id, status="ok", latency_ms=12, tool_calls=2)
    assert agent_ops.flush(3.0)
    deadline = time.time() + 3
    items = []
    while time.time() < deadline:
        items = client.get("/api/admin/agent-ops/runs", headers=admin_h).json()["items"]
        if items:
            break
        time.sleep(0.1)
    assert items, "run 应已异步落库"
    assert items[0]["run_id"] == run_id
    assert items[0]["intent"] == "knowledge_qa"
    assert items[0]["needs_rag"] is True
    assert items[0]["rag_decision"] == "used"


def test_run_detail_endpoint(client):
    admin_h = _register(client, "admin", "ops-detail")
    from app.services import agent_ops

    run_id = agent_ops.start_run(
        conversation_id=None,
        agent_id="assistant",
        user_id=None,
        intent="knowledge_qa",
        needs_rag=True,
        rag_decision="used",
        task_kind="rag_qa",
    )
    agent_ops.finish_run(run_id, status="ok", latency_ms=8)
    assert agent_ops.flush(3.0)

    deadline = time.time() + 3
    r = None
    while time.time() < deadline:
        r = client.get(f"/api/admin/agent-ops/runs/{run_id}", headers=admin_h)
        if r.status_code == 200:
            break
        time.sleep(0.1)
    assert r is not None and r.status_code == 200, r.text if r is not None else "no response"
    body = r.json()
    assert body["run"]["run_id"] == run_id
    assert body["run"]["rag_status"] == "used"
    assert isinstance(body["spans"], list)


def test_intent_classification_no_rag_for_ppt():
    from app.services import agent_intent

    r = agent_intent.classify("帮我生成 28 页的 Python 课件 PPT", agent_id="assistant")
    assert r["intent"] == "ppt_task"
    assert r["needs_rag"] is False

    r2 = agent_intent.classify("学员课时余额还有多少", agent_id="assistant")
    assert r2["intent"] == "business_data"
    assert r2["needs_rag"] is False

    r3 = agent_intent.classify("退费政策怎么规定", agent_id="assistant")
    assert r3["intent"] == "knowledge_qa"
    assert r3["needs_rag"] is True

    r4 = agent_intent.classify("你好", agent_id="assistant")
    assert r4["intent"] == "chitchat"
    assert r4["needs_rag"] is False


def test_ppt_validate_alignment():
    from app.models.ppt_task import AgentPptTask
    from app.services import ppt_task

    task = AgentPptTask(
        conversation_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        target_page_count=3,
        current_page_count=2,
        outline=[
            {"page_id": "p1", "title": "封面", "status": "generated"},
            {"page_id": "p2", "title": "目录", "status": "missing"},
            {"page_id": "p3", "title": "总结", "status": "missing"},
        ],
        status="needs_patch",
    )
    v = ppt_task.validate(task)
    assert v["aligned"] is False
    assert v["target_page_count"] == 3
    assert v["current_page_count"] == 2
    assert len(v["missing"]) == 2
    assert "补齐" in ppt_task.repair_prompt(task)


def test_ppt_contract_block_and_skill_hint():
    from app.models.ppt_task import AgentPptTask
    from app.services import ppt_task

    task = AgentPptTask(
        conversation_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        title="测试 PPT",
        theme="brand",
        target_page_count=2,
        current_page_count=2,
        outline=[
            {"page_id": "p1", "title": "封面", "status": "generated"},
            {"page_id": "p2", "title": "内容", "status": "generated"},
        ],
        project_key="projects/demo",
        status="exported",
    )
    block = ppt_task.contract_block(task)
    assert "目标页数：2" in block
    assert "已对齐" in block
    assert ppt_task.skill_hint(task)["project_key"] == "projects/demo"
