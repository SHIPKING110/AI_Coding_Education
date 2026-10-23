"""Skill 受控脚本执行器：白名单解释器、长任务超时、工作目录隔离、产物自动回收。

安全策略：
- 仅允许包内已登记 files 中的 .py/.js/.sh；
- 解释器白名单：python3→sys.executable、node→node、sh→bash；
- env 最小透传（PATH 含 venv bin、HOME、LANG、PYTHONPATH），不透传业务密钥；
- cwd=技能目录；超时可配（默认 300s）；输出截断 64KB；
- 运行后快照新增文件，回收为本 Skill 的可下载产物。

容器内 python3 存在；node/bash 缺失则报不可用而非崩溃。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

ALLOWED_RUN = {".py": None, ".js": "node", ".sh": "bash"}
TIMEOUT_S = 300
MAX_OUT = 64 * 1024
LOCAL_FETCH_MAX_FILES = 8
LOCAL_FETCH_MAX_BYTES = 32 * 1024 * 1024


def _local_env() -> dict:
    """最小环境：保留解释器/字体/编码所需，去业务密钥。PATH 前置 venv bin 与 node。"""
    import sys as _sys

    venv_bin = str(pathlib.Path(_sys.executable).parent)
    parts = [venv_bin, "/usr/local/bin", "/usr/bin", "/bin"]
    path = os.pathsep.join(dict.fromkeys(p for p in parts if p))
    return {
        "PATH": path,
        "HOME": os.environ.get("HOME", "/root"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }


def _snapshot(root: pathlib.Path) -> dict:
    snap: dict[str, float] = {}
    for p in root.rglob("*"):
        try:
            if p.is_file():
                snap[str(p.relative_to(root)).replace("\\", "/")] = p.stat().st_mtime
        except OSError:
            continue
    return snap


def _collect_outputs(owner_id, skill_id, dest: pathlib.Path, before: dict) -> list:
    """回收运行期间新增/改动的文件，落盘 uploads/skills/<owner>/<skill>/_outputs/ 并给下载 URL。

    按产物价值排序：成品文档（pptx/pdf/docx/xlsx）优先，避免配额被中间报告占满。
    """
    prio_suffix = {".pptx": 0, ".pdf": 1, ".docx": 2, ".xlsx": 3, ".png": 4, ".jpg": 4, ".jpeg": 4}
    new_files: list[tuple[int, str, pathlib.Path]] = []
    for p in sorted(dest.rglob("*")):
        if not p.is_file():
            continue
        try:
            rel = str(p.relative_to(dest)).replace("\\", "/")
        except ValueError:
            continue
        if rel.startswith("_outputs/") or "__pycache__" in rel.split("/"):
            continue
        try:
            mtime = p.stat().st_mtime
            size = p.stat().st_size
        except OSError:
            continue
        if before.get(rel) == mtime:
            continue  # 未变动（含所有原始包文件与本次预先写入的源文件）
        if ".." in pathlib.PurePosixPath(rel).parts or p.suffix.lower() == ".pyc":
            continue
        if size <= 0 or size > LOCAL_FETCH_MAX_BYTES:
            continue
        new_files.append((prio_suffix.get(p.suffix.lower(), 9), rel, p))
    new_files.sort(key=lambda x: (x[0], x[1]))
    produced: list = []
    # 按运行时间戳分目录，保证每次运行的下载链接只指向「本次」产物，绝不覆盖/串到历史运行
    import time as _time

    run_id = _time.strftime("%Y%m%d_%H%M%S")
    out_dir = dest / "_outputs" / run_id
    for _, rel, p in new_files[:LOCAL_FETCH_MAX_FILES]:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            safe = p.name[:80] or "output.bin"
            shutil.copyfile(p, out_dir / safe)
        except OSError:
            continue
        produced.append({
            "name": safe,
            "url": f"/uploads/skills/{owner_id}/{skill_id}/_outputs/{run_id}/{safe}",
            "bytes": p.stat().st_size,
        })
    return produced


def run_script(owner_id, skill_id, rel: str, args: list, timeout_s: int | None = None) -> dict:
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
    limit = max(10, min(int(timeout_s or TIMEOUT_S), 1800))
    before = _snapshot(dest)
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=limit,
            cwd=str(dest), env=_local_env(), check=False,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"执行超时（{limit}s），已终止")
    out = (p.stdout or "")[:MAX_OUT]
    err = (p.stderr or "")[:MAX_OUT]
    produced = _collect_outputs(owner_id, skill_id, dest, before)
    phases = [f"① 本地执行 {cmd[0].rsplit('/', 1)[-1]} {rel} {(' '.join(safe_args)).strip()}".rstrip()]
    if produced:
        phases.append("② 回收产物 " + "、".join(f["name"] for f in produced))
    return {"ok": p.returncode == 0, "code": p.returncode, "stdout": out, "stderr": err,
            "files": produced, "phases": phases}


# ---------------- 远程沙箱（阿里云百炼 Sandbox，E2B 兼容协议） ----------------
# 管控面：POST https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v1/agentstudio/sandbox/sandboxes
# Header: Authorization: Bearer {百炼API Key}，Body: {"templateID": template_code}
# 数据面：connect 返回 domain+token，后续命令/文件/代码执行直连沙箱运行时。
REMOTE_MAX_FILES = 300
REMOTE_MAX_TOTAL = 1024 * 1024
REMOTE_TEXT_SUFFIX = {".py", ".txt", ".md", ".json", ".yaml", ".yml", ".sh", ".js", ".cfg", ".ini", ".toml"}


def collect_exec_files(owner_id, skill_id) -> dict:
    """打包技能目录内文本文件（含同级 import 依赖），供远程沙箱写入后执行。

    优先级收录：入口/SKILL.md/requirements/scripts 先行，保证配额内关键文件不被海量参考资料挤掉。
    """
    from app.services import skill_bundle as _bundle

    dest = _bundle.skill_dir(owner_id, skill_id).resolve()

    def _priority(rel: str) -> tuple[int, str]:
        low = rel.lower()
        base = low.rsplit("/", 1)[-1]
        if base == "skill.md" or base.startswith("requirements"):
            return (0, rel)
        if base in ("attribution_guard.py",) or low.endswith("/attribution_guard.py"):
            return (1, rel)
        if "/scripts/" in low and low.endswith((".py", ".js", ".sh")):
            return (2, rel)
        if low.endswith((".py", ".js", ".sh")):
            return (3, rel)
        return (4, rel)

    cands: list[str] = []
    for p in sorted(dest.rglob("*")):
        if not p.is_file():
            continue
        try:
            rel = str(p.relative_to(dest)).replace("\\", "/")
        except ValueError:
            continue
        if pathlib.PurePosixPath(rel).suffix.lower() not in REMOTE_TEXT_SUFFIX:
            continue
        cands.append(rel)
    cands.sort(key=_priority)
    files: dict[str, str] = {}
    total = 0
    for rel in cands:
        if len(files) >= REMOTE_MAX_FILES:
            break
        try:
            text = (dest / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if total + len(text) > REMOTE_MAX_TOTAL:
            continue
        files[rel] = text
        total += len(text)
    return files


def _bailian_base(workspace_id: str, region: str) -> str:
    ws = (workspace_id or "").strip()
    rg = (region or "cn-beijing").strip() or "cn-beijing"
    return f"https://{ws}.{rg}.maas.aliyuncs.com/api/v1/agentstudio/sandbox"


FETCH_MAX_FILES = 5
FETCH_MAX_BYTES = 8 * 1024 * 1024


def _fetch_outputs(sent_keys, run_fn, fetch_fn, skill_id) -> list:
    """取回沙箱中新生成的产物文件（如 .pptx），落盘 uploads/skills/<skill_id>/，返回 [{name, url, bytes}]。"""
    try:
        code, out, _ = run_fn("find /home/user/workspace -type f | sort", 30)
    except Exception:
        return []
    if code != 0:
        return []
    sent = set(sent_keys or [])
    produced = []
    for line in (out or "").splitlines():
        rel = line.strip()
        if rel.startswith("/home/user/workspace/"):
            rel = rel[len("/home/user/workspace/"):]
        rel = rel.strip()
        if not rel or rel in sent or "__pycache__" in rel.split("/"):
            continue
        if len(produced) >= FETCH_MAX_FILES:
            break
        try:
            data = fetch_fn(f"/home/user/workspace/{rel}")
        except Exception:
            continue
        if not data or len(data) > FETCH_MAX_BYTES:
            continue
        safe = pathlib.PurePosixPath(rel).name[:80] or "output.bin"
        dest_dir = pathlib.Path("uploads") / "skills" / str(skill_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / safe).write_bytes(data)
        produced.append({"name": safe, "url": f"/uploads/skills/{skill_id}/{safe}", "bytes": len(data)})
    return produced


def run_remote(owner_id, skill_id, rel: str, args: list, *, endpoint: str, token: str, timeout_s: int,
               workspace_id: str = "", region: str = "cn-beijing", template_code: str = "") -> dict:
    """百炼 Sandbox 执行：创建实例 → 写文件 →（有 requirements.txt 则先 pip 安装依赖）→ 跑命令 → 释放实例。"""
    import httpx

    if not workspace_id or not token or not template_code:
        raise ValueError("百炼沙箱缺配置：工作空间ID / API Key / 模板 code 必填")
    base = _bailian_base(workspace_id, region)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    step_timeout = max(10, min(int(timeout_s or 30), 120))
    timeout = step_timeout + 60
    entry = str(rel).replace("\\", "/")
    safe_args = [str(a)[:200] for a in (args or [])][:8]
    quoted = " ".join(f"'{a.replace(chr(39), chr(39) * 4)}'" for a in safe_args)
    command = f"python3 {entry} {quoted}".strip() if entry.endswith(".py") else (
        f"node {entry} {quoted}".strip() if entry.endswith(".js") else f"bash {entry} {quoted}".strip()
    )
    files = collect_exec_files(owner_id, skill_id)
    if entry not in files:
        base = entry.rsplit("/", 1)[-1].lower()
        same = [f for f in files if f.rsplit("/", 1)[-1].lower() == base][:3]
        hint = f"（可发送的同名文件：{'、'.join(same)}）" if same else "（注意用包内完整相对路径，参考 Skill 清单里的脚本路径）"
        raise ValueError(f"入口脚本 {entry} 不在可发送文件内{hint}")
    # 约定：包内 requirements*.txt 即依赖清单，运行时自动 pip 安装（后续 Skill 同理，无需额外配置）
    req_files = sorted(
        frel for frel in files
        if frel.rsplit("/", 1)[-1].lower().startswith("requirements") and frel.lower().endswith(".txt")
    )

    def _post(path: str, body: dict | None = None, method: str = "POST") -> httpx.Response:
        try:
            if method == "DELETE":
                return httpx.request("DELETE", base + path, headers=headers, timeout=timeout)
            if method == "GET":
                return httpx.get(base + path, headers=headers, timeout=timeout)
            return httpx.post(base + path, json=body or {}, headers=headers, timeout=timeout)
        except Exception as e:
            raise ValueError(f"百炼沙箱连接失败：{e}")

    # 1. 创建实例（按模板 code；E2B 协议成功返回 201，响应里直接带数据面地址与 token）
    r = _post("/sandboxes", {"templateID": template_code})
    if r.status_code not in (200, 201):
        raise ValueError(f"创建沙箱实例失败（{r.status_code}）：{(r.text or '')[:300]}")
    try:
        created = r.json()
    except Exception:
        raise ValueError("创建实例返回非 JSON，请检查工作空间ID/地域")
    if not isinstance(created, dict):
        raise ValueError(f"创建实例返回异常：{(r.text or '')[:300]}")
    nested = created.get("sandbox") if isinstance(created.get("sandbox"), dict) else {}
    sandbox_id = (
        created.get("sandboxID") or created.get("sandboxId") or created.get("id")
        or created.get("bailianSandboxId") or nested.get("sandboxID")
        or nested.get("sandboxId") or nested.get("id")
    )
    if not sandbox_id:
        raise ValueError(f"创建实例未返回 sandboxID：{(r.text or '')[:300]}")

    def _cleanup() -> None:
        try:
            _post(f"/sandboxes/{sandbox_id}", method="DELETE")
        except Exception:
            pass

    try:
        # 2. 连接实例：创建响应若已带 envdUrl + envdAccessToken，直接用，省一次往返；
        # 否则走 /connect（成功可能是 200/201）
        domain = (created.get("envdUrl") or "").rstrip("/")
        data_token = created.get("envdAccessToken") or ""
        if not domain:
            r = _post(f"/sandboxes/{sandbox_id}/connect", {})
            if r.status_code not in (200, 201):
                raise ValueError(f"连接沙箱失败（{r.status_code}）：{(r.text or '')[:300]}")
            conn = r.json()
            domain = (conn.get("domain") or conn.get("envdUrl") or "").rstrip("/")
            data_token = conn.get("token") or conn.get("envdAccessToken") or ""
        if not domain:
            raise ValueError(f"连接沙箱未返回 domain：{(r.text or '')[:300]}")
        # E2B 数据面（envd）鉴权头是 X-Access-Token，不是 Authorization
        dh = {"X-Access-Token": data_token} if data_token else {}

        # 3. 写文件（SDK files.write 等价：POST /files?path=）
        for frel, text in files.items():
            try:
                wr = httpx.post(f"{domain}/files", params={"path": f"/home/user/workspace/{frel}"},
                                content=text.encode("utf-8"), headers=dh, timeout=60)
            except Exception as e:
                raise ValueError(f"写文件 {frel} 失败：{e}")
            if wr.status_code not in (200, 201):
                raise ValueError(f"写文件 {frel} 失败（{wr.status_code}）：{(wr.text or '')[:200]}")

        # 4. （可选）先装依赖，再执行入口；封装为同一数据面调用
        def _data_exec(cmd: str, limit: int) -> tuple[int, str, str]:
            try:
                er = httpx.post(f"{domain}/process.Process/Start",
                                json={"processName": cmd, "cwd": "/home/user/workspace"},
                                headers=dh, timeout=limit)
            except Exception as e:
                return -1, "", f"执行失败：{e}"
            if er.status_code not in (200, 201):
                return -1, "", f"执行接口返回 {er.status_code}：{(er.text or '')[:200]}"
            try:
                ed = er.json()
            except Exception:
                return -1, "", f"执行返回非 JSON：{(er.text or '')[:200]}"
            return (
                int(ed.get("exitCode", ed.get("code", 0))),
                str(ed.get("stdout", "") or ed.get("output", "")),
                str(ed.get("stderr", "")),
            )

        phases = [f"① 建实例 sandboxID={sandbox_id}"]
        deps_note = ""
        deps_log = ""
        if req_files:
            # 用国内镜像源加速；模板需在网络白名单放行 pypi（见模板高级配置→网络配置）
            pip_cmd = " && ".join(
                f"pip install -r '/home/user/workspace/{f}' -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet --disable-pip-version-check"
                for f in req_files[:2]
            )
            pcode, pout, perr = _data_exec(pip_cmd, step_timeout + 60)
            tail = ((pout or "") + "\n" + (perr or "")).strip().splitlines()[-20:]
            deps_log = "\n".join(tail)
            phases.append(f"② 装依赖 {', '.join(req_files)} → {'成功' if pcode == 0 else '失败(code ' + str(pcode) + ')'}")
            if pcode != 0:
                return {"ok": False, "code": pcode,
                        "stdout": "",
                        "stderr": f"依赖安装失败（{', '.join(req_files)}）：\n" + "\n".join(tail)
                                 + "\n（如报网络不通，请在百炼模板→高级配置→网络配置放行 pypi；域名需带 https:// 前缀）",
                        "sandbox_id": sandbox_id, "phases": phases, "deps_log": deps_log}
            deps_note = f"已自动安装依赖（{', '.join(req_files)}）"

        # 5. 执行入口命令
        phases.append(f"③ 跑脚本 {command}")
        code, out, err = _data_exec(command, step_timeout)

        def _fetch(abs_path: str) -> bytes:
            fr = httpx.get(f"{domain}/files", params={"path": abs_path}, headers=dh, timeout=60)
            if fr.status_code not in (200, 201):
                raise ValueError(f"下载产物失败（{fr.status_code}）")
            return fr.content

        produced = _fetch_outputs(files.keys(), _data_exec, _fetch, skill_id) if code == 0 else []
        if produced:
            phases.append(f"④ 取回产物 {len(produced)} 个：" + "、".join(p["name"] for p in produced))
        return {"ok": code == 0, "code": code, "stdout": out[:MAX_OUT], "stderr": err[:MAX_OUT],
                "deps": deps_note, "sandbox_id": sandbox_id, "phases": phases, "deps_log": deps_log,
                "files": produced}
    finally:
        _cleanup()


E2B_API_KEY_PLACEHOLDER = "e2b_0123456789abcdef"
SBX_WS = "/home/user/workspace"


def run_remote_sdk(owner_id, skill_id, rel: str, args: list, *, endpoint: str, token: str, timeout_s: int,
                   workspace_id: str = "", region: str = "cn-beijing", template_code: str = "") -> dict:
    """百炼 Sandbox 执行（官方 E2B SDK，版本按文档 pin 死）：建实例 → 写文件 → 装依赖 → 跑脚本 → 取产物 → 释放。

    raw HTTP 手写 E2B 协议处处踩坑（201/鉴权头/进程消息体），以 SDK 为准；执行链路 phases 照旧返回。
    """
    from e2b import Sandbox

    if not workspace_id or not token or not template_code:
        raise ValueError("百炼沙箱缺配置：工作空间ID / API Key / 模板 code 必填")
    base = _bailian_base(workspace_id, region)
    entry = str(rel).replace("\\", "/")
    safe_args = [str(a)[:200] for a in (args or [])][:8]
    quoted = " ".join(f"'{a.replace(chr(39), chr(39) * 4)}'" for a in safe_args)
    command = f"python3 {entry} {quoted}".strip() if entry.endswith(".py") else (
        f"node {entry} {quoted}".strip() if entry.endswith(".js") else f"bash {entry} {quoted}".strip()
    )
    files = collect_exec_files(owner_id, skill_id)
    if entry not in files:
        base_name = entry.rsplit("/", 1)[-1].lower()
        same = [f for f in files if f.rsplit("/", 1)[-1].lower() == base_name][:3]
        hint = f"（可发送的同名文件：{'、'.join(same)}）" if same else "（注意用包内完整相对路径，参考 Skill 清单里的脚本路径）"
        raise ValueError(f"入口脚本 {entry} 不在可发送文件内{hint}")
    req_files = sorted(
        frel for frel in files
        if frel.rsplit("/", 1)[-1].lower().startswith("requirements") and frel.lower().endswith(".txt")
    )
    step_timeout = max(10, min(int(timeout_s or 30), 120))

    try:
        sbx = Sandbox.create(api_url=base, api_key=E2B_API_KEY_PLACEHOLDER,
                             headers={"Authorization": f"Bearer {token}"}, template=template_code)
    except Exception as e:
        raise ValueError(f"创建沙箱实例失败：{e}")
    sandbox_id = getattr(sbx, "sandbox_id", "") or ""
    phases = [f"① 建实例 sandboxID={sandbox_id}"]

    def _run(cmd: str, limit: int) -> tuple[int, str, str]:
        try:
            r = sbx.commands.run(cmd, cwd=SBX_WS, timeout=limit)
        except Exception as e:
            # E2B 非零退出抛 CommandExitException：把它的 stdout/stderr 拆出来，别吞掉 pip 日志
            return (int(getattr(e, "exit_code", 1) or 1),
                    str(getattr(e, "stdout", "") or ""),
                    (str(getattr(e, "stderr", "") or "") or str(e))[:2000])
        return int(r.exit_code or 0), str(r.stdout or ""), str(r.stderr or "")

    try:
        for frel, text in files.items():
            try:
                sbx.files.write(f"{SBX_WS}/{frel}", text)
            except Exception as e:
                raise ValueError(f"写文件 {frel} 失败：{e}")
        deps_note = ""
        deps_log = ""
        if req_files:
            outs: list[str] = []
            ok_all, pcode = True, 0
            for f in req_files[:2]:
                c, o, e = _run(
                    f"pip install -r '{SBX_WS}/{f}' -i https://pypi.tuna.tsinghua.edu.cn/simple"
                    " --quiet --disable-pip-version-check",
                    step_timeout + 60,
                )
                outs.append((o + "\n" + e).strip())
                if c != 0:
                    ok_all, pcode = False, c
            tail = "\n".join(outs).splitlines()[-20:]
            deps_log = "\n".join(tail)
            phases.append(f"② 装依赖 {', '.join(req_files)} → {'成功' if ok_all else '失败(code ' + str(pcode) + ')'}")
            if not ok_all:
                return {"ok": False, "code": pcode, "stdout": "",
                        "stderr": f"依赖安装失败（{', '.join(req_files)}）：\n{deps_log}"
                                  "\n（如报网络不通，请在百炼模板→高级配置→网络配置放行 pypi；域名需带 https:// 前缀）",
                        "deps": "", "sandbox_id": sandbox_id, "phases": phases,
                        "deps_log": deps_log, "files": [], "provider": "bailian"}
            deps_note = f"已自动安装依赖（{', '.join(req_files)}）"
        phases.append(f"③ 跑脚本 {command}")
        code, out, err = _run(command, step_timeout)
        produced: list = []
        if code == 0:
            c, o, _ = _run("find /home/user/workspace -type f | sort", 30)
            if c == 0:
                import base64 as _b64

                sent = set(files.keys())
                for line in (o or "").splitlines():
                    r = line.strip()
                    if r.startswith(SBX_WS + "/"):
                        r = r[len(SBX_WS) + 1:]
                    r = r.strip()
                    if not r or r in sent or "__pycache__" in r.split("/"):
                        continue
                    if len(produced) >= FETCH_MAX_FILES:
                        break
                    bc, bo, _be = _run(f"base64 -w0 '{SBX_WS}/{r}'", 60)
                    if bc != 0:
                        continue
                    try:
                        data = _b64.b64decode(bo.strip())
                    except Exception:
                        continue
                    if not data or len(data) > FETCH_MAX_BYTES:
                        continue
                    safe = pathlib.PurePosixPath(r).name[:80] or "output.bin"
                    dest_dir = pathlib.Path("uploads") / "skills" / str(skill_id)
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    (dest_dir / safe).write_bytes(data)
                    produced.append({"name": safe, "url": f"/uploads/skills/{skill_id}/{safe}",
                                     "bytes": len(data)})
            if produced:
                phases.append(f"④ 取回产物 {len(produced)} 个：" + "、".join(p["name"] for p in produced))
        return {"ok": code == 0, "code": code, "stdout": out[:MAX_OUT], "stderr": err[:MAX_OUT],
                "deps": deps_note, "sandbox_id": sandbox_id, "phases": phases, "deps_log": deps_log,
                "files": produced, "provider": "bailian"}
    finally:
        try:
            sbx.kill()
        except Exception:
            pass


def dispatch(owner_id, skill_id, rel: str, args: list, *, provider: str = "local", endpoint: str = "",
             token: str = "", timeout_s: int = 30, workspace_id: str = "",
             region: str = "cn-beijing", template_code: str = "") -> dict:
    """统一执行入口（对话框工具与 Skill 页运行共用）：按沙箱配置路由到本地/百炼，结果带 provider。

    沙箱失败（配置缺失/建实例失败）自动回退本地：保证"先跑通"，沙箱接口原样保留、随时切回。
    """
    if (provider or "local") == "bailian" and (workspace_id or "").strip():
        try:
            result = run_remote_sdk(
                owner_id, skill_id, rel, args if isinstance(args, list) else [],
                endpoint=endpoint, token=token or "", timeout_s=timeout_s or 30,
                workspace_id=workspace_id or "", region=region or "cn-beijing",
                template_code=template_code or "",
            )
            result["provider"] = "bailian"
            return result
        except ValueError as e:
            import logging as _log

            _log.getLogger(__name__).warning("百炼沙箱不可用，回退本地执行：%s", e)
    if (provider or "") == "aliyun_fc":
        raise ValueError("自建函数沙箱已下线，请在沙箱配置区改用“阿里云百炼”")
    result = run_script(owner_id, skill_id, rel, args if isinstance(args, list) else [], timeout_s=timeout_s)
    result["provider"] = "local"
    return result


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
