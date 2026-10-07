"""Agent 工作台 API：注册表 / 会话 / 消息 / 记忆 / 统一流式对话。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.crud import agent as agent_crud
from app.crud import knowledge as knowledge_crud
from app.crud import report as report_crud
from app.models.user import User
from app.services import agent_chat, agent_memory, agent_planner, agent_registry, llm, ppt_chat
from app.services import rag as rag_service

router = APIRouter(prefix="/agents", tags=["agents"])


class ConversationCreate(BaseModel):
    agent_id: str
    context_ref: dict = {}
    title: str = "新的对话"


class ConversationUpdate(BaseModel):
    title: str | None = None
    rag_enabled: bool | None = None
    stage: str | None = None
    pinned: bool | None = None
    context_ref: dict | None = Field(default=None, description="工作台内直接更换素材（报告/班级）")


@router.get("")
def list_agents():
    return {"items": agent_registry.AGENTS}


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = agent_crud.list_conversations(db, owner_id=user.id)
    return {
        "items": [
            {
                "id": str(c.id),
                "agent_id": c.agent_id,
                "context_ref": c.context_ref,
                "title": c.title,
                "rag_enabled": c.rag_enabled,
                "stage": c.stage,
                "pinned": c.pinned,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in items
        ]
    }


@router.post("/conversations")
def create_conversation(
    body: ConversationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if agent_registry.get_agent(body.agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    conv = agent_crud.create_conversation(
        db, owner_id=user.id, agent_id=body.agent_id, context_ref=body.context_ref, title=body.title,
        # 智能助手默认开启知识库引用（RAG 问答是其核心能力）
        rag_enabled=(body.agent_id == "assistant"),
    )
    return {"id": str(conv.id), "agent_id": conv.agent_id, "title": conv.title}


@router.get("/conversations/{conv_id}/messages")
def conversation_messages(conv_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = agent_crud.get_conversation(db, conv_id=conv_id, owner_id=user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    msgs = agent_crud.list_messages(db, conversation_id=conv.id)
    return {
        "conversation": {
            "id": str(conv.id),
            "agent_id": conv.agent_id,
            "title": conv.title,
            "context_ref": conv.context_ref,
            "stage": conv.stage,
        },
        "items": [
            {
                "id": str(m.id), "role": m.role, "content": m.content,
                "citations": m.citations, "options": m.options, "spec": m.spec,
            }
            for m in msgs
        ],
    }


@router.post("/conversations/{conv_id}/share")
def share_conversation(conv_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """生成（或复用）只读分享链接：任何人凭链接可查看该会话全文。"""
    conv = agent_crud.get_conversation(db, conv_id=conv_id, owner_id=user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if not conv.share_token:
        conv = agent_crud.update_conversation(db, conv, share_token=uuid.uuid4().hex)
    return {"token": conv.share_token, "path": f"/share/{conv.share_token}"}


@router.get("/share/{token}")
def read_shared_conversation(token: str, db: Session = Depends(get_db)):
    """公开只读分享页：无需登录；仅返回标题与消息正文（不含 options/spec 等内部结构）。"""
    conv = agent_crud.get_conversation_by_share(db, token=token)
    if conv is None:
        raise HTTPException(status_code=404, detail="分享链接无效或已失效")
    msgs = agent_crud.list_messages(db, conversation_id=conv.id)
    return {
        "title": conv.title,
        "agent_id": conv.agent_id,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "items": [{"role": m.role, "content": m.content} for m in msgs],
    }


@router.patch("/conversations/{conv_id}")
def patch_conversation(
    conv_id: uuid.UUID,
    body: ConversationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = agent_crud.get_conversation(db, conv_id=conv_id, owner_id=user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    conv = agent_crud.update_conversation(
        db, conv, title=body.title, rag_enabled=body.rag_enabled, stage=body.stage,
        pinned=body.pinned, context_ref=body.context_ref,
    )
    return {
        "id": str(conv.id), "title": conv.title, "rag_enabled": conv.rag_enabled,
        "stage": conv.stage, "pinned": conv.pinned, "context_ref": conv.context_ref,
    }


class PptBuildIn(BaseModel):
    title: str | None = None
    theme: str | None = None
    outline: list[dict] | None = Field(
        default=None, description="人工审核后的大纲（缺省用会话最新规格）"
    )
    sections: list[dict] | None = Field(
        default=None, description="人工审核后的文案（缺省用会话最新规格）"
    )


def _latest_spec(db: Session, conv_id: uuid.UUID) -> dict:
    """会话规格合并：按时间倒序逐条回填 outline/sections/theme（新者优先）。

    大纲阶段与文案阶段产出在不同消息里，只取最新一条会导致另一半丢失
    （如文案消息没有 outline，生成时就会报"还没有可用大纲"）。
    """
    merged: dict = {}
    for m in reversed(agent_crud.list_messages(db, conversation_id=conv_id)):
        if m.role != "assistant" or not m.spec:
            continue
        spec = m.spec
        for key in ("outline", "sections", "theme", "slides"):
            if key not in merged and spec.get(key):
                merged[key] = spec[key]
        if all(merged.get(k) for k in ("outline", "sections")):
            break
    return merged


def _report_ids_from_ref(ref: dict) -> list[str]:
    """会话 context_ref → 报告 id 列表：兼容单选(id/report_id)与多选(ids/reports)。"""
    ids: list[str] = []
    raw_ids = ref.get("ids")
    if isinstance(raw_ids, list):
        ids = [str(x) for x in raw_ids if x]
    if not ids and isinstance(ref.get("reports"), list):
        ids = [str(r.get("id")) for r in ref["reports"] if isinstance(r, dict) and r.get("id")]
    if not ids:
        single = ref.get("id") or ref.get("report_id")
        if single:
            ids = [str(single)]
    seen: set[str] = set()
    return [x for x in ids if not (x in seen or seen.add(x))]


def _load_reports(db: Session, ref: dict) -> list:
    out = []
    for rid in _report_ids_from_ref(ref):
        try:
            rep = report_crud.get(db, uuid.UUID(rid))
        except ValueError:
            rep = None
        if rep is not None:
            out.append(rep)
    return out


def _tool_trace(plan_outcome) -> list[dict]:
    """规划层调用轨迹 → 可持久化/可展示的精简结构（整条裁剪，避免截断成半行）。"""
    trace: list[dict] = []
    for i, s in enumerate(plan_outcome.steps):
        summary = agent_planner.compact_result(s.result, 900) if s.ok else ""
        trace.append({
            "seq": i + 1,
            "tool": s.tool,
            "args": s.args,
            "ok": s.ok,
            "summary": summary,
            "error": None if s.ok else (s.error or "执行失败"),
        })
    return trace


def _fmt_period(start, end) -> str:
    """素材周期展示：只到日期（2026-07-01 ~ 2026-09-30），不带时分秒时区。"""
    def _d(v):
        if v is None:
            return ""
        try:
            return v.strftime("%Y-%m-%d")
        except AttributeError:
            return str(v).split(" ")[0][:10]
    s, e = _d(start), _d(end)
    if s and e:
        return f"{s} ~ {e}"
    return s or e


@router.get("/conversations/{conv_id}/material")
def conversation_material(
    conv_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """工作区素材：会话绑定的报告/班级评估（用了哪些数据，一目了然）。"""
    conv = agent_crud.get_conversation(db, conv_id=conv_id, owner_id=user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    ref = conv.context_ref or {}
    out: dict = {"agent_id": conv.agent_id, "context_ref": ref, "items": []}
    if conv.agent_id == "report_ppt":
        for rep in _load_reports(db, ref):
            stats = rep.stats or {}
            out["items"].append({
                "kind": "report", "id": str(rep.id), "title": rep.title, "type": rep.type,
                "period": _fmt_period(rep.period_start, rep.period_end),
                "stat_keys": sorted(stats.keys())[:12], "stat_count": len(stats),
            })
    else:
        class_id = ref.get("class_id") or ref.get("id")
        if class_id:
            try:
                from app.models.enrollment import Class

                cls = db.get(Class, uuid.UUID(str(class_id)))
            except ValueError:
                cls = None
            if cls is not None:
                ref_period = str(ref.get("period") or "")
                if not ref_period and (ref.get("period_start") or ref.get("period_end")):
                    ref_period = _fmt_period(ref.get("period_start"), ref.get("period_end"))
                out["items"].append({
                    "kind": "class", "id": str(cls.id), "title": cls.name,
                    "period": ref_period or str(ref.get("title") or ""),
                })
    if not out["items"] and ref:
        out["items"].append({"kind": "context", "title": str(ref.get("title") or "业务上下文"), "id": ""})
    return out


@router.post("/conversations/{conv_id}/build-ppt")
def conversation_build_ppt(
    conv_id: uuid.UUID, body: PptBuildIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """工作台一键生成 PPT：以会话最新规格（或人工审核后的大纲）构建 .pptx 并返回下载地址。"""
    from datetime import UTC, datetime

    from app.services import pptx_builder

    conv = agent_crud.get_conversation(db, conv_id=conv_id, owner_id=user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if agent_registry.get_agent(conv.agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    spec = _latest_spec(db, conv.id)
    outline = body.outline if body.outline is not None else spec.get("outline") or []
    sections = body.sections if body.sections is not None else spec.get("sections") or []
    if not outline and sections:
        outline = [
            {"id": str(s.get("id") or f"p{i + 1}"), "title": str(s.get("title") or f"第 {i + 1} 页"), "kind": "bullets"}
            for i, s in enumerate(sections) if isinstance(s, dict)
        ]
    if not outline:
        raise HTTPException(status_code=400, detail="会话中还没有可用大纲：请先走完大纲阶段，或在工作区编辑大纲")
    theme = (body.theme or spec.get("theme") or "brand").strip().lower()
    if theme not in ("brand", "cyan", "deep"):
        theme = "brand"

    by_id = {str(s.get("id")): s for s in sections if isinstance(s, dict)}
    by_title = {str(s.get("title")): s for s in sections if isinstance(s, dict)}
    valid_kinds = ("cover", "stats", "table", "bar", "bullets", "prose", "end")

    # 报告真实数据（统计快照 + 逐月明细）：先取数，后面数据类版式直接用数画图
    stats: dict = {}
    period_label = ""
    monthly: list[dict] = []
    breakdown: list[dict] | None = None
    if conv.agent_id == "report_ppt":
        ref = conv.context_ref or {}
        reps = _load_reports(db, ref)
        if reps:
            mat = ppt_chat.combined_report_material(db, reps)
            stats = mat.get("stats") or {}
            monthly = mat.get("monthly") or []
            breakdown = mat.get("breakdown") or None
            if reps[0].period_start:
                period_label = _fmt_period(reps[0].period_start, reps[0].period_end)
    if breakdown is None and monthly:
        breakdown = [
            {"month": m.get("month"), "consumed_lessons": m.get("consumed_lessons"),
             "expected_lessons": m.get("expected_lessons")}
            for m in monthly if isinstance(m, dict)
        ] or None

    slides: list[dict] = []
    for i, o in enumerate(outline):
        if not isinstance(o, dict):
            continue
        title = str(o.get("title") or f"第 {i + 1} 页")
        kind = str(o.get("kind") or "bullets")
        if kind not in valid_kinds:
            kind = "bullets"
        sec = by_id.get(str(o.get("id"))) or by_title.get(title) or {}
        body_text = sec.get("body") if isinstance(sec, dict) else None
        note_text = str(o.get("note") or "")
        # 数据类版式优先用真实数据画图；实在无数据才降级为要点卡，保证不丢页
        if kind == "stats":
            cards = _stat_cards_from_stats(stats)
            if cards:
                slides.append({"title": title, "kind": "stats", "kicker": f"PART {i + 1:02d}", "cards": cards})
                continue
            kind = "bullets"
        elif kind == "table":
            rows = _stat_rows_from_stats(stats)
            if rows:
                slides.append({
                    "title": title, "kind": "table", "kicker": f"PART {i + 1:02d}",
                    "headers": ["指标", "数值", "说明"], "rows": rows,
                    "widths": [0.34, 0.30, 0.36], "aligns": ["center", "center", "center"],
                    "note": "来源：报告已保存统计快照",
                })
                continue
            kind = "bullets"
        elif kind == "bar":
            trend = _trend_from_monthly(monthly)
            if trend.get("labels"):
                slides.append({"title": title, "kind": "bar", "kicker": f"PART {i + 1:02d}", **trend})
                continue
            kind = "bullets"
        slide: dict = {"title": title, "kind": kind, "kicker": f"PART {i + 1:02d}"}
        if kind == "prose":
            slide["text"] = str(body_text or note_text or "")
        else:
            if isinstance(body_text, list):
                slide["items"] = [str(x) for x in body_text]
            else:
                slide["items"] = str(body_text or note_text or title)
        slides.append(slide)
    title = (body.title or conv.title or "工作汇报").strip() or "工作汇报"
    ppt_url = pptx_builder.build_custom_ppt(
        title=title, period_label=period_label,
        teacher_name=user.name or "教师", created_at=datetime.now(UTC),
        stats=stats, breakdown=breakdown, slides=slides, theme=theme,
    )
    # 页数必须与文件实际一致：构建器会跳过空页并注入数据总览页，直接数文件
    pages = len(slides) + 2
    try:
        from pptx import Presentation as _PptxReader

        from app.core.config import get_settings

        _path = Path(get_settings().UPLOAD_DIR) / ppt_url
        pages = len(_PptxReader(str(_path)).slides)
    except Exception:
        pass
    return {"ppt_url": ppt_url, "download": f"/uploads/{ppt_url}", "pages": pages, "theme": theme}


def _stat_cards_from_stats(stats: dict) -> list[list]:
    """报告统计快照 → stats 版式 cards（label, value, unit），无有效数据返回空。"""
    s = stats or {}
    num = lambda k: s.get(k) or 0  # noqa: E731
    cards = [
        ["当前学员", f"{num('current_students')}", "人"],
        ["上课人次", f"{num('attended')}", "人次"],
        ["消耗课时", f"{num('consumed_lessons')}", "节"],
        ["出勤率", f"{(s.get('attendance_rate') or 0) * 100:.1f}", "%"],
        ["达标率", f"{(s.get('achievement_rate') or 0) * 100:.1f}", "%"],
        ["新增学员", f"{num('new_students')}", "人"],
    ]
    if all(c[1] in ("0", "0.0") for c in cards):
        return []
    return cards


def _stat_rows_from_stats(stats: dict) -> list[list]:
    """报告统计快照 → table 版式 rows（指标/数值/说明），全零视为无有效数据。"""
    s = stats or {}
    vals = {
        "current_students": s.get("current_students") or 0,
        "schedules": s.get("schedules") or 0,
        "attended": s.get("attended") or 0,
        "leave": s.get("leave") or 0,
        "attendance_rate": s.get("attendance_rate") or 0,
        "consumed_lessons": s.get("consumed_lessons") or 0,
        "achievement_rate": s.get("achievement_rate") or 0,
        "new_students": s.get("new_students") or 0,
    }
    if all(float(v or 0) == 0 for v in vals.values()):
        return []
    return [
        ["当前学员", f"{vals['current_students']} 人", "期间末在读"],
        ["已完成排课", f"{vals['schedules']} 节", "期间已完成"],
        ["上课人次", f"{vals['attended']} 人次", "已到考勤"],
        ["缺课人次", f"{vals['leave']} 人次", "请假考勤"],
        ["出勤率", f"{vals['attendance_rate'] * 100:.1f}%", "上课/应到"],
        ["消耗课时", f"{vals['consumed_lessons']} 节", "已到×2"],
        ["达标率", f"{vals['achievement_rate'] * 100:.1f}%", "消耗/应耗"],
        ["新增学员", f"{vals['new_students']} 人", "期间新建"],
    ]


def _trend_from_monthly(monthly: list[dict]) -> dict:
    """逐月明细 → bar 版式（消耗 vs 应耗），不足 2 个月返回空。"""
    rows = [m for m in (monthly or []) if isinstance(m, dict) and m.get("month")]
    if len(rows) < 2:
        return {}
    return {
        "labels": [str(m.get("month") or "") for m in rows],
        "consumed": [int(m.get("consumed_lessons") or 0) for m in rows],
        "expected": [int(m.get("expected_lessons") or 0) for m in rows],
        "note": "消耗 vs 应耗课时（来源：已保存快照）",
    }


# 各 Agent 路线图顺序：用于从模型实际产出反推进度（只前进不后退）
STAGE_ORDER: dict[str, list[str]] = {
    "report_ppt": ["data", "outline", "outline_confirm", "copy", "theme", "layout", "layout_confirm", "export"],
    "class_parent_ppt": [
        "data", "style", "title", "outline", "outline_confirm",
        "focus", "suggestion", "theme", "layout", "export",
    ],
    "assistant": ["chat"],
}


def _infer_stage(agent_id: str, current: str, options: list[dict], spec: dict) -> str:
    """路线图对齐：模型一次可能推进多步（如直接给大纲+排版建议），
    按 options/spec 反推本轮实际到达的阶段；绝不回退，避免对话与路线图打架。"""
    order = STAGE_ORDER.get(agent_id) or []
    if not order:
        return current
    try:
        best = order.index(current)
    except ValueError:
        best = 0

    def _opt_stage(o: dict) -> str | None:
        if not isinstance(o, dict):
            return None
        raw = o.get("action")
        nested = raw if isinstance(raw, dict) else {}
        for cand in (o.get("stage"), nested.get("stage")):
            if isinstance(cand, str) and cand in order:
                return cand
        act = raw if isinstance(raw, str) else nested.get("type")
        if act == "build_ppt":
            return "export"
        return None

    for o in options or []:
        s = _opt_stage(o)
        if s is not None:
            best = max(best, order.index(s))
    if isinstance(spec.get("outline"), list) and spec["outline"]:
        for key in ("outline_confirm", "outline"):
            if key in order:
                best = max(best, order.index(key))
                break
    if isinstance(spec.get("sections"), list) and spec["sections"]:
        # 文案已出：报告线进入主题，家长会线进入侧重
        for key in ("theme", "focus", "copy"):
            if key in order:
                best = max(best, order.index(key))
                break
    return order[best]


@router.delete("/conversations/{conv_id}")
def remove_conversation(conv_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conv = agent_crud.get_conversation(db, conv_id=conv_id, owner_id=user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    agent_crud.delete_conversation(db, conv)
    return {"ok": True}


@router.get("/memories")
def list_memories(agent_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = agent_crud.list_memories(db, owner_id=user.id, agent_id=agent_id)
    return {"items": [{"id": str(m.id), "key": m.key, "value": m.value} for m in items]}


@router.delete("/memories/{memory_id}")
def remove_memory(memory_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ok = agent_crud.delete_memory(db, memory_id=memory_id, owner_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True}


class ConversationChatIn(BaseModel):
    stage: str = "chat"
    message: str = ""
    state: dict = {}
    use_rag: bool | None = Field(default=None, description="单条消息临时切换 RAG；缺省跟随会话开关")
    config_id: str | None = Field(default=None, description="Agent工作台切换模型：指定配置ID")


@router.post("/conversations/{conv_id}/chat")
def conversation_chat(
    conv_id: uuid.UUID,
    body: ConversationChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """统一流式对话：对话 + 可执行 options + phase，自动持久化消息并注入长短期记忆。

    事件格式与报告 ppt-chat 一致：phase / delta / done / error。
    """
    conv = agent_crud.get_conversation(db, conv_id=conv_id, owner_id=user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if agent_registry.get_agent(conv.agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    from app.services import llm_context as _llm_ctx

    try:
        resolved = _llm_ctx.resolve_override(db, user.id, "agent", body.config_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except llm.LLMConfigError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    state = body.state or {}
    message = body.message or ""
    context_ref = conv.context_ref or {}

    # 会话 stage：前端按路线图推进（缺省沿用会话当前 stage）
    stage_keys = [s.get("key") for s in (agent_registry.get_agent(conv.agent_id) or {}).get("stages", [])]
    stage = body.stage if body.stage in stage_keys else (conv.stage if conv.stage in stage_keys else "chat")
    if stage != conv.stage:
        conv = agent_crud.update_conversation(db, conv, stage=stage)
    prompt_stage = agent_chat.prompt_stage_for(conv.agent_id, stage)

    # 报告 Agent 需要报告素材；家长会 Agent 用 context_ref 即可
    material: dict | None = None
    if conv.agent_id == "report_ppt":
        reps = _load_reports(db, context_ref)
        if reps:
            material = ppt_chat.combined_report_material(db, reps)

    mem_ctx = agent_memory.build_memory_context(db, owner_id=user.id, agent_id=conv.agent_id, conversation_id=conv.id)
    mem_block = agent_memory.memory_prompt_block(mem_ctx)
    # RAG：会话开关默认关；单条消息可临时切换；关闭时不检索不注入
    agent_info = agent_registry.get_agent(conv.agent_id) or {}
    want_rag = body.use_rag if body.use_rag is not None else bool(conv.rag_enabled)
    citations: dict | None = None
    if want_rag and agent_info.get("supports_rag") and message.strip():
        try:
            # 寒暄类消息跳过检索：省一次向量化，首字更快
            if rag_service.needs_retrieval(message.strip()):
                collected = knowledge_crud.collected_doc_ids(db, user_id=user.id)
                # 压入教师个人配置：检索向量化走自配 embedding 模型
                with _llm_ctx.use_llm(resolved):
                    hits = rag_service.retrieve(
                        message.strip(), db=db, owner_id=user.id, collected_ids=collected
                    )
            if hits:
                citations = {"hits": hits}
                lines = [
                    f"- 《{h['title']}》（相似度 {h['similarity']}）：{h['text'][:200]}"
                    for h in hits
                ]
                rag_block = (
                    "【知识库引用片段】\n" + "\n".join(lines)
                    + "\n回答时优先依据上述片段，并在末尾给出引用来源。"
                )
                mem_block = (mem_block + "\n\n" + rag_block).strip() if mem_block else rag_block
        except Exception:
            pass
    # 智能助手：多轮规划层执行只读业务工具（排课考勤/教学数据/班级/学员/评估）。
    # 规划→执行→观察，带预算护栏与降级；非业务问题或失败时静默跳过，不影响流式回答。
    plan_outcome = agent_planner.PlanOutcome()
    if conv.agent_id == "assistant" and message.strip():
        try:
            plan_outcome = agent_planner.plan_and_run(db, user, message.strip())
            if plan_outcome.block:
                mem_block = (mem_block + "\n\n" + plan_outcome.block).strip() if mem_block else plan_outcome.block
        except Exception:
            plan_outcome = agent_planner.PlanOutcome()
    tool_names = plan_outcome.tools
    system, prompt = agent_chat.build_unified_prompt(
        agent_id=conv.agent_id,
        stage=prompt_stage,
        user_message=message,
        state=state,
        context_ref=context_ref,
        memory_block=mem_block,
        material=material,
    )
    if message.strip():
        agent_crud.add_message(db, conversation_id=conv.id, role="user", content=message.strip())

    def _frame(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    def event_stream():
        # 最外层兜底：任何未预期异常都必须以 error 帧结束，绝不能让前端无限卡"接收中"
        try:
            with _llm_ctx.use_llm(resolved):
                yield from _run_stream()
        except Exception as e:  # noqa: BLE001
            try:
                yield _frame({"error": llm.friendly_llm_error(e)})
            except Exception:
                pass

    def _run_stream():
        import queue
        import threading
        import time as _time

        full = ""
        try:
            yield _frame({"phase": {"key": "read", "label": "读取会话与记忆"}})
            if tool_names:
                used = "、".join(dict.fromkeys(tool_names))
                yield _frame({"phase": {"key": "tools", "label": f"查询业务数据（{used}）"}})
            yield _frame({"phase": {"key": "analyze", "label": "组装上下文"}})
            yield _frame({"phase": {"key": "model", "label": "AI 模型生成中"}})
            # 生产者线程拉 LLM 流，主循环带心跳消费：
            # 模型持续出字 → delta 照常；网关缓冲导致长静默 → 每 15s 一个存活心跳，
            # 前端据此区分"还在生成"与"连接已死"，长文（年度总结）不再被误杀
            box: queue.Queue = queue.Queue()

            def _produce():
                # 线程不继承 contextvar，在此重新压入教师个人配置
                with _llm_ctx.use_llm(resolved):
                    try:
                        for chunk in llm.stream_text(system, prompt):
                            box.put(("delta", chunk))
                        box.put(("end", None))
                    except Exception as e:  # noqa: BLE001
                        box.put(("error", e))

            t0 = _time.monotonic()
            threading.Thread(target=_produce, daemon=True).start()
            started = False
            while True:
                try:
                    kind, payload = box.get(timeout=15)
                except queue.Empty:
                    elapsed = int(_time.monotonic() - t0)
                    if elapsed > 600:
                        yield _frame({"error": "AI 生成超时（超过 10 分钟无结果），请缩短问题或稍后重试"})
                        return
                    # 存活心跳：仍在等模型，前端看门狗据此续命，并展示已用时长
                    yield _frame({"phase": {"key": "stream", "label": f"持续生成中（已用 {elapsed} 秒）"}})
                    continue
                if kind == "error":
                    raise payload
                if kind == "end":
                    break
                if not started:
                    started = True
                    yield _frame({"phase": {"key": "stream", "label": "接收并整理结果"}})
                full += payload
                yield _frame({"delta": payload})
        except Exception as e:  # noqa: BLE001
            yield _frame({"error": llm.friendly_llm_error(e)})
            return
        # 持久化助手回复 + 异步增量提炼长期记忆（不阻塞流式）
        options = agent_chat.extract_options(full)
        spec = agent_chat.extract_spec(full)
        final_stage = _infer_stage(conv.agent_id, stage, options, spec)
        # 工具调用轨迹：随 citations 持久化（免迁移），前端在气泡下方可收起展开
        tool_trace = _tool_trace(plan_outcome)
        msg_citations: dict | None = citations
        if tool_trace:
            msg_citations = dict(msg_citations or {})
            msg_citations["tools"] = tool_trace
            msg_citations["rounds"] = plan_outcome.rounds
            msg_citations["degraded"] = plan_outcome.degraded
        # 首轮问答后自动拟标题：默认标题才改，用户改过的保持不动
        auto_title: str | None = None
        if (conv.title or "新的对话") == "新的对话" and message.strip():
            auto_title = message.strip().replace("\n", " ")[:16]
        try:
            agent_crud.add_message(
                db, conversation_id=conv.id, role="assistant", content=full,
                citations=msg_citations, options=options or None, spec=spec or None,
            )
            updates: dict = {}
            if final_stage != conv.stage:
                updates["stage"] = final_stage
            if auto_title:
                updates["title"] = auto_title
            if updates:
                agent_crud.update_conversation(db, conv, **updates)
            else:
                agent_crud.touch_conversation(db, conv)
        except Exception:
            pass
        try:
            agent_memory.distill_async(user.id, conv.agent_id, conv.id, message, full)
        except Exception:
            pass
        yield _frame({
            "done": True, "stage": final_stage, "options": options,
            "has_spec": bool(spec), "title": auto_title,
            "tools": list(dict.fromkeys(tool_names)) if tool_names else [],
            "tool_trace": tool_trace,
            "tool_rounds": plan_outcome.rounds,
            "tool_degraded": plan_outcome.degraded,
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
