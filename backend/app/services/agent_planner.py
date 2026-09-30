"""智能助手「规划层」：多轮 规划 → 执行 → 观察 循环。

设计见 docs/adr/adr-0002-assistant-tool-planning.md。目标：
- 理解用户问题，规划出要调用哪些业务工具（可多轮、可多工具）；
- 高效：单轮内可并行多工具；预算护栏防止无限循环；不把冗长上下文喂回模型；
- 省 token：紧凑工具目录、工具结果截断回灌、注入块限长；
- 稳定：每步容错、去重、时间/步数/轮数预算、失败自动降级到启发式路由。

对外只有一个入口：plan_and_run()，永远返回结论（可能为空），不抛异常。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.user import User
from app.services import agent_tools, llm

logger = logging.getLogger(__name__)


@dataclass
class Step:
    tool: str
    args: dict
    ok: bool
    result: Any = None
    error: str | None = None


@dataclass
class PlanOutcome:
    steps: list[Step] = field(default_factory=list)
    block: str = ""
    rounds: int = 0
    degraded: bool = False  # True = 未走 LLM 规划（启发式或跳过）

    @property
    def tools(self) -> list[str]:
        return [s.tool for s in self.steps]


def _elapsed_ms(t0: float) -> float:
    return (time.monotonic() - t0) * 1000.0


def plan_and_run(
    db: Session,
    user: User,
    message: str,
    *,
    max_rounds: int | None = None,
    max_calls: int | None = None,
    time_budget_ms: int | None = None,
) -> PlanOutcome:
    """规划并执行只读业务工具，返回调用记录与注入文本块。

    - 非业务问题：直接返回空（不触发任何 LLM 调用）；
    - LLM 不可用或规划失败：降级为关键词启发式单轮路由；
    - 任何工具异常：记录错误并继续，不中断整体流程。
    """
    if not agent_tools.looks_like_business(message):
        return PlanOutcome()

    cfg = get_settings()
    budget_ms = time_budget_ms or cfg.AGENT_TOOL_TIME_BUDGET_MS
    rounds_cap = max_rounds or cfg.AGENT_TOOL_MAX_ROUNDS
    calls_cap = max_calls or cfg.AGENT_TOOL_MAX_CALLS
    result_chars = cfg.AGENT_TOOL_RESULT_CHARS
    block_chars = cfg.AGENT_TOOL_BLOCK_CHARS

    t0 = time.monotonic()
    steps: list[Step] = []
    seen: set[str] = set()
    rounds = 0
    # 规划消息：只带「系统角色 + 用户问题 + 各轮工具结果」，不带历史对话，省 token
    messages: list = [llm._sys_msg(llm.TOOL_PLANNER_SYS), llm._human_msg(message)]
    planner_failed = False

    for _ in range(rounds_cap):
        if len(steps) >= calls_cap or _elapsed_ms(t0) > budget_ms:
            break
        try:
            _, calls = llm.tool_step(messages, agent_tools.TOOLS_SCHEMA)
        except Exception:
            planner_failed = True
            break
        if not calls:
            break  # 模型认为信息已足够，停止规划
        rounds += 1
        observations: list[str] = []
        for c in calls:
            if len(steps) >= calls_cap:
                break
            name = str(c.get("name") or "")
            args = c.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (ValueError, TypeError):
                    args = {}
            key = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
            if key in seen:
                observations.append(f"· {name}：{json.dumps(args, ensure_ascii=False)}（重复调用已跳过）")
                continue
            seen.add(key)
            ok, payload = _exec(db, user, name, args)
            steps.append(
                Step(tool=name, args=args, ok=ok,
                     result=payload if ok else None, error=None if ok else str(payload))
            )
            observations.append(f"· {name}：{compact_result(payload, result_chars)}")
        if observations:
            messages.append(llm._human_msg("工具结果：\n" + "\n".join(observations)))

    if not steps:
        # 规划未产出任何调用：LLM 不可用/规划抛错时降级启发式；
        # 规划成功但返回空（模型漏调，某些模型 function-calling 偏保守）时，
        # 若关键词启发式能命中，也走启发式兜底——业务问题绝不允许"零工具"回答。
        heuristic = agent_tools._heuristic_calls(message)[:calls_cap]
        if planner_failed or not llm.is_llm_configured() or heuristic:
            if planner_failed:
                logger.warning("工具规划失败，已降级启发式路由")
            elif heuristic:
                logger.info("规划器未选工具，启发式兜底命中 %d 个", len(heuristic))
            steps = _heuristic_run(db, user, message, calls_cap)
            block = _format_block(steps, block_chars, result_chars=result_chars)
            return PlanOutcome(steps=steps, block=block, degraded=True)
        return PlanOutcome()

    block = _format_block(steps, block_chars, result_chars=result_chars)
    return PlanOutcome(steps=steps, block=block, rounds=rounds)


def _exec(db: Session, user: User, name: str, args: dict) -> tuple[bool, Any]:
    try:
        return True, agent_tools.execute_tool(db, user, name, args)
    except Exception as e:  # noqa: BLE001 —— 单工具失败不拖垮整体
        return False, {"错误": str(e)}


def _heuristic_run(db: Session, user: User, message: str, calls_cap: int) -> list[Step]:
    steps: list[Step] = []
    for c in agent_tools._heuristic_calls(message)[:calls_cap]:
        name = str(c.get("name") or "")
        args = c.get("arguments") or {}
        ok, payload = _exec(db, user, name, args)
        steps.append(Step(tool=name, args=args, ok=ok, result=payload if ok else None,
                          error=None if ok else str(payload)))
    return steps


def compact_result(obj: Any, max_chars: int) -> str:
    """工具结果 → 紧凑 JSON 字符串；超长时按「整条记录」裁剪，绝不把一行切成两半。

    返回要么完整，要么是"完整的前 N 条 + 未列出条数提示"，
    避免模型看到被截断的行而出现"未返回/数据缺失"的幻觉。
    """
    try:
        text = json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(obj)
    if len(text) <= max_chars:
        return text
    trimmed = _trim_list_records(obj, max_chars)
    if trimmed is not None:
        return trimmed
    return text[:max_chars] + "…（已截断）"


def _trim_list_records(obj: Any, max_chars: int) -> str | None:
    """找 dict 里最大的列表字段，按整条裁剪到预算内；找不到可裁剪列表则返回 None。"""
    if not isinstance(obj, dict):
        return None
    key = max(
        (k for k, v in obj.items() if isinstance(v, list) and len(v) > 1),
        key=lambda k: len(obj[k]),
        default=None,
    )
    if key is None:
        return None
    vals = obj[key]

    def fits(count: int) -> bool:
        cand = dict(obj)
        cand[key] = vals[:count]
        return len(json.dumps(cand, ensure_ascii=False)) <= max_chars

    lo, hi = 1, len(vals) + 1
    while lo < hi:
        mid = (lo + hi) // 2
        if fits(mid):
            lo = mid + 1
        else:
            hi = mid
    best = lo - 1
    if best < 1 or best >= len(vals):
        return None
    cand = dict(obj)
    cand[key] = vals[:best]
    out = json.dumps(cand, ensure_ascii=False)
    note = f"，另有 {len(vals) - best} 条未列出"
    return out + note


def _format_block(
    steps: list[Step], max_chars: int, *, result_chars: int = 1200
) -> str:
    if not steps:
        return ""
    parts = ["【业务数据】（系统实时数据，请据此作答并注明数据周期；未列出的不要编造）"]
    for s in steps:
        if s.ok:
            parts.append(f"· {s.tool}({_brief_args(s.args)})：{compact_result(s.result, result_chars)}")
        else:
            parts.append(f"· {s.tool}：查询失败（{s.error}）")
    # 整块也按条裁剪：宁可少保留一个结果，也不截断到一行中间
    total = 0
    kept: list[str] = []
    for p in parts:
        if total + len(p) + 1 > max_chars:
            break
        kept.append(p)
        total += len(p) + 1
    block = "\n".join(kept)
    if len(kept) < len(parts):
        block += "\n…（其余业务数据因篇幅未列出，如需可再追问）"
    return block


def _brief_args(args: dict) -> str:
    if not args:
        return ""
    return ", ".join(f"{k}={v}" for k, v in args.items())[:80]


__all__ = ["PlanOutcome", "Step", "plan_and_run"]
