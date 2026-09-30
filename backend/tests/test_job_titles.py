"""职务标签与职务预设：新建/换职务自动套用预设权限；一键应用。"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models.user import User

TEST_DB_NAME = "child_code_test_jobtitle"


def _engine():
    from app.core.config import get_settings

    base_url = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()
    engine = create_engine(base_url + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def client():
    import app.core.security as sec

    engine = _engine()
    Session = sessionmaker(bind=engine)
    with Session() as s:
        admin = User(id=uuid.uuid4(), role="admin", username=f"a{uuid.uuid4().hex[:5]}", name="管", password_hash="x")
        t = User(id=uuid.uuid4(), role="teacher", username=f"t{uuid.uuid4().hex[:5]}", name="王", password_hash="x")
        s.add_all([admin, t])
        s.commit()
        ids = {"admin": admin.id, "t": t.id}

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    tokens = {k: sec.create_access_token(str(v)) for k, v in ids.items()}
    try:
        yield TestClient(app), ids, tokens
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _h(tokens, who):
    return {"Authorization": f"Bearer {tokens[who]}"}


def test_job_title_crud_and_apply(client):
    c, ids, tokens = client
    # 新建职务预设：助教（关掉新增学员与删班）
    r = c.post(
        "/api/permissions/job-titles",
        headers=_h(tokens, "admin"),
        json={"name": "助教", "permissions": {"student_create": False, "class_delete": False}},
    )
    assert r.status_code == 201, r.text
    # 一键应用到教师：职务写入 + 权限套用
    r = c.post(
        f"/api/permissions/teachers/{ids['t']}/apply-title",
        headers=_h(tokens, "admin"),
        json={"title": "助教"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["permissions"]["student_create"] is False
    assert r.json()["permissions"]["class_delete"] is False
    # 教师 title 落库
    r = c.get(f"/api/auth/teachers/{ids['t']}", headers=_h(tokens, "admin"))
    assert r.json()["title"] == "助教"
    # 被收权后新建学员 403
    r = c.post("/api/students", headers=_h(tokens, "t"), json={"name": "小黑"})
    assert r.status_code == 403, r.text


def test_change_title_via_update_applies_preset(client):
    c, ids, tokens = client
    c.post(
        "/api/permissions/job-titles",
        headers=_h(tokens, "admin"),
        json={"name": "主教", "permissions": {"student_create": True}},
    )
    # 编辑教师职务 → 自动套用
    r = c.patch(
        f"/api/auth/teachers/{ids['t']}",
        headers=_h(tokens, "admin"),
        json={"title": "主教"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "主教"
    # 未知职务名：职务照写，权限不动（不报错）
    r = c.patch(
        f"/api/auth/teachers/{ids['t']}",
        headers=_h(tokens, "admin"),
        json={"title": "自定义职务"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "自定义职务"
