"""Agent 工作台记忆服务（生产化）：
- 检索：长期记忆按「相关度 + 强度 + 新近度」排序并封顶，不再全量注入；
- 优先级裁决：本轮用户显式指令 > 强偏好 > 弱偏好，冲突以本轮为准；
- 生命周期：写入(提炼) / 强化(召回即强化) / 压缩衰减 / 删除(淘汰)。

设计要点：
- 一次性指令（“这次详细点”）**不写入**长期记忆（会污染），仅当轮生效；
- 长期记忆只存“稳定倾向”，检索时若与本轮指令冲突，由 prompt 显式声明以本轮为准。
"""

from __future__ import annotations

import re
import threading

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.crud import agent as agent_crud
from app.services import llm

SHORT_WINDOW_TURNS = 10
SUMMARY_TRIGGER_MESSAGES = 30
# 长期记忆注入上限（过多会挤占上下文且稀释重点）
MEMORY_TOP_K = 8
# 触发记忆衰减/淘汰的间隔（每 N 次提炼做一次）
DECAY_EVERY = 20


def build_memory_context(
    db: Session, *, owner_id, agent_id: str, conversation_id, query: str = ""
) -> dict:
    """组装注入 prompt 的记忆上下文：短期窗口 + 摘要 + 检索出的长期记忆。

    query 用于长期记忆的相关度排序；召回的记忆会在本轮被强化（reinforce）。
    """
    recent = agent_crud.recent_messages(db, conversation_id=conversation_id, limit=SHORT_WINDOW_TURNS)
    summary_row = agent_crud.get_summary(db, conversation_id=conversation_id)
    ranked = agent_crud.rank_memories(
        db, owner_id=owner_id, agent_id=agent_id, query=query, top_k=MEMORY_TOP_K
    )
    working = _working_view(db, owner_id=owner_id, agent_id=agent_id)
    # 召回即强化：被本轮选中的记忆 use_count+1、刷新 last_used_at
    try:
        agent_crud.reinforce_memories(db, memory_ids=[m["id"] for m in ranked])
    except Exception:
        pass
    return {
        "recent": [
            {"role": m.role, "content": _clean_history(m.content)} for m in recent
        ],
        "summary": summary_row.summary if summary_row else "",
        "long_term": [
            {k: m[k] for k in ("key", "value", "category", "strength_tier", "confidence", "use_count")}
            for m in ranked
        ],
        "working": working,
    }


def _clean_history(content: str) -> str:
    """清洗历史消息文本：剔除原生工具调用标记，避免把乱码回灌给模型形成污染循环。"""
    if not content:
        return content
    try:
        from app.services.llm import strip_toolcall_markup

        return strip_toolcall_markup(content)
    except Exception:
        return content


_CATEGORY_LABEL = {"preference": "偏好", "fact": "事实", "experience": "经验"}


def memory_prompt_block(ctx: dict) -> str:
    """生成记忆注入块。含优先级裁决规则：本轮显式指令 > 强偏好 > 弱偏好。"""
    parts: list[str] = []
    if ctx.get("summary"):
        parts.append(f"【本会话此前摘要】\n{ctx['summary']}")

    ltm = ctx.get("long_term") or []
    if ltm:
        lines = []
        for m in ltm:
            tier = "强" if m.get("strength_tier") == "strong" else "弱"
            cat = _CATEGORY_LABEL.get(m.get("category", ""), "记忆")
            conf = m.get("confidence")
            conf_txt = f"（置信{conf:.0%}）" if isinstance(conf, (int, float)) else ""
            lines.append(f"- [{cat}/{tier}] {m['key']}：{m['value']}{conf_txt}")
        # 优先级规则写在最前，作为行为约束
        parts.append(
            "【长期记忆（该用户在本 Agent 下的稳定偏好/事实）】\n"
            "使用规则（优先级）：本轮用户的显式指令 > 强偏好 > 弱偏好；"
            "若记忆与本轮要求冲突（例如记忆偏好简短、用户本次要求详细解释），一律以本轮指令为准。\n"
            + "\n".join(lines)
        )

    wm = ctx.get("working")
    if wm and (wm.get("goal") or wm.get("steps")):
        lines = []
        if wm.get("summary"):
            lines.append(f"更早：{wm['summary'][:200]}")
        for i, s in enumerate(wm.get("steps") or [], 1):
            raw_tools = s.get("tools") or []
            tool_names = [
                str(t.get("tool") or t.get("name") or "") if isinstance(t, dict) else str(t)
                for t in raw_tools
            ]
            tools = "、".join(n for n in tool_names if n)
            tail = f"（工具 {tools}）" if tools else ""
            result = (s.get("result") or "")[:80]
            lines.append(f"{i}. {s.get('ask', '')[:80]}{tail}" + (f" → {result}" if result else ""))
        state = "进行中" if wm.get("status") == "active" else "已完成"
        parts.append(
            f"【工作记忆·跨会话任务（{state}）】\n"
            f"目标：{wm.get('goal', '')[:200]}\n"
            + ("\n".join(lines) if lines else "尚无已完成步骤。")
            + "\n规则：用户说「继续/接着/下一步」时沿此推进；"
            "说「新任务/重新开始」则放弃本任务。本轮若是无关新话题，不要强行套用。"
        )

    if ctx.get("recent"):
        lines = "\n".join(
            f"{'用户' if m['role'] == 'user' else '助手'}：{m['content'][:500]}" for m in ctx["recent"]
        )
        parts.append(f"【最近对话】\n{lines}")
    return "\n\n".join(parts)


def _distill_sync(owner_id, agent_id: str, conversation_id, user_text: str, assistant_text: str) -> None:
    """后台增量提炼：抽取长期事实/偏好并写入；滚动摘要；周期性衰减淘汰。"""
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

        # 抽取可长期记住的稳定信息（明确排除一次性指令与时变业务数据）
        try:
            model = llm._chat_model()
            resp = model.invoke(
                "从下面这轮对话中抽取**可长期复用的稳定信息**，分三类：\n"
                "  - preference 偏好/习惯（配色、模板、措辞、称呼等稳定倾向）\n"
                "  - fact 稳定事实（如班级固定信息、长期约定）\n"
                "  - experience 历史经验（踩过的坑、已验证的做法）\n"
                "**严格排除**：① 一次性指令（如“这次详细点/这次简短”）——只当轮生效，不要记；"
                "② 会随时间变化的业务数据（学员人数、名单、课时余额、考勤数字、成绩等）——每次需实时查询。\n"
                "输出 JSON 数组，每项形如 "
                '{"key":"...","value":"...","category":"preference|fact|experience",'
                '"importance":0.0~1.0,"confidence":0.0~1.0}；无则输出 []。\n'
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
                            importance=_clamp(it.get("importance", 0.5)),
                            confidence=_clamp(it.get("confidence", 0.5)),
                            category=str(it.get("category", "preference"))[:16],
                        )
        except Exception:
            pass

        # 周期性压缩/淘汰：控制记忆总量、衰减陈旧弱记忆
        try:
            count = db.query(agent_crud.AgentMemory).filter(
                agent_crud.AgentMemory.owner_id == owner_id,
                agent_crud.AgentMemory.agent_id == agent_id,
            ).count()
            if count and count % DECAY_EVERY == 0:
                agent_crud.decay_memories(db, owner_id=owner_id, agent_id=agent_id)
        except Exception:
            pass
    finally:
        db.close()


def _clamp(v, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return 0.5


_NEW_TASK = re.compile(r"新任务|换个任务|重新开始|从头开始|另外一件")
_DONE_TASK = re.compile(r"做完了|任务完成|结束这个任务|到此为止")
_RESUME = re.compile(r"继续|接着|下一步|上次|刚才那个")


def _working_view(db: Session, *, owner_id, agent_id: str) -> dict | None:
    row = agent_crud.latest_working(db, owner_id=owner_id, agent_id=agent_id)
    if row is None:
        return None
    return {
        "status": row.status,
        "goal": row.goal or "",
        "summary": row.summary or "",
        "steps": list(row.steps or [])[-6:],
    }


def record_working_turn(
    db: Session,
    *,
    owner_id,
    agent_id: str,
    conversation_id,
    user_text: str,
    assistant_text: str,
    stage: str = "",
    tools: list[str] | None = None,
) -> None:
    """把本轮进度写入跨会话工作记忆。寒暄不记；「新任务」归档旧的再开一条。"""
    text = (user_text or "").strip()
    reply = (assistant_text or "").strip()
    if len(text) < 4 or not reply:
        return
    flat: list[str] = []
    for t in (tools or []):
        if isinstance(t, str):
            flat.append(t)
        elif isinstance(t, dict):
            name = str(t.get("tool") or t.get("name") or "").strip()
            if name:
                flat.append(("✅ " if t.get("ok") else "❌ ") + name + ("" if t.get("ok") else f"（{t.get('error') or '失败'}）"))
        else:
            s = str(t).strip()
            if s:
                flat.append(s)
    tools = flat[:6]
    step = {
        "ask": text[:160],
        "stage": stage or "",
        "tools": tools,
        "result": reply.replace("\n", " ")[:280],
    }
    done = bool(_DONE_TASK.search(text))
    if _NEW_TASK.search(text):
        row = agent_crud.start_working(
            db, owner_id=owner_id, agent_id=agent_id, goal=text[:200], conversation_id=conversation_id
        )
    else:
        row = agent_crud.get_active_working(db, owner_id=owner_id, agent_id=agent_id)
        if row is None:
            prev = agent_crud.latest_working(db, owner_id=owner_id, agent_id=agent_id)
            if prev is not None and prev.status == "done" and _RESUME.search(text):
                prev.status = "active"
                db.commit()
                row = prev
            elif prev is not None and prev.status == "active":
                row = prev
            else:
                row = agent_crud.start_working(
                    db, owner_id=owner_id, agent_id=agent_id, goal=text[:200], conversation_id=conversation_id
                )
    agent_crud.append_working_step(
        db, row, step=step, conversation_id=conversation_id, mark_done=done
    )


def distill_async(owner_id, agent_id: str, conversation_id, user_text: str, assistant_text: str) -> None:
    t = threading.Thread(
        target=_distill_sync, args=(owner_id, agent_id, conversation_id, user_text, assistant_text), daemon=True
    )
    t.start()


__all__ = [
    "MEMORY_TOP_K",
    "SHORT_WINDOW_TURNS",
    "SUMMARY_TRIGGER_MESSAGES",
    "build_memory_context",
    "memory_prompt_block",
    "record_working_turn",
    "distill_async",
]