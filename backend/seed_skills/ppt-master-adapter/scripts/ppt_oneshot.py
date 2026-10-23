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


def cmd_build(args):
    project = Path(args.project).resolve()
    _normalize_svg_order(project)
    qc = [str(SCRIPTS / "svg_quality_checker.py"), str(project),
          "--quick-generate", "--canonical-authoring", "--stage", "final", "--json"]
    code, out = _run(qc)
    if code != 0:
        print("[质量检查未通过]\n" + _tail(out))
        return code
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
