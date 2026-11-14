"""Agent 行为评测运行器：驱动真实对话链路，抽取工具 span 序列并打分。

链路（与线上完全一致，不引入第二套行为）：
  用例(question) → 建 source='eval' 一次性会话 → 进程内调用 /chat 的流式端点
  → 解析 delta 拼出终答复 → 按 conversation 找 agent_run_traces.run_id
  → 从 agent_run_spans(tool/skill/mcp) 还原工具调用序列
  → evals.agent_metrics 规则打分（工具 P/R/序列/禁用/拒答/关键事实）→ 聚合 + 闸门

设计约束：
- 评测会话不写长期记忆、不出现在用户会话列表（X-Eval-Run 守卫）；
- 评测消耗归因到「用量与成本」的任务监控（trace 带 eval_run_id 属性）；
- 逐条落库、进度可轮询；任何单条失败不影响整体（记 error 继续）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent_trace import AgentRunSpan, AgentRunTrace
from app.models.rag_admin import AgentEvalCase, AgentEvalResult, AgentEvalRun
from evals import agent_metrics

logger = logging.getLogger(__name__)

_SESSION_FACTORY = None


def _session_factory():
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        from app.core.database import SessionLocal

        _SESSION_FACTORY = SessionLocal
    return _SESSION_FACTORY


def start_run(run_id) -> None:
    """后台线程执行评测，接口立即返回（与 RAG 评测同一模式）。"""
    threading.Thread(target=_run, args=(str(run_id),), daemon=True).start()


def _set_progress(db: Session, run: AgentEvalRun, *, stage: str, processed: int, total: int) -> None:
    run.stage = stage
    run.processed_cases = processed
    run.progress = int(processed * 100 / total) if total else 0
    db.commit()


def _eval_user(db: Session):
    """评测驱动使用管理员账号（无个人记忆污染：spec 会话 source='eval' 已隔离）。"""
    from app.models.user import Role, User

    user = db.scalars(
        select(User).where(User.role == Role.ADMIN).order_by(User.created_at).limit(1)
    ).first()
    return user


def known_tool_names() -> set[str]:
    """内置工具注册表（agent_tools.TOOLS_SCHEMA）的工具名集合。

    用作评测用例的启动校验：工具改名/下线时立即报错，避免用例静默失配。
    """
    from app.services import agent_tools

    names: set[str] = set()
    for t in getattr(agent_tools, "TOOLS_SCHEMA", []) or []:
        fn = (t or {}).get("function") or {}
        name = str(fn.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def validate_tool_names(cases: list[AgentEvalCase]) -> list[str]:
    """校验用例引用的工具名都在注册表中；返回错误描述列表（空=通过）。"""
    known = known_tool_names()
    if not known:
        return []
    errors: list[str] = []
    for case in cases:
        refs: list[str] = []
        for field in ("expected_tools", "allowed_extra_tools", "forbidden_tools"):
            refs.extend(str(x) for x in (getattr(case, field) or []) if str(x).strip())
        unknown = sorted({r for r in refs if r not in known})
        if unknown:
            errors.append(f"用例「{(case.query or '')[:30]}」引用了未注册工具: {', '.join(unknown)}")
    return errors


def _drive_turn(db: Session, user, conv, message: str, eval_run_id: str, config_id: str | None):
    """进程内消费 /chat 的 SSE 流：返回 (终答复全文, done 帧, error)。"""
    from app.api.routers import agents as agents_router

    body = agents_router.ConversationChatIn(stage="chat", message=message, config_id=config_id)
    resp = agents_router.conversation_chat(conv.id, body, db, user, x_eval_run=eval_run_id)

    async def consume():
        parts: list[str] = []
        done = None
        error = None
        async for raw in resp.body_iterator:
            chunk = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            for line in chunk.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    ev = json.loads(payload)
                except Exception:
                    continue
                if isinstance(ev.get("delta"), str):
                    parts.append(ev["delta"])
                if ev.get("error"):
                    error = ev["error"]
                if ev.get("done"):
                    done = ev
        return "".join(parts), done, error

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(consume())
    finally:
        loop.close()


def _tool_name(span: AgentRunSpan) -> str:
    """span.name 形如 tool.find_students / skill.run_skill_script，还原注册表工具名。"""
    name = span.name or ""
    for prefix in ("tool.", "skill."):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _collect_tool_run(db: Session, conv_id) -> tuple[str, list[dict], float]:
    """按会话取最近一次 run trace 的工具 span 序列与费用。"""
    trace = db.scalars(
        select(AgentRunTrace)
        .where(AgentRunTrace.conversation_id == conv_id)
        .order_by(AgentRunTrace.created_at.desc())
        .limit(1)
    ).first()
    if trace is None:
        return "", [], 0.0
    spans = db.scalars(
        select(AgentRunSpan)
        .where(
            AgentRunSpan.run_id == trace.run_id,
            AgentRunSpan.span_type.in_(("tool", "skill", "mcp")),
        )
        .order_by(AgentRunSpan.started_at.asc().nulls_last(), AgentRunSpan.created_at.asc())
    ).all()
    calls = []
    for s in spans:
        name = _tool_name(s)
        # mcp 汇总 span（mcp.run）不对应单个工具，单独工具名记录在 attributes 里，MVP 跳过
        if s.span_type == "mcp" and name == "mcp.run":
            continue
        if not name:
            continue
        calls.append(
            {
                "name": name,
                "type": s.span_type,
                "status": s.status,
                "latency_ms": int(s.latency_ms or 0),
                "error": (s.error or "")[:300],
            }
        )
    cost = (
        db.scalar(
            select(func.coalesce(func.sum(AgentRunSpan.cost_estimate), 0.0)).where(
                AgentRunSpan.run_id == trace.run_id
            )
        )
        or 0.0
    )
    return trace.run_id, calls, float(cost)


def _case_payload(case: AgentEvalCase) -> dict:
    return {
        "query": case.query,
        "expected_tools": case.expected_tools or [],
        "allowed_extra_tools": case.allowed_extra_tools or [],
        "forbidden_tools": case.forbidden_tools or [],
        "expect_abstain": bool(case.expect_abstain),
        "expected_facts": case.expected_facts or [],
    }


def _execute_case(db: Session, run: AgentEvalRun, case: AgentEvalCase, user) -> AgentEvalResult:
    from app.crud import agent as agent_crud

    started = time.monotonic()
    row = AgentEvalResult(
        run_id=run.id,
        case_id=case.id,
        query=case.query,
        expected_tools=case.expected_tools or [],
    )
    conv = None
    try:
        conv = agent_crud.create_conversation(
            db,
            owner_id=user.id,
            agent_id=run.agent_id or "assistant",
            context_ref={},
            title=f"[评测] {(case.query or '')[:40]}",
            rag_enabled=True,
            source="eval",
        )
        config_id = str(run.model_config_id) if run.model_config_id else None
        turns = case.messages if isinstance(case.messages, list) and case.messages else None
        final_text = ""
        all_calls: list[dict] = []
        all_cost = 0.0
        last_trace = ""
        if turns:
            # 多轮脚本：逐条发送 user 消息；工具序列按全程累计（多轮用例的期望=两轮累计）
            for msg in turns:
                if not isinstance(msg, dict) or msg.get("role") != "user":
                    continue
                final_text, _done, error = _drive_turn(
                    db, user, conv, str(msg.get("content") or ""), str(run.id), config_id
                )
                if error:
                    raise RuntimeError(error)
                trace_run_id, calls, cost = _collect_tool_run(db, conv.id)
                last_trace = trace_run_id or last_trace
                all_calls.extend(calls)
                all_cost += cost
        else:
            final_text, _done, error = _drive_turn(
                db, user, conv, case.query or "", str(run.id), config_id
            )
            if error:
                raise RuntimeError(error)
            last_trace, all_calls, all_cost = _collect_tool_run(db, conv.id)

        metrics = agent_metrics.evaluate_case(
            _case_payload(case),
            actual_tools=[c["name"] for c in all_calls],
            final_text=final_text or "",
        )
        row.trace_run_id = last_trace
        row.final_text = (final_text or "")[:8000]
        row.tool_calls = all_calls
        row.metrics = metrics
        row.metrics["cost"] = all_cost
        row.metrics["latency_ms"] = int((time.monotonic() - started) * 1000)
    except Exception as exc:  # 单条失败不中断整批
        logger.exception("agent eval case failed: %s", case.id)
        row.error = str(exc)[:1000]
        row.metrics = {"bad_case_type": "error", "passed": False}
    db.add(row)
    db.commit()
    return row


def _aggregate_rows(rows: list[AgentEvalResult], split_of: dict) -> dict:
    packed = [
        {
            "metrics": r.metrics,
            "cost": (r.metrics or {}).get("cost") or 0.0,
            "latency_ms": (r.metrics or {}).get("latency_ms") or 0,
            "error": r.error,
            "split": split_of.get(r.case_id, "regression"),
        }
        for r in rows
    ]
    splits = sorted({p["split"] for p in packed})
    return {
        "overall": agent_metrics.aggregate(packed),
        "splits": {
            s: agent_metrics.aggregate([p for p in packed if p["split"] == s]) for s in splits
        },
    }


def _baseline_metrics(db: Session, run: AgentEvalRun) -> dict | None:
    """基线 = 同集更早「全量」完成运行中最多 3 次的冻结集指标均值（平滑 LLM 非确定性波动）。

    CLI 冒烟限额运行（eval_snapshot.limit）不参与基线，避免样本差异污染对比。
    """
    candidates = db.scalars(
        select(AgentEvalRun)
        .where(
            AgentEvalRun.set_id == run.set_id,
            AgentEvalRun.id != run.id,
            AgentEvalRun.status == "done",
            AgentEvalRun.metrics.is_not(None),
            AgentEvalRun.created_at < run.created_at,
        )
        .order_by(AgentEvalRun.created_at.desc())
        .limit(10)
    ).all()
    frozen_rows = []
    for prev in candidates:
        if (prev.eval_snapshot or {}).get("limit"):
            continue
        frozen = ((prev.metrics or {}).get("splits") or {}).get("frozen") or {}
        if frozen.get("cases"):
            frozen_rows.append(frozen)
        if len(frozen_rows) >= 3:
            break
    if not frozen_rows:
        return None

    def _mean(key: str) -> float | None:
        vals = [float(f[key]) for f in frozen_rows if isinstance(f.get(key), (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else None

    return {
        "splits": {
            "frozen": {
                "cases": frozen_rows[0].get("cases"),
                "seq_score": _mean("seq_score"),
                "tool_recall": _mean("tool_recall"),
                "abstention_rate": _mean("abstention_rate"),
            }
        }
    }


def _run(run_id: str) -> None:
    factory = _session_factory()
    db: Session = factory()
    try:
        run = db.get(AgentEvalRun, uuid.UUID(run_id))
        if run is None:
            return
        run.status = "running"
        _set_progress(db, run, stage="pending", processed=0, total=run.total_cases or 0)

        # CLI 冒烟场景支持限额：run.eval_snapshot 预置 {"limit": n} 时只跑前 n 条
        prev_snapshot = dict(run.eval_snapshot or {})
        requested_limit = 0
        try:
            requested_limit = int(prev_snapshot.get("limit") or 0)
        except Exception:
            requested_limit = 0

        cases = list(
            db.scalars(
                select(AgentEvalCase)
                .where(AgentEvalCase.set_id == run.set_id)
                .order_by(AgentEvalCase.created_at.asc())
            ).all()
        )
        if not cases:
            run.status = "failed"
            run.stage = "failed"
            run.error = "评测集为空"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return
        if requested_limit > 0:
            cases = cases[:requested_limit]
        run.total_cases = len(cases)
        run.eval_snapshot = {
            "cases": len(cases),
            "limit": requested_limit or None,
            "frozen": sum(1 for c in cases if c.split == "frozen"),
            "agent_id": run.agent_id,
            "model_config_id": str(run.model_config_id) if run.model_config_id else None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        db.commit()

        # 启动校验：用例引用的工具名必须存在于 agent_tools 注册表
        tool_errors = validate_tool_names(cases)
        if tool_errors:
            run.status = "failed"
            run.stage = "failed"
            run.error = "工具名校验失败：" + "; ".join(tool_errors)
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.error("agent eval run %s failed tool validation: %s", run_id, tool_errors)
            return

        user = _eval_user(db)
        if user is None:
            run.status = "failed"
            run.stage = "failed"
            run.error = "未找到可用的管理员账号"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        rows: list[AgentEvalResult] = []
        split_of = {c.id: (c.split or "regression") for c in cases}
        for idx, case in enumerate(cases, start=1):
            _set_progress(db, run, stage="running", processed=idx - 1, total=len(cases))
            rows.append(_execute_case(db, run, case, user))
        _set_progress(db, run, stage="aggregating", processed=len(cases), total=len(cases))

        metrics = _aggregate_rows(rows, split_of)
        run.metrics = metrics
        run.gate = agent_metrics.agent_eval_gate(metrics, baseline_metrics=_baseline_metrics(db, run))
        run.status = "done"
        run.stage = "done"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        logger.exception("agent eval run failed: %s", run_id)
        try:
            run = db.get(AgentEvalRun, uuid.UUID(run_id))
            if run is not None:
                run.status = "failed"
                run.stage = "failed"
                run.error = str(exc)[:2000]
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            logger.exception("agent eval run finalize failed: %s", run_id)
    finally:
        db.close()


__all__ = ["known_tool_names", "start_run", "validate_tool_names"]
