"""RAG 知识库链路：上传 → 后台索引 → 检索命中 → 发布广场 → 收录 → 取消收录/下架/删除。"""

import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app
from tests.env_capability import embedding_available

TEST_DB_NAME = "child_code_test"


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
    from app.api.routers import knowledge as knowledge_router
    from app.services import rag

    # 测试用隔离的 Chroma 目录，避免污染开发环境向量库
    rag.CHROMA_DIR = tmp_path_factory.mktemp("chroma")

    TestSession = sessionmaker(bind=test_engine)
    rag._SESSION_FACTORY = TestSession
    rag.invalidate_embedding_cache()
    rag.invalidate_parent_embedding_cache()
    # 后台索引线程直连生产 SessionLocal；测试将其指向测试库
    knowledge_router._SESSION_FACTORY = TestSession

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
    rag._SESSION_FACTORY = None
    rag.invalidate_embedding_cache()
    rag.invalidate_parent_embedding_cache()
    app.dependency_overrides.clear()


def _register(client, role, tag):
    username = f"{tag}-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/auth/register",
        json={"role": role, "username": username, "password": "123456", "name": tag},
    )
    assert r.status_code == 201, r.text
    login = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _wait_ready(client, headers, timeout: float = 180.0) -> dict:
    """轮询我的库直到文档索引完成（后台线程 + 本地模型加载需要时间）。"""
    start = time.time()
    while time.time() - start < timeout:
        items = client.get("/api/knowledge/documents", headers=headers).json()["items"]
        assert len(items) == 1
        if items[0]["status"] == "ready":
            return items[0]
        assert items[0]["status"] in ("pending", "indexing"), items[0]
        time.sleep(2)
    raise AssertionError("文档索引超时未完成")


@pytest.mark.skipif(not embedding_available(), reason="本环境无可用 embedding（无 API 凭据/本地权重），跳过真实索引链路")
def test_knowledge_full_chain(client):
    """上传 → 索引 → 检索 → 发布 → 广场可见 → 收录 → 取消收录 → 下架 → 删除。"""
    teacher = _register(client, "teacher", "kb-t")
    other = _register(client, "teacher", "kb-o")

    # 1. 上传（标题/描述必填校验）
    bad = client.post(
        "/api/knowledge/documents",
        files={"file": ("a.txt", "内容", "text/plain")},
        data={"title": "", "description": "x"},
        headers=teacher,
    )
    assert bad.status_code == 422
    content = "家长会 PPT 应当先讲班级整体情况，再讲个体亮点，最后给家庭建议。"
    r = client.post(
        "/api/knowledge/documents",
        files={"file": ("ppt-guide.txt", content, "text/plain")},
        data={"title": "家长会指南", "description": "家长会流程说明"},
        headers=teacher,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("pending", "indexing", "ready")

    # 2. 等待后台索引完成
    doc = _wait_ready(client, teacher)
    assert doc["chunk_count"] >= 1

    # 3. 服务层检索命中（范围=本人库）
    from app.services import rag as rag_svc

    owner_id = uuid.UUID(doc["id"])  # 仅占位，下方用真实 owner
    _ = owner_id
    me = client.get("/api/auth/me", headers=teacher).json()
    _db = client.test_session_factory()
    try:
        hits = rag_svc.retrieve("家长会 PPT 先讲什么", db=_db, owner_id=uuid.UUID(me["id"]))
        assert hits, "本人库应检索命中"
        assert hits[0]["title"] == "家长会指南"

        # 他人未收录时检索不到
        other_me = client.get("/api/auth/me", headers=other).json()
        assert rag_svc.retrieve("家长会 PPT 先讲什么", db=_db, owner_id=uuid.UUID(other_me["id"])) == []

        # 关闭检索开关后，本人也检索不到
        from app.crud import knowledge as _kb

        doc_row = _kb.get_document_any(_db, doc_id=uuid.UUID(doc["id"]))
        assert doc_row is not None
        _kb.set_enabled(_db, doc_row, False)
        assert rag_svc.retrieve("家长会 PPT 先讲什么", db=_db, owner_id=uuid.UUID(me["id"])) == []
        _kb.set_enabled(_db, doc_row, True)
    finally:
        _db.close()

    # 4. 未就绪不能发布——此处已就绪，直接发布到广场
    pub = client.post(f"/api/knowledge/documents/{doc['id']}/publish", headers=teacher)
    assert pub.status_code == 200, pub.text
    assert pub.json()["visibility"] == "plaza"

    # 5. 广场可见 + 收录
    plaza = client.get("/api/knowledge/plaza", headers=other).json()["items"]
    assert any(i["id"] == doc["id"] for i in plaza)
    col = client.post(f"/api/knowledge/plaza/{doc['id']}/collect", headers=other)
    assert col.status_code == 200, col.text

    # 6. 收录后他人可检索命中
    _db2 = client.test_session_factory()
    try:
        hits2 = rag_svc.retrieve(
            "家长会 PPT 先讲什么",
            db=_db2,
            owner_id=uuid.UUID(other_me["id"]),
            collected_ids=[uuid.UUID(doc["id"])],
        )
        assert hits2, "收录后应检索命中"
    finally:
        _db2.close()

    # 7. 取消收录 → 下架 → 广场不可见 → 删除
    un = client.delete(f"/api/knowledge/plaza/{doc['id']}/collect", headers=other)
    assert un.status_code == 200
    unpub = client.post(f"/api/knowledge/documents/{doc['id']}/unpublish", headers=teacher)
    assert unpub.json()["visibility"] == "private"
    plaza2 = client.get("/api/knowledge/plaza", headers=other).json()["items"]
    assert all(i["id"] != doc["id"] for i in plaza2)
    rm = client.delete(f"/api/knowledge/documents/{doc['id']}", headers=teacher)
    assert rm.status_code == 200
    mine = client.get("/api/knowledge/documents", headers=teacher).json()["items"]
    assert mine == []


def test_bulk_upload_uses_per_file_descriptions(client, monkeypatch):
    from app.api.routers import knowledge as knowledge_router

    monkeypatch.setattr(knowledge_router.rag, "index_in_background", lambda **kwargs: None)
    teacher = _register(client, "teacher", "kb-bulk")

    r = client.post(
        "/api/knowledge/documents/bulk",
        files=[
            ("files", ("a.txt", "文档 A 正文", "text/plain")),
            ("files", ("b.txt", "文档 B 正文", "text/plain")),
        ],
        data={
            "titles": json.dumps(["文档 A", "文档 B"]),
            "descriptions": json.dumps(["A 的描述", "B 的描述"]),
        },
        headers=teacher,
    )
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert [d["title"] for d in created] == ["文档 A", "文档 B"]
    assert [d["description"] for d in created] == ["A 的描述", "B 的描述"]


def test_describe_document_uses_selected_model_context(client, monkeypatch):
    from types import SimpleNamespace

    from app.services import llm, llm_context

    captured: dict = {}
    config_id = uuid.uuid4()
    resolved = SimpleNamespace(
        base_url="https://example.com/v1",
        api_key="sk-test",
        model="test-model",
        embed_model=None,
        config_id=config_id,
        config_name="测试模型",
        owner_id=None,
        module="knowledge",
        is_platform=False,
    )

    def fake_resolve(db, user_id, module, selected_config_id=None):
        captured["module"] = module
        captured["config_id"] = selected_config_id
        return resolved

    def fake_invoke(system, prompt, *, temperature=0.0, timeout=60):
        captured["ctx"] = llm_context.get_current()
        captured["prompt"] = prompt
        return "  自动生成的知识库描述  "

    monkeypatch.setattr(llm_context, "resolve_override", fake_resolve)
    monkeypatch.setattr(llm, "invoke_text", fake_invoke)
    teacher = _register(client, "teacher", "kb-desc")

    r = client.post(
        "/api/knowledge/documents/describe",
        files={"file": ("a.txt", "这是用于生成描述的正文。", "text/plain")},
        data={"config_id": str(config_id), "title": "测试文档"},
        headers=teacher,
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "自动生成的知识库描述"
    assert captured["module"] == "knowledge"
    assert str(captured["config_id"]) == str(config_id)
    # 记账上下文必须带上所选模型，/usage 才能按 teacher + config 归属
    assert captured["ctx"].config_id == config_id
    assert captured["ctx"].model == "test-model"
    assert "测试文档" in captured["prompt"]


def test_describe_document_meters_usage_with_knowledge_module(client, monkeypatch):
    from types import SimpleNamespace

    from app.services import llm, llm_context, usage_meter

    config_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    resolved = SimpleNamespace(
        base_url="https://example.com/v1",
        api_key="sk-test",
        model="test-model",
        embed_model=None,
        config_id=config_id,
        config_name="测试模型",
        owner_id=owner_id,
        module="knowledge",
        is_platform=False,
    )

    class FakeResp:
        content = "自动生成的描述"
        usage_metadata = {"input_tokens": 11, "output_tokens": 7}

    class FakeModel:
        def invoke(self, msgs):
            return FakeResp()

    payload: dict = {}
    monkeypatch.setattr(llm_context, "resolve_override", lambda *a, **k: resolved)
    monkeypatch.setattr(llm, "_build_chat", lambda *a, **k: FakeModel())
    monkeypatch.setattr(usage_meter, "_put", lambda item: payload.update(item))
    teacher = _register(client, "teacher", "kb-meter")

    r = client.post(
        "/api/knowledge/documents/describe",
        files={"file": ("a.txt", "用于记账测试的正文。", "text/plain")},
        data={"config_id": str(config_id), "title": "记账测试"},
        headers=teacher,
    )
    assert r.status_code == 200, r.text
    assert payload["module"] == "knowledge"
    assert payload["config_id"] == config_id
    assert payload["owner_id"] == owner_id
    assert payload["model"] == "test-model"
    assert payload["input_tokens"] == 11
    assert payload["output_tokens"] == 7
