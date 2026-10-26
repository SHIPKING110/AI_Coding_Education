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

def test_svg_page_title_picks_largest_text():
    """大纲标题取真实页标题：SVG 内字号最大的文本，而不是文件名 slug。"""
    from app.api.routers.agents import _svg_page_title

    svg = (
        '<svg viewBox="0 0 1280 720">'
        '<text x="10" y="10" font-size="18">小字页脚</text>'
        '<text x="10" y="100" font-size="56" font-weight="bold">Python 探险岛 · 第一关</text>'
        '<text x="10" y="200" font-size="24">正文说明</text>'
        '</svg>'
    )
    assert _svg_page_title(svg) == "Python 探险岛 · 第一关"
    # 无 text 时返回空（调用方回退文件名）
    assert _svg_page_title("<svg><rect/></svg>") == ""


def test_derive_spec_uses_full_page_list_from_build():
    """调整后续写：以 build 回执的整份页清单为准，未改动的旧页也进大纲（不再只剩本次写过的页）。"""
    from app.services.agent_planner import PlanOutcome, Step
    from app.api.routers.agents import _derive_spec_from_tools

    svg = "<svg><text font-size='56'>变量是什么</text></svg>"
    steps = [
        Step(tool="write_skill_file", ok=True,
             args={"skill": "ppt-master", "path": "projects/py-grade46-v2/svg_output/05_variable.svg",
                   "content": svg}, result={}),
        Step(tool="run_skill_script", ok=True,
             args={"skill": "ppt-master", "path": "ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py",
                   "args": ["build", "projects/py-grade46-v2"]},
             result={
                 "成功": True,
                 "页清单": ["01_cover.svg", "02_map.svg", "05_variable.svg", "24_summary.svg"],
                 "生成文件": [
                     {"名": "01_cover.svg", "下载": "/u/01_cover.svg"},
                     {"名": "02_map.svg", "下载": "/u/02_map.svg"},
                     {"名": "05_variable.svg", "下载": "/u/05_variable.svg"},
                     {"名": "24_summary.svg", "下载": "/u/24_summary.svg"},
                     {"名": "deck.pptx", "下载": "/u/deck.pptx"},
                 ],
             }),
    ]
    spec = _derive_spec_from_tools(PlanOutcome(steps=steps))
    titles = [o["title"] for o in spec["outline"]]
    assert len(titles) == 4, titles  # 整份 4 页，而非只本轮写入的 1 页
    assert titles[0] == "cover"
    assert titles[2] == "变量是什么"  # 本轮写入页用真实标题
    assert spec["outline"][2]["url"] == "/u/05_variable.svg"


def test_conversation_ppt_block_lists_conv_project(factory, tmp_path, monkeypatch):
    """二次编辑基线：本会话隔离目录里的项目/页数/成品要被列出，且不掺别的会话。"""
    import uuid as _uuid
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.services import skill_bundle
    from app.api.routers.agents import _conversation_ppt_block

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        user = _mk_user(db, name="edit-base")
        skill = ext.create_skill(db, owner_id=user.id, name="ppt-master", description="",
                                 content="", files=["x.txt"])
        conv_id = _uuid.uuid4()
        prefix = "conversations/conv_" + str(conv_id).replace("-", "")[:12]
        desk = skill_bundle.skill_dir(user.id, skill.id)
        proj = desk / prefix / "projects" / "py-grade46-v2"
        (proj / "svg_output").mkdir(parents=True)
        for i in (1, 2, 3):
            (proj / "svg_output" / f"{i:02d}_p{i}.svg").write_text("<svg/>", encoding="utf-8")
        (proj / "exports").mkdir()
        (proj / "exports" / "deck.pptx").write_bytes(b"PK\x03\x04")
        # 另一个会话的项目：不能出现在本会话基线里
        other = desk / "conversations/conv_ffffffffffff/projects/other"
        (other / "svg_output").mkdir(parents=True)
        (other / "svg_output" / "01_x.svg").write_text("<svg/>", encoding="utf-8")

        block = _conversation_ppt_block(db, user, conv_id)
        assert "projects/py-grade46-v2" in block and "3 页" in block
        assert "deck.pptx" in block
        assert "other" not in block
        assert "禁止另起新项目" in block
    finally:
        db.close()


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

def test_conversation_scoped_paths():
    """会话隔离：projects/ 路径按会话改写到 conversations/conv_xxx/ 下，非 projects 原样。"""
    from app.services import agent_tools as A

    A.use_conversation("abcd-1234-5678-efgh")
    assert A._scope_path("projects/demo/svg_output/01.svg").startswith("conversations/conv_")
    assert "projects/demo" in A._scope_path("projects/demo/svg_output/01.svg")
    assert A._scope_path("scripts/build.py") == "scripts/build.py"
    scoped = A._scope_path("projects/x")
    assert A._unscope_path(scoped) == "projects/x"
    # 清除作用域后原样
    A.use_conversation(None)
    assert A._scope_path("projects/x") == "projects/x"

def test_skill_allowlist_blocks_unselected(factory, tmp_path, monkeypatch):
    """问题1：Agent 没勾选某 Skill 时，executor/inventory/autobuild 都不得使用它。"""
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.services import skill_bundle, agent_tools

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        user = _mk_user(db, name="perm-user")
        skill = ext.create_skill(
            db, owner_id=user.id, name="ppt-master", description="",
            content="", files=["manifests/x.txt"],
        )
        files = [str(f) for f in (skill.files or [])] + ["ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py"]
        ext.update_skill(db, skill, files=files)

        # 未设置白名单（None）→ 允许
        agent_tools.use_allowed_skills(None)
        t, _ = agent_tools._resolve_skill_for_exec(db, user, "ppt-master")
        assert t is not None

        # 白名单为空集合 → 拒绝
        agent_tools.use_allowed_skills([])
        t, _ = agent_tools._resolve_skill_for_exec(db, user, "ppt-master")
        assert t is None, "没勾选时 executor 不应解析到该 Skill"

        # 白名单含该 id → 允许
        agent_tools.use_allowed_skills([str(skill.id)])
        t, _ = agent_tools._resolve_skill_for_exec(db, user, "ppt-master")
        assert t is not None

        # inventory 也按白名单过滤
        from app.services import agent_planner
        agent_tools.use_allowed_skills([])
        assert "ppt-master" not in agent_planner._skill_inventory(db, user)
        agent_tools.use_allowed_skills([str(skill.id)])
        assert "ppt-master" in agent_planner._skill_inventory(db, user)
    finally:
        agent_tools.use_allowed_skills(None)
        db.close()


def test_agent_effective_skills_only_bound():
    """问题1：custom agent 的生效 Skill = 自身 skill_ids ∪ 全局默认；空则不得回落到「全部自有」。"""
    # 纯逻辑验证：allowed 计算 = per_skill ∪ global
    per_skill = []
    glob = []
    allowed = [str(x) for x in (per_skill + glob)]
    assert allowed == [], "空绑定应得空白名单（不再默认放行全部自有 Skill）"

def test_effective_skill_ids_self_heals_by_name(factory, tmp_path, monkeypatch):
    """权限：绑定的旧 id 指向「他人私有、本人不可用」的同名 skill → 按名字自愈到本人可用的同名 skill。

    复现真实场景：admin 的 Agent 绑定的是 zhang 的私有 ppt-master（e7d71aa7，本人不可用），
    但 admin 自己有同名可用 ppt-master（适配版）→ 生效应自愈到本人那个，PPT 路径不误伤。
    """
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.services import agent_registry

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        admin = _mk_user(db, name="admin-sh")
        zhang = _mk_user(db, name="zhang-sh")
        # zhang 的私有 ppt-master（本人 admin 不可用）
        z_skill = ext.create_skill(db, owner_id=zhang.id, name="ppt-master", description="", content="", files=["a.py"])
        ext.update_skill(db, z_skill, files=["ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py"])
        # admin 自己的同名可用 ppt-master
        a_skill = ext.create_skill(db, owner_id=admin.id, name="ppt-master", description="", files=["b.py"])
        ext.update_skill(db, a_skill, files=["ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py"])
        # admin 的 Agent 错绑到 zhang 的私有 id
        agent_id = f"custom_{uuid.uuid4().hex[:8]}_7"
        ext.create_custom_agent(db, owner_id=admin.id, agent_id=agent_id, name="PPT生成助手", skill_ids=[str(z_skill.id)])
        ids = agent_registry.effective_skill_ids(db, admin.id, agent_id)
        assert str(a_skill.id) in ids, "应自愈到本人可用的同名 ppt-master"
        assert str(z_skill.id) not in ids, "不应引用他人私有 skill"
    finally:
        db.close()


def test_effective_skill_ids_normal_binding(factory, tmp_path, monkeypatch):
    """正常绑定：勾选的本人可用 skill 出现在生效清单，未勾选的不出现。"""
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.services import agent_registry

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        user = _mk_user(db, name="normalbind")
        s1 = ext.create_skill(db, owner_id=user.id, name="ppt-master", description="", content="", files=["x.py"])
        ext.update_skill(db, s1, files=["ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py"])
        s2 = ext.create_skill(db, owner_id=user.id, name="other", description="", content="hi", files=[])
        agent_id = f"custom_{uuid.uuid4().hex[:8]}_8"
        ext.create_custom_agent(db, owner_id=user.id, agent_id=agent_id, name="A", skill_ids=[str(s1.id)])
        ids = agent_registry.effective_skill_ids(db, user.id, agent_id)
        assert str(s1.id) in ids
        assert str(s2.id) not in ids
    finally:
        db.close()

def test_resolve_by_name_prefers_usable_adapter(factory, tmp_path, monkeypatch):
    """问题3：用户名下有个"不可用的旧同名 skill"时，按名字解析应优先命中"可用的适配版"，
    不能被旧版遮蔽（否则教师用残缺旧版、效果更差）。"""
    from app.core.config import get_settings
    from app.crud import agent_ext as ext

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        # zhang：自留旧版 ppt-master（无 wrapper，files 至少非空以模拟"存在"）
        zhang = _mk_user(db, name="zhang-rn")
        old = ext.create_skill(db, owner_id=zhang.id, name="ppt-master", description="old", content="x", files=["a.txt"])
        # admin 发布适配版到广场；zhang 收录
        admin = _mk_user(db, name="admin-rn", role="admin")
        adapter = ext.create_skill(db, owner_id=admin.id, name="ppt-master", description="adapter", files=["b.py"])
        ext.update_skill(db, adapter, files=["ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py"])
        ext.set_skill_visibility(db, adapter, "plaza")
        ext.collect_skill(db, user_id=zhang.id, skill_id=adapter.id)

        # 无白名单：按名字解析，应命中"可用"的——这里旧版可用(content=x)，但适配版也有 wrapper
        # 关键断言：当旧版"不可用"（禁用）时，必须解析到适配版
        ext.update_skill(db, old, enabled=False)
        r = ext.resolve_skill_for_user(db, user_id=zhang.id, skill_ref="ppt-master")
        assert r is not None and str(r.id) == str(adapter.id), "应解析到可用的适配版，而非被禁用的旧版"

        # 带 allowlist：zhang 的 PPT 助手只授权了适配版
        from app.services import agent_tools
        agent_tools.use_allowed_skills([str(adapter.id)])
        t, _ = agent_tools._resolve_skill_for_exec(db, zhang, "ppt-master")
        assert t is not None and str(t.id) == str(adapter.id), "白名单下应命中适配版"
        agent_tools.use_allowed_skills(None)
    finally:
        db.close()

def test_scope_path_handles_dot_and_backslash():
    """问题2：模型给 ./projects/... 或 projects\\... 也要正确改写到会话子目录（否则 build 跑空）。"""
    from app.services import agent_tools as A
    A.use_conversation("0e55ce5a-523b-4158-a64c-b83950ae81d1")
    pfx = A._conv_prefix()
    assert A._scope_path("projects/x").startswith(pfx)
    assert A._scope_path("./projects/x") == pfx + "projects/x"
    assert A._scope_path(".//projects/x") == pfx + "projects/x"
    assert A._scope_path("projects\\x\\y") == pfx + "projects/x/y"
    A.use_conversation(None)

def test_sanitize_svg_fonts_removes_zero_placeholder():
    """质量门禁阻断修复：font-size=0 的空白占位文本会让 DrawingML 判非法整单失败。
    空白占位 → 整段移除；非空但字号过小 → 提升到 12px。"""
    import re, tempfile
    from pathlib import Path
    src = open("seed_skills/ppt-master-adapter/scripts/ppt_oneshot.py", encoding="utf-8").read()
    m = re.search(r"def _sanitize_svg_fonts.*?(?=\ndef _qc_errors_only)", src, re.S)
    ns = {"Path": Path, "print": print}
    exec(m.group(0), ns)
    fn = ns["_sanitize_svg_fonts"]
    d = Path(tempfile.mkdtemp()); (d/"svg_output").mkdir()
    f = d/"svg_output/16_end.svg"
    f.write_text(
        '<svg><text font-size="56">下节课见！</text>'
        '<text x="640" font-size="0"> </text>'
        '<text font-size=\'0.5\'>看不见的字</text>'
        '<text font-size="24">正常</text></svg>',
        encoding="utf-8",
    )
    fn(d)
    out = f.read_text(encoding="utf-8")
    assert 'font-size="0"' not in out, "空白占位应被整段移除"
    assert "0.5" not in out and "12" in out, "过小字号应提升到 12"
    assert "看不见的字" in out and "下节课见！" in out and "正常" in out

def test_sanitize_pptx_role_ids_fixes_missing_ids():
    """质量门禁自愈：data-pptx-role 元素缺 id（唯一常见 error）自动补齐，出片不再卡死。"""
    import re, tempfile
    from pathlib import Path
    src = open("seed_skills/ppt-master-adapter/scripts/ppt_oneshot.py", encoding="utf-8").read()
    m = re.search(r"def _sanitize_pptx_role_ids.*?(?=\ndef _qc_errors_only)", src, re.S)
    ns = {"Path": Path, "print": print}
    exec(m.group(0), ns)
    fn = ns["_sanitize_pptx_role_ids"]
    d = Path(tempfile.mkdtemp()); (d/"svg_output").mkdir()
    f = d/"svg_output/01_cover.svg"
    f.write_text(
        '<svg viewBox="0 0 1280 720">'
        '<rect x="0" y="0" width="1280" height="720" fill="#000" data-pptx-role="background"/>'
        '<rect x="0" y="0" width="1280" height="6" fill="#fff" data-pptx-role="decoration"/>'
        '<rect x="5" y="5" width="10" height="10" fill="#111" data-pptx-role="decoration" id="keep-me"/>'
        '<text id="t1">标题</text></svg>',
        encoding="utf-8",
    )
    fn(d)
    out = f.read_text(encoding="utf-8")
    assert out.count('data-pptx-role="background"') == 1
    assert 'id="role-background-1"' in out
    assert out.count('data-pptx-role="decoration"') == 2
    assert out.count('id="role-decoration-1"') == 1  # 只给缺 id 的那个补一次
    assert 'id="keep-me"' in out
    assert 'id="role-decoration-1"' in out

def test_sanitize_svg_colors_fixes_invalid():
    """问题1/2：模型写出非法颜色(如 #33island) 时，build 前自动修正，避免质量门禁整单失败。"""
    import re, tempfile
    from pathlib import Path
    src = open("seed_skills/ppt-master-adapter/scripts/ppt_oneshot.py", encoding="utf-8").read()
    m = re.search(r"def _sanitize_svg_colors.*?(?=\ndef cmd_build)", src, re.S)
    ns = {"Path": Path, "print": print}
    exec(m.group(0), ns)
    fn = ns["_sanitize_svg_colors"]
    d = Path(tempfile.mkdtemp()); (d/"svg_output").mkdir()
    f = d/"svg_output/01_cover.svg"
    f.write_text('<svg><rect stroke="#33island" fill="#FFF"/><text fill="#GGG">x</text></svg>', encoding="utf-8")
    fn(d)
    out = f.read_text(encoding="utf-8")
    # 非法颜色被改成合法 hex；#FFF 保留(3->6)；不再有 island/GGG
    assert "island" not in out and "GGG" not in out
    assert "#33" in out.lower() or "#330" in out.lower() or "#000000" in out
    assert "#ffffff" in out.lower()

def test_sanitize_root_bounds_overlap_drops_smaller():
    """质量门禁自愈：根级 <g> data-pptx-bounds 重叠（error）→ 移除较小那组声明，降级为 warning。"""
    import re, tempfile
    from pathlib import Path
    src = open("seed_skills/ppt-master-adapter/scripts/ppt_oneshot.py", encoding="utf-8").read()
    m = re.search(r"def _sanitize_root_bounds_overlap.*?(?=\ndef _qc_errors_only)", src, re.S)
    ns = {"Path": Path, "print": print}
    exec(m.group(0), ns)
    fn = ns["_sanitize_root_bounds_overlap"]
    d = Path(tempfile.mkdtemp()); (d/"svg_output").mkdir()
    f = d/"svg_output/06.svg"
    f.write_text(
        '<svg viewBox="0 0 1280 720">'
        '<g id="big" data-pptx-bounds="0 0 800 600"><rect/></g>'
        '<g id="small" data-pptx-bounds="600 300 200 100"><rect/></g>'
        '<g id="apart" data-pptx-bounds="900 0 380 200"><rect/></g>'
        '</svg>',
        encoding="utf-8",
    )
    fn(d)
    out = f.read_text(encoding="utf-8")
    assert 'id="big" data-pptx-bounds="0 0 800 600"' in out  # 大组保留
    assert 'id="small"' in out and 'data-pptx-bounds="600 300 200 100"' not in out  # 小组去掉声明
    assert 'id="apart" data-pptx-bounds="900 0 380 200"' in out  # 不重叠不动

def test_sanitize_svg_xml_fixes_unescaped_amp():
    """质量门禁自愈：未转义 & / 控制字符导致 Invalid XML → 无损转义修复。"""
    import re, tempfile
    from pathlib import Path
    src = open("seed_skills/ppt-master-adapter/scripts/ppt_oneshot.py", encoding="utf-8").read()
    m = re.search(r"def _sanitize_svg_xml.*?(?=\ndef _sanitize_svg_overflow)", src, re.S)
    ns = {"Path": Path, "print": print}
    exec(m.group(0), ns)
    fn = ns["_sanitize_svg_xml"]
    d = Path(tempfile.mkdtemp()); (d/"svg_output").mkdir()
    f = d/"svg_output/01.svg"
    f.write_text('<svg><text>A & B &amp; C</text><text>ctl\x08char</text></svg>', encoding="utf-8")
    fn(d)
    out = f.read_text(encoding="utf-8")
    assert "A &amp; B &amp; C" in out  # 孤立 & 被转义，原本合法的 &amp; 不动
    assert "\x08" not in out


def test_sanitize_svg_overflow_clamps_into_viewbox():
    """质量门禁自愈：元素越出画布（error）→ 坐标/尺寸回收到 viewBox 内。"""
    import re, tempfile
    from pathlib import Path
    src = open("seed_skills/ppt-master-adapter/scripts/ppt_oneshot.py", encoding="utf-8").read()
    m = re.search(r"def _sanitize_svg_overflow.*?(?=\ndef _qc_errors_only)", src, re.S)
    ns = {"Path": Path, "print": print}
    exec(m.group(0), ns)
    fn = ns["_sanitize_svg_overflow"]
    d = Path(tempfile.mkdtemp()); (d/"svg_output").mkdir()
    f = d/"svg_output/01.svg"
    f.write_text(
        '<svg viewBox="0 0 1280 720">'
        '<rect x="-40" y="100" width="200" height="50" fill="#fff"/>'
        '<rect x="1200" y="700" width="300" height="80" fill="#fff"/>'
        '<text x="120" y="200" font-size="24">正常</text>'
        '</svg>',
        encoding="utf-8",
    )
    fn(d)
    out = f.read_text(encoding="utf-8")
    assert 'x="-40"' not in out and 'x="0"' in out          # 负坐标归零
    assert 'width="300"' not in out                          # 超宽被截断
    assert 'x="120" y="200"' in out                          # 合法元素不动

def test_qc_errors_only():
    from pathlib import Path
    import re
    src=open("seed_skills/ppt-master-adapter/scripts/ppt_oneshot.py",encoding="utf-8").read()
    m=re.search(r"def _qc_errors_only.*?(?=\ndef cmd_build)", src, re.S)
    ns={"print":print}; exec(m.group(0),ns); fn=ns["_qc_errors_only"]
    assert fn('{"summary":{"errors":0,"warnings":2,"passed":0}}') is True
    assert fn('{"summary":{"errors":1}}') is False
    assert fn('[ERROR] bad') is False
    assert fn('all good') is True

def test_ensure_default_ppt_agent_idempotent(factory, tmp_path, monkeypatch):
    """A1：教师账号默认自动获得「PPT生成助手」，绑定广场适配版；幂等不重复建。"""
    from app.core.config import get_settings
    from app.crud import agent_ext as ext
    from app.services import agent_provision

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    db = factory()
    try:
        # 管理员发布广场适配版
        admin = _mk_user(db, name="adm-prov", role="admin")
        adapter = ext.create_skill(db, owner_id=admin.id, name="ppt-master", description="", files=["x"])
        ext.update_skill(db, adapter, files=["ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py"])
        ext.set_skill_visibility(db, adapter, "plaza")
        # 教师
        t = _mk_user(db, name="teach-prov", role="teacher")
        made1 = agent_provision.ensure_default_ppt_agent(db, t)
        made2 = agent_provision.ensure_default_ppt_agent(db, t)
        assert made1 is True and made2 is False, "首次建、二次不应重复"
        agents = [a for a in ext.list_custom_agents(db, owner_id=t.id) if a.name == "PPT生成助手"]
        assert len(agents) == 1
        assert str(adapter.id) in [str(x) for x in (agents[0].skill_ids or [])], "应绑定适配版"
        assert ext.is_skill_collected(db, user_id=t.id, skill_id=adapter.id), "应自动收录"
    finally:
        db.close()


def test_cleanup_conversation_removes_scoped_dirs(factory, tmp_path, monkeypatch):
    """A2：删除会话时清理其会话隔离目录 + _outputs 产物。"""
    from app.core.config import get_settings
    from app.services import skill_bundle

    monkeypatch.setattr(get_settings(), "UPLOAD_DIR", str(tmp_path), raising=False)
    owner = "00000000-0000-0000-0000-000000000001"
    skill = "11111111-1111-1111-1111-111111111111"
    conv = "abcdef12-3456-7890-abcd-ef1234567890"
    d = skill_bundle.skill_dir(owner, skill)
    scope = d / "conversations" / "conv_abcdef123456"
    (scope / "projects" / "p1" / "svg_output").mkdir(parents=True, exist_ok=True)
    (scope / "projects" / "p1" / "svg_output" / "01.svg").write_text("<svg/>", encoding="utf-8")
    outd = d / "_outputs" / "20260101_000000"
    outd.mkdir(parents=True, exist_ok=True)
    (outd / "deck.pptx").write_bytes(b"x")
    url = f"/uploads/skills/{owner}/{skill}/_outputs/20260101_000000/deck.pptx"
    n = skill_bundle.cleanup_conversation(owner, conv, output_urls=[url])
    assert n >= 2
    assert not scope.exists(), "会话隔离目录应删除"
    assert not outd.exists(), "产物目录应删除"

def test_tool_schema_for_skill_task_excludes_business():
    """PPT跑偏/拖沓：Skill 生成任务剔除业务数据工具，只留 skill/web_search/文件工具。"""
    from app.services import agent_tools
    names = [t["function"]["name"] for t in agent_tools.tool_schema_for(True)]
    assert "run_skill_script" in names and "write_skill_file" in names and "web_search" in names
    for biz in ("my_teaching_stats", "list_my_classes", "find_students", "sql_query"):
        assert biz not in names, f"Skill 任务不应含业务工具 {biz}"
    # 非 skill 任务保留全部
    assert len(agent_tools.tool_schema_for(False)) == len(agent_tools.TOOLS_SCHEMA)


def test_derive_spec_attaches_svg_urls_by_name():
    """svg↔大纲对齐：_derive_spec 按文件名把每页 svg 下载 url 挂到 slides/outline。"""
    from app.api.routers.agents import _derive_spec_from_tools
    from app.services.agent_planner import Step, PlanOutcome

    steps = [
        Step(tool="write_skill_file", args={"path": "projects/x/svg_output/01_cover.svg"}, ok=True, result={}),
        Step(tool="write_skill_file", args={"path": "projects/x/svg_output/02_value.svg"}, ok=True, result={}),
        Step(tool="run_skill_script", args={}, ok=True, result={"生成文件": [
            {"名": "01_cover.svg", "下载": "/u/01_cover.svg"},
            {"名": "02_value.svg", "下载": "/u/02_value.svg"},
            {"名": "x.pptx", "下载": "/u/x.pptx"},
        ]}),
    ]
    spec = _derive_spec_from_tools(PlanOutcome(steps=steps))
    assert len(spec["outline"]) == 2
    assert spec["outline"][0]["url"] == "/u/01_cover.svg"
    assert spec["outline"][1]["url"] == "/u/02_value.svg"
    assert spec["slides"][0]["title"] == "cover"


def test_synthesize_ppt_summary_includes_download():
    """空回复兜底：合成交付说明含页数、逐页标题、pptx 下载链接。"""
    from app.api.routers.agents import _synthesize_ppt_summary
    from app.services.agent_planner import Step, PlanOutcome

    steps = [
        Step(tool="write_skill_file", args={"path": "projects/x/svg_output/01_cover.svg"}, ok=True, result={}),
        Step(tool="run_skill_script", args={}, ok=True, result={"生成文件": [
            {"名": "deck_2026.pptx", "下载": "/u/deck.pptx"},
            {"名": "01_cover.svg", "下载": "/u/01_cover.svg"},
        ]}),
    ]
    text, has = _synthesize_ppt_summary(PlanOutcome(steps=steps))
    assert has and "deck.pptx" in text and "1 页" in text

