"""Skill 文件包：上传 zip（含 SKILL.md + 脚本/资源）→ 落盘隔离目录 → 解析引用。

安全设计（默认全部收紧）：
- 只允许解压 .md/.txt/.json/.yaml/.yml/.py/.js/.sh/.png/.jpg/.jpeg/.gif/.webp，
  其余一律跳过；zip 内拒绝绝对路径与 `..` 穿越；单文件 ≤2MB、解压总量 ≤10MB、文件数 ≤50。
- 脚本默认不执行：SKILL.md 与脚本内容只以文本形式注入上下文供 Agent 引用；
  如需执行，走受控子进程（见 skill_exec）：白名单 python3/node/bash、无网络、5s 超时、
  只读挂载技能目录、禁 env 透传，后续按需开放。
- 落盘目录：UPLOAD_DIR/skills/{owner_id}/{skill_id}/，删除 Skill 时连带清理。
"""

from __future__ import annotations

import io
import pathlib
import zipfile

ALLOWED_SUFFIX = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".js", ".sh",
                  ".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_FILES = 50
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024


def skill_dir(owner_id, skill_id) -> pathlib.Path:
    from app.core.config import get_settings

    base = pathlib.Path(get_settings().UPLOAD_DIR) / "skills" / str(owner_id) / str(skill_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_name(name: str) -> str | None:
    p = pathlib.PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts:
        return None
    if not p.suffix.lower() in ALLOWED_SUFFIX:
        return None
    clean = "/".join(x for x in p.parts if x not in ("", "."))
    return clean or None


def save_bundle(owner_id, skill_id, data: bytes) -> dict:
    """解压 zip 包并落盘，返回 {files: [...], skill_md: str}。非法包抛 ValueError。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        raise ValueError("不是有效的 zip 包")
    names = [i.filename for i in zf.infolist() if not i.is_dir()]
    if len(names) > MAX_FILES:
        raise ValueError(f"文件过多（>{MAX_FILES}），请精简")
    total = 0
    kept: list[tuple[str, bytes]] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        clean = _safe_name(info.filename)
        if clean is None:
            continue
        raw = zf.read(info.filename)
        if len(raw) > MAX_FILE_BYTES:
            continue
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("解压后总量超 10MB，请精简")
        kept.append((clean, raw))
    if not kept:
        raise ValueError("包内无可用文件（仅支持 md/txt/json/yaml/py/js/sh/图片）")
    dest = skill_dir(owner_id, skill_id)
    for clean, raw in kept:
        target = dest / clean
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    files = sorted(clean for clean, _ in kept)
    skill_md = ""
    for clean, raw in kept:
        if clean.lower().endswith("skill.md") or clean.lower() == "skill.md":
            try:
                skill_md = raw.decode("utf-8", errors="ignore")[:8000]
            except Exception:
                skill_md = ""
            break
    return {"files": files, "skill_md": skill_md}


def read_text_file(owner_id, skill_id, rel: str, limit: int = 6000) -> str:
    dest = skill_dir(owner_id, skill_id)
    target = (dest / rel).resolve()
    if dest.resolve() not in target.parents:
        raise ValueError("非法路径")
    if target.suffix.lower() not in ALLOWED_SUFFIX or target.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        raise ValueError("该类型不支持预览")
    return target.read_text(encoding="utf-8", errors="ignore")[:limit]


def skill_context_block(owner_id, skill_id, name: str, content: str, files: list) -> str:
    """拼注入块：手工指令 + SKILL.md 摘要 + 文件清单（含脚本清单供引用，不执行）。"""
    parts = [f"【Skill·{name}】"]
    if (content or "").strip():
        parts.append((content or "").strip()[:2000])
    dest = skill_dir(owner_id, skill_id)
    md_path = None
    for rel in files or []:
        if str(rel).lower().endswith("skill.md"):
            md_path = dest / str(rel)
            break
    if md_path is not None and md_path.exists():
        try:
            parts.append("SKILL.md 摘要：\n" + md_path.read_text(encoding="utf-8", errors="ignore")[:3000])
        except Exception:
            pass
    scripts = [f for f in (files or []) if str(f).lower().endswith((".py", ".js", ".sh"))]
    if scripts:
        parts.append("配套脚本（仅引用说明，不自动执行）：\n" + "\n".join(f"- {s}" for s in scripts[:20]))
    others = [f for f in (files or []) if f not in scripts and not str(f).lower().endswith("skill.md")]
    if others:
        parts.append("配套文件：\n" + "\n".join(f"- {s}" for s in others[:20]))
    return "\n".join(parts)[:5000]


def remove_bundle(owner_id, skill_id) -> None:
    import shutil

    dest = skill_dir(owner_id, skill_id)
    shutil.rmtree(dest, ignore_errors=True)
