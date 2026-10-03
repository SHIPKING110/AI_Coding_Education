"""邀约编辑/删除 + 流失自动清档。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

TEST_DB_NAME = "child_code_test_invedit"


@pytest.fixture()
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


def test_edit_delete_and_lost_cleanup(client):
    admin, _ = _register(client, "admin", "ie-admin")
    teacher, _ = _register(client, "teacher", "ie-teacher")

    inv = client.post(
        "/api/trials/invitations",
        json={"parent_name": "P", "student_name": "S1", "remark": "old"},
        headers=teacher,
    ).json()

    # 编辑
    upd = client.patch(
        f"/api/trials/invitations/{inv['id']}",
        json={"student_name": "S2", "parent_phone": "13800000000", "remark": "new"},
        headers=teacher,
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["student_name"] == "S2"
    assert upd.json()["remark"] == "new"

    # 建体验学员后标记流失 → 学员档案自动删除，邀约保留 lost
    ts = client.post(f"/api/trials/invitations/{inv['id']}/trial-student", headers=teacher)
    assert ts.status_code == 201, ts.text
    sid = ts.json()["id"]
    lost = client.patch(
        f"/api/trials/students/{sid}/trial-status",
        json={"trial_status": "lost"},
        headers=admin,
    )
    assert lost.status_code == 200, lost.text
    assert lost.json().get("deleted_student") is True
    gone = client.get(f"/api/students/{sid}", headers=admin)
    assert gone.status_code == 404
    invs = client.get("/api/trials/invitations", headers=admin).json()
    assert [i for i in invs["items"] if i["id"] == inv["id"]][0]["status"] == "lost"

    # 删除邀约（连带无学员）成功
    d = client.delete(f"/api/trials/invitations/{inv['id']}", headers=admin)
    assert d.status_code == 200, d.text

    # 删除带体验中学员的邀约 → 级联清档
    inv2 = client.post(
        "/api/trials/invitations",
        json={"parent_name": "P", "student_name": "S3"},
        headers=teacher,
    ).json()
    sid2 = client.post(f"/api/trials/invitations/{inv2['id']}/trial-student", headers=teacher).json()["id"]
    d2 = client.delete(f"/api/trials/invitations/{inv2['id']}", headers=admin)
    assert d2.status_code == 200, d2.text
    assert d2.json()["cleaned_student"] is True
    assert client.get(f"/api/students/{sid2}", headers=admin).status_code == 404

    # 已报名转正的邀约不可删
    inv3 = client.post(
        "/api/trials/invitations",
        json={"parent_name": "P", "student_name": "S4"},
        headers=teacher,
    ).json()
    sid3 = client.post(f"/api/trials/invitations/{inv3['id']}/trial-student", headers=teacher).json()["id"]
    ok = client.patch(
        f"/api/trials/students/{sid3}/trial-status",
        json={"trial_status": "signed"},
        headers=admin,
    )
    assert ok.status_code == 200
    d3 = client.delete(f"/api/trials/invitations/{inv3['id']}", headers=admin)
    assert d3.status_code == 400
