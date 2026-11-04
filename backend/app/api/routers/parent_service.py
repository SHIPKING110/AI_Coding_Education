"""家长客服 API（P0，无 Redis）：

- POST /parent-service/auth/wechat   小程序 code → openid → 家长 JWT
- POST /parent-service/chat          问答（配额→高风险→家长域 RAG→生成→落账本）
- POST /parent-service/threads/{id}/escalate  家长主动转人工
- GET  /parent-service/threads/{id}/messages  本人会话消息
- GET  /teacher/service/threads      教师接待列表（escalated 置顶）
- GET  /teacher/service/threads/{id}/messages
- POST /teacher/service/threads/{id}/reply
- POST /teacher/service/threads/{id}/close

家长域检索隔离：retrieve() 的 collected_ids 只传家长版白名单文档，
零命中不编造；高风险命中直接转人工，不调 LLM。
"""

from __future__ import annotations

import os
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_teacher_permission
from app.core import security
from app.core.config import get_settings
from app.core.database import get_db
from app.crud import parent_service as ps
from app.models.parent_service import (
    ROLE_ASSISTANT,
    ROLE_STAFF,
    ROLE_USER,
    THREAD_ESCALATED,
    ParentServiceThread,
)
from app.models.user import Role, User
from app.services import rag, rag_trace
from app.services.llm import LLMConfigError

parent_router = APIRouter(prefix="/parent-service", tags=["parent-service"])
teacher_router = APIRouter(prefix="/teacher/service", tags=["teacher-service"])

settings = get_settings()
_optional_bearer = HTTPBearer(auto_error=False)

# 教学服务模块键：对话模型与 Rerank 共用 teacher_module_models.parent_service 映射。
# - 对话：家长登录用本人映射；匿名用会话归属教师（thread.owner_teacher_id）映射，均无则走默认→系统；
# - Rerank：系统级 embedding 决定向量空间（全校统一）；教师级 rerank 按归属教师取，未配则退化单层召回。
PARENT_MODULE = "parent_service"

# 家长客服垂直化 system：业务边界（课程/课时/请假/活动/成长）+ 非业务婉拒 + 输出格式约束。
# 费用/退费/安全类由词表前置拦截（不调 LLM），此处是第二道语义护栏。
PARENT_SYS = (
    "你是少儿编程培训机构的家长客服助手「课程小助手」，亲切、简洁、有依据。\n"
    "【业务范围】只回答：课程内容与安排、课时与余额查询指引、请假与补课流程、"
    "校区活动通知、孩子学习成长情况查询指引。\n"
    "【越界处理】超出范围的问题（如闲聊、通用知识、作业代写、其他机构比较），"
    "礼貌婉拒并引导回业务或转人工，绝不展开回答。\n"
    "【高风险】涉及退费/收费/价格/安全/伤害/投诉/报警/律师等，一律只回复固定话术："
    "「这个问题需要老师人工确认，已为您转接人工老师，请稍候。」并引导转人工。\n"
    "【输出格式】200字内，分点不超过3条；有政策依据时末尾注明「依据：《标题》」；"
    "不编造政策细节、费用数字与时间；不知道就说不知道并给转人工入口。"
)

# 输出安全护栏：命中任一模式 → 答案作废、转人工（防模型绕过词表前置拦截）。
UNSAFE_PATTERNS = ps.UNSAFE_PATTERNS

# 业务/非业务粗分类关键词（纯规则前置，LLM 只做兜底表达）
NON_BIZ_HINTS = ps.NON_BIZ_HINTS


def _unsafe_output(answer: str) -> str | None:
    """输出护栏：返回命中的风险片段，否则 None（实现见 crud，便于单测）。"""
    return ps.unsafe_output(answer)


def _non_biz_hint(content: str) -> bool:
    return ps.non_biz_hint(content)


class WechatLoginIn(BaseModel):
    code: str = Field(min_length=1)
    nickname: str = ""


class ChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    thread_id: uuid.UUID | None = None
    anon_key: str = Field(default="", max_length=64)


class ReplyIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


def _optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """可选鉴权：有 token 取家长用户，无 token 返回 None（匿名）。"""
    if credentials is None:
        return None
    try:
        payload = security.decode_token(credentials.credentials, expected_type="access")
        subject = payload.get("sub")
    except Exception:
        return None
    if subject is None:
        return None
    from app.crud import user as user_crud

    try:
        return user_crud.get_by_id(db, uuid.UUID(str(subject)))
    except Exception:
        return None


def _code2session(code: str) -> dict:
    """微信 code 换 openid；AppID/Secret 只读环境变量，不入库。"""
    appid = (os.environ.get("WECHAT_APPID") or getattr(settings, "WECHAT_APPID", "") or "").strip()
    secret = (os.environ.get("WECHAT_SECRET") or getattr(settings, "WECHAT_SECRET", "") or "").strip()
    if not appid or not secret:
        raise HTTPException(status_code=500, detail="未配置微信小程序 AppID/Secret，请联系管理员")
    try:
        r = httpx.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={"appid": appid, "secret": secret, "js_code": code, "grant_type": "authorization_code"},
            timeout=10,
        )
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"微信登录服务暂不可用：{e}") from e
    if not data.get("openid"):
        raise HTTPException(status_code=502, detail=f"微信登录失败：{data.get('errmsg', '未知错误')}")
    return data


@parent_router.post("/auth/wechat")
def wechat_login(body: WechatLoginIn, db: Session = Depends(get_db)) -> dict:
    data = _code2session(body.code.strip())
    user = ps.find_or_create_parent_by_openid(db, openid=data["openid"], nickname=body.nickname.strip())
    token = security.create_access_token(str(user.id))
    return {"access_token": token, "user": {"id": str(user.id), "role": user.role, "name": user.name}}


def _render_tool_answer(name: str, result: dict) -> str | None:
    """工具结果 → 家长话术（确定性渲染，数字原样透出，零幻觉）。

    无数据返回 None（调用方走"诚实告知+转人工"分支）。
    """
    if name == "balance":
        rows = result.get("students") or []
        if not rows:
            return None
        lines = []
        for s in rows:
            warn = "（余额不足10，请及时续费）" if s.get("low") else ""
            lines.append(f"• {s['student']}：剩余 {s['balance']} 课时{warn}")
        return "查到课时余额如下：\n" + "\n".join(lines)
    if name == "schedule":
        items = result.get("items") or []
        if not items:
            return None
        lines = []
        for it in items[:8]:
            st = (it.get("start") or "")[:16].replace("T", " ")
            lines.append(f"• {st}｜{it.get('student','')}《{it.get('class','')}》{it.get('teacher','')}老师")
        more = f"\n（共{len(items)}节，仅显示前8节）" if len(items) > 8 else ""
        return "未来7天课表：\n" + "\n".join(lines) + more
    if name == "feedbacks":
        items = result.get("items") or []
        if not items:
            return None
        lines = [f"• {it.get('student','')}：{it.get('summary','')}" for it in items[:3]]
        return "老师最近反馈摘要：\n" + "\n".join(lines)
    if name == "history":
        rows = result.get("students") or []
        if not rows:
            return None
        blocks = []
        for s in rows:
            head = f"{s['student']}共上过 {s['total']} 节课"
            detail = f"（到课 {s['attended']} 节，请假 {s['leave']} 节）" if s.get("attended") or s.get("leave") else ""
            lines = [head + detail]
            for it in (s.get("lessons") or [])[:6]:
                st = (it.get("start") or "")[:16].replace("T", " ")
                topic = it.get("topic") or ""
                topic_part = f" 课题：{topic}" if topic else ""
                lines.append(
                    f"• {st}｜《{it.get('class','')}》{it.get('teacher','')}老师 · {it.get('attendance','')}{topic_part}"
                )
            if len(s.get("lessons") or []) > 6:
                lines.append(f"…（仅显示最近6节，共 {s['total']} 节）")
            blocks.append("\n".join(lines))
        return "上课历史：\n" + "\n\n".join(blocks)
    return None


def _thread_out(th: ParentServiceThread) -> dict:
    return {
        "id": str(th.id), "status": th.status, "risk_flag": bool(th.risk_flag),
        "created_at": th.created_at.isoformat() if th.created_at else None,
        "updated_at": th.updated_at.isoformat() if th.updated_at else None,
    }


@parent_router.post("/chat")
def parent_chat(
    body: ChatIn, db: Session = Depends(get_db), user: User | None = Depends(_optional_user)
) -> dict:
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="请输入问题内容")
    parent_id = user.id if user is not None and user.role == Role.PARENT.value else None
    anon_key = (body.anon_key or "").strip() if parent_id is None else ""
    if parent_id is None and not anon_key:
        raise HTTPException(status_code=422, detail="匿名咨询请携带设备标识（anon_key）")

    # 1) 配额（DB 计数口径：当日 user 消息数；P1 再迁 Redis）
    anon_limit, parent_limit = ps.quota_limits(db)
    used = ps.count_today_user_messages(db, parent_id=parent_id, anon_key=anon_key or None)
    limit = parent_limit if parent_id is not None else anon_limit
    if used >= limit:
        tip = (
            "今日咨询次数已用完，请明日再来，或点击转人工咨询老师。"
            if parent_id is not None
            else "匿名体验次数已用完，请绑定微信后继续咨询。"
        )
        raise HTTPException(status_code=429, detail=tip)

    # 2) 会话 + 存用户消息（归属教师在建会话时解析，用于模块映射+Rerank）
    # 2a) 惰性清理：闲置超阈值的 open/escalated 会话自动关闭（教师端列表也会触发）
    ps.auto_close_stale(db)
    th = ps.get_or_create_thread(db, parent_id=parent_id, anon_key=anon_key or None, thread_id=body.thread_id)
    if parent_id is not None and th.parent_id != parent_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    if parent_id is None and th.anon_key != anon_key:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    ps.add_message(db, thread_id=th.id, role=ROLE_USER, content=content)

    # 3) 高风险 → 直接转人工，不调 LLM
    words = ps.risk_words(db)
    hit = ps.hit_risk_word(content, words)
    if hit is not None:
        ps.escalate(db, th, risk_word=hit)
        ps.add_message(
            db, thread_id=th.id, role=ROLE_ASSISTANT,
            content=f"您的问题涉及「{hit}」，已为您转接人工老师，请稍候，老师会尽快回复。",
        )
        return {"thread": _thread_out(th), "answer": None, "refs": [], "escalated": True, "risk_word": hit}

    # 4) 意图路由（分层，零 token 短路）：SMALLTALK/CAPABILITY/TOOL/MENU_FOLLOWUP/POLICY/UNKNOWN
    # 只有 POLICY 与 MENU_FOLLOWUP 会走到 RAG+LLM；其余确定性回复，避免浪费 Token。
    from app.services import parent_intent as pi

    history_msgs = ps.list_messages(db, thread_id=th.id)[:-1][-6:]
    # 跨段轻量记忆：本段首条消息时，注入上一段（7 天内已关闭）尾部 4 条
    prev_tail: list[dict] = []
    if len(history_msgs) == 0:
        prev_tail = ps.previous_segment_tail(db, parent_id=parent_id, anon_key=anon_key or None)
    last_user_q = next((m.content for m in reversed(history_msgs) if m.role == ROLE_USER), "")
    last_assistant = next((m.content for m in reversed(history_msgs) if m.role == ROLE_ASSISTANT), "")
    # 上轮是否来自查询工具（diag 记 tool 名）：用于"对应课题呢/具体哪些"这类跟随问句
    # 直接重跑上轮工具（补全后自然带课题），而不是误杀进兜底。
    last_tool = ""
    for m in reversed(history_msgs):
        if m.role == ROLE_ASSISTANT:
            d = m.retrieval_diag or {}
            if d.get("tool"):
                last_tool = str(d.get("tool"))
            break
    intent = pi.classify(
        content, last_assistant=last_assistant, last_user=last_user_q, last_tool=last_tool
    )
    intent_name = intent["intent"]

    # 4a) 零 token 短路：越界/能力清单/寒暄
    if intent_name == pi.UNKNOWN:
        fallback = pi.UNIFIED_FALLBACK
        ps.add_message(db, thread_id=th.id, role=ROLE_ASSISTANT, content=fallback,
                       retrieval_diag={"intent": pi.UNKNOWN, "reason": intent.get("reason")})
        return {"thread": _thread_out(th), "answer": fallback, "refs": [], "escalated": False,
                "kind": "fallback", "intent": pi.UNKNOWN}
    if intent_name == pi.CAPABILITY:
        reply = pi.CAPABILITY_REPLY
        ps.add_message(db, thread_id=th.id, role=ROLE_ASSISTANT, content=reply,
                       retrieval_diag={"intent": pi.CAPABILITY})
        return {"thread": _thread_out(th), "answer": reply, "refs": [], "escalated": False,
                "kind": "capability", "intent": pi.CAPABILITY}
    if intent_name == pi.SMALLTALK:
        reply = pi.SMALLTALK_REPLY
        ps.add_message(db, thread_id=th.id, role=ROLE_ASSISTANT, content=reply,
                       retrieval_diag={"intent": pi.SMALLTALK})
        return {"thread": _thread_out(th), "answer": reply, "refs": [], "escalated": False,
                "kind": "smalltalk", "intent": pi.SMALLTALK}
    if intent_name == pi.CLARIFY:
        reply = pi.CLARIFY_REPLY
        ps.add_message(db, thread_id=th.id, role=ROLE_ASSISTANT, content=reply,
                       retrieval_diag={"intent": pi.CLARIFY})
        return {"thread": _thread_out(th), "answer": reply, "refs": [], "escalated": False,
                "kind": "clarify", "intent": pi.CLARIFY}

    # 4b) 查询工具（登录家长专属）：余额/历史课/课表/反馈走确定性数据，不走 RAG；
    # 匿名无工具（倒逼绑定）。学生范围由后端反查，绝不信任前端输入。
    tool_name = intent.get("tool") if intent_name == pi.TOOL else None
    if tool_name is None and parent_id is not None and user is not None:
        from app.services import parent_tools

        tool_name = parent_tools.pick_tool(content)  # 菜单跟进等场景兜底再扫一次
    if tool_name is not None and parent_id is not None and user is not None:
        from app.services import parent_tools

        result = parent_tools.run_tool(db, user, tool_name)
        diag_tool = {"intent": "tool", "tool": tool_name, "ms": result.get("ms", 0)}
        rendered = _render_tool_answer(tool_name, result)
        if rendered is None:
            # 有工具但无数据（未绑定学员/无记录）：统一兜底话术
            fallback = pi.UNIFIED_FALLBACK
            ps.add_message(db, thread_id=th.id, role=ROLE_ASSISTANT, content=fallback, retrieval_diag=diag_tool)
            return {"thread": _thread_out(th), "answer": fallback, "refs": [], "escalated": False,
                    "kind": "fallback", "intent": "tool_empty"}
        ps.add_message(db, thread_id=th.id, role=ROLE_ASSISTANT, content=rendered, retrieval_diag=diag_tool)
        return {"thread": _thread_out(th), "answer": rendered, "refs": [], "escalated": False,
                "kind": f"tool:{tool_name}", "intent": "tool"}

    # 4c) 检索查询：菜单跟进用「上一问+本轮」；其余短跟随问句拼接上一问
    retrieval_query = intent.get("retrieval_query") or content
    if last_user_q and len(content) <= 12 and any(
        k in content for k in ("几次", "哪些", "那个", "还有", "怎么弄", "多久", "什么时候", "呢", "那")
    ):
        retrieval_query = f"{last_user_q} {content}"

    # 5) 家长域 RAG：collected_ids 只传家长版白名单（物理复用 Chroma，逻辑隔离）
    diag: dict = {}
    hits: list[dict] = []
    white = ps.parent_visible_doc_ids(db)
    if not white:
        # 白名单为空（运营尚未勾选）：直接走"零命中不编造"分支，不调检索
        hits = []
    else:
        # RAG owner = 归属教师（教师级 Rerank 按此生效）；匿名/无归属用首个 admin 占位，
        # 白名单 collected_ids 仍保证家长域隔离。
        owner_id = th.owner_teacher_id
        if owner_id is None:
            if parent_id is not None:
                ps_owner = ps.resolve_owner_teacher(db, parent_id)
                if ps_owner is not None:
                    th.owner_teacher_id = ps_owner
                    db.commit()
                    db.refresh(th)
                    owner_id = ps_owner
            if owner_id is None:
                admin = db.query(User).filter(User.role == Role.ADMIN.value).first()
                owner_id = admin.id if admin is not None else None
        if owner_id is None:
            hits = []
        else:
            try:
                with rag_trace.trace_scope(
                    domain="parent_service",
                    user_id=parent_id,
                    owner_id=owner_id,
                    conversation_id=th.id,
                    route="parent_service",
                ):
                    hits = rag.retrieve(
                        retrieval_query, db=db, owner_id=owner_id,
                        collected_ids=white, top_k=5, diag=diag,
                        route_key="parent_service", parent_mode=True,
                    )
            except Exception:
                hits = []
    # 二次硬过滤：doc_id 不在白名单的一律丢弃（防 collected_ids 语义漂移）
    allowed = {str(d) for d in white}
    hits = [h for h in hits if str(h.get("doc_id") or "") in allowed]

    if not hits:
        # 统一兜底话术（零编造；RAG 零命中不再各自造文案）
        fallback = pi.UNIFIED_FALLBACK
        diag["intent"] = intent_name
        _msg = ps.add_message(
            db, thread_id=th.id, role=ROLE_ASSISTANT,
            content=fallback,
            retrieval_diag=diag or None,
        )
        rag_trace.attach_message(diag.get("trace_id"), _msg.id)
        return {
            "thread": _thread_out(th), "answer": fallback,
            "refs": [], "escalated": False, "kind": "fallback", "intent": intent_name,
            "retrieval": rag.retrieval_summary(diag),
        }

    # 6) 生成：走 parent_service 模块映射（管理员/教师可在模型配置页按模块选用）；
    # owner 取登录家长（匿名取占位 admin），失败转人工兜底。
    contexts = "\n\n".join(f"【{h.get('title', '')}】{h.get('text', '')[:800]}" for h in hits[:5])
    hist_txt = "\n".join(
        f"{'家长' if m.role == ROLE_USER else ('老师' if m.role == ROLE_STAFF else '客服')}：{m.content[:200]}"
        for m in history_msgs
    )
    prev_txt = ""
    if prev_tail:
        prev_txt = "上一段对话（供理解上下文）：\n" + "\n".join(
            f"{'家长' if m['role'] == ROLE_USER else '客服'}：{m['content'][:150]}" for m in prev_tail
        ) + "\n\n"
    menu_hint = (
        "家长这条消息是在选择你上一条列表中的若干项，请逐项简要回答；"
        "没有资料的项目直接说明未收录并建议转人工，不要编造引用。\n\n"
        if intent_name == pi.MENU_FOLLOWUP
        else ""
    )
    prompt = (
        menu_hint
        + prev_txt
        + (f"最近对话：\n{hist_txt}\n\n" if hist_txt else "")
        + f"家长问题：{content}\n\n政策资料：\n{contexts}\n\n请按【输出格式】作答（200字内）。"
        "结合最近对话理解指代；末尾注明依据了哪份资料。"
    )
    answer = ""
    tokens: int | None = None
    try:
        from app.services import llm, llm_context

        # 模型归属：归属教师的 parent_service 映射 → 教师默认 → 系统默认；
        # 无归属（未绑定学员/匿名）用占位 owner（admin）的映射/默认/系统，
        # 绝不能用家长自己的 owner_id——家长账号没有模型配置，会直接报 Missing credentials。
        model_owner = th.owner_teacher_id or owner_id
        # 优先使用管理员配置的家长客服共享对话模型；未配置时回退到归属教师映射/系统默认。
        try:
            from app.crud import llm_config as _pllm_crud
            resolved = _pllm_crud.resolve_parent_llm(db)
        except Exception:
            resolved = None
        if resolved is None:
            resolved = llm_context.resolve_override(db, model_owner, PARENT_MODULE)
        with llm_context.use_llm(resolved):
            answer = llm._invoke_with_system(PARENT_SYS, prompt) if hasattr(llm, "_invoke_with_system") else ""
            if not answer:
                from langchain_core.messages import HumanMessage, SystemMessage

                resp = llm._chat_model().invoke([SystemMessage(content=PARENT_SYS), HumanMessage(content=prompt)])
                answer = (resp.content or "").strip() if isinstance(resp.content, str) else str(resp.content)
        tokens = len(answer) // 2 or None
    except (LLMConfigError, Exception):
        ps.escalate(db, th)
        ps.add_message(
            db, thread_id=th.id, role=ROLE_ASSISTANT,
            content="AI 服务暂时不可用，已为您转接人工老师，请稍候。",
            retrieval_diag=diag or None,
        )
        return {"thread": _thread_out(th), "answer": None, "refs": [], "escalated": True}
    # 7) 输出安全护栏：命中风险模式 → 作废答案、转人工（防模型绕过词表前置拦截）
    bad = _unsafe_output(answer)
    if bad is not None:
        ps.escalate(db, th, risk_word=bad)
        safe = "这个问题需要老师人工确认，已为您转接人工老师，请稍候。"
        ps.add_message(db, thread_id=th.id, role=ROLE_ASSISTANT, content=safe, retrieval_diag=diag or None)
        return {"thread": _thread_out(th), "answer": safe, "refs": [], "escalated": True, "guard": bad}
    # 结构化引用（对齐教师端 Agent：去重 + 摘录 + 相似度，前端收起可展开）
    refs: list[dict] = []
    seen: set[str] = set()
    for h in hits:
        did = str(h.get("doc_id") or "")
        if not did or did in seen:
            continue
        seen.add(did)
        refs.append({
            "title": h.get("title", ""), "doc_id": did,
            "excerpt": (h.get("text") or "")[:120],
            "similarity": h.get("similarity"),
        })
        if len(refs) >= 3:
            break
    store_diag = dict(diag or {})
    store_diag["intent"] = intent_name
    store_diag["refs"] = refs
    _msg = ps.add_message(db, thread_id=th.id, role=ROLE_ASSISTANT, content=answer, tokens=tokens, retrieval_diag=store_diag)
    rag_trace.attach_message(store_diag.get("trace_id"), _msg.id)
    return {
        "thread": _thread_out(th), "answer": answer, "refs": refs,
        "citations": {"refs": refs, "summary": rag.retrieval_summary(diag)},
        "escalated": False, "intent": intent_name, "retrieval": rag.retrieval_summary(diag),
    }


@parent_router.post("/threads/{thread_id}/escalate")
def parent_escalate(
    thread_id: uuid.UUID, db: Session = Depends(get_db), user: User | None = Depends(_optional_user)
) -> dict:
    th = db.get(ParentServiceThread, thread_id)
    if th is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if user is not None and th.parent_id is not None and th.parent_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作该会话")
    ps.escalate(db, th)
    return {"thread": _thread_out(th), "escalated": True}


@parent_router.get("/threads/{thread_id}/messages")
def parent_messages(
    thread_id: uuid.UUID, db: Session = Depends(get_db), user: User | None = Depends(_optional_user)
) -> dict:
    th = db.get(ParentServiceThread, thread_id)
    if th is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if user is not None and th.parent_id is not None and th.parent_id != user.id:
        raise HTTPException(status_code=403, detail="无权查看该会话")
    items = [
        {
            "id": str(m.id), "role": m.role, "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "refs": ((m.retrieval_diag or {}).get("refs") or []),
        }
        for m in ps.list_messages(db, thread_id=thread_id)
    ]
    return {"thread": _thread_out(th), "items": items}


# —— 教师端接待 ——

def _staff() -> object:
    return require_teacher_permission("service_reply")


DEFAULT_QUICK_REPLIES: list[tuple[str, str, str]] = [
    ("请假流程", "您好，请假请提前在家长端提交请假申请，或直接回复本消息说明学员姓名、班级和请假日期，老师会为您登记并安排补课。", "教务"),
    ("补课安排", "您好，请假课程可在两周内安排补课。老师会根据班级进度和校区排课为您协调时间，确认后会在家长端同步。", "教务"),
    ("课时余额", "您好，课时余额可在家长端「学习档案」查看；如显示异常，请告知学员姓名，老师为您核对。", "课时"),
    ("上课提醒", "您好，明天上课前请提醒孩子提前 10 分钟到校区，带好水杯；如临时有事请提前请假。", "教务"),
    ("活动通知", "您好，校区近期活动已发布在家长端通知栏，名额有限，建议尽早报名；如需协助报名可直接回复本消息。", "活动"),
    ("学习反馈", "您好，老师会在每次课后更新学习反馈，您可在家长端查看课堂表现、作业与阶段建议。", "教学"),
]


def _qr_out(row) -> dict:
    return {
        "id": str(row.id),
        "title": row.title,
        "content": row.content,
        "category": row.category,
        "enabled": bool(row.enabled),
        "usage_count": int(row.usage_count or 0),
        "sort_order": int(row.sort_order or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _ensure_default_quick_replies(db: Session, owner_id) -> None:
    """首次进入教学服务时给教师初始化一组行业常用术语，可自由增删改。"""
    existing = db.scalar(select(func.count()).select_from(ps.ParentQuickReply).where(
        ps.ParentQuickReply.owner_id == owner_id
    ))
    if int(existing or 0) > 0:
        return
    for i, (title, content, category) in enumerate(DEFAULT_QUICK_REPLIES):
        db.add(ps.ParentQuickReply(
            owner_id=owner_id, title=title, content=content, category=category, sort_order=i
        ))
    db.commit()


class QuickReplyIn(BaseModel):
    title: str = Field(default="", max_length=64)
    content: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="", max_length=32)


class QuickReplyUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=64)
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    category: str | None = Field(default=None, max_length=32)
    enabled: bool | None = None


@teacher_router.get("/quick-replies")
def list_quick_replies(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    _ensure_default_quick_replies(db, user.id)
    return {"items": [_qr_out(r) for r in ps.list_quick_replies(db, owner_id=user.id)]}


@teacher_router.post("/quick-replies", status_code=status.HTTP_201_CREATED)
def create_quick_reply(
    body: QuickReplyIn, db: Session = Depends(get_db), user: User = Depends(_staff())
) -> dict:
    row = ps.create_quick_reply(
        db, owner_id=user.id, title=body.title, content=body.content, category=body.category
    )
    return {"item": _qr_out(row)}


@teacher_router.patch("/quick-replies/{reply_id}")
def update_quick_reply(
    reply_id: uuid.UUID, body: QuickReplyUpdate,
    db: Session = Depends(get_db), user: User = Depends(_staff()),
) -> dict:
    row = ps.get_quick_reply(db, owner_id=user.id, reply_id=reply_id)
    if row is None:
        raise HTTPException(status_code=404, detail="快捷术语不存在")
    row = ps.update_quick_reply(
        db, row, title=body.title, content=body.content,
        category=body.category, enabled=body.enabled,
    )
    return {"item": _qr_out(row)}


@teacher_router.delete("/quick-replies/{reply_id}")
def delete_quick_reply(
    reply_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(_staff())
) -> dict:
    row = ps.get_quick_reply(db, owner_id=user.id, reply_id=reply_id)
    if row is None:
        raise HTTPException(status_code=404, detail="快捷术语不存在")
    ps.delete_quick_reply(db, row)
    return {"deleted": True}


@teacher_router.post("/quick-replies/{reply_id}/use")
def use_quick_reply(
    reply_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(_staff())
) -> dict:
    row = ps.get_quick_reply(db, owner_id=user.id, reply_id=reply_id)
    if row is None:
        raise HTTPException(status_code=404, detail="快捷术语不存在")
    return {"item": _qr_out(ps.use_quick_reply(db, row))}


@teacher_router.get("/config-status")
def config_status(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    """家长客服模型接入状态：LLM 模块映射 / 系统 Embedding / 教师 Rerank / 家长可见文档。"""
    from app.crud import llm_config as llm_crud
    from app.crud import retrieval_config as ret_crud

    # 家长客服 LLM：优先系统共享配置，回退教师映射
    try:
        resolved_llm = llm_crud.resolve_parent_llm(db)
    except Exception:
        resolved_llm = None
    llm_config_id = None
    try:
        row = llm_crud.get_system_parent_llm(db)
        llm_config_id = str(row.config_id) if row and row.config_id else None
    except Exception:
        llm_config_id = None
    parent_embedding = ret_crud.resolve_parent_embedding(db)
    embedding = parent_embedding or ret_crud.resolve_embedding(db)
    rerank = ret_crud.resolve_parent_rerank(db)
    if rerank is None:
        try:
            rerank = ret_crud.resolve_rerank(db, user.id)
        except Exception:
            rerank = None
    try:
        from app.crud import parent_service as ps_crud

        parent_docs = len(ps_crud.parent_visible_doc_ids(db))
    except Exception:
        parent_docs = 0
    index_status = {}
    try:
        index_status = rag.parent_index_status(db)
    except Exception:
        index_status = {}
    return {
        "llm": {
            "configured": resolved_llm is not None,
            "module_bound": llm_config_id is not None,
            "name": getattr(resolved_llm, "config_name", "") if resolved_llm else "",
            "model": getattr(resolved_llm, "model", "") if resolved_llm else "",
        },
        "embedding": {
            "configured": embedding is not None,
            "dedicated": parent_embedding is not None,
            "model": getattr(embedding, "model", "") if embedding else "",
            "provider": getattr(embedding, "provider", "") if embedding else "",
        },
        "rerank": {
            "configured": rerank is not None,
            "model": getattr(rerank, "model", "") if rerank else "",
            "provider": getattr(rerank, "provider", "") if rerank else "",
        },
        "parent_visible_docs": parent_docs,
        "parent_index": index_status,
    }


# —— 家长客服共享模型（管理员）：LLM 选用 + Rerank 配置 ——

class ParentLLMSelectIn(BaseModel):
    config_id: uuid.UUID | None = None


class ParentRerankIn(BaseModel):
    provider: str = "remote"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    model_path: str = ""
    enabled: bool = True


class ParentEmbeddingIn(BaseModel):
    provider: str = "remote"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    model_path: str = ""
    enabled: bool = True


@teacher_router.get("/parent-llm-config")
def get_parent_llm_config(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    from app.crud import llm_config as llm_crud

    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    row = llm_crud.get_system_parent_llm(db)
    cfg = llm_crud.get_config(db, row.config_id) if (row and row.config_id) else None
    resolved = llm_crud.resolve_parent_llm(db)
    return {
        "config_id": str(row.config_id) if (row and row.config_id) else None,
        "name": getattr(cfg, "name", "") if cfg else "",
        "model": getattr(cfg, "model", "") if cfg else "",
        "resolved_name": getattr(resolved, "config_name", "") if resolved else "",
        "resolved_model": getattr(resolved, "model", "") if resolved else "",
    }


@teacher_router.post("/parent-llm-config")
def set_parent_llm_config(
    body: ParentLLMSelectIn, db: Session = Depends(get_db), user: User = Depends(_staff())
) -> dict:
    from app.crud import llm_config as llm_crud

    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    if body.config_id is not None:
        cfg = llm_crud.get_config(db, body.config_id)
        if cfg is None:
            raise HTTPException(status_code=404, detail="模型配置不存在")
    llm_crud.set_system_parent_llm(db, body.config_id)
    return {"ok": True}


@teacher_router.delete("/parent-llm-config")
def delete_parent_llm_config(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    from app.crud import llm_config as llm_crud

    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    llm_crud.delete_system_parent_llm(db)
    return {"ok": True}


@teacher_router.get("/parent-rerank-config")
def get_parent_rerank_config(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    from app.crud import retrieval_config as ret_crud

    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    row = ret_crud.get_system_parent_rerank(db)
    return {
        "configured": row is not None,
        "provider": row.provider if row else "remote",
        "base_url": row.base_url if row else "",
        "model": row.model if row else "",
        "model_path": row.model_path if row else "",
        "enabled": row.enabled if row else True,
    }


@teacher_router.post("/parent-rerank-config")
def save_parent_rerank_config(
    body: ParentRerankIn, db: Session = Depends(get_db), user: User = Depends(_staff())
) -> dict:
    from app.crud import retrieval_config as ret_crud

    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    if body.provider == "remote" and (not body.base_url.strip() or not body.model.strip()):
        raise HTTPException(status_code=422, detail="接口地址与模型名不能为空")
    if body.provider == "remote":
        # api_key 可留空表示不修改（已有配置时）
        existing = ret_crud.get_system_parent_rerank(db)
        if existing is None and not body.api_key.strip():
            raise HTTPException(status_code=422, detail="首次配置需填写 API Key")
    row = ret_crud.upsert_system_parent_rerank(
        db,
        provider=body.provider,
        base_url=body.base_url,
        api_key=body.api_key.strip() or None,
        model=body.model,
        model_path=body.model_path,
        enabled=body.enabled,
    )
    return {
        "configured": True,
        "provider": row.provider,
        "base_url": row.base_url,
        "model": row.model,
        "model_path": row.model_path,
        "enabled": row.enabled,
    }


@teacher_router.delete("/parent-rerank-config")
def delete_parent_rerank_config(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    from app.crud import retrieval_config as ret_crud

    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    ret_crud.delete_system_parent_rerank(db)
    return {"ok": True}


# —— 家长客服专属 Embedding（管理员）：独立父索引 parent_knowledge__{fingerprint} ——


def _parent_embedding_out(row) -> dict:
    return {
        "configured": row is not None,
        "provider": row.provider if row else "remote",
        "base_url": row.base_url if row else "",
        "api_key_masked": "***" if (row and row.api_key_enc) else "",
        "model": row.model if row else "",
        "model_path": row.model_path if row else "",
        "enabled": row.enabled if row else True,
    }


@teacher_router.get("/parent-embedding-config")
def get_parent_embedding_config(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    from app.crud import retrieval_config as ret_crud

    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    return {"item": _parent_embedding_out(ret_crud.get_system_parent_embedding(db))}


@teacher_router.post("/parent-embedding-config")
def save_parent_embedding_config(
    body: ParentEmbeddingIn, db: Session = Depends(get_db), user: User = Depends(_staff())
) -> dict:
    from app.crud import retrieval_config as ret_crud

    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    if body.provider == "remote" and (not body.base_url.strip() or not body.model.strip()):
        raise HTTPException(status_code=422, detail="接口地址与模型名不能为空")
    if body.provider == "remote":
        existing = ret_crud.get_system_parent_embedding(db)
        if existing is None and not body.api_key.strip():
            raise HTTPException(status_code=422, detail="首次配置需填写 API Key")
    row = ret_crud.upsert_system_parent_embedding(
        db,
        provider=body.provider,
        base_url=body.base_url,
        api_key=body.api_key.strip() or None,
        model=body.model,
        model_path=body.model_path,
        enabled=body.enabled,
    )
    # 指纹变化 → 家长端切到新集合；后台重建家长可见文档索引，避免新集合为空
    rag.invalidate_parent_embedding_cache()
    indexing = rag.start_parent_index_sync()
    return {"item": _parent_embedding_out(row), "indexing_started": indexing}


@teacher_router.delete("/parent-embedding-config")
def delete_parent_embedding_config(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    from app.crud import retrieval_config as ret_crud

    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    ret_crud.delete_system_parent_embedding(db)
    rag.invalidate_parent_embedding_cache()
    return {"ok": True}


@teacher_router.post("/parent-embedding-config/test")
def test_parent_embedding_config(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    import time

    from app.crud import retrieval_config as ret_crud

    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    resolved = ret_crud.resolve_parent_embedding(db) or ret_crud.resolve_embedding(db)
    if resolved is None:
        return {"ok": False, "error": "尚未配置可用的 Embedding 模型"}
    started = time.time()
    try:
        vecs = rag.embed_texts(["连通性检查"], parent=True)
        dim = len(vecs[0]) if vecs else 0
        return {"ok": True, "latency_ms": int((time.time() - started) * 1000), "dim": dim}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@teacher_router.get("/parent-embedding-index")
def parent_embedding_index(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    return rag.parent_index_status(db)


@teacher_router.post("/parent-embedding-index/rebuild")
def rebuild_parent_embedding_index(db: Session = Depends(get_db), user: User = Depends(_staff())) -> dict:
    if user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="仅管理员可配置家长客服共享模型")
    started = rag.start_parent_index_sync()
    return {"started": started, **rag.parent_index_status(db)}


@teacher_router.get("/threads")
def staff_threads(
    campus: str | None = Query(default=None),
    limit: int = Query(default=100, le=200),
    db: Session = Depends(get_db), user: User = Depends(_staff()),
) -> dict:
    _ = user
    # 惰性清理：闲置超阈值的会话自动结束（open 24h / escalated 48h，阈值可后台改）
    closed = ps.auto_close_stale(db)
    items = []
    for th in ps.list_threads_for_staff(db, limit=limit):
        ident = ps.parent_identity(db, th.parent_id)
        d = _thread_out(th)
        if th.parent_id is not None:
            first = (ident["students"] or [{}])[0]
            cls = ", ".join(c["name"] for c in (first.get("classes") or [])[:2])
            d["parent_name"] = f"{ident['name'] or '家长'}"
            d["student_name"] = first.get("name", "")
            d["student_label"] = " · ".join(x for x in [first.get("name", ""), cls] if x) or "未绑定学员"
            d["phone"] = ident["phone"]
        else:
            d["parent_name"] = f"匿名-{str(th.anon_key or '')[:8]}"
            d["student_label"] = "匿名咨询"
            d["phone"] = ""
            d["student_name"] = ""
        d["campuses"] = ident["campuses"]
        d["campus_label"] = "、".join(ident["campuses"][:2]) if ident["campuses"] else "未分区校"
        unread = (
            db.query(ps.ParentServiceMessage).filter(
                ps.ParentServiceMessage.thread_id == th.id,
                ps.ParentServiceMessage.role == ROLE_USER,
            ).count()
        )
        d["user_msg_count"] = unread
        if campus and campus not in (ident["campuses"] or []):
            continue
        items.append(d)
    campuses = sorted({c for it in items for c in (it.get("campuses") or []) if c})
    return {"items": items, "campuses": campuses, "auto_closed": closed}


@teacher_router.get("/threads/{thread_id}/messages")
def staff_messages(
    thread_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(_staff())
) -> dict:
    _ = user
    th = db.get(ParentServiceThread, thread_id)
    if th is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    items = [
        {"id": str(m.id), "role": m.role, "content": m.content,
         "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in ps.list_messages(db, thread_id=thread_id)
    ]
    return {"thread": _thread_out(th), "items": items}


@teacher_router.post("/threads/{thread_id}/reply")
def staff_reply(
    thread_id: uuid.UUID, body: ReplyIn,
    db: Session = Depends(get_db), user: User = Depends(_staff()),
) -> dict:
    _ = user
    th = db.get(ParentServiceThread, thread_id)
    if th is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if th.status == THREAD_ESCALATED or th.status == "open":
        msg = ps.add_message(db, thread_id=thread_id, role=ROLE_STAFF, content=body.content.strip())
        return {"ok": True, "id": str(msg.id), "thread": _thread_out(th)}
    raise HTTPException(status_code=400, detail="该会话已关闭")


@teacher_router.post("/threads/{thread_id}/close")
def staff_close(
    thread_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(_staff())
) -> dict:
    _ = user
    from app.models.parent_service import THREAD_CLOSED

    th = db.get(ParentServiceThread, thread_id)
    if th is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    th.status = THREAD_CLOSED
    db.commit()
    db.refresh(th)
    return {"ok": True, "thread": _thread_out(th)}
