"""家长客服 P0 单测：高风险词命中、家长版白名单隔离、配额计数。

- hit_risk_word：纯函数，无 DB。
- 白名单隔离：parent_visible_doc_ids 只返回 ready+启用+家长可见。
- 配额：count_today_user_messages 按日计 user 消息；超限判定逻辑在路由层（429），此处验计数口径。
"""

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base

TEST_DB_NAME = "child_code_test_parent"


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
    # 确保所有模型都已注册到 metadata（否则 create_all 缺表）
    import app.models.knowledge  # noqa: F401
    import app.models.parent_service  # noqa: F401
    import app.models.system_setting  # noqa: F401
    import app.models.user  # noqa: F401

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


def _mk_user(db, username="owner1"):
    from app.models.user import User

    u = db.query(User).filter(User.username == username).first()
    if u is None:
        u = User(role="admin", username=username, name=username, password_hash="!")
        db.add(u)
        db.commit()
        db.refresh(u)
    return u


def _mk_doc(db, title, *, status="ready", enabled=True, visible=False, owner_id=None):
    from app.models.knowledge import KnowledgeDocument

    if owner_id is None:
        owner_id = _mk_user(db).id
    doc = KnowledgeDocument(
        owner_id=owner_id, title=title, description="t",
        file_name="t.md", file_path="/tmp/t.md",
        status=status, enabled=enabled, visible_to_parents=visible,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_hit_risk_word():
    from app.crud import parent_service as ps

    words = ["退费", "安全"]
    assert ps.hit_risk_word("我想退费怎么办", words) == "退费"
    assert ps.hit_risk_word("课程表怎么查", words) is None
    assert ps.hit_risk_word("", words) is None


def test_unsafe_output_guard():
    from app.crud import parent_service as ps

    assert ps.unsafe_output("退多少钱能说一下吗") == "退多少钱"
    assert ps.unsafe_output("课程安排是周六上午") is None
    assert ps.unsafe_output("") is None


def test_non_biz_hint():
    from app.crud import parent_service as ps

    assert ps.non_biz_hint("你好") is True
    assert ps.non_biz_hint("讲个笑话") is True
    assert ps.non_biz_hint("怎么请假") is False
    assert ps.non_biz_hint("课时还剩多少") is False


def test_pick_tool_routing():
    from app.services import parent_tools as pt

    assert pt.pick_tool("课时还剩多少") == "balance"
    assert pt.pick_tool("这周有什么课") == "schedule"
    assert pt.pick_tool("小明上过哪些课") == "history"
    assert pt.pick_tool("上了几次课") == "history"
    assert pt.pick_tool("老师反馈说了啥") == "feedbacks"
    assert pt.pick_tool("怎么请假") is None


def test_answer_numbers_safe():
    from app.services import parent_tools as pt

    ok_result = {"students": [{"balance": 12.5}]}
    assert pt.answer_numbers_safe("剩余 12.5 课时", ok_result) is True
    assert pt.answer_numbers_safe("剩余 99.9 课时", ok_result) is False
    assert pt.answer_numbers_safe("未来7天有3节课", ok_result) is True  # 无小数不拦截


def test_intent_capability_smalltalk_unknown():
    from app.services import parent_intent as pi

    assert pi.classify("你有哪些服务")["intent"] == pi.CAPABILITY
    assert pi.classify("你能做什么")["intent"] == pi.CAPABILITY
    assert pi.classify("你是谁")["intent"] == pi.CAPABILITY
    assert pi.classify("你好")["intent"] == pi.SMALLTALK
    assert pi.classify("谢谢！")["intent"] == pi.SMALLTALK
    assert pi.classify("讲个笑话")["intent"] == pi.UNKNOWN
    assert pi.classify("帮我写作业")["intent"] == pi.UNKNOWN


def test_intent_tool_before_menu():
    from app.services import parent_intent as pi

    menu = "我可以帮您：\n1) 查课时余额\n2) 查未来 7 天课表\n3) 查上课历史"
    # 直接数据查询优先于菜单跟进
    r = pi.classify("课时还剩多少", last_assistant=menu, last_user="你有哪些服务")
    assert r["intent"] == pi.TOOL and r["tool"] == "balance"


def test_intent_menu_followup():
    from app.services import parent_intent as pi

    menu = "我可以帮您：\n1) 查课时余额\n2) 查未来 7 天课表\n3) 查上课历史与出勤\n5) 课程/请假/活动等政策问答"
    r = pi.classify(
        "请假与补课流程、校区活动通知",
        last_assistant=menu, last_user="你有哪些服务",
    )
    assert r["intent"] == pi.MENU_FOLLOWUP
    assert r["retrieval_query"] == "你有哪些服务 请假与补课流程、校区活动通知"

def test_intent_policy_default():
    from app.services import parent_intent as pi

    assert pi.classify("怎么请假")["intent"] == pi.POLICY
    assert pi.looks_like_menu("我可以帮您：\n1) 查课时余额\n2) 查课表") is True
    assert pi.looks_like_menu("请假需提前一天在群里说") is False


def test_risk_words_default_when_empty(session_factory):
    from app.crud import parent_service as ps

    db = session_factory()
    try:
        words = ps.risk_words(db)
        assert "退费" in words and "安全" in words
    finally:
        db.close()


def test_parent_visible_only_whitelisted(session_factory):
    from app.crud import parent_service as ps

    db = session_factory()
    try:
        pub = _mk_doc(db, "家长版-请假流程", visible=True)
        _mk_doc(db, "内部-教师考勤", visible=False)
        _mk_doc(db, "未就绪-家长版", status="indexing", visible=True)
        ids = {str(i) for i in ps.parent_visible_doc_ids(db)}
        assert str(pub.id) in ids
        assert len(ids) == 1  # 内部文档与未就绪文档均被隔离
    finally:
        db.close()


def test_quota_counts_only_user_messages(session_factory):
    from app.crud import parent_service as ps

    db = session_factory()
    try:
        th = ps.get_or_create_thread(db, anon_key="test-anon-1")
        ps.add_message(db, thread_id=th.id, role="user", content="q1")
        ps.add_message(db, thread_id=th.id, role="assistant", content="a1")
        assert ps.count_today_user_messages(db, anon_key="test-anon-1") == 1
        ps.add_message(db, thread_id=th.id, role="user", content="q2")
        assert ps.count_today_user_messages(db, anon_key="test-anon-1") == 2
    finally:
        db.close()


def test_escalate_sets_status(session_factory):
    from app.crud import parent_service as ps
    from app.models.parent_service import THREAD_ESCALATED

    db = session_factory()
    try:
        th = ps.get_or_create_thread(db, anon_key="test-anon-2")
        ps.escalate(db, th, risk_word="退费")
        assert th.status == THREAD_ESCALATED
        assert th.risk_flag is True
    finally:
        db.close()
