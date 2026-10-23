# -*- coding: utf-8 -*-
"""Agent 工作台四项优化回归测试：
1) 广场收录 Skill 可被收录者解析/执行（物化到使用者目录，效果与发布者一致）；
2) 原生工具调用标记净化（二次编辑不再吐乱码）；
3) Skill 生成 PPT 时从工具轨迹提炼大纲（大纲/成果对齐、SVG 页可预览）。
"""

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models.agent_ext  # noqa: F401  确保建表
from app.core.database import Base

TEST_DB = "child_code_test_agent_workbench"


@pytest.fixture(scope="module")
def factory():
    from app.core.config import get_settings

    base = get_settings().DATABASE_URL.rsplit("/", 1)[0]
    admin_engine = create_engine(base + "/postgres", isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {TEST_DB}"))
    admin_engine.dispose()
    engine = create_engine(base + f"/{TEST_DB}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    yield Session
    engine.dispose()


def _mk_user(db, role="teacher", name="张三"):
    from app.models.user import User

    u = User(id=uuid.uuid4(), role=role, username=f"u-{uuid.uuid4().hex[:8]}", name=name, password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_plaza_skill_collect_and_materialize(factory, tmp_path, monkeypatch):
    """收录者能解析到作者的广场 Skill，并把文件包物化到自己目录（效果与作者一致）。"""
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.services import skill_bundle, agent_tools

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        author = _mk_user(db, name="zhang")
        user = _mk_user(db, name="teacher2")
        # 作者建 Skill（含脚本），发布到广场，落盘文件包到作者目录
        skill = ext.create_skill(
            db, owner_id=author.id, name="ppt-master", description="生成PPT",
            content="", files=["SKILL.md", "scripts/build.py"],
        )
        d = skill_bundle.skill_dir(author.id, skill.id)
        (d / "SKILL.md").write_text("# ppt-master\n入口 scripts/build.py", encoding="utf-8")
        (d / "scripts").mkdir(exist_ok=True)
        (d / "scripts" / "build.py").write_text("print('ok')", encoding="utf-8")
        ext.set_skill_visibility(db, skill, "plaza")

        # 收录者：未收录时 resolve 不到（除非广场可见，这里广场可见也应能解析）
        ext.collect_skill(db, user_id=user.id, skill_id=skill.id)
        resolved = ext.resolve_skill_for_user(db, user_id=user.id, skill_ref="ppt-master")
        assert resolved is not None and resolved.id == skill.id
        assert str(resolved.owner_id) == str(author.id)  # 真实 owner 是作者

        # 通过工具层解析 + 物化：文件应复制到使用者目录
        target, _avail = agent_tools._resolve_skill_for_exec(db, user, "ppt-master")
        assert target is not None
        user_dir = skill_bundle.skill_dir(user.id, skill.id)
        assert (user_dir / "SKILL.md").exists(), "物化后使用者目录应有 SKILL.md"
        assert (user_dir / "scripts" / "build.py").exists(), "物化后使用者目录应有脚本"
        assert skill_bundle.is_materialized(user.id, skill.id)
    finally:
        db.close()


def test_plaza_skill_inventory_visible_to_collector(factory, tmp_path, monkeypatch):
    """规划器清单对收录者可见广场 Skill（否则模型根本不会去调用它）。"""
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.services import agent_planner

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        author = _mk_user(db, name="zhang")
        user = _mk_user(db, name="t3")
        skill = ext.create_skill(
            db, owner_id=author.id, name="ppt-master", description="生成PPT",
            content="", files=["SKILL.md", "scripts/build.py"],
        )
        ext.set_skill_visibility(db, skill, "plaza")
        ext.collect_skill(db, user_id=user.id, skill_id=skill.id)
        inv = agent_planner._skill_inventory(db, user)
        assert "ppt-master" in inv
        assert "scripts/build.py" in inv
    finally:
        db.close()


def test_sanitizer_strips_toolcall_markup():
    """二次编辑乱码根因修复：原生工具调用标记被剔除（含跨 chunk 流式）。"""
    from app.services.llm import strip_toolcall_markup, _StreamSanitizer

    assert strip_toolcall_markup("好的。<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name=Bash") == "好的。"
    assert strip_toolcall_markup("正文<|tool\u2581calls\u2581begin|>garbage<|tool\u2581calls\u2581end|>结尾") == "正文结尾"
    assert strip_toolcall_markup('结果：\n<|tool\u2581calls\u2581begin|>\n{"x":1}\n<|tool\u2581calls\u2581end|>\n请查收') == "结果：\n\n请查收"
    assert strip_toolcall_markup("纯文本 a<b 正常") == "纯文本 a<b 正常"

    s = _StreamSanitizer()
    parts = ["好的，<|tool", "\u2581calls\u2581begin|>garbage<|tool\u2581calls", "\u2581end|>结束"]
    out = "".join(s.feed(p) for p in parts) + s.flush()
    assert out == "好的，结束", f"got {out!r}"


def test_derive_spec_from_tools_builds_outline():
    """Skill 用 write_skill_file 逐页写 svg → 提炼大纲，使大纲每页对应成品、svg 页可预览。"""
    from app.services.agent_planner import PlanOutcome, Step
    from app.api.routers.agents import _derive_spec_from_tools

    steps = [
        Step(tool="write_skill_file", args={"skill": "ppt-master", "path": "projects/demo/svg/01_cover.svg"}, ok=True, result={}),
        Step(tool="write_skill_file", args={"skill": "ppt-master", "path": "projects/demo/svg/02_outline.svg"}, ok=True, result={}),
        Step(tool="write_skill_file", args={"skill": "ppt-master", "path": "projects/demo/svg/03_content.svg"}, ok=True, result={}),
        Step(tool="run_skill_script", args={"skill": "ppt-master", "path": "scripts/build.py"}, ok=True, result={"生成文件": [{"名": "demo.pptx"}]}),
    ]
    spec = _derive_spec_from_tools(PlanOutcome(steps=steps))
    assert len(spec["outline"]) == 3
    assert spec["outline"][0]["kind"] == "cover"
    assert spec["outline"][0]["title"] == "cover"
    assert spec["outline"][1]["title"] == "outline"
    assert len(spec["slides"]) == 3


def test_derive_spec_no_svg_returns_empty():
    """没有写 svg 的工具轨迹 → 不臆造大纲（保持原有 json 解析结果）。"""
    from app.services.agent_planner import PlanOutcome, Step
    from app.api.routers.agents import _derive_spec_from_tools

    steps = [Step(tool="my_schedule_overview", args={}, ok=True, result={})]
    assert _derive_spec_from_tools(PlanOutcome(steps=steps)) == {}


def test_looks_like_ppt_edit_gate():
    """PPT 二次编辑意图识别：加/删/改页/调顺序 → True；纯从零生成 → False。"""
    from app.services.agent_tools import looks_like_ppt_edit

    assert looks_like_ppt_edit("加一页，第二页放内容大纲") is True
    assert looks_like_ppt_edit("把第 3 页删掉") is True
    assert looks_like_ppt_edit("把封面标题改成家长会") is True
    assert looks_like_ppt_edit("调一下页顺序") is True
    assert looks_like_ppt_edit("换个风格") is True
    # 纯生成（无编辑词）→ False
    assert looks_like_ppt_edit("帮我做一个关于少儿编程的PPT") is False
    assert looks_like_ppt_edit("生成一份家长会PPT") is False
    assert looks_like_ppt_edit("") is False


def test_existing_pptx_block_lists_sources(factory, tmp_path, monkeypatch):
    """PPT 二次编辑：把已有 .pptx 源文件路径注入上下文，供「就地改」。"""
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.services import skill_bundle
    from app.api.routers.agents import _existing_pptx_block

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        user = _mk_user(db, name="ppt-user")
        skill = ext.create_skill(
            db, owner_id=user.id, name="ppt-master", description="生成PPT",
            content="", files=["projects/demo/out.pptx"],
        )
        d = skill_bundle.skill_dir(user.id, skill.id)
        (d / "projects" / "demo").mkdir(parents=True, exist_ok=True)
        (d / "projects" / "demo" / "out.pptx").write_bytes(b"PK\x03\x04fake")
        block = _existing_pptx_block(db, user)
        assert "projects/demo/out.pptx" in block
        assert "Edit Native PPTX" in block
    finally:
        db.close()


def test_existing_pptx_block_empty_without_pptx(factory, tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.api.routers.agents import _existing_pptx_block

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        user = _mk_user(db, name="no-ppt")
        ext.create_skill(db, owner_id=user.id, name="x", description="", content="hi", files=[])
        assert _existing_pptx_block(db, user) == ""
    finally:
        db.close()

def test_attachment_block_acknowledges_images():
    """图片附件块：明确告知图片数量+文件名+磁盘路径，并要求回复确认收到（避免「看不见图」）。"""
    from app.api.routers.agents import _attachment_block

    block = _attachment_block([
        {"name": "课堂照片.jpg", "kind": "image", "url": "/uploads/chat/c1/a.jpg"},
        {"name": "课件.pdf", "kind": "doc", "url": "/uploads/chat/c1/b.pdf", "text": "课件正文内容"},
    ])
    assert "课堂照片.jpg" in block
    assert "已收到" in block or "收到这" in block
    assert "磁盘路径" in block
    assert "课件正文内容" in block  # 文档正文仍注入
    # 图片数量提示
    assert "1 张图片" in block or "1 张" in block


def test_attachment_block_no_image_no_ack():
    """仅文档时不应出现「图片须回应」的强指令。"""
    from app.api.routers.agents import _attachment_block

    block = _attachment_block([{"name": "a.txt", "kind": "doc", "text": "x"}])
    assert "张图片" not in block

def test_looks_like_ppt_continue_gate():
    """问题3：催出片/继续/下载 等续作意图要能识别（否则模型只空口出片不执行）。"""
    from app.services.agent_tools import looks_like_ppt_continue

    assert looks_like_ppt_continue("出片把") is True
    assert looks_like_ppt_continue("继续") is True
    assert looks_like_ppt_continue("给我PPTx下载啊，") is True
    assert looks_like_ppt_continue("文件呢") is True
    assert looks_like_ppt_continue("生成好了吗") is True
    assert looks_like_ppt_continue("今天天气不错我们聊点别的吧这件事之后再说") is False


def test_auto_build_ppt_picks_fresh_project(factory, tmp_path, monkeypatch):
    """问题3兜底：模型写了 svg 但没导出时，auto_build_ppt 能找到项目并跑 build 出片。"""
    import time
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.services import skill_bundle, agent_tools

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        user = _mk_user(db, name="autobuild")
        skill = ext.create_skill(
            db, owner_id=user.id, name="ppt-master", description="",
            content="", files=["manifests/x.txt"],
        )
        desk = skill_bundle.skill_dir(user.id, skill.id)
        # 造一个适配版 wrapper + 一个有 svg_output 的项目
        wrap_dir = desk / "ppt-master-main/skills/ppt-master/scripts"
        wrap_dir.mkdir(parents=True, exist_ok=True)
        (wrap_dir / "ppt_oneshot.py").write_text(
            "import sys,os\n"
            "proj=sys.argv[2]\n"
            "os.makedirs(os.path.join(proj,'exports'),exist_ok=True)\n"
            "open(os.path.join(proj,'exports','out.pptx'),'wb').write(b'PK\\x03\\x04fake')\n"
            "print('ok')\n",
            encoding="utf-8",
        )
        proj = desk / "projects" / "demo"
        (proj / "svg_output").mkdir(parents=True, exist_ok=True)
        (proj / "svg_output" / "01_cover.svg").write_text("<svg/>", encoding="utf-8")
        # 登记 files 让 execute_tool 能找到 wrapper
        files = [str(f) for f in (skill.files or [])]
        files += ["ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py"]
        ext.update_skill(db, skill, files=files)

        out = agent_tools.auto_build_ppt(db, user)
        assert out is not None, "应找到项目并执行 build"
        assert out.get("成功") is True, f"build 应成功: {out}"
    finally:
        db.close()


def test_auto_build_ppt_skips_stale_project(factory, tmp_path, monkeypatch):
    """问题2/3：太旧的项目（>60 分钟）不自动抓，避免串到别的旧会话。"""
    import os
    import time
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.services import skill_bundle, agent_tools

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        user = _mk_user(db, name="autobuild-stale")
        skill = ext.create_skill(
            db, owner_id=user.id, name="ppt-master", description="",
            content="", files=["ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py"],
        )
        desk = skill_bundle.skill_dir(user.id, skill.id)
        wrap = desk / "ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py"
        wrap.parent.mkdir(parents=True, exist_ok=True)
        wrap.write_text("print('ok')\n", encoding="utf-8")
        proj = desk / "projects" / "old"
        sd = proj / "svg_output"
        sd.mkdir(parents=True, exist_ok=True)
        old_svg = sd / "01_cover.svg"
        old_svg.write_text("<svg/>", encoding="utf-8")
        old = time.time() - 3 * 3600
        os.utime(old_svg, (old, old))
        out = agent_tools.auto_build_ppt(db, user)
        assert out is None, "旧项目不应被自动抓取"
    finally:
        db.close()
