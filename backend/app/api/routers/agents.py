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
    # 默认 Agent 供给：每个教师/管理员账号默认有一个「PPT生成助手」（幂等，已存在则跳过）
    try:
        from app.services import agent_provision

        agent_provision.ensure_default_ppt_agent(db, user)
    except Exception:
        pass
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


# 视觉模型（OpenAI 兼容 image_url）支持的格式；SVG/BMP 需先转换，这里直接跳过
_VISION_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _image_data_urls(attachments: list[dict], *, max_images: int = 4, max_total_bytes: int = 30 * 1024 * 1024) -> list[str]:
    """把随消息上传的图片读成 data URL，供多模态模型直读（如 deepseek-flash 图像理解）。

    只收视觉模型支持的格式（PNG/JPEG/GIF/WebP），总原始体积封顶 30MB（base64 后约 40MB，
    低于 DeepSeek 48MiB 请求体上限）。读不到/超限的图片跳过，不影响文字对话。
    """
    if not attachments:
        return []
    import base64

    from app.core.config import get_settings

    settings = get_settings()
    upload_root = Path(settings.UPLOAD_DIR).resolve()
    out: list[str] = []
    total = 0
    for a in attachments:
        if not isinstance(a, dict) or str(a.get("kind")) == "doc":
            continue
        url = str(a.get("url") or "")
        if not url.startswith("/uploads/"):
            continue
        disk = upload_root / url[len("/uploads/"):]
        mime = _VISION_MIME.get(disk.suffix.lower())
        if not mime:
            continue
        try:
            data = disk.read_bytes()
        except OSError:
            continue
        if not data or total + len(data) > max_total_bytes:
            continue
        total += len(data)
        out.append(f"data:{mime};base64," + base64.b64encode(data).decode("ascii"))
        if len(out) >= max_images:
            break
    return out


def _looks_like_vision_rejection(exc: BaseException) -> bool:
    """判断异常是否「模型/网关不接受图片输入」，用于自动降级为纯文本重试。"""
    text = f"{exc}".lower()
    return any(k in text for k in ("image", "vision", "multimodal", "image_url", "content type", "unsupported"))


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
            f"\n【重要·须回应附件】用户本次上传了 {img_count} 张图片，图片已以多模态方式随本轮消息直接附给模型。"
            "若你能看到图片内容，请直接基于图片作答（描述画面、识别文字、分析图表等），"
            "不要说自己不具备查看图片的能力，也不要编造可见范围之外的内容；"
            "只有在你确实收不到图片时，才如实说明并请用户补充文字描述。"
            "回答开头用一句话确认「已收到这 N 张图片」并复述文件名。"
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


def _svg_page_title(content: str) -> str:
    """从 SVG 源码提炼页面标题（实现在 agent_tools.svg_page_title，供工具层/大纲共用）。"""
    return agent_tools.svg_page_title(content)


def _page_num_key(name: str):
    """页文件名自然排序键（01_x.svg < 02_y.svg < 10_z.svg）。"""
    import re as _re

    m = _re.match(r"^(\d+)", str(name))
    return int(m.group(1)) if m else 10 ** 9


def _conv_ppt_data(db, user, conv_id) -> list[dict]:
    """本会话（会话隔离目录）里各 Skill 的 PPT 项目数据：项目、页清单（文件名+真实标题）、成品。"""
    data: list[dict] = []
    try:
        from app.crud import agent_ext as _ext
        from app.services import skill_bundle as _bundle

        prefix = "conversations/conv_" + str(conv_id).replace("-", "")[:12] + "/"
        for s in _ext.list_skills(db, owner_id=user.id):
            if not s.enabled:
                continue
            desk = _bundle.skill_dir(user.id, s.id)
            conv_dir = desk / prefix / "projects"
            if not conv_dir.is_dir():
                continue
            for proj in sorted(conv_dir.iterdir()):
                svg_dir = proj / "svg_output"
                if not (proj.is_dir() and svg_dir.is_dir()):
                    continue
                files = sorted(svg_dir.glob("*.svg"),
                               key=lambda p: (_page_num_key(p.name), p.name.lower()))
                if not files:
                    continue
                pptx = sorted(proj.rglob("*.pptx"), key=lambda p: p.stat().st_mtime)
                pages: list[tuple[str, str]] = []
                for fp in files:
                    try:
                        t = agent_tools.svg_page_title(fp.read_text(encoding="utf-8", errors="ignore"))
                    except OSError:
                        t = ""
                    pages.append((fp.name, t))
                data.append({
                    "skill": s.name,
                    "rel": "projects/" + proj.name,
                    "n_pages": len(pages),
                    "latest": str(pptx[-1].relative_to(desk)).replace("\\", "/") if pptx else "",
                    "pages": pages,
                })
            if len(data) >= 6:
                break
    except Exception:
        return []
    return data


def _render_conv_ppt_block(data: list[dict]) -> str:
    if not data:
        return ""
    lines: list[str] = []
    for d in data[:6]:
        seg = f"- Skill「{d['skill']}」- 项目 `{d['rel']}`（{d['n_pages']} 页）"
        if d["latest"]:
            seg += f"，最新成品：{d['latest']}"
        # 当前页清单（文件名 + 真实标题）：二次编辑时模型能精确指名要改的页，
        # 不必重造整份、也不会把已定稿的页改差（多轮质量衰减的关键）。
        bits = [f"{n}「{t}」" if t else n for n, t in d["pages"][:30]]
        if d["n_pages"] > 30:
            bits.append(f"…另有 {d['n_pages'] - 30} 页")
        if bits:
            seg += "\n  当前页：" + "；".join(bits)
        lines.append(seg)
    return (
        "【本会话已生成的 PPT（二次编辑基线）】\n" + "\n".join(lines)
        + "\n若用户要求「在这基础上调整」（改字/换配色/加删页/调顺序），必须直接改上面"
        "**本会话该项目**的 svg_output（先用 write_skill_file 覆盖改动的页、删页就删对应 svg 文件，"
        "未改页保持不动，处理后重新 build），禁止另起新项目或从头重写整份。"
        "\n若用户明确说「重新做/换主题/新的一套」，才新建项目。"
    )


def _conversation_ppt_block(db, user, conv_id) -> str:
    """列出「本会话」已生成的 PPT 项目与成品，作为二次编辑的基线注入。"""
    return _render_conv_ppt_block(_conv_ppt_data(db, user, conv_id))


def _page_diff_note(prev_titles: list[str], new_titles: list[str]) -> str:
    """对比改动前后页标题，生成「改动计划（已执行）」回执（无变化返回空）。

    - 新增：定位第一个新增页在新序中的下标，报「第 N 页后插入」；
    - 删除：列出被移除的页标题；
    - 页数变化始终给出。
    """
    if not prev_titles or not new_titles:
        return ""
    inserted = [t for t in new_titles if t not in prev_titles]
    removed = [t for t in prev_titles if t not in new_titles]
    if not inserted and not removed:
        return ""
    bits: list[str] = []
    if inserted:
        try:
            pos = new_titles.index(inserted[0])
        except ValueError:
            pos = 0
        bits.append(f"新增 {len(inserted)} 页（第 {pos} 页后插入：{'、'.join(inserted)}）")
    if removed:
        bits.append(f"删除 {len(removed)} 页（{'、'.join(removed)}）")
    return (
        "改动计划（已执行）：" + "；".join(bits)
        + f"。页数 {len(prev_titles)} → {len(new_titles)}。"
    )


def _derive_spec_from_tools(plan_outcome) -> dict:
    """从 Skill 工具执行轨迹里提炼 PPT 规格（大纲 + 幻灯片预览），供工作区「大纲/成果」对齐。

    当模型用 ppt-master 之类的 Skill 生成 PPT 时，正文通常不含 ```json 大纲，
    但工具会：
      - write_skill_file 逐页写入 svg（含 SVG 源码）→ 标题取页面内字号最大的文本（真实标题）；
      - run_skill_script build 会把**整份** svg 落到 _outputs（带下载 url）→ 以它的文件清单为准，
        保证「调整后的大纲」反映最终成品全部页（含本次未改动的页），而不是只有本次写过的页。
    """
    import re as _re

    # 1) build 产出的每页 svg 下载 url（按文件名索引，如 01_cover.svg → url）
    #    同时记录**整份** svg 清单（含本次未改动的旧页）——调整后大纲要反映最终成品全部页。
    svg_url_by_name: dict[str, str] = {}
    built_svg_names: list[str] = []
    built_info_by_name: dict[str, dict] = {}

    def _sort_names(names: list[str]) -> list[str]:
        def _k(n: str):
            m = _re.match(r"^(\d+)", n)
            return (int(m.group(1)) if m else 10 ** 9, n.lower())
        return sorted(names, key=_k)

    for s in plan_outcome.steps:
        if s.tool != "run_skill_script" or not s.ok or not isinstance(s.result, dict):
            continue
        step_svg: list[str] = []
        step_info: dict[str, dict] = {}
        for f in (s.result.get("生成文件") or []):
            if not isinstance(f, dict):
                continue
            nm = str(f.get("名") or "")
            url = str(f.get("下载") or "")
            if nm.lower().endswith(".svg"):
                if url:
                    svg_url_by_name[nm] = url  # 后出现的覆盖前面的（更接近最新一次 build）
                step_svg.append(nm)
        pages = s.result.get("页清单")
        if isinstance(pages, list):
            step_svg = [str(x) for x in pages if str(x).lower().endswith(".svg")]
        infos = s.result.get("页信息")
        if isinstance(infos, list):
            for i in infos:
                if isinstance(i, dict):
                    step_info[str(i.get("名") or "")] = {
                        "title": str(i.get("标题") or ""),
                        "url": str(i.get("url") or ""),
                    }
        if step_svg:
            built_svg_names = _sort_names(step_svg)  # 最后一步 build 的整份清单为准
            built_info_by_name = step_info

    # 2) 本轮 write_skill_file 写过的页：记录源码与写入的包内路径
    #    标题取 SVG 内字号最大的文本（真实页标题），不再用文件名 slug。
    written: dict[str, dict] = {}  # base 文件名 → {path, url, title}
    order: list[str] = []
    for s in plan_outcome.steps:
        if s.tool != "write_skill_file" or not s.ok:
            continue
        args = s.args or {}
        path = str(args.get("path") or "")
        if not path.lower().endswith(".svg"):
            continue
        base = path.rsplit("/", 1)[-1]
        if base in written:
            # 同一页本会话写过多次：位置取首次，内容/标题以最后写入为准
            written[base]["path"] = path
            written[base]["title"] = _svg_page_title(str(args.get("content") or "")) or written[base]["title"]
            continue
        order.append(base)
        written[base] = {
            "path": path,
            "url": svg_url_by_name.get(base, ""),
            "title": _svg_page_title(str(args.get("content") or "")),
        }

    svg_pages: list[dict] = []
    if built_svg_names:
        # 3) 以 build 的整份清单为准（按文件名排序即页序）：本次没改的旧页也在内。
        #    标题/预览 url 用工具回执的「页信息」（build 后从磁盘 svg 提取）→ 与成品逐页对齐；
        #    回执缺失时才退回本轮写入内容、最后退回文件名。
        for base in built_svg_names:
            info = written.get(base) or {}
            binfo = built_info_by_name.get(base) or {}
            stem = base.rsplit(".", 1)[0]
            title = (binfo.get("title") or info.get("title")
                     or _re.sub(r"^\d+[_\-\s]*", "", stem).strip() or stem)
            svg_pages.append({
                "id": f"p{len(svg_pages) + 1}",
                "title": title,
                "kind": "content",
                "file": info.get("path") or base,
                "url": binfo.get("url") or info.get("url") or svg_url_by_name.get(base, ""),
            })
    else:
        # 还没出片：按本轮写入顺序还原
        for base in order:
            info = written[base]
            stem = base.rsplit(".", 1)[0]
            svg_pages.append({
                "id": f"p{len(svg_pages) + 1}",
                "title": info.get("title") or _re.sub(r"^\d+[_\-\s]*", "", stem).strip() or stem,
                "kind": "content",
                "file": info.get("path") or base,
                "url": svg_url_by_name.get(base, ""),
            })
    if not svg_pages:
        return {}
    outline = [
        {"id": p["id"], "title": p["title"], "kind": ("cover" if i == 0 else "content"),
         "url": p.get("url", "")}
        for i, p in enumerate(svg_pages)
    ]
    return {"outline": outline, "slides": svg_pages}


def _synthesize_ppt_summary(plan_outcome) -> tuple[str, bool]:
    """当模型正文过短/缺下载链接时，基于工具轨迹合成一段完整交付说明。

    返回 (markdown, has_pptx)。内容：页数 + 逐页标题 + pptx 下载链接。
    **以 build 回执的整份页清单为准**（页数=成品页数，标题=磁盘 SVG 提炼的真实标题），
    与工作区大纲、实际页逐一对齐；不再按标题去重（重复标题的页也曾被吞掉）。
    避免「空回复/输出不完整」——保证用户一定拿到「生成了什么、怎么下载」。
    """
    import re as _re

    pptx_url = ""
    roster: list[dict] = []  # build 成品完整页清单（最后一步 build 为准）
    written: list[dict] = []  # 本轮 write_skill_file 写过的页（尚未成片时的回退）
    for s in plan_outcome.steps:
        if s.tool == "run_skill_script" and s.ok and isinstance(s.result, dict):
            for f in (s.result.get("生成文件") or []):
                if isinstance(f, dict) and str(f.get("名") or "").lower().endswith(".pptx") and f.get("下载"):
                    pptx_url = str(f.get("下载"))
            infos = s.result.get("页信息")
            if isinstance(infos, list) and infos:
                roster = [i for i in infos if isinstance(i, dict)]
            elif isinstance(s.result.get("页清单"), list):
                roster = [{"名": str(x), "标题": ""} for x in s.result["页清单"]]
            else:
                svg_files = [
                    str(f.get("名"))
                    for f in (s.result.get("生成文件") or [])
                    if isinstance(f, dict) and str(f.get("名") or "").lower().endswith(".svg")
                ]
                if svg_files:
                    roster = [{"名": nm, "标题": ""} for nm in svg_files]
        elif s.tool == "write_skill_file" and s.ok:
            args = s.args or {}
            path = str(args.get("path") or "")
            if path.lower().endswith(".svg"):
                t = _svg_page_title(str(args.get("content") or ""))
                written.append({"名": path.rsplit("/", 1)[-1], "标题": t})
    if not pptx_url and not roster and not written:
        return "", False

    def _clean(name: str) -> str:
        stem = name.rsplit(".", 1)[0]
        return _re.sub(r"^\d+[_\-\s]*", "", stem).strip() or stem

    pages = roster or written
    titles = [str(p.get("标题") or "").strip() or _clean(str(p.get("名") or "")) for p in pages]
    lines: list[str] = []
    if roster:
        lines.append(f"已生成 **{len(titles)} 页** 幻灯片：")
    elif titles:
        lines.append(f"本轮已写入 **{len(titles)} 页**（构建未完成，质量检查未通过，修复后将自动重新出片）：")
    for i, t in enumerate(titles, 1):
        lines.append(f"{i}. {t}")
    if pptx_url:
        lines.append("")
        lines.append(f"📥 [下载 PPTX]({pptx_url})")
    return "\n".join(lines), bool(pptx_url)


def _has_pptx_result(plan_outcome) -> bool:
    """本轮是否成功拿到可下载的 .pptx 成品（以**最后一次** build 结果为准）。"""
    last = None
    for s in plan_outcome.steps:
        if s.tool == "run_skill_script":
            last = s
    if last is None or not isinstance(last.result, dict):
        return False
    for f in (last.result.get("生成文件") or []):
        if isinstance(f, dict) and str(f.get("名") or "").lower().endswith(".pptx") and f.get("下载"):
            return True
    return False


def _build_error_lines(plan_outcome) -> list[str]:
    """从失败 build 的 stdout/stderr 里提取关键报错行（给自动重试与兜底说明用）。"""
    import re as _re

    lines: list[str] = []
    for s in plan_outcome.steps:
        if s.tool != "run_skill_script" or not isinstance(s.result, dict):
            continue
        blob = str(s.result.get("stdout") or "") + "\n" + str(s.result.get("stderr") or "")
        for raw in blob.splitlines():
            ln = raw.strip()
            if not ln:
                continue
            if ("[ERROR]" in ln or "errors:" in ln.lower()
                    or _re.search(r"\.svg.*(exceed|cannot|requires|Unsupported|Invalid|missing)", ln, _re.I)):
                lines.append(ln[:200])
            if len(lines) >= 6:
                return lines
    return lines


def _build_error_pages(plan_outcome) -> list[str]:
    """失败页文件名（02_xxx.svg），用于给用户一个可操作的定位。"""
    import re as _re

    pages: list[str] = []
    for s in plan_outcome.steps:
        if s.tool != "run_skill_script" or not isinstance(s.result, dict):
            continue
        blob = str(s.result.get("stdout") or "") + "\n" + str(s.result.get("stderr") or "")
        for m in _re.finditer(r"(\d{1,3}[\w\-]*\.svg)", blob):
            n = m.group(1)
            if n not in pages:
                pages.append(n)
    return pages[:3]


_NARRATION_HINTS = (
    "我先把", "我先读", "先读出来", "读出来", "再重跑", "上一轮", "我这就", "先确认",
    "接下来我", "先看看", "先定位", "我重新", "我马上", "稍等一下", "我先按",
)


def _looks_like_narration(text: str) -> bool:
    """是否「过程旁白」式回复（讲下一步要做什么，却没有交付）。"""
    t = (text or "").strip()
    if not t or len(t) > 260:
        return False
    return any(w in t for w in _NARRATION_HINTS)


# 模型会把工具调用「当正文」吐出来（XML/伪 YAML 风格，如 <write_skill_file> skill: … path: … content: | …）。
# 这些必须：① 从正文里剔除；② 若规划层实际没执行，按块内容**真实执行**，结果进执行链路。
_PSEUDO_TOOL_NAMES = (
    "write_skill_file", "read_skill_file", "list_skill_files", "delete_skill_file",
    "run_skill_script", "web_search",
)
# `<tool_use><name>run_skill_script</name><arguments>{json}</arguments></tool_use>` 形式
# （模型原生 tool-call 语法被当正文吐出来的另一变体，常见于 Claude 风格）
_TOOL_USE_BLOCK_RE = r"<tool_use>\s*<name>\s*([\w./-]+)\s*</name>\s*<arguments>\s*([\s\S]*?)\s*</arguments>\s*</tool_use>"
_INVOKE_BLOCK_RE = r"<invoke\s+name=[\"']([\w./-]+)[\"']\s*>\s*<[\s\S]*?</invoke>"
_PSEUDO_BLOCK_RE = None


def _pseudo_block_re():
    global _PSEUDO_BLOCK_RE
    import re as _re

    if _PSEUDO_BLOCK_RE is None:
        _PSEUDO_BLOCK_RE = _re.compile(
            r"<(" + "|".join(_PSEUDO_TOOL_NAMES) + r")\b[^>]*>(.*?)</\1>",
            _re.S | _re.I,
        )
    return _PSEUDO_BLOCK_RE


def _extract_tool_use_blocks(text: str) -> list[tuple[str, dict]]:
    """解析 `<tool_use><name>X</name><arguments>{json}</arguments></tool_use>` 变体。"""
    import re as _re

    out: list[tuple[str, dict]] = []
    if not text:
        return out
    for m in _re.finditer(_TOOL_USE_BLOCK_RE, text, _re.S):
        name = m.group(1).strip().lower()
        raw = m.group(2).strip()
        args: dict = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    args = parsed
            except (ValueError, TypeError):
                args = {}
        # 归一化：run_skill_script 的 script 字段统一成 path（与真实工具签名一致）
        if name == "run_skill_script" and "script" in args and "path" not in args:
            args["path"] = args.pop("script")
        if name in _PSEUDO_TOOL_NAMES and (args.get("skill") or args.get("path")):
            out.append((name, args))
    return out


def _extract_pseudo_tool_blocks(text: str) -> list[tuple[str, dict]]:
    """从正文里提取伪工具调用块 → [(工具名, 参数)]（用于真实执行 + 正文剔除）。

    支持两种常见变体：
    1) `<write_skill_file> skill: … path: … content: | <svg…>`（YAML 风格）；
    2) `<tool_use><name>…</name><arguments>{json}</arguments></tool_use>`（原生调用语法）。
    """
    import re as _re

    out: list[tuple[str, dict]] = []
    if not text:
        return out
    for m in _pseudo_block_re().finditer(text):
        name = m.group(1).strip().lower()
        body = m.group(2)

        def _pick(key: str) -> str:
            mm = _re.search(rf"^\s*{key}\s*:\s*(.+)$", body, _re.M)
            if not mm:
                return ""
            return mm.group(1).strip().strip('"').strip("'")

        skill = _pick("skill")
        path = _pick("path") or _pick("script")
        args: dict = {}
        if skill:
            args["skill"] = skill
        if path:
            args["path"] = path
        if name == "write_skill_file":
            cm = _re.search(r"^\s*content\s*:\s*\|?\s*\n([\s\S]*)$", body, _re.M)
            if cm and cm.group(1).strip():
                args["content"] = cm.group(1).rstrip()
        raw_args = _pick("args")
        if raw_args:
            try:
                args["args"] = json.loads(raw_args)
            except (ValueError, TypeError):
                args["args"] = [x.strip().strip('"').strip("'") for x in raw_args.strip("[]").split(",") if x.strip()]
        if skill or path:
            out.append((name, args))
    # 归一化再补 tool_use JSON 变体（去重：同一 (name,path) 只留一个）
    seen = {(n, a.get("path")) for n, a in out}
    for n, a in _extract_tool_use_blocks(text):
        key = (n, a.get("path"))
        if key not in seen:
            seen.add(key)
            out.append((n, a))
    return out


def _strip_pseudo_tool_blocks(text: str) -> str:
    """从正文剔除伪工具调用块（含其 YAML/SVG/JSON 载荷），保留前后正常文字。"""
    import re as _re

    if not text:
        return text
    clean = _pseudo_block_re().sub("", text)
    clean = _re.sub(_TOOL_USE_BLOCK_RE, "", clean, flags=_re.S)
    clean = _re.sub(_INVOKE_BLOCK_RE, "", clean, flags=_re.S)
    clean = _re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean


def _execute_rescue_blocks(db, user, conv_id, agent_id, blocks: list[tuple[str, dict]], on_step=None):
    """把正文里的伪工具调用**真实执行**（写页/跑构建），让执行链路与交付对齐。

    on_step(step, seq, phase)：可选回调，让 rescue 执行也在前端实时可见
    （否则用户在「整理结果」阶段仍看不到写页/出片进行到哪一步）。
    """
    from app.services.agent_planner import Step

    steps: list = []
    if not blocks:
        return steps
    try:
        agent_tools.use_conversation(conv_id)
    except Exception:
        pass
    try:
        from app.services import agent_registry as _reg

        agent_tools.use_allowed_skills(_reg.effective_skill_ids(db, user.id, agent_id))
    except Exception:
        try:
            agent_tools.use_allowed_skills(None)
        except Exception:
            pass
    total_chars = 0

    def _fire(step, phase):
        if on_step is not None:
            try:
                on_step(step, len(steps) + (1 if phase == "start" else 0), phase)
            except Exception:
                pass

    try:
        for name, args in blocks[:40]:
            if total_chars > 2_000_000:
                break
            content = args.get("content")
            if isinstance(content, str):
                total_chars += len(content)
            step = Step(tool=name, args=args, ok=True, result=None, error=None)
            _fire(step, "start")
            try:
                payload = agent_tools.execute_tool(db, user, name, args)
                ok = not (isinstance(payload, dict) and payload.get("错误"))
                err = None if ok else str(payload.get("错误"))
            except Exception as e:  # noqa: BLE001 —— 单条失败不影响后续
                payload, ok, err = {"错误": str(e)}, False, str(e)
            step.ok, step.result, step.error = ok, (payload if ok else None), err
            steps.append(step)
            _fire(step, "done")
    finally:
        # 恢复上下文，避免线程池复用把会话作用域泄漏到后续请求
        try:
            agent_tools.use_conversation(None)
            agent_tools.use_allowed_skills(None)
        except Exception:
            pass
    return steps


def _pptx_failure_notice(plan_outcome) -> str:
    """无成品时的用户可执行兜底说明（绝不输出内部过程旁白/空内容）。"""
    pages = _build_error_pages(plan_outcome)
    where = f"（主要卡在：{'、'.join(pages)}）" if pages else ""
    return (
        f"这一版**没有成功导出成品**{where}——自动修复两轮后仍有版式细节没通过校验"
        "（常见是文字越界、分组滤镜、特殊字体样式）。源文件都保留了，没有丢。\n\n"
        "接下来可以这样选：\n"
        "1. 回复「**继续修复**」：我再自动修一轮并重新导出；\n"
        "2. 告诉我可放宽的地方（例如「文字允许小一点」「这页内容精简一半」），我改后立即重导；\n"
        "3. 只想先要一部分：回复「**先导出前 N 页**」，我删掉其余页再出片。\n\n"
        "小提示：一次把页数和每页要点说清楚，能明显减少来回修改。"
    )


def _tool_trace(plan_outcome) -> list[dict]:
    """规划层调用轨迹 → 可持久化/可展示的精简结构（整条裁剪，避免截断成半行）。

    args 里的大文本（如 write_skill_file 的 SVG content）截断展示：trace 是给用户看的
    执行摘要，不是文件备份；真实内容已在包内文件里。
    """
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
        args = s.args or {}
        if isinstance(args, dict):
            args = {k: (v[:600] + "…(已截断)" if isinstance(v, str) and len(v) > 600 else v)
                    for k, v in args.items()}
        trace.append({
            "seq": i + 1,
            "tool": s.tool,
            "args": args,
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
    # 先收集该会话产出文件的下载 url（在删消息前），用于连带清理 _outputs 产物
    output_urls: list[str] = []
    try:
        msgs = agent_crud.list_messages(db, conversation_id=conv.id, limit=500)
        import re as _re

        for m in msgs:
            if not isinstance(m.citations, dict):
                continue
            for t in (m.citations.get("tools") or []):
                for f in (t.get("files") or []) if isinstance(t, dict) else []:
                    u = f.get("url") if isinstance(f, dict) else None
                    if u:
                        output_urls.append(u)
    except Exception:
        pass
    agent_crud.delete_conversation(db, conv)
    # 清理该会话的隔离工作区（conversations/conv_xxx）+ 产出文件（_outputs/run），不留垃圾
    try:
        from app.services import skill_bundle

        skill_bundle.cleanup_conversation(user.id, conv_id, output_urls=output_urls)
    except Exception:
        pass
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
    # 会话粘性：本会话「近几轮已经在做 PPT/用 Skill」时，把「可以给我了吗/确认/好的/开始吧」
    # 以及「决定保留全部 24 页；要学生上机跟敲」这类**延续指令**也纳入 Skill 路径，
    # 避免它们被当成普通闲聊、模型只空口应「好」却不真正执行（「空话不干活」根因）。
    _FOLLOWUP_WORDS = (
        "保留", "全部", "决定", "确定", "确认", "就用", "按照", "按这个", "按上面", "按你的",
        "继续", "接着", "开始做", "开始生成", "出片", "跟敲", "上机", "就要", "可以了", "没问题",
        "就这样", "改一下", "调整", "换成", "加一", "删掉", "补充",
    )
    if not skill_mode and has_skill_tools and _msg_stripped:
        try:
            recent = agent_crud.recent_messages(db, conversation_id=conv.id, limit=6)
            had_tools = False
            for m in recent:
                if m.role != "assistant" or not isinstance(m.citations, dict):
                    continue
                _tools = [t.get("tool") for t in (m.citations.get("tools") or []) if isinstance(t, dict)]
                if any(t in ("write_skill_file", "run_skill_script", "delete_skill_file") for t in _tools):
                    had_tools = True
                    break
            # 短确认句，或明显是在延续既有 PPT 任务的指令，都进执行链路
            if had_tools and (len(_msg_stripped) <= 40
                              or any(w in _msg_stripped for w in _FOLLOWUP_WORDS)):
                skill_mode = True
        except Exception:
            pass
    # 多轮续作兜底：本会话已生成过 PPT 项目 → 一律走 Skill 链路（带基线 + 长预算）。
    # 否则「补充讲师/日期/条款」这类较长内容更新会被当成普通聊天，丢掉基线后越改越差。
    conv_ppt_block = ""
    prev_ppt_pages: list[str] = []
    prev_ppt_count = 0
    if has_skill_tools:
        try:
            _ppt_data = _conv_ppt_data(db, user, conv.id)
            conv_ppt_block = _render_conv_ppt_block(_ppt_data)
            if _ppt_data:
                prev_ppt_pages = [t for _, t in _ppt_data[0]["pages"]]
                prev_ppt_count = _ppt_data[0]["n_pages"]
        except Exception:
            conv_ppt_block = ""
        if conv_ppt_block and not skill_mode:
            skill_mode = True
    # PPT 二次编辑：把「本会话已生成的 PPT（基线）+ 包内已有 pptx」注入上下文，
    # 让模型能「就地改上一版」而不是重造；同时明确区分「接着调整」与「重新做」。
    if skill_mode and has_skill_tools:
        if conv_ppt_block:
            mem_block = (mem_block + "\n\n" + conv_ppt_block).strip() if mem_block else conv_ppt_block
    if skill_mode and agent_tools.looks_like_ppt_edit(_msg_stripped):
        try:
            pptx_block = _existing_pptx_block(db, user)
            if pptx_block:
                mem_block = (mem_block + "\n\n" + pptx_block).strip() if mem_block else pptx_block
        except Exception:
            pass
    plan_box: dict = {}
    plan_thread = None
    # 实时执行事件队列：规划线程每完成/开始一步就 push 到这里，event_stream 边等边推给前端
    import queue as _live_queue_mod
    live_queue: "_live_queue_mod.Queue" = _live_queue_mod.Queue()
    # 重试会让规划器内部的 seq 从 1 重新计数，这里做单调映射，避免前端按 seq 去重时互相覆盖
    _seq_state = {"offset": 0, "max": 0}

    def _emit_step(step, seq, phase):
        try:
            if phase == "start" and seq <= _seq_state["max"]:
                _seq_state["offset"] = _seq_state["max"]  # 进入新一轮（重试）
            gseq = _seq_state["offset"] + seq
            if phase == "done":
                _seq_state["max"] = max(_seq_state["max"], gseq)
            live_queue.put_nowait({"phase": phase, "seq": gseq, "step": step})
        except Exception:
            pass
    # 页级编辑意图（插页/删页/改页/调序）：用于「零写入自动重试」与「改动计划回执」
    _PAGE_EDIT_HINTS = (
        "插入", "插到", "加页", "加一页", "加两页", "加三页", "新增", "新增页",
        "删除", "删掉", "去掉这页", "修改第", "改第", "换掉第", "调顺序", "移到第",
    )
    _is_page_edit = bool(_msg_stripped) and (
        agent_tools.looks_like_ppt_edit(_msg_stripped)
        or any(w in _msg_stripped for w in _PAGE_EDIT_HINTS)
    )
    # 本轮是否在要「产出/修改成品」（用于无成品时的兜底话术判断）
    _PRODUCE_HINTS = ("出片", "生成PPT", "生成一份", "生成一套", "做一份", "做一套", "导出", "PPT", "ppt",
                       "幻灯片", "加页", "插页", "删页", "修复", "重试", "再来一版", "继续做")
    _wants_deliverable = bool(_msg_stripped) and any(w in _msg_stripped for w in _PRODUCE_HINTS)
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

                def _plan_once(msg_text: str, hist_items: list[tuple[str, str]]):
                    if skill_mode:
                        # Skill 干活（读文件/跑脚本/取产物）：多轮 + 长预算，沙箱执行慢也不掐断
                        return agent_planner.plan_and_run(
                            sdb, suser, msg_text, conversation_id=conv.id, agent_id=conv.agent_id,
                            max_rounds=16, max_calls=30, time_budget_ms=600000,
                            history=hist_items, context_block=conv_ppt_block or None,
                            on_step=_emit_step,
                        )
                    return agent_planner.plan_and_run(
                        sdb, suser, msg_text, conversation_id=conv.id, agent_id=conv.agent_id,
                        history=hist_items, context_block=conv_ppt_block or None,
                        on_step=_emit_step,
                    )
                # 线程不继承 contextvar：在此重新压入教师个人模型配置，否则规划模型拿不到 Key
                with _llm_ctx.use_llm(resolved):
                    # 最近几轮对话：多轮 Skill 续作（「继续用深靛」「加页」）必须有上文，
                    # 否则规划器会把短确认句当成新任务，跑到无关主题/旧项目上（错片根因）。
                    hist: list[tuple[str, str]] = []
                    try:
                        for m in agent_crud.recent_messages(sdb, conversation_id=conv.id, limit=4):
                            if m.role == "user" and (m.content or "").strip() == _msg:
                                continue  # 当前这条消息单独作为本轮输入，避免重复
                            content = (m.content or "").strip()
                            if m.role == "assistant":
                                # 历史里的伪工具调用代码块/乱码会污染后续轮次（越改越差）：
                                # 先净化再喂给规划器。
                                content = llm.strip_toolcall_markup(content)[:800]
                            if content:
                                hist.append((m.role, content))
                    except Exception:
                        hist = []
                    out = _plan_once(_msg, hist)
                    _attempts = 0

                    def _mutated(o) -> bool:
                        return any(
                            st.tool in ("write_skill_file", "delete_skill_file", "run_skill_script")
                            for st in o.steps
                        )

                    # ① 规划零写入（只 list/read 就停，正文只剩「开始执行…」的旁白）：自动重试，附带执行约束。
                    # 触发条件：Skill 任务 + 明确想推进（页级编辑 / 成品诉求 / **带动作词的短确认**）+ 零写入。
                    # 注意：不能把「好的/谢谢/收到/嗯」这类寒暄当确认——否则会给一句客套话强行重造整份 PPT。
                    # 只有短句里出现「按这个/开始/继续/执行/出片…」才视为「让我动手」。
                    _ACTION_WORDS = ("按这个", "按你的", "就按", "开始", "继续", "执行", "来吧", "开做",
                                     "动手", "出片", "可以", "确定", "好的开始", "go", "ok开始")
                    _confirm_action = bool(_msg_stripped) and len(_msg_stripped) <= 16 and any(
                        w in _msg_stripped.lower() for w in _ACTION_WORDS
                    )
                    if skill_mode and (_is_page_edit or _wants_deliverable or _confirm_action) \
                            and not _mutated(out) and _attempts < 2:
                        logger.info("skill task planned no mutations → forced retry (edit=%s deliverable=%s confirm=%s conv=%s)",
                                    _is_page_edit, _wants_deliverable, _confirm_action, conv.id)
                        _attempts += 1
                        _exec_hint = (
                            "① 先用 2-4 行给出页级改动计划（插入/删除/修改哪些页、每页标题与要点）；"
                            "② 实际用 write_skill_file 写入新增或修改的页（插入页用「插入位置序号+描述」"
                            "命名，如 21x_xinsai.svg），删页用 delete_skill_file 删除对应 svg 文件；"
                            "③ 用 run_skill_script 跑 build 出片。禁止只读文件、禁止只回文字。"
                            if _is_page_edit else
                            "① 直接用 write_skill_file 逐页写入 SVG（沿用本会话已定主题与项目名）；"
                            "② 写完后必须用 run_skill_script 跑 build 出片并拿到 pptx 下载链接。"
                            "禁止只读文件、禁止只回一句计划或旁白、禁止只说不写。"
                        )
                        out = _plan_once(
                            _msg + "\n\n【执行约束·本轮必须遵守】上一轮只读/未执行，等于没做。本轮必须真正动手："
                                   + _exec_hint,
                            hist,
                        )
                    # ② 本轮跑过 build 但没拿到 pptx（门禁未过）：带上具体报错自动再修一轮，
                    # 不让用户反复说「出片」而系统一直不给结果。
                    if (
                        skill_mode
                        and _attempts < 2
                        and not _has_pptx_result(out)
                        and any(st.tool == "run_skill_script" for st in out.steps)
                    ):
                        err_lines = _build_error_lines(out)
                        digest = ("\n".join(err_lines))[:800] or "（未捕获到具体报错行）"
                        logger.info("build failed without pptx → auto repair retry (conv=%s)", conv.id)
                        _attempts += 1
                        out = _plan_once(
                            _msg + "\n\n【修复约束·自动重试】上一轮 build 未通过质量门禁，具体报错：\n"
                                   + digest
                                   + "\n请按报错定位到具体页，只修这些页（write_skill_file 覆盖）后重新 run_skill_script build。"
                                   "本轮结束时必须要么给出 pptx 下载链接，要么用通俗中文说明：做到哪一步、卡在哪些页/哪类问题、"
                                   "建议用户怎么调整（不要输出内部过程旁白、不要只说下一步计划）。",
                            hist,
                        )
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
    plan_note_holder: list[str] = [""]

    def _frame(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    def event_stream():
        # 最外层兜底：任何未预期异常都必须以 error 帧结束，绝不能让前端无限卡"接收中"
        nonlocal plan_outcome, mem_block, tool_names, system, prompt
        try:
            # 等后台规划：边等边把每一步执行结果实时推给前端（tool_step 帧），
            # 不再是「整轮结束才一次性看到全链路」的黑盒等待；空闲约 5s 仍发一次心跳。
            if plan_thread is not None:
                import time as _pt

                t_plan = _pt.monotonic()
                t_beat = t_plan
                while plan_thread.is_alive():
                    try:
                        ev = live_queue.get(timeout=0.2)
                    except Exception:
                        ev = None
                    if ev is not None:
                        step = ev.get("step")
                        if step is not None:
                            yield _frame({"tool_step": {
                                "phase": ev.get("phase"), "seq": ev.get("seq"),
                                "tool": step.tool, "args": step.args, "ok": step.ok,
                                "summary": (agent_planner.compact_result(step.result, 700)
                                            if step.ok else (step.error or "执行失败")),
                            }})
                    now = _pt.monotonic()
                    if plan_thread.is_alive() and now - t_beat >= 5:
                        t_beat = now
                        el = int(now - t_plan)
                        doing = "正在执行 Skill（读文件/跑脚本/取产物）" if skill_mode else "正在查询业务数据"
                        yield _frame({"phase": {"key": "plan", "label": f"{doing}（已用 {el} 秒）"}})
                    if plan_thread.is_alive():
                        plan_thread.join(timeout=0.2)
                # 规划结束后把队列里残余的事件全部推完
                while True:
                    try:
                        ev = live_queue.get_nowait()
                    except Exception:
                        break
                    step = ev.get("step")
                    if step is not None:
                        yield _frame({"tool_step": {
                            "phase": ev.get("phase"), "seq": ev.get("seq"),
                            "tool": step.tool, "args": step.args, "ok": step.ok,
                            "summary": (agent_planner.compact_result(step.result, 700)
                                        if step.ok else (step.error or "执行失败")),
                        }})
                got = plan_box.get("outcome")
                if isinstance(got, agent_planner.PlanOutcome):
                    plan_outcome = got
            tool_names = plan_outcome.tools
            # 页级改动回执：确定性对比「改动前页清单 vs 本轮成品页清单」，
            # 让正文开头一定有计划（新增/删除了哪些页、插在第几页后、页数变化），
            # 不依赖模型自觉输出，也避免口径与实际成品不一致。
            if skill_mode and _is_page_edit and plan_outcome.steps:
                try:
                    derived0 = _derive_spec_from_tools(plan_outcome)
                    new_titles = [str(o.get("title") or "") for o in (derived0.get("outline") or [])]
                    plan_note_holder[0] = _page_diff_note(prev_ppt_pages, new_titles)
                except Exception:
                    plan_note_holder[0] = ""
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
            if skill_mode:
                # 正文禁止出现工具调用语法（如 <write_skill_file> / run_skill_script(...)）：
                # 它是「执行动作」不是「聊天内容」，只能走工具调用；写进正文会被系统剔除并改为真实执行，
                # 用户不该看到原始 XML/SVG 载荷。这里从源头约束 + 下游兜底双保险。
                prompt = (
                    prompt
                    + "\n\n【输出铁律】绝对不要在正文里书写任何工具调用语法或原始文件载荷——包括但不限于 "
                    "<write_skill_file>、</write_skill_file>、<run_skill_script>、read_skill_file(...)、"
                    "```svg 代码块、path:/content:/skill: 这类字段。执行动作由系统工具完成；"
                    "你只需用**自然语言**告诉用户「做了什么、结果如何、下一步」：比如「已生成 22 页成品，"
                    "点下方下载」。若还需要执行动作，直接发起工具调用，不要用文字模拟。"
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
                        # 上传的图片 → data URL 多模态直传（deepseek-flash 等视觉模型可直读）；
                        # 模型/网关不接受图片输入时自动降级为纯文本，不让整轮对话失败。
                        imgs = _image_data_urls(body.attachments or [])
                        if imgs:
                            try:
                                for chunk in llm.stream_text(system, prompt, images=imgs):
                                    box.put(("delta", chunk))
                                box.put(("end", None))
                                return
                            except Exception as e:  # noqa: BLE001
                                if not _looks_like_vision_rejection(e):
                                    raise
                                logger.warning("vision stream rejected, fallback text-only: %s", e)
                                box.put(("delta", "（当前模型未接受图片输入，本轮按图片文件名与文字理解；如需识图请改用支持视觉的模型，如 deepseek-flash。）\n\n"))
                        for chunk in llm.stream_text(system, prompt):
                            box.put(("delta", chunk))
                        box.put(("end", None))
                    except Exception as e:  # noqa: BLE001
                        logger.exception("chat stream failed conv=%s", conv.id)
                        box.put(("error", e))

            t0 = _time.monotonic()
            threading.Thread(target=_produce, daemon=True).start()
            started = False
            # 显示层过滤：模型把 <write_skill_file>…</write_skill_file> 当正文吐出时，
            # 实时流里也不给用户看原始块；full 仍保留原文用于「真实执行 + 轨迹」。
            disp_filter = llm.XmlToolStreamFilter()
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
                    tail = disp_filter.flush()
                    if tail:
                        yield _frame({"delta": tail})
                    break
                if not started:
                    started = True
                    yield _frame({"phase": {"key": "stream", "label": "接收并整理结果"}})
                full += payload
                shown = disp_filter.feed(payload)
                if shown:
                    yield _frame({"delta": shown})
        except Exception as e:  # noqa: BLE001
            yield _frame({"error": llm.friendly_llm_error(e)})
            return
        # 持久化助手回复 + 异步增量提炼长期记忆（不阻塞流式）
        # 次序很重要：先从**原始**正文提取伪工具块（下面净化会把这些块连同载荷一起剔除），
        # 再净化原生标记、再按需真实执行 rescue 块。
        _pseudo_blocks = _extract_pseudo_tool_blocks(full)
        full = llm.strip_toolcall_markup(full)
        if _pseudo_blocks:
            # 防重复执行/覆盖：若规划器本轮**已经**写页/出片，正文里的同名伪块多半是模型「复述」，
            # 再执行一次可能把已产出的好成品用不完整的一份覆盖掉，也可能白跑一次 build。
            # 因此只在「规划器本轮零写入」时才 rescue 执行；无论如何都把这些块从正文剔除。
            _already_mutated = any(
                s.tool in ("write_skill_file", "delete_skill_file", "run_skill_script")
                for s in plan_outcome.steps
            )
            if not _already_mutated:
                try:
                    _rescue_steps = _execute_rescue_blocks(
                        db, user, conv.id, conv.agent_id, _pseudo_blocks, on_step=_emit_step
                    )
                    if _rescue_steps:
                        plan_outcome.steps.extend(_rescue_steps)
                        logger.info("pseudo-tool rescue executed %s blocks (conv=%s)",
                                    len(_rescue_steps), conv.id)
                except Exception:
                    logger.exception("pseudo-tool rescue failed (conv=%s)", conv.id)
                # rescue 是在主线程同步执行的：把队列里的事件即时转成 tool_step 帧，
                # 让写页/出片也实时可见（否则用户在「整理结果」阶段看不到进展）。
                while True:
                    try:
                        _ev = live_queue.get_nowait()
                    except Exception:
                        break
                    _st = _ev.get("step")
                    if _st is not None:
                        yield _frame({"tool_step": {
                            "phase": _ev.get("phase"), "seq": _ev.get("seq"),
                            "tool": _st.tool, "args": _st.args, "ok": _st.ok,
                            "summary": (agent_planner.compact_result(_st.result, 700)
                                        if _st.ok else (_st.error or "执行失败")),
                        }})
            full = _strip_pseudo_tool_blocks(full)
        # 页级改动回执置顶：模型正文若没讲清「加了/删了哪些页、插在哪」，这里兜底补上，
        # 保证用户每轮都能看到与成品一致的改动计划。
        if plan_note_holder[0] and "改动计划（已执行）" not in full:
            full = (plan_note_holder[0] + ("\n\n" + full.strip() if full.strip() else ""))
        # 空/过短回复兜底：Skill 任务已真正产出文件，但模型正文过短或缺下载链接时，
        # 用工具轨迹合成一段完整交付说明（页数+逐页标题+下载链接），杜绝「空回复/输出不完整」。
        # 另外：正文自述的页数与成品不符（如说 19 页实际 22 页）时，也追加校正清单，
        # 保证「对话正文 = 工作区大纲 = 实际成品」三处页数/标题对齐。
        if plan_outcome.steps and any(
            s.tool in ("write_skill_file", "run_skill_script") for s in plan_outcome.steps
        ):
            _syn, _has_pptx = _synthesize_ppt_summary(plan_outcome)
            _txt = (full or "").strip()
            _need = (len(_txt) < 120) or (_has_pptx and ".pptx" not in _txt and "下载" not in _txt)
            if _syn and not _need and _has_pptx:
                import re as _re_n

                _nm = _re_n.search(r"已生成 \*\*(\d+) 页\*\*", _syn)
                if _nm:
                    _n = _nm.group(1)
                    if f"{_n} 页" not in _txt and f"{_n}页" not in _txt:
                        _need = True
            if _need and _syn:
                full = (full.rstrip() + "\n\n" + _syn) if _txt else _syn
        # 无成品兜底：PPT/Skill 任务跑了但没导出 pptx 时，绝不把「内部过程旁白」丢给用户。
        #  - 旁白式回复（「我先把报告读出来/再重跑」）或空内容 → 换成可执行的下一步说明；
        #  - 已自愈两轮仍失败时，正文里也不允许出现空洞的成功口径（有「已生成/下载」但无成品 → 追加真实状态）。
        if (skill_mode and _wants_deliverable) and not _has_pptx_result(plan_outcome):
            _notice = _pptx_failure_notice(plan_outcome)
            _txt2 = (full or "").strip()
            if (_looks_like_narration(_txt2) or len(_txt2) < 80
                    or "构建未完成" in _txt2 or "质量检查" in _txt2):
                full = _notice
            elif "下载" in _txt2 or "已生成" in _txt2:
                full = _txt2 + "\n\n" + _notice
        options = agent_chat.extract_options(full)
        spec = agent_chat.extract_spec(full)
        # 大纲与成品对齐：只要本轮有 Skill 执行轨迹，**以工具产物为准**刷新大纲/成果。
        # 模型正文里自拟的 json 大纲可能与实际页不一致（标题对不上），工具轨迹才是真实成品。
        if plan_outcome.steps:
            derived = _derive_spec_from_tools(plan_outcome)
            if derived:
                if spec.get("outline"):
                    # 保留模型给出的主题等元信息，但大纲/幻灯片以真实产物覆盖
                    spec = {**spec, "outline": derived["outline"], "slides": derived["slides"]}
                else:
                    spec = derived
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
