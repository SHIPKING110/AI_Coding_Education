"""MCP 运行时执行器：per-agent ∪ 全局启用的 MCP，LLM 决策调用 → HTTP 执行 → 结果回灌。

流程（全部容错，失败降级为空，不影响主回答）：
1. effective_mcps() 取出生效的 MCP 行（endpoint 非空 + enabled）。
2. LLM 选工具：把用户消息 + 工具目录（name/description/endpoint）喂给小规划，
   返回 [{name, arguments}]，只返回 JSON 数组。
3. 逐个 POST endpoint，body={tool, arguments, message}，10s 超时，取 text/result/data 字段。
4. 拼成【MCP 工具结果】块回灌进 memory_block + 记录 tool_names（前端可展示调用了哪些工具）。
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_CALLS = 3
TIMEOUT_S = 10
RESULT_CHARS = 1500
BLOCK_CHARS = 4000


def effective_mcps(db: Session, owner_id, agent_id: str) -> list:
    from app.crud import agent_ext as _ext

    glob = _ext.get_global_setting(db, owner_id=owner_id)
    per_mcp: list = []
    c = _ext.get_custom_agent(db, owner_id=owner_id, agent_id=agent_id)
    if c is not None:
        per_mcp = list(c.mcp_ids or [])
    want = {str(x) for x in (per_mcp + list((glob.default_mcp_ids if glob else []) or []))}
    if not want:
        return []
    out = []
    for m in _ext.list_mcps(db, owner_id=owner_id):
        if m.enabled and str(m.id) in want and (m.endpoint or "").strip():
            out.append(m)
    # 内置 Agent 也吃全局默认（c 为 None 时 per_mcp 为空，只剩全局）
    return out


def _plan_calls(message: str, tools: list[dict]) -> list[dict]:
    """LLM 决策调用哪些 MCP：返回 [{name, arguments}]，失败/无需调用返回 []。"""
    if not tools or not message.strip():
        return []
    try:
        from app.services import llm as _llm

        catalog = "\n".join(
            f"- {t['name']}：{t.get('description') or '（无描述）'}（endpoint: {t.get('endpoint')}）"
            for t in tools
        )
        prompt = (
            "你是 MCP 工具调度器。根据用户消息判断是否需要调用外部工具。\n"
            f"可用工具：\n{catalog}\n\n"
            f"用户消息：{message.strip()[:1000]}\n\n"
            "规则：不需要调用返回 []；需要则只返回 JSON 数组，如 "
            '[{"name": "工具名", "arguments": {"key": "value"}}]，最多 3 个，不要多余文字。'
        )
        raw = _llm._invoke(prompt)
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        s, e = text.find("["), text.rfind("]")
        if s == -1 or e == -1 or e <= s:
            return []
        data = json.loads(text[s : e + 1])
        if not isinstance(data, list):
            return []
        calls = []
        names = {t["name"] for t in tools}
        for item in data[:MAX_CALLS]:
            if isinstance(item, dict) and item.get("name") in names:
                args = item.get("arguments")
                calls.append({"name": item["name"], "arguments": args if isinstance(args, dict) else {}})
        return calls
    except Exception:
        logger.exception("mcp plan failed")
        return []


def _call_endpoint(endpoint: str, name: str, arguments: dict, message: str) -> str:
    try:
        import httpx

        with httpx.Client(timeout=TIMEOUT_S) as client:
            resp = client.post(endpoint, json={"tool": name, "arguments": arguments, "message": message[:1000]})
        if resp.status_code >= 400:
            return f"调用失败（HTTP {resp.status_code}）"
        try:
            data = resp.json()
        except Exception:
            return (resp.text or "")[:RESULT_CHARS] or "（空响应）"
        if isinstance(data, dict):
            for k in ("result", "text", "data", "output", "message"):
                v = data.get(k)
                if v:
                    return str(v)[:RESULT_CHARS]
            return json.dumps(data, ensure_ascii=False)[:RESULT_CHARS]
        return str(data)[:RESULT_CHARS]
    except Exception as e:
        return f"调用异常：{e}"


def run(db: Session, owner_id, agent_id: str, message: str) -> tuple[str, list[str]]:
    """执行生效 MCP，返回 (注入块, 调用的工具名列表)。无工具/无需调用/失败返回 ("", [])。"""
    try:
        mcps = effective_mcps(db, owner_id, agent_id)
    except Exception:
        logger.exception("mcp effective failed")
        return "", []
    if not mcps or not message.strip():
        return "", []
    tools = [{"name": m.name, "description": m.description, "endpoint": m.endpoint} for m in mcps]
    calls = _plan_calls(message, tools)
    if not calls:
        return "", []
    by_name = {m.name: m for m in mcps}
    lines: list[str] = []
    used: list[str] = []
    for call in calls:
        m = by_name.get(call["name"])
        if m is None:
            continue
        result = _call_endpoint(m.endpoint, m.name, call.get("arguments") or {}, message)
        used.append(m.name)
        lines.append(f"- {m.name}：{result}")
    if not lines:
        return "", []
    block = "【MCP 工具结果】（已实际调用外部工具，如下结果可直接引用）\n" + "\n".join(lines)
    return block[:BLOCK_CHARS], used
