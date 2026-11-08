"""Token 计量与成本：定价解析、记账归属、统计聚合、CSV 导出、月度对账与保留清理。"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app

TEST_DB_NAME = "child_code_test_usage"


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
    import app.models  # noqa: F401 —— 注册全部表元数据

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def TestSession(test_engine):
    return sessionmaker(bind=test_engine)


@pytest.fixture(autouse=True)
def _clean_usage_tables(test_engine):
    """每个用例前清空账本/价格/对账表，保证统计断言互不干扰。"""
    with test_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE llm_usage_events, llm_usage_monthly, "
                "llm_usage_reconciliations, llm_model_prices"
            )
        )
    yield


@pytest.fixture()
def client(test_engine):
    from app.api import deps

    TestS = sessionmaker(bind=test_engine)

    def override_get_db():
        session = TestS()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def meter(TestSession, monkeypatch):
    from app.services import usage_meter

    monkeypatch.setattr(usage_meter, "_session_factory", lambda: TestSession)
    monkeypatch.setattr(usage_meter, "enabled", lambda: True)
    return usage_meter


def _register(client, role, tag):
    username = f"{tag}-{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/auth/register",
        json={"role": role, "username": username, "password": "123456", "name": tag},
    )
    assert r.status_code == 201, r.text
    login = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_price(Session, **kwargs):
    from app.models.usage import LLMModelPrice

    with Session() as s:
        row = LLMModelPrice(**kwargs)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


# ---------------- 定价解析 ----------------


def test_pricing_match_tier_window_and_unknown(TestSession):
    from app.models.usage import LLMModelPrice
    from app.services import pricing

    with TestSession() as s:
        s.add(
            LLMModelPrice(
                provider_host="api.deepseek.com",
                model_pattern="deepseek",
                input_per_1m=2.0,
                output_per_1m=8.0,
                tiers=[
                    {"min_input_tokens": 0, "input_per_1m": 2.0, "output_per_1m": 8.0},
                    {"min_input_tokens": 100_000, "input_per_1m": 1.0, "output_per_1m": 4.0},
                ],
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        s.add(
            LLMModelPrice(
                provider_host="api.deepseek.com",
                model_pattern="discount-model",
                input_per_1m=10.0,
                output_per_1m=10.0,
                time_windows=[{"start": "16:30", "end": "00:30", "discount": 0.5}],
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        s.commit()

    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    with TestSession() as s:
        row = pricing.resolve_price(s, "api.deepseek.com", "deepseek-chat", now)
        assert row is not None
        # 前缀匹配
        assert row.model_pattern == "deepseek"
        # host 不同 / 模型不匹配 / 生效时间之前 → 无价格
        assert pricing.resolve_price(s, "api.other.com", "deepseek-chat", now) is None
        assert pricing.resolve_price(s, "api.deepseek.com", "gpt-4o", now) is None
        assert (
            pricing.resolve_price(
                s, "api.deepseek.com", "deepseek-chat", datetime(2025, 6, 1, tzinfo=UTC)
            )
            is None
        )

        # 阶梯：200k 输入 → 第二档 1.0/1M
        cost, snap = pricing.compute_cost(
            row, input_tokens=200_000, output_tokens=0, cached_tokens=0, at=now
        )
        assert cost == pytest.approx(0.2)
        assert snap["input_per_1m"] == 1.0
        assert snap["tier_min_input_tokens"] == 100_000

        # 第一档：小额输入输出
        cost2, _ = pricing.compute_cost(
            row, input_tokens=1000, output_tokens=1000, cached_tokens=0, at=now
        )
        assert cost2 == pytest.approx((1000 * 2.0 + 1000 * 8.0) / 1_000_000)

        # 分时段折扣：UTC 20:00 落在 16:30–00:30 窗口
        discount_row = pricing.resolve_price(s, "api.deepseek.com", "discount-model", now)
        assert discount_row is not None
        at_window = datetime(2026, 6, 1, 20, 0, tzinfo=UTC)
        cost3, snap3 = pricing.compute_cost(
            discount_row, input_tokens=1_000_000, output_tokens=0, cached_tokens=0, at=at_window
        )
        assert cost3 == pytest.approx(5.0)  # 10 * 0.5
        assert snap3["time_discount"] == 0.5


def test_pricing_embedding_cross_host_fallback(TestSession):
    """Embedding/Rerank 跨网关兜底：同名模型换域名仍可按价格表计价；前缀不跨网关。"""
    from app.models.usage import LLMModelPrice
    from app.services import pricing

    with TestSession() as s:
        s.add(
            LLMModelPrice(
                provider_host="llm-x.maas.aliyuncs.com",
                model_pattern="text-embedding-v4",
                input_per_1m=0.5,
                output_per_1m=0.0,
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        s.commit()

    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    with TestSession() as s:
        # 普通调用（对话）不跨网关，避免同名模型误用他家价格
        assert pricing.resolve_price(s, "maas.qianwenaiapi.com", "text-embedding-v4", now) is None
        # Embedding/Rerank 允许按模型名精确兜底
        row = pricing.resolve_price(
            s, "maas.qianwenaiapi.com", "text-embedding-v4", now, allow_host_mismatch=True
        )
        assert row is not None and row.input_per_1m == 0.5
        # 前缀匹配不参与跨网关兜底
        assert (
            pricing.resolve_price(
                s, "maas.qianwenaiapi.com", "text-embedding-v4-extra", now,
                allow_host_mismatch=True,
            )
            is None
        )


def test_reprice_unpriced_embedding_cross_host(TestSession):
    """重算未定价：Embedding 换网关后按同名模型价格补算保留期明细。"""
    from app.api.routers.usage import reprice_unpriced
    from app.models.usage import LLMModelPrice, LLMUsageEvent

    with TestSession() as s:
        s.add(
            LLMModelPrice(
                provider_host="llm-x.maas.aliyuncs.com",
                model_pattern="text-embedding-v4",
                input_per_1m=0.5,
                output_per_1m=0.0,
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        ev = LLMUsageEvent(
            kind="embedding", module="embedding",
            provider_host="maas.qianwenaiapi.com", model="text-embedding-v4",
            input_tokens=1_000_000, output_tokens=0, source="estimated",
            priced_status="unpriced", cost=0.0, currency="CNY",
            created_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        )
        s.add(ev)
        s.commit()
        eid = ev.id

    with TestSession() as s:
        out = reprice_unpriced(since_days=366, db=s)
        assert out["repriced"] == 1
        ev = s.get(LLMUsageEvent, eid)
        assert ev.priced_status == "priced"
        assert ev.cost == pytest.approx(0.5)
        assert ev.price_snapshot


def test_pricing_weekday_peak_surcharge(TestSession):
    """DeepSeek 峰谷定价：闲时价为基准价，工作日高峰窗口（UTC）×2，周末全天不浮动。"""
    from app.models.usage import LLMModelPrice
    from app.services import pricing

    with TestSession() as s:
        s.add(
            LLMModelPrice(
                provider_host="api.deepseek.com",
                model_pattern="deepseek-flash",
                # 闲时基准价（元/1M tokens）
                input_per_1m=1.0,
                output_per_1m=4.0,
                cache_read_per_1m=0.02,
                # 北京工作日 09:00-12:00 / 14:00-18:00 = UTC 01:00-04:00 / 06:00-10:00
                time_windows=[
                    {"start": "01:00", "end": "04:00", "discount": 2.0, "weekdays": [0, 1, 2, 3, 4]},
                    {"start": "06:00", "end": "10:00", "discount": 2.0, "weekdays": [0, 1, 2, 3, 4]},
                ],
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        s.commit()

    monday = datetime(2026, 6, 1, tzinfo=UTC)  # 周一
    saturday = datetime(2026, 6, 6, tzinfo=UTC)  # 周六

    def cost_at(day, hour):
        at = day.replace(hour=hour)
        with TestSession() as s:
            row = pricing.resolve_price(s, "api.deepseek.com", "deepseek-flash", at)
            assert row is not None
            cost, snap = pricing.compute_cost(
                row, input_tokens=1_000_000, output_tokens=0, cached_tokens=0, at=at
            )
            return cost, snap["time_discount"]

    # 工作日高峰 ×2
    assert cost_at(monday, 2) == (pytest.approx(2.0), 2.0)
    assert cost_at(monday, 8) == (pytest.approx(2.0), 2.0)
    # 工作日两个高峰之间（05:00 UTC）闲时 ×1
    assert cost_at(monday, 5) == (pytest.approx(1.0), 1.0)
    # 周末即便落在高峰时刻也按闲时 ×1
    assert cost_at(saturday, 2) == (pytest.approx(1.0), 1.0)
    # 周末晚间闲时
    assert cost_at(saturday, 20) == (pytest.approx(1.0), 1.0)


def test_estimate_tokens():
    from app.services.pricing import estimate_tokens

    assert estimate_tokens("") == 0
    assert estimate_tokens("你好世界") >= 4
    assert estimate_tokens("hello world") >= 2


def test_meter_chat_skips_failed_calls_without_tokens(monkeypatch):
    """失败且未收到 token 的调用不写账本；流式已收到部分增量仍记录。"""
    from app.services import llm, usage_meter

    captured: dict = {}
    monkeypatch.setattr(usage_meter, "record_chat", lambda **kw: captured.update(kw))

    llm._meter_chat(
        input_tokens=0,
        output_tokens=0,
        prompt_text="连接失败" * 100,
        status="error",
    )
    assert captured == {}

    llm._meter_chat(
        input_tokens=0,
        output_tokens=0,
        prompt_text="已部分输出",
        output_chars=8,
        status="error",
    )
    assert captured.get("status") == "error"


def test_purge_unpriced_only_deletes_unpriced(TestSession):
    from datetime import UTC, datetime, timedelta

    from app.crud import usage as usage_crud
    from app.models.usage import LLMUsageEvent

    since = datetime.now(UTC) - timedelta(days=1)
    with TestSession() as db:
        db.add_all(
            [
                LLMUsageEvent(
                    kind="chat", module="rag_eval", provider_host="example.com",
                    model="model-a", priced_status="unpriced", cost=0.0, created_at=datetime.now(UTC),
                ),
                LLMUsageEvent(
                    kind="chat", module="rag_eval", provider_host="example.com",
                    model="model-b", priced_status="unpriced", cost=0.0, created_at=datetime.now(UTC),
                ),
                LLMUsageEvent(
                    kind="chat", module="rag_eval", provider_host="api.deepseek.com",
                    model="deepseek-chat", priced_status="priced", cost=1.5, created_at=datetime.now(UTC),
                ),
            ]
        )
        db.commit()
        scanned = usage_crud.count_unpriced(
            db, since=since, provider_host="example.com", model="model-a"
        )
        deleted = usage_crud.purge_unpriced(
            db, since=since, provider_host="example.com", model="model-a"
        )
        assert scanned == 1 and deleted == 1
        remaining = db.scalars(select(LLMUsageEvent)).all()
        assert {r.model for r in remaining} == {"model-b", "deepseek-chat"}


# ---------------- 记账与归属 ----------------


def test_meter_records_cost_and_attribution(TestSession, meter):
    from app.models.usage import LLMUsageEvent

    _seed_price(
        TestSession,
        provider_host="api.deepseek.com",
        model_pattern="deepseek-chat",
        input_per_1m=1.0,
        output_per_1m=2.0,
    )
    owner = uuid.uuid4()
    meter.record_chat(
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        input_tokens=1_000_000,
        output_tokens=0,
        owner_id=owner,
        module="report",
        is_platform=False,
    )
    meter.record_chat(
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        input_tokens=2_000_000,
        output_tokens=0,
        module="parent_service",
        is_platform=True,
    )
    meter.record_chat(
        model="unknown-model",
        base_url="https://api.unknown.com/v1",
        input_tokens=500,
        output_tokens=100,
        owner_id=owner,
        module="agent",
        is_platform=False,
    )
    assert meter.flush(5)

    with TestSession() as s:
        rows = list(s.scalars(select(LLMUsageEvent)).all())
    assert len(rows) == 3
    teacher_rows = [r for r in rows if r.model == "deepseek-chat" and not r.is_platform]
    assert len(teacher_rows) == 1
    teacher = teacher_rows[0]
    assert teacher.owner_id == owner
    assert teacher.module == "report"
    assert teacher.priced_status == "priced"
    assert teacher.cost == pytest.approx(1.0)
    assert teacher.price_snapshot["input_per_1m"] == 1.0
    platform = [r for r in rows if r.is_platform][0]
    assert platform.cost == pytest.approx(2.0)
    unpriced = [r for r in rows if r.model == "unknown-model"][0]
    assert unpriced.priced_status == "unpriced"
    assert unpriced.cost == 0.0


# ---------------- 统计 API ----------------


def test_stats_aggregation_and_permissions(client, TestSession):
    from app.models.usage import LLMUsageEvent

    admin = _register(client, "admin", "usage-admin")
    now = datetime.now(UTC)
    with TestSession() as s:
        for i in range(3):
            s.add(
                LLMUsageEvent(
                    kind="chat",
                    module="report",
                    is_platform=False,
                    provider_host="api.deepseek.com",
                    model="deepseek-chat",
                    input_tokens=1000,
                    output_tokens=500,
                    cost=0.5,
                    priced_status="priced",
                    source="provider",
                    created_at=now - timedelta(hours=i),
                )
            )
        s.add(
            LLMUsageEvent(
                kind="embedding",
                module="embedding",
                is_platform=True,
                provider_host="dashscope.aliyuncs.com",
                model="text-embedding-v3",
                input_tokens=2000,
                cost=0.2,
                priced_status="priced",
                source="estimated",
                created_at=now,
            )
        )
        s.commit()

    r = client.get("/api/admin/usage/stats?days=7", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["events"] == 4
    assert d["input_tokens"] == 5000
    assert d["output_tokens"] == 1500
    assert d["cost_estimate"] == pytest.approx(1.7)
    assert d["cost_platform"] == pytest.approx(0.2)
    assert d["cost_teacher"] == pytest.approx(1.5)
    assert d["estimated_events"] == 1
    assert d["provider_events"] == 3
    # 仪表盘求和 = 账本行求和（分日序列一致）
    assert sum(p["cost"] for p in d["series"]) == pytest.approx(d["cost_estimate"], abs=1e-6)
    assert sum(p["input_tokens"] for p in d["series"]) == d["input_tokens"]
    assert d["by_kind"]
    assert d["by_module"]

    teacher = _register(client, "teacher", "usage-teacher")
    assert client.get("/api/admin/usage/stats", headers=teacher).status_code == 403


def test_stats_unpriced_excludes_failed_and_empty_calls(client, TestSession):
    from app.models.usage import LLMUsageEvent

    admin = _register(client, "admin", "usage-noise")
    now = datetime.now(UTC)
    with TestSession() as s:
        common = {
            "kind": "chat",
            "module": "report",
            "provider_host": "api.deepseek.com",
            "model": "deepseek-chat",
            "cost": 0.0,
            "priced_status": "unpriced",
            "source": "provider",
            "created_at": now,
        }
        s.add(LLMUsageEvent(input_tokens=100, output_tokens=50, status="ok", **common))
        s.add(LLMUsageEvent(input_tokens=100, output_tokens=50, status="error", **common))
        s.add(LLMUsageEvent(input_tokens=0, output_tokens=0, status="ok", **common))
        s.commit()

    d = client.get("/api/admin/usage/stats?days=7", headers=admin).json()
    assert d["unpriced_events"] == 1
    assert sum(u["events"] for u in d["unpriced"]) == 1


def test_price_crud_export_and_reconcile(client, TestSession):
    from app.models.usage import LLMUsageEvent

    admin = _register(client, "admin", "usage-admin2")
    r = client.post(
        "/api/admin/usage/prices",
        json={
            "provider_host": "api.deepseek.com",
            "model_pattern": "deepseek-chat",
            "input_per_1m": 1.0,
            "output_per_1m": 2.0,
            "source_note": "官网价目 2026-11 核对",
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    price_id = r.json()["id"]
    items = client.get("/api/admin/usage/prices", headers=admin).json()["items"]
    assert any(p["id"] == price_id for p in items)

    r = client.put(
        f"/api/admin/usage/prices/{price_id}", json={"output_per_1m": 9.5}, headers=admin
    )
    assert r.status_code == 200
    assert r.json()["output_per_1m"] == 9.5

    now = datetime.now(UTC)
    with TestSession() as s:
        s.add(
            LLMUsageEvent(
                kind="chat",
                module="report",
                is_platform=False,
                provider_host="api.deepseek.com",
                model="deepseek-chat",
                input_tokens=10,
                output_tokens=5,
                cost=10.0,
                currency="CNY",
                priced_status="priced",
                source="provider",
                created_at=now,
            )
        )
        s.commit()

    month = now.strftime("%Y-%m")
    r = client.post(
        "/api/admin/usage/reconciliations",
        json={"month": month, "provider": "deepseek", "billed_amount": 10.5},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    recon = r.json()
    assert recon["ledger_cost"] == pytest.approx(10.0)
    assert recon["diff"] == pytest.approx(0.5)
    assert recon["diff_ratio"] == pytest.approx(0.05)

    r = client.get("/api/admin/usage/export?days=7", headers=admin)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "时间" in r.text and "deepseek-chat" in r.text

    assert client.delete(f"/api/admin/usage/prices/{price_id}", headers=admin).status_code == 200


def test_budget_settings(client):
    admin = _register(client, "admin", "usage-budget")
    r = client.put(
        "/api/admin/usage/settings",
        json={"monthly_budget": 500, "alert_ratio": 0.7},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    got = client.get("/api/admin/usage/settings", headers=admin).json()
    assert got["monthly_budget"] == pytest.approx(500)
    assert got["alert_ratio"] == pytest.approx(0.7)


def test_budget_alert_notifies_once_per_month(client, TestSession, meter):
    from app.models.system_setting import SystemSetting
    from app.models.usage import LLMUsageEvent

    _register(client, "admin", "usage-budget-alert")
    with TestSession() as s:
        s.add(
            LLMUsageEvent(
                kind="chat",
                module="agent",
                is_platform=True,
                provider_host="api.deepseek.com",
                model="deepseek-chat",
                input_tokens=1,
                output_tokens=1,
                cost=60.0,
                priced_status="priced",
                source="provider",
                created_at=datetime.now(UTC),
            )
        )
        row = s.get(SystemSetting, 1)
        if row is None:
            row = SystemSetting(id=1)
            s.add(row)
        row.llm_monthly_budget = 100.0
        row.llm_budget_alert_ratio = 0.5
        s.commit()

    first = meter.check_month_budget()
    assert first is not None
    assert first["sent"] >= 1
    # 同月幂等：再检查不重复发送
    second = meter.check_month_budget()
    assert second is not None
    assert second["sent"] == 0


# ---------------- 保留策略 ----------------


def test_cleanup_rolls_monthly_then_deletes(TestSession, meter):
    from app.models.usage import LLMUsageEvent, LLMUsageMonthly

    old = datetime.now(UTC) - timedelta(days=400)
    with TestSession() as s:
        s.add(
            LLMUsageEvent(
                kind="chat",
                module="agent",
                is_platform=False,
                provider_host="api.deepseek.com",
                model="deepseek-chat",
                input_tokens=10,
                output_tokens=5,
                cost=0.3,
                priced_status="priced",
                source="provider",
                created_at=old,
            )
        )
        s.commit()

    result = meter.cleanup_expired()
    assert result["deleted"] >= 1
    with TestSession() as s:
        assert s.scalar(select(func.count()).select_from(LLMUsageEvent)) == 0
        months = list(s.scalars(select(LLMUsageMonthly)).all())
    target = old.strftime("%Y-%m")
    assert any(m.month == target and m.events >= 1 for m in months)
