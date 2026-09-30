"""季度/年度总结 PPT 构建服务（M3）。

- 使用 python-pptx 从报告 content(stats) 构建标准 16:9 简报
- 版式约定（简洁模板）：封面页 + 目录页 + 数据概览页 + 各内容小节 + 结尾
- 产物返回相对路径，由调用方写入 reports.ppt_url 并从 /uploads 静态服务

设计令牌与前端一致：品牌 indigo→cyan、白色背景、深色文字。
"""

import re
import uuid
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from app.core.config import get_settings
from app.services.llm import clean_listish_text

# 品牌色板 — 与前端 App.vue 设计令牌对齐（2026 精炼版）
BRAND = RGBColor(0x61, 0x5F, 0xFF)  # #615FFF 主品牌
BRAND_SOFT = RGBColor(0xEE, 0xF2, 0xFF)
BRAND_DEEP = RGBColor(0x31, 0x2E, 0x81)
CYAN = RGBColor(0x00, 0xB8, 0xDB)  # #00B8DB 天青
CYAN_SOFT = RGBColor(0xEC, 0xFE, 0xFF)
INK = RGBColor(0x0F, 0x17, 0x2A)
INK_SOFT = RGBColor(0x62, 0x74, 0x8E)
INK_LIGHT = RGBColor(0x90, 0xA1, 0xB9)
PAPER = RGBColor(0xFF, 0xFF, 0xFF)
CARD_BG = RGBColor(0xF8, 0xFA, 0xFF)
LINE_SOFT = RGBColor(0xE2, 0xE8, 0xF0)
_AMBER = RGBColor(0xF5, 0x9E, 0x0B)
_GREEN = RGBColor(0x10, 0xB9, 0x81)
_PURPLE = RGBColor(0xA8, 0x55, 0xF7)
_DEEP = BRAND_DEEP

EMU_W = Inches(13.333)  # 16:9
EMU_H = Inches(7.5)

# 圆角能力条 / 数据卡统一半径（EMU）
ABILITY_RADIUS = Inches(0.10)
CARD_RADIUS = Inches(0.16)
QUOTE_RADIUS = Inches(0.12)


def _blank_slide(prs: Presentation):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _rect(slide, x, y, w, h, *, color, line=False):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    if line:
        shape.line.color.rgb = color
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def _rounded_rect(slide, x, y, w, h, *, color, radius=CARD_RADIUS, line=False,
                  line_color=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    if line:
        shape.line.color.rgb = line_color or color
        shape.line.width = Pt(0.75)
    else:
        shape.line.fill.background()
    try:
        shape.adjustments[0] = 0.12
    except Exception:
        pass
    shape.shadow.inherit = False
    return shape


def _pill(slide, x, y, w, h, *, color):
    shape = _rounded_rect(slide, x, y, w, h, color=color, radius=h / 2)
    try:
        shape.adjustments[0] = 0.5
    except Exception:
        pass
    return shape


def _text(slide, x, y, w, h, text, *, size, color=INK, bold=False, align=PP_ALIGN.LEFT,
          anchor=MSO_ANCHOR.TOP, wrap=True, line_spacing=None):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = align
    p.text = text
    if line_spacing is not None and hasattr(p, "line_spacing"):
        p.line_spacing = line_spacing
    for run in p.runs:
        run.font.size = Pt(size)
        run.font.color.rgb = color
        run.font.bold = bold
        run.font.name = "微软雅黑"
    return box


def _text_height_in(
    text: str, *, font_pt: float, box_w_in: float, line_spacing: float = 1.3
) -> float:
    """估算文本在给定宽度文本框内的高度（英寸）：CJK 字宽≈字号，行高≈1.3×字号。"""
    if not text:
        return 0.0
    char_w_in = font_pt / 72.0
    per_line = max(1, int(box_w_in / char_w_in))
    lines = 0
    for para in str(text).splitlines() or [str(text)]:
        lines += max(1, -(-len(para) // per_line))
    return lines * (font_pt * line_spacing) / 72.0


def _fit_size(text: str, *, box_w_in: float, box_h_in: float, max_pt: float,
              min_pt: float = 12.0, line_spacing: float = 1.3) -> float:
    """在框内放下全部文本所需的最大字号；放不下则逐级缩小，仍不行取下限。"""
    size = max_pt
    while size > min_pt:
        h = _text_height_in(text, font_pt=size, box_w_in=box_w_in, line_spacing=line_spacing)
        if h <= box_h_in:
            return size
        size -= 1.0
    return min_pt


def _truncated_lines(items: list[str], *, box_w_in: float, box_h_in: float, font_pt: float,
                     line_spacing: float = 1.3) -> list[str]:
    """按可容纳的总行数截断条目列表：放不下的行丢弃，最后一行以「…」收尾。"""
    char_w_in = font_pt / 72.0
    per_line = max(1, int(box_w_in / char_w_in))
    max_lines = max(1, int(box_h_in / ((font_pt * line_spacing) / 72.0)))
    out: list[str] = []
    used = 0
    for item in items:
        para = str(item)
        wrapped = [para[i:i + per_line] for i in range(0, len(para), per_line)] or [""]
        room = max_lines - used
        if room <= 0:
            break
        if len(wrapped) > room:
            out.append(wrapped[room - 1][: max(0, per_line - 1)] + "…")
            used += room
            break
        out.extend(wrapped)
        used += len(wrapped)
    return out or [items[0][: max(0, per_line - 1)] + "…" if items else ""]


def _bullets(slide, x, y, w, h, items, *, size=15, color=INK, accent=BRAND,
             bullet_gap=10, auto_fit=True):
    """条目列表：胶囊圆点 + 自动缩字截断；每条前置彩色圆点。"""
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    box_w_in = w / 914400
    box_h_in = h / 914400
    real_size = size
    bullet_color = accent if accent else color
    if auto_fit:
        joined = "\n".join(str(i) for i in items)
        real_size = _fit_size(joined, box_w_in=box_w_in, box_h_in=box_h_in, max_pt=size)
        if real_size <= min(size, 12.0) + 0.01:
            items = _truncated_lines([str(i) for i in items], box_w_in=box_w_in,
                                     box_h_in=box_h_in, font_pt=real_size)
    first = True
    for item in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_after = Pt(bullet_gap)
        if hasattr(p, "line_spacing"):
            p.line_spacing = 1.18
        # 彩色圆点 + 文本 双 run
        r_dot = p.add_run()
        r_dot.text = "●  "
        r_dot.font.size = Pt(max(8, real_size - 5))
        r_dot.font.color.rgb = bullet_color
        r_dot.font.name = "微软雅黑"
        r_txt = p.add_run()
        r_txt.text = str(item)
        r_txt.font.size = Pt(real_size)
        r_txt.font.color.rgb = color
        r_txt.font.name = "微软雅黑"
    return box


def _quote_block(slide, x, y, w, h, *, bg=CARD_BG, accent=BRAND):
    """引用块底板：柔和底色 + 左侧彩色竖条（圆角）。"""
    bg_shape = _rounded_rect(slide, x, y, w, h, color=bg, radius=QUOTE_RADIUS)
    _rect(slide, x, y, Inches(0.08), h, color=accent)
    return bg_shape


def _color_for(text, fallback):
    if text.startswith("• "):
        return fallback
    return fallback


def _header(slide, kicker: str, title: str, *, brand=BRAND, soft=BRAND_SOFT, accent=CYAN) -> None:
    """页眉：左侧品牌竖条 + 胶囊 kicker + 标题 + 主题下划线（agent-theme-chat 真换肤）。"""
    _rect(slide, 0, 0, Inches(0.14), Inches(7.5), color=brand)
    pill_w = Inches(max(1.15, len(kicker) * 0.11 + 0.5))
    _pill(slide, Inches(0.7), Inches(0.42), pill_w, Inches(0.32), color=soft)
    _text(slide, Inches(0.7), Inches(0.44), pill_w, Inches(0.28), kicker,
          size=10.5, color=brand, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _text(slide, Inches(0.7), Inches(0.84), Inches(12), Inches(0.7), title,
          size=28, color=INK, bold=True)
    _pill(slide, Inches(0.7), Inches(1.64), Inches(1.4), Inches(0.06), color=accent)


def build_summary_ppt(
    *,
    title: str,
    period_label: str,
    teacher_name: str,
    created_at: datetime,
    content: dict,
    stats: dict | None,
    report_type: str = "quarterly",
    quarter_summaries: list[dict] | None = None,
    table_breakdown: list[dict] | None = None,
    include_sections: dict[str, list[int]] | None = None,
) -> str:
    """构建季度/年度总结 PPT，返回相对路径（uploads/ppt/<uuid>.pptx）。

    - stats 与 table_breakdown 均为调用方传入的已保存快照，构建器只做展示、不重算
    - quarterly：封面/目录/数据总览表/月度柱状图/总体/亮点/问题/计划/数据说明/行动收束
    - yearly：封面/目录/季度对照表/季度柱状图/季度回顾卡/数据故事/行动收束
      （长文字只进要点卡/散文页，数字只进表与图，互不混排）
    - include_sections：要点类字段勾选入页的条目下标；key 缺席=全选，空列表=整段跳过
    """
    def _pick(field: str, items: list[str]) -> list[str]:
        if include_sections is None:
            return items
        if field not in include_sections:
            return items
        wanted = {int(i) for i in (include_sections.get(field) or [])}
        return [t for i, t in enumerate(items) if i in wanted]
    prs = Presentation()
    prs.slide_width = EMU_W
    prs.slide_height = EMU_H

    stats = stats or {}
    c = content or {}
    is_yearly = report_type == "yearly"
    kicker_prefix = "ANNUAL" if is_yearly else "QUARTERLY"
    footer_label = "ANNUAL REVIEW" if is_yearly else "QUARTERLY REVIEW"

    # 1) 封面 — 浅色卡片化封面 + 胶囊 period + 品牌线 + 关键指标条（取自已保存快照）
    s = _blank_slide(prs)
    _rect(s, 0, 0, EMU_W, EMU_H, color=CARD_BG)
    # 装饰圆角卡
    _rounded_rect(s, Inches(0.7), Inches(1.15), Inches(11.9), Inches(4.0),
                  color=PAPER, line=True, line_color=LINE_SOFT)
    # 顶部胶囊 period
    if period_label:
        pw = Inches(max(2.0, len(period_label) * 0.12 + 0.6))
        _pill(s, Inches(1.15), Inches(1.42), pw, Inches(0.32), color=BRAND_SOFT)
        _text(s, Inches(1.15), Inches(1.44), pw, Inches(0.28), period_label,
              size=11, color=BRAND, bold=True, align=PP_ALIGN.CENTER,
              anchor=MSO_ANCHOR.MIDDLE)
    _text(s, Inches(1.15), Inches(1.92), Inches(11), Inches(1.5), title or "工作总结",
          size=38, color=INK, bold=True)
    _pill(s, Inches(1.15), Inches(3.55), Inches(1.5), Inches(0.06), color=CYAN)
    _text(s, Inches(1.15), Inches(3.72), Inches(11), Inches(0.5),
          f"汇报人：{teacher_name}   ·   生成时间：{created_at.strftime('%Y-%m-%d')}",
          size=13, color=INK_SOFT)
    # 封面关键指标条：消耗课时 / 达标率 / 出勤率 / 篇数（季度=周报数，年度=季度数）
    consumed = stats.get("consumed_lessons", 0)
    achieve = f"{(stats.get('achievement_rate') or 0) * 100:.1f}%"
    attend_rate = f"{(stats.get('attendance_rate') or 0) * 100:.1f}%"
    count_label = "季度总结" if is_yearly else "已发布周报"
    count_val = stats.get("quarterly_count", 0) if is_yearly else stats.get("weekly_count", 0)
    cover_metrics = (
        f"消耗课时 {consumed} 节   ·   达标率 {achieve}   ·   "
        f"出勤率 {attend_rate}   ·   {count_label} {count_val} 篇"
    )
    _text(s, Inches(1.15), Inches(4.35), Inches(11), Inches(0.55),
          cover_metrics, size=12.5, color=BRAND, bold=True)

    # 1b) 目录页：数据只进表/图、文字只进要点，页页有分工
    toc_items = (
        ["数据总览", "季度趋势", "季度回顾", "数据故事", "总体情况",
         "主要亮点", "问题与改进", "下阶段计划", "数据说明", "行动收束"]
        if is_yearly
        else ["数据总览", "月度趋势", "总体情况", "主要亮点",
              "问题与改进", "下阶段计划", "数据说明", "行动收束"]
    )
    s = _blank_slide(prs)
    _header(s, f"{kicker_prefix} · OUTLINE", "本页讲什么")
    _point_cards(s, toc_items, accent=CYAN)

    # 2) 数据总览表（替代纯数字卡：指标/数值/单位三列，可逐行核对）
    s = _blank_slide(prs)
    _header(s, f"{kicker_prefix} · DATA", "数据总览")
    _summary_table(
        s,
        ["指标", "数值", "说明"],
        [
            ["当前学员", f"{stats.get('current_students', 0)} 人", "期间末在读"],
            ["已完成排课", f"{stats.get('schedules', 0)} 节", "期间已完成"],
            ["上课人次", f"{stats.get('attended', 0)} 人次", "已到考勤"],
            ["缺课人次", f"{stats.get('leave', 0)} 人次", "请假考勤"],
            ["出勤率", f"{(stats.get('attendance_rate') or 0) * 100:.1f}%", "上课/应到"],
            ["应耗课时", f"{stats.get('expected_lessons', 0)} 节", "应到×2"],
            ["消耗课时", f"{stats.get('consumed_lessons', 0)} 节", "已到×2"],
            ["达标率", f"{(stats.get('achievement_rate') or 0) * 100:.1f}%", "消耗/应耗"],
            ["新增学员", f"{stats.get('new_students', 0)} 人", "期间新建"],
        ],
        widths=[0.34, 0.30, 0.36],
        aligns=["left", "right", "left"],
        source_note="来源：报告已保存统计快照（保存时写入 stats，PPT 不再重算）",
    )

    # 2b) 明细表：季度=逐月明细，年度=季度对照（调用方传入已保存快照的行）
    if table_breakdown:
        s = _blank_slide(prs)
        if is_yearly:
            _header(s, "ANNUAL · QUARTERS TABLE", "季度对照")
            _summary_table(
                s,
                ["季度", "消耗/应耗", "出勤率", "一句话"],
                [
                    [
                        r.get("label", ""),
                        f"{r.get('consumed_lessons', 0)}/{r.get('expected_lessons', 0)}",
                        f"{(r.get('attendance_rate') or 0) * 100:.1f}%",
                        str(r.get("summary") or "")[:42],
                    ]
                    for r in table_breakdown[:4]
                ],
                widths=[0.16, 0.24, 0.16, 0.44],
                aligns=["center", "center", "center", "left"],
                source_note="来源：各季度总结已保存 stats + 总体情况首句",
            )
        else:
            _header(s, f"{kicker_prefix} · MONTHLY", "逐月明细")
            _summary_table(
                s,
                ["月份", "消耗/应耗", "上课人次", "新增"],
                [
                    [
                        r.get("month", ""),
                        f"{r.get('consumed_lessons', 0)}/{r.get('expected_lessons', 0)}",
                        r.get("attendance", 0),
                        r.get("new_students", 0),
                    ]
                    for r in table_breakdown
                ],
                widths=[0.22, 0.30, 0.24, 0.24],
                aligns=["center", "center", "center", "center"],
                source_note="来源：报告已保存统计快照的逐月行（PPT 不再重算）",
            )

    # 2c) 趋势柱状图：数字可视化，避免“文字套数据”
    breakdown_rows = table_breakdown or []
    if breakdown_rows:
        if is_yearly:
            _bar_chart_slide(
                prs,
                kicker=f"{kicker_prefix} · TREND",
                title="季度趋势",
                labels=[str(r.get("label") or "")[:14] for r in breakdown_rows[:4]],
                consumed=[int(r.get("consumed_lessons") or 0) for r in breakdown_rows[:4]],
                expected=[int(r.get("expected_lessons") or 0) for r in breakdown_rows[:4]],
                note="各季度消耗 vs 应耗课时（来源：已保存快照）",
            )
        else:
            _bar_chart_slide(
                prs,
                kicker=f"{kicker_prefix} · TREND",
                title="月度趋势",
                labels=[str(r.get("month") or "") for r in breakdown_rows],
                consumed=[int(r.get("consumed_lessons") or 0) for r in breakdown_rows],
                expected=[int(r.get("expected_lessons") or 0) for r in breakdown_rows],
                note="各月消耗 vs 应耗课时（来源：已保存快照）",
            )

    if is_yearly:
        # 3a) 年度专属：季度回顾 Q1-Q4（一页四卡，具体内容来自季度总结）
        s = _blank_slide(prs)
        _header(s, "ANNUAL · QUARTERS", "季度回顾")
        _quarter_review_cards(s, quarter_summaries or [])
        # 3b) 年度专属：数据故事（达标率/出勤率一句话解读，非纯数字卡）
        _section_slide(prs, "ANNUAL · STORY", "数据故事",
                       _data_story_text(stats, c.get("stats_notes")),
                       BRAND, style="prose", brand=BRAND, soft=BRAND_SOFT, line=LINE_SOFT)

    # 4) 总体情况（散文卡）+ 要点卡（按勾选分流：只进勾选条目，数字只进表/图）
    _section_slide(prs, f"{kicker_prefix} · SUMMARY", "总体情况",
                   c.get("summary") or "", INK, style="prose")
    _section_slide(prs, f"{kicker_prefix} · HIGHLIGHTS", "主要亮点",
                   _pick("highlights", _split_list_text(c.get("highlights") or "")), CYAN)
    pp_amber = RGBColor(0xF5, 0x9E, 0x0B)
    _section_slide(prs, f"{kicker_prefix} · PROBLEMS", "问题与改进方向",
                   _pick("problems", _split_list_text(c.get("problems") or "")), pp_amber)
    _section_slide(prs, f"{kicker_prefix} · NEXT", "下阶段计划",
                   _pick("next_plan", _split_list_text(c.get("next_plan") or "")), CYAN)
    _section_slide(prs, f"{kicker_prefix} · DATA NOTE", "数据说明",
                   c.get("stats_notes") or "", BRAND, style="prose")

    # 5) 行动收束页：勾选的下阶段计划前 3 条（未勾选时用勾选结果，去套话）
    next_items = _pick("next_plan", _split_list_text(c.get("next_plan") or ""))[:3]
    s = _blank_slide(prs)
    _rect(s, 0, 0, EMU_W, EMU_H, color=RGBColor(0xEE, 0xF2, 0xFF))
    _text(s, Inches(1.2), Inches(1.6), Inches(11), Inches(0.8),
          "下阶段 · 3 件事" if next_items else title,
          size=36, color=BRAND, bold=True, align=PP_ALIGN.CENTER)
    if next_items:
        _point_cards(s, [f"{t}" for t in next_items], accent=CYAN,
                     y0=Inches(2.8), h=Inches(3.4))
    else:
        _text(s, Inches(1.2), Inches(2.8), Inches(11), Inches(0.6), title,
              size=16, color=INK_SOFT, align=PP_ALIGN.CENTER)

    _add_footers(prs, footer_label)
    # 落盘
    out_dir = Path(get_settings().UPLOAD_DIR) / "ppt"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.pptx"
    path = out_dir / fname
    prs.save(str(path))
    return f"ppt/{fname}"


_SENTENCE_END_RE = re.compile(r"(?<=[。！？!?；;\n])")
_LIST_SEP_RE = re.compile(r"(?<=[；;])\s*|\n+")


def _split_list_text(text: str, max_chars: int = 60) -> list[str]:
    """把「要点列表」文本切成条目：以「；/;」或换行为主分隔符。

    LLM 输出的列表字段规范是「一条完整的一句话 + 分号」，因此只按分号与
    换行切分，句号保留在条内 —— 避免一句话被逗号/句号拆成碎点。
    """
    if not text:
        return []
    items: list[str] = []
    for para in str(text).splitlines():
        para = para.strip()
        if not para:
            continue
        for piece in _LIST_SEP_RE.split(para):
            piece = piece.strip().strip("。；;")
            if piece:
                items.append(piece)
    merged: list[str] = []
    for item in items:
        if merged and len(item) <= 6 and len(merged[-1]) + len(item) <= max_chars:
            merged[-1] += item
        else:
            merged.append(item)
    return merged


def _split_text(text: str, max_chars: int = 60) -> list[str]:
    """长文本按**完整句子**切分为条目列表。

    只以句末标点（。！？；!?;）与换行作为分隔点；逗号、顿号、冒号一律保留
    在句内，由文本框自动换行 —— 避免「一句话被拆成好几个碎点」。
    """
    if not text:
        return []
    items: list[str] = []
    for para in str(text).splitlines():
        para = para.strip()
        if not para:
            continue
        parts = [p.strip() for p in _SENTENCE_END_RE.split(para) if p and p.strip()]
        items.extend(parts)
    # 合并被句号拆得过短的残句（如称呼语后紧跟正文）
    merged: list[str] = []
    for item in items:
        if merged and len(item) <= 6 and len(merged[-1]) + len(item) <= max_chars:
            merged[-1] += item
        else:
            merged.append(item)
    return merged


def _section_slide(  # noqa: E501 - 签名需一次列全主题色参数
    prs, kicker, title, items, accent, *, style="cards", brand=BRAND, soft=BRAND_SOFT, line=LINE_SOFT,
) -> None:
    """内容小节页 — 两种版式（主题色可注入，真换肤）：

    - style="cards"：编号要点卡（每条一句话一张圆角白卡 + 彩色编号胶囊）
    - style="prose"：散文卡（整段文字自然排版，引用块 + 左竖条 + 大引号）
    空内容直接跳过整页，避免只有页眉的空白幻灯片。
    """
    if items is None:
        return
    if isinstance(items, str) and not items.strip():
        return
    if isinstance(items, (list, tuple)) and not any(str(t or "").strip() for t in items):
        return
    s = _blank_slide(prs)
    _header(s, kicker, title, brand=brand, soft=soft, accent=accent)
    if items:
        if style == "prose":
            _prose_card(s, items, accent=accent, line=line)
        else:
            _point_cards(s, items, accent=accent, line=line)
    _pill(s, Inches(0.7), Inches(6.92), Inches(0.9), Inches(0.06), color=accent)


def _prose_card(slide, text, *, accent, y0=Inches(2.0), h=Inches(4.72), compact=False, line=LINE_SOFT) -> None:
    """散文卡：整段文字连贯排版（不做句级拆点），圆角白卡 + 左侧彩色竖条。

    compact=True 时用于矮卡（如能力点评区）：去掉大引号装饰、缩小内边距与字号。
    """
    text = str(text or "").strip()
    if not text:
        return
    x, w = Inches(0.7), Inches(11.9)
    _rounded_rect(slide, x, y0, w, h, color=PAPER, line=True, line_color=line)
    pad_top = Inches(0.12) if compact else Inches(0.35)
    pad_bottom = Inches(0.12) if compact else Inches(0.35)
    _pill(slide, x, y0 + pad_top, Inches(0.07), h - pad_top - pad_bottom, color=accent)
    if not compact:
        # 右上角大引号装饰（柔色，不抢正文）
        _text(slide, x + w - Inches(1.55), y0 + Inches(0.02), Inches(1.1), Inches(1.1),
              "”", size=60, color=line, bold=True, align=PP_ALIGN.RIGHT)
    tx = x + Inches(0.4 if compact else 0.52)
    tw = w - Inches(0.75 if compact else 1.3)
    th = h - Inches(0.24 if compact else 0.86)
    real = _fit_size(
        text, box_w_in=tw / 914400, box_h_in=th / 914400,
        max_pt=13.5 if compact else 17, min_pt=10.5 if compact else 12.5,
        line_spacing=1.5 if compact else 1.6,
    )
    _text(slide, tx, y0 + (Inches(0.12) if compact else Inches(0.43)), tw, th, text,
          size=real, color=INK, anchor=MSO_ANCHOR.MIDDLE, wrap=True,
          line_spacing=1.5 if compact else 1.6)


def _point_cards(slide, items, *, accent, y0=Inches(2.0), h=Inches(4.72), line=LINE_SOFT) -> None:
    """编号要点卡：每条一句话一张圆角白卡 + 彩色编号胶囊；条数多时自动双列。"""
    texts = [str(t).strip() for t in (items or []) if str(t or "").strip()]
    if not texts:
        return
    n = len(texts)
    area_x, area_w = Inches(0.7), Inches(11.9)
    gap = Inches(0.16)
    cols = 1 if n <= 4 else 2
    rows = -(-n // cols)
    col_w = (area_w - gap * (cols - 1)) / cols
    card_h = (h - gap * (rows - 1)) / rows
    badge_s = Inches(0.44)
    for i, text in enumerate(texts):
        r, c = divmod(i, cols)
        x = area_x + (col_w + gap) * c
        y = y0 + (card_h + gap) * r
        _rounded_rect(slide, x, y, col_w, card_h, color=PAPER, line=True,
                      line_color=line)
        badge_x = x + Inches(0.24)
        badge_y = y + (card_h - badge_s) / 2
        _pill(slide, badge_x, badge_y, badge_s, badge_s, color=accent)
        _text(slide, badge_x, badge_y, badge_s, badge_s, f"{i + 1:02d}", size=12,
              color=PAPER, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        tx = badge_x + badge_s + Inches(0.2)
        tw = x + col_w - tx - Inches(0.3)
        th = card_h - Inches(0.28)
        real = _fit_size(
            text, box_w_in=tw / 914400, box_h_in=th / 914400,
            max_pt=15.5, min_pt=10.5, line_spacing=1.28,
        )
        if _text_height_in(text, font_pt=real, box_w_in=tw / 914400,
                           line_spacing=1.28) > th / 914400:
            lines = _truncated_lines(
                [text], box_w_in=tw / 914400, box_h_in=th / 914400,
                font_pt=real, line_spacing=1.28,
            )
            text = "".join(lines)
        _text(slide, tx, y + Inches(0.14), tw, th, text, size=real, color=INK,
              anchor=MSO_ANCHOR.MIDDLE, wrap=True, line_spacing=1.28)


def _data_story_text(stats: dict, stats_notes: str | None) -> str:
    """年度数据故事：达标率/出勤率一句话解读 + 教师数据说明，去纯数字罗列。"""
    s = stats or {}
    achieve = (s.get("achievement_rate") or 0) * 100
    attend = (s.get("attendance_rate") or 0) * 100
    consumed = s.get("consumed_lessons", 0)
    expected = s.get("expected_lessons", 0)
    interpret = (
        f"全年消耗课时 {consumed} 节（应耗 {expected} 节），达标率 {achieve:.1f}%"
        f"{'，整体完成情况良好' if achieve >= 80 else '，仍有提升空间，重点看低达标季度'}；"
        f"出勤率 {attend:.1f}%"
        f"{'，学员到课稳定' if attend >= 85 else '，缺课偏多，建议结合季度回顾找原因'}。"
    )
    note = (stats_notes or "").strip()
    return interpret + (f"\n{note}" if note else "")


def _quarter_review_cards(slide, quarters: list[dict]) -> None:
    """年度季度回顾：一页四卡（Q1-Q4标题+一句话摘要），无季度时给引导文案。"""
    if not quarters:
        _text(slide, Inches(0.9), Inches(2.6), Inches(11.5), Inches(0.8),
              "本年度暂无已发布季度总结，建议先完善各季度总结后再生成年度 PPT。",
              size=16, color=INK_SOFT)
        return
    shown = quarters[:4]
    area_x, area_w = Inches(0.7), Inches(11.9)
    gap = Inches(0.25)
    cols = len(shown)
    card_w = (area_w - gap * (cols - 1)) / cols
    card_h = Inches(4.5)
    y0 = Inches(2.1)
    for i, q in enumerate(shown):
        x = area_x + (card_w + gap) * i
        _rounded_rect(slide, x, y0, card_w, card_h, color=PAPER, line=True,
                      line_color=LINE_SOFT)
        _pill(slide, x + Inches(0.25), y0 + Inches(0.25), Inches(0.9), Inches(0.36),
              color=BRAND_SOFT)
        _text(slide, x + Inches(0.25), y0 + Inches(0.26), Inches(0.9), Inches(0.34),
              str(q.get("label") or f"Q{i + 1}"), size=12, color=BRAND, bold=True,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        _text(slide, x + Inches(0.25), y0 + Inches(0.75), card_w - Inches(0.5),
              Inches(0.7), str(q.get("title") or ""), size=13, color=INK, bold=True)
        summary = str(q.get("summary") or "（该季度暂无摘要）")
        tw = card_w - Inches(0.5)
        th = Inches(3.0)
        real = _fit_size(summary, box_w_in=tw / 914400, box_h_in=th / 914400,
                         max_pt=12.5, min_pt=10, line_spacing=1.35)
        if _text_height_in(summary, font_pt=real, box_w_in=tw / 914400,
                           line_spacing=1.35) > th / 914400:
            summary = "".join(_truncated_lines(
                [summary], box_w_in=tw / 914400, box_h_in=th / 914400,
                font_pt=real, line_spacing=1.35))
        _text(slide, x + Inches(0.25), y0 + Inches(1.5), tw, th, summary,
              size=real, color=INK_SOFT, line_spacing=1.35)


def _add_footers(prs, label: str) -> None:
    """为除封面外的每页添加页脚：左侧章节标签，右侧页码。"""
    total = len(prs.slides._sldIdLst)  # noqa: SLF001 - python-pptx 无公开 count
    if total <= 1:
        return
    for idx, slide in enumerate(prs.slides, start=1):
        if idx == 1:
            continue
        _text(slide, Inches(0.7), Inches(7.16), Inches(9.0), Inches(0.26), label,
              size=9, color=INK_LIGHT)
        _text(slide, Inches(10.4), Inches(7.16), Inches(2.2), Inches(0.26),
              f"{idx:02d} / {total:02d}", size=9, color=INK_LIGHT,
              align=PP_ALIGN.RIGHT)


# ---------------------------------------------------------------------------
# M6 家长会 PPT：单学员综合评估（FR-EV-05）
# ---------------------------------------------------------------------------

_ABILITY_LEVELS = ("待观察", "需加强", "良好", "优秀", "非常优秀")


def _level_text(level: int) -> str:
    try:
        lv = int(level)
    except (TypeError, ValueError):
        lv = 3
    lv = max(1, min(5, lv))
    return _ABILITY_LEVELS[lv - 1]


def build_parent_meeting_ppt(
    *,
    student_name: str,
    period_label: str,
    class_label: str,
    teacher_name: str,
    created_at: datetime,
    title: str | None,
    content: dict,
    stats: dict | None,
) -> str:
    """构建家长会 · 单学员综合评估 PPT，返回相对路径（uploads/ppt/<uuid>.pptx）。

    页面：封面（学员/周期）→ 数据概览 → 综合表现 → 学科能力（能力条）→
    进步亮点 → 待提升 → 家长建议 → 结尾。
    """
    prs = Presentation()
    prs.slide_width = EMU_W
    prs.slide_height = EMU_H

    stats = stats or {}
    c = content or {}
    subjects = c.get("subjects") or []
    ppt_title = title or f"{student_name} 学习评估"

    # 1) 封面 — 浅卡背景 + 胶囊标签 + 圆角白卡
    s = _blank_slide(prs)
    _rect(s, 0, 0, EMU_W, EMU_H, color=CARD_BG)
    _rounded_rect(s, Inches(0.7), Inches(1.1), Inches(11.9), Inches(4.2),
                  color=PAPER, line=True, line_color=LINE_SOFT)
    _pill(s, Inches(1.12), Inches(1.42), Inches(2.35), Inches(0.32), color=BRAND_SOFT)
    _text(s, Inches(1.12), Inches(1.44), Inches(2.35), Inches(0.28),
          "家长会 · 学员综合评估", size=11, color=BRAND, bold=True,
          align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _text(s, Inches(1.12), Inches(1.95), Inches(11), Inches(1.2), student_name,
          size=44, color=INK, bold=True)
    _text(s, Inches(1.12), Inches(3.15), Inches(11), Inches(0.6), ppt_title,
          size=20, color=INK_SOFT)
    meta_parts = [
        p for p in [period_label, class_label, teacher_name and f"教师：{teacher_name}"] if p
    ]
    _text(s, Inches(1.12), Inches(3.85), Inches(11), Inches(0.6),
          "   ·   ".join(meta_parts) + f"   ·   生成时间：{created_at.strftime('%Y-%m-%d')}",
          size=13, color=INK_LIGHT)
    _pill(s, Inches(1.12), Inches(4.62), Inches(1.4), Inches(0.05), color=CYAN)

    # 2) 数据概览（学员周期）— 圆角数据卡
    s = _blank_slide(prs)
    _header(s, "DATA SNAPSHOT", f"{student_name} 周期学习数据")
    attended = stats.get("attended", 0)
    leave = stats.get("leave", 0)
    _stat_cards(s, [
        ("出勤率", f"{stats.get('attendance_rate', 0) * 100:.0f}%", f"到课 {attended} 次"),
        ("消耗课时", stats.get("consumed_lessons", 0), "节"),
        ("已发布反馈", stats.get("feedback_count", 0), "篇"),
        ("作业批改", stats.get("homework_count", 0), "份"),
        ("作业得分率", _score_rate_text(stats.get("homework_score_rate")), ""),
        ("请假", leave, "次"),
    ])

    # 3) 综合表现
    _section_slide(prs, "SUMMARY", "综合表现",
                   _split_text(c.get("summary") or "（暂无综合表现总结）"), BRAND)

    # 4) 学科能力（圆角胶囊能力条 + 点评）
    s = _blank_slide(prs)
    _header(s, "ABILITIES", "学科能力")
    if not subjects:
        _text(s, Inches(0.9), Inches(2.4), Inches(11.5), Inches(0.6),
              "（暂无能力条目）", size=16, color=INK_SOFT)
    else:
        shown_subjects = subjects[:6]
        y0 = Inches(2.0)
        y0_in = 2.0
        bottom_in = 7.1
        row_h_in = min(1.02, (bottom_in - y0_in) / len(shown_subjects))
        row_h = Inches(row_h_in)
        name_pt = 17 if row_h_in >= 0.95 else 14
        track_h = Inches(0.22)
        for i, sub in enumerate(shown_subjects):
            name = str(sub.get("name") or "能力项")
            try:
                lv = max(1, min(5, int(sub.get("level", 3))))
            except (TypeError, ValueError):
                lv = 3
            comment = str(sub.get("comment") or "")
            y = y0 + row_h * i
            _text(s, Inches(0.9), y, Inches(2.2), Inches(row_h_in * 0.42), name,
                  size=name_pt, color=INK, bold=True)
            bar_x = Inches(3.35)
            bar_w = Inches(5.55)
            pct = lv / 5.0
            _pill(s, bar_x, y + Inches(0.06), bar_w, track_h, color=RGBColor(0xE2, 0xE8, 0xF0))
            if pct > 0.04:
                fw = max(bar_w * pct, Inches(0.28))
                _pill(s, bar_x, y + Inches(0.06), fw, track_h, color=BRAND)
            _text(s, Inches(9.12), y, Inches(3.0), Inches(row_h_in * 0.42),
                  f"{lv} · {_level_text(lv)}", size=12.5, color=BRAND, bold=True)
            if comment:
                comment_y = y + Inches(row_h_in * 0.42)
                comment_h = Inches(row_h_in * 0.56)
                _bullets(
                    s, Inches(3.35), comment_y, Inches(8.5), comment_h,
                    _split_text(comment), size=11.5, color=INK_SOFT,
                    accent=BRAND, bullet_gap=0,
                )

    # 5) 进步亮点 / 待提升（编号要点卡）
    _section_slide(prs, "PROGRESS", "进步亮点",
                   _split_list_text(clean_listish_text(c.get("progress")) or "（暂无进步记录）"), CYAN)
    pp_amber = RGBColor(0xF5, 0x9E, 0x0B)
    _section_slide(prs, "TO IMPROVE", "待提升项",
                   _split_list_text(clean_listish_text(c.get("to_improve")) or "（暂无待提升项）"),
                   pp_amber)

    # 6) 家长建议（编号要点卡）
    _section_slide(prs, "SUGGESTIONS", "给家长的建议",
                   _split_list_text(clean_listish_text(c.get("suggestions")) or "（暂无建议）"), BRAND)

    # 7) 结尾
    s = _blank_slide(prs)
    _rect(s, 0, 0, EMU_W, EMU_H, color=RGBColor(0xEE, 0xF2, 0xFF))
    _text(s, Inches(1.2), Inches(2.8), Inches(11), Inches(0.8),
          f"谢谢关注 {student_name} 的成长", size=36, color=BRAND, bold=True, align=PP_ALIGN.CENTER)
    _text(s, Inches(1.2), Inches(4.0), Inches(11), Inches(0.6),
          "让我们一起见证每一次进步", size=16, color=INK_SOFT, align=PP_ALIGN.CENTER)

    _add_footers(prs, f"{student_name} · 学习评估")
    out_dir = Path(get_settings().UPLOAD_DIR) / "ppt"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.pptx"
    path = out_dir / fname
    prs.save(str(path))
    return f"ppt/{fname}"


def _score_rate_text(rate) -> str:
    """得分率 0-1 -> 百分比文本；空/None -> 暂无。"""
    if rate is None:
        return "暂无"
    try:
        return f"{float(rate) * 100:.0f}%"
    except (TypeError, ValueError):
        return "暂无"


# ---------------------------------------------------------------------------
# 对话式定制 PPT（PptBuilderDrawer）：按对话确认的 slides 规格构建
# ---------------------------------------------------------------------------

_THEMES = {
    "brand": (BRAND, BRAND_SOFT, CYAN),
    "cyan": (CYAN, CYAN_SOFT, BRAND),
    "deep": (BRAND_DEEP, BRAND_SOFT, CYAN),
}


def _auto_data_slides(stats: dict, breakdown: list[dict]) -> list[dict]:
    """始终注入的数据页：核心指标表 + 趋势柱状图（保证统计一定以图表呈现）。"""
    slides: list[dict] = []
    s = stats or {}
    slides.append(
        {
            "kind": "table",
            "kicker": "DATA",
            "title": "数据总览",
            "headers": ["指标", "数值", "说明"],
            "rows": [
                ["当前学员", f"{s.get('current_students', 0)} 人", "期间末在读"],
                ["已完成排课", f"{s.get('schedules', 0)} 节", "期间已完成"],
                ["上课人次", f"{s.get('attended', 0)} 人次", "已到考勤"],
                ["缺课人次", f"{s.get('leave', 0)} 人次", "请假考勤"],
                ["出勤率", f"{(s.get('attendance_rate') or 0) * 100:.1f}%", "上课/应到"],
                ["消耗课时", f"{s.get('consumed_lessons', 0)} 节", "已到×2"],
                ["达标率", f"{(s.get('achievement_rate') or 0) * 100:.1f}%", "消耗/应耗"],
                ["新增学员", f"{s.get('new_students', 0)} 人", "期间新建"],
            ],
            "widths": [0.34, 0.30, 0.36],
            "aligns": ["center", "center", "center"],
            "note": "来源：报告已保存统计快照",
        }
    )
    if breakdown:
        is_monthly = "month" in breakdown[0]
        if is_monthly:
            labels = [str(r.get("month") or "") for r in breakdown]
        else:
            labels = [str(r.get("label") or "") for r in breakdown]
        slides.append(
            {
                "kind": "bar",
                "kicker": "TREND",
                "title": "趋势对比",
                "labels": labels,
                "consumed": [int(r.get("consumed_lessons") or 0) for r in breakdown],
                "expected": [int(r.get("expected_lessons") or 0) for r in breakdown],
                "note": "消耗 vs 应耗课时（来源：已保存快照）",
            }
        )
    return slides


def build_custom_ppt(
    *,
    title: str,
    period_label: str,
    teacher_name: str,
    created_at: datetime,
    stats: dict | None,
    breakdown: list[dict] | None,
    slides: list[dict],
    theme: str = "brand",
) -> str:
    """按对话确认的 slides 规格构建 PPT，返回相对路径。

    - 无论大纲如何，都会注入数据总览表 + 趋势柱状图（统计一定以图表呈现）
    - slides[].kind ∈ cover/stats/table/bar/bullets/prose/end
    - 旧数据缺失时安全降级：空内容页自动跳过
    """
    brand, soft, accent = _THEMES.get(theme or "brand", _THEMES["brand"])
    prs = Presentation()
    prs.slide_width = EMU_W
    prs.slide_height = EMU_H
    stats = stats or {}
    kicker_prefix = "SUMMARY"

    # 封面
    s = _blank_slide(prs)
    _rect(s, 0, 0, EMU_W, EMU_H, color=CARD_BG)
    _rounded_rect(s, Inches(0.7), Inches(1.15), Inches(11.9), Inches(4.0),
                  color=PAPER, line=True, line_color=LINE_SOFT)
    if period_label:
        pw = Inches(max(2.0, len(period_label) * 0.12 + 0.6))
        _pill(s, Inches(1.15), Inches(1.42), pw, Inches(0.32), color=soft)
        _text(s, Inches(1.15), Inches(1.44), pw, Inches(0.28), period_label,
              size=11, color=brand, bold=True, align=PP_ALIGN.CENTER,
              anchor=MSO_ANCHOR.MIDDLE)
    _text(s, Inches(1.15), Inches(1.92), Inches(11), Inches(1.5), title or "工作总结",
          size=38, color=INK, bold=True)
    _pill(s, Inches(1.15), Inches(3.55), Inches(1.5), Inches(0.06), color=accent)
    _text(s, Inches(1.15), Inches(3.72), Inches(11), Inches(0.5),
          f"汇报人：{teacher_name}   ·   生成时间：{created_at.strftime('%Y-%m-%d')}",
          size=13, color=INK_SOFT)

    # 用户大纲中的内容页（跳过 cover/end，数据页交给自动注入）
    user_slides = [sl for sl in (slides or []) if sl.get("kind") not in ("cover", "end")]
    has_data = any(sl.get("kind") in ("stats", "table", "bar") for sl in user_slides)
    ordered = list(user_slides)
    if not has_data:
        ordered = _auto_data_slides(stats, breakdown or []) + ordered

    for sl in ordered:
        kind = sl.get("kind")
        kicker = sl.get("kicker") or kicker_prefix
        stitle = sl.get("title") or ""
        if kind == "stats":
            cards = sl.get("cards") or []
            if not cards:
                continue
            page = _blank_slide(prs)
            _header(page, kicker, stitle, brand=brand, soft=soft, accent=accent)
            _stat_cards(page, [tuple(c) for c in cards], brand=brand, accent=accent)
        elif kind == "table":
            rows = sl.get("rows") or []
            if not rows:
                continue
            page = _blank_slide(prs)
            _header(page, kicker, stitle, brand=brand, soft=soft, accent=accent)
            _summary_table(
                page, sl.get("headers") or [], rows,
                widths=sl.get("widths"), aligns=sl.get("aligns"), source_note=sl.get("note"),
            )
        elif kind == "bar":
            labels = sl.get("labels") or []
            if not labels:
                continue
            _bar_chart_slide(
                prs, kicker=kicker, title=stitle, labels=labels,
                consumed=sl.get("consumed") or [], expected=sl.get("expected") or [],
                note=sl.get("note"),
            )
        elif kind == "prose":
            _section_slide(prs, kicker, stitle, sl.get("text") or "",
                           accent, style="prose", brand=brand, soft=soft)
        else:  # bullets（默认）
            items = sl.get("items") or []
            if isinstance(items, str):
                items = _split_list_text(items)
            if not items:
                continue
            _section_slide(prs, kicker, stitle, items, accent,
                           style="cards", brand=brand, soft=soft)

    # 结尾
    s = _blank_slide(prs)
    _rect(s, 0, 0, EMU_W, EMU_H, color=soft)
    _text(s, Inches(1.2), Inches(2.8), Inches(11), Inches(0.8),
          title or "谢谢", size=36, color=brand, bold=True, align=PP_ALIGN.CENTER)
    _text(s, Inches(1.2), Inches(4.0), Inches(11), Inches(0.6),
          "数据驱动 · 持续改进", size=16, color=INK_SOFT, align=PP_ALIGN.CENTER)

    _add_footers(prs, "SUMMARY REVIEW")
    out_dir = Path(get_settings().UPLOAD_DIR) / "ppt"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.pptx"
    path = out_dir / fname
    prs.save(str(path))
    return f"ppt/{fname}"


# ---------------------------------------------------------------------------
# M6 班级家长会 PPT：以班级为单位，结合全班学员评估汇报（FR-EV-05 班级版）
# ---------------------------------------------------------------------------

_PURPLE = RGBColor(0xA8, 0x55, 0xF7)
_GREEN = RGBColor(0x10, 0xB9, 0x81)
_AMBER = RGBColor(0xF5, 0x9E, 0x0B)
_CARD_BG = RGBColor(0xF1, 0xF5, 0xF9)
_DEEP = RGBColor(0x31, 0x2E, 0x81)


def _stat_cards(slide, cards, *, y0=Inches(2.1), cols=3, brand=BRAND, accent=CYAN, third=None, line=LINE_SOFT):
    """3 列统计卡片网格 — 圆角数据卡 + 顶部彩色描边（主题色可注入）。"""
    third = third if third is not None else _AMBER
    area_x, area_w = Inches(0.7), Inches(11.9)
    gap = Inches(0.25)
    card_w = (area_w - gap * (cols - 1)) / cols
    card_h = Inches(1.5)
    for i, (label, value, unit) in enumerate(cards):
        x = area_x + (card_w + gap) * (i % cols)
        y = y0 + Inches(1.9) * (i // cols)
        _rounded_rect(slide, x, y, card_w, card_h, color=PAPER, line=True,
                      line_color=line)
        _rect(  # 顶部胶囊描边（与卡片圆角一致为视觉连续）
            slide, x, y, card_w, Inches(0.06),
            color=brand if i % 3 == 0 else accent if i % 3 == 1 else third,
        )
        try:
            slide.shapes[-1].adjustments[0] = 0.5
        except Exception:
            pass
        _text(slide, x + Inches(0.3), y + Inches(0.30), card_w - Inches(0.6), Inches(0.4),
              label, size=13, color=INK_SOFT)
        _text(slide, x + Inches(0.3), y + Inches(0.62), card_w - Inches(0.6), Inches(0.7),
              f"{value} {unit}", size=28, color=brand, bold=True)


def _summary_table(
    slide,
    headers: list[str],
    rows: list[list],
    *,
    y0=Inches(2.0),
    h=Inches(4.72),
    widths: list[float] | None = None,
    aligns: list[str] | None = None,
    colormap: dict[int, object] | None = None,
    source_note: str | None = None,
    fills: list[object] | None = None,
) -> None:
    """数据表格：白卡底 + 深色表头 + 斑马纹行，用于替代纯文字罗列关键数据。

    - headers/rows 同长度；数值列建议右对齐，文本列左对齐
    - colormap: {列索引: RGBColor}，用于比率列低/高着色
    - source_note: 表下数据来源小字（如“来源：已保存统计快照”）
    """
    from pptx.enum.text import MSO_ANCHOR as _A
    from pptx.util import Emu as _Emu

    x, w = Inches(0.7), Inches(11.9)
    _rounded_rect(slide, x, y0, w, h, color=PAPER, line=True, line_color=LINE_SOFT)
    n = len(headers)
    if widths:
        shares = list(widths)
    else:
        shares = [1.0 / n] * n
    total_share = sum(shares) or 1.0
    inner_pad = Inches(0.28)
    table_w = w - inner_pad * 2
    head_h = min(Inches(0.62), h * 0.16)
    body_h = h - head_h - (Inches(0.42) if source_note else Inches(0.28))
    gx = x + inner_pad
    gy = y0 + (Inches(0.30) if not source_note else Inches(0.18))
    table_shape = slide.shapes.add_table(len(rows) + 1, n, _Emu(gx), _Emu(gy), _Emu(table_w), _Emu(head_h + body_h))
    table = table_shape.table
    col_ws = [int(table_w * s / total_share) for s in shares]
    for j, cw in enumerate(col_ws):
        table.columns[j].width = _Emu(cw)
    for j, head in enumerate(headers):
        cell = table.cell(0, j)
        cell.vertical_anchor = _A.MIDDLE
        cell.fill.solid()
        cell.fill.fore_color.rgb = BRAND_DEEP
        cell.margin_left = _Emu(Inches(0.12))
        cell.margin_right = _Emu(Inches(0.12))
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        p.text = str(head)
        for run in p.runs:
            run.font.size = Pt(12)
            run.font.bold = True
            run.font.color.rgb = PAPER
            run.font.name = "微软雅黑"
    fills = fills or [PAPER, CARD_BG]
    for i, row in enumerate(rows):
        for j in range(n):
            val = row[j] if j < len(row) else ""
            cell = table.cell(i + 1, j)
            cell.vertical_anchor = _A.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = fills[i % len(fills)]
            cell.margin_left = _Emu(Inches(0.12))
            cell.margin_right = _Emu(Inches(0.12))
            p = cell.text_frame.paragraphs[0]
            align = (aligns[j] if aligns and j < len(aligns) else ("left" if j == 0 else "center"))
            p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[align]
            p.text = str(val)
            color = INK
            if colormap and j in colormap:
                color = colormap[j]
            for run in p.runs:
                run.font.size = Pt(12.5)
                run.font.bold = (j == 0)
                run.font.color.rgb = color
                run.font.name = "微软雅黑"
    if source_note:
        _text(slide, x + inner_pad, y0 + h - Inches(0.36), w - inner_pad * 2, Inches(0.3),
              source_note, size=9.5, color=INK_LIGHT)


def _bar_chart_slide(prs, *, kicker: str, title: str, labels: list[str],
                     consumed: list[int], expected: list[int], note: str | None = None) -> None:
    """趋势柱状图（原生 python-pptx 图表，非图片）：消耗 vs 应耗课时分组对比。

    - 用 clustering 柱状图 + 数据标签，WPS/Office 均可二次编辑数值
    - 行数与表页同源（已保存快照），图与表互相印证
    """
    from pptx.chart.data import ChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION

    labels = [str(x) for x in (labels or [])]
    consumed = [int(v or 0) for v in (consumed or [])]
    expected = [int(v or 0) for v in (expected or [])]
    if not labels:
        return
    s = _blank_slide(prs)
    _header(s, kicker, title)
    data = ChartData()
    data.categories = labels
    data.add_series("消耗课时", tuple(consumed))
    data.add_series("应耗课时", tuple(expected))
    chart_frame = s.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Inches(0.7), Inches(2.0), Inches(11.9), Inches(4.5),
        data,
    )
    chart = chart_frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    try:
        chart.value_axis.has_major_gridlines = True
        chart.value_axis.has_minor_gridlines = False
    except Exception:
        pass
    for series in chart.series:
        try:
            series.has_data_labels = True
            series.data_labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
            series.data_labels.show_value = True
        except Exception:
            pass
    try:
        fills = (BRAND, CYAN)
        for idx, series in enumerate(chart.series):
            fill = series.format.fill
            fill.solid()
            fill.fore_color.rgb = fills[idx % len(fills)]
    except Exception:
        pass
    if note:
        _text(s, Inches(0.7), Inches(6.55), Inches(11.9), Inches(0.3),
              note, size=9.5, color=INK_LIGHT)


def _ability_bars(slide, averages, *, y0=Inches(2.0), brand=BRAND):
    """班级能力平均分 — 圆角胶囊进度条（与前端 ability-bar 一致，主题色可注入）。"""
    if not averages:
        _text(slide, Inches(0.9), y0 + Inches(0.4), Inches(11.5), Inches(0.6),
              "（暂无能力评估数据）", size=16, color=INK_SOFT)
        return y0
    shown = averages[:6]
    y0_in = y0 / 914400
    bottom_in = 6.8
    row_h_in = min(1.02, (bottom_in - y0_in) / len(shown))
    row_h = Inches(row_h_in)
    name_pt = 17 if row_h_in >= 0.95 else 14
    track_h = Inches(0.22)
    for i, (name, avg) in enumerate(shown):
        y = y0 + row_h * i
        _text(slide, Inches(0.9), y, Inches(2.2), Inches(row_h_in * 0.42), name,
              size=name_pt, color=INK, bold=True)
        bar_x = Inches(3.35)
        bar_w = Inches(5.55)
        pct = max(0.0, min(1.0, float(avg) / 5.0))
        # 背景胶囊
        _pill(slide, bar_x, y + Inches(0.06), bar_w, track_h, color=RGBColor(0xE2, 0xE8, 0xF0))
        # 前景胶囊（按平均分比例）
        if pct > 0.04:
            fill_w = bar_w * pct
            # 保留最小可视胶囊
            fill_w = max(fill_w, Inches(0.28))
            _pill(slide, bar_x, y + Inches(0.06), fill_w, track_h, color=brand)
        # 数值与等级
        lv_text = _level_text(int(round(avg)))
        _text(
            slide, Inches(9.15), y, Inches(3.0), Inches(row_h_in * 0.42),
            f"{avg:.1f} / 5  ·  {lv_text}", size=12.5, color=brand, bold=True,
        )
    return y0 + row_h * len(shown)


def _honor_roll(slide, names_notes, *, y0=Inches(2.0), brand=BRAND, soft=BRAND_SOFT, line=LINE_SOFT):
    """进步之星荣誉墙 — 编号渐变徽标 + 圆角白卡 + 左侧品牌描边（主题色可注入）。"""
    if not names_notes:
        _text(slide, Inches(0.9), y0, Inches(11.5), Inches(0.6),
              "（暂无提名，快去评估里记录学员的进步吧）", size=15, color=INK_SOFT)
        return
    chip_w = Inches(3.75)
    chip_h = Inches(1.55)
    cols = 3
    shown = names_notes[: cols * 2]
    note_w_in = 3.75 - 0.42
    for i, (name, note) in enumerate(shown):
        x = Inches(0.78) + (chip_w + Inches(0.32)) * (i % cols)
        y = y0 + (chip_h + Inches(0.28)) * (i // cols)
        card = _rounded_rect(slide, x, y, chip_w, chip_h, color=PAPER, line=True,
                             line_color=line)
        # 左侧品牌竖条（圆角卡内）
        _rect(slide, x, y + Inches(0.18), Inches(0.06), chip_h - Inches(0.36), color=brand)
        try:
            slide.shapes[-1].adjustments[0] = 0.5
        except Exception:
            pass
        # 编号徽标（右上角）
        badge = _pill(slide, x + chip_w - Inches(0.52), y + Inches(0.12),
                      Inches(0.40), Inches(0.40), color=soft)
        try:
            badge.adjustments[0] = 0.5
        except Exception:
            pass
        _text(slide, x + chip_w - Inches(0.52), y + Inches(0.12), Inches(0.40),
              Inches(0.40), str(i + 1), size=12, color=brand, bold=True,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        tf = card.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.TOP
        tf.margin_left = Inches(0.16)
        tf.margin_right = Inches(0.55)
        tf.margin_top = Inches(0.08)
        tf.margin_bottom = Inches(0.08)
        note = str(note or "").strip()
        note_h = chip_h / 914400 - 0.44
        note_size = _fit_size(
            note, box_w_in=note_w_in, box_h_in=note_h, max_pt=11, min_pt=9,
        )
        if note and _text_height_in(note, font_pt=note_size, box_w_in=note_w_in) > note_h:
            lines = _truncated_lines(
                [note], box_w_in=note_w_in, box_h_in=note_h, font_pt=note_size,
            )
            note = "".join(lines)
        p1 = tf.paragraphs[0]
        p1.alignment = PP_ALIGN.LEFT
        p1.text = f"★ {name}"
        for run in p1.runs:
            run.font.size = Pt(14)
            run.font.color.rgb = INK
            run.font.bold = True
            run.font.name = "微软雅黑"
        if note:
            p2 = tf.add_paragraph()
            p2.alignment = PP_ALIGN.LEFT
            p2.space_before = Pt(4)
            p2.text = note
            for run in p2.runs:
                run.font.size = Pt(note_size)
                run.font.color.rgb = INK_SOFT
                run.font.name = "微软雅黑"


def build_class_meeting_ppt(
    *,
    class_name: str,
    subject: str,
    period_label: str,
    teacher_name: str,
    created_at: datetime,
    class_stats: dict,
    averages: list[tuple[str, float]],
    honor_roll: list[tuple[str, str]],
    content: dict,
) -> str:
    """构建「班级家长会」PPT，返回相对路径（uploads/ppt/<uuid>.pptx）。

    版式（面向全班家长）：
      封面（班级/周期/教师）→ 班级学习数据 → 班级整体情况（class_summary）→
      能力培养（班级平均分条形图）→ 班级亮点 → 进步之星（荣誉墙独占页）→
      共性问题与改进 → 下阶段教学安排 → 给家长的建议 → 结尾。
    内容优先取 AI 提炼的班级文案（content），缺省时用数据兜底生成可读文本。
    所有正文文本框均走自动缩字/截断，杜绝文字互相重叠。
    """
    prs = Presentation()
    prs.slide_width = EMU_W
    prs.slide_height = EMU_H

    stats = class_stats or {}
    c = content or {}
    title = str(c.get("title") or f"{class_name} 家长会")

    # 1) 封面 — 浅卡化圆角白卡 + 深色顶条（与单学员封面体系一致）
    s = _blank_slide(prs)
    _rect(s, 0, 0, EMU_W, EMU_H, color=CARD_BG)
    _rounded_rect(s, Inches(0.7), Inches(0.95), Inches(11.9), Inches(4.15),
                  color=PAPER, line=True, line_color=LINE_SOFT)
    _rect(s, Inches(0.7), Inches(0.95), Inches(11.9), Inches(0.46), color=_DEEP)
    _pill(s, Inches(1.12), Inches(1.10), Inches(2.45), Inches(0.30), color=BRAND_SOFT)
    _text(s, Inches(1.12), Inches(1.12), Inches(2.45), Inches(0.26),
          "家长会 · 班级学习汇报", size=11, color=BRAND, bold=True,
          align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _text(s, Inches(1.12), Inches(1.72), Inches(11), Inches(0.9), title,
          size=30, color=INK, bold=True)
    _pill(s, Inches(1.12), Inches(2.68), Inches(1.4), Inches(0.05), color=CYAN)
    meta_parts = [
        p for p in [class_name, subject, period_label, teacher_name and f"主讲：{teacher_name}"]
        if p
    ]
    _text(s, Inches(1.12), Inches(2.95), Inches(11), Inches(0.6),
          "   ·   ".join(meta_parts) + f"   ·   {created_at.strftime('%Y-%m-%d')}",
          size=13, color=INK_SOFT)
    _text(s, Inches(1.12), Inches(3.55), Inches(11), Inches(0.4),
          "结合全班学员评估 · 面向全体家长", size=11, color=INK_LIGHT)

    # 2) 班级学习数据
    s = _blank_slide(prs)
    _header(s, "CLASS DATA", f"{class_name} 本阶段学习数据")
    _stat_cards(s, [
        ("在读学员", f"{stats.get('active_count', 0)}/{stats.get('student_count', 0)}", "人"),
        ("上课总量", stats.get("total_lessons", 0), "人次·节"),
        ("平均出勤率", f"{stats.get('avg_attendance_rate', 0) * 100:.0f}%", ""),
        ("课后反馈", stats.get("total_feedbacks", 0), "篇"),
        ("批改作业", stats.get("total_homework", 0), "份"),
        ("作业平均得分率", _score_rate_text(stats.get("avg_homework_score_rate")), ""),
    ])

    # 3) 班级整体情况（AI 提炼的 class_summary，缺省用数据兜底）— 散文卡
    fallback_summary = (
        f"本阶段 {class_name} 共 {stats.get('student_count', 0)} 名学员参与学习，"
        f"平均出勤率 {stats.get('avg_attendance_rate', 0) * 100:.0f}%。"
    )
    _section_slide(prs, "OVERVIEW", "班级整体情况",
                   c.get("class_summary") or fallback_summary, BRAND, style="prose")

    # 4) 能力培养（班级平均分 + 点评）— 能力点评散文化
    s = _blank_slide(prs)
    _header(s, "ABILITIES", "能力培养情况（班级平均）")
    bars_end = _ability_bars(s, averages)
    comment = str(c.get("ability_comment") or "")
    if comment:
        y = max(bars_end + Inches(0.14), Inches(5.3))
        h = Inches(6.94) - y
        _prose_card(s, comment, accent=BRAND, y0=y, h=h, compact=True)

    # 5) 班级亮点（编号要点卡）
    _section_slide(prs, "HIGHLIGHTS", "班级亮点",
                   _split_list_text(c.get("highlights") or "") or ["（暂无班级亮点总结）"], CYAN)

    # 6) 进步之星（荣誉墙独占整页）
    s = _blank_slide(prs)
    _header(s, "STAR STUDENTS", "进步之星")
    _honor_roll(s, honor_roll, y0=Inches(2.1))

    # 7) 共性问题与改进
    _section_slide(prs, "TO IMPROVE", "共性问题与改进措施",
                   _split_list_text(c.get("to_improve") or "（暂无共性问题记录）"), _AMBER)

    # 8) 下阶段教学安排
    _section_slide(prs, "NEXT PLAN", "下阶段教学安排",
                   _split_list_text(c.get("next_plan") or "（暂无下阶段安排）"), CYAN)

    # 9) 给家长的建议
    _section_slide(prs, "FOR PARENTS", "给家长的建议",
                   _split_list_text(c.get("home_suggestions") or "（暂无建议）"), _GREEN)

    # 10) 结尾
    s = _blank_slide(prs)
    _rect(s, 0, 0, EMU_W, EMU_H, color=RGBColor(0xEE, 0xF2, 0xFF))
    _text(s, Inches(1.2), Inches(2.7), Inches(11), Inches(0.9),
          "感谢各位家长的陪伴与支持", size=36, color=_DEEP, bold=True, align=PP_ALIGN.CENTER)
    _text(s, Inches(1.2), Inches(3.9), Inches(11), Inches(0.6),
          f"让我们一起见证 {class_name} 每一位孩子的成长", size=16, color=INK_SOFT,
          align=PP_ALIGN.CENTER)

    _add_footers(prs, f"{class_name} · 家长会")
    out_dir = Path(get_settings().UPLOAD_DIR) / "ppt"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.pptx"
    path = out_dir / fname
    prs.save(str(path))
    return f"ppt/{fname}"


STYLE_PALETTES: dict[str, dict[str, RGBColor]] = {
    # Agent 风格真换肤（agent-theme-chat）：四套可明显区分的主题，封面/页眉/
    # 数据卡/能力条/荣誉墙统一取自同一调色板，不再共用一套 indigo 模板
    "A": {
        "brand": RGBColor(0xEA, 0x58, 0x0C), "accent": RGBColor(0xF5, 0x9E, 0x0B),
        "deep": RGBColor(0x7C, 0x2D, 0x12), "bg": RGBColor(0xFF, 0xF7, 0xED),
        "soft": RGBColor(0xFF, 0xED, 0xD5), "line": RGBColor(0xFD, 0xD6, 0xA4),
    },
    "warm": {
        "brand": RGBColor(0xEA, 0x58, 0x0C), "accent": RGBColor(0xF5, 0x9E, 0x0B),
        "deep": RGBColor(0x7C, 0x2D, 0x12), "bg": RGBColor(0xFF, 0xF7, 0xED),
        "soft": RGBColor(0xFF, 0xED, 0xD5), "line": RGBColor(0xFD, 0xD6, 0xA4),
    },
    "B": {
        "brand": RGBColor(0x1E, 0x40, 0xAF), "accent": RGBColor(0x02, 0x84, 0xC7),
        "deep": RGBColor(0x1E, 0x3A, 0x8A), "bg": RGBColor(0xEF, 0xF6, 0xFF),
        "soft": RGBColor(0xDB, 0xE8, 0xFE), "line": RGBColor(0xBF, 0xDB, 0xFE),
    },
    "pro": {
        "brand": RGBColor(0x1E, 0x40, 0xAF), "accent": RGBColor(0x02, 0x84, 0xC7),
        "deep": RGBColor(0x1E, 0x3A, 0x8A), "bg": RGBColor(0xEF, 0xF6, 0xFF),
        "soft": RGBColor(0xDB, 0xE8, 0xFE), "line": RGBColor(0xBF, 0xDB, 0xFE),
    },
    "C": {
        "brand": RGBColor(0xA8, 0x55, 0xF7), "accent": RGBColor(0xEC, 0x48, 0x99),
        "deep": RGBColor(0x6B, 0x21, 0xA8), "bg": RGBColor(0xFA, 0xF5, 0xFF),
        "soft": RGBColor(0xF3, 0xE8, 0xFF), "line": RGBColor(0xE9, 0xD5, 0xFF),
    },
    "playful": {
        "brand": RGBColor(0xA8, 0x55, 0xF7), "accent": RGBColor(0xEC, 0x48, 0x99),
        "deep": RGBColor(0x6B, 0x21, 0xA8), "bg": RGBColor(0xFA, 0xF5, 0xFF),
        "soft": RGBColor(0xF3, 0xE8, 0xFF), "line": RGBColor(0xE9, 0xD5, 0xFF),
    },
    "D": {
        "brand": RGBColor(0x33, 0x41, 0x55), "accent": RGBColor(0x94, 0xA3, 0xB8),
        "deep": RGBColor(0x0F, 0x17, 0x2A), "bg": RGBColor(0xF8, 0xFA, 0xFC),
        "soft": RGBColor(0xF1, 0xF5, 0xF9), "line": RGBColor(0xE2, 0xE8, 0xF0),
    },
    "minimal": {
        "brand": RGBColor(0x33, 0x41, 0x55), "accent": RGBColor(0x94, 0xA3, 0xB8),
        "deep": RGBColor(0x0F, 0x17, 0x2A), "bg": RGBColor(0xF8, 0xFA, 0xFC),
        "soft": RGBColor(0xF1, 0xF5, 0xF9), "line": RGBColor(0xE2, 0xE8, 0xF0),
    },
    "custom": {
        "brand": BRAND, "accent": CYAN,
        "deep": RGBColor(0x0F, 0x17, 0x2A), "bg": RGBColor(0x0F, 0x17, 0x2A),
        "soft": RGBColor(0x1E, 0x29, 0x3B), "line": RGBColor(0x33, 0x41, 0x55),
        "dark": True, "ink": RGBColor(0xF1, 0xF5, 0xF9), "ink_soft": RGBColor(0x94, 0xA3, 0xB8),
    },
}


def _pal(style: str) -> dict[str, RGBColor]:
    """按风格 key 取调色板；custom:xxx 回退 custom，大小写不敏感，未知回退 A。"""
    key = (style or "A").split(":")[0].strip().lower()
    mapping = {
        "a": "A", "warm": "warm", "b": "B", "pro": "pro",
        "c": "C", "playful": "playful", "d": "D", "minimal": "minimal",
        "custom": "custom",
    }
    return STYLE_PALETTES.get(mapping.get(key, "A"), STYLE_PALETTES["A"])


def build_class_meeting_ppt_dynamic(
    *,
    class_name: str,
    subject: str,
    period_label: str,
    teacher_name: str,
    created_at: datetime,
    class_stats: dict,
    averages: list[tuple[str, float]],
    honor_roll: list[tuple[str, str]],
    content: dict,
    outline: list[dict] | None = None,
    style: str = "A",
) -> str:
    """按大纲动态生成班级家长会 PPT（Agent 定制）。

    - outline 为 None 时完全兼容原固定流（委托 build_class_meeting_ppt）
    - 否则按 outline 中 enabled/order/title/kicker 动态决定是否渲染对应章节
    - style 映射调色板（A/warm, B/pro, C/playful, D/minimal）
    """
    if not outline:
        return build_class_meeting_ppt(
            class_name=class_name,
            subject=subject,
            period_label=period_label,
            teacher_name=teacher_name,
            created_at=created_at,
            class_stats=class_stats,
            averages=averages,
            honor_roll=honor_roll,
            content=content,
        )
    stats = class_stats or {}
    c = content or {}
    # 大纲中用户可自定义标题/排序
    enabled = {o.get("key"): o for o in outline if o.get("enabled")}

    def _outline_title(key: str, fallback: str) -> str:
        item = enabled.get(key)
        if item and str(item.get("title") or "").strip():
            return str(item["title"]).strip()
        return fallback

    def _outline_kicker(key: str, fallback: str) -> str:
        item = enabled.get(key)
        if item and str(item.get("kicker") or "").strip():
            return str(item["kicker"]).strip()
        return fallback

    pal = _pal(style)
    brand = pal["brand"]
    accent_cyan = pal["accent"]
    deep = pal["deep"]
    bg = pal.get("bg", CARD_BG)
    soft = pal.get("soft", BRAND_SOFT)
    line = pal.get("line", LINE_SOFT)
    # 深色商务（custom:xxx，如“深色商务风”）：整套深色底+浅色字，由 _pal 统一解析
    dark_mode = bool(pal.get("dark"))
    title_ink = pal.get("ink", INK)
    body_soft = pal.get("ink_soft", INK_SOFT)

    prs = Presentation()
    prs.slide_width = EMU_W
    prs.slide_height = EMU_H
    title_text = str(c.get("title") or f"{class_name} 家长会")

    # 1) 封面（真换肤：整页底色/卡片描边/胶囊/顶条全部取主题色；深色模式用深底+浅字）
    if "cover" in enabled:
        s = _blank_slide(prs)
        _rect(s, 0, 0, EMU_W, EMU_H, color=bg)
        cover_card = bg if not dark_mode else RGBColor(0x1E, 0x29, 0x3B)
        _rounded_rect(s, Inches(0.7), Inches(0.95), Inches(11.9), Inches(4.15),
                      color=PAPER if not dark_mode else cover_card, line=True, line_color=line)
        _rect(s, Inches(0.7), Inches(0.95), Inches(11.9), Inches(0.46), color=deep)
        _pill(s, Inches(1.12), Inches(1.10), Inches(2.45), Inches(0.30), color=soft)
        _text(s, Inches(1.12), Inches(1.12), Inches(2.45), Inches(0.26),
              "家长会 · 班级学习汇报", size=11, color=brand, bold=True,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        _text(s, Inches(1.12), Inches(1.72), Inches(11), Inches(0.9), title_text,
              size=30, color=title_ink, bold=True)
        _pill(s, Inches(1.12), Inches(2.68), Inches(1.4), Inches(0.05), color=accent_cyan)
        meta_parts = [p for p in [class_name, subject, period_label, teacher_name and f"主讲：{teacher_name}"] if p]  # noqa: E501
        _text(s, Inches(1.12), Inches(2.95), Inches(11), Inches(0.6),
              "   ·   ".join(meta_parts) + f"   ·   {created_at.strftime('%Y-%m-%d')}",
              size=13, color=body_soft)
        _text(s, Inches(1.12), Inches(3.55), Inches(11), Inches(0.4),
              "结合全班学员评估 · 面向全体家长", size=11, color=body_soft)

    # 2) 数据（页眉/统计卡全部取主题色；深色模式页底同步加深）
    if "data" in enabled:
        s = _blank_slide(prs)
        if dark_mode:
            _rect(s, 0, 0, EMU_W, EMU_H, color=bg)
        _header(s, _outline_kicker("data", "CLASS DATA"), _outline_title("data", f"{class_name} 本阶段学习数据"), brand=brand, soft=soft, accent=accent_cyan)  # noqa: E501
        _stat_cards(s, [
            ("在读学员", f"{stats.get('active_count', 0)}/{stats.get('student_count', 0)}", "人"),
            ("上课总量", stats.get("total_lessons", 0), "人次·节"),
            ("平均出勤率", f"{stats.get('avg_attendance_rate', 0) * 100:.0f}%", ""),
            ("课后反馈", stats.get("total_feedbacks", 0), "篇"),
            ("批改作业", stats.get("total_homework", 0), "份"),
            ("作业平均得分率", _score_rate_text(stats.get("avg_homework_score_rate")), ""),
        ], brand=brand, accent=accent_cyan, line=line)

    # 3) 整体情况
    if "overview" in enabled:
        fallback_summary = f"本阶段 {class_name} 共 {stats.get('student_count', 0)} 名学员参与学习，平均出勤率 {stats.get('avg_attendance_rate', 0) * 100:.0f}%。"  # noqa: E501
        _section_slide(prs, _outline_kicker("overview", "OVERVIEW"), _outline_title("overview", "班级整体情况"),  # noqa: E501
                       c.get("class_summary") or fallback_summary, brand, style="prose",
                       brand=brand, soft=soft, line=line)

    # 4) 能力（页眉/能力条取主题色；深色模式页底同步加深）
    if "abilities" in enabled:
        s = _blank_slide(prs)
        if dark_mode:
            _rect(s, 0, 0, EMU_W, EMU_H, color=bg)
        _header(s, _outline_kicker("abilities", "ABILITIES"), _outline_title("abilities", "能力培养情况（班级平均）"), brand=brand, soft=soft, accent=accent_cyan)  # noqa: E501
        bars_end = _ability_bars(s, averages, brand=brand)
        comment = str(c.get("ability_comment") or "")
        if comment:
            y = max(bars_end + Inches(0.14), Inches(5.3))
            h = Inches(6.94) - y
            _prose_card(s, comment, accent=brand, y0=y, h=h, compact=True, line=line)

    # 5) 亮点
    if "highlights" in enabled:
        _section_slide(prs, _outline_kicker("highlights", "HIGHLIGHTS"), _outline_title("highlights", "班级亮点"),  # noqa: E501
                       _split_list_text(c.get("highlights") or "") or ["（暂无班级亮点总结）"], accent_cyan,
                       brand=brand, soft=soft, line=line)

    # 6) 进步之星（页眉/荣誉墙取主题色；深色模式页底同步加深）
    if "honor" in enabled:
        s = _blank_slide(prs)
        if dark_mode:
            _rect(s, 0, 0, EMU_W, EMU_H, color=bg)
        _header(s, _outline_kicker("honor", "STAR STUDENTS"), _outline_title("honor", "进步之星"),  # noqa: E501
                brand=brand, soft=soft, accent=accent_cyan)
        _honor_roll(s, honor_roll, y0=Inches(2.1), brand=brand, soft=soft, line=line)

    # 7) 作品展示（新增可选章节）
    if "works" in enabled:
        works_text = c.get("works") or c.get("highlights") or "（教师可在文案中补充本阶段学员代表作品与展示安排）"
        # works 按散文卡渲染，避免与亮点重复
        _section_slide(prs, _outline_kicker("works", "WORKS"), _outline_title("works", "作品展示"),
                       works_text if isinstance(works_text, str) else str(works_text), accent_cyan, style="prose",  # noqa: E501
                       brand=brand, soft=soft, line=line)

    # 8) 共性问题
    if "to_improve" in enabled:
        _section_slide(prs, _outline_kicker("to_improve", "TO IMPROVE"), _outline_title("to_improve", "共性问题与改进措施"),  # noqa: E501
                       _split_list_text(c.get("to_improve") or "（暂无共性问题记录）"), _AMBER,
                       brand=brand, soft=soft, line=line)

    # 9) 下阶段
    if "next_plan" in enabled:
        _section_slide(prs, _outline_kicker("next_plan", "NEXT PLAN"), _outline_title("next_plan", "下阶段教学安排"),  # noqa: E501
                       _split_list_text(c.get("next_plan") or "（暂无下阶段安排）"), accent_cyan,
                       brand=brand, soft=soft, line=line)

    # 10) 家长建议
    if "suggestions" in enabled:
        _section_slide(prs, _outline_kicker("suggestions", "FOR PARENTS"), _outline_title("suggestions", "给家长的建议"),  # noqa: E501
                       _split_list_text(c.get("home_suggestions") or "（暂无建议）"), _GREEN,
                       brand=brand, soft=soft, line=line)

    # 11) 结尾（底色取主题 soft；深色模式用深底+浅字）
    if "ending" in enabled:
        s = _blank_slide(prs)
        _rect(s, 0, 0, EMU_W, EMU_H, color=soft)
        ending_title = deep if not dark_mode else title_ink
        _text(s, Inches(1.2), Inches(2.7), Inches(11), Inches(0.9),
              "感谢各位家长的陪伴与支持", size=36, color=ending_title, bold=True, align=PP_ALIGN.CENTER)  # noqa: E501
        _text(s, Inches(1.2), Inches(3.9), Inches(11), Inches(0.6),
              f"让我们一起见证 {class_name} 每一位孩子的成长", size=16, color=body_soft, align=PP_ALIGN.CENTER)

    # 若大纲未包含封面/结尾，至少保留一页避免空文档
    if len(prs.slides) == 0:
        return build_class_meeting_ppt(
            class_name=class_name, subject=subject, period_label=period_label,
            teacher_name=teacher_name, created_at=created_at,
            class_stats=class_stats, averages=averages, honor_roll=honor_roll, content=content,
        )

    _add_footers(prs, f"{class_name} · 家长会")
    out_dir = Path(get_settings().UPLOAD_DIR) / "ppt"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.pptx"
    path = out_dir / fname
    prs.save(str(path))
    return f"ppt/{fname}"


def build_class_meeting_fallback(
    *,
    class_name: str,
    subject: str,
    class_stats: dict,
    averages: list[tuple[str, float]],
    honor_roll: list[tuple[str, str]],
) -> dict[str, str]:
    """未配置 LLM 时的模板兜底文案（基于班级聚合数据，可直接成稿）。"""
    stats = class_stats or {}
    rate = f"{stats.get('avg_attendance_rate', 0) * 100:.0f}%"
    hw = _score_rate_text(stats.get("avg_homework_score_rate"))
    avg_text = "、".join(f"{n}平均{v:.1f}分" for n, v in averages[:4]) or "能力数据待完善"
    top = "、".join(n for n, _ in honor_roll[:3]) or "（待教师评估后提名）"
    return {
        "title": f"{class_name} 阶段学习汇报家长会",
        "class_summary": (
            f"本阶段 {class_name}（{subject}）共 {stats.get('student_count', 0)} 名学员参与学习，"
            f"累计上课 {stats.get('total_lessons', 0)} 人次·节，平均出勤率 {rate}；"
            f"发布课后反馈 {stats.get('total_feedbacks', 0)} 篇、批改作业 "
            f"{stats.get('total_homework', 0)} 份（平均得分率 {hw}）。整体学习氛围良好，"
            f"{avg_text}。"
        ),
        "ability_comment": (
            f"从班级平均来看，{avg_text}。学员们在项目实践中逐步建立编程思维，"
            "课堂参与度与作品完成度稳步提升。"
        ),
        "highlights": (
            f"平均出勤率 {rate}，学习习惯保持良好；"
            f"{stats.get('total_feedbacks', 0)} 篇课堂反馈记录了孩子们的点滴进步；"
            f"{top} 等学员本阶段进步突出。"
        ),
        "to_improve": (
            "部分学员课后练习频次偏低，知识巩固不足；课堂表达与作品讲解能力可以进一步锻炼，"
            "后续将通过课堂展示环节加强。"
        ),
        "next_plan": (
            "延续现有课程进度，进入新知识模块学习；"
            "每两周安排一次综合项目实践，巩固所学；"
            "期末组织班级作品展示，让每位学员都有登台讲解的机会。"
        ),
        "home_suggestions": (
            "每周安排固定时间完成课后练习（建议 2 次，每次 30 分钟）；"
            "鼓励孩子把课堂作品讲给家长听，锻炼表达能力；"
            "课时不足 10 节时请及时与老师沟通续报，避免学习中断。"
        ),
    }
