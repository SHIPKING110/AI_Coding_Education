"""Agent 工作台 API：注册表 / 会话 / 消息 / 记忆 / 统一流式对话。"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.crud import agent as agent_crud
from app.crud import knowledge as knowledge_crud
from app.crud import report as report_crud
from app.models.user import User
from app.services import agent_chat, agent_memory, agent_planner, agent_registry, agent_tools, llm, ppt_chat
from app.services import rag as rag_service

router = APIRouter(prefix="/agents", tags=["agents"])

logger = logging.getLogger(__name__)


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
def list_agents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"items": agent_registry.list_for_owner(db, user.id)}


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
    if agent_registry.resolve_agent(db, user.id, body.agent_id) is None:
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
                "id": str(m.id), "role": m.role,
                # 历史里可能残留旧版本的工具调用标记乱码：读取时统一净化
                "content": llm.strip_toolcall_markup(m.content) if m.role == "assistant" else m.content,
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
    # 历史里可能残留旧版本产生的原生工具调用标记（乱码）：分享页统一净化
    return {
        "title": conv.title,
        "agent_id": conv.agent_id,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "items": [
            {"role": m.role, "content": llm.strip_toolcall_markup(m.content) if m.role == "assistant" else m.content}
            for m in msgs
        ],
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


def _class_eval_block(db: Session, user: User, context_ref: dict, max_chars: int = 3000) -> str:
    """绑定班级 → 学员评估正文自动注入对话上下文。

    素材 tab 绑定班级后，每条对话自动携带该班学员最新评估摘要/评语，
    Agent 无需再调工具就能直接引用；超长按学员整条裁剪。
    """
    class_id = (context_ref or {}).get("class_id") or (context_ref or {}).get("id")
    if not class_id:
        return ""
    try:
        from sqlalchemy.orm import selectinload

        from app.models.enrollment import Class
        from app.models.evaluation import Evaluation
        from app.models.user import Role

        cls = db.get(Class, uuid.UUID(str(class_id)), options=[selectinload(Class.students)])
    except (ValueError, AttributeError):
        return ""
    if cls is None:
        return ""
    if getattr(user, "role", None) == getattr(__import__("app.models.user", fromlist=["Role"]), "Role").TEACHER:
        if str(getattr(cls, "teacher_id", "") or "") != str(user.id):
            return ""
    try:
        from sqlalchemy import select

        from app.models.evaluation import EvaluationStatus

        ev_stmt = select(Evaluation).order_by(Evaluation.updated_at.desc())
        if str(getattr(user, "role", "")) == "teacher":
            ev_stmt = ev_stmt.where(Evaluation.teacher_id == user.id)
        latest: dict = {}
        for ev in db.scalars(ev_stmt).unique().all():
            latest.setdefault(ev.student_id, ev)
    except Exception:
        return ""
    lines: list[str] = []
    for s in sorted(getattr(cls, "students", []) or [], key=lambda x: x.name):
        ev = latest.get(s.id)
        if ev is None:
            lines.append(f"- {s.name}：暂无评估")
            continue
        c = ev.content or {}
        summary = str(c.get("summary") or c.get("comment") or "")[:160]
        to_improve = str(c.get("to_improve") or "")[:80]
        seg = f"- {s.name}（{ev.period_start}~{ev.period_end}）：{summary}"
        if to_improve:
            seg += f"；待改进：{to_improve}"
        lines.append(seg)
    if not lines:
        return ""
    head = f"【绑定班级·学员评估】班级《{cls.name}》（共 {len(lines)} 人，最新评估摘要如下，回答班级/学员问题时直接引用）"
    body = head + "\n" + "\n".join(lines)
    if len(body) > max_chars:
        # 按学员整条裁剪
        kept = [head]
        for ln in lines:
            if len("\n".join(kept) + "\n" + ln) > max_chars:
                break
            kept.append(ln)
        kept.append(f"…另有 {len(lines) - (len(kept) - 1)} 人未列出")
        body = "\n".join(kept)
    return body


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


_REPORT_TYPE_CN = {
    "daily": "日报", "weekly": "周报", "monthly": "月报",
    "quarterly": "季度总结", "yearly": "年度总结",
}


def _report_snippet(rep) -> str:
    """报告正文摘要（供素材卡片与对话注入的共用短文本）。"""
    c = rep.content or {}
    parts: list[str] = []
    for key, label in (
        ("summary", "总结"), ("work", "工作"), ("highlights", "亮点"),
        ("problems", "问题"), ("plan", "计划"), ("next_plan", "下阶段"),
    ):
        val = str(c.get(key) or "").strip()
        if val:
            parts.append(f"{label}：{val}")
    return "；".join(parts)


def _report_block(db: Session, ref: dict, max_chars: int = 4000) -> str:
    """绑定报告 → 报告正文自动注入对话上下文。

    素材 tab 绑定「报告总结」的报告后，每条对话自动携带该报告已保存的正文摘要，
    Agent 无需再调工具即可直接引用；超长按报告整条裁剪。
    """
    reps = _load_reports(db, ref)
    if not reps:
        return ""
    lines: list[str] = []
    for rep in reps:
        type_cn = _REPORT_TYPE_CN.get(str(rep.type), str(rep.type))
        period = _fmt_period(rep.period_start, rep.period_end)
        snippet = _report_snippet(rep)
        seg = f"- 《{rep.title or '未命名报告'}》（{type_cn}·{period}）：{snippet or '（无正文）'}"
        lines.append(seg)
    head = f"【绑定报告·正文摘要】已绑定 {len(reps)} 份报告，回答相关问题直接引用："
    body = head + "\n" + "\n".join(lines)
    if len(body) > max_chars:
        kept = [head]
        for ln in lines:
            if len("\n".join(kept) + "\n" + ln) > max_chars:
                break
            kept.append(ln)
        kept.append(f"…另有 {len(lines) - (len(kept) - 1)} 份报告未列出")
        body = "\n".join(kept)
    return body


_IMG_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
_DOC_SUFFIXES = {".txt", ".md", ".markdown", ".pdf", ".docx"}


def _attachment_block(attachments: list[dict]) -> str:
    """随消息上传的附件 → 注入对话上下文。

    文档抽取正文（节选）供模型直接参考；图片登记文件名 + 可被 Skill 引用的绝对路径，
    并提示：如需把图片放进 PPT，可先用 write_skill_file 思路 / 让 Skill 脚本读取该路径，
    或把图片写进 Skill 包内资源目录再生成。这样「上传图片 + ppt-master」可以配合使用。
    """
    if not attachments:
        return ""
    from app.core.config import get_settings

    settings = get_settings()
    upload_root = str(Path(settings.UPLOAD_DIR).resolve())
    lines: list[str] = []
    image_hints: list[str] = []
    for a in attachments:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "未命名附件")
        url = str(a.get("url") or "")
        if str(a.get("kind")) == "doc":
            text = str(a.get("text") or "").strip()
            if text:
                lines.append(f"【附件·文档《{name}》内容节选】\n{text[:6000]}")
            else:
                lines.append(f"- 用户上传了文档《{name}》（未能解析出文本，请按文件名理解用途）")
        else:
            # 把 /uploads/... 映射到磁盘绝对路径，供 Skill 脚本读取/嵌入
            disk_path = ""
            if url.startswith("/uploads/"):
                disk_path = str(Path(upload_root) / url[len("/uploads/"):])
            lines.append(
                f"- 用户上传了图片《{name}》"
                + (f"（磁盘路径：{disk_path}，可直接在 Skill 脚本中读取并插入 PPT/文档）" if disk_path else "")
            )
            if disk_path:
                image_hints.append(disk_path)
    if not lines:
        return ""
    img_count = sum(1 for a in attachments if isinstance(a, dict) and str(a.get("kind")) != "doc")
    block = (
        "【用户随消息上传的附件】\n" + "\n".join(lines)
        + "\n请优先结合上述附件内容完成用户的请求；附件内容优先于历史对话。"
    )
    if img_count:
        block += (
            f"\n【重要·须回应附件】用户本次上传了 {img_count} 张图片。"
            "请在回答开头用一句话明确告知「已收到这 N 张图片」并复述图片文件名，"
            "让用户确知附件已被接收；若当前模型无法直接识别图像内容，要如实说明「无法查看图片细节，"
            "请补充文字描述或用图片文件名指代」，不要假装看不见、也不要编造图片内容。"
        )
    if image_hints:
        block += (
            "\n【附件图片可用于生成产物】若用户希望把这些图片放进 PPT/文档：可让 Skill 脚本直接读取上面的"
            "磁盘路径并插入；或用 write_skill_file 把图片相关引用/说明写入 Skill 包内，再由 run_skill_script 生成。"
        )
    return block


def _existing_pptx_block(db, user) -> str:
    """列出当前用户可用 Skill 包内已有的 .pptx 源文件，供「就地二次编辑」定位源文件。

    出现条件：用户已有生成过 PPT（包内存在 projects/**/*.pptx 或 *_outputs/*.pptx）。
    模型据此走 ppt-master 的 Edit Native PPTX 路由（pptx_to_svg --roundtrip → 改页 → svg_to_pptx --roundtrip），
    保留原设计、只重建改动页，而不是从头重做。
    """
    try:
        from app.crud import agent_ext as _ext
        from app.services import skill_bundle as _bundle

        found: list[tuple[str, str]] = []
        for s in _ext.list_skills(db, owner_id=user.id):
            if not s.enabled:
                continue
            has_pptx_file = any(str(f).lower().endswith(".pptx") for f in (s.files or []))
            if not has_pptx_file:
                continue
            desk = _bundle.skill_dir(user.id, s.id)
            for p in desk.rglob("*.pptx"):
                rel = str(p.relative_to(desk)).replace("\\", "/")
                found.append((s.name, rel))
            if len(found) >= 8:
                break
        if not found:
            return ""
        lines = [f"- Skill「{n}」：{rel}" for n, rel in found[:8]]
        return (
            "【当前已有的 PPT 源文件（可用于二次编辑）】\n" + "\n".join(lines)
            + "\n若用户本次是「修改/加页/删页/调顺序/换文字」，请基于上面的 .pptx 源文件走 ppt-master 的"
            "「Edit Native PPTX」路由：pptx_to_svg.py \"<该路径>\" ... --roundtrip 导入 → 只改需要的页 → "
            "svg_to_pptx.py ... --roundtrip 导出；不要重新从头生成整份。若用户要全新主题/整体重做，则走生成路由。"
        )
    except Exception:
        return ""


def _derive_spec_from_tools(plan_outcome) -> dict:
    """从 Skill 工具执行轨迹里提炼 PPT 规格（大纲 + 幻灯片预览），供工作区「大纲/成果」对齐。

    当模型用 ppt-master 之类的 Skill 生成 PPT 时，正文通常不含 ```json 大纲，
    但工具会：
      - write_skill_file 逐页写入 svg（每页一个 .svg 源文件）→ 可据文件名/顺序还原大纲；
      - run_skill_script 产出的 pptx 页数 → 校验大纲页数与成品一致。
    这里把「写入了哪些页」还原成 outline（标题取自 svg 文件名），并附 slides 预览结构，
    让「大纲」的每一页都对得上「成果」里实际生成的幻灯片，SVG 页也能在前端预览。
    """
    svg_pages: list[dict] = []
    seen: set[str] = set()
    for s in plan_outcome.steps:
        if s.tool == "write_skill_file" and s.ok:
            path = str((s.args or {}).get("path") or "")
            if path.lower().endswith(".svg") and path not in seen:
                seen.add(path)
                fname = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                # 文件名多为 "01_cover" / "02_outline" 这类：去掉序号前缀得到标题
                import re as _re

                title = _re.sub(r"^\d+[_\-\s]*", "", fname).strip() or fname
                svg_pages.append({"id": f"p{len(svg_pages) + 1}", "title": title,
                                  "kind": "content", "file": path})
    if not svg_pages:
        return {}
    # 按文件名前缀排序不稳定，这里保持写入顺序（write 顺序即页序）
    outline = [
        {"id": p["id"], "title": p["title"], "kind": ("cover" if i == 0 else "content")}
        for i, p in enumerate(svg_pages)
    ]
    return {"outline": outline, "slides": svg_pages}


def _tool_trace(plan_outcome) -> list[dict]:
    """规划层调用轨迹 → 可持久化/可展示的精简结构（整条裁剪，避免截断成半行）。"""
    trace: list[dict] = []
    for i, s in enumerate(plan_outcome.steps):
        summary = agent_planner.compact_result(s.result, 900) if s.ok else ""
        files: list[dict] = []
        if s.ok and isinstance(s.result, dict):
            raw = s.result.get("生成文件")
            if isinstance(raw, list):
                files = [
                    {"名": f.get("名"), "下载": f.get("下载"), "字节": f.get("字节")}
                    for f in raw if isinstance(f, dict) and f.get("下载")
                ]
        trace.append({
            "seq": i + 1,
            "tool": s.tool,
            "args": s.args,
            "ok": s.ok,
            "summary": summary,
            "files": files,
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
    # 素材按引用内容判定（不再按 Agent 写死）：报告总结的报告与班级评估可同时绑定，任何 Agent 都能用
    for rep in _load_reports(db, ref):
        stats = rep.stats or {}
        out["items"].append({
            "kind": "report", "id": str(rep.id), "title": rep.title or "未命名报告", "type": rep.type,
            "period": _fmt_period(rep.period_start, rep.period_end),
            "stat_keys": sorted(stats.keys())[:12], "stat_count": len(stats),
            "snippet": _report_snippet(rep),
        })
    class_id = ref.get("class_id")
    if not class_id and not _report_ids_from_ref(ref):
        # 兼容旧班级引用：无报告 id 时把顶层 id 视为班级 id
        class_id = ref.get("id")
    if class_id:
        try:
            from sqlalchemy.orm import selectinload

            from app.models.enrollment import Class
            from app.models.evaluation import Evaluation
            from app.models.user import Role

            cls = db.get(Class, uuid.UUID(str(class_id)), options=[selectinload(Class.students)])
        except (ValueError, TypeError):
            cls = None
        if cls is not None and getattr(user, "role", None) == Role.TEACHER:
            if str(getattr(cls, "teacher_id", "") or "") != str(user.id):
                cls = None
        if cls is not None:
            ref_period = str(ref.get("period") or "")
            if not ref_period and (ref.get("period_start") or ref.get("period_end")):
                ref_period = _fmt_period(ref.get("period_start"), ref.get("period_end"))
            students = sorted(getattr(cls, "students", []) or [], key=lambda x: x.name)
            done = 0
            try:
                from sqlalchemy import select

                from app.models.evaluation import EvaluationStatus

                ev_stmt = select(Evaluation.student_id, Evaluation.status)
                if str(getattr(user, "role", "")) == "teacher":
                    ev_stmt = ev_stmt.where(Evaluation.teacher_id == user.id)
                seen: dict = {}
                for sid, st in db.execute(ev_stmt).all():
                    if sid not in seen or st == EvaluationStatus.PUBLISHED.value:
                        seen[sid] = st
                done = sum(1 for s in students if seen.get(s.id) == EvaluationStatus.PUBLISHED.value)
            except Exception:
                pass
            out["items"].append({
                "kind": "class", "id": str(cls.id), "title": cls.name,
                "period": ref_period or str(ref.get("title") or ""),
                "student_count": len(students),
                "eval_done": done,
                "students": [s.name for s in students[:30]],
            })
    if not out["items"] and ref:
        out["items"].append({"kind": "context", "title": str(ref.get("title") or "业务上下文"), "id": ""})
    return out


@router.post("/conversations/{conv_id}/attachments")
def upload_conversation_attachment(
    conv_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对话附件上传：图片/文档暂存到 uploads/chat/<会话>/，文档解析出正文供本轮对话引用。

    返回的结构（id/name/kind/url/size/text）由前端在发送消息时原样回传，
    后端据此把附件内容注入对话上下文；URL 经 /uploads 静态服务可直接预览。
    """
    from app.core.config import get_settings
    from app.services import rag as _rag

    conv = agent_crud.get_conversation(db, conv_id=conv_id, owner_id=user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix in _IMG_SUFFIXES:
        kind = "image"
    elif suffix in _DOC_SUFFIXES:
        kind = "doc"
    else:
        raise HTTPException(status_code=400, detail=f"暂不支持的文件类型：{suffix or '未知'}（支持图片与 txt/md/pdf/docx）")

    settings = get_settings()
    dest_dir = Path(settings.UPLOAD_DIR) / "chat" / str(conv.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{suffix}"
    dest = dest_dir / stored
    max_bytes = max(1, settings.MAX_UPLOAD_SIZE_MB) * 1024 * 1024
    size = 0
    try:
        with dest.open("wb") as f:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"文件超过 {settings.MAX_UPLOAD_SIZE_MB}MB 上限")
                f.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise

    text: str | None = None
    if kind == "doc":
        try:
            text = (_rag.extract_text(str(dest), file.filename or stored) or "")[:20000]
        except Exception:
            text = None
    return {
        "id": stored.split(".")[0],
        "name": file.filename or stored,
        "kind": kind,
        "url": f"/uploads/chat/{conv.id}/{stored}",
        "size": size,
        "text": text,
    }


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
    if agent_registry.resolve_agent(db, user.id, conv.agent_id) is None:
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

    # 报告真实数据（统计快照 + 逐月明细）：绑定报告就取数，数据类版式直接用数画图
    stats: dict = {}
    period_label = ""
    monthly: list[dict] = []
    breakdown: list[dict] | None = None
    if conv.agent_id == "report_ppt" or _report_ids_from_ref(conv.context_ref or {}):
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
    attachments: list[dict] = Field(default=[], description="随消息上传的附件：{id,name,kind,url,size,text}")


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
    agent_def = agent_registry.resolve_agent(db, user.id, conv.agent_id)
    if agent_def is None:
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
    stage_keys = [s.get("key") for s in (agent_def or {}).get("stages", [])]
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

    mem_ctx = agent_memory.build_memory_context(
        db, owner_id=user.id, agent_id=conv.agent_id, conversation_id=conv.id, query=message
    )
    mem_block = agent_memory.memory_prompt_block(mem_ctx)
    # 绑定班级 → 学员评估正文自动回传进对话（任何 Agent 都生效，无需再调工具）
    try:
        class_block = _class_eval_block(db, user, context_ref)
        if class_block:
            mem_block = (mem_block + "\n\n" + class_block).strip() if mem_block else class_block
    except Exception:
        pass
    # 绑定报告 → 报告正文摘要自动回传（素材 tab 绑定「报告总结」后直接引用）
    try:
        report_block = _report_block(db, context_ref)
        if report_block:
            mem_block = (mem_block + "\n\n" + report_block).strip() if mem_block else report_block
    except Exception:
        pass
    # 随消息上传的附件（文档正文/图片登记）注入本轮上下文
    attachment_block = _attachment_block(body.attachments or [])
    if attachment_block:
        mem_block = (mem_block + "\n\n" + attachment_block).strip() if mem_block else attachment_block
    # 自定义 Agent 的 system_prompt 覆盖 + Skill/MCP 生效（per-agent ∪ 全局）：
    # Skill 以追加指令块注入；MCP 名单注入 + 运行时真实调用（规划→POST→回灌）。
    caps = agent_registry.effective_capabilities(db, user.id, conv.agent_id)
    custom_sys = (agent_def or {}).get("system_prompt") or ""
    extra_blocks: list[str] = []
    if custom_sys.strip() and (agent_def or {}).get("custom"):
        extra_blocks.append(f"【Agent 专属指令】\n{custom_sys.strip()}")
    extra_blocks.extend(caps.get("skill_blocks") or [])
    if caps.get("mcp_names"):
        extra_blocks.append("【可用外部工具（MCP）】\n" + "\n".join(f"- {n}" for n in caps["mcp_names"]))
    if extra_blocks:
        extra = "\n\n".join(extra_blocks)
        mem_block = (mem_block + "\n\n" + extra).strip() if mem_block else extra
    # MCP 运行时执行：LLM 决策是否调用生效的 MCP，POST endpoint 取结果回灌。
    # 全部容错：无工具/无需调用/失败/超时静默跳过，不影响主回答。
    mcp_tool_names: list[str] = []
    mcp_trace: list[dict] = []
    try:
        if message.strip():
            from app.services import mcp_runner as _mcp

            # 压入教师个人模型配置：规划调用走自配模型，否则全局无 key 时报 Missing credentials
            with _llm_ctx.use_llm(resolved):
                mcp_block, mcp_tool_names, mcp_trace = _mcp.run(db, user.id, conv.agent_id, message.strip())
            if mcp_block:
                mem_block = (mem_block + "\n\n" + mcp_block).strip() if mem_block else mcp_block
    except Exception:
        mcp_tool_names = []
        mcp_trace = []
    # RAG：会话开关默认关；单条消息可临时切换。
    # 自动引用：开关关闭时，若本条消息确需知识库（非寒暄）且用户确有文档，
    # 自动为本条检索一次并注入，不改会话开关（前端会提示"本次已自动引用"）。
    agent_info = agent_def or {}
    want_rag = body.use_rag if body.use_rag is not None else bool(conv.rag_enabled)
    rag_auto = False
    citations: dict | None = None
    if agent_info.get("supports_rag") and message.strip() and (
        want_rag or (body.use_rag is None and not conv.rag_enabled)
    ):
        try:
            # 寒暄类消息跳过检索：省一次向量化，首字更快
            if rag_service.needs_retrieval(message.strip()):
                collected = knowledge_crud.collected_doc_ids(db, user_id=user.id)
                # 压入教师个人配置：检索向量化走自配 embedding 模型
                diag: dict = {}
                with _llm_ctx.use_llm(resolved):
                    hits = rag_service.retrieve(
                        message.strip(), db=db, owner_id=user.id, collected_ids=collected, diag=diag
                    )
            if hits:
                if not want_rag:
                    rag_auto = True
                citations = {
                    "hits": hits,
                    # 检索诊断：向量/关键词/重排是否真的生效（前端展示 + 排障）
                    "retrieval": {
                        "vector": bool(diag.get("vector")),
                        "keyword": bool(diag.get("keyword")),
                        "rerank": bool(diag.get("rerank")),
                        "rerank_model": diag.get("rerank_model"),
                        "summary": rag_service.retrieval_summary(diag),
                    },
                }
                if rag_auto:
                    citations["rag_auto"] = True
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
    # 智能助手：多轮规划层执行只读业务工具（排课考勤/教学数据/班级/学员/评估）或 Skill 脚本。
    # 规划→执行→观察，带预算护栏与降级；非业务问题或失败时静默跳过，不影响流式回答。
    # 长耗时（沙箱建实例/装依赖按分钟计）不能在发流前同步等：提前扔后台线程，
    # event_stream 里一边心跳报进度一边等，完工立刻推送执行链路，再组装 prompt 进模型。
    plan_outcome: agent_planner.PlanOutcome = agent_planner.PlanOutcome()
    has_skill_tools = bool(caps.get("skill_blocks"))
    _msg_stripped = message.strip()
    # Skill 任务判定：既包括「生成/制作/跑脚本」，也包括 PPT「二次编辑」意图（加页/删页/改文字/调顺序…），
    # 以及「催出片/继续/下载」这类续作意图。后两者若不纳入，用户说「出片把」「继续」就不会进 Skill 路径，
    # 模型只能凭空叙述「我马上出片」却从不真正执行——正是「说了出片不出片」的根因。
    skill_mode = has_skill_tools and bool(_msg_stripped) and (
        agent_tools.looks_like_skill_task(_msg_stripped)
        or agent_tools.looks_like_ppt_edit(_msg_stripped)
        or agent_tools.looks_like_ppt_continue(_msg_stripped)
    )
    # PPT 二次编辑：把当前用户已有 Skill 包内的 .pptx 源文件路径注入上下文，让模型能「就地改」而不是重造。
    if skill_mode and agent_tools.looks_like_ppt_edit(_msg_stripped):
        try:
            pptx_block = _existing_pptx_block(db, user)
            if pptx_block:
                mem_block = (mem_block + "\n\n" + pptx_block).strip() if mem_block else pptx_block
        except Exception:
            pass
    plan_box: dict = {}
    plan_thread = None
    if (conv.agent_id == "assistant" or has_skill_tools) and message.strip():
        import threading as _plan_th

        from app.core.database import SessionLocal as _SessionLocal

        _uid = user.id
        _msg = message.strip()

        def _run_plan():
            sdb = _SessionLocal()
            try:
                from app.models.user import User as _User

                suser = sdb.get(_User, _uid)
                if suser is None:
                    plan_box["outcome"] = agent_planner.PlanOutcome()
                    return
                # 线程不继承 contextvar：在此重新压入教师个人模型配置，否则规划模型拿不到 Key
                with _llm_ctx.use_llm(resolved):
                    if skill_mode:
                        # Skill 干活（读文件/跑脚本/取产物）：多轮 + 长预算，沙箱执行慢也不掐断
                        out = agent_planner.plan_and_run(
                            sdb, suser, _msg, max_rounds=16, max_calls=30, time_budget_ms=600000,
                        )
                    else:
                        out = agent_planner.plan_and_run(sdb, suser, _msg)
                    plan_box["outcome"] = out
                    logger.info("plan done agent=%s skill_mode=%s steps=%s",
                                conv.agent_id, skill_mode, [s.tool for s in out.steps])
            except Exception as e:  # noqa: BLE001 —— 规划失败静默降级，不拖垮对话
                logger.exception("plan failed agent=%s skill_mode=%s", conv.agent_id, skill_mode)
                plan_box["error"] = e
            finally:
                sdb.close()

        plan_thread = _plan_th.Thread(target=_run_plan, daemon=True)
        plan_thread.start()
    # prompt 组装所需的变量先在端点作用域占位，真实赋值在 event_stream 等规划完成后进行
    # （_run_stream 与 done 帧都闭包读取它们）
    tool_names: list = []
    system, prompt = "", ""

    def _frame(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    def event_stream():
        # 最外层兜底：任何未预期异常都必须以 error 帧结束，绝不能让前端无限卡"接收中"
        nonlocal plan_outcome, mem_block, tool_names, system, prompt
        try:
            # 等后台规划（心跳报进度，不再是发流前的黑盒等待）；完工立刻把执行链路推给前端
            if plan_thread is not None:
                import time as _pt

                t_plan = _pt.monotonic()
                while plan_thread.is_alive():
                    plan_thread.join(timeout=5)
                    if plan_thread.is_alive():
                        el = int(_pt.monotonic() - t_plan)
                        doing = "正在执行 Skill（读文件/跑脚本/取产物）" if skill_mode else "正在查询业务数据"
                        yield _frame({"phase": {"key": "plan", "label": f"{doing}（已用 {el} 秒）"}})
                got = plan_box.get("outcome")
                if isinstance(got, agent_planner.PlanOutcome):
                    plan_outcome = got
            tool_names = plan_outcome.tools
            if plan_outcome.block:
                mem_block = (mem_block + "\n\n" + plan_outcome.block).strip() if mem_block else plan_outcome.block
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
                att_meta = [
                    {k: a.get(k) for k in ("id", "name", "kind", "url", "size")}
                    for a in (body.attachments or []) if isinstance(a, dict)
                ]
                agent_crud.add_message(
                    db, conversation_id=conv.id, role="user", content=message.strip(),
                    citations=({"attachments": att_meta} if att_meta else None),
                )
            if tool_names:
                yield _frame({"tools_live": _tool_trace(plan_outcome)})
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
                        logger.exception("chat stream failed conv=%s", conv.id)
                        box.put(("error", e))

            t0 = _time.monotonic()
            threading.Thread(target=_produce, daemon=True).start()
            started = False
            while True:
                try:
                    kind, payload = box.get(timeout=15)
                except queue.Empty:
                    elapsed = int(_time.monotonic() - t0)
                    if elapsed > 900:
                        yield _frame({"error": "AI 生成超时（超过 15 分钟无结果），请缩短问题或稍后重试"})
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
        # 先净化：剔除模型偶发吐出的原生工具调用标记，避免乱码入库、污染后续历史
        full = llm.strip_toolcall_markup(full)
        options = agent_chat.extract_options(full)
        spec = agent_chat.extract_spec(full)
        # Skill 路径兜底：模型用 run_skill_script 生成 PPT 时，通常不会在正文里输出 ```json 大纲，
        # 导致工作区「大纲/成果」不同步、SVG 预览丢失。这里从工具执行结果里提炼大纲回填 spec，
        # 让「大纲」与「成果」始终对齐（大纲里的每一页都能对应到已生成的幻灯片）。
        if not spec.get("outline") and plan_outcome.steps:
            derived = _derive_spec_from_tools(plan_outcome)
            if derived:
                spec = {**derived, **spec}
        final_stage = _infer_stage(conv.agent_id, stage, options, spec)
        # 工具调用轨迹：随 citations 持久化（免迁移），前端在气泡下方可收起展开
        tool_trace = _tool_trace(plan_outcome)
        msg_citations: dict | None = citations
        if mcp_tool_names:
            tool_trace = (tool_trace + [f"MCP:{n}" for n in mcp_tool_names]) if tool_trace else [f"MCP:{n}" for n in mcp_tool_names]
        if mcp_trace:
            msg_citations = dict(msg_citations or {})
            msg_citations["mcp_trace"] = mcp_trace
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
            agent_memory.record_working_turn(
                db,
                owner_id=user.id,
                agent_id=conv.agent_id,
                conversation_id=conv.id,
                user_text=message,
                assistant_text=full,
                stage=final_stage,
                tools=tool_trace or [],
            )
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
            "mcp_trace": mcp_trace,
            "rag_auto": rag_auto,
            # 本次检索命中：随 done 帧发给前端即时渲染（免刷新）
            "hits": [
                {"title": h.get("title", ""), "text": (h.get("text") or "")[:400],
                 "similarity": h.get("similarity", 0),
                 "rerank_score": h.get("rerank_score")}
                for h in (citations or {}).get("hits", [])
            ] if citations and (citations or {}).get("hits") else [],
            "retrieval": (citations or {}).get("retrieval"),
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
