"""检索模型配置 CRUD 单元测试（WS3 覆盖补齐）。

覆盖 app/crud/retrieval_config.py：系统 Embedding 单例 upsert、密钥加密存储与
resolve 逻辑（remote/local/缺参拒绝）、指纹稳定性、Rerank（系统家长 + 教师级）、
删除。

注意：secretbox 依赖 SECRET_KEY，测试环境用 config 默认值（dev/test 不强制校验）。
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.database import Base
from app.crud import retrieval_config as rc
from app.models.retrieval_config import PROVIDER_LOCAL, PROVIDER_REMOTE

TEST_DB_NAME = "child_code_retrieval_cfg_test"


@pytest.fixture(scope="module")
def session_factory():
    from app.core.config import get_settings

    base_url = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()
    engine = create_engine(base_url + f"/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()
    admin_engine = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
    admin_engine.dispose()


@pytest.fixture()
def db(session_factory):
    s = session_factory()
    yield s
    s.close()


def test_system_embedding_upsert_singleton_and_key_encrypted(db):
    row = rc.upsert_system_embedding(
        db,
        provider=PROVIDER_REMOTE,
        base_url="https://api.example.com/",
        api_key="sk-secret-123",
        model="text-embedding-v3",
    )
    assert rc.get_system_embedding(db).id == row.id
    # 密钥加密存储，不回明文
    assert row.api_key_enc
    assert "sk-secret-123" not in row.api_key_enc
    # base_url 规范化去尾斜杠
    assert not row.base_url.endswith("/")

    # 再次 upsert 仍为单例，字段更新
    again = rc.upsert_system_embedding(
        db,
        provider=PROVIDER_REMOTE,
        base_url="https://api2.example.com/v1",
        api_key=None,
        model="text-embedding-v3",
    )
    assert again.id == row.id
    assert again.base_url == "https://api2.example.com/v1"
    # api_key 传空表示保留旧密钥
    resolved = rc.resolve_embedding(db)
    assert resolved is not None
    assert resolved.api_key == "sk-secret-123"


def test_resolve_embedding_remote_requires_key_and_url(db):
    rc.delete_system_embedding(db)
    assert rc.resolve_embedding(db) is None
    # 远端模式只强制要求 api_key（base_url 允许空，走 SDK 默认端点）
    rc.upsert_system_embedding(db, provider=PROVIDER_REMOTE, base_url="", api_key="k", model="m")
    resolved = rc.resolve_embedding(db)
    assert resolved is not None and resolved.base_url == "" and resolved.api_key == "k"

    # enabled=False 时拒绝
    rc.upsert_system_embedding(
        db, provider=PROVIDER_REMOTE, base_url="https://x/v1", api_key="k", model="m", enabled=False
    )
    assert rc.resolve_embedding(db) is None
    rc.delete_system_embedding(db)


def test_resolve_embedding_local_requires_model_path(db):
    rc.upsert_system_embedding(
        db, provider=PROVIDER_LOCAL, base_url="ignored", api_key=None, model="bge-m3", model_path=""
    )
    assert rc.resolve_embedding(db) is None  # 本地模式缺 model_path 拒绝

    rc.upsert_system_embedding(
        db, provider=PROVIDER_LOCAL, base_url="", api_key=None, model="bge-m3", model_path="/models/bge-m3"
    )
    resolved = rc.resolve_embedding(db)
    assert resolved is not None
    assert resolved.model_path == "/models/bge-m3"
    assert resolved.api_key is None
    rc.delete_system_embedding(db)


def test_embedding_fingerprint_stability(db):
    rc.upsert_system_embedding(
        db, provider=PROVIDER_REMOTE, base_url="https://api.example.com/v1", api_key="k", model="m1"
    )
    f1 = rc.resolve_embedding(db).fingerprint()
    # base_url 尾斜杠不影响指纹；换模型必须变化
    rc.upsert_system_embedding(
        db, provider=PROVIDER_REMOTE, base_url="https://api.example.com/v1/", api_key="k", model="m1"
    )
    assert rc.resolve_embedding(db).fingerprint() == f1
    rc.upsert_system_embedding(
        db, provider=PROVIDER_REMOTE, base_url="https://api.example.com/v1", api_key="k", model="m2"
    )
    assert rc.resolve_embedding(db).fingerprint() != f1
    rc.delete_system_embedding(db)


def test_parent_embedding_and_rerank_independent(db):
    rc.upsert_system_parent_embedding(
        db, provider=PROVIDER_REMOTE, base_url="https://p/v1", api_key="pk", model="pe"
    )
    assert rc.resolve_parent_embedding(db) is not None
    # 系统级 embedding 与家长级互不影响
    assert rc.get_system_embedding(db) is None

    rc.upsert_system_parent_rerank(
        db, provider=PROVIDER_REMOTE, base_url="https://p/v1", api_key="pk", model="pr"
    )
    rr = rc.resolve_parent_rerank(db)
    assert rr is not None and rr.model == "pr"

    rc.delete_system_parent_rerank(db)
    assert rc.resolve_parent_rerank(db) is None
    rc.delete_system_parent_embedding(db)
    assert rc.resolve_parent_embedding(db) is None


def test_teacher_rerank_crud(db, session_factory):
    import uuid as _uuid

    from app.models.user import Role, User, UserStatus

    owner = User(
        username=f"u-{_uuid.uuid4().hex[:8]}", name="师", role=Role.TEACHER,
        status=UserStatus.ACTIVE, password_hash="x",
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)

    row = rc.upsert_rerank(
        db, owner_id=owner.id, provider=PROVIDER_REMOTE,
        base_url="https://t/v1", api_key="tk", model="tr",
    )
    assert rc.get_rerank(db, owner_id=owner.id).id == row.id
    resolved = rc.resolve_rerank(db, owner_id=owner.id)
    assert resolved is not None and resolved.api_key == "tk"

    rc.delete_rerank(db, owner_id=owner.id)
    assert rc.get_rerank(db, owner_id=owner.id) is None
    assert rc.resolve_rerank(db, owner_id=owner.id) is None
