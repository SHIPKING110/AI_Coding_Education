"""全局个性化设置（单例行 id=1）：管理员设置，全局生效。

- login_theme: 登录页主题（default/light/dark/poster）
- desktop_bg: 桌面背景（default/纯色/图片 URL）
- ui_theme: 系统主题风格（default/fresh/calm/warm）
- login_title/login_subtitle: 登录页主标题/副标题（可自定义）
- login_logo: 登录页 Logo（emoji 或图片 URL；空则用默认闪电图标）
- login_accent: 登录页强调色（按钮/高亮；空则跟随主题默认）
- login_hero: 登录页海报副文案（poster 主题左侧底部一行；空则用默认）
- sidebar_sub: 侧边栏英文副标题（默认 Child Code Studio）
- sidebar_theme: 侧边栏风格（navy/light/brand）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    login_theme: Mapped[str] = mapped_column(String(32), default="default")
    desktop_bg: Mapped[str] = mapped_column(String(512), default="default")
    ui_theme: Mapped[str] = mapped_column(String(32), default="default")
    login_title: Mapped[str] = mapped_column(String(64), default="智能少儿编程教育")
    login_subtitle: Mapped[str] = mapped_column(
        String(128), default="教务管理系统 · 教师效率提升 家长服务闭环"
    )
    login_logo: Mapped[str] = mapped_column(String(512), default="")
    login_accent: Mapped[str] = mapped_column(String(32), default="")
    login_hero: Mapped[str] = mapped_column(String(128), default="排课 · 考勤 · 课时 · 反馈，一站式教务")
    sidebar_sub: Mapped[str] = mapped_column(String(64), default="Child Code Studio")
    sidebar_theme: Mapped[str] = mapped_column(String(16), default="navy")
    # 侧边栏模块排序：navKey 数组 JSON，空表示默认顺序
    nav_order: Mapped[str] = mapped_column(Text, default="[]")
    # 家长客服配额与高风险词表（设置页可改；沿用单例行模式）
    parent_anon_daily_limit: Mapped[int] = mapped_column(Integer, default=3)
    parent_daily_limit: Mapped[int] = mapped_column(Integer, default=50)
    # 高风险词表 JSON 数组字符串（退费/收费/安全类，命中强制转人工）
    parent_risk_words: Mapped[str] = mapped_column(
        Text,
        default='["退费", "收费", "价格", "安全", "受伤", "事故", "投诉", "报警", "律师", "骨折", "过敏"]',
    )
    # 教师快捷回复 JSON 数组字符串（F8 低优，默认空）
    parent_quick_replies: Mapped[str] = mapped_column(Text, default="[]")
    # 会话自动关闭阈值（小时）：open 会话闲置 / escalated 会话闲置 → 自动结束
    parent_open_idle_hours: Mapped[int] = mapped_column(Integer, default=24)
    parent_escalated_idle_hours: Mapped[int] = mapped_column(Integer, default=48)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["SystemSetting"]
