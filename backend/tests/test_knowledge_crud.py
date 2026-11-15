"""RAG 知识库 CRUD 单元测试（WS3 覆盖补齐）。

覆盖 app/crud/knowledge.py：文档生命周期（建/改/删/索引标记）、可见性与检索范围、
收录（collect/uncollect）幂等、广场与家长白名单过滤。
"""

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.database import Base
from app.crud import knowledge as kb
from app.models.user import Role, User, UserStatus

TEST_DB_NAME = "child_code_kb_crud_test"


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


def _user(db, name: str) -> User:
    u = User(
        username=f"u-{uuid.uuid4().hex[:8]}",
        name=name,
        role=Role.TEACHER,
        status=UserStatus.ACTIVE,
        password_hash="x",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_create_document_defaults_and_trim(db):
    owner = _user(db, "李老师")
    doc = kb.create_document(db, owner_id=owner.id, title="   ", description="")
    assert doc.title == "未命名文档"
    assert doc.status == "pending"
    assert doc.enabled is True
    assert doc.visibility == "private"

    doc2 = kb.create_document(db, owner_id=owner.id, title="  JavaScript 入门  ")
    assert doc2.title == "JavaScript 入门"


def test_get_document_owner_scoped(db):
    owner = _user(db, "A")
    other = _user(db, "B")
    doc = kb.create_document(db, owner_id=owner.id, title="私有")

    assert kb.get_document(db, doc_id=doc.id) is not None
    assert kb.get_document(db, doc_id=doc.id, owner_id=owner.id) is not None
    # 别人按 owner 过滤查不到，但 get_document_any 可以（管理/同步场景）
    assert kb.get_document(db, doc_id=doc.id, owner_id=other.id) is None
    assert kb.get_document_any(db, doc_id=doc.id) is not None


def test_list_my_documents_only_mine(db):
    owner = _user(db, "C")
    other = _user(db, "D")
    kb.create_document(db, owner_id=owner.id, title="一")
    kb.create_document(db, owner_id=owner.id, title="二")
    kb.create_document(db, owner_id=other.id, title="别人的")

    mine = kb.list_my_documents(db, owner_id=owner.id)
    assert len(mine) == 2
    assert {d.title for d in mine} == {"一", "二"}


def test_plaza_only_ready_and_visibility(db):
    owner = _user(db, "E")
    plaza = kb.create_document(db, owner_id=owner.id, title="广场")
    kb.set_visibility(db, plaza, "plaza")
    # 未就绪：不应出现在广场
    assert all(d.id != plaza.id for d in kb.list_plaza(db))
    kb.mark_indexed(db, doc_id=plaza.id, chunk_count=3)
    assert any(d.id == plaza.id for d in kb.list_plaza(db))


def test_enabled_toggle_and_owned_ready_scope(db):
    owner = _user(db, "F")
    doc = kb.create_document(db, owner_id=owner.id, title="检索源")
    kb.mark_indexed(db, doc_id=doc.id, chunk_count=2)
    assert [i for i in kb.owned_ready_doc_ids(db, user_id=owner.id)] == [doc.id]

    kb.set_enabled(db, doc, False)
    assert kb.owned_ready_doc_ids(db, user_id=owner.id) == []


def test_mark_indexed_success_and_failure(db):
    owner = _user(db, "G")
    doc = kb.create_document(db, owner_id=owner.id, title="索引")
    kb.mark_indexed(db, doc_id=doc.id, chunk_count=5)
    fresh = kb.get_document_any(db, doc_id=doc.id)
    assert fresh is not None and fresh.status == "ready" and fresh.chunk_count == 5

    kb.mark_indexed(db, doc_id=doc.id, chunk_count=0, error="源文件缺失")
    fresh = kb.get_document_any(db, doc_id=doc.id)
    assert fresh is not None and fresh.status == "failed" and fresh.error == "源文件缺失"

    # 不存在的 id 静默返回
    kb.mark_indexed(db, doc_id=uuid.uuid4(), chunk_count=1)


def test_parent_visible_whitelist(db):
    owner = _user(db, "H")
    doc = kb.create_document(db, owner_id=owner.id, title="家长政策")
    kb.mark_indexed(db, doc_id=doc.id, chunk_count=1)
    assert all(d.id != doc.id for d in kb.list_parent_visible_documents(db))

    doc.visible_to_parents = True
    db.commit()
    assert any(d.id == doc.id for d in kb.list_parent_visible_documents(db))


def test_collect_uncollect_idempotent(db):
    owner = _user(db, "I")
    user = _user(db, "J")
    doc = kb.create_document(db, owner_id=owner.id, title="收藏目标")
    kb.mark_indexed(db, doc_id=doc.id, chunk_count=1)

    assert kb.is_collected(db, user_id=user.id, doc_id=doc.id) is False
    kb.collect(db, user_id=user.id, doc_id=doc.id)
    assert kb.is_collected(db, user_id=user.id, doc_id=doc.id) is True
    assert kb.collected_doc_ids(db, user_id=user.id) == [doc.id]

    assert kb.uncollect(db, user_id=user.id, doc_id=doc.id) is True
    assert kb.uncollect(db, user_id=user.id, doc_id=doc.id) is False
    assert kb.collected_doc_ids(db, user_id=user.id) == []


def test_delete_document(db):
    owner = _user(db, "K")
    doc = kb.create_document(db, owner_id=owner.id, title="待删")
    kb.delete_document(db, doc)
    assert kb.get_document_any(db, doc_id=doc.id) is None
