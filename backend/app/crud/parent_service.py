"""家长客服 CRUD：家长版白名单、配额计数、会话账本读写。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeDocument
from app.models.parent_service import (
    ROLE_ASSISTANT,
    ROLE_STAFF,
    ROLE_USER,
    THREAD_CLOSED,
    THREAD_ESCALATED,
    THREAD_OPEN,
    ParentServiceMessage,
    ParentServiceThread,
)
from app.models.system_setting import SystemSetting
from app.models.user import Role, User

DEFAULT_RISK_WORDS = [
    "退费", "收费", "价格", "安全", "受伤", "事故",
    "投诉", "报警", "律师", "骨折", "过敏",
]

# 输出安全护栏：命中任一模式 → 答案作废、转人工（防模型绕过词表前置拦截）。
UNSAFE_PATTERNS = (
    "退多少钱", "退款金额", "赔偿", "赔付", "报警", "律师函", "起诉",
    "保证提分", "保证拿奖", "100%通过", "内部价", "回扣",
)

# 业务/非业务粗分类关键词（纯规则前置，LLM 只做兜底表达）
NON_BIZ_HINTS = (
    "你是谁", "你叫什么", "讲个笑话", "写作业", "代写", "作文",
    "天气", "股票", "彩票", "游戏攻略", "追星",
)


def unsafe_output(answer: str) -> str | None:
    """输出护栏：返回命中的风险片段，否则 None。"""
    t = answer or ""
    for p in UNSAFE_PATTERNS:
        if p and p in t:
            return p
    return None


def non_biz_hint(content: str) -> bool:
    """闲聊/非业务 → True（不调 RAG，直接短答，省 token + 防串味）。"""
    t = (content or "").strip()
    if not t:
        return True
    if len(t) <= 4 and t in ("你好", "在吗", "谢谢", "再见", "辛苦了"):
        return True
    return any(h in t for h in NON_BIZ_HINTS)


def parent_visible_doc_ids(db: Session) -> list[uuid.UUID]:
    """家长版白名单：ready + 启用 + 家长可见 的文档 id（家长域检索的 collected_ids）。"""
    rows = db.scalars(
        select(KnowledgeDocument.id).where(
            KnowledgeDocument.status == "ready",
            KnowledgeDocument.enabled.is_(True),
            KnowledgeDocument.visible_to_parents.is_(True),
        )
    ).all()
    return list(rows)


def get_setting(db: Session) -> SystemSetting | None:
    return db.scalars(select(SystemSetting).where(SystemSetting.id == 1)).first()


def quota_limits(db: Session) -> tuple[int, int]:
    """(匿名日限额, 家长日限额)，读单例配置，缺失用默认 3/50。"""
    s = get_setting(db)
    anon = int(getattr(s, "parent_anon_daily_limit", 3) or 3)
    parent = int(getattr(s, "parent_daily_limit", 50) or 50)
    return anon, parent


def risk_words(db: Session) -> list[str]:
    s = get_setting(db)
    raw = (getattr(s, "parent_risk_words", "") or "").strip()
    if not raw:
        return list(DEFAULT_RISK_WORDS)
    try:
        arr = json.loads(raw)
        if isinstance(arr, list) and arr:
            return [str(w).strip() for w in arr if str(w).strip()]
    except (ValueError, TypeError):
        pass
    return list(DEFAULT_RISK_WORDS)


def hit_risk_word(content: str, words: list[str]) -> str | None:
    """命中高风险词返回该词，否则 None（子串匹配，P0 规则先行）。"""
    text = content or ""
    for w in words:
        if w and w in text:
            return w
    return None


def _today_start() -> datetime:
    return datetime.combine(datetime.now().date(), time.min)


def count_today_user_messages(
    db: Session, *, parent_id: uuid.UUID | None = None, anon_key: str | None = None
) -> int:
    """当日用户已发轮次（配额口径：只计 user role 消息）。"""
    start = _today_start()
    thread_ids = select(ParentServiceThread.id).where(
        ParentServiceThread.status != THREAD_CLOSED
    )
    if parent_id is not None:
        thread_ids = thread_ids.where(ParentServiceThread.parent_id == parent_id)
    elif anon_key:
        thread_ids = thread_ids.where(ParentServiceThread.anon_key == anon_key)
    else:
        return 0
    return (
        db.scalar(
            select(func.count(ParentServiceMessage.id)).where(
                ParentServiceMessage.thread_id.in_(thread_ids),
                ParentServiceMessage.role == ROLE_USER,
                ParentServiceMessage.created_at >= start,
            )
        )
        or 0
    )


def get_or_create_thread(
    db: Session, *, parent_id: uuid.UUID | None = None,
    anon_key: str | None = None, thread_id: uuid.UUID | None = None,
) -> ParentServiceThread:
    if thread_id is not None:
        th = db.get(ParentServiceThread, thread_id)
        if th is not None and th.status != THREAD_CLOSED:
            if parent_id is not None and th.parent_id == parent_id:
                return th
            if parent_id is None and anon_key and th.anon_key == anon_key:
                return th
    stmt = select(ParentServiceThread).where(ParentServiceThread.status == THREAD_OPEN)
    if parent_id is not None:
        stmt = stmt.where(ParentServiceThread.parent_id == parent_id)
    else:
        stmt = stmt.where(ParentServiceThread.anon_key == anon_key)
    th = db.scalars(stmt.order_by(ParentServiceThread.updated_at.desc())).first()
    if th is not None:
        return th
    th = ParentServiceThread(parent_id=parent_id, anon_key=anon_key, status=THREAD_OPEN)
    if parent_id is not None:
        th.owner_teacher_id = resolve_owner_teacher(db, parent_id)
    db.add(th)
    db.commit()
    db.refresh(th)
    return th


def resolve_owner_teacher(db: Session, parent_id: uuid.UUID) -> uuid.UUID | None:
    """归属教师：家长首个在读学员的首个班级主带教师；无归属返回 None（走系统默认）。"""
    from app.models.enrollment import Student, StudentStatus

    stu = db.scalars(
        select(Student)
        .where(Student.parent_user_id == parent_id, Student.status != StudentStatus.ARCHIVED.value)
        .order_by(Student.created_at.asc())
        .limit(1)
    ).first()
    if stu is None:
        return None
    for c in stu.classes or []:
        if c.teacher_id is not None:
            return c.teacher_id
    return None


def parent_identity(db: Session, parent_id: uuid.UUID | None) -> dict:
    """家长身份聚合：名下在读学员（姓名/校区/班级/余额）+ 联系方式，供接待列表展示。

    解决"只显示一个号码不知道是谁"：教师看到的是"张三家长 · 学员李四（一校·Python启蒙班）"。
    """
    out: dict = {"students": [], "campuses": [], "phone": "", "name": ""}
    if parent_id is None:
        return out
    from app.models.enrollment import Student, StudentStatus

    owner = db.get(User, parent_id)
    if owner is not None:
        out["name"] = owner.name or ""
        out["phone"] = owner.phone or ""
    rows = db.scalars(
        select(Student)
        .where(Student.parent_user_id == parent_id, Student.status != StudentStatus.ARCHIVED.value)
        .order_by(Student.created_at.asc())
    ).all()
    for s in rows:
        classes = [{"name": c.name, "subject": c.subject} for c in (s.classes or [])]
        out["students"].append({
            "id": str(s.id), "name": s.name, "campus": s.campus or "",
            "balance": float(s.lesson_balance or 0), "classes": classes,
        })
        if s.campus and s.campus not in out["campuses"]:
            out["campuses"].append(s.campus)
    return out


def add_message(
    db: Session, *, thread_id: uuid.UUID, role: str, content: str,
    tokens: int | None = None, retrieval_diag: dict | None = None,
) -> ParentServiceMessage:
    msg = ParentServiceMessage(
        thread_id=thread_id, role=role, content=content,
        tokens=tokens, retrieval_diag=retrieval_diag,
    )
    db.add(msg)
    th = db.get(ParentServiceThread, thread_id)
    if th is not None:
        th.updated_at = datetime.now()
    db.commit()
    db.refresh(msg)
    return msg


def escalate(db: Session, thread: ParentServiceThread, *, risk_word: str | None = None) -> ParentServiceThread:
    thread.status = THREAD_ESCALATED
    if risk_word:
        thread.risk_flag = True
    db.commit()
    db.refresh(thread)
    return thread


def list_threads_for_staff(db: Session, *, limit: int = 100) -> list[ParentServiceThread]:
    """教师接待列表：escalated 置顶，其余按更新倒序。"""
    rows = db.scalars(
        select(ParentServiceThread)
        .order_by(
            ParentServiceThread.status != THREAD_ESCALATED,
            ParentServiceThread.updated_at.desc(),
        )
        .limit(limit)
    ).all()
    return list(rows)


def list_messages(db: Session, *, thread_id: uuid.UUID) -> list[ParentServiceMessage]:
    return list(
        db.scalars(
            select(ParentServiceMessage)
            .where(ParentServiceMessage.thread_id == thread_id)
            .order_by(ParentServiceMessage.created_at.asc())
        ).all()
    )


def find_or_create_parent_by_openid(db: Session, *, openid: str, nickname: str = "") -> User:
    from app.crud import user as user_crud

    user = db.scalars(select(User).where(User.wechat_openid == openid)).first()
    if user is not None:
        return user
    username = f"wx_{openid[:12]}"
    suffix = 0
    while user_crud.get_by_username(db, username):
        suffix += 1
        username = f"wx_{openid[:10]}{suffix}"
    user = User(
        role=Role.PARENT.value,
        username=username,
        name=nickname or "微信家长",
        password_hash="!",
        wechat_openid=openid,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


__all__ = [
    "DEFAULT_RISK_WORDS",
    "add_message",
    "count_today_user_messages",
    "escalate",
    "find_or_create_parent_by_openid",
    "get_or_create_thread",
    "get_setting",
    "hit_risk_word",
    "list_messages",
    "list_threads_for_staff",
    "non_biz_hint",
    "parent_identity",
    "parent_visible_doc_ids",
    "quota_limits",
    "resolve_owner_teacher",
    "risk_words",
    "unsafe_output",
]
