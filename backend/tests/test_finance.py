"""课包 × 财务 × 设置回归测试：科目/校区 CRUD、课包科目标签与编辑锁、
小数课时消耗与创收账本、订单 5 分钟过期、家长自助退款三闸、权限新键、财务聚合。

需要本地 PostgreSQL；使用独立测试库 child_code_finance_test。
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app

TEST_DB_NAME = "child_code_finance_test"


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
def client(test_engine):
    from app.api import deps

    TestSession = sessionmaker(bind=test_engine)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def dbsession(test_engine):
    """直连测试库的 session（注意：不要用 SessionLocal，那是开发库）。"""
    TestSession = sessionmaker(bind=test_engine)
    session = TestSession()
    yield session
    session.close()


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


def _uid(client, headers):
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    return r.json()["id"]


@pytest.fixture()
def admin(client):
    return _register(client, "admin", "fin-admin")


@pytest.fixture()
def teacher(client):
    return _register(client, "teacher", "fin-teacher")


def test_business_seed_and_crud(client, admin, teacher):
    """校区/科目 seed + 增删改查；教师默认无设置权限。"""
    subs = client.get("/api/business/subjects", headers=admin)
    assert subs.status_code == 200, subs.text
    names = {s["name"] for s in subs.json()["items"]}
    assert {"乐高", "Python", "C++"} <= names
    lego = next(s for s in subs.json()["items"] if s["name"] == "乐高")
    assert lego["per_session"] == "1.5"

    camps = client.get("/api/business/campuses", headers=admin)
    assert {c["name"] for c in camps.json()["items"]} >= {"一校", "二校", "总部"}

    # 教师无 settings_manage：写被拒
    r = client.post("/api/business/campuses", json={"name": "新校区"}, headers=teacher)
    assert r.status_code == 403, r.text

    # 管理员新增/改名/停用校区
    r = client.post("/api/business/campuses", json={"name": "新校区"}, headers=admin)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = client.patch(f"/api/business/campuses/{cid}", json={"name": "三校"}, headers=admin)
    assert r.json()["name"] == "三校"
    r = client.patch(f"/api/business/campuses/{cid}", json={"active": False}, headers=admin)
    assert r.json()["active"] is False

    # 科目新增（带抽成）+ 清空为全局
    r = client.post(
        "/api/business/subjects",
        json={"name": "测试科目", "per_session": "1.5", "commission_rate": "0.25"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = client.patch(
        f"/api/business/subjects/{sid}",
        json={"commission_rate": None, "commission_rate_set": True},
        headers=admin,
    )
    assert r.json()["commission_rate"] is None

    # 财务参数读写
    r = client.get("/api/business/finance-setting", headers=admin)
    assert r.status_code == 200
    assert "formula" in r.json()
    r = client.put(
        "/api/business/finance-setting",
        json={"commission_default": "0.35"},
        headers=admin,
    )
    assert float(r.json()["commission_default"]) == 0.35
    # 教师写财务参数被拒
    r = client.put(
        "/api/business/finance-setting", json={"commission_default": "0.1"}, headers=teacher
    )
    assert r.status_code == 403


def _make_package(client, admin, **kw):
    payload = {"name": f"包-{uuid.uuid4().hex[:6]}", "price": "3000.00", "total_lessons": 20}
    payload.update(kw)
    r = client.post("/api/lesson-packages", json=payload, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def _make_student(client, admin, name, balance, class_ids, **extra):
    r = client.post(
        "/api/students",
        json={"name": name, "lesson_balance": balance, "class_ids": class_ids, **extra},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_package_subject_tag_filters_and_edit_lock(client, admin):
    """课包科目/标签/活动时间窗/筛选/发布日期销量/编辑锁。"""
    subs = client.get("/api/business/subjects", headers=admin).json()["items"]
    lego_id = next(s["id"] for s in subs if s["name"] == "乐高")

    start = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    end = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    pkg = _make_package(
        client, admin, subject_id=lego_id, tag="activity",
        sale_start=start, sale_end=end,
    )
    assert pkg["subject_name"] == "乐高"
    assert pkg["tag"] == "activity"
    assert pkg["published_at"] is not None
    assert pkg["paid_students"] == 0

    # 活动包缺时间窗被拒
    r = client.post(
        "/api/lesson-packages",
        json={"name": "坏活动包", "price": "100.00", "total_lessons": 2, "tag": "activity"},
        headers=admin,
    )
    assert r.status_code == 400

    # 筛选：科目 + 标签 + 售价范围
    r = client.get(
        "/api/lesson-packages",
        params={"subject_id": lego_id, "tag": "activity", "price_min": "100", "price_max": "5000"},
        headers=admin,
    )
    assert r.status_code == 200
    assert any(p["id"] == pkg["id"] for p in r.json()["items"])
    r = client.get("/api/lesson-packages", params={"price_min": "99999"}, headers=admin)
    assert all(p["id"] != pkg["id"] for p in r.json()["items"])

    # 编辑：改名/科目 ok
    r = client.patch(
        f"/api/lesson-packages/{pkg['id']}",
        json={"name": "改名包", "subject_id": None, "subject_id_set": True},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "改名包"

    # 产生已支付订单后锁价与总课时
    parent = _register(client, "parent", "lock-parent")
    parent_uid = _uid(client, parent)
    stu = _make_student(client, admin, "锁价学员", 0, [], parent_user_id=parent_uid)
    o = client.post(
        "/api/client/orders",
        json={"student_id": stu["id"], "package_id": pkg["id"]},
        headers=parent,
    )
    assert o.status_code == 201
    pay = client.post(f"/api/client/orders/{o.json()['id']}/pay", headers=parent)
    assert pay.status_code == 200
    r = client.patch(
        f"/api/lesson-packages/{pkg['id']}", json={"price": "9999.00"}, headers=admin
    )
    assert r.status_code == 400
    assert "不可再改" in r.json()["detail"]
    r = client.patch(
        f"/api/lesson-packages/{pkg['id']}", json={"name": "改名2"}, headers=admin
    )
    assert r.status_code == 200


def test_fraction_consume_and_ledger(client, admin):
    """乐高班考勤扣 1.5 + 创收账本（FIFO 单价快照 + 抽成快照）。"""
    parent = _register(client, "parent", "ledger-parent")
    parent_uid = _uid(client, parent)
    r = client.post(
        "/api/classes", json={"name": "乐高消耗班", "subject": "乐高"}, headers=admin
    )
    assert r.status_code == 201
    class_id = r.json()["id"]
    stu = _make_student(client, admin, "消耗学员", 10, [class_id], parent_user_id=parent_uid)

    pkg = _make_package(client, admin, price="3000.00", total_lessons=20)  # 150/课时
    o = client.post(
        "/api/client/orders",
        json={"student_id": stu["id"], "package_id": pkg["id"]},
        headers=parent,
    ).json()
    client.post(f"/api/client/orders/{o['id']}/pay", headers=parent)
    conf = client.post(f"/api/orders/{o['id']}/confirm", headers=admin)
    assert conf.status_code == 200, conf.text

    start = datetime(2026, 8, 20, 14, 0)
    end = datetime(2026, 8, 20, 15, 30)
    tid = _uid(client, admin)
    s = client.post(
        "/api/schedules",
        json={"class_id": class_id, "teacher_id": tid,
              "start_time": start.isoformat(), "end_time": end.isoformat()},
        headers=admin,
    )
    assert s.status_code == 201, s.text
    sched_id = s.json()["schedule"]["id"]
    sub = client.post(
        f"/api/schedules/{sched_id}/attendance",
        json={"items": [{"student_id": stu["id"], "status": "attended"}]},
        headers=admin,
    )
    assert sub.status_code == 200, sub.text
    rec = sub.json()["lesson_records"][0]
    assert float(rec["delta"]) == -1.5
    assert float(rec["balance_after"]) == 28.5

    # 账本：1.5 × 150 = 225，抽成按全局默认 0.30（前一个测试改过）或科目
    ov = client.get("/api/finance/overview", params={"granularity": "year"}, headers=admin)
    assert ov.status_code == 200, ov.text
    assert float(ov.json()["totals"]["revenue"]) >= 225
    by = client.get("/api/finance/by-subject", headers=admin)
    assert by.status_code == 200
    lego = next((i for i in by.json()["items"] if i["subject"] == "乐高"), None)
    assert lego is not None
    assert float(lego["revenue"]) >= 225
    tea = client.get("/api/finance/by-teacher", headers=admin)
    assert tea.status_code == 200
    assert len(tea.json()["items"]) >= 1

    # 教师无 finance_view 被拒
    teacher = _register(client, "teacher", "ledger-teacher")
    r = client.get("/api/finance/overview", headers=teacher)
    assert r.status_code == 403


def test_order_expiry(client, admin, dbsession):
    """待支付订单过期：支付被拒并自动撤销。"""
    parent = _register(client, "parent", "expire-parent")
    parent_uid = _uid(client, parent)
    stu = _make_student(client, admin, "过期学员", 0, [], parent_user_id=parent_uid)
    pkg = _make_package(client, admin)
    o = client.post(
        "/api/client/orders",
        json={"student_id": stu["id"], "package_id": pkg["id"]},
        headers=parent,
    ).json()
    assert o["expires_at"] is not None

    # 后台把过期时间拨到过去模拟超时
    from app.models.enrollment import Order

    order = dbsession.get(Order, o["id"])
    order.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    dbsession.commit()

    pay = client.post(f"/api/client/orders/{o['id']}/pay", headers=parent)
    assert pay.status_code == 400
    assert "超时" in pay.json()["detail"]
    # 列表再次读取应为已取消
    lst = client.get("/api/client/orders", params={"student_id": stu["id"]}, headers=parent)
    assert lst.json()["items"][0]["status"] == "cancelled"


def test_parent_self_refund_gates(client, admin, dbsession):
    """家长自助退款：可退 / 已消耗 / 超 7 天三闸。"""
    parent = _register(client, "parent", "refund-parent")
    parent_uid = _uid(client, parent)

    def new_pair(name):
        stu = _make_student(client, admin, name, 0, [], parent_user_id=parent_uid)
        pkg = _make_package(client, admin, price="2000.00", total_lessons=10)
        o = client.post(
            "/api/client/orders",
            json={"student_id": stu["id"], "package_id": pkg["id"]},
            headers=parent,
        ).json()
        client.post(f"/api/client/orders/{o['id']}/pay", headers=parent)
        conf = client.post(f"/api/orders/{o['id']}/confirm", headers=admin)
        assert conf.status_code == 200
        return stu, o

    # 正常可退：全额 + 扣余额
    stu_ok, o_ok = new_pair("退款学员A")
    chk = client.get(f"/api/client/orders/{o_ok['id']}/refund-check", headers=parent)
    assert chk.json()["ok"] is True
    r = client.post(
        f"/api/client/orders/{o_ok['id']}/refund",
        json={"reason_key": "wrong_package"},
        headers=parent,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "refunded"
    assert r.json()["refund_note"] == "买错课包了"
    me = client.get("/api/client/me", headers=parent).json()
    s_after = next(s for s in me["students"] if s["id"] == stu_ok["id"])
    assert float(s_after["lesson_balance"]) == 0
    # 订单管理可见退款记录
    lst = client.get("/api/orders", params={"status": "refunded"}, headers=admin)
    assert any(x["id"] == o_ok["id"] for x in lst.json()["items"])

    # 其他原因必填文本
    _, o_other = new_pair("退款学员B")
    r = client.post(
        f"/api/client/orders/{o_other['id']}/refund",
        json={"reason_key": "other", "reason_text": ""},
        headers=parent,
    )
    assert r.status_code == 400

    # 已消耗闸：排一节 Python 课扣 2
    stu_c, o_c = new_pair("退款学员C")
    r = client.post("/api/classes", json={"name": "退款消耗班", "subject": "Python"}, headers=admin)
    class_id = r.json()["id"]
    client.patch(f"/api/students/{stu_c['id']}/classes", json={"class_ids": [class_id]}, headers=admin)
    s = client.post(
        "/api/schedules",
        json={"class_id": class_id, "teacher_id": _uid(client, admin),
              "start_time": "2026-08-20T14:00:00", "end_time": "2026-08-20T15:30:00"},
        headers=admin,
    ).json()
    client.post(
        f"/api/schedules/{s['schedule']['id']}/attendance",
        json={"items": [{"student_id": stu_c["id"], "status": "attended"}]},
        headers=admin,
    )
    chk = client.get(f"/api/client/orders/{o_c['id']}/refund-check", headers=parent)
    assert chk.json()["ok"] is False
    assert chk.json()["code"] == "consumed"
    r = client.post(
        f"/api/client/orders/{o_c['id']}/refund",
        json={"reason_key": "busy"},
        headers=parent,
    )
    assert r.status_code == 400
    assert "联系教务" in r.json()["detail"]

    # 超 7 天闸
    _, o_old = new_pair("退款学员D")
    from app.models.enrollment import Order as OrderModel

    order = dbsession.get(OrderModel, o_old["id"])
    order.confirmed_at = datetime.now(UTC) - timedelta(days=8)
    dbsession.commit()
    chk = client.get(f"/api/client/orders/{o_old['id']}/refund-check", headers=parent)
    assert chk.json()["code"] == "overdue"


def test_permission_keys_and_teacher_nav(client, admin, teacher):
    """权限键含新键；教师默认关闭设置/财务；学生不可见课时包。"""
    keys = client.get("/api/permissions/keys", headers=admin).json()["keys"]
    by_key = {k["key"]: k["label"] for k in keys}
    assert "settings_manage" in by_key and "finance_view" in by_key

    mine = client.get("/api/permissions/mine", headers=teacher).json()["permissions"]
    assert mine["settings_manage"] is False
    assert mine["finance_view"] is False
    assert mine["order_visible"] is False

    student_user = _register(client, "student", "fin-student")
    r = client.get("/api/client/packages", headers=student_user)
    assert r.status_code == 403
