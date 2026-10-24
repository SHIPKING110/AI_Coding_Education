"""Skill 文件包：上传 zip（含 SKILL.md + 脚本/资源）→ 落盘隔离目录 → 解析引用。

安全设计（默认全部收紧）：
- 只允许解压 .md/.txt/.json/.yaml/.yml/.py/.js/.sh/.png/.jpg/.jpeg/.gif/.webp，
  其余一律跳过；zip 内拒绝绝对路径与 `..` 穿越；单文件 ≤10MB、解压总量 ≤80MB、文件数 ≤200。
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
# 无后缀的常见署名/说明文件也允许落盘（很多第三方 Skill 自带完整性校验，缺失会报 attribution 缺失）
ALLOWED_BASENAMES = {"license", "licence", "notice", "authors", "copying", "attribution", "readme", "changelog"}
MAX_FILES = 2000
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 80 * 1024 * 1024
# 整包导入时直接跳过的噪音目录（依赖产物/版本库/构建输出，Agent 引用无意义）
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv", ".next", "coverage"}


def parse_skill_md(text: str) -> dict:
    """解析 SKILL.md：YAML frontmatter(name/description) + 正文。

    返回 {"name": str, "description": str, "body": str}。
    无 frontmatter 时 name/description 为空，body 为原文。
    """
    name, description, body = "", "", (text or "")
    lines = (text or "").splitlines()
    if lines and lines[0].strip() == "---":
        end = next((idx for idx in range(1, len(lines)) if lines[idx].strip() in ("---", "...")), None)
        if end is not None:
            fm = lines[1:end]
            body = "\n".join(lines[end + 1 :]).strip()
            data: dict[str, str] = {}
            cur_key: str | None = None
            for ln in fm:
                if not ln.strip() or ln.strip().startswith("#"):
                    continue
                m = ln.split(":", 1)
                if len(m) == 2 and not ln.startswith((" ", "\t")) and m[0].strip().lower() in ("name", "description"):
                    cur_key = m[0].strip().lower()
                    data[cur_key] = m[1].strip().lstrip(">").strip().strip("\"'")
                elif cur_key and ln.startswith((" ", "\t")):
                    data[cur_key] = (data[cur_key] + " " + ln.strip()).strip()
            name = data.get("name", "")
            description = data.get("description", "")
    if not name:
        first = next((ln.strip("# ").strip() for ln in body.splitlines() if ln.strip()), "")
        name = first[:64]
    return {"name": name, "description": description[:256], "body": body[:8000]}


def skill_dir(owner_id, skill_id) -> pathlib.Path:
    from app.core.config import get_settings

    base = pathlib.Path(get_settings().UPLOAD_DIR) / "skills" / str(owner_id) / str(skill_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def cleanup_conversation(owner_id, conv_id, output_urls=None) -> int:
    """删除一个会话时，清理它在各 Skill 下的会话隔离工作区 + 关联产物。

    - 会话隔离目录：每个 skill 下 conversations/conv_<cid12>/ 整目录删除；
    - 产物文件：调用方传入该会话消息里出现过的产物下载 url（/uploads/skills/<o>/<s>/_outputs/<run>/<f>），
      解析出 <skill>/<run> 目录后整目录删除（一次运行一个目录，删该会话自己的产物，不误删他人的）。
    返回删除的顶层路径数。尽力而为，任何异常静默跳过。
    """
    import re as _re
    import shutil as _sh

    removed = 0
    conv_key = "conv_" + str(conv_id).replace("-", "")[:12]
    try:
        base = pathlib.Path(get_settings_dir())
        skills_root = base / "skills" / str(owner_id)
        if skills_root.is_dir():
            for sdir in skills_root.iterdir():
                if not sdir.is_dir():
                    continue
                cd = sdir / "conversations" / conv_key
                if cd.is_dir():
                    _sh.rmtree(cd, ignore_errors=True)
                    removed += 1
                # 兜底：conversations 下可能因不同短 id 截断产生相近目录，按前缀再清一次
            convroot = None
            # 清理 _outputs：按传入 url 精确到 <run> 目录
            for url in output_urls or []:
                m = _re.search(r"/uploads/skills/([^/]+)/([^/]+)/_outputs/([^/]+)/", str(url))
                if not m:
                    continue
                o_id, s_id, run = m.group(1), m.group(2), m.group(3)
                if str(o_id) != str(owner_id):
                    continue
                run_dir = skills_root / s_id / "_outputs" / run
                if run_dir.is_dir():
                    _sh.rmtree(run_dir, ignore_errors=True)
                    removed += 1
    except Exception:
        pass
    return removed


def get_settings_dir() -> str:
    from app.core.config import get_settings

    return get_settings().UPLOAD_DIR


def _safe_name(name: str) -> str | None:
    p = pathlib.PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts:
        return None
    base = p.name.lower()
    allowed = p.suffix.lower() in ALLOWED_SUFFIX or base in ALLOWED_BASENAMES or any(
        base.startswith(prefix) for prefix in ("license", "licence", "notice", "attribution")
    )
    if not allowed:
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
    # 先过滤噪音目录 + 非白名单后缀再计数：只有真正会落盘的文件才占名额
    # （node_modules/.git/dist 等跳过；二进制/锁文件等后缀不计入）
    def _countable(n: str) -> bool:
        norm = n.replace("\\", "/")
        if any(f"/{d}/" in f"/{norm}/" for d in SKIP_DIRS):
            return False
        return _safe_name(n) is not None
    countable = [n for n in names if _countable(n)]
    if len(countable) > MAX_FILES:
        raise ValueError(f"文件过多（>{MAX_FILES}，已自动跳过 node_modules/.git/dist 等噪音目录与非文本文件），请精简")
    total = 0
    kept: list[tuple[str, bytes]] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        norm = info.filename.replace("\\", "/")
        if any(f"/{d}/" in f"/{norm}/" for d in SKIP_DIRS):
            continue
        clean = _safe_name(info.filename)
        if clean is None:
            continue
        raw = zf.read(info.filename)
        if len(raw) > MAX_FILE_BYTES:
            continue
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("解压后总量超 80MB，请精简")
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
    if target.suffix.lower() not in ALLOWED_SUFFIX and target.name.lower() not in ALLOWED_BASENAMES:
        if target.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            raise ValueError("图片类型不支持预览")
        raise ValueError("该类型不支持预览")
    return target.read_text(encoding="utf-8", errors="ignore")[:limit]


def skill_context_block(owner_id, skill_id, name: str, content: str, files: list) -> str:
    """拼注入块：手工指令 + SKILL.md 摘要 + 文件清单（含脚本清单，对话中可通过 run_skill_script 工具实际执行）。"""
    dest = skill_dir(owner_id, skill_id)
    root = str(dest.resolve())

    def _fill(text: str) -> str:
        # Skill 文档里常引用 ${SKILL_DIR}：替换为真实绝对路径，模型不再报“未提供路径”
        return (text or "").replace("${SKILL_DIR}", root).replace("$SKILL_DIR", root)

    parts = [f"【Skill·{name}】", f"Skill 文件根目录：{root}"]
    if (content or "").strip():
        parts.append(_fill((content or "").strip())[:2000])
    md_path = None
    for rel in files or []:
        if str(rel).lower().endswith("skill.md"):
            md_path = dest / str(rel)
            break
    if md_path is not None and md_path.exists():
        try:
            parts.append("SKILL.md 摘要：\n" + _fill(md_path.read_text(encoding="utf-8", errors="ignore"))[:3000])
        except Exception:
            pass
    # 专业结构分组：SKILL.md(已在摘要中) / scripts 可执行脚本 / references 参考资料 / assets 资源文件
    lowers = [(f, str(f).lower()) for f in (files or [])]
    scripts = [f for f, l in lowers if l.endswith((".py", ".js", ".sh")) and not l.endswith("skill.md")]
    if scripts:
        parts.append("可执行脚本 scripts/（对话中可用 run_skill_script 工具实际执行：传 skill 名 + 脚本路径 + 参数；"
                     "生成的文件会自动取回并给出下载链接，不要只描述不执行）：\n" + "\n".join(f"- {s}" for s in scripts[:20]))
    refs = [f for f, l in lowers if ("/references/" in f"/{l}" or l.endswith((".md", ".txt"))) and not l.endswith("skill.md") and f not in scripts]
    if refs:
        parts.append("参考资料 references/：\n" + "\n".join(f"- {s}" for s in refs[:20]))
    assets = [f for f, _ in lowers if f not in scripts and f not in refs and not str(f).lower().endswith("skill.md")]
    if assets:
        parts.append("资源文件 assets/：\n" + "\n".join(f"- {s}" for s in assets[:20]))
    return "\n".join(parts)[:5000]


def remove_bundle(owner_id, skill_id) -> None:
    import shutil

    dest = skill_dir(owner_id, skill_id)
    shutil.rmtree(dest, ignore_errors=True)


# ---------------------------------------------------------------------------
# 收录物化：把「作者目录」里的 Skill 文件包复制到「使用者目录」
# ---------------------------------------------------------------------------

_MARKER = ".materialized.json"


def _read_marker(dest: pathlib.Path) -> dict:
    try:
        import json

        return json.loads((dest / _MARKER).read_text(encoding="utf-8"))
    except Exception:
        return {}


def materialize_bundle(src_owner_id, src_skill_id, dst_owner_id, dst_skill_id) -> dict:
    """把 Skill 文件包从作者目录复制到使用者目录（收录/首次使用）。

    为什么必须物化：Skill 包按「作者 owner_id/skill_id」落盘在**作者目录**，收录者目录里
    并没有这份文件。若按收录者 id 定位目录，执行必然找不到脚本——表现就是
    「收录后看得见 Skill、也能出计划，但一执行就失败、产不出 PPT」。
    物化后，执行/写文件/取产物都在使用者自己的目录里完成：
    - 发布者与所有收录者行为一致（同一个 skill，任何人效果相同）；
    - 使用者写入的中间产物（如手写 SVG 源文件）不会污染作者目录；
    - 产物下载链接按使用者维度隔离。

    返回 {"materialized": bool, "synced": bool}。
    """
    import json
    import shutil

    if str(src_owner_id) == str(dst_owner_id) and str(src_skill_id) == str(dst_skill_id):
        return {"materialized": False, "synced": False}
    src = skill_dir(src_owner_id, src_skill_id)
    dst = skill_dir(dst_owner_id, dst_skill_id)
    marker = _read_marker(dst)
    src_files = sorted(
        str(p.relative_to(src)).replace("\\", "/")
        for p in src.rglob("*")
        if p.is_file() and not str(p.relative_to(src)).startswith(_MARKER)
    )
    # 已物化且来源未变 → 跳过（避免每次调用都全量复制）
    if marker.get("src") == f"{src_owner_id}/{src_skill_id}" and marker.get("files") == src_files:
        return {"materialized": True, "synced": False}
    # 清掉历史物化内容后重建（作者更新了包：以作者为准整体刷新）
    for child in dst.iterdir():
        if child.name == _MARKER:
            continue
        try:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        except OSError:
            pass
    copied = 0
    for rel in src_files:
        s = src / rel
        t = dst / rel
        try:
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(s, t)
            copied += 1
        except OSError:
            continue
    try:
        (dst / _MARKER).write_text(
            json.dumps({"src": f"{src_owner_id}/{src_skill_id}", "files": src_files}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    return {"materialized": True, "synced": True, "copied": copied}


def is_materialized(dst_owner_id, dst_skill_id) -> bool:
    """使用者目录里是否已有物化副本。"""
    try:
        dest = skill_dir(dst_owner_id, dst_skill_id)
        marker = _read_marker(dest)
        if marker.get("src"):
            return True
        # 兼容早期：无 marker 但目录内有实际文件 → 视为已就位
        return any(p.is_file() and p.name != _MARKER for p in dest.rglob("*"))
    except Exception:
        return False
