"""清理「旧版 ppt-master」的悬空引用（幂等，默认 dry-run）。

背景：教师/管理员早期绑定的是旧版 ppt-master（无 ppt_oneshot 适配 wrapper）。
后发布广场适配版后，旧版成为"同名遮蔽源"（虽已按名自愈不再生效，但残留引用仍混淆）。
本脚本做两件安全的事（不删用户数据，可回滚）：
  1) 把所有 Agent 的 skill_ids / 全局默认里指向旧版的项，替换为适配版（若同 owner 可用），否则移除；
  2) 停用旧版（enabled=False），使其彻底退出解析（不物理删除，留作回溯）。

判定「旧版」：name=ppt-master 且目录内缺 ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py。
判定「适配版」：name=ppt-master 且含上述 wrapper（任取一个可用者，优先 plaza）。

用法（容器内）：
  docker compose exec backend python scripts/cleanup_legacy_pptm.py           # 预览
  docker compose exec backend python scripts/cleanup_legacy_pptm.py --apply   # 执行
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.crud import agent_ext as ext  # noqa: E402
from app.models.agent_ext import AgentGlobalSetting, AgentSkill, CustomAgent  # noqa: E402
from app.services import skill_bundle  # noqa: E402

WRAPPER = "ppt-master-main/skills/ppt-master/scripts/ppt_oneshot.py"


def _has_wrapper(s) -> bool:
    d = skill_bundle.skill_dir(s.owner_id, s.id)
    return (d / WRAPPER).is_file() or WRAPPER in [str(f) for f in (s.files or [])]


def main() -> None:
    ap = argparse.ArgumentParser(description="清理旧版 ppt-master 悬空引用")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        skills = list(db.scalars(select(AgentSkill).where(AgentSkill.name == "ppt-master")).all())
        legacy = [s for s in skills if not _has_wrapper(s)]
        adapter = [s for s in skills if _has_wrapper(s)]
        print(f"适配版: {[str(s.id)[:8] for s in adapter]}")
        print(f"旧版  : {[str(s.id)[:8] for s in legacy]}")
        legacy_ids = {str(s.id) for s in legacy}
        adapter_ids = {str(s.id) for s in adapter}
        if not legacy:
            print("无旧版，无需清理。")
            return

        def replacement_for(owner_id):
            # 优先同 owner 的适配版，其次 plaza 适配版
            for s in adapter:
                if str(s.owner_id) == str(owner_id):
                    return str(s.id)
            for s in adapter:
                if getattr(s, "visibility", "") == "plaza":
                    return str(s.id)
            return None

        changes = 0
        # 1) 修 Agent 绑定
        for c in db.scalars(select(CustomAgent)).all():
            ids = [str(x) for x in (c.skill_ids or [])]
            hit = [x for x in ids if x in legacy_ids]
            if not hit:
                continue
            new_ids = [x for x in ids if x not in legacy_ids]
            repl = replacement_for(c.owner_id)
            if repl and repl not in new_ids:
                new_ids.append(repl)
            print(f"  Agent {c.name}({str(c.owner_id)[:8]}): {[x[:8] for x in ids]} -> {[x[:8] for x in new_ids]}")
            changes += 1
            if args.apply:
                ext.update_custom_agent(db, c, skill_ids=new_ids)
        # 2) 修全局默认
        for g in db.scalars(select(AgentGlobalSetting)).all():
            ids = [str(x) for x in (g.default_skill_ids or [])]
            hit = [x for x in ids if x in legacy_ids]
            if not hit:
                continue
            new_ids = [x for x in ids if x not in legacy_ids]
            repl = replacement_for(g.owner_id)
            if repl and repl not in new_ids:
                new_ids.append(repl)
            print(f"  Global {str(g.owner_id)[:8]}: {[x[:8] for x in ids]} -> {[x[:8] for x in new_ids]}")
            changes += 1
            if args.apply:
                ext.upsert_global_setting(db, owner_id=g.owner_id, default_skill_ids=new_ids)
        # 3) 停用旧版
        for s in legacy:
            print(f"  停用旧版 {str(s.id)[:8]}")
            if args.apply:
                ext.update_skill(db, s, enabled=False)

        print(f"{'[已执行]' if args.apply else '[DRY-RUN]'} 受影响 Agent/Global: {changes}，旧版 {len(legacy)} 个")
        if not args.apply:
            print("确认无误后加 --apply。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
