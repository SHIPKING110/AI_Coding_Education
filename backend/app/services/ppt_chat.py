"""对话式 PPT 定制服务：把报告数据/总结转成可流式对话的素材与提示词。

设计：
- 后端只负责「给定报告上下文 + 当前大纲/文案 + 用户消息 -> 流式文本」；
  会话状态（大纲、文案、主题、进度）由前端持有并在每次请求回传，后端无状态。
- 约定：大纲/文案阶段，模型在自然语言说明之外，附带一个 ```json 代码块，
  前端解析该块即可把结构化结果应用到可编辑的大纲/文案上（可直接在界面上改）。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.crud import report as report_crud
from app.models.report import Report, ReportType

# 幻灯片可用的版式（与 pptx_builder.build_custom_ppt 的 slides[].kind 对齐）
SLIDE_KINDS = ("cover", "stats", "table", "bar", "bullets", "prose", "end")


def report_material(db: Session, rep: Report) -> dict[str, Any]:
    """汇总报告上下文：已保存统计 + 明细快照 + 月度/对比图表数据 + 正文文本。"""
    stats = rep.stats or {}
    content = rep.content or {}
    is_yearly = rep.type == ReportType.YEARLY.value

    if is_yearly:
        quarterly = report_crud.list_published_quarterlies(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        raw = report_crud.compute_period_stats(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        agg = report_crud.rollup_period_to_annual(
            quarterly, current_students=raw.get("current_students", 0)
        )
        merged = {**agg, **stats}
        merged["quarterly_count"] = len(quarterly)
    else:
        raw = report_crud.compute_period_stats(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        merged = {**raw, **stats}

    monthly = report_crud.compute_period_monthly(
        db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
    )
    comparison = report_crud.compute_period_comparison(
        db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
    )
    breakdown = content.get("ppt_breakdown")
    if not isinstance(breakdown, list):
        breakdown = []

    return {
        "type": rep.type,
        "title": rep.title or "",
        "period": f"{rep.period_start.strftime('%Y-%m-%d')} ~ {rep.period_end.strftime('%Y-%m-%d')}",
        "stats": merged,
        "content": {
            k: content.get(k)
            for k in ("summary", "highlights", "problems", "next_plan", "stats_notes")
        },
        "monthly": monthly,
        "comparison": comparison,
        "breakdown": breakdown,
    }


def combined_report_material(db: Session, reps: list[Report]) -> dict[str, Any]:
    """多份报告合并素材：统计相加、逐月/明细拼接、正文分段，用于"多选素材"生成 PPT。"""
    if not reps:
        return {}
    if len(reps) == 1:
        return report_material(db, reps[0])
    parts = [report_material(db, r) for r in reps]
    additive = (
        "schedules", "attended", "leave", "consumed_lessons",
        "expected_lessons", "new_students",
    )
    stats: dict[str, Any] = {}
    for key in additive:
        stats[key] = sum(int(p["stats"].get(key) or 0) for p in parts)
    stats["current_students"] = max(int(p["stats"].get("current_students") or 0) for p in parts)
    denom = stats["attended"] + stats["leave"]
    stats["attendance_rate"] = (stats["attended"] / denom) if denom else 0
    stats["achievement_rate"] = (
        stats["consumed_lessons"] / stats["expected_lessons"] if stats["expected_lessons"] else 0
    )
    monthly: list[dict] = []
    for p in parts:
        monthly.extend(p.get("monthly") or [])
    breakdown: list[dict] = []
    for p in parts:
        breakdown.extend(p.get("breakdown") or [])
    content: dict[str, Any] = {}
    for field in ("summary", "highlights", "problems", "next_plan", "stats_notes"):
        chunks = [str(p["content"].get(field) or "").strip() for p in parts if p["content"].get(field)]
        if chunks:
            content[field] = "\n".join(chunks)
    titles = "、".join(p["title"] for p in parts if p["title"])
    periods = " / ".join(p["period"] for p in parts if p["period"])
    return {
        "type": "merged",
        "title": titles,
        "period": periods,
        "stats": stats,
        "content": content,
        "monthly": monthly,
        "comparison": parts[0].get("comparison") or {},
        "breakdown": breakdown,
    }


def _fmt_stats(stats: dict[str, Any]) -> str:
    def pct(v: Any) -> str:
        try:
            return f"{float(v or 0) * 100:.1f}%"
        except (TypeError, ValueError):
            return "0.0%"

    return (
        f"- 当前学员：{stats.get('current_students', 0)} 人\n"
        f"- 已完成排课：{stats.get('schedules', 0)} 节\n"
        f"- 上课人次：{stats.get('attended', 0)}，缺课人次：{stats.get('leave', 0)}\n"
        f"- 出勤率：{pct(stats.get('attendance_rate'))}\n"
        f"- 应耗课时：{stats.get('expected_lessons', 0)} 节，消耗课时：{stats.get('consumed_lessons', 0)} 节\n"
        f"- 达标率：{pct(stats.get('achievement_rate'))}\n"
        f"- 新增学员：{stats.get('new_students', 0)} 人"
    )


def _fmt_monthly(monthly: list[dict]) -> str:
    if not monthly:
        return "（无逐月数据）"
    return "\n".join(
        f"- {m.get('month')}：消耗 {m.get('consumed_lessons', 0)} 节 / 应耗 "
        f"{m.get('expected_lessons', 0)} 节，上课 {m.get('attendance', 0)} 人次，"
        f"新增 {m.get('new_students', 0)} 人"
        for m in monthly
    )


def _fmt_breakdown(breakdown: list[dict]) -> str:
    if not breakdown:
        return "（无明细快照）"
    lines = []
    for r in breakdown:
        if "month" in r:
            lines.append(
                f"- {r.get('month')}：消耗 {r.get('consumed_lessons', 0)} / 应耗 "
                f"{r.get('expected_lessons', 0)} 节"
            )
        else:
            lines.append(
                f"- {r.get('label', '')}：消耗 {r.get('consumed_lessons', 0)} / 应耗 "
                f"{r.get('expected_lessons', 0)} 节，出勤率 "
                f"{float(r.get('attendance_rate') or 0) * 100:.1f}%"
            )
    return "\n".join(lines)


def _fmt_content(content: dict) -> str:
    labels = {
        "summary": "总体情况",
        "highlights": "主要亮点",
        "problems": "问题与改进",
        "next_plan": "下阶段计划",
        "stats_notes": "数据说明",
    }
    parts = []
    for k, label in labels.items():
        v = (content.get(k) or "").strip() if isinstance(content.get(k), str) else ""
        if v:
            parts.append(f"【{label}】{v}")
    return "\n".join(parts) or "（报告正文暂为空，可主要依据统计数据构建）"


def context_text(material: dict[str, Any]) -> str:
    """把报告上下文整理成给模型的纯文本素材。"""
    label = "季度" if material["type"] == ReportType.QUARTERLY.value else "年度"
    return (
        f"报告类型：{label}总结\n"
        f"标题：{material['title']}\n"
        f"周期：{material['period']}\n\n"
        f"【核心统计数据（必须用图表/表格体现，不要只堆文字）】\n"
        f"{_fmt_stats(material['stats'])}\n\n"
        f"【逐月数据】\n{_fmt_monthly(material['monthly'])}\n\n"
        f"【明细/季度对照】\n{_fmt_breakdown(material['breakdown'])}\n\n"
        f"【报告正文要点】\n{_fmt_content(material['content'])}"
    )


SYSTEM_PROMPT = (
    "你是资深演示文稿设计师，帮助教师把季度/年度教学总结做成简洁、数据驱动、"
    "可读性强的 PPT。原则：\n"
    "1) 统计数据必须用图表或表格呈现，不堆砌数字文字；\n"
    "2) 文案精炼，一句话讲清一件事，避免空话套话；\n"
    "3) 页面有分工：数据进图表页，结论进要点页，叙述进散文页。\n"
    "你会在自然语言说明之外，按需附带一个 ```json 代码块供系统解析（见各阶段要求）。"
    "只依据给定数据，不编造事实。回答用 Markdown 组织（可用小标题、列表、加粗）。"
)

_KIND_HINT = (
    "slides[].kind 取值：cover(封面) / stats(数据卡) / table(数据表) / "
    "bar(柱状图) / bullets(要点卡) / prose(散文) / end(结尾)。"
)

# 系统真正能执行的动作目录：模型只能从这里挑选，避免给“做不到”的空选项
_ACTION_CATALOG = (
    "可选动作（options[].action.type 只能取以下之一，参数必须合法，系统会真的执行）：\n"
    '- apply_theme：{"type":"apply_theme","theme":"brand|cyan|deep"} 切换整体配色\n'
    '- apply_outline：{"type":"apply_outline","outline":[{"id","title","kind","note"}]} 用新大纲整体替换\n'
    '- apply_sections：{"type":"apply_sections","sections":[{"id","title","body"}]} 用新文案整体替换\n'
    '- add_page：{"type":"add_page","title":"...","kind":"bullets|prose|table|bar|stats","note":"..."} 新增一页\n'
    '- remove_page：{"type":"remove_page","title":"要删除的页标题"} 删除某页\n'
    '- go_stage：{"type":"go_stage","stage":"outline|copy|layout|export"} 跳到某一步\n'
    '- build_ppt：{"type":"build_ppt","theme":"brand|cyan|deep"} 立即生成并导出 PPT\n'
    '- regen：{"type":"regen","stage":"outline|copy|layout"} 重新生成该阶段内容\n'
    '- send：{"type":"send","prompt":"..."} 用该文案作为用户消息继续对话\n'
)

_OPTIONS_HINT = (
    "另外，请在同一个 JSON 代码块里给出 options（2-4 个可点击选项，帮用户做选择）：\n"
    'options 结构：[{"id":"o1","label":"按钮文案","recommended":true,"action":{...}}]。\n'
    "要求：\n"
    "- 恰好 1 个选项 recommended=true（你最推荐、最省事的下一步）；\n"
    "- label 是用户视角的动作用语（如“按推荐主题直接生成 PPT”“再加一页亮点”“换成深蓝主题”），"
    "不要写“建议/推荐某某”这种空话；\n"
    "- 每个选项的 action 必须是上面可选动作之一，且参数合法、系统能真正执行；\n"
    "- 选项要覆盖“继续推进”和“微调”两类，引导用户一步步走到导出。\n"
    + _ACTION_CATALOG
)


def outline_prompt(material: dict, user_message: str, current_outline: list[dict]) -> str:
    cur = json.dumps(current_outline, ensure_ascii=False) if current_outline else "（暂无）"
    return (
        f"报告素材：\n{context_text(material)}\n\n"
        f"当前大纲（用户可能已改过）：{cur}\n"
        f"用户诉求：{user_message or '请给出建议的 PPT 大纲'}\n\n"
        f"请先用 2-4 句话说明你的构思，然后输出一个 ```json 代码块，结构："
        '{"message":"给用户的一句话确认","outline":[{"id":"s1","title":"页标题",'
        '"kind":"bullets","note":"这页讲什么/用什么图"}],"options":[...]}。\n'
        f"{_KIND_HINT}\n"
        "要求：页数 6-10 页；第一页通常是数据总览/核心结论，务必包含至少一页数据图表；"
        "页标题短而具体。id 用 s1,s2,... 稳定不变。\n"
        f"{_OPTIONS_HINT}\n"
        "本阶段 options 建议包含：确认大纲并生成文案（recommended）、重新生成大纲、直接生成 PPT 等。"
    )


def copy_prompt(material: dict, outline: list[dict], user_message: str) -> str:
    outline_txt = json.dumps(outline, ensure_ascii=False)
    return (
        f"报告素材：\n{context_text(material)}\n\n"
        f"已确认的大纲：{outline_txt}\n"
        f"用户诉求：{user_message or '请为每一页撰写文案'}\n\n"
        "请为每一页撰写精炼文案（每页 1-3 句或 2-4 条要点），数据页只写解读不重复罗列数字。"
        "先用 1-2 句话说明，然后输出一个 ```json 代码块，结构："
        '{"message":"一句话确认","sections":[{"id":"s1","title":"页标题","body":"该页文案"}],"options":[...]}。\n'
        "id 必须与大纲一致。\n"
        f"{_OPTIONS_HINT}\n"
        "本阶段 options 建议包含：进入排版并让 AI 选配色（recommended）、重新生成文案、直接生成 PPT 等。"
    )


def layout_prompt(material: dict, outline: list[dict], sections: list[dict], user_message: str) -> str:
    return (
        f"报告素材：\n{context_text(material)}\n\n"
        f"大纲：{json.dumps(outline, ensure_ascii=False)}\n"
        f"文案：{json.dumps(sections, ensure_ascii=False)}\n"
        f"用户诉求：{user_message or '请给出排版与视觉建议'}\n\n"
        "我们的 PPT 只能套用系统内置主题与版式（三种配色 brand/cyan/deep，数据自动走表格与柱状图）。"
        "请先用 2-3 句话给出排版建议，并**明确推荐一种主题配色**，然后输出一个 ```json 代码块，结构："
        '{"message":"一句话确认","theme":"brand|cyan|deep","options":[...]}。\n'
        "theme 为你推荐的主题。\n"
        f"{_OPTIONS_HINT}\n"
        "本阶段 options 必须包含：用推荐主题生成 PPT（recommended，action=build_ppt）；"
        "并给出另外 1-2 种主题切换（apply_theme）或微调页面的选项。"
    )


def chat_prompt(material: dict, user_message: str, outline: list[dict], sections: list[dict]) -> str:
    return (
        f"报告素材：\n{context_text(material)}\n\n"
        f"当前大纲：{json.dumps(outline, ensure_ascii=False)}\n"
        f"当前文案：{json.dumps(sections, ensure_ascii=False)}\n"
        f"用户消息：{user_message}\n\n"
        "请针对用户消息给出简洁、可执行的回答（Markdown）。若涉及大纲/文案/主题/新增页面的调整，"
        "请把结果放进 ```json 代码块（可含 outline / sections / theme / options）。\n"
        f"{_OPTIONS_HINT}"
    )


def build_prompt(
    *, stage: str, material: dict, user_message: str,
    outline: list[dict], sections: list[dict],
) -> str:
    if stage == "outline":
        return outline_prompt(material, user_message, outline)
    if stage == "copy":
        return copy_prompt(material, outline, user_message)
    if stage == "layout":
        return layout_prompt(material, outline, sections, user_message)
    return chat_prompt(material, user_message, outline, sections)
