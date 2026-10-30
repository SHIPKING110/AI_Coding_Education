# -*- coding: utf-8 -*-
"""PPT 三处对齐（正文页清单 / 工作区大纲 / 实际 SVG）+ 多轮续作 回归测试：

1) 标题提炼不再把大号装饰数字（01/2000+）当页标题，多行标题能拼回完整一句；
2) 交付摘要以 build 回执的整份页清单为准（页数不再因标题去重而变少，标题来自磁盘真实页）；
3) 伪工具调用代码块（list_skill_files(...)）从正文/历史中剔除；
4) 会话已有 PPT 项目时，多轮修改保持 Skill 链路（基线注入、不被当普通聊天）。
"""

from pathlib import Path

from app.services import agent_tools, llm
from app.services.agent_planner import PlanOutcome, Step


def test_svg_page_title_ignores_big_section_numbers():
    svg = (
        '<svg viewBox="0 0 1280 720">'
        '<text x="96" y="188" font-size="46" font-weight="bold" id="h1">今天讲什么</text>'
        '<text x="128" y="378" font-size="58" font-weight="bold">01</text>'
        '<text x="504" y="378" font-size="58" font-weight="bold">02</text>'
        '<text x="128" y="442" font-size="30" id="t1">在学什么</text>'
        '</svg>'
    )
    assert agent_tools.svg_page_title(svg) == "今天讲什么"


def test_svg_page_title_ignores_stat_numbers():
    svg = (
        '<svg viewBox="0 0 1280 720">'
        '<text x="0" y="330" font-size="52" font-weight="bold">2000+</text>'
        '<text x="0" y="330" font-size="52" font-weight="bold">4 小时+</text>'
        '<text x="0" y="330" font-size="52" font-weight="bold">320</text>'
        '<text x="0" y="134" font-size="44" font-weight="bold">这条路，已经有孩子走完了</text>'
        '</svg>'
    )
    assert agent_tools.svg_page_title(svg) == "这条路，已经有孩子走完了"


def test_svg_page_title_merges_wrapped_title_lines():
    svg = (
        '<svg viewBox="0 0 1280 720">'
        '<text y="230" font-size="46">孩子带回家的，</text>'
        '<text y="290" font-size="46">不是一个分数，</text>'
        '<text y="350" font-size="46">是一个能跑起来的作品。</text>'
        '<text y="120" font-size="20">01 / 在学什么</text>'
        '</svg>'
    )
    assert agent_tools.svg_page_title(svg) == "孩子带回家的，不是一个分数，是一个能跑起来的作品"


def test_svg_page_title_prefers_semantic_id():
    svg = (
        '<svg viewBox="0 0 1280 720">'
        '<text x="0" y="100" font-size="60" id="big">气泡装饰</text>'
        '<text x="0" y="300" font-size="44" id="main-title">真正的页标题</text>'
        '</svg>'
    )
    assert agent_tools.svg_page_title(svg) == "真正的页标题"


def test_synthesize_uses_roster_count_and_disk_titles():
    """交付摘要：页数=成品完整页数（不去重）、标题=页信息（磁盘真实页标题）。"""
    from app.api.routers.agents import _synthesize_ppt_summary

    steps = [
        Step(tool="run_skill_script", args={}, ok=True, result={
            "生成文件": [{"名": "deck.pptx", "下载": "/u/deck.pptx"}],
            "页清单": ["01_a.svg", "02_b.svg", "03_c.svg", "04_d.svg"],
            "页信息": [
                {"名": "01_a.svg", "标题": "封面页"},
                {"名": "02_b.svg", "标题": "同一标题"},
                {"名": "03_c.svg", "标题": "同一标题"},
                {"名": "04_d.svg", "标题": ""},
            ],
        }),
    ]
    text, has = _synthesize_ppt_summary(PlanOutcome(steps=steps))
    assert has and "已生成 **4 页**" in text  # 不再因标题重复少算成 3 页
    assert text.count("同一标题") == 2       # 重复标题的页都要保留
    assert "d" in text                        # 无标题页回退文件名


def test_synthesize_marks_incomplete_build():
    from app.api.routers.agents import _synthesize_ppt_summary

    svg = "<svg><text font-size='40'>封面</text></svg>"
    steps = [
        Step(tool="write_skill_file", ok=True,
             args={"path": "projects/x/svg_output/01_cover.svg", "content": svg}, result={}),
    ]
    text, has = _synthesize_ppt_summary(PlanOutcome(steps=steps))
    assert not has and "构建未完成" in text and "1 页" in text


def test_strip_pseudo_toolcall_fences():
    txt = (
        "我先确认页面与规范。\n\n"
        "```\nlist_skill_files(skill=ppt-master, path=projects/xir/svg_output)\n```\n\n"
        "然后一次性写满 22 页并重建。\n"
        "write_skill_file(path=projects/x/01.svg)\n"
    )
    clean = llm.strip_toolcall_markup(txt)
    assert "list_skill_files" not in clean
    assert "write_skill_file" not in clean
    assert "我先确认页面与规范" in clean
    assert "然后一次性写满 22 页并重建" in clean


def test_page_diff_note_insert_after():
    from app.api.routers.agents import _page_diff_note

    prev = ["A", "B", "C", "D"]
    new = ["A", "B", "C", "X1", "X2", "D"]
    note = _page_diff_note(prev, new)
    assert "新增 2 页" in note
    assert "第 3 页后插入" in note and "X1、X2" in note
    assert "4 → 6" in note
    # 无变化 → 空
    assert _page_diff_note(prev, list(prev)) == ""


def test_page_diff_note_delete_page():
    from app.api.routers.agents import _page_diff_note

    note = _page_diff_note(["A", "B", "C"], ["A", "C"])
    assert "删除 1 页" in note and "B" in note and "3 → 2" in note


def test_delete_skill_file_tool_registered():
    names = {t["function"]["name"] for t in agent_tools.TOOLS_SCHEMA}
    assert "delete_skill_file" in names
    assert "delete_skill_file" in agent_tools._TOOL_FUNCS


def test_normalize_svg_order_keeps_insert_position(tmp_path):
    import re

    src = Path("seed_skills/ppt-master-adapter/scripts/ppt_oneshot.py").read_text(encoding="utf-8")
    num_prefix = re.search(r"_NUM_PREFIX\s*=\s*re\.compile\([^\n]+\)", src).group(0)
    fn = re.search(r"def _normalize_svg_order.*?(?=\ndef )", src, re.S).group(0)
    ns: dict = {"Path": Path, "re": re}
    exec(num_prefix, ns)
    exec(fn, ns)
    proj = tmp_path / "proj"
    d = proj / "svg_output"
    d.mkdir(parents=True)
    for n in ("01_cover.svg", "21_cta.svg", "21x_xinsai.svg", "22_end.svg"):
        (d / n).write_text("<svg/>", encoding="utf-8")
    ns["_normalize_svg_order"](proj)
    after = sorted(p.name for p in d.glob("*.svg"))
    # 连续序号，且插入页仍排在原第 21 页之后、结尾页之前
    assert after == ["01_cover.svg", "02_cta.svg", "03_x_xinsai.svg", "04_end.svg"]


def test_strip_tool_calls_markup_leak():
    txt = (
        "我先确认现有页的文件名。\n"
        '<tool_calls>\n<tool_calls>\n'
        '{"name": "list_skill_files", "arguments": {"skill": "ppt-master", "path": "projects/x"}}\n'
    )
    clean = llm.strip_toolcall_markup(txt)
    assert "tool_calls" not in clean
    assert "list_skill_files" not in clean
    assert "我先确认现有页的文件名" in clean
