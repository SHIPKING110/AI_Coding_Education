"""MCP 运行时执行器 v2：协议感知调用 + 全链路 trace。

支持的 kind：
- streamable_http：MCP Streamable HTTP（JSON-RPC 2.0，POST endpoint，含 MCP-Protocol-Version 头），
  如高德 amap-maps streamableHTTP。流程：initialize → notifications/initialized →
  tools/list（校验 tool 存在）→ tools/call。响应可能是 JSON 或 SSE 流，均解析。
- http：普通 webhook 式 POST {tool, arguments, message}，取 result/text/data 字段。
- sse：远端 SSE 端点（GET 建立、POST 发消息），本版本按 streamable_http 兼容处理。

全链路 trace：每次 run() 返回 trace 列表，每步 {step, ok, detail, ms}，
持久化进消息 citations.mcp_trace，前端可在气泡下方展开查看“规划→调用→结果”。
另提供 test() 供「测试连接」按钮：list 工具清单并试调一次，结果直接返回给前端。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_CALLS = 3
TIMEOUT_S = 15
RESULT_CHARS = 2000
BLOCK_CHARS = 6000


def _headers(m) -> dict:
    cfg = m.config or {}
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    extra = cfg.get("headers") or {}
    if isinstance(extra, dict):
        headers.update({str(k): str(v) for k, v in extra.items()})
    return headers


def _parse_rpc_text(text: str) -> dict | None:
    """JSON-RPC 响应可能是纯 JSON，也可能是 SSE 流（多行 data: {...}），逐行解析取最后一条 result/error。"""
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            return json.loads(text)
        except Exception:
            return None
    last: dict | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                last = obj
    return last


def _rpc_post(client, endpoint: str, headers: dict, payload: dict) -> tuple[dict | None, str]:
    """发一次 JSON-RPC，返回 (响应对象, 原始文本摘要)。"""
    resp = client.post(endpoint, headers=headers, json=payload)
    body = resp.text or ""
    if resp.status_code >= 400:
        return None, f"HTTP {resp.status_code}：{body[:300]}"
    return _parse_rpc_text(body), body[:300]


def streamable_tools_list(m) -> tuple[list[dict], list[dict]]:
    """tools/list 握手：返回 (工具清单, trace)。清单项 {name, description, inputSchema}。"""
    import httpx

    trace: list[dict] = []
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            headers = _headers(m)
            init_payload = {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "child-code", "version": "1.0"}},
            }
            init_resp, init_note = _rpc_post(client, m.endpoint, headers, init_payload)
            ms = int((time.monotonic() - t0) * 1000)
            if init_resp is None or "error" in init_resp:
                trace.append({"step": "initialize", "ok": False, "ms": ms, "detail": f"握手失败：{init_note}"})
                return [], trace
            session_id = (init_resp.get("result") or {}).get("sessionId") or ""
            trace.append({"step": "initialize", "ok": True, "ms": ms, "detail": "握手成功"})
            headers2 = dict(headers)
            if session_id and isinstance(session_id, str):
                headers2["Mcp-Session-Id"] = session_id
            try:
                client.post(m.endpoint, headers=headers2, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            except Exception:
                pass
            t1 = time.monotonic()
            list_resp, list_note = _rpc_post(
                client, m.endpoint, headers2, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            )
            ms2 = int((time.monotonic() - t1) * 1000)
            if list_resp is None or "error" in list_resp:
                trace.append({"step": "tools/list", "ok": False, "ms": ms2, "detail": f"获取工具清单失败：{list_note}"})
                return [], trace
            tools = ((list_resp.get("result") or {}).get("tools")) or []
            trace.append({"step": "tools/list", "ok": True, "ms": ms2, "detail": f"发现 {len(tools)} 个工具"})
            return tools if isinstance(tools, list) else [], trace
    except Exception as e:
        trace.append({"step": "connect", "ok": False, "ms": int((time.monotonic() - t0) * 1000), "detail": f"连接异常：{e}"})
        return [], trace


def streamable_tools_call(m, tool: str, arguments: dict) -> tuple[str, list[dict]]:
    """tools/call 一次，返回 (结果文本, trace)。"""
    import httpx

    trace: list[dict] = []
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            headers = _headers(m)
            init_payload = {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "child-code", "version": "1.0"}},
            }
            init_resp, init_note = _rpc_post(client, m.endpoint, headers, init_payload)
            if init_resp is None or "error" in init_resp:
                trace.append({"step": "initialize", "ok": False, "ms": int((time.monotonic() - t0) * 1000), "detail": f"握手失败：{init_note}"})
                return f"调用失败：{init_note}", trace
            session_id = (init_resp.get("result") or {}).get("sessionId") or ""
            if session_id and isinstance(session_id, str):
                headers["Mcp-Session-Id"] = session_id
            try:
                client.post(m.endpoint, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            except Exception:
                pass
            t1 = time.monotonic()
            call_resp, call_note = _rpc_post(
                client, m.endpoint, headers,
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": tool, "arguments": arguments or {}}},
            )
            ms = int((time.monotonic() - t1) * 1000)
            if call_resp is None:
                trace.append({"step": f"tools/call {tool}", "ok": False, "ms": ms, "detail": f"无响应：{call_note}"})
                return f"调用失败：{call_note}", trace
            if "error" in call_resp:
                err = call_resp["error"]
                detail = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                trace.append({"step": f"tools/call {tool}", "ok": False, "ms": ms, "detail": f"服务端报错：{detail}"})
                return f"调用失败：{detail}", trace
            result = call_resp.get("result") or {}
            parts: list[str] = []
            for c in result.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                    parts.append(str(c["text"]))
            text = "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)
            trace.append({"step": f"tools/call {tool}", "ok": True, "ms": ms,
                          "detail": f"参数 {json.dumps(arguments or {}, ensure_ascii=False)[:200]}，返回 {len(text)} 字"})
            return text[:RESULT_CHARS], trace
    except Exception as e:
        trace.append({"step": f"tools/call {tool}", "ok": False, "ms": int((time.monotonic() - t0) * 1000), "detail": f"连接异常：{e}"})
        return f"调用异常：{e}", trace


def _call_plain_http(m, tool: str, arguments: dict, message: str) -> tuple[str, list[dict]]:
    import httpx

    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            resp = client.post(m.endpoint, headers=_headers(m),
                               json={"tool": tool, "arguments": arguments or {}, "message": (message or "")[:1000]})
        ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code >= 400:
            return f"调用失败（HTTP {resp.status_code}）", [{"step": f"POST {tool}", "ok": False, "ms": ms, "detail": resp.text[:300]}]
        try:
            data = resp.json()
        except Exception:
            return (resp.text or "")[:RESULT_CHARS] or "（空响应）", [{"step": f"POST {tool}", "ok": True, "ms": ms, "detail": "纯文本响应"}]
        if isinstance(data, dict):
            for k in ("result", "text", "data", "output", "message"):
                v = data.get(k)
                if v:
                    return str(v)[:RESULT_CHARS], [{"step": f"POST {tool}", "ok": True, "ms": ms, "detail": f"取字段 {k}"}]
            return json.dumps(data, ensure_ascii=False)[:RESULT_CHARS], [{"step": f"POST {tool}", "ok": True, "ms": ms, "detail": "完整 JSON"}]
        return str(data)[:RESULT_CHARS], [{"step": f"POST {tool}", "ok": True, "ms": ms, "detail": "数组响应"}]
    except Exception as e:
        return f"调用异常：{e}", [{"step": f"POST {tool}", "ok": False, "ms": int((time.monotonic() - t0) * 1000), "detail": str(e)}]


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
    return out


def _plan_calls(message: str, tools: list[dict]) -> tuple[list[dict], dict]:
    """LLM 决策调用哪些 MCP：返回 (calls, trace_step)。calls 项 {server, tool, arguments}。"""
    step: dict = {"step": "plan", "ok": True, "ms": 0, "detail": "无需调用外部工具"}
    if not tools or not message.strip():
        return [], step
    t0 = time.monotonic()
    try:
        from app.services import llm as _llm

        catalog = "\n".join(
            f"- server={t['server']} tool={t['tool']}：{t.get('description') or '（无描述）'}"
            for t in tools
        )
        prompt = (
            "你是 MCP 工具调度器。根据用户消息判断是否需要调用外部工具。\n"
            f"可用工具：\n{catalog}\n\n"
            f"用户消息：{message.strip()[:1000]}\n\n"
            "规则：不需要调用返回 []；需要则只返回 JSON 数组，如 "
            '[{"server": "server名", "tool": "工具名", "arguments": {"city": "赣州"}}]，'
            "server/tool 必须照抄目录里的值，arguments 按工具语义填写，最多 3 个，不要多余文字。"
        )
        raw = _llm._invoke(prompt)
        ms = int((time.monotonic() - t0) * 1000)
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        s, e = text.find("["), text.rfind("]")
        if s == -1 or e == -1 or e <= s:
            step = {"step": "plan", "ok": True, "ms": ms, "detail": "模型判定无需调用"}
            return [], step
        data = json.loads(text[s : e + 1])
        if not isinstance(data, list) or not data:
            step = {"step": "plan", "ok": True, "ms": ms, "detail": "模型判定无需调用"}
            return [], step
        valid = {(t["server"], t["tool"]) for t in tools}
        calls = []
        for item in data[:MAX_CALLS]:
            if isinstance(item, dict) and (item.get("server"), item.get("tool")) in valid:
                args = item.get("arguments")
                calls.append({"server": item["server"], "tool": item["tool"],
                              "arguments": args if isinstance(args, dict) else {}})
        step = {"step": "plan", "ok": True, "ms": ms,
                "detail": f"决策调用 {len(calls)} 个：{'、'.join(c['tool'] for c in calls) or '无'}"}
        return calls, step
    except Exception as e:
        logger.exception("mcp plan failed")
        return [], {"step": "plan", "ok": False, "ms": int((time.monotonic() - t0) * 1000), "detail": f"规划失败：{e}"}


def run(db: Session, owner_id, agent_id: str, message: str) -> tuple[str, list[str], list[dict]]:
    """执行生效 MCP，返回 (注入块, 工具名列表, trace)。"""
    trace: list[dict] = []
    try:
        mcps = effective_mcps(db, owner_id, agent_id)
    except Exception:
        logger.exception("mcp effective failed")
        return "", [], [{"step": "load", "ok": False, "ms": 0, "detail": "读取 MCP 配置失败"}]
    if not mcps:
        return "", [], [{"step": "load", "ok": True, "ms": 0, "detail": "该 Agent 未绑定任何启用的 MCP（检查 per-agent 绑定与全局默认）"}]
    if not message.strip():
        return "", [], trace
    # 工具目录：streamable_http 先 tools/list 拿到真实工具名
    catalog: list[dict] = []
    by_server: dict[str, Any] = {}
    for m in mcps:
        by_server[m.name] = m
        kind = (m.kind or "streamable_http").lower()
        if kind in ("streamable_http", "streamablehttp", "sse"):
            tools, ltrace = streamable_tools_list(m)
            trace.extend(ltrace)
            for tool in tools:
                if isinstance(tool, dict) and tool.get("name"):
                    catalog.append({"server": m.name, "description": f"{m.name}/{tool.get('description') or ''}",
                                    "tool": tool["name"], "inputSchema": tool.get("inputSchema") or {}})
            if not tools:
                catalog.append({"server": m.name, "description": m.description, "tool": m.name, "inputSchema": {}})
        else:
            catalog.append({"server": m.name, "description": m.description, "tool": m.name, "inputSchema": {}})
    calls, plan_step = _plan_calls(message, catalog)
    trace.append(plan_step)
    if not calls:
        return "", [], trace
    lines: list[str] = []
    used: list[str] = []
    for call in calls:
        m = by_server.get(call["server"])
        if m is None:
            trace.append({"step": f"call {call['tool']}", "ok": False, "ms": 0, "detail": "server 不存在"})
            continue
        kind = (m.kind or "streamable_http").lower()
        if kind in ("streamable_http", "streamablehttp", "sse"):
            result, ctrace = streamable_tools_call(m, call["tool"], call.get("arguments") or {})
        else:
            result, ctrace = _call_plain_http(m, call["tool"], call.get("arguments") or {}, message)
        trace.extend(ctrace)
        used.append(f"{call['server']}/{call['tool']}")
        lines.append(f"- {call['server']}/{call['tool']}：{result}")
    if not lines:
        return "", used, trace
    block = "【MCP 工具结果】（已实际调用外部工具，如下结果可直接引用）\n" + "\n".join(lines)
    return block[:BLOCK_CHARS], used, trace


def test_connection(db: Session, owner_id, mcp_id) -> dict:
    """「测试连接」：握手 + tools/list + 记录 trace，前端直接展示。"""
    from app.crud import agent_ext as _ext

    m = _ext.get_mcp(db, owner_id=owner_id, mcp_id=mcp_id)
    if m is None:
        return {"ok": False, "tools": [], "trace": [{"step": "load", "ok": False, "ms": 0, "detail": "MCP 不存在"}]}
    if not (m.endpoint or "").strip():
        return {"ok": False, "tools": [], "trace": [{"step": "load", "ok": False, "ms": 0, "detail": "未填写 endpoint"}]}
    kind = (m.kind or "streamable_http").lower()
    if kind in ("streamable_http", "streamablehttp", "sse"):
        tools, trace = streamable_tools_list(m)
        return {"ok": any(s.get("ok") for s in trace),
                "tools": [{"name": t.get("name"), "description": t.get("description", "")} for t in tools if isinstance(t, dict)],
                "trace": trace}
    # 普通 http：发一次空调用探活
    result, trace = _call_plain_http(m, m.name, {}, "ping")
    ok = not result.startswith("调用失败") and not result.startswith("调用异常")
    return {"ok": ok, "tools": [], "trace": trace + [{"step": "ping", "ok": ok, "ms": 0, "detail": result[:200]}]}
