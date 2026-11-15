"""SCHEMA_ENSURE_MODE=verify 只读校验回归（WS1-1.3）。

口径：verify 只报告差异、绝不执行 DDL；auto 模式行为由既有全量用例覆盖。
"""

import pytest
from sqlalchemy import create_engine, text

import app.models  # noqa: F401
from app.core.database import Base
from app.core.schema_ensure import verify_business_schema

TEST_DB_NAME = "child_code_schema_verify_test"


@pytest.fixture(scope="module")
def engine():
    from app.core.config import get_settings

    base_url = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()
    eng = create_engine(base_url + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
    admin_engine.dispose()


def test_verify_clean_schema_has_no_issues(engine):
    assert verify_business_schema(engine) == []


def test_verify_detects_missing_table_without_ddl(engine):
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE agent_eval_results"))
        conn.execute(text("DROP TABLE agent_eval_runs"))
        conn.execute(text("DROP TABLE agent_eval_cases"))
        conn.execute(text("DROP TABLE agent_eval_sets"))
    issues = verify_business_schema(engine)
    assert any("agent_eval_sets" in i for i in issues)
    # 只读：表依然缺失（未被自动重建）
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass('public.agent_eval_sets')")
        ).scalar()
    assert exists is None


def test_verify_detects_missing_column(engine):
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE notifications DROP COLUMN IF EXISTS title"))
    issues = verify_business_schema(engine)
    assert any("notifications" in i and "title" in i for i in issues)
