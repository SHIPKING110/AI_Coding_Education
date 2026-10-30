# -*- coding: utf-8 -*-
"""出片失败兜底 + 门禁自愈扩充 + 脚本版本对齐 回归测试：

1) 失败/旁白回复不再原样丢给用户：无成品时输出可执行的下一步说明（含定位页）；
2) 新自愈规则：text 内 span→tspan、<g> filter 移除、文本越界按估宽收缩、spec_lock 自动补 typography；
3) ppt-master 适配脚本按标记同步到所有用户包（管理员/教师同版本、同质量）。
"""

import re
from pathlib import Path

from app.api.routers import agents as agents_router
from app.services import llm
from app.services.agent_planner import PlanOutcome, Step


def _fail_outcome():
    return PlanOutcome(steps=[
        Step(tool="write_skill_file", ok=True, args={"path": "projects/x/svg_output/06_concept.svg"}, result={}),
        Step(tool="run_skill_script", ok=True, args={}, result={
            "成功": False,
            "stdout": "06_concept.svg: svg: data-pptx-role belongs on a visual SVG element\n"
                      "09_works.svg: <text> exceeds the root viewBox",
            "stderr": "",
        }),
    ])


def test_narration_detection_sample():
    txt = ("好，按现有 16 页出片。上一轮 build 质量门禁报了 2 个 error，"
           "我先把报告读出来，定位到具体页改掉，再重跑导出。")
    assert agents_router._looks_like_narration(txt)


def test_failure_notice_is_actionable():
    note = agents_router._pptx_failure_notice(_fail_outcome())
    assert "没有成功导出成品" in note
    assert "06_concept.svg" in note  # 定位到失败页
    assert "继续修复" in note and "先导出前 N 页" in note
    assert "质量门禁" not in note and "build" not in note  # 不暴露内部术语


def test_has_pptx_result():
    ok = PlanOutcome(steps=[
        Step(tool="run_skill_script", ok=True, args={}, result={
            "生成文件": [{"名": "deck.pptx", "下载": "/u/deck.pptx"}],
        }),
    ])
    assert agents_router._has_pptx_result(ok)
    assert not agents_router._has_pptx_result(_fail_outcome())


def _load_oneshot_funcs(*names):
    src = Path("seed_skills/ppt-master-adapter/scripts/ppt_oneshot.py").read_text(encoding="utf-8")
    ns = {"Path": Path, "re": re}
    # 先取常量/工具函数
    for pat in (r"_NUM_PREFIX\s*=\s*re\.compile\([^\n]+\)",
                r"def _text_estimate_width.*?(?=\ndef )"):
        m = re.search(pat, src, re.S)
        if m:
            exec(m.group(0), ns)
    for name in names:
        m = re.search(rf"def {name}.*?(?=\ndef )", src, re.S)
        assert m, name
        exec(m.group(0), ns)
    return ns


def test_sanitize_spans_and_filters(tmp_path):
    ns = _load_oneshot_funcs("_sanitize_spans", "_sanitize_filters")
    proj = tmp_path / "p"
    d = proj / "svg_output"
    d.mkdir(parents=True)
    svg = (
        '<svg viewBox="0 0 1280 720">'
        '<g filter="url(#blur)"><text font-size="20">A<span font-weight="bold">B</span></text></g>'
        '</svg>'
    )
    (d / "01_a.svg").write_text(svg, encoding="utf-8")
    ns["_sanitize_spans"](proj)
    ns["_sanitize_filters"](proj)
    out = (d / "01_a.svg").read_text(encoding="utf-8")
    assert "<span" not in out and "<tspan" in out
    assert 'filter="url(#blur)"' not in out


def test_sanitize_text_fit_shrinks_overflow(tmp_path):
    ns = _load_oneshot_funcs("_sanitize_text_fit")
    proj = tmp_path / "p"
    d = proj / "svg_output"
    d.mkdir(parents=True)
    svg = (
        '<svg viewBox="0 0 1280 720">'
        '<text x="1060" y="500" font-size="180">C++</text>'
        '</svg>'
    )
    (d / "01_a.svg").write_text(svg, encoding="utf-8")
    ns["_sanitize_text_fit"](proj)
    out = (d / "01_a.svg").read_text(encoding="utf-8")
    fs = float(re.search(r'font-size="([0-9.]+)"', out).group(1))
    assert fs < 180  # 越界文本被缩小


def test_ensure_spec_lock_adds_typography(tmp_path):
    ns = _load_oneshot_funcs("_ensure_spec_lock")
    proj = tmp_path / "p"
    proj.mkdir()
    ns["_ensure_spec_lock"](proj)
    text = (proj / "spec_lock.md").read_text(encoding="utf-8")
    assert "## typography" in text and "- title:" in text and "- body:" in text


def test_sync_ppt_adapter_updates_bundles(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.services import skill_bundle

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    # 造一个「旧版适配器」包 + 一个用户自装同名脚本包
    adapter = tmp_path / "skills" / "u1" / "s1" / "wrap" / "scripts"
    adapter.mkdir(parents=True)
    (adapter / "ppt_oneshot.py").write_text("# PPT-Master 兼容适配器 old\n", encoding="utf-8")
    user_own = tmp_path / "skills" / "u2" / "s2" / "wrap" / "scripts"
    user_own.mkdir(parents=True)
    (user_own / "ppt_oneshot.py").write_text("# user own script\n", encoding="utf-8")

    updated = skill_bundle.sync_ppt_adapter()
    assert updated == 1
    assert "PPT-Master 兼容适配器" in (adapter / "ppt_oneshot.py").read_text(encoding="utf-8")
    assert (user_own / "ppt_oneshot.py").read_text(encoding="utf-8") == "# user own script\n"


def test_tool_calls_markup_and_pseudo_fence_removed():
    txt = (
        "先给计划。\n"
        "```\nlist_skill_files(skill=ppt-master, path=projects/x)\n```\n"
        "好的。\n<tool_calls>\n{\"name\": \"write_skill_file\"}\n"
    )
    clean = llm.strip_toolcall_markup(txt)
    assert "list_skill_files" not in clean and "tool_calls" not in clean
    assert "先给计划" in clean


def test_has_pptx_uses_last_build_result():
    from app.services.agent_planner import PlanOutcome, Step

    steps = [
        Step(tool="run_skill_script", ok=True, args={}, result={
            "生成文件": [{"名": "deck_old.pptx", "下载": "/u/old.pptx"}],
        }),
        Step(tool="run_skill_script", ok=True, args={}, result={
            "生成文件": [], "成功": False, "stdout": "06_a.svg: exceeds root viewBox",
        }),
    ]
    assert not agents_router._has_pptx_result(PlanOutcome(steps=steps))
