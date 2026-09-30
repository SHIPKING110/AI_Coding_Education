"""M5 客户端测试：账号绑定、客户端首页、反馈/课表查看、课时订阅（模拟支付）、
在线作业作答（断点保存/空题校验/自动判题/教师批改）、通知提醒。

需要本地 PostgreSQL；使用独立测试库 child_code_test。
"""

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app

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


def _make_class(client, admin, name="Python 入门"):
    r = client.post("/api/classes", json={"name": name, "subject": "Python"}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _make_student(client, admin, name, balance, class_ids, **extra):
    r = client.post(
        "/api/students",
        json={
            "name": name,
            "phone": None,
            "lesson_balance": balance,
            "class_ids": class_ids,
            **extra,
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _make_package(client, admin, name="48 课时包", total=48, price="4800.00"):
    r = client.post(
        "/api/lesson-packages",
        json={"name": name, "price": price, "total_lessons": total},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_client_binding_and_home(client):
    """家长账号绑定学员后，客户端首页可见孩子课时/班级/未读通知。"""
    admin = _register(client, "admin", "admin")
    parent = _register(client, "parent", "parent")
    parent_uid = _uid(client, parent)
    class_id = _make_class(client, admin)
    stu = _make_student(client, admin, "小红", 20, [class_id], parent_user_id=parent_uid)
    assert stu["parent_user_id"] == parent_uid

    home = client.get("/api/client/me", headers=parent)
    assert home.status_code == 200, home.text
    body = home.json()
    assert body["role"] == "parent"
    assert len(body["students"]) == 1
    s = body["students"][0]
    assert s["name"] == "小红"
    assert s["lesson_balance"] == 20
    assert s["low_balance"] is False
    assert "unread_notifications" in body


def test_student_user_binding(client):
    """学员账号可绑定自己的学员记录并访问客户端（student_user_id）。"""
    admin = _register(client, "admin", "admin")
    student_user = _register(client, "student", "stu")
    uid = _uid(client, student_user)
    class_id = _make_class(client, admin)
    stu = _make_student(client, admin, "自己", 20, [class_id], student_user_id=uid)
    assert stu["student_user_id"] == uid

    home = client.get("/api/client/me", headers=student_user)
    assert home.status_code == 200
    assert len(home.json()["students"]) == 1
    assert home.json()["students"][0]["name"] == "自己"


def test_register_phone_conflict_rejected(client):
    """注册手机号冲突返回 409（家长手机号=登录名场景：同手机号只能有一个 phone 记录）。"""
    phone = f"138{uuid.uuid4().int % 10**8:08d}"
    r1 = client.post(
        "/api/auth/register",
        json={
            "role": "parent",
            "username": f"p-{uuid.uuid4().hex[:8]}",
            "password": "123456",
            "name": "家长A",
            "phone": phone,
        },
    )
    assert r1.status_code == 201, r1.text
    r2 = client.post(
        "/api/auth/register",
        json={
            "role": "parent",
            "username": f"p-{uuid.uuid4().hex[:8]}",
            "password": "123456",
            "name": "家长B",
            "phone": phone,
        },
    )
    assert r2.status_code == 409
    assert r2.json()["detail"] == "Phone already exists"


def test_client_feedbacks_published_only(client):
    """客户端只能看到已发布（published）的反馈，草稿不可见；发布后家长收到通知。"""
    admin = _register(client, "admin", "admin")
    teacher = _register(client, "teacher", "teacher")
    teacher_uid = _uid(client, teacher)
    parent = _register(client, "parent", "parent")
    parent_uid = _uid(client, parent)
    class_id = _make_class(client, admin)
    stu = _make_student(client, admin, "反馈学生", 20, [class_id], parent_user_id=parent_uid)

    schedule_id = _make_schedule(
        client, teacher, class_id, teacher_uid,
        datetime(2026, 9, 10, 9, 0), datetime(2026, 9, 10, 10, 30),
    )

    fb = client.post(
        "/api/feedbacks",
        json={
            "schedule_id": schedule_id,
            "student_id": stu["id"],
            "title": "第1次课",
            "topic": "变量与打印",
            "content": "学习了 print",
            "performance": "表现很好",
            "homework": "练习 print",
        },
        headers=teacher,
    )
    assert fb.status_code == 201, fb.text
    fb_id = fb.json()["id"]

    # 草稿不可见
    r = client.get(f"/api/client/students/{stu['id']}/feedbacks", headers=parent)
    assert r.json()["total"] == 0
    # 发布后可见
    client.post(f"/api/feedbacks/{fb_id}/publish", headers=teacher)
    r = client.get(f"/api/client/students/{stu['id']}/feedbacks", headers=parent)
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["topic"] == "变量与打印"
    # 通知已生成
    notif = client.get("/api/notifications", headers=parent)
    assert notif.status_code == 200
    types = [n["type"] for n in notif.json()["items"]]
    assert "feedback_published" in types


def _make_schedule(client, teacher, class_id, teacher_id, start, end):
    r = client.post(
        "/api/schedules",
        json={
            "class_id": class_id,
            "teacher_id": teacher_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
        headers=teacher,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] is True, body
    return body["schedule"]["id"]


def test_subscription_order_flow(client):
    """课时订阅：下单(pending) → 模拟支付(paid) → 管理员确认(confirmed 到账+流水+通知)。"""
    admin = _register(client, "admin", "admin")
    parent = _register(client, "parent", "parent")
    parent_uid = _uid(client, parent)
    class_id = _make_class(client, admin)
    stu = _make_student(client, admin, "订阅学生", 20, [class_id], parent_user_id=parent_uid)
    pkg = _make_package(client, admin)

    order = client.post(
        "/api/client/orders",
        json={"student_id": stu["id"], "package_id": pkg["id"]},
        headers=parent,
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert order.json()["status"] == "pending"
    assert order.json()["package_name"] == pkg["name"]

    orders = client.get("/api/client/orders", headers=parent)
    assert orders.json()["total"] == 1

    paid = client.post(f"/api/client/orders/{order_id}/pay", headers=parent)
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"

    # 确认前课时不变
    detail = client.get(f"/api/client/students/{stu['id']}", headers=parent)
    assert detail.json()["lesson_balance"] == 20

    # 管理员确认到账
    confirmed = client.post(f"/api/orders/{order_id}/confirm", headers=admin)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    detail = client.get(f"/api/client/students/{stu['id']}", headers=parent)
    assert detail.json()["lesson_balance"] == 20 + pkg["total_lessons"]

    notif = client.get("/api/notifications", headers=parent)
    types = [n["type"] for n in notif.json()["items"]]
    assert "order_confirmed" in types


def test_assignment_judge_and_grade(client):
    """在线作业：发布 → 客户端列表/详情（不含答案）→ 保存进度 → 空题拦截 →
    提交自动判题 → 教师批改编程题 → 学员端看到成绩与通知。"""
    admin = _register(client, "admin", "admin")
    teacher = _register(client, "teacher", "teacher")
    parent = _register(client, "parent", "parent")
    parent_uid = _uid(client, parent)
    class_id = _make_class(client, admin)
    stu = _make_student(client, admin, "作业学生", 20, [class_id], parent_user_id=parent_uid)

    questions = [
        {
            "type": "single_choice",
            "stem": "Python 中输出用什么函数？",
            "options": ["printf", "print", "echo", "console.log"],
            "answer": 1,
            "analysis": "print 是 Python 输出函数",
            "difficulty": 2,
        },
        {
            "type": "programming",
            "stem": "写一个函数 add(a,b) 返回两数之和",
            "answer": "def add(a, b):\n    return a + b",
            "analysis": "直接 return a+b",
            "difficulty": 3,
            "test_cases": [{"input": "1 2", "output": "3"}],
            "language": "python",
        },
    ]
    a = client.post(
        "/api/assignments",
        json={"title": "第一次作业", "description": "基础练习", "questions": questions},
        headers=teacher,
    )
    assignment_id = a.json()["id"]

    pub = client.post(
        f"/api/assignments/{assignment_id}/publish",
        json={"class_ids": [class_id], "deadline": None},
        headers=teacher,
    )
    assert pub.status_code == 200, pub.text

    # 客户端列表可见
    lst = client.get(f"/api/client/assignments?student_id={stu['id']}", headers=parent)
    assert lst.status_code == 200, lst.text
    assert lst.json()["total"] == 1
    assert lst.json()["items"][0]["my_status"] == "not_submitted"
    assert lst.json()["items"][0]["question_count"] == 2

    # 详情：题目不含答案/解析
    detail = client.get(
        f"/api/client/assignments/{assignment_id}?student_id={stu['id']}", headers=parent
    )
    assert detail.status_code == 200, detail.text
    qs = detail.json()["questions"]
    assert len(qs) == 2
    assert "answer" not in qs[0]
    assert "analysis" not in qs[0]

    # 保存进度（FR-CL-12 自动保存）
    save = client.post(
        f"/api/client/assignments/{assignment_id}/answers?student_id={stu['id']}",
        json={"answers": {"1": 1}},
        headers=parent,
    )
    assert save.status_code == 200, save.text
    assert save.json()["answers"]["1"] == 1
    assert save.json()["status"] == "not_submitted"

    # 提交：空题拦截（第 2 题未做）
    submit = client.post(
        f"/api/client/assignments/{assignment_id}/submit?student_id={stu['id']}",
        json={"answers": {"1": 1}},
        headers=parent,
    )
    assert submit.status_code == 200
    assert submit.json()["empty_questions"] == [2]

    # 全部完成提交 → 自动判题（单选对，编程待人工批改）
    submit = client.post(
        f"/api/client/assignments/{assignment_id}/submit?student_id={stu['id']}",
        json={"answers": {"1": 1, "2": "def add(a, b):\n    return a + b"}},
        headers=parent,
    )
    assert submit.status_code == 200, submit.text
    res = submit.json()
    assert res["empty_questions"] == []
    assert res["pending_manual"] == 1
    sub = res["submission"]
    assert sub["status"] == "submitted"
    assert sub["judge_results"]["1"]["correct"] is True
    assert sub["judge_results"]["2"]["correct"] is None

    # 教师查看提交列表与详情
    subs = client.get(f"/api/assignments/{assignment_id}/submissions", headers=teacher)
    assert subs.status_code == 200, subs.text
    assert len(subs.json()) == 1
    assert subs.json()[0]["pending_manual"] == 1
    sub_id = subs.json()[0]["id"]

    # 批改：编程题给 1 分
    grade = client.post(
        f"/api/assignments/{assignment_id}/submissions/{sub_id}/grade",
        json={"scores": {"2": 1}, "comment": "写得很棒"},
        headers=teacher,
    )
    assert grade.status_code == 200, grade.text
    body = grade.json()
    assert body["score"] == 2
    assert body["total"] == 2
    assert body["status"] == "graded"

    # 学员端：我的状态 graded，分数 2/2
    lst = client.get(f"/api/client/assignments?student_id={stu['id']}", headers=parent)
    item = lst.json()["items"][0]
    assert item["my_status"] == "graded"
    assert item["my_score"] == 2
    assert item["my_total"] == 2

    # 通知：批改完成（家长收到）
    notif = client.get("/api/notifications", headers=parent)
    types = [n["type"] for n in notif.json()["items"]]
    assert "submission_graded" in types


def test_reminders_and_notifications(client):
    """提醒通知：低课时（≤10）自动生成；未读数与标记已读。"""
    admin = _register(client, "admin", "admin")
    parent = _register(client, "parent", "parent")
    parent_uid = _uid(client, parent)
    class_id = _make_class(client, admin)
    stu = _make_student(client, admin, "提醒学生", 20, [class_id], parent_user_id=parent_uid)

    # 调低课时 → 触发低余量提醒
    client.post(
        f"/api/students/{stu['id']}/lesson-records",
        json={"delta": -18, "remark": "消耗"},
        headers=admin,
    )
    me = client.get("/api/client/me", headers=parent)
    assert me.status_code == 200
    assert me.json()["students"][0]["low_balance"] is True

    notif = client.get("/api/notifications?unread_only=true", headers=parent)
    types = [n["type"] for n in notif.json()["items"]]
    assert "low_balance" in types

    unread = client.get("/api/notifications/unread-count", headers=parent)
    assert unread.json()["count"] > 0
    read = client.post("/api/notifications/read-all", headers=parent)
    assert read.status_code == 200
    unread = client.get("/api/notifications/unread-count", headers=parent)
    assert unread.json()["count"] == 0


def test_client_access_control(client):
    """客户端仅 parent/student 可访问；教师访问 403。"""
    teacher = _register(client, "teacher", "teacher")
    r = client.get("/api/client/me", headers=teacher)
    assert r.status_code == 403


# ---------- M5 增强回归 ----------

def test_student_campus_and_refund_fifo(client):
    """学员校区 + FIFO 退费：多课时包按先进先出扣减，退费自动算明细并通知家长。"""
    admin = _register(client, "admin", "admin")
    parent = _register(client, "parent", "parent")
    parent_uid = _uid(client, parent)
    class_id = _make_class(client, admin)
    stu = _make_student(
        client, admin, "小明", 0, [class_id],
        campus="一校", parent_user_id=parent_uid,
    )
    assert stu["campus"] == "一校"

    # 两个课时包：先买 40 课时 ¥4800（¥120/节），后买 80 课时 ¥7600（¥95/节）
    pkg_a = _make_package(client, admin, name="40 课时包", total=40, price="4800.00")
    pkg_b = _make_package(client, admin, name="80 课时包", total=80, price="7600.00")

    def _buy(pkg):
        o = client.post(
            "/api/client/orders",
            json={"student_id": stu["id"], "package_id": pkg["id"]},
            headers=parent,
        ).json()
        client.post(f"/api/client/orders/{o['id']}/pay", headers=parent)
        c = client.post(f"/api/orders/{o['id']}/confirm", headers=admin)
        assert c.status_code == 200, c.text
        assert c.json()["status"] == "confirmed"
        return o

    oa = _buy(pkg_a)  # 40 课时
    ob = _buy(pkg_b)  # 80 课时

    # 消耗 35 课时（先扣 A 包 35 节，剩 A=5、B=80）
    consume = client.post(
        f"/api/students/{stu['id']}/lesson-records",
        json={"delta": -35, "remark": "消耗课时"},
        headers=admin,
    )
    assert consume.status_code == 201, consume.text
    balance = client.get(f"/api/students/{stu['id']}", headers=admin).json()["lesson_balance"]
    assert balance == 85

    # 退费预览：A 剩余 5 节 × ¥120 = ¥600；B 剩余 80 节 × ¥95 = ¥7600
    preview = client.get(f"/api/students/{stu['id']}/refund-preview", headers=admin)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total_lessons"] == 85
    items = {it["order_id"]: it for it in body["items"]}
    assert items[oa["id"]]["remaining_lessons"] == 5
    assert items[oa["id"]]["refund_amount"] == "600.00"
    assert items[ob["id"]]["remaining_lessons"] == 80
    assert items[ob["id"]]["refund_amount"] == "7600.00"
    assert body["total_amount"] == "8200.00"

    # 备注必填
    r_no = client.post(f"/api/students/{stu['id']}/refund", json={"note": ""}, headers=admin)
    assert r_no.status_code == 422

    # 执行退费：余额归零、订单 refunded、流水/通知生成
    r = client.post(
        f"/api/students/{stu['id']}/refund",
        json={"note": "家长申请退费"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["total_lessons"] == 85
    assert res["total_amount"] == "8200.00"
    assert len(res["orders"]) == 2
    assert len(res["records"]) == 2

    assert client.get(f"/api/students/{stu['id']}", headers=admin).json()["lesson_balance"] == 0

    order_a = client.get(f"/api/orders/{oa['id']}", headers=admin).json()
    assert order_a["status"] == "refunded"
    assert order_a["refund_amount"] == "600.00"

    notif = client.get("/api/notifications", headers=parent)
    types = [n["type"] for n in notif.json()["items"]]
    assert "refund" in types

    # 二次退费：无可退课时
    r2 = client.post(f"/api/students/{stu['id']}/refund", json={"note": "再退"}, headers=admin)
    assert r2.status_code == 400


def test_order_filters_and_campus(client):
    """订单筛选：姓名搜索 / 校区 / 课时包 / 状态 / 时间区间。"""
    admin = _register(client, "admin", "admin")
    parent = _register(client, "parent", "parent")
    parent_uid = _uid(client, parent)
    class_id = _make_class(client, admin)
    # 校区用唯一标签，避免共享测试库中其他用例数据干扰筛选断言
    campus_hit = f"筛选校区{uuid.uuid4().hex[:6]}"
    campus_miss = f"无单校区{uuid.uuid4().hex[:6]}"
    stu = _make_student(
        client, admin, "筛选学生", 0, [class_id],
        campus=campus_hit, parent_user_id=parent_uid,
    )
    pkg = _make_package(client, admin, name="筛选包", total=20, price="2000.00")

    o = client.post(
        "/api/client/orders",
        json={"student_id": stu["id"], "package_id": pkg["id"]},
        headers=parent,
    ).json()
    client.post(f"/api/client/orders/{o['id']}/pay", headers=parent)
    client.post(f"/api/orders/{o['id']}/confirm", headers=admin)

    # 姓名搜索命中
    by_name = client.get("/api/orders", params={"keyword": "筛选学生"}, headers=admin)
    assert by_name.status_code == 200
    assert by_name.json()["total"] == 1
    assert by_name.json()["items"][0]["student_campus"] == campus_hit

    # 校区/课时包筛选命中与不命中（校区唯一 → 不受其他用例数据影响）
    by_campus = client.get("/api/orders", params={"campus": campus_hit}, headers=admin)
    assert by_campus.json()["total"] == 1
    by_campus_no = client.get("/api/orders", params={"campus": campus_miss}, headers=admin)
    assert by_campus_no.json()["total"] == 0

    by_pkg = client.get("/api/orders", params={"package_id": pkg["id"]}, headers=admin)
    assert by_pkg.json()["total"] == 1
    by_pkg_no = client.get("/api/orders", params={"package_id": str(uuid.uuid4())}, headers=admin)
    assert by_pkg_no.json()["total"] == 0

    # 状态筛选：限定本用例学员（共享测试库存在其他订单）
    confirmed = client.get(
        "/api/orders",
        params={"status": "confirmed", "keyword": "筛选学生"},
        headers=admin,
    )
    assert confirmed.json()["total"] == 1
    pending = client.get(
        "/api/orders",
        params={"status": "pending", "keyword": "筛选学生"},
        headers=admin,
    )
    assert pending.json()["total"] == 0

    # 时间区间：过去命中、未来不命中（同样限定本用例学员）
    past = client.get(
        "/api/orders",
        params={
            "keyword": "筛选学生",
            "date_from": "2026-01-01T00:00:00",
            "date_to": "2026-12-31T23:59:59",
        },
        headers=admin,
    )
    assert past.json()["total"] == 1
    future = client.get(
        "/api/orders",
        params={"keyword": "筛选学生", "date_from": "2099-01-01T00:00:00"},
        headers=admin,
    )
    assert future.json()["total"] == 0


def test_assignment_scoring_makeup_flow(client):
    """题型分值 + 达标线 + 补练作业：分值影响总分、未达标标红、补练仅定向可见。"""
    admin = _register(client, "admin", "admin")
    teacher = _register(client, "teacher", "teacher")
    parent = _register(client, "parent", "parent")
    parent_uid = _uid(client, parent)
    class_id = _make_class(client, admin)
    stu = _make_student(client, admin, "补练学生", 20, [class_id], parent_user_id=parent_uid)
    other = _make_student(client, admin, "其他学生", 20, [class_id])

    questions = [
        {
            "type": "single_choice",
            "stem": "Python 输出函数？",
            "options": ["printf", "print", "echo", "log"],
            "answer": 1,
            "analysis": "print",
            "difficulty": 2,
        },
        {
            "type": "programming",
            "stem": "add(a,b)",
            "answer": "def add(a, b):\n    return a + b",
            "analysis": "return",
            "difficulty": 3,
            "test_cases": [{"input": "1 2", "output": "3"}],
            "language": "python",
        },
    ]
    a = client.post(
        "/api/assignments",
        json={
            "title": "达标测试作业",
            "description": "基础",
            "type_scores": {"single_choice": 2, "programming": 5},
            "passing_score": 6,
            "questions": questions,
        },
        headers=teacher,
    )
    assert a.status_code == 201, a.text
    body = a.json()
    assert body["total_score"] == 7  # 2 + 5
    assignment_id = body["id"]

    pub = client.post(
        f"/api/assignments/{assignment_id}/publish",
        json={
            "class_ids": [class_id],
            "type_scores": {"single_choice": 2, "programming": 5},
            "passing_score": 6,
        },
        headers=teacher,
    )
    assert pub.status_code == 200, pub.text
    assert pub.json()["passing_score"] == 6

    # 提交（单选答对 2 分，编程满分 5 分）→ 7/7 达标
    submit = client.post(
        f"/api/client/assignments/{assignment_id}/submit?student_id={stu['id']}",
        json={"answers": {"1": 1, "2": "def add(a, b):\n    return a + b"}},
        headers=parent,
    )
    assert submit.status_code == 200, submit.text
    res = submit.json()
    assert res["submission"]["score"] == 2
    assert res["submission"]["total"] == 7
    assert res["submission"]["judge_results"]["1"]["max_score"] == 2

    subs = client.get(f"/api/assignments/{assignment_id}/submissions", headers=teacher)
    sub_id = subs.json()[0]["id"]
    grade = client.post(
        f"/api/assignments/{assignment_id}/submissions/{sub_id}/grade",
        json={"scores": {"2": 5}, "comment": "不错"},
        headers=teacher,
    )
    assert grade.status_code == 200, grade.text
    assert grade.json()["score"] == 7
    assert grade.json()["total"] == 7

    lst = client.get(f"/api/client/assignments?student_id={stu['id']}", headers=parent)
    item = lst.json()["items"][0]
    assert item["my_score"] == 7
    assert item["my_passed"] is True

    # 提交列表带达标标识 + 统计含未达标数
    subs = client.get(f"/api/assignments/{assignment_id}/submissions", headers=teacher)
    assert subs.json()[0]["passed"] is True
    stats = client.get(
        f"/api/assignments/{assignment_id}/submission-stats", headers=teacher
    )
    assert stats.json()["passing_score"] == 6
    assert stats.json()["below_pass"] == 0
    # 提交统计口径：常规班级作业=发布班级学员去重（本用例班级 2 名学员）
    assert stats.json()["total_students"] == 2
    assert stats.json()["submitted"] == 1
    assert stats.json()["not_submitted"] == 1

    # 批改模式：创建时指定 teacher_confirm，发布时可覆盖
    rm = client.post(
        "/api/assignments",
        json={
            "title": "批改模式作业",
            "review_mode": "teacher_confirm",
            "questions": [questions[0]],
        },
        headers=teacher,
    )
    assert rm.status_code == 201, rm.text
    assert rm.json()["review_mode"] == "teacher_confirm"
    rm_pub = client.post(
        f"/api/assignments/{rm.json()['id']}/publish",
        json={"class_ids": [class_id], "review_mode": "auto"},
        headers=teacher,
    )
    assert rm_pub.status_code == 200, rm_pub.text
    assert rm_pub.json()["review_mode"] == "auto"

    # 批改模式门禁：teacher_confirm 作业提交后不公布答案解析，教师批改后才公布
    tc = client.post(
        "/api/assignments",
        json={
            "title": "确认后公布作业",
            "review_mode": "teacher_confirm",
            "questions": [questions[0]],
        },
        headers=teacher,
    )
    assert tc.status_code == 201, tc.text
    tc_id = tc.json()["id"]
    pub_tc = client.post(
        f"/api/assignments/{tc_id}/publish",
        json={"class_ids": [class_id]},
        headers=teacher,
    )
    assert pub_tc.status_code == 200, pub_tc.text
    assert pub_tc.json()["review_mode"] == "teacher_confirm"
    submit_tc = client.post(
        f"/api/client/assignments/{tc_id}/submit?student_id={stu['id']}",
        json={"answers": {"1": 1}},
        headers=parent,
    )
    assert submit_tc.status_code == 200, submit_tc.text
    detail_tc = client.get(
        f"/api/client/assignments/{tc_id}?student_id={stu['id']}", headers=parent
    )
    assert detail_tc.status_code == 200, detail_tc.text
    # 提交后（未批改）：不公布参考答案/解析
    assert detail_tc.json()["questions"][0]["reference_answer"] is None
    assert detail_tc.json()["questions"][0]["reference_analysis"] is None
    # submission-stats 口径：该作业也是同一班级 2 名学员
    stats_tc = client.get(
        f"/api/assignments/{tc_id}/submission-stats", headers=teacher
    )
    assert stats_tc.json()["total_students"] == 2
    assert stats_tc.json()["submitted"] == 1
    assert stats_tc.json()["pending_review"] == 1
    # 教师批改后：公布答案解析
    subs_tc = client.get(f"/api/assignments/{tc_id}/submissions", headers=teacher)
    grade_tc = client.post(
        f"/api/assignments/{tc_id}/submissions/{subs_tc.json()[0]['id']}/grade",
        json={"scores": {}, "comment": "好"},
        headers=teacher,
    )
    assert grade_tc.status_code == 200, grade_tc.text
    detail_tc2 = client.get(
        f"/api/client/assignments/{tc_id}?student_id={stu['id']}", headers=parent
    )
    assert detail_tc2.json()["questions"][0]["reference_answer"] is not None
    assert detail_tc2.json()["questions"][0]["reference_analysis"] is not None

    # auto 模式对照：同一学员提交后直接公布答案解析
    auto = client.post(
        "/api/assignments",
        json={
            "title": "自动公布作业",
            "review_mode": "auto",
            "questions": [questions[0]],
        },
        headers=teacher,
    )
    auto_id = auto.json()["id"]
    client.post(
        f"/api/assignments/{auto_id}/publish",
        json={"class_ids": [class_id]},
        headers=teacher,
    )
    client.post(
        f"/api/client/assignments/{auto_id}/submit?student_id={stu['id']}",
        json={"answers": {"1": 1}},
        headers=parent,
    )
    detail_auto = client.get(
        f"/api/client/assignments/{auto_id}?student_id={stu['id']}", headers=parent
    )
    assert detail_auto.json()["questions"][0]["reference_answer"] is not None

    # 作业列表聚合 + 待批改筛选 + 批改中心
    lst_agg = client.get("/api/assignments", headers=teacher).json()
    by_id = {i["id"]: i for i in lst_agg["items"]}
    assert by_id[tc_id]["pending_review_count"] == 0  # 已批改，无待批改
    assert by_id[auto_id]["pending_review_count"] == 1  # 已提交未批改
    assert by_id[auto_id]["submitted_count"] == 1
    pr = client.get("/api/assignments?pending_review=true", headers=teacher).json()
    assert auto_id in {i["id"] for i in pr["items"]}
    assert tc_id not in {i["id"] for i in pr["items"]}
    center = client.get("/api/assignments/grading-center", headers=teacher).json()
    assert center["total"] >= 1
    center_ids = {i["assignment_id"] for i in center["items"]}
    assert auto_id in center_ids
    assert tc_id not in center_ids
    center_item = next(i for i in center["items"] if i["assignment_id"] == auto_id)
    assert center_item["pending_review"] == 1
    assert center_item["total_students"] == 2

    # 补练：仅指定学员可见（其他学员不可见）
    makeup = client.post(
        f"/api/assignments/{assignment_id}/makeup",
        json=[stu["id"]],
        headers=teacher,
    )
    assert makeup.status_code == 201, makeup.text
    draft = makeup.json()
    assert draft["status"] == "draft"
    assert "补练" in draft["title"]
    assert draft["target_student_ids"] == [stu["id"]]
    assert draft["passing_score"] == 6
    assert draft["type_scores"]["programming"] == 5

    # 家长（定向学员）可见补练草稿？—— 草稿不可见；发布后仅定向学员可见
    lst_all = client.get(f"/api/client/assignments?student_id={stu['id']}", headers=parent)
    assert all(d["id"] != draft["id"] for d in lst_all.json()["items"])

    pub2 = client.post(
        f"/api/assignments/{draft['id']}/publish",
        json={
            "class_ids": [class_id],
            "type_scores": draft["type_scores"],
            "passing_score": 6,
            "target_student_ids": [stu["id"]],
        },
        headers=teacher,
    )
    assert pub2.status_code == 200, pub2.text
    assert pub2.json()["status"] == "published"

    # 定向学员可见；非定向学员（家长视角创建）不可见
    lst_target = client.get(f"/api/client/assignments?student_id={stu['id']}", headers=parent)
    assert any(d["id"] == draft["id"] for d in lst_target.json()["items"])

    # 其他学生（无家长绑定，直接用学员本人视角不可行）——通过详情接口 403 验证
    r_other = client.get(
        f"/api/client/assignments/{draft['id']}?student_id={other['id']}",
        headers=parent,
    )
    assert r_other.status_code == 403
