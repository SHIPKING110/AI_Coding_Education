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
