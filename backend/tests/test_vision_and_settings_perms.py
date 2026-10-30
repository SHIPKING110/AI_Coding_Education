# -*- coding: utf-8 -*-
"""视觉输入 + 设置权限对齐 回归测试：

1) `llm.stream_text` 收到图片时构造 OpenAI 兼容多模态内容块（image_url / data URL），
   让 deepseek-flash 等视觉模型能真正读取用户上传的图片；
2) 随消息附件 → data URL 的转换只收视觉模型支持的格式、跳过文档与超限项；
3) Embedding / 联网搜索配置接口与「设置-模型配置」权限（settings_tab_model）对齐，
   教师被授予该权限后与管理员看到并操作同样的配置项。
"""

import base64
import re
from pathlib import Path

from app.services import llm as llm_mod

ROOT = Path(__file__).resolve().parents[1]


def test_stream_text_includes_image_blocks(monkeypatch):
    captured = {}

    class FakeChunk:
        content = "OK"

    class FakeModel:
        def stream(self, messages):
            captured["messages"] = messages
            yield FakeChunk()

    monkeypatch.setattr(llm_mod, "_require_any_llm", lambda msg: None)
    monkeypatch.setattr(llm_mod, "_chat_model", lambda: FakeModel())

    data_url = "data:image/png;base64,AAAA"
    out = "".join(llm_mod.stream_text("系统提示", "这张图里有什么？", images=[data_url]))
    assert out == "OK"
    human = captured["messages"][-1]
    assert isinstance(human.content, list)
    assert human.content[0] == {"type": "text", "text": "这张图里有什么？"}
    assert {"type": "image_url", "image_url": {"url": data_url}} in human.content


def test_stream_text_text_only_keeps_plain_content(monkeypatch):
    captured = {}

    class FakeChunk:
        content = "hi"

    class FakeModel:
        def stream(self, messages):
            captured["messages"] = messages
            yield FakeChunk()

    monkeypatch.setattr(llm_mod, "_require_any_llm", lambda msg: None)
    monkeypatch.setattr(llm_mod, "_chat_model", lambda: FakeModel())

    "".join(llm_mod.stream_text("sys", "纯文本消息"))
    assert captured["messages"][-1].content == "纯文本消息"


def _load_image_helper():
    """从 agents 路由里提取 _image_data_urls（避免整包导入的重依赖）。"""
    src = (ROOT / "app/api/routers/agents.py").read_text(encoding="utf-8")
    mime = re.search(r"_VISION_MIME\s*=\s*\{.*?\n\}", src, re.S)
    fn = re.search(r"def _image_data_urls.*?(?=\ndef _looks_like_vision_rejection)", src, re.S)
    ns = {"Path": Path}
    exec(mime.group(0), ns)
    exec(fn.group(0), ns)
    return ns["_image_data_urls"], ns


def test_image_data_urls_reads_png_skips_doc_and_svg(tmp_path, monkeypatch):
    upload = tmp_path / "uploads"
    d = upload / "chat" / "conv1"
    d.mkdir(parents=True)
    raw = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    (d / "a.png").write_bytes(raw)
    (d / "b.svg").write_text("<svg/>", encoding="utf-8")
    (d / "c.docx").write_bytes(b"PK")

    import app.core.config as core_config

    class S:
        UPLOAD_DIR = str(upload)

    monkeypatch.setattr(core_config, "get_settings", lambda: S)

    fn, _ns = _load_image_helper()
    urls = fn(
        [
            {"kind": "image", "url": "/uploads/chat/conv1/a.png"},
            {"kind": "doc", "url": "/uploads/chat/conv1/c.docx", "text": "x"},
            {"kind": "image", "url": "/uploads/chat/conv1/b.svg"},
            {"kind": "image", "url": "/uploads/chat/conv1/missing.png"},
        ]
    )
    assert len(urls) == 1
    assert urls[0] == "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def test_settings_config_routers_use_model_tab_permission():
    """Embedding / 联网搜索接口改用 settings_tab_model 权限依赖（教师与管理员配置项同步）。"""
    for name in ("search_configs.py", "retrieval_configs.py"):
        src = (ROOT / "app/api/routers" / name).read_text(encoding="utf-8")
        assert 'require_teacher_permission("settings_tab_model")' in src
        assert "require_roles(*ADMIN_ROLES)" not in src
