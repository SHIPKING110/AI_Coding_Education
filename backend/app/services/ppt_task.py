"""PPT 任务契约服务：规划目标大纲、回写实际产物、校验页数、生成补齐指令。"""

from __future__ import annotations

import json
import re
import uuid

from sqlalchemy.orm import Session

from app.crud import ppt_task as crud
from app.models.ppt_task import AgentPptTask

_NEW_DECK_HINTS = ("重新做", "新的一套", "换一套", "新建", "从头", "重新生成一份", "另做")
_PAGE_COUNT_RE = re.compile(r"(\d{1,3})\s*(?:页|张|p)\b", re.IGNORECASE)


def _norm_title(text: str) -> str:
    return re.sub(r"[\s\-_/·.,，。:：]+", "", str(text or "")).lower()


def _target_from_message(message: str) -> int | None:
    m = _PAGE_COUNT_RE.search(message or "")
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return n if 1 <= n <= 200 else None


def _clean_outline(raw: list, target: int | None = None) -> list[dict]:
    out: list[dict] = []
    for i, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("页标题") or "").strip()
        if not title:
            continue
        out.append({
            "page_id": f"p{i + 1}",
            "order": i + 1,
            "title": title[:120],
            "kind": str(item.get("kind") or ("cover" if i == 0 else "content")),
            "key_points": item.get("key_points") or item.get("要点") or "",
            "status": "pending",
            "svg_file": "",
            "actual_title": "",
            "error": "",
        })
    if target and target > 0:
        out = out[:target]
        while len(out) < target:
            i = len(out)
            out.append({
                "page_id": f"p{i + 1}",
                "order": i + 1,
                "title": f"补充页 {i + 1}",
                "kind": "content",
                "key_points": "",
                "status": "pending",
                "svg_file": "",
                "actual_title": "",
                "error": "",
            })
    return out


def _parse_json(raw: str) -> dict | None:
    raw = (raw or "").strip()
    candidates = [raw]
    m = re.search(r"```json\s*([\s\S]*?)```", raw)
    if m:
        candidates.append(m.group(1))
    m2 = re.search(r"\{[\s\S]*\}", raw)
    if m2:
        candidates.append(m2.group(0))
    for c in candidates:
        try:
            data = json.loads(c)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _plan_outline_with_llm(message: str, *, material_text: str = "", agent_id: str = "") -> dict | None:
    try:
        from app.services import llm

        target = _target_from_message(message)
        target_hint = f"用户明确要求 {target} 页，必须严格输出 {target} 页。" if target else "页数控制在 8-16 页。"
        system = (
            "你是 PPT 任务规划器。先把用户需求冻结成可执行的大纲契约，后续生成严格按契约执行。"
            "只输出 JSON，不要解释。"
        )
        prompt = (
            f"Agent={agent_id}。\n用户需求：{message[:1200]}\n"
            f"素材摘要：{material_text[:3000] or '（无）'}\n"
            f"{target_hint}\n"
            "输出格式："
            '{"title":"PPT标题","theme":"brand|cyan|deep",'
            '"outline":[{"title":"页标题","kind":"cover|content|data|ending","key_points":"本页要点"}]}'
            "\n要求：大纲顺序就是最终页序；标题要具体、可区分；不要输出 Markdown 代码块以外的内容。"
        )
        raw = llm.invoke_text(system, prompt, temperature=0.2, timeout=90)
        data = _parse_json(raw)
        if not data:
            return None
        outline = _clean_outline(data.get("outline") or [], target)
        if not outline:
            return None
        return {
            "title": str(data.get("title") or "智能生成 PPT")[:200],
            "theme": str(data.get("theme") or "brand")[:32],
            "outline": outline,
        }
    except Exception:
        return None


def _extend_outline(outline: list[dict], target: int, *, message: str = "") -> list[dict]:
    """用户明确改页数时扩/缩大纲；扩展页先给可执行占位标题，后续由生成器细化。"""
    out = _clean_outline(outline, None)
    if target <= len(out):
        return _clean_outline(out, target)
    if target > len(out):
        try:
            from app.services import llm

            existing = "、".join(str(x.get("title") or "") for x in out)
            raw = llm.invoke_text(
                "你是 PPT 大纲规划器。只输出 JSON 数组，每项 {\"title\":\"页标题\",\"key_points\":\"要点\"}。",
                f"原有 {len(out)} 页：{existing}\n用户现在要求补齐到 {target} 页。"
                f"请只输出新增的 {target - len(out)} 页，标题不要与原有页重复。原始需求：{message[:800]}",
                temperature=0.2,
                timeout=60,
            )
            data = _parse_json(raw)
            extra = data if isinstance(data, list) else (data or {}).get("outline") if isinstance(data, dict) else None
            if isinstance(extra, list):
                out.extend(_clean_outline(extra, target - len(out)))
        except Exception:
            pass
    return _clean_outline(out, target)


def ensure_contract(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    owner_id: uuid.UUID,
    agent_id: str,
    message: str,
    state_outline: list | None = None,
    material_text: str = "",
) -> AgentPptTask | None:
    """取得/创建当前会话的 PPT 契约。非 PPT 请求返回 None。"""
    from app.services import agent_tools

    text = (message or "").strip()
    active = crud.get_active(db, conversation_id=conversation_id)
    is_ppt_request = bool(active) or agent_tools.looks_like_skill_task(text) or (
        agent_tools.looks_like_ppt_edit(text) or agent_tools.looks_like_ppt_continue(text)
    )
    if not is_ppt_request:
        return None

    # 明确「重新做一套」才归档旧契约；「补齐/改页/继续」永远沿用 active
    if active is not None and any(k in text for k in _NEW_DECK_HINTS) and not any(
        k in text for k in ("补齐", "补页", "补全", "缺页", "继续")
    ):
        crud.archive_active(db, conversation_id=conversation_id, except_id=active.id)
        active = None

    target = _target_from_message(text)
    if active is not None:
        outline = list(active.outline or [])
        if target and target != int(active.target_page_count or 0):
            outline = _extend_outline(outline, target, message=text)
            active = crud.update_task(
                db, active,
                outline=outline,
                target_page_count=len(outline),
                current_page_count=min(int(active.current_page_count or 0), len(outline)),
                status="needs_patch",
                version=int(active.version or 1) + 1,
            )
            crud.add_event(db, task_id=active.id, action="contract.rescale", detail={
                "target": target, "message": text[:300],
            })
        return active

    outline: list[dict] = []
    title = "智能生成 PPT"
    theme = "brand"
    if state_outline:
        outline = _clean_outline(state_outline, target)
    if not outline:
        planned = _plan_outline_with_llm(text, material_text=material_text, agent_id=agent_id)
        if planned:
            outline = planned["outline"]
            title = planned["title"]
            theme = planned["theme"]
    if not outline:
        # 规划模型不可用/未配置 key 时，明确页数的请求仍要冻结契约（占位页序），
        # 否则生成完成后目标页数永远是 0，PPT 对齐率指标失去分母。
        target = _target_from_message(text)
        if target:
            outline = _clean_outline(
                [{"title": f"第 {i + 1} 页", "kind": "cover" if i == 0 else "content"}
                 for i in range(target)],
                target,
            )
    if not outline:
        return None

    task = crud.create_task(
        db,
        conversation_id=conversation_id,
        owner_id=owner_id,
        agent_id=agent_id,
        title=title,
        theme=theme,
        status="outline",
        target_page_count=len(outline),
        current_page_count=0,
        outline=outline,
    )
    crud.add_event(db, task_id=task.id, action="contract.create", detail={
        "target": len(outline), "message": text[:300],
    })
    return task


def _steps_pages(outcome) -> tuple[list[dict], str, str, str]:
    """从工具轨迹提取最后一次 build 的完整页清单、pptx 下载地址、Skill 与项目路径。"""
    pages: list[dict] = []
    pptx_url = ""
    skill_name = ""
    project_key = ""
    for step in getattr(outcome, "steps", []) or []:
        if getattr(step, "tool", "") != "run_skill_script" or not getattr(step, "ok", False):
            continue
        result = getattr(step, "result", None)
        if not isinstance(result, dict):
            continue
        if result.get("skill"):
            skill_name = str(result.get("skill"))
        args = getattr(step, "args", {}) or {}
        raw_args = args.get("args") if isinstance(args, dict) else None
        for token in (raw_args if isinstance(raw_args, list) else []):
            norm = str(token).replace("\\", "/").strip("/")
            if norm == "projects" or norm.startswith("projects/"):
                project_key = norm
                break
        infos = result.get("页信息")
        if isinstance(infos, list) and infos:
            pages = [
                {"name": str(i.get("名") or ""), "title": str(i.get("标题") or ""),
                 "url": str(i.get("url") or "")}
                for i in infos if isinstance(i, dict)
            ]
        elif isinstance(result.get("页清单"), list):
            pages = [{"name": str(x), "title": "", "url": ""} for x in result["页清单"]]
        for f in result.get("生成文件") or []:
            if isinstance(f, dict) and str(f.get("名") or "").lower().endswith(".pptx"):
                pptx_url = str(f.get("下载") or "")
    return pages, pptx_url, skill_name, project_key


def _renumber_outline(outline: list[dict]) -> list[dict]:
    for i, item in enumerate(outline):
        item["page_id"] = f"p{i + 1}"
        item["order"] = i + 1
    return outline


def _disk_svg_pages(task: AgentPptTask) -> list[str]:
    """从磁盘扫描该项目 svg_output 下的 SVG 文件名（按序号排序）。

    build 回执缺失/不完整时，以磁盘实际文件为事实源，避免「文件已生成却仍判缺失」。
    会话隔离路径 + 多 Skill 包：遍历 owner 下所有 skill 目录，按 project_key 匹配。
    """
    from pathlib import Path

    from app.core.config import get_settings

    try:
        base = Path(get_settings().UPLOAD_DIR) / "skills" / str(task.owner_id)
    except Exception:
        return []
    if not base.is_dir():
        return []

    project_key = str(task.project_key or "").replace("\\", "/").strip("/")
    # 候选 svg_output 目录
    cand_dirs: list[Path] = []

    def _collect(d: Path) -> None:
        if d.is_dir():
            if any(p.is_file() and p.suffix.lower() == ".svg" for p in d.iterdir()):
                cand_dirs.append(d)

    # 1) 精确路径匹配（scoped + unscoped）
    keys_to_try: list[str] = []
    if project_key:
        keys_to_try.append(project_key)
        # 去掉会话前缀 → projects/...
        prefix = ""
        if project_key.startswith("conversations/"):
            parts = project_key.split("/", 2)
            if len(parts) >= 3:
                keys_to_try.append(parts[2])
    for skill_dir in base.iterdir():
        if not skill_dir.is_dir():
            continue
        for k in keys_to_try:
            _collect(skill_dir / k / "svg_output")
        # 2) 兜底：遍历所有 svg_output，按项目名/路径包含匹配
        try:
            for svg_dir in skill_dir.rglob("svg_output"):
                if not svg_dir.is_dir():
                    continue
                rel = str(svg_dir.relative_to(skill_dir)).replace("\\", "/")
                if project_key and (project_key in rel or (keys_to_try and any(kt in rel for kt in keys_to_try))):
                    _collect(svg_dir)
        except Exception:
            pass

    if not cand_dirs:
        # 最后兜底：owner 下最近修改的 svg_output
        try:
            all_dirs = [d for d in base.rglob("svg_output") if d.is_dir() and any(p.suffix.lower() == ".svg" for p in d.iterdir())]
            if all_dirs:
                all_dirs.sort(key=lambda d: max((p.stat().st_mtime for p in d.glob("*.svg")), default=0.0), reverse=True)
                cand_dirs = all_dirs[:1]
        except Exception:
            pass

    if not cand_dirs:
        return []

    # 选 SVG 最多 / 最新 的目录
    def _score(d: Path) -> tuple[int, float]:
        svgs = list(d.glob("*.svg"))
        mt = max((p.stat().st_mtime for p in svgs), default=0.0)
        return (len(svgs), mt)

    best = max(cand_dirs, key=_score)
    import re as _re

    def _key(p: Path):
        m = _re.match(r"^(\d+)", p.name)
        return (int(m.group(1)) if m else 10 ** 9, p.name.lower())

    return [p.name for p in sorted(best.glob("*.svg"), key=_key)]


def sync_from_outcome(db: Session, task: AgentPptTask, outcome, *, message: str = "") -> dict:
    """把本轮 build 产物写回契约，并返回校验结果。

    ``message`` 用于区分「用户主动增删页」与「构建漏页」：
      - 新增页：把成品里的额外页并入契约（否则会被判成 extra，陷入反复修复）；
      - 用户要求删页：接受成品页数变少并收缩契约（否则会把删掉的页又补回来）；
      - 其余缺页：保留为 missing，交给补齐流程。
    """
    pages, pptx_url, skill_name, project_key = _steps_pages(outcome)
    # 磁盘观测兜底：build 回执缺失/页数不全时，以磁盘实际 SVG 文件为准，
    # 避免「文件已生成却仍判缺失、后续继续规划要补页」。
    disk_pages = _disk_svg_pages(task)
    if disk_pages:
        existing_names = {str(p.get("name") or "") for p in pages}
        if not pages:
            pages = [{"name": n, "title": "", "url": ""} for n in disk_pages]
        elif len(disk_pages) > len(pages):
            for n in disk_pages:
                if n not in existing_names:
                    pages.append({"name": n, "title": "", "url": ""})
                    existing_names.add(n)
    target_outline = list(task.outline or [])
    target_count = int(task.target_page_count or len(target_outline) or 0)

    if not target_count and pages:
        target_count = len(pages)
        target_outline = _clean_outline(
            [{"title": p.get("title") or p.get("name") or f"第 {i + 1} 页"}
             for i, p in enumerate(pages)],
            target_count,
        )
        task = crud.update_task(db, task, target_page_count=target_count, outline=target_outline)

    used: set[int] = set()
    matched: dict[int, dict] = {}
    matched_page_indices: set[int] = set()
    for i, page in enumerate(pages):
        title = _norm_title(page.get("title") or page.get("name") or "")
        hit = None
        for j, item in enumerate(target_outline):
            if j in used:
                continue
            if title and title == _norm_title(item.get("title") or ""):
                hit = j
                break
        if hit is None:
            for j in range(len(target_outline)):
                if j not in used:
                    hit = j
                    break
        if hit is not None:
            used.add(hit)
            matched_page_indices.add(i)
            matched[hit] = page

    missing: list[dict] = []
    for i, item in enumerate(target_outline):
        page = matched.get(i)
        if page is None:
            item["status"] = "missing"
            item["error"] = "本轮未找到对应成品页"
            missing.append({"page_id": item.get("page_id"), "order": i + 1, "title": item.get("title")})
        else:
            item["status"] = "generated"
            item["svg_file"] = page.get("name") or ""
            item["actual_title"] = page.get("title") or ""
            item["error"] = ""

    extra = [p for i, p in enumerate(pages) if i not in matched_page_indices]
    # 用户主动新增的页：并入契约，避免 extra 被当成错误反复重做。
    for page in extra:
        target_outline.append({
            "page_id": "",
            "order": 0,
            "title": str(page.get("title") or page.get("name") or "新增页")[:120],
            "kind": "content",
            "key_points": "",
            "status": "generated",
            "svg_file": page.get("name") or "",
            "actual_title": page.get("title") or "",
            "error": "",
        })
    # 用户明确要求删页：接受页数减少并收缩契约，不再把删掉的页补回来。
    user_deleted = any(k in (message or "") for k in ("删", "去掉", "移除", "删掉"))
    wants_fill = any(
        k in (message or "") for k in ("补齐", "补全", "缺页", "页数不对", "继续修复", "补页")
    ) or (not user_deleted and bool(_target_from_message(message or "")))
    if user_deleted and not wants_fill:
        target_outline = [x for x in target_outline if x.get("status") != "missing"]
        missing = []
    _renumber_outline(target_outline)
    target_count = len(target_outline)
    remaining_missing = [x for x in target_outline if x.get("status") != "generated"]

    aligned = not remaining_missing and len(pages) == target_count
    status = "exported" if aligned and pptx_url else ("needs_patch" if pages or target_count else task.status)
    task = crud.update_task(
        db, task,
        outline=target_outline,
        target_page_count=target_count,
        current_page_count=len(pages),
        current_pptx_url=pptx_url or task.current_pptx_url,
        skill_name=skill_name or task.skill_name,
        project_key=project_key or task.project_key,
        status=status,
        last_build_id=uuid.uuid4().hex[:16],
        last_error="" if aligned else f"缺 {len(remaining_missing)} 页 / 多 {len(extra)} 页",
    )
    crud.add_event(db, task_id=task.id, action="build.sync", detail={
        "target": target_count, "current": len(pages), "aligned": aligned,
        "missing": remaining_missing[:20], "extra": len(extra), "pptx": bool(pptx_url),
        "user_deleted": user_deleted,
    })
    return validate(task)


def validate(task: AgentPptTask) -> dict:
    outline = list(task.outline or [])
    missing = [
        {"page_id": x.get("page_id"), "order": i + 1, "title": x.get("title")}
        for i, x in enumerate(outline) if x.get("status") != "generated"
    ]
    return {
        "aligned": not missing and int(task.current_page_count or 0) == int(task.target_page_count or 0),
        "target_page_count": int(task.target_page_count or 0),
        "current_page_count": int(task.current_page_count or 0),
        "missing": missing,
        "status": task.status,
        "project_key": task.project_key,
        "pptx_url": task.current_pptx_url,
    }


def contract_block(task: AgentPptTask | None) -> str:
    if task is None:
        return ""
    v = validate(task)
    lines = [
        "【PPT 任务契约（唯一事实源，禁止偏离）】",
        f"- 目标页数：{v['target_page_count']}；当前成品：{v['current_page_count']} 页；状态：{task.status}",
        f"- 当前项目：{task.project_key or '（尚未定位，沿用本会话已有项目）'}",
        f"- 标题：{task.title or '-'}；主题：{task.theme or 'brand'}",
    ]
    if v["missing"]:
        lines.append(
            "- 缺失页：" + "；".join(
                f"第{m['order']}页《{m['title']}》" for m in v["missing"][:30]
            )
        )
        lines.append(
            "规则：用户说「补齐/补全/还差几页」时，只补上述缺失页；未改页保持不动；"
            "禁止另起新项目、禁止从头重写整份。"
        )
    else:
        lines.append("- 页数已对齐。用户要求改页时只改指定页；未改页保持不动。")
    lines.append(
        "规则：build 后必须核对页数=目标页数；若不一致，先补缺失页再回复，不能把缺页成品当成功交付。"
    )
    return "\n".join(lines)


def repair_prompt(task: AgentPptTask, *, message: str = "") -> str:
    v = validate(task)
    if v["aligned"]:
        return ""
    missing = v["missing"]
    hint = ""
    if missing:
        hint = "缺失页：" + "；".join(
            f"第{m['order']}页《{m['title']}》" for m in missing[:30]
        )
    return (
        "【契约补齐任务】上一轮 build 后页数与契约不一致。\n"
        f"目标 {v['target_page_count']} 页，实际 {v['current_page_count']} 页。{hint}\n"
        f"项目：{task.project_key or '本会话当前项目'}。\n"
        "请只补齐缺失页（write_skill_file 写入对应 svg，命名用「插入位置序号+描述」），"
        "未改页保持不动，然后 run_skill_script build；不要新建项目、不要重写整份。"
        f"用户原始诉求：{message[:600]}"
    )


def skill_hint(task: AgentPptTask | None) -> dict:
    if task is None:
        return {}
    return {"skill_id": task.skill_id, "skill_name": task.skill_name, "project_key": task.project_key}


def target_page_count_from_text(message: str) -> int | None:
    """从用户消息里解析显式页数（如「20 页/20页/20p」）；无显式页数返回 None。"""
    return _target_from_message(message or "")


def pages_from_outcome(outcome) -> tuple[list[dict], str, str, str]:
    """对外暴露工具轨迹里的成品页清单/pptx 地址/技能名/项目路径。

    用于「没有契约但已出片」的运行补写观测指标，避免页面明明生成、
    后台 PPT 页数对齐却一直是 0。
    """
    return _steps_pages(outcome)


__all__ = [
    "ensure_contract",
    "sync_from_outcome",
    "validate",
    "contract_block",
    "repair_prompt",
    "skill_hint",
    "target_page_count_from_text",
    "pages_from_outcome",
]

