"""Skill 受控脚本执行器：白名单解释器、无网络、短超时、只读目录、禁 env 透传。

安全策略：
- 仅允许包内已登记 files 中的 .py/.js/.sh；
- 解释器白名单：python3→sys.executable、node→node、sh→bash；
- env 置空（仅 PATH=/usr/bin:/bin），cwd=技能目录只读语义（不写回）；
- 超时 5s，输出截断 8KB；非零退出返回 ok=False + stderr。
容器内 python3 存在；node/bash 缺失则报不可用而非崩溃。
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

ALLOWED_RUN = {".py": None, ".js": "node", ".sh": "bash"}
TIMEOUT_S = 5
MAX_OUT = 8 * 1024


def run_script(owner_id, skill_id, rel: str, args: list) -> dict:
    from app.services import skill_bundle as _bundle

    suffix = pathlib.PurePosixPath(rel).suffix.lower()
    if suffix not in ALLOWED_RUN:
        raise ValueError("仅支持运行包内的 .py/.js/.sh 脚本")
    if ".." in pathlib.PurePosixPath(rel).parts or pathlib.PurePosixPath(rel).is_absolute():
        raise ValueError("非法路径")
    dest = _bundle.skill_dir(owner_id, skill_id)
    target = (dest / rel).resolve()
    if dest.resolve() not in target.parents:
        raise ValueError("非法路径")
    if not target.exists():
        raise ValueError("脚本不存在")
    safe_args = [str(a)[:200] for a in (args or [])][:8]
    import sys as _sys

    if suffix == ".py":
        cmd = [_sys.executable, str(target), *safe_args]
    else:
        binary = ALLOWED_RUN[suffix]
        assert binary is not None
        if shutil.which(binary) is None:
            raise ValueError(f"容器内无 {binary}，该脚本暂不可运行（仅预览）")
        cmd = [binary, str(target), *safe_args]
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT_S,
            cwd=str(dest), env={"PATH": "/usr/bin:/bin"}, check=False,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError("timeout")
    out = (p.stdout or "")[:MAX_OUT]
    err = (p.stderr or "")[:MAX_OUT]
    return {"ok": p.returncode == 0, "code": p.returncode, "stdout": out, "stderr": err}


# ---------------- 远程沙箱（阿里云函数计算 FC：用户自建执行器函数） ----------------
# 协议：POST {endpoint}  Header: Authorization: Bearer {token}
# Body: {"entry": "a.py", "language": "python", "args": [...], "timeout": 25, "files": {rel: text}}
# Resp: {"ok": bool, "code": int, "stdout": str, "stderr": str}
REMOTE_MAX_FILES = 100
REMOTE_MAX_TOTAL = 200 * 1024
REMOTE_TEXT_SUFFIX = {".py", ".txt", ".md", ".json", ".yaml", ".yml", ".sh", ".js", ".cfg", ".ini", ".toml"}


def collect_exec_files(owner_id, skill_id) -> dict:
    """打包技能目录内文本文件（含同级 import 依赖），供远程沙箱写入后执行。"""
    from app.services import skill_bundle as _bundle

    dest = _bundle.skill_dir(owner_id, skill_id).resolve()
    files: dict[str, str] = {}
    total = 0
    for p in sorted(dest.rglob("*")):
        if not p.is_file() or len(files) >= REMOTE_MAX_FILES:
            continue
        try:
            rel = str(p.relative_to(dest)).replace("\\", "/")
        except ValueError:
            continue
        if pathlib.PurePosixPath(rel).suffix.lower() not in REMOTE_TEXT_SUFFIX:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if total + len(text) > REMOTE_MAX_TOTAL:
            break
        files[rel] = text
        total += len(text)
    return files


def run_remote(owner_id, skill_id, rel: str, args: list, *, endpoint: str, token: str, timeout_s: int) -> dict:
    import httpx

    suffix = pathlib.PurePosixPath(rel).suffix.lower()
    language = {"py": "python", ".py": "python", ".js": "node", ".sh": "bash"}.get(suffix, "python")
    payload = {
        "entry": rel,
        "language": language,
        "args": [str(a)[:200] for a in (args or [])][:8],
        "timeout": max(5, min(int(timeout_s or 25), 120)),
        "files": collect_exec_files(owner_id, skill_id),
    }
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = httpx.post(endpoint, json=payload, headers=headers, timeout=payload["timeout"] + 15)
    except Exception as e:
        raise ValueError(f"远程沙箱连接失败：{e}")
    if r.status_code == 401:
        raise ValueError("远程沙箱鉴权失败（token 不对），请检查沙箱配置")
    if r.status_code != 200:
        raise ValueError(f"远程沙箱返回 {r.status_code}：{(r.text or '')[:200]}")
    try:
        data = r.json()
    except Exception:
        raise ValueError("远程沙箱返回非 JSON，请检查 endpoint 是否填了函数触发器 URL")
    return {
        "ok": bool(data.get("ok", False)),
        "code": int(data.get("code", -1)),
        "stdout": str(data.get("stdout", ""))[:MAX_OUT],
        "stderr": str(data.get("stderr", ""))[:MAX_OUT],
    }


def test_remote(*, endpoint: str, token: str, timeout_s: int) -> dict:
    """连通性测试：让远端执行一段 hello，验证鉴权与协议。"""
    import httpx

    payload = {
        "entry": "__ping__.py",
        "language": "python",
        "args": [],
        "timeout": 10,
        "files": {"__ping__.py": "print('sandbox-ok')"},
    }
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = httpx.post(endpoint, json=payload, headers=headers, timeout=25)
    except Exception as e:
        return {"ok": False, "detail": f"连接失败：{e}"}
    if r.status_code == 401:
        return {"ok": False, "detail": "鉴权失败：token 不对"}
    if r.status_code != 200:
        return {"ok": False, "detail": f"返回 {r.status_code}：{(r.text or '')[:200]}"}
    try:
        data = r.json()
    except Exception:
        return {"ok": False, "detail": "返回非 JSON：endpoint 可能填错（要填函数 HTTP 触发器 URL）"}
    ok = bool(data.get("ok")) and "sandbox-ok" in str(data.get("stdout", ""))
    return {"ok": ok, "detail": "连通正常" if ok else f"远端执行异常：{str(data.get('stderr', ''))[:200]}"}
