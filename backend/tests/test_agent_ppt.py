"""验证工作台 build-ppt：数据页真实填充 + 页数与文件一致。"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.main import app

TEST_DB_NAME = "child_code_test"


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


def test_build_ppt_with_real_data():
    from app.api import deps
    from app.models.report import Report

    engine = _engine()
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    try:
        client = TestClient(app)
        r = client.post(
            "/api/auth/register",
            json={"role": "teacher", "username": f"ppt-{uuid.uuid4().hex[:8]}", "password": "123456", "name": "t"},
        )
        assert r.status_code == 201, r.text
        login = client.post(
            "/api/auth/login",
            json={"username": r.json()["username"], "password": "123456"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        # 建一份带统计快照的季度报告
        with TestSession() as s:
            me = s.query(__import__("app.models.user", fromlist=["User"]).User).order_by(
                __import__("app.models.user", fromlist=["User"]).User.created_at.desc()
            ).first()
            rep = Report(
                teacher_id=me.id, type="quarterly", title="Q3 总结",
                period_start="2026-07-01T00:00:00", period_end="2026-09-30T23:59:59",
                content={"summary": "x"},
                stats={"current_students": 3, "schedules": 36, "attended": 95,
                       "leave": 5, "attendance_rate": 0.95, "consumed_lessons": 190,
                       "achievement_rate": 0.9, "new_students": 1},
            )
            s.add(rep)
            s.commit()
            rep_id = str(rep.id)
        conv = client.post(
            "/api/agents/conversations",
            json={"agent_id": "report_ppt", "context_ref": {"kind": "report", "id": rep_id, "title": "Q3"},
                  "title": "Q3 总结"},
            headers=headers,
        ).json()
        outline = [
            {"id": "p1", "title": "封面", "kind": "prose", "note": "2026 Q3 教学总结"},
            {"id": "p2", "title": "核心指标", "kind": "stats"},
            {"id": "p3", "title": "数据总览", "kind": "table"},
            {"id": "p4", "title": "趋势", "kind": "bar"},
            {"id": "p5", "title": "结论", "kind": "bullets"},
        ]
        sections = [{"id": "p5", "title": "结论", "body": "继续保持\n加强 outreach"}]
        out = client.post(
            f"/api/agents/conversations/{conv['id']}/build-ppt",
            json={"title": "Q3 总结", "theme": "brand", "outline": outline, "sections": sections},
            headers=headers,
        )
        assert out.status_code == 200, out.text
        data = out.json()
        print("PAGES:", data["pages"], "URL:", data["ppt_url"])
        # 文件真实页数必须与返回一致，且数据页真实存在（不止封面+结尾）
        from pathlib import Path

        from pptx import Presentation

        from app.core.config import get_settings

        path = Path(get_settings().UPLOAD_DIR) / data["ppt_url"]
        n = len(Presentation(str(path)).slides)
        assert n == data["pages"], (n, data["pages"])
        assert n >= 7, n  # 封面+数据总览+趋势+5正文+结尾（自动页另计）
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
