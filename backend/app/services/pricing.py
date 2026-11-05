"""模型价格解析与成本计算（版本化价格表 + 阶梯 + 分时段折扣 + 快照）。

精确性原则：
- 价格匹配 = base_url 域名（host）优先 + 模型名（精确 > 最长前缀 > 通配）；
- 只取 `effective_from <= 调用时间` 的最新价格行 → 调价只新增行，历史账本不受影响；
- 分时折扣按 UTC 解释，窗口可选 `weekdays` 限定星期（工作日高峰加价 / 周末全天闲时等）；
- 匹配不到价格 → 返回 None（调用方标记 unpriced，绝不臆造费用）；
- 命中后把实际采用的单价、阶梯、折扣、币种冻结成快照，随记账行一起落库。
"""

from __future__ import annotations

import math
from datetime import datetime, time
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.usage import LLMModelPrice

_CJK_RANGES = (
    (0x4E00, 0x9FFF),   # CJK 统一汉字
    (0x3400, 0x4DBF),   # 扩展 A
    (0x3000, 0x303F),   # CJK 标点
    (0xFF00, 0xFFEF),   # 全角字符
)


def provider_host(base_url: str | None) -> str:
    """从 base_url 提取小写域名（不含端口），用于价格匹配与台账展示。"""
    raw = (base_url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    try:
        return (urlparse(raw).hostname or "").lower()
    except ValueError:
        return ""


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """无 usage 时的 token 估算：中日韩字符≈1 token/字，其余≈4 字符/token（保守偏大）。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    return max(1, cjk + math.ceil(other / 4))


def estimate_tokens_many(texts: list[str]) -> int:
    total = sum(estimate_tokens(t) for t in texts)
    return max(1, total) if texts else 0


def resolve_price(
    db: Session,
    host: str,
    model: str,
    at: datetime,
) -> LLMModelPrice | None:
    """按 host + 模型名 + 生效时间选价格行（host 命中优先，模型精确 > 前缀 > 通配）。"""
    rows = list(
        db.scalars(select(LLMModelPrice).where(LLMModelPrice.effective_from <= at)).all()
    )
    if not rows:
        return None
    host_l = (host or "").lower()
    model_l = (model or "").lower()

    best: tuple | None = None
    best_row: LLMModelPrice | None = None
    for row in rows:
        row_host = (row.provider_host or "").lower()
        if row_host and row_host != host_l:
            continue
        pattern = (row.model_pattern or "").lower()
        if pattern:
            if model_l == pattern:
                model_rank = 2
            elif model_l.startswith(pattern):
                model_rank = 1
            else:
                continue
        else:
            model_rank = 0
        host_rank = 1 if row_host else 0
        score = (host_rank, model_rank, len(pattern), row.effective_from)
        if best is None or score > best:
            best = score
            best_row = row
    return best_row


def _pick_tier(price: LLMModelPrice, input_tokens: int) -> dict | None:
    """按输入 token 选阶梯（取 min_input_tokens <= 输入量的最高档）。"""
    tiers = price.tiers
    if not isinstance(tiers, list) or not tiers:
        return None
    chosen: dict | None = None
    chosen_min = -1.0
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        try:
            min_tokens = float(tier.get("min_input_tokens", 0) or 0)
        except (TypeError, ValueError):
            continue
        if input_tokens >= min_tokens and min_tokens >= chosen_min:
            chosen = tier
            chosen_min = min_tokens
    return chosen


def _coerce_weekdays(raw) -> set[int] | None:
    """把窗口里的 weekdays 归一化成 {0..6} 集合（0=周一，6=周日）。None/空=不限制。"""
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return None
    out: set[int] = set()
    for item in raw:
        try:
            out.add(int(item) % 7)
        except (TypeError, ValueError):
            continue
    return out or None


def _in_window(
    now: time,
    start: str,
    end: str,
    weekdays: set[int] | None = None,
    weekday: int | None = None,
) -> bool:
    # weekday 限制：不落在指定星期则整体不命中（如仅工作日高峰加价）
    if weekdays is not None and weekday is not None and (weekday % 7) not in weekdays:
        return False
    try:
        sh, sm = (int(x) for x in str(start).split(":"))
        eh, em = (int(x) for x in str(end).split(":"))
    except (ValueError, TypeError):
        return False
    start_t = time(sh % 24, sm % 60)
    end_t = time(eh % 24, em % 60)
    if start_t <= end_t:
        return start_t <= now < end_t
    # 跨零点（如 16:30 → 00:30）
    return now >= start_t or now < end_t


def _matched_window(price: LLMModelPrice, at: datetime) -> dict | None:
    """返回命中的分时窗口（UTC 解释；支持可选 weekdays 限定星期）。"""
    windows = price.time_windows
    if not isinstance(windows, list):
        return None
    try:
        from datetime import UTC

        now_utc = at.astimezone(UTC) if at.tzinfo else at
    except (ValueError, OSError):
        return None
    weekday = now_utc.weekday()
    for window in windows:
        if not isinstance(window, dict):
            continue
        weekdays = _coerce_weekdays(window.get("weekdays"))
        if _in_window(
            now_utc.time(),
            window.get("start", ""),
            window.get("end", ""),
            weekdays,
            weekday,
        ):
            return window
    return None


def compute_cost(
    price: LLMModelPrice,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    at: datetime,
) -> tuple[float, dict]:
    """按价格行计算费用，返回 (cost, 单价快照)。未知/零价不算错（0 元也记 priced）。"""
    input_tokens = max(0, int(input_tokens or 0))
    output_tokens = max(0, int(output_tokens or 0))
    cached_tokens = max(0, min(int(cached_tokens or 0), input_tokens))

    in_price = float(price.input_per_1m or 0.0)
    out_price = float(price.output_per_1m or 0.0)
    cache_read_price = float(price.cache_read_per_1m or 0.0)
    tier = _pick_tier(price, input_tokens)
    tier_min = None
    if tier is not None:
        tier_min = tier.get("min_input_tokens", 0)
        if tier.get("input_per_1m") is not None:
            in_price = float(tier["input_per_1m"])
        if tier.get("output_per_1m") is not None:
            out_price = float(tier["output_per_1m"])
        if tier.get("cache_read_per_1m") is not None:
            cache_read_price = float(tier["cache_read_per_1m"])

    effective_cache_price = cache_read_price if cache_read_price > 0 else in_price
    billed_input = input_tokens - cached_tokens
    cost = (
        billed_input * in_price
        + cached_tokens * effective_cache_price
        + output_tokens * out_price
    ) / 1_000_000

    window = _matched_window(price, at)
    discount = 1.0
    if window is not None:
        try:
            discount = max(0.0, float(window.get("discount", 1.0)))
        except (TypeError, ValueError):
            discount = 1.0
    cost = round(cost * discount, 8)

    snapshot = {
        "price_id": str(price.id),
        "input_per_1m": in_price,
        "output_per_1m": out_price,
        "cache_read_per_1m": cache_read_price,
        "currency": price.currency or "CNY",
        "tier_min_input_tokens": tier_min,
        "time_discount": discount,
        "time_window": window,
        "effective_from": price.effective_from.isoformat() if price.effective_from else None,
        "source_note": price.source_note or "",
    }
    return cost, snapshot


__all__ = [
    "compute_cost",
    "estimate_tokens",
    "estimate_tokens_many",
    "provider_host",
    "resolve_price",
]
