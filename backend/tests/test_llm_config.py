"""教师自配模型：CRUD、解析优先级、脱敏、连通性检查占位。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.config import get_settings
from app.crud import llm_config as crud
from app.main import app

TEST_DB_NAME = "child_code_test_llm"


@pytest.fixture()
def test_engine():
    base = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()
    engine = create_engine(base + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(test_engine):
    TestingSession = sessionmaker(bind=test_engine)

    def override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def session(test_engine):
    S = sessionmaker(bind=test_engine)
    db = S()
    try:
        yield db
    finally:
        db.close()


def _register(client, role, tag):
    username = f"{tag}-{role}-{uuid.uuid4().hex[:5]}"
    r = client.post(
        "/api/auth/register",
        json={"role": role, "username": username, "password": "123456", "name": tag},
    )
    assert r.status_code == 201, r.text
    login = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    tok = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=tok).json()
    return tok, me["id"]


CFG = {
    "name": "deepseek-主",
    "base_url": "https://api.deepseek.com",
    "api_key": "sk-test-123",
    "model": "deepseek-chat",
}


def test_create_list_masked(client):
    tok, _ = _register(client, "teacher", "llm")
    r = client.post("/api/llm-configs", json=CFG, headers=tok)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_default"] is True  # 首个自动为默认
    assert body["base_url"].endswith("/v1")
    items = client.get("/api/llm-configs", headers=tok).json()["items"]
    assert len(items) == 1
    assert "sk-test-123" not in str(items)  # 密钥不外泄
    assert items[0]["api_key_masked"] == "***"


def test_default_switch_and_delete_promotes(client):
    tok, _ = _register(client, "teacher", "llm2")
    a = client.post("/api/llm-configs", json=CFG, headers=tok).json()
    b = client.post(
        "/api/llm-configs",
        json={**CFG, "name": "备", "make_default": True},
        headers=tok,
    ).json()
    assert b["is_default"] is True
    items = client.get("/api/llm-configs", headers=tok).json()["items"]
    assert [i["is_default"] for i in items].count(True) == 1
    client.delete(f"/api/llm-configs/{b['id']}", headers=tok)
    items = client.get("/api/llm-configs", headers=tok).json()["items"]
    assert len(items) == 1 and items[0]["is_default"] is True  # 删默认后最早的顶上


def test_resolve_priority_mapping_over_default(client, session):
    tok, uid = _register(client, "teacher", "llm3")
    a = client.post("/api/llm-configs", json=CFG, headers=tok).json()
    b = client.post("/api/llm-configs", json={**CFG, "name": "备"}, headers=tok).json()
    r = client.put(
        "/api/llm-configs/modules/mapping",
        json={"mapping": {"report": b["id"]}},
        headers=tok,
    )
    assert r.status_code == 200, r.text
    got = client.get("/api/llm-configs/modules/mapping", headers=tok).json()["mapping"]
    assert got["report"] == b["id"]
    # crud 层优先级：映射 > 默认
    resolved = crud.resolve(session, uuid.UUID(uid), "report")
    assert resolved.config_id == uuid.UUID(b["id"])
    resolved2 = crud.resolve(session, uuid.UUID(uid), "agent")
    assert resolved2.config_id == uuid.UUID(a["id"])


def test_mapping_rejects_foreign_config(client):
    tok_a, _ = _register(client, "teacher", "llmA")
    tok_b, _ = _register(client, "teacher", "llmB")
    other = client.post("/api/llm-configs", json=CFG, headers=tok_b).json()
    r = client.put(
        "/api/llm-configs/modules/mapping",
        json={"mapping": {"agent": other["id"]}},
        headers=tok_a,
    )
    assert r.status_code == 400


def test_parent_cannot_configure(client):
    tok, _ = _register(client, "parent", "llmP")
    r = client.post("/api/llm-configs", json=CFG, headers=tok)
    assert r.status_code == 403


def test_test_endpoint_reports_unreachable(client):
    tok, _ = _register(client, "teacher", "llmT")
    cfg = client.post(
        "/api/llm-configs",
        json={**CFG, "base_url": "http://127.0.0.1:9", "model": "x"},
        headers=tok,
    ).json()
    r = client.post(f"/api/llm-configs/{cfg['id']}/test", headers=tok)
    assert r.status_code == 200
    assert r.json()["ok"] is False  # 连不上要有可读错误而不是 500
    assert r.json()["error"]


def test_context_switches_client():
    from app.services import llm as llm_svc
    from app.services import llm_context as ctx

    resolved = crud.ResolvedLLM(
        base_url="https://api.deepseek.com/v1",
        api_key="sk-x",
        model="deepseek-chat",
        embed_model=None,
        config_id=None,
        config_name="t",
    )
    with ctx.use_llm(resolved):
        assert ctx.get_current() is resolved
        client = llm_svc._chat_model()
        assert getattr(client, "model_name", "") == "deepseek-chat"
    assert ctx.get_current() is None
