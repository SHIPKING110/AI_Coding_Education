"""联网搜索（Tavily）：给 Agent 补充"公网外部事实"。

定位（安全边界，务必保持）：
- 本系统是**教务系统**：学员/课时/排课/本校政策/收费标准都以**内部数据与知识库**为准；
- 联网搜索只补充**外部公开信息**（行业动态、竞品做法、公开资料、通用知识），
  **不得**用于回答本校政策/收费/课时规则类问题；
- 工具返回值带 `来源=公网` 标记，由规划层注入块统一标注，提示模型区分内外事实。

工程要点：
- 同步 httpx 调用（规划层在工作线程里跑，无阻塞主事件循环之虞）；
- 超时/限流/余额不足等一律**降级**为可读错误，不抛异常打断对话；
- 结果只保留必要字段（标题/链接/摘要/日期），控制回灌给模型的字符数。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT_S = 20.0
# 单条摘要截断长度（控制回灌体积）；最终再由 planner 的 compact_result 整体裁剪
_SNIPPET_CHARS = 500


def _error_of(payload: Any) -> str:
    """从 Tavily 错误响应里取出可读原因。"""
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            return str(detail.get("error") or "搜索失败")
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                return str(first.get("msg") or "搜索参数不合法")
        if detail:
            return str(detail)
    return "搜索失败"


def search_web(
    resolved,
    *,
    query: str,
    max_results: int | None = None,
    search_depth: str | None = None,
    topic: str | None = None,
    time_range: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict:
    """调用 Tavily Search，返回规整后的结果 dict（不抛异常）。

    返回结构：
      {"来源": "公网", "查询": query, "结果": [{标题, 链接, 摘要, 日期, 相关度}], "条数": n}
    失败时返回 {"来源": "公网", "错误": "..."}。
    """
    q = (query or "").strip()
    if not q:
        return {"来源": "公网", "错误": "搜索关键词不能为空"}
    if resolved is None:
        return {"来源": "公网", "错误": "未配置联网搜索（Tavily），无法联网检索"}

    import httpx

    base = (resolved.base_url or "https://api.tavily.com").rstrip("/")
    url = f"{base}/search"
    depth = search_depth if search_depth in ("basic", "advanced", "fast") else (resolved.search_depth or "basic")
    limit = max(1, min(int(max_results or resolved.max_results or 5), 20))
    payload: dict[str, Any] = {
        "query": q,
        "search_depth": depth,
        "max_results": limit,
        "topic": topic if topic in ("general", "news", "finance") else "general",
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    if time_range:
        payload["time_range"] = time_range
    lang = (resolved.language or "").strip()
    if lang:
        payload["language"] = lang
    if include_domains:
        payload["include_domains"] = list(include_domains)[:20]
    if exclude_domains:
        payload["exclude_domains"] = list(exclude_domains)[:20]
    headers = {
        "Authorization": f"Bearer {resolved.api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=SEARCH_TIMEOUT_S) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        return {"来源": "公网", "错误": "联网搜索超时，请稍后重试"}
    except httpx.HTTPError as e:
        return {"来源": "公网", "错误": f"联网搜索请求失败：{e}"}

    if resp.status_code == 401:
        return {"来源": "公网", "错误": "联网搜索 Key 无效或已过期，请在设置中检查"}
    if resp.status_code == 429:
        return {"来源": "公网", "错误": "联网搜索请求过于频繁或额度已用尽，请稍后再试"}
    if resp.status_code >= 400:
        try:
            detail = _error_of(resp.json())
        except Exception:
            detail = resp.text[:200]
        return {"来源": "公网", "错误": f"联网搜索失败（HTTP {resp.status_code}）：{detail}"}

    try:
        data = resp.json()
    except Exception:
        return {"来源": "公网", "错误": "联网搜索返回内容无法解析"}

    rows: list[dict] = []
    for item in (data.get("results") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("content") or "").strip()
        rows.append(
            {
                "标题": str(item.get("title") or "").strip()[:160],
                "链接": str(item.get("url") or "").strip()[:400],
                "摘要": snippet[:_SNIPPET_CHARS],
                "日期": str(item.get("published_date") or "").strip()[:40],
                "相关度": round(float(item.get("score") or 0), 3),
            }
        )
    if not rows:
        return {"来源": "公网", "查询": q, "结果": [], "条数": 0, "提示": "没有找到相关结果"}
    return {"来源": "公网", "查询": q, "条数": len(rows), "结果": rows}


__all__ = ["search_web"]
