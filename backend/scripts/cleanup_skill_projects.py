"""清理「会话隔离改造前」遗留的共享 Skill 项目（幂等，默认 dry-run）。

背景：ADR-0015 之后 Skill 的 projects/ 已按会话隔离到 conversations/conv_xxx/projects/。
改造前遗留在「技能根 projects/」下的旧项目不再被新会话读取，属于死重量/易混淆，
本脚本用于一次性清理（默认只列不删，加 --apply 才真删）。

安全：只处理 <skill>/projects/* 下的**一级子目录**（旧共享项目）；
绝不触碰 conversations/（会话隔离目录）与 scripts/templates/references 等包内容。
用法（容器内）：
  docker compose exec backend python scripts/cleanup_skill_projects.py           # 预览
  docker compose exec backend python scripts/cleanup_skill_projects.py --apply   # 删除
"""

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="清理遗留的共享 Skill 项目（默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="实际删除（默认只预览）")
    args = ap.parse_args()

    root = os.path.join(get_settings().UPLOAD_DIR, "skills")
    targets = []
    if os.path.isdir(root):
        for owner in os.listdir(root):
            op = os.path.join(root, owner)
            if not os.path.isdir(op):
                continue
            for skill in os.listdir(op):
                proj = os.path.join(op, skill, "projects")
                if not os.path.isdir(proj):
                    continue
                for name in os.listdir(proj):
                    pd = os.path.join(proj, name)
                    # 只处理一级子目录；跳过 conversations（会话隔离目录不应出现在此处，防御性跳过）
                    if os.path.isdir(pd) and name != "conversations":
                        n = sum(len(fs) for _, _, fs in os.walk(pd))
                        targets.append((pd, n))

    total_files = sum(n for _, n in targets)
    print(f"发现 {len(targets)} 个遗留共享项目，共 {total_files} 个文件：")
    for pd, n in targets:
        rel = os.path.relpath(pd, root)
        print(f"  - {rel}  ({n} files)")
    if not targets:
        print("无遗留项目，无需清理。")
        return
    if args.apply:
        for pd, _ in targets:
            shutil.rmtree(pd, ignore_errors=True)
        print(f"[已删除] {len(targets)} 个遗留项目")
    else:
        print("\n[DRY-RUN] 未删除。确认无误后加 --apply 执行。")


if __name__ == "__main__":
    main()
