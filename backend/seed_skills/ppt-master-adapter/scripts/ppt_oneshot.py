#!/usr/bin/env python3
"""PPT-Master 兼容适配器（one-shot 包装）：把 ppt-master 的多步生成/编辑流程收成一条命令。

官方流程是多阶段交互式的（project_manager -> 质量门禁 -> 导出，外加确认UI/模板候选/图片获取）。
工作台模型工具预算有限，自己摸多步路由极易漏步走偏（正是"生成不稳、二次编辑崩"的诱因）。
本脚本不重写 ppt-master，只编排它自带的脚本，把最稳的链路封成单入口，生成质量与官方一致。

  build  : 质量门禁 -> 导出 pptx（一步出成品）
  edit   : 把已有 .pptx 导入为可编辑工作区(roundtrip)
  export : 对已改好的 roundtrip 工作区导出
  init   : 初始化项目目录
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
from pathlib import Path


def _find_skill_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "scripts" / "svg_to_pptx.py").is_file():
            return parent
    for parent in [here.parent, *here.parents]:
        cand = parent / "ppt-master-main" / "skills" / "ppt-master"
        if (cand / "scripts" / "svg_to_pptx.py").is_file():
            return cand
    raise SystemExit("找不到 ppt-master 脚本目录（scripts/svg_to_pptx.py）")


SKILL_ROOT = _find_skill_root()
SCRIPTS = SKILL_ROOT / "scripts"
PY = sys.executable

_NUM_PREFIX = re.compile(r"^(\d+)[_\-\s]*(.*)$")


def _normalize_svg_order(project: Path) -> None:
    """导出前把 svg_output/*.svg 规范为「连续唯一」的两位序号前缀，保证页序确定。

    为什么需要：svg_to_pptx 严格按文件名排序导出。模型增/删/调序时若没重排序号，
    会出现重号（如两个 02_）——此时顺序退化为「数字相同再按整串字母序」，等于碰运气。
    本函数按「数字前缀（缺失视为最大）→ 文件名」排序后统一重编号为 01_ 02_ 03_…
    （保留原描述后缀），既消除重号，又让导出顺序与模型文件名语义一致。

    局限（诚实说明）：它只保证「确定 + 无重号」，不猜模型意图——真正的页序仍取决于
    模型给的前缀数字（SKILL.md 快速通道已要求重排序号）。二者配合才稳。
    """
    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    files = [p for p in svg_dir.iterdir() if p.is_file() and p.suffix.lower() == ".svg"]
    if len(files) <= 1:
        return

    def _key(p: Path):
        m = _NUM_PREFIX.match(p.name)
        num = int(m.group(1)) if m else 10 ** 9
        return (num, p.name.lower())

    ordered = sorted(files, key=_key)
    nums = []
    has_dup = False
    for p in ordered:
        m = _NUM_PREFIX.match(p.name)
        n = int(m.group(1)) if m else -1
        nums.append(n)
    seen = set()
    for n in nums:
        if n in seen:
            has_dup = True
        seen.add(n)
    is_consecutive = nums == list(range(1, len(nums) + 1))

    if is_consecutive and not has_dup:
        return  # 已经规范，无需改

    # 需要重排：按当前排序结果重新连续编号（先改到临时名避免命名冲突）
    plan = []
    for i, p in enumerate(ordered):
        stem = p.stem  # 文件名去扩展名，如 "02_syllabus"
        m = _NUM_PREFIX.match(stem)
        slug = (m.group(2) if m and m.group(2) else stem).strip("_- ") or stem
        new_name = f"{i + 1:02d}_{slug}.svg"
        plan.append((p, new_name))

    tmp_pairs = []
    for p, new_name in plan:
        tmp = svg_dir / (".renumber_" + p.name)
        p.rename(tmp)
        tmp_pairs.append((tmp, svg_dir / new_name))
    for tmp, dest in tmp_pairs:
        tmp.rename(dest)

    print("[已自动重排页序] 检测到 SVG 序号重复/断号，已按当前顺序重编号为 01..N：")
    for _, dn in plan:
        print("  ->", dn)


def _run(args):
    p = subprocess.run([PY, *args], cwd=str(SKILL_ROOT), capture_output=True, text=True)
    out = ((p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")).strip()
    return p.returncode, out


def _tail(text, n=1600):
    return text if len(text) <= n else "..." + text[-n:]


def _newest_pptx(project):
    files = sorted(glob.glob(str(project / "**" / "*.pptx"), recursive=True),
                   key=lambda f: os.path.getmtime(f))
    return files[-1] if files else None


def _resolve_project(project: Path) -> Path:
    """容忍路径不一致：若给定 project 目录不存在，但 SKILL_ROOT 下有
    conversations/*/projects/<同名> 或 projects/<同名>，回退到实际存在且有 svg_output 的那个。

    背景：模型可能把 SVG 写到「会话隔离目录 conversations/conv_xxx/projects/X」，
    但 build 用了未隔离的「projects/X」；这里做一次确定性回退，避免"写了页却 build 空目录"。
    """
    if (project / "svg_output").is_dir():
        return project
    name = project.name
    candidates = []
    for base in [SKILL_ROOT / "projects", *list((SKILL_ROOT / "conversations").glob("*/projects"))]:
        cand = base / name
        if (cand / "svg_output").is_dir():
            # 选 svg 最近改过的那个（当前会话产物最新）
            svgs = list((cand / "svg_output").glob("*.svg"))
            mtime = max((p.stat().st_mtime for p in svgs), default=0)
            candidates.append((mtime, cand))
    if candidates:
        candidates.sort(reverse=True)
        chosen = candidates[0][1]
        print(f"[路径回退] {project} 不存在，改用 {chosen}")
        return chosen
    return project


def _sanitize_svg_colors(project: Path) -> None:
    """导出前修正模型常见的「非法颜色值」，避免质量门禁因小瑕疵整单失败。

    典型：stroke='#33island'（模型把颜色写成非法 token）、#RRGGBB 后跟杂字符等。
    规则：把 `#hex` 后面粘连的非十六进制字符截断；对明显过短/非法的 hex 回退到安全色。
    只动颜色属性值，不改结构与文案。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    color_attr = _re.compile(
        r"""(fill|stroke|color|stop-color)\s*=\s*(["'])([^"']*)(["'])""", _re.IGNORECASE
    )
    hex_ok = _re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
    fixed = 0
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        def _fix(m):
            nonlocal fixed
            attr, q1, val, q2 = m.group(1), m.group(2), m.group(3).strip(), m.group(4)
            if val.lower() in ("none", "currentcolor", "transparent") or val.startswith("url("):
                return m.group(0)
            nv = val
            if val.startswith("#"):
                # 截断到第一个非 hex 字符
                mm = _re.match(r"#([0-9a-fA-F]+)", val)
                hexpart = "#" + (mm.group(1) if mm else "")
                # 规整长度：补到 6 位（3→6 复制，其他取前6）
                h = hexpart[1:]
                if len(h) == 3:
                    h = h[0]*2 + h[1]*2 + h[2]*2
                h = h[:6] if len(h) >= 6 else (h + "0" * (6 - len(h)))
                nv = "#" + h
                if not hex_ok.match(nv):
                    nv = "#000000"
                if nv != val:
                    fixed += 1
            return f'{attr}={q1}{nv}{q2}'

        new = color_attr.sub(_fix, text)
        if new != text:
            try:
                p.write_text(new, encoding="utf-8")
            except OSError:
                pass
    if fixed:
        print(f"[颜色修正] 已规范化 {fixed} 处非法颜色值")


def _qc_errors_only(out: str) -> bool:
    """从质量检查输出判断「是否只有 warning、没有 error」。

    返回 True 表示可放行导出（仅有 warning / 仅 passed:0 但 errors:0）。
    """
    import re as _re
    txt = out or ""
    # 抓 JSON 摘要里的 errors 计数（--json 会带 summary）
    m = _re.search(r'"errors"\s*:\s*(\d+)', txt)
    if m:
        try:
            return int(m.group(1)) == 0
        except ValueError:
            return False
    # 无 json 摘要时，按关键字判断：出现 ERROR 视为阻断
    return not _re.search(r"\[ERROR\]|\berrors?\s*[:：]\s*[1-9]", txt, _re.IGNORECASE)


def cmd_build(args):
    project = _resolve_project(Path(args.project).resolve())
    _normalize_svg_order(project)
    _sanitize_svg_colors(project)
    qc = [str(SCRIPTS / "svg_quality_checker.py"), str(project),
          "--quick-generate", "--canonical-authoring", "--stage", "final", "--json"]
    code, out = _run(qc)
    # 质量门禁：**仅 warning 不阻断出片**（errors:0 即放行）；只有存在 error 才停。
    # 原因：模型生成的 SVG 几乎总有字体/颜色规范类 warning，若一律拦截会「写了页却永不出片」。
    if code != 0 and not _qc_errors_only(out):
        print("[质量检查未通过（存在 error）]\n" + _tail(out))
        return code
    if code != 0:
        print("[质量检查：仅有 warning，已放行出片]\n" + _tail(out)[:600])
    # 导出（--quick-generate 自带宽松导出；不能再叠 --enable-dangerous-nonconforming，二者冲突）
    code, out = _run([str(SCRIPTS / "svg_to_pptx.py"), str(project), "--quick-generate"])
    print(_tail(out))
    if code != 0:
        return code
    pptx = _newest_pptx(project)
    if pptx:
        print("\n[PPTX]" + pptx)
    return 0


def cmd_edit(args):
    src = Path(args.pptx).resolve()
    project = Path(args.project).resolve()
    if not src.is_file():
        print("[错误] 源 pptx 不存在：" + str(src))
        return 2
    code, out = _run([str(SCRIPTS / "pptx_to_svg.py"), str(src), "-o", str(project),
                      "--inheritance-mode", "both", "--roundtrip"])
    print(_tail(out))
    return code


def cmd_export(args):
    project = Path(args.project).resolve()
    code, out = _run([str(SCRIPTS / "svg_to_pptx.py"), str(project), "--roundtrip"])
    print(_tail(out))
    if code != 0:
        return code
    pptx = _newest_pptx(project)
    if pptx:
        print("\n[PPTX]" + pptx)
    return 0


def cmd_init(args):
    code, out = _run([str(SCRIPTS / "project_manager.py"), "init", args.name])
    print(_tail(out))
    return code


def main():
    ap = argparse.ArgumentParser(description="PPT-Master 兼容适配器（one-shot）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="质量门禁 + 导出 pptx")
    b.add_argument("project")
    b.set_defaults(func=cmd_build)
    e = sub.add_parser("edit", help="把已有 pptx 导入为可编辑工作区")
    e.add_argument("pptx")
    e.add_argument("project")
    e.set_defaults(func=cmd_edit)
    x = sub.add_parser("export", help="对改好的工作区做 roundtrip 导出")
    x.add_argument("project")
    x.set_defaults(func=cmd_export)
    i = sub.add_parser("init", help="初始化项目目录")
    i.add_argument("name")
    i.set_defaults(func=cmd_init)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
