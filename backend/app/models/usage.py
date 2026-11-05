"""Token 计量与成本记账模型。

- LLMModelPrice：版本化模型价格表（按 base_url 域名 + 模型名匹配，effective_from 生效，
  支持上下文长度阶梯 tiers 与分时段折扣 time_windows）；调价**新增行**而非改旧行，
  历史记账行冻结单价快照，保证账本可审计、不被后续调价改写。
- LLMUsageEvent：一笔模型调用（chat / embedding / rerank）的记账行。
  source=provider（厂商返回 usage）| estimated（本地估算）| local（本机模型，无费用）。
- LLMUsageMonthly：明细超过保留期后仍永久保留的月度汇总。
- LLMUsageReconciliation：月度厂商账单对账记录（账本 vs 账单差异）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LLMModelPrice(Base):
    """模型价格（版本化）：host+model 匹配，effective_from 后生效。"""

    __tablename__ = "llm_model_prices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 匹配规则：provider_host 为空=任意网关；model_pattern 为空=任意模型，支持前缀匹配
    provider_host: Mapped[str] = mapped_column(String(128), default="", index=True)
    model_pattern: Mapped[str] = mapped_column(String(128), default="", index=True)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    # 单价：每 1M tokens（人民币/美元，按 currency）
    input_per_1m: Mapped[float] = mapped_column(Float, default=0.0)
    output_per_1m: Mapped[float] = mapped_column(Float, default=0.0)
    cache_read_per_1m: Mapped[float] = mapped_column(Float, default=0.0)
    cache_write_per_1m: Mapped[float] = mapped_column(Float, default=0.0)
    # 阶梯：[{"min_input_tokens":0,"input_per_1m":..,"output_per_1m":..}, ...]
    tiers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 分时折扣（UTC）：[{"start":"16:30","end":"00:30","discount":0.5}, ...]
    # 可选 weekdays 限定星期（0=周一..6=周日），如工作日高峰加价：
    # {"start":"01:00","end":"04:00","discount":2.0,"weekdays":[0,1,2,3,4]}
    time_windows: Mapped[list | None] = mapped_column(JSON, nullable=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # 来源备注（官网价目/商务报价/对账单核对日期），供审计
    source_note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMUsageEvent(Base):
    """单笔模型调用记账行（成本按写入时的价格快照计算，之后调价不影响历史行）。"""

    __tablename__ = "llm_usage_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    span_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    # chat / embedding / rerank
    kind: Mapped[str] = mapped_column(String(16), default="chat", index=True)
    # agent / report / evaluation / assignment / feedback / parent_service / embedding / rerank
    module: Mapped[str] = mapped_column(String(32), default="", index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    config_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # True=平台共享 Key（机构成本）；False=教师自配 Key（个人成本）
    is_platform: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    provider_host: Mapped[str] = mapped_column(String(128), default="", index=True)
    model: Mapped[str] = mapped_column(String(128), default="", index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # provider | estimated | local
    source: Mapped[str] = mapped_column(String(12), default="provider", index=True)
    price_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # 冻结的单价快照（含命中的阶梯/时段/币种），供审计与重算核对
    price_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    # priced | unpriced（无价格行/未知模型，不臆造费用）
    priced_status: Mapped[str] = mapped_column(String(16), default="priced", index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    # ok | error
    status: Mapped[str] = mapped_column(String(16), default="ok", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LLMUsageMonthly(Base):
    """月度汇总（明细保留期到期清理前落库，永久保留）。"""

    __tablename__ = "llm_usage_monthly"
    __table_args__ = (UniqueConstraint("month", "currency", name="uq_llm_usage_month_currency"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    events: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_total: Mapped[float] = mapped_column(Float, default=0.0)
    cost_platform: Mapped[float] = mapped_column(Float, default=0.0)
    cost_teacher: Mapped[float] = mapped_column(Float, default=0.0)
    unpriced_events: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LLMUsageReconciliation(Base):
    """月度厂商账单对账（同一月同一供应商一条，记录账单金额与备注）。"""

    __tablename__ = "llm_usage_reconciliations"
    __table_args__ = (UniqueConstraint("month", "provider", name="uq_llm_usage_recon_month"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    provider: Mapped[str] = mapped_column(String(64), default="")
    billed_amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = [
    "LLMModelPrice",
    "LLMUsageEvent",
    "LLMUsageMonthly",
    "LLMUsageReconciliation",
]
