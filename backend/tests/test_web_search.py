"""联网搜索工具（Tavily）单测：配置解析、工具注册、门控、内外分块、降级。

不真实调用 Tavily：用 monkeypatch 替换 httpx 传输层，验证请求体/响应解析/错误分支。
"""

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base

# 建表前导入模型，确保 metadata 收录（否则 system_search_config 不会被 create_all 建出来）
import app.models.search_config  # noqa: F401

TEST_DB_NAME = "child_code_test_websearch"


@pytest.fixture(scope="module")
def db_factory():
    from app.core.config import get_settings

    base_url = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()
    engine = create_engine(base_url + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def test_search_config_crud_and_resolve(db_factory):
    """配置：保存后能解析出明文 Key；停用/无 Key → resolve 为 None（工具自动不可用）。"""
    from app.crud import search_config as crud

    db = db_factory()
    try:
        assert crud.resolve_search(db) is None
        row = crud.upsert_system_search(
            db, base_url="https://api.tavily.com", api_key="tvly-test-key",
            enabled=True, search_depth="basic", max_results=5, language="zh",
        )
        assert row.api_key_enc and "tvly-test-key" not in row.api_key_enc  # 加密存储
        resolved = crud.resolve_search(db)
        assert resolved is not None
        assert resolved.api_key == "tvly-test-key"
        assert resolved.max_results == 5

        # 停用 → 不可用
        crud.upsert_system_search(
            db, base_url="https://api.tavily.com", api_key="", enabled=False,
        )
        assert crud.resolve_search(db) is None
    finally:
        db.close()


def test_web_search_tool_registered_and_unconfigured(db_factory):
    """工具已注册；未配置时返回明确提示而不是抛异常。"""
    from app.models.user import User
    from app.services import agent_tools

    db = db_factory()
    try:
        names = {t["function"]["name"] for t in agent_tools.TOOLS_SCHEMA}
        assert "web_search" in names
        with db:
            user = User(
                id=uuid.uuid4(), role="teacher", username=f"t-{uuid.uuid4().hex[:6]}",
                name="王老师", password_hash="x",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            out = agent_tools.execute_tool(db, user, "web_search", {"query": "少儿编程 政策"})
        assert out.get("来源") == "公网"
        assert "错误" in out and "Tavily" in out["错误"]
    finally:
        db.close()


def test_search_web_parses_results(monkeypatch):
    """响应解析：标题/链接/摘要/日期归位，条数受 max_results 限制。"""
    from app.services import web_search

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "query": "少儿编程",
                "results": [
                    {
                        "title": "政策解读",
                        "url": "https://example.com/a",
                        "content": "内容" * 200,
                        "score": 0.9,
                        "published_date": "2026-01-02",
                    },
                    {
                        "title": "行业报告",
                        "url": "https://example.com/b",
                        "content": "摘要",
                        "score": 0.8,
                    },
                ],
            }

    captured: dict = {}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "Client", _Client)

    class _Resolved:
        provider = "tavily"
        base_url = "https://api.tavily.com"
        api_key = "tvly-x"
        search_depth = "basic"
        max_results = 5
        language = "zh"

    out = web_search.search_web(_Resolved(), query="少儿编程", max_results=1)
    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["headers"]["Authorization"] == "Bearer tvly-x"
    assert captured["json"]["query"] == "少儿编程"
    assert captured["json"]["max_results"] == 1
    assert captured["json"]["language"] == "zh"
    assert out["来源"] == "公网"
    assert out["条数"] == 1
    assert out["结果"][0]["标题"] == "政策解读"
    assert out["结果"][0]["链接"] == "https://example.com/a"
    assert out["结果"][0]["日期"] == "2026-01-02"
    # 摘要被截断，避免回灌体积失控
    assert len(out["结果"][0]["摘要"]) <= 500


def test_search_web_handles_401_and_timeout(monkeypatch):
    """错误降级：401 → 提示 Key 无效；超时 → 提示超时；均不抛异常。"""
    from app.services import web_search

    class _Resolved:
        provider = "tavily"
        base_url = "https://api.tavily.com"
        api_key = "tvly-x"
        search_depth = "basic"
        max_results = 5
        language = "zh"

    class _Err:
        status_code = 401

        @staticmethod
        def json():
            return {"detail": {"error": "Unauthorized"}}

    class _Client401:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            return _Err()

    import httpx

    monkeypatch.setattr(httpx, "Client", _Client401)
    out = web_search.search_web(_Resolved(), query="x")
    assert "错误" in out and "Key" in out["错误"]

    class _ClientTimeout:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "Client", _ClientTimeout)
    out2 = web_search.search_web(_Resolved(), query="x")
    assert "错误" in out2 and "超时" in out2["错误"]

    # 未配置 → 明确提示
    out3 = web_search.search_web(None, query="x")
    assert "错误" in out3


def test_planner_block_separates_web_results():
    """注入块：内部业务数据与公网搜索结果分块，且公网块带边界说明。"""
    from app.services import agent_planner as planner

    steps = [
        planner.Step(tool="my_schedule_overview", args={"period": "this_week"}, ok=True,
                     result={"排课节数": 3}),
        planner.Step(tool="web_search", args={"query": "最新政策"}, ok=True,
                     result={"来源": "公网", "条数": 1, "结果": [{"标题": "政策", "链接": "u"}]}),
    ]
    block = planner._format_block(steps, 5000, result_chars=1200)
    assert "【业务数据】" in block
    assert "【联网搜索结果·公网外部资料】" in block
    assert "不得" in block  # 边界约束
    assert block.index("【业务数据】") < block.index("【联网搜索结果")  # 内部在前
    # 公网结果里不允许出现内部数据块标题的污染
    assert block.count("【业务数据】") == 1


def test_web_search_gate_keywords():
    """门控：外部/时效类问题放行规划器；纯业务问题由业务门控负责。"""
    from app.services import agent_tools

    assert agent_tools.looks_like_web_search("最新的少儿编程政策是什么") is True
    assert agent_tools.looks_like_web_search("帮我搜一下竞品怎么收费") is True
    assert agent_tools.looks_like_web_search("你好") is False
    assert agent_tools.looks_like_web_search("") is False
