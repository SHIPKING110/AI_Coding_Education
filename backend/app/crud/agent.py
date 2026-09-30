"""Agent 工作台 CRUD：会话 / 消息 / 记忆 / 摘要。"""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.agent import AgentConversation, AgentConversationSummary, AgentMemory, AgentMessage


def create_conversation(
    db: Session, *, owner_id, agent_id: str, context_ref: dict, title: str = "新的对话",
    rag_enabled: bool = False,
) -> AgentConversation:
    conv = AgentConversation(
        owner_id=owner_id, agent_id=agent_id, context_ref=context_ref or {},
        title=title or "新的对话", rag_enabled=rag_enabled,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def list_conversations(db: Session, *, owner_id) -> list[AgentConversation]:
    stmt = (
        select(AgentConversation)
        .where(AgentConversation.owner_id == owner_id)
        .order_by(desc(AgentConversation.pinned), desc(AgentConversation.updated_at))
    )
    return list(db.scalars(stmt).all())


def get_conversation(db: Session, *, conv_id, owner_id) -> AgentConversation | None:
    stmt = select(AgentConversation).where(AgentConversation.id == conv_id, AgentConversation.owner_id == owner_id)
    return db.scalars(stmt).first()


def get_conversation_by_share(db: Session, *, token: str) -> AgentConversation | None:
    """按分享令牌读取（无需登录，只读分享页使用）。"""
    stmt = select(AgentConversation).where(AgentConversation.share_token == token)
    return db.scalars(stmt).first()


def update_conversation(db: Session, conv: AgentConversation, **fields) -> AgentConversation:
    for k, v in fields.items():
        if hasattr(conv, k) and v is not None:
            setattr(conv, k, v)
    db.commit()
    db.refresh(conv)
    return conv


def delete_conversation(db: Session, conv: AgentConversation) -> None:
    db.delete(conv)
    db.commit()


def add_message(
    db: Session, *, conversation_id, role: str, content: str,
    citations: dict | None = None, options: list | None = None, spec: dict | None = None,
) -> AgentMessage:
    msg = AgentMessage(
        conversation_id=conversation_id, role=role, content=content,
        citations=citations, options=options, spec=spec,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def list_messages(db: Session, *, conversation_id, limit: int = 200) -> list[AgentMessage]:
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.conversation_id == conversation_id)
        .order_by(AgentMessage.created_at)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def recent_messages(db: Session, *, conversation_id, limit: int = 10) -> list[AgentMessage]:
    """短期记忆窗口：最近 N 轮（user+assistant 算 2 条）。"""
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.conversation_id == conversation_id)
        .order_by(desc(AgentMessage.created_at))
        .limit(limit * 2)
    )
    return list(reversed(db.scalars(stmt).all()))


def get_summary(db: Session, *, conversation_id) -> AgentConversationSummary | None:
    stmt = select(AgentConversationSummary).where(AgentConversationSummary.conversation_id == conversation_id)
    return db.scalars(stmt).first()


def upsert_summary(db: Session, *, conversation_id, summary: str) -> AgentConversationSummary:
    row = get_summary(db, conversation_id=conversation_id)
    if row is None:
        row = AgentConversationSummary(conversation_id=conversation_id, summary=summary)
        db.add(row)
    else:
        row.summary = summary
    db.commit()
    db.refresh(row)
    return row


def list_memories(db: Session, *, owner_id, agent_id: str) -> list[AgentMemory]:
    stmt = select(AgentMemory).where(AgentMemory.owner_id == owner_id, AgentMemory.agent_id == agent_id)
    return list(db.scalars(stmt).all())


def upsert_memory(db: Session, *, owner_id, agent_id: str, key: str, value: str) -> AgentMemory:
    stmt = select(AgentMemory).where(
        AgentMemory.owner_id == owner_id, AgentMemory.agent_id == agent_id, AgentMemory.key == key
    )
    row = db.scalars(stmt).first()
    if row is None:
        row = AgentMemory(owner_id=owner_id, agent_id=agent_id, key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    db.refresh(row)
    return row


def delete_memory(db: Session, *, memory_id, owner_id) -> bool:
    stmt = select(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.owner_id == owner_id)
    row = db.scalars(stmt).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def touch_conversation(db: Session, conv: AgentConversation) -> None:
    from sqlalchemy import func as _func

    conv.updated_at = _func.now()
    db.commit()


__all__ = [
    "create_conversation",
    "list_conversations",
    "get_conversation",
    "update_conversation",
    "delete_conversation",
    "add_message",
    "list_messages",
    "recent_messages",
    "get_summary",
    "upsert_summary",
    "list_memories",
    "upsert_memory",
    "delete_memory",
    "touch_conversation",
]
