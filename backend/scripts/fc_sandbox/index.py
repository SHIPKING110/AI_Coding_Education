"""阿里云函数计算 FC · Skill 脚本沙箱执行器。

部署方式（二选一，见 README_DEPLOY.md）：
  A. 控制台粘贴：新建 Python3.10 函数 → 把本文件内容粘贴为 index.py → 入口 index.handler
  B. S 工具部署：s deploy（s.yaml 同目录，需先配密钥，见 README）

协议：
  请求 POST JSON: {"entry": "a.py", "language": "python|node|bash",
                   "args": [...], "timeout": 25, "files": {"a.py": "..."}}
  Header: Authorization: Bearer <SANDBOX_TOKEN>（与环境变量一致）
  响应 JSON: {"ok": bool, "code": int, "stdout": str, "stderr": str}
"""

import json
import os
import shutil
import subprocess
import tempfile

TOKEN = os.environ.get("SANDBOX_TOKEN", "")
TIMEOUT_MAX = 120
OUT_MAX = 8 * 1024


def _resp(obj, status=200):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(obj, ensure_ascii=False),
    }


def handler(event, context):
    # 鉴权（token 为空表示未配置：拒绝，避免裸奔）
    if not TOKEN:
        return _resp({"ok": False, "code": -1, "stdout": "", "stderr": "函数未配置 SANDBOX_TOKEN 环境变量"}, 500)
    try:
        headers = (event.get("headers") or {}) if isinstance(event, dict) else {}
        auth = headers.get("authorization") or headers.get("Authorization") or ""
        if auth != f"Bearer {TOKEN}":
            return _resp({"ok": False, "code": -1, "stdout": "", "stderr": "unauthorized"}, 401)
        body = event.get("body", "") if isinstance(event, dict) else ""
        if isinstance(body, str):
            try:
                req = json.loads(body) if body else {}
            except Exception:
                req = {}
        else:
            req = body or {}
    except Exception as e:
        return _resp({"ok": False, "code": -1, "stdout": "", "stderr": f"bad request: {e}"}, 400)

    entry = str(req.get("entry", "") or "").replace("\\", "/")
    language = str(req.get("language", "python") or "python").lower()
    args = [str(a)[:200] for a in (req.get("args") or [])][:8]
    timeout = max(5, min(int(req.get("timeout") or 25), TIMEOUT_MAX))
    files = req.get("files") or {}
    if not entry or entry.startswith("/") or ".." in entry.split("/"):
        return _resp({"ok": False, "code": -1, "stdout": "", "stderr": "非法 entry"})

    runners = {"python": ["python3"], "node": ["node"], "bash": ["bash"]}
    if language not in runners or shutil.which(runners[language][0]) is None:
        return _resp({"ok": False, "code": -1, "stdout": "", "stderr": f"运行时 {language} 不可用"}, 400)

    with tempfile.TemporaryDirectory() as work:
        for rel, text in list(files.items())[:100]:
            rel = str(rel).replace("\\", "/")
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                continue
            if len(str(text)) > 200 * 1024:
                continue
            target = os.path.join(work, rel)
            os.makedirs(os.path.dirname(target) or work, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(str(text))
        target = os.path.join(work, entry)
        if not os.path.exists(target):
            return _resp({"ok": False, "code": -1, "stdout": "", "stderr": f"入口不存在：{entry}"}, 400)
        try:
            p = subprocess.run(
                [*runners[language], target, *args],
                capture_output=True, text=True, timeout=timeout,
                cwd=work, env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired:
            return _resp({"ok": False, "code": 124, "stdout": "", "stderr": f"执行超时（{timeout}s），已终止"})
        return _resp({
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout": (p.stdout or "")[:OUT_MAX],
            "stderr": (p.stderr or "")[:OUT_MAX],
        })
