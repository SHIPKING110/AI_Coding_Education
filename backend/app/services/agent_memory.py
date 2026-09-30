"""Agent 工作台记忆服务：短期窗口 + 滚动摘要 + 长期记忆注入与增量提炼。"""

from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.crud import agent as agent_crud
from app.services import llm

SHORT_WINDOW_TURNS = 10
SUMMARY_TRIGGER_MESSAGES = 30


def build_memory_context(db: Session, *, owner_id, agent_id: str, conversation_id) -> dict:
    """组装注入 prompt 的记忆上下文：短期窗口 + 摘要 + 长期记忆。"""
    recent = agent_crud.recent_messages(db, conversation_id=conversation_id, limit=SHORT_WINDOW_TURNS)
    summary_row = agent_crud.get_summary(db, conversation_id=conversation_id)
    memories = agent_crud.list_memories(db, owner_id=owner_id, agent_id=agent_id)
    return {
        "recent": [{"role": m.role, "content": m.content} for m in recent],
        "summary": summary_row.summary if summary_row else "",
        "long_term": [{"key": m.key, "value": m.value} for m in memories],
    }


def memory_prompt_block(ctx: dict) -> str:
    parts: list[str] = []
    if ctx.get("summary"):
        parts.append(f"【本会话此前摘要】\n{ctx['summary']}")
    if ctx.get("long_term"):
        lines = "\n".join(f"- {m['key']}：{m['value']}" for m in ctx["long_term"])
        parts.append(f"【长期记忆（该用户在本 Agent 下的偏好与事实）】\n{lines}")
    if ctx.get("recent"):
        lines = "\n".join(f"{'用户' if m['role'] == 'user' else '助手'}：{m['content'][:500]}" for m in ctx["recent"])
        parts.append(f"【最近对话】\n{lines}")
    return "\n\n".join(parts)


def _distill_sync(owner_id, agent_id: str, conversation_id, user_text: str, assistant_text: str) -> None:
    """后台增量提炼：从本轮对话抽取长期事实并 upsert。失败静默。"""
    db: Session = SessionLocal()
    try:
        msgs = agent_crud.list_messages(db, conversation_id=conversation_id, limit=1000)
        # 超限则滚动摘要
        if len(msgs) >= SUMMARY_TRIGGER_MESSAGES:
            tail = "\n".join(f"{m.role}:{m.content[:300]}" for m in msgs[-20:])
            try:
                model = llm._chat_model()
                resp = model.invoke(f"请用 3-5 句话总结以下对话的要点（事实/偏好/结论），中文：\n{tail}")
                agent_crud.upsert_summary(db, conversation_id=conversation_id, summary=str(resp.content)[:2000])
            except Exception:
                pass
        try:
            model = llm._chat_model()
            resp = model.invoke(
                "从下面这轮对话中抽取可长期记住的**用户偏好/习惯/常用设置**（如配色偏好、常用模板、措辞习惯、称呼习惯）。"
                "**不要**记录会随时间变化的业务数据（如学员人数、名单、课时余额、考勤数字、班级成员）——这类数据每次都要实时查询。"
                '只输出 JSON 数组，如 [{"key":"配色偏好","value":"深蓝"}]；无则输出 []。\n'
                f"用户：{user_text[:1000]}\n助手：{assistant_text[:1000]}"
            )
            import json as _json

            text = str(resp.content)
            start, end = text.find("["), text.rfind("]")
            if start >= 0 and end > start:
                items = _json.loads(text[start : end + 1])
                for it in items if isinstance(items, list) else []:
                    if isinstance(it, dict) and it.get("key") and it.get("value"):
                        agent_crud.upsert_memory(
                            db,
                            owner_id=owner_id,
                            agent_id=agent_id,
                            key=str(it["key"])[:128],
                            value=str(it["value"])[:2000],
                        )
        except Exception:
            pass
    finally:
        db.close()


def distill_async(owner_id, agent_id: str, conversation_id, user_text: str, assistant_text: str) -> None:
    t = threading.Thread(
        target=_distill_sync, args=(owner_id, agent_id, conversation_id, user_text, assistant_text), daemon=True
    )
    t.start()


__all__ = [
    "SHORT_WINDOW_TURNS",
    "SUMMARY_TRIGGER_MESSAGES",
    "build_memory_context",
    "memory_prompt_block",
    "distill_async",
]
