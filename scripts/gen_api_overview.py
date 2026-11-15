"""生成 docs/api-overview.md：从 OpenAPI schema 输出 method/path/tag 清单。

用法（backend 目录下）：`uv run python ../scripts/gen_api_overview.py`
说明：新版 FastAPI 的 include_router 为惰性包装，直接遍历 app.routes 拿不到子路由，
     因此统一从 app.openapi()["paths"] 生成（无需数据库连接）。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from app.main import app  # noqa: E402


def main() -> None:
    schema = app.openapi()
    groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for path, ops in schema.get("paths", {}).items():
        seg = path.strip("/").split("/")
        group = seg[1] if len(seg) > 1 and seg[0] == "api" else "root"
        for method, op in ops.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            summary = op.get("summary") or ""
            tags = ", ".join(op.get("tags") or [])
            groups[group].append((method.upper(), path, summary or tags))

    total = sum(len(v) for v in groups.values())
    lines = [
        "# API 概览（自动生成）",
        "",
        "> 由 `scripts/gen_api_overview.py` 从 OpenAPI schema 生成，勿手改。",
        "> 重新生成：`cd backend && uv run python ../scripts/gen_api_overview.py`",
        "",
        f"共 **{total}** 个端点，按 `/api/<前缀>` 分组；权限细节见各路由源码依赖声明。",
        "",
    ]
    for group in sorted(groups):
        lines.append(f"## /api/{group}" if group != "root" else "## 其他")
        lines.append("")
        lines.append("| 方法 | 路径 | 说明 |")
        lines.append("| --- | --- | --- |")
        for method, path, desc in sorted(groups[group], key=lambda x: (x[1], x[0])):
            lines.append(f"| {method} | `{path}` | {desc} |")
        lines.append("")
    Path("../docs/api-overview.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote ../docs/api-overview.md，{total} endpoints")


if __name__ == "__main__":
    main()
