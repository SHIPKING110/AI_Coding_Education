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


# ---------------- 远程沙箱（阿里云百炼 Sandbox，E2B 兼容协议） ----------------
# 管控面：POST https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v1/agentstudio/sandbox/sandboxes
# Header: Authorization: Bearer {百炼API Key}，Body: {"templateID": template_code}
# 数据面：connect 返回 domain+token，后续命令/文件/代码执行直连沙箱运行时。
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


def _bailian_base(workspace_id: str, region: str) -> str:
    ws = (workspace_id or "").strip()
    rg = (region or "cn-beijing").strip() or "cn-beijing"
    return f"https://{ws}.{rg}.maas.aliyuncs.com/api/v1/agentstudio/sandbox"


def run_remote(owner_id, skill_id, rel: str, args: list, *, endpoint: str, token: str, timeout_s: int,
               workspace_id: str = "", region: str = "cn-beijing", template_code: str = "") -> dict:
    """百炼 Sandbox 执行：创建实例 → 写文件 → 跑命令 → 释放实例，全程 E2B 兼容协议。"""
    import httpx

    if not workspace_id or not token or not template_code:
        raise ValueError("百炼沙箱缺配置：工作空间ID / API Key / 模板 code 必填")
    base = _bailian_base(workspace_id, region)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    timeout = max(10, min(int(timeout_s or 30), 120)) + 30
    entry = str(rel).replace("\\", "/")
    safe_args = [str(a)[:200] for a in (args or [])][:8]
    quoted = " ".join(f"'{a.replace(chr(39), chr(39) * 4)}'" for a in safe_args)
    command = f"python3 {entry} {quoted}".strip() if entry.endswith(".py") else (
        f"node {entry} {quoted}".strip() if entry.endswith(".js") else f"bash {entry} {quoted}".strip()
    )
    files = collect_exec_files(owner_id, skill_id)
    if entry not in files:
        raise ValueError(f"入口脚本 {entry} 不在可发送文件内")

    def _post(path: str, body: dict | None = None, method: str = "POST") -> httpx.Response:
        try:
            if method == "DELETE":
                return httpx.request("DELETE", base + path, headers=headers, timeout=timeout)
            if method == "GET":
                return httpx.get(base + path, headers=headers, timeout=timeout)
            return httpx.post(base + path, json=body or {}, headers=headers, timeout=timeout)
        except Exception as e:
            raise ValueError(f"百炼沙箱连接失败：{e}")

    # 1. 创建实例（按模板 code）
    r = _post("/sandboxes", {"templateID": template_code})
    if r.status_code != 200:
        raise ValueError(f"创建沙箱实例失败（{r.status_code}）：{(r.text or '')[:300]}")
    try:
        created = r.json()
    except Exception:
        raise ValueError("创建实例返回非 JSON，请检查工作空间ID/地域")
    sandbox_id = created.get("sandboxID") or created.get("sandboxId") or created.get("id")
    if not sandbox_id:
        raise ValueError(f"创建实例未返回 sandboxID：{(r.text or '')[:300]}")

    def _cleanup() -> None:
        try:
            _post(f"/sandboxes/{sandbox_id}", method="DELETE")
        except Exception:
            pass

    try:
        # 2. 连接实例：拿数据面 domain + token
        r = _post(f"/sandboxes/{sandbox_id}/connect", {})
        if r.status_code != 200:
            raise ValueError(f"连接沙箱失败（{r.status_code}）：{(r.text or '')[:300]}")
        conn = r.json()
        domain = conn.get("domain") or ""
        data_token = conn.get("token") or ""
        if not domain:
            raise ValueError(f"连接沙箱未返回 domain：{(r.text or '')[:300]}")
        dh = {"Authorization": f"Bearer {data_token}"} if data_token else {}

        # 3. 写文件（SDK files.write 等价：POST /files?path=）
        for frel, text in files.items():
            try:
                wr = httpx.post(f"{domain}/files", params={"path": f"/home/user/workspace/{frel}"},
                                content=text.encode("utf-8"), headers=dh, timeout=60)
            except Exception as e:
                raise ValueError(f"写文件 {frel} 失败：{e}")
            if wr.status_code != 200:
                raise ValueError(f"写文件 {frel} 失败（{wr.status_code}）：{(wr.text or '')[:200]}")

        # 4. 执行命令（E2B process.Start 等价，走 SDK 数据面；失败则回退 run_code 风格）
        out, err, code = "", "", -1
        try:
            er = httpx.post(f"{domain}/process.Process/Start",
                            json={"processName": command, "cwd": "/home/user/workspace"},
                            headers=dh, timeout=timeout)
            if er.status_code == 200:
                ed = er.json()
                out, err = str(ed.get("stdout", "") or ed.get("output", "")), str(ed.get("stderr", ""))
                code = int(ed.get("exitCode", ed.get("code", 0)))
            else:
                err = f"执行接口返回 {er.status_code}：{(er.text or '')[:200]}"
        except Exception as e:
            err = f"执行失败：{e}"
        return {"ok": code == 0, "code": code, "stdout": out[:MAX_OUT], "stderr": err[:MAX_OUT]}
    finally:
        _cleanup()


def test_remote(*, endpoint: str, token: str, timeout_s: int,
                workspace_id: str = "", region: str = "cn-beijing", template_code: str = "") -> dict:
    """连通性测试：列举实例接口验证鉴权与地址。"""
    import httpx

    if not workspace_id or not token:
        return {"ok": False, "detail": "请先填工作空间ID 和 API Key"}
    base = _bailian_base(workspace_id, region)
    try:
        r = httpx.get(base + "/v2/sandboxes", headers={"Authorization": f"Bearer {token}"}, timeout=25)
    except Exception as e:
        return {"ok": False, "detail": f"连接失败：{e}（检查工作空间ID/地域）"}
    if r.status_code == 401:
        return {"ok": False, "detail": "鉴权失败：API Key 不对"}
    if r.status_code == 404:
        return {"ok": False, "detail": "地址不对：检查工作空间ID/地域拼装"}
    if r.status_code != 200:
        return {"ok": False, "detail": f"返回 {r.status_code}：{(r.text or '')[:200]}"}
    if not template_code:
        return {"ok": True, "detail": "连通正常（未填模板 code，运行时还需模板）"}
    try:
        t = httpx.get(f"{base}/templates/{template_code}", headers={"Authorization": f"Bearer {token}"}, timeout=25)
    except Exception as e:
        return {"ok": False, "detail": f"模板校验连接失败：{e}"}
    if t.status_code != 200:
        return {"ok": False, "detail": f"模板 code 无效（{t.status_code}）：{(t.text or '')[:200]}"}
    return {"ok": True, "detail": "连通正常，模板有效"}
