"""清理历史消息中残留的「原生工具调用标记」乱码（幂等可重跑）。

背景：早期最终回答走纯文本流式，模型偶发把工具调用特殊 token（如 tool-calls-begin 标记、
DSML 标记、function_calls）当普通文本输出，落库后显示为乱码并被当历史回灌。系统读取侧已做净化
（见 ADR-0013），本脚本把库中已存的乱码一次性清洗。

用法（容器内）：
    docker compose exec backend python scripts/cleanup_garbled_messages.py          # 预览
    docker compose exec backend python scripts/cleanup_garbled_messages.py --apply  # 写入
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.agent import AgentMessage  # noqa: E402
from app.services.llm import strip_toolcall_markup  # noqa: E402

_FW = chr(0xFF5C)
_US = chr(0x2581)
PLACEHOLDER = "（此条消息为旧版本工具调用标记乱码，已自动清理）"


def is_dirty(s: str) -> bool:
    if not s:
        return False
    return ("<|" in s) or ("<" + _FW in s) or ("DSML" in s) or ("function_calls" in s) or ("tool" + _US + "call" in s)


def main() -> None:
    ap = argparse.ArgumentParser(description="清理历史消息中的工具调用标记乱码")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认仅预览）")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        rows = db.execute(select(AgentMessage.id, AgentMessage.content).where(AgentMessage.role == "assistant")).all()
        changed = emptied = 0
        for mid, content in rows:
            if not is_dirty(content):
                continue
            clean = strip_toolcall_markup(content)
            if clean == content:
                continue
            changed += 1
            new = clean if clean.strip() else PLACEHOLDER
            if not clean.strip():
                emptied += 1
            print(f"CHANGE {mid} {len(content)} -> {len(new)}")
            if args.apply:
                db.execute(AgentMessage.__table__.update().where(AgentMessage.id == mid).values(content=new))
        if args.apply:
            db.commit()
        print(f"{'APPLIED' if args.apply else 'DRY-RUN'} scanned={len(rows)} dirty_changed={changed} emptied={emptied}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
