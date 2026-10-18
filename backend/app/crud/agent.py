"""Agent 工作台 CRUD：会话 / 消息 / 记忆 / 摘要。"""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.agent import (
    AgentConversation,
    AgentConversationSummary,
    AgentMemory,
    AgentMessage,
    AgentWorkingMemory,
)


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


# —— 记忆检索：相关度 + 强度 + 时间衰减 的综合排序（替代全量注入）——

_STOP = set("的了和是我你他她它们在有就不都与及或对为以于被把将从到")


def _mem_terms(text: str) -> set[str]:
    import re as _re

    t = (text or "").lower()
    out = set(_re.findall(r"[a-z0-9_]+", t))
    cjk = _re.sub(r"[^\u4e00-\u9fff]+", "", t)
    for i in range(len(cjk) - 1):
        bg = cjk[i : i + 2]
        if not (set(bg) & _STOP):
            out.add(bg)
    return {x for x in out if len(x) >= 2}


def _recency_factor(last_used, updated_at) -> float:
    """时间衰减：越久未命中/更新，得分越低（半衰约 30 天，下限 0.5）。"""
    import time as _time

    ref = last_used or updated_at
    if ref is None:
        return 0.7
    try:
        ref_ts = ref.timestamp()
    except Exception:
        return 0.7
    days = max(0.0, (_time.time() - ref_ts) / 86400.0)
    return max(0.5, 0.5 ** (days / 30.0))


def rank_memories(
    db: Session, *, owner_id, agent_id: str, query: str = "", top_k: int = 8
) -> list[dict]:
    """记忆检索：按「相关度 + 强度 + 新近度」排序，返回 top_k（含强度分层）。

    - 相关度：记忆 key/value 与本轮 query 的词元重合度（无 query 时为 0）；
    - 强度：importance/confidence/use_count 融合；
    - 新近度：last_used_at/updated_at 的时间衰减；
    返回每条含 strength 分层（strong/weak）供优先级裁决使用。
    """
    rows = list_memories(db, owner_id=owner_id, agent_id=agent_id)
    if not rows:
        return []
    qterms = _mem_terms(query) if query else set()
    scored: list[dict] = []
    for r in rows:
        blob = f"{r.key} {r.value}".lower()
        rel = 0.0
        if qterms:
            terms = _mem_terms(blob)
            rel = len(qterms & terms) / max(len(qterms), 1)
        strength = (
            0.5 * float(r.importance or 0.5)
            + 0.3 * float(r.confidence or 0.5)
            + 0.2 * min(1.0, float(r.use_count or 0) / 5.0)
        )
        recency = _recency_factor(r.last_used_at, r.updated_at)
        score = 0.5 * rel + 0.35 * strength + 0.15 * recency
        scored.append({
            "id": r.id, "key": r.key, "value": r.value, "category": r.category,
            "importance": float(r.importance or 0.5), "confidence": float(r.confidence or 0.5),
            "use_count": int(r.use_count or 0), "rel": rel, "strength": strength, "score": score,
        })
    # 强记忆（高强度且被反复使用）即使不相关也优先保底注入少量
    scored.sort(key=lambda x: x["score"], reverse=True)
    picked = scored[:top_k]
    # 强度分层：>=0.6 为强偏好
    for s in picked:
        s["strength_tier"] = "strong" if s["strength"] >= 0.6 else "weak"
    return picked


def reinforce_memories(db: Session, *, memory_ids: list) -> int:
    """强化：本轮被召回/采用的记忆 use_count+1、刷新 last_used_at、importance 微升。"""
    from datetime import datetime, timezone as _tz

    if not memory_ids:
        return 0
    rows = db.scalars(select(AgentMemory).where(AgentMemory.id.in_(memory_ids))).all()
    now = datetime.now(_tz.utc)
    for r in rows:
        r.use_count = int(r.use_count or 0) + 1
        r.last_used_at = now
        r.importance = min(1.0, float(r.importance or 0.5) + 0.02)
    db.commit()
    return len(rows)


def decay_memories(
    db: Session, *, owner_id, agent_id: str, min_keep: int = 5, max_keep: int = 60
) -> dict:
    """压缩/删除：按时间衰减重要度，淘汰「低强度 + 久未命中 + 低频」的弱记忆。

    至少保留 min_keep 条（按强度取），总量封顶 max_keep。
    """
    import time as _time

    rows = list_memories(db, owner_id=owner_id, agent_id=agent_id)
    if len(rows) <= min_keep:
        return {"decayed": 0, "deleted": 0, "kept": len(rows)}
    now = _time.time()
    for r in rows:
        ref = r.last_used_at or r.updated_at
        try:
            days = max(0.0, (now - ref.timestamp()) / 86400.0) if ref else 60.0
        except Exception:
            days = 60.0
        decay = max(0.0, 0.5 ** (days / 30.0))
        # 久未命中且重要度低 → 逐步衰减；频繁使用则保护
        base = float(r.importance or 0.5) * (0.5 + 0.5 * decay)
        freq_protect = min(1.0, float(r.use_count or 0) / 5.0)
        r.importance = round(min(1.0, base * (0.7 + 0.3 * freq_protect)), 4)
    db.commit()
    # 超量淘汰：保留最重要的 min_keep 起步，其余按重要度+使用频次裁剪到 max_keep
    rows.sort(key=lambda r: (r.importance or 0) + 0.05 * min(r.use_count or 0, 10), reverse=True)
    keep, drop = rows[:max_keep], rows[max_keep:]
    for r in drop:
        db.delete(r)
    db.commit()
    return {"decayed": len(rows), "deleted": len(drop), "kept": len(keep)}


def upsert_memory(
    db: Session, *, owner_id, agent_id: str, key: str, value: str,
    importance: float = 0.5, confidence: float = 0.5, category: str = "preference",
) -> AgentMemory:
    stmt = select(AgentMemory).where(
        AgentMemory.owner_id == owner_id, AgentMemory.agent_id == agent_id, AgentMemory.key == key
    )
    row = db.scalars(stmt).first()
    if row is None:
        row = AgentMemory(
            owner_id=owner_id, agent_id=agent_id, key=key, value=value,
            importance=importance, confidence=confidence, category=category,
        )
        db.add(row)
    else:
        row.value = value
        row.importance = importance
        row.confidence = confidence
        row.category = category
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


WORKING_STEP_CAP = 12


def get_active_working(db: Session, *, owner_id, agent_id: str) -> AgentWorkingMemory | None:
    return db.scalars(
        select(AgentWorkingMemory)
        .where(
            AgentWorkingMemory.owner_id == owner_id,
            AgentWorkingMemory.agent_id == agent_id,
            AgentWorkingMemory.status == "active",
        )
        .order_by(desc(AgentWorkingMemory.updated_at))
        .limit(1)
    ).first()


def latest_working(db: Session, *, owner_id, agent_id: str) -> AgentWorkingMemory | None:
    """进行中优先，否则最近一条已完成（供新会话回顾）。"""
    active = get_active_working(db, owner_id=owner_id, agent_id=agent_id)
    if active is not None:
        return active
    return db.scalars(
        select(AgentWorkingMemory)
        .where(AgentWorkingMemory.owner_id == owner_id, AgentWorkingMemory.agent_id == agent_id)
        .order_by(desc(AgentWorkingMemory.updated_at))
        .limit(1)
    ).first()


def archive_active_working(db: Session, *, owner_id, agent_id: str, status: str = "archived") -> None:
    row = get_active_working(db, owner_id=owner_id, agent_id=agent_id)
    if row is not None:
        row.status = status
        db.commit()


def start_working(
    db: Session, *, owner_id, agent_id: str, goal: str, conversation_id=None
) -> AgentWorkingMemory:
    archive_active_working(db, owner_id=owner_id, agent_id=agent_id)
    row = AgentWorkingMemory(
        owner_id=owner_id,
        agent_id=agent_id,
        status="active",
        goal=(goal or "")[:300],
        steps=[],
        summary="",
        conversation_id=conversation_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def append_working_step(
    db: Session,
    row: AgentWorkingMemory,
    *,
    step: dict,
    conversation_id=None,
    mark_done: bool = False,
) -> AgentWorkingMemory:
    steps = list(row.steps or [])
    steps.append(step)
    if len(steps) > WORKING_STEP_CAP:
        dropped = steps[: len(steps) - WORKING_STEP_CAP]
        steps = steps[-WORKING_STEP_CAP :]
        extra = "；".join((d.get("ask") or "")[:40] for d in dropped if d.get("ask"))
        if extra:
            row.summary = ((row.summary or "") + "；" + extra).strip("；")[:800]
    row.steps = steps
    if conversation_id is not None:
        row.conversation_id = conversation_id
    if mark_done:
        row.status = "done"
    db.commit()
    db.refresh(row)
    return row


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
    "rank_memories",
    "reinforce_memories",
    "decay_memories",
    "get_active_working",
    "latest_working",
    "start_working",
    "append_working_step",
    "archive_active_working",
    "touch_conversation",
]
