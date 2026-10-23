"""把「ppt-master 兼容适配版」装成 Skill（幂等）。不依赖大 zip 入库——
运行时从**已有的上传版 ppt-master 包**就地构造适配版：

  1) 复制源包（缺省取广场/任意已上传的 ppt-master 包）；
  2) 注入 scripts/ppt_oneshot.py（一条命令出片/编辑/导出，本仓库 backend/seed_skills/... 提供）；
  3) 在 SKILL.md 顶部写入「工作台快速通道」提示；
  4) 用与「上传 ZIP 导入」一致的 skill_bundle.save_bundle 落盘，建/更新 AgentSkill；
  5) 可选 --publish 发布到广场。

用法（容器内）：
    docker compose exec backend python scripts/seed_ppt_master_adapter.py --owner admin --publish
"""

import argparse
import io
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.crud import agent_ext as ext  # noqa: E402
from app.models.agent_ext import AgentSkill  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import skill_bundle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ADAPTER_SCRIPT = os.path.join(
    HERE, "..", "seed_skills", "ppt-master-adapter", "scripts", "ppt_oneshot.py"
)
NAME = "ppt-master"
DESCRIPTION = "PPT 生成与二次编辑（兼容适配版·一步出片/就地改页）"
FASTLANE = (
    "> ⚡ **本工作台快速通道（优先使用）**：生成 PPT 直接用封装脚本一步出片，"
    "不必逐条执行下方多阶段交互流程（确认UI/模板候选/图片获取在工作台不可用）：\n"
    "> 1) 每页写成 SVG 放进 `<项目>/svg_output/`，**文件名前缀序号即页序**（01_cover.svg、02_...、03_...，务必连续且唯一）；\n"
    "> 2) `python3 \"${SKILL_DIR}/scripts/ppt_oneshot.py\" build <项目>`（质量门禁+导出，产物自动回链）；\n"
    "> 3) 二次编辑：`ppt_oneshot.py edit <源.pptx> <工作区>` 导入 → 改动 `svg_output/` 里的页 → `ppt_oneshot.py export <工作区>`。\n"
    "> **增页/删页/调序的铁律**：改完 `svg_output/` 后，必须按最终页序重命名所有文件为 01_ 02_ 03_…（连续、唯一、两位序号）；"
    "导出严格按文件名排序，出现重复序号（如两个 02_）会导致顺序错乱。\n\n---\n\n"
)


def _find_source_bundle(db, exclude_owner=None) -> AgentSkill | None:
    """找一份已上传的 ppt-master 源包（优先广场，其次任意含 svg_to_pptx 的）。

    必须校验磁盘上真的有 svg_to_pptx.py：否则可能选中「记录还在、目录已被删」的空壳，
    导致后续打包为空、注入失败。
    """
    cands = list(db.scalars(select(AgentSkill).where(AgentSkill.name == NAME)).all())
    cands.sort(key=lambda s: (0 if s.visibility == "plaza" else 1, -len(s.files or [])))
    for s in cands:
        root = skill_bundle.skill_dir(s.owner_id, s.id)
        for rel in (s.files or []):
            if str(rel).endswith("scripts/svg_to_pptx.py") and (root / str(rel)).is_file():
                return s
    return None


def _zip_source(src: AgentSkill) -> bytes:
    """把源 Skill 的落盘目录打包成 zip（保持包内相对路径不变）。"""
    from pathlib import Path

    root = skill_bundle.skill_dir(src.owner_id, src.id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in (src.files or []):
            p = root / str(rel)
            if p.is_file():
                z.write(str(p), str(rel))
    return buf.getvalue()


def _inject_adapter(zip_bytes: bytes) -> bytes:
    """在源包 zip 上注入 wrapper 脚本 + SKILL.md 快速通道段，返回新 zip bytes。"""
    with open(REPO_ADAPTER_SCRIPT, encoding="utf-8") as f:
        wrapper = f.read()
    tmp = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            z.extractall(tmp)
        # 找 ppt-master 技能根（含 scripts/svg_to_pptx.py）
        root = None
        for dirpath, _, _ in os.walk(tmp):
            if os.path.isfile(os.path.join(dirpath, "scripts", "svg_to_pptx.py")):
                root = dirpath
                break
        if root is None:
            raise SystemExit("源包里找不到 scripts/svg_to_pptx.py，无法适配")
        with open(os.path.join(root, "scripts", "ppt_oneshot.py"), "w", encoding="utf-8") as f:
            f.write(wrapper)
        sk = os.path.join(root, "SKILL.md")
        if os.path.isfile(sk):
            txt = open(sk, encoding="utf-8").read()
            # 幂等替换：先剥掉旧的快速通道块（含分隔符），再插最新版，保证重跑能升级提示词
            import re as _re

            txt = _re.sub(r"> ⚡ \*\*本工作台快速通道.*?---\n\n", "", txt, count=1, flags=_re.S)
            idx = txt.find("---", txt.find("---") + 3)
            at = idx + 3 if idx != -1 else 0
            txt = txt[:at] + "\n\n" + FASTLANE + txt[at:]
            open(sk, "w", encoding="utf-8").write(txt)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for dirpath, _, files in os.walk(tmp):
                for fn in files:
                    full = os.path.join(dirpath, fn)
                    z.write(full, os.path.relpath(full, tmp))
        return out.getvalue()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="安装 ppt-master 兼容适配版 Skill（从已有源包就地构造）")
    ap.add_argument("--owner", default="admin")
    ap.add_argument("--publish", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(REPO_ADAPTER_SCRIPT):
        print(f"[错误] 找不到适配脚本：{REPO_ADAPTER_SCRIPT}", file=sys.stderr)
        sys.exit(2)

    db = SessionLocal()
    try:
        user = db.scalars(select(User).where(User.username == args.owner)).first()
        if user is None:
            print(f"[错误] 用户不存在：{args.owner}", file=sys.stderr)
            sys.exit(2)
        src = _find_source_bundle(db)
        if src is None:
            print("[错误] 找不到可用的 ppt-master 源包（需先有人上传过 ppt-master）", file=sys.stderr)
            sys.exit(2)

        data = _inject_adapter(_zip_source(src))

        row = db.scalars(
            select(AgentSkill).where(AgentSkill.owner_id == user.id, AgentSkill.name == NAME)
        ).first()
        if row is None:
            row = AgentSkill(owner_id=user.id, name=NAME, description=DESCRIPTION,
                             content="", files=[], enabled=True, visibility="private")
            db.add(row)
            db.commit()
            db.refresh(row)

        result = skill_bundle.save_bundle(user.id, row.id, data)
        ext.update_skill(db, row, name=NAME, description=DESCRIPTION,
                         files=result["files"], enabled=True)
        if args.publish:
            ext.set_skill_visibility(db, row, "plaza")

        print(f"[OK] 适配版 '{NAME}' 已装到用户 {args.owner}（id={row.id}，源={src.owner_id}）")
        print(f"     文件数：{len(result['files'])}，广场发布：{args.publish}")
        print("     快速通道：scripts/ppt_oneshot.py（build / edit / export）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
