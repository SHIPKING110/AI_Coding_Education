"""学员评估报告 PDF 构建服务（M6 后端化导出）。

- 使用 reportlab 从评估 content(stats) 渲染标准 A4 报告单 PDF：
  封面（品牌封面头 + 学员/周期/教师 + 已发布印章）→ 周期统计卡 →
  综合表现 → 学科能力（雷达图 + 星级条目）→ 进步亮点 → 待提升项 →
  给家长的建议 → 落款（教师/发布时间）
- 中文字体：优先嵌入本机 TTF（微软雅黑/黑体/思源黑体/苹方等，跨 Windows/macOS/Linux），
  找不到时回退 PDF 内置 CID 字体（STSong-Light，字体由阅读器提供）
- 产物直接返回字节流（BytesIO），由路由层流式下发 —— 无浏览器打印的页眉/页脚/网址痕迹

设计令牌与前端一致：品牌 indigo→cyan、卡片化统计、能力星级（1-5）、彩色能力等级。
"""

import io
import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.services.llm import clean_listish_text

# 品牌色板 — 2026 精炼版（与前端 App.vue 对齐）
BRAND = colors.HexColor("#615FFF")
BRAND_SOFT = colors.HexColor("#EEF2FF")
CYAN = colors.HexColor("#00B8DB")
CYAN_SOFT = colors.HexColor("#ECFEFF")
INK = colors.HexColor("#0F172A")
INK_SOFT = colors.HexColor("#62748E")
INK_LIGHT = colors.HexColor("#90A1B9")
PAPER = colors.white
LINE = colors.HexColor("#E2E8F0")
BG_SOFT = colors.HexColor("#F8FAFC")
CARD_BG = colors.HexColor("#F8FAFF")
COVER_DARK = colors.HexColor("#1E1B4B")
GREEN = colors.HexColor("#0E9F6E")
AMBER = colors.HexColor("#F59E0B")
PURPLE = colors.HexColor("#A855F7")
GOLD = colors.HexColor("#FBBF24")
BRAND_DEEP = colors.HexColor("#312E81")

# ---------------------------------------------------------------- 中文字体
FONT_MAIN = "report-cjk"
FONT_BOLD = "report-cjk-bold"
_font_ready = False

# 常见系统中文字体候选（按平台优先级），值为 (主字体, 粗体可选路径)
_FONT_CANDIDATES: list[tuple[Path, Path | None]] = [
    (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/msyhbd.ttc")),  # 微软雅黑
    (Path("C:/Windows/Fonts/simhei.ttf"), None),  # 黑体
    (Path("C:/Windows/Fonts/simsun.ttc"), None),  # 宋体
    (Path("/System/Library/Fonts/PingFang.ttc"), None),  # macOS 苹方
    (Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"), None),  # Linux Noto
    (Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"), None),  # Linux 文泉驿
]

_FALLBACK_FONT = "STSong-Light"


def _load_cjk_fonts() -> None:
    """注册中文字体；全部失败时回退内置 CID 字体（保证导出始终可用）。"""
    global _font_ready, FONT_MAIN, FONT_BOLD
    if _font_ready:
        return
    for reg, bold in _FONT_CANDIDATES:
        if not reg.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(FONT_MAIN, str(reg)))
            bold_src = bold if bold and bold.exists() else reg
            pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold_src)))
            _font_ready = True
            return
        except Exception:  # noqa: BLE001 - 单个字体注册失败则尝试下一个候选
            continue
    pdfmetrics.registerFont(UnicodeCIDFont(_FALLBACK_FONT))
    FONT_MAIN = FONT_BOLD = _FALLBACK_FONT
    _font_ready = True


# ---------------------------------------------------------------- 页面尺寸
PAGE_W, PAGE_H = A4  # 595 x 842 pt
MARGIN = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

ABILITY_LEVELS = ("待观察", "需加强", "良好", "优秀", "非常优秀")
LEVEL_COLORS = {
    5: colors.HexColor("#047857"),
    4: colors.HexColor("#059669"),
    3: colors.HexColor("#0E7490"),
    2: colors.HexColor("#B45309"),
    1: colors.HexColor("#B91C1C"),
}

# 星级常量
STAR_ON = "#F59E0B"  # 填充星（amber）
STAR_OFF = "#CBD5E1"  # 空星


def _rgb(color: colors.Color) -> str:
    """Color -> '#RRGGBB'（用于 Paragraph 内联颜色标记）。"""
    r, g, b = (int(color.red * 255), int(color.green * 255), int(color.blue * 255))
    return f"#{r:02X}{g:02X}{b:02X}"


def _esc(text: object) -> str:
    """转义用户内容中的 XML 特殊字符，避免破坏 Paragraph 标记。"""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _clamp_level(level: object) -> int:
    try:
        lv = int(level)
    except (TypeError, ValueError):
        lv = 3
    return max(1, min(5, lv))


def _level_text(level: int) -> str:
    return ABILITY_LEVELS[level - 1]


def _split_items(raw: object) -> list[str]:
    """progress/to_improve/suggestions 规整为条目列表。"""
    text = clean_listish_text(raw)
    if not text:
        return []
    return [s.strip() for s in str(text).split("；") if s.strip()]


def _score_rate_text(rate: object) -> str:
    if rate is None:
        return "暂无"
    try:
        return f"{float(rate) * 100:.0f}%"
    except (TypeError, ValueError):
        return "暂无"


def _style(*, size=10.5, leading=None, color=INK, bold=False, align=0,
           space_before=0, space_after=0, left_indent=0) -> ParagraphStyle:
    return ParagraphStyle(
        name="cjk",
        fontName=FONT_BOLD if bold else FONT_MAIN,
        fontSize=size,
        leading=leading or (size * 1.55),
        textColor=color,
        alignment=align,
        wordWrap="CJK",
        splitLongWords=True,
        spaceBefore=space_before,
        spaceAfter=space_after,
        leftIndent=left_indent,
    )


def _p(text: str, **kw) -> Paragraph:
    return Paragraph(text, _style(**kw))


# ---------------------------------------------------------------- 雷达图
class RadarChart(Flowable):
    """SVG 能力雷达图的服务端等价实现（reportlab canvas 绘制，同前端几何）。"""

    def __init__(self, subjects: list[dict], width: float, height: float):
        super().__init__()
        self.subjects = subjects
        self.width = width
        self.height = height

    def wrap(self, avail_width, avail_height):
        return min(self.width, avail_width), min(self.height, avail_height)

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        subs = self.subjects
        n = len(subs)
        cx = self.width / 2
        cy = self.height / 2 + 2
        R = min(self.width, self.height) / 2 - 24
        ang = lambda i: (math.pi * 2 * i) / n - math.pi / 2  # noqa: E731

        def pt(i: int, r: float) -> tuple[float, float]:
            return (cx + math.cos(ang(i)) * r, cy + math.sin(ang(i)) * r)

        # 五层同心环
        canvas.setLineWidth(0.7)
        for level in range(1, 6):
            canvas.setStrokeColor(LINE if level < 5 else colors.HexColor("#CBD5E1"))
            pts = [pt(i, (R * level) / 5) for i in range(n)]
            p = canvas.beginPath()
            p.moveTo(*pts[0])
            for x, y in pts[1:]:
                p.lineTo(x, y)
            p.close()
            canvas.drawPath(p, stroke=1, fill=0)
        # 轴线
        canvas.setStrokeColor(colors.HexColor("#EEF2F7"))
        canvas.setLineWidth(0.7)
        for i in range(n):
            x, y = pt(i, R)
            canvas.line(cx, cy, x, y)
        # 数据多边形
        data_pts = [pt(i, R * _clamp_level(s.get("level", 3)) / 5) for i, s in enumerate(subs)]
        p = canvas.beginPath()
        p.moveTo(*data_pts[0])
        for x, y in data_pts[1:]:
            p.lineTo(x, y)
        p.close()
        canvas.setFillColor(BRAND, alpha=0.16)
        canvas.setStrokeColor(CYAN)
        canvas.setLineWidth(1.5)
        canvas.drawPath(p, stroke=1, fill=1)
        # 顶点圆点
        canvas.setFillColor(PAPER)
        for x, y in data_pts:
            canvas.setStrokeColor(BRAND)
            canvas.setLineWidth(1.3)
            canvas.circle(x, y, 3, stroke=1, fill=1)
        # 能力名标签
        canvas.setFont(FONT_MAIN, 8)
        canvas.setFillColor(INK_SOFT)
        for i, sub in enumerate(subs):
            name = str(sub.get("name") or f"能力项 {i + 1}")
            x, y = pt(i, R + 16)
            anchor = "end" if x < cx - 8 else "start" if x > cx + 8 else "center"
            y = y + 2.5 if y < cy - 4 else y - 2.5 if y > cy + 4 else y + 3
            draw = {
                "end": canvas.drawRightString,
                "start": canvas.drawString,
                "center": canvas.drawCentredString,
            }[anchor]
            draw(x, y, name)
        canvas.restoreState()


# ---------------------------------------------------------------- 构建助手
def _cover_block(title_text: str, meta_parts: list[str], *, published: bool) -> list:
    """封面头：品牌深色底 + 标题 + 学员/周期/教师 meta + 已发布印章。"""
    rows = []
    if published:
        rows.append([_p("已发布", size=10, bold=True, color=GOLD, align=TA_RIGHT)])
    rows.append([_p("学 员 学 习 评 估 报 告", size=10.5,
                    color=colors.HexColor("#A5B4FC"), bold=True)])
    rows.append([_p(_esc(title_text), size=18, leading=25, color=PAPER, bold=True)])
    meta = "　·　".join(_esc(p) for p in meta_parts)
    rows.append([_p(meta, size=9.5, leading=14, color=colors.HexColor("#E2E8F0"))])
    cover = Table(rows, colWidths=[CONTENT_W])
    cover.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COVER_DARK),
                ("LEFTPADDING", (0, 0), (-1, -1), 20),
                ("RIGHTPADDING", (0, 0), (-1, -1), 20),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    bar = Table([[""]], colWidths=[CONTENT_W], rowHeights=[2.6])
    bar.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CYAN),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [cover, bar]


def _section_head(title: str, accent: colors.Color) -> list:
    """小节标题：左侧色条 + 标题文字。"""
    head = Table(
        [[_p(_esc(title), size=12.5, leading=16, color=INK, bold=True)]],
        colWidths=[CONTENT_W],
    )
    head.setStyle(
        TableStyle(
            [
                ("LINEBEFORE", (0, 0), (0, 0), 3.2, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return [head, Spacer(1, 4)]


def _stat_grid(stats: dict) -> Table:
    """周期统计卡：4 列卡片（值 + 标签），不足补空保持整齐。"""
    rate = stats.get("attendance_rate")
    cards: list[tuple[str, str]] = [
        (f"{float(rate) * 100:.0f}%" if rate is not None else "—", "出勤率"),
        (f"{stats.get('attended', 0)} 次", "到课"),
        (f"{stats.get('leave', 0)} 次", "请假"),
        (f"{stats.get('consumed_lessons', 0)} 节", "课时消耗"),
        (f"{stats.get('feedback_count', 0)} 篇", "课后反馈"),
        (f"{stats.get('homework_count', 0)} 份", "已批改作业"),
        (_score_rate_text(stats.get("homework_score_rate")), "作业得分率"),
    ]
    while len(cards) % 4:
        cards.append(("", ""))

    rows = []
    for i in range(0, len(cards), 4):
        cells = []
        for value, label in cards[i : i + 4]:
            cells.append(
                [
                    _p(_esc(value) if value else "", size=13, leading=15, color=BRAND, bold=True,
                       align=TA_CENTER),
                    _p(label, size=8.5, leading=10, color=INK_SOFT, align=TA_CENTER,
                       space_before=2),
                ]
            )
        rows.append(cells)

    tbl = Table(rows, colWidths=[CONTENT_W / 4] * 4, hAlign="LEFT")
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("BOX", (0, 0), (-1, -1), 0.9, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.9, LINE),
                ("BACKGROUND", (0, 0), (-1, -1), BG_SOFT),
            ]
        )
    )
    return tbl


def _subject_rows(subjects: list[dict]) -> Table:
    """学科能力条目：名称 + 星级 + 等级徽标 + 点评。"""
    rows = []
    for i, sub in enumerate(subjects):
        name = str(sub.get("name") or f"能力项 {i + 1}")
        level = _clamp_level(sub.get("level", 3))
        comment = str(sub.get("comment") or "").strip()
        color = LEVEL_COLORS[level]

        stars = f'<font color="{STAR_ON}">{"★" * level}</font>' \
                f'<font color="{STAR_OFF}">{"☆" * (5 - level)}</font>'
        left_cell = [
            _p(_esc(name), size=11, leading=14, color=INK, bold=True),
            Paragraph(stars, ParagraphStyle("stars", fontName=FONT_MAIN, fontSize=12.5,
                                            leading=15, spaceBefore=2)),
        ]
        if comment:
            left_cell.append(_p(_esc(comment), size=9.5, leading=14, color=INK_SOFT,
                                space_before=2))
        right_cell = _p(f"{_level_text(level)} · {level}/5", size=9.5, leading=13, color=color,
                        bold=True, align=TA_RIGHT)
        rows.append([left_cell, right_cell])

    tbl = Table(rows, colWidths=[CONTENT_W * 0.76, CONTENT_W * 0.24], hAlign="LEFT")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(len(rows)):
        if i % 2 == 1:
            style.append(("BACKGROUND", (0, i), (-1, i), BG_SOFT))
    tbl.setStyle(TableStyle(style))
    return tbl


def _bullet_items(items: list[str], accent: colors.Color) -> list:
    """条目列表（彩色圆点前缀）。"""
    return [
        Paragraph(
            f'<font color="{_rgb(accent)}">●</font>　{_esc(it)}',
            ParagraphStyle(
                "bullet",
                fontName=FONT_MAIN,
                fontSize=10.5,
                leading=16.5,
                textColor=colors.HexColor("#334155"),
                wordWrap="CJK",
                splitLongWords=True,
                leftIndent=13,
                spaceAfter=4,
            ),
        )
        for it in items
    ]


def _on_page(footer_text: str):
    """生成页脚回调（页面底部说明 + 页码）。"""

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)
        canvas.setFont(FONT_MAIN, 7.5)
        canvas.setFillColor(INK_LIGHT)
        canvas.drawString(MARGIN, 10 * mm, footer_text)
        canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, f"第 {canvas.getPageNumber()} 页")
        canvas.restoreState()

    return on_page


def build_evaluation_pdf(
    *,
    title: str | None,
    student_name: str,
    period_label: str,
    class_label: str,
    teacher_name: str,
    published_at: str | None,
    content: dict | None,
    stats: dict | None,
) -> bytes:
    """构建学员评估报告 PDF，返回字节流（由路由流式下发，不落盘）。

    版式：封面（品牌头 + 已发布印章）→ 周期统计卡 → 综合表现 →
    学科能力（雷达图 + 星级条目）→ 进步亮点 → 待提升项 → 建议 → 落款。
    """
    _load_cjk_fonts()
    content = content or {}
    stats = stats or {}

    student_name = student_name or "学员"
    title_text = (title or "").strip() or f"{student_name} 学习评估"
    published = bool(published_at)

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=17 * mm,
        title=f"学习评估报告 · {title_text}",
        author=teacher_name or "智能少儿编程教育管理系统",
        subject="学员学习评估报告",
    )

    story: list = []
    # ---------- 封面 ----------
    meta_parts = [student_name]
    if period_label:
        meta_parts.append(period_label)
    if class_label:
        meta_parts.append(class_label)
    if teacher_name:
        meta_parts.append(f"评估教师：{teacher_name}")
    story += _cover_block(title_text, meta_parts, published=published)
    story.append(Spacer(1, 12))

    # ---------- 周期统计卡 ----------
    story.append(_stat_grid(stats))
    story.append(Spacer(1, 14))

    # ---------- 正文小节 ----------
    def add_section(title: str, accent: colors.Color, flows: list) -> None:
        if flows:
            story.extend(_section_head(title, accent))
            story.extend(flows)
            story.append(Spacer(1, 10))

    summary = clean_listish_text(content.get("summary"))
    if summary:
        box = Table(
            [[_p(_esc(summary), size=10.5, leading=17.5, color=colors.HexColor("#334155"))]],
            colWidths=[CONTENT_W],
            hAlign="LEFT",
        )
        box.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BG_SOFT),
                    ("BOX", (0, 0), (-1, -1), 0.9, LINE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ]
            )
        )
        add_section("综合表现", BRAND, [box])

    subjects = [s for s in (content.get("subjects") or []) if isinstance(s, dict) and s.get("name")]
    if subjects:
        flows: list = []
        if 3 <= len(subjects) <= 8:
            radar = RadarChart(subjects, width=220, height=205)
            wrap = Table([[radar]], colWidths=[CONTENT_W], hAlign="LEFT")
            wrap.setStyle(
                TableStyle(
                    [
                        ("ALIGN", (0, 0), (0, 0), "CENTER"),
                        ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            flows.append(wrap)
        flows.append(_subject_rows(subjects))
        add_section("学科能力", CYAN, flows)

    add_section("进步亮点", GREEN, _bullet_items(_split_items(content.get("progress")), GREEN))
    add_section("待提升项", AMBER, _bullet_items(_split_items(content.get("to_improve")), AMBER))
    add_section("给家长的建议", PURPLE,
                _bullet_items(_split_items(content.get("suggestions")), PURPLE))

    # ---------- 落款 ----------
    if published_at:
        sign = f"评估教师：{teacher_name or '—'}　|　发布于 {published_at}"
    else:
        sign = "草稿预览 · 内容以最终发布为准"
    story.append(Spacer(1, 2))
    story.append(_p(sign, size=9.5, leading=13, color=INK_SOFT, align=TA_RIGHT))

    footer = f"智能少儿编程教育管理系统 · 学习评估报告 · {student_name}"
    frame = Frame(MARGIN, 17 * mm, CONTENT_W, PAGE_H - MARGIN - 17 * mm, id="main")
    doc.addPageTemplates(
        [PageTemplate(id="report", frames=[frame], onPage=_on_page(footer))]
    )
    doc.build(story)
    return buf.getvalue()


def render_evaluation_pdf(db, evaluation) -> bytes:
    """评估记录 -> PDF 字节流（路由层共用入口）。

    从评估记录解析学员/教师/班级/周期元信息后调用 build_evaluation_pdf。
    published_at 缺省时按草稿渲染（封面不带印章、落款显示草稿提示）。
    """
    from app.models.enrollment import Student

    student = db.get(Student, evaluation.student_id)
    student_name = student.name if student else "学员"
    class_label = "、".join(c.name for c in student.classes) if student else ""
    teacher_name = evaluation.teacher.name if evaluation.teacher else ""
    published_at = (
        evaluation.published_at.strftime("%Y-%m-%d") if evaluation.published_at else None
    )
    period_label = (
        f"{evaluation.period_start:%Y-%m-%d} ~ {evaluation.period_end:%Y-%m-%d}"
    )
    return build_evaluation_pdf(
        title=evaluation.title,
        student_name=student_name,
        period_label=period_label,
        class_label=class_label,
        teacher_name=teacher_name,
        published_at=published_at,
        content=evaluation.content or {},
        stats=evaluation.stats or {},
    )
