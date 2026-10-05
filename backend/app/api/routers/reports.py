import json
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.crud import report as report_crud
from app.models.report import Report, ReportStatus, ReportType
from app.models.user import Role, User
from app.schemas.enrollment import PageOut
from app.schemas.report import (
    AiDraftJobOut,
    AiDraftJobStatusOut,
    DailyStatsOut,
    PeriodComparison,
    PeriodMonthlyPoint,
    PeriodStatsOut,
    PptBuildIn,
    PptChatIn,
    ReportAiDraftIn,
    ReportAiDraftOut,
    ReportBoardItemOut,
    ReportBoardStatsOut,
    ReportCreate,
    ReportOut,
    ReportPptIn,
    ReportPptOut,
    ReportUpdate,
    WeeklyStatsOut,
)
from app.services import llm, ppt_chat, pptx_builder

router = APIRouter(prefix="/reports", tags=["reports"])

# 报告管理：admin/staff/teacher（教师撰写，教务/管理员可查）
REPORT_ROLES = (Role.ADMIN, Role.STAFF, Role.TEACHER)

settings = get_settings()


def _to_out(rep: Report) -> ReportOut:
    out = ReportOut.model_validate(rep)
    if rep.teacher:
        out.teacher_name = rep.teacher.name
    return out


def _ensure_visible(rep: Report, user: User) -> Report:
    """可见性：本人报告随时可见；他人已发布（公栏）报告任何人可查看；管理员/教务可见全部。"""
    if user.role in (Role.ADMIN.value, Role.STAFF.value):
        return rep
    if rep.teacher_id == user.id:
        return rep
    if rep.status == ReportStatus.PUBLISHED.value:
        return rep
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该报告")


def _ensure_editable(rep: Report, user: User) -> None:
    """可编辑/发布/撤回/删除：本人或管理员/教务。"""
    if user.role in (Role.ADMIN.value, Role.STAFF.value):
        return
    if rep.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该报告")


SUMMARY_TEXT_KEYS = ("summary", "highlights", "problems", "next_plan", "stats_notes")
SUMMARY_STAT_KEYS = ("schedules", "attended", "consumed_lessons", "current_students")


def _summary_has_text(content: dict | None) -> bool:
    c = content or {}
    for k in SUMMARY_TEXT_KEYS:
        v = c.get(k)
        if isinstance(v, str) and v.strip():
            return True
    return False


def _summary_stats_empty(stats: dict | None) -> bool:
    s = stats or {}
    try:
        return all(int(s.get(k) or 0) == 0 for k in SUMMARY_STAT_KEYS)
    except (TypeError, ValueError):
        return True


def _raise_if_summary_empty(db: Session, rep: Report) -> None:
    """空数据门禁：正文 5 字段全空且期间统计全零时拒绝生成 PPT（422）。

    年度总结额外要求：本年度内需至少 1 篇已发布季度总结，否则同样视为无实质数据。
    """
    has_text = _summary_has_text(rep.content)
    stats_empty = _summary_stats_empty(rep.stats)
    if has_text or not stats_empty:
        return
    if rep.type == ReportType.YEARLY.value:
        quarters = report_crud.list_published_quarterlies(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        if quarters:
            return
        raise HTTPException(
            status_code=422,
            detail="年度总结暂无实质内容：正文为空、统计全零且本年度无已发布季度总结，"
            "请先勾选季度总结生成 AI 年总结并保存后再生成 PPT",
        )
    raise HTTPException(
        status_code=422,
        detail="总结暂无实质内容：正文为空且期间统计全零，"
        "请先完善总结内容或确认周期内有排课/周报数据后再生成 PPT",
    )


@router.get("", response_model=PageOut[ReportOut])
def list_reports(
    type: str | None = Query(default=None, pattern="^(daily|weekly|quarterly|yearly)$"),
    teacher_id: uuid.UUID | None = Query(default=None),
    mine: bool = Query(default=False, description="仅看本人报告（历史记录用，管理员也只看本人）"),
    start: datetime | None = Query(default=None, description="周期起（含）"),
    end: datetime | None = Query(default=None, description="周期止（含）"),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PageOut[ReportOut]:
    """报告列表（日报/周报按周期筛选，分页）。

    历史记录用 mine=true：任何角色都只看本人报告；他人报告只能通过公栏查看已发布内容。
    未指定 mine 时：教师只看自己；管理员/教务可看全部（供管理场景）。
    """
    can_view_all = user.role in (Role.ADMIN.value, Role.STAFF.value)
    if mine:
        target_teacher = user.id
    elif teacher_id is not None:
        if not can_view_all:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看他人报告")
        target_teacher = teacher_id
    else:
        target_teacher = None if can_view_all else user.id
    items, total = report_crud.list_reports(
        db,
        type=type,
        teacher_id=target_teacher,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    return PageOut[ReportOut](
        items=[_to_out(r) for r in items], total=total, limit=limit, offset=offset
    )


@router.get("/board/stats", response_model=ReportBoardStatsOut)
def board_stats(
    start: datetime | None = Query(default=None, description="周期起（含）"),
    end: datetime | None = Query(default=None, description="周期止（含）"),
    campus: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportBoardStatsOut:
    """公栏数据统计：按在职教师 + 周期统计日报/周报应提交与已提交数量（供所有人查看）。"""
    return ReportBoardStatsOut(
        **report_crud.board_report_stats(db, start=start, end=end, campus=campus)
    )


@router.get("/board", response_model=PageOut[ReportBoardItemOut])
def board_list(
    type: str | None = Query(default=None, pattern="^(daily|weekly|quarterly|yearly)$"),
    teacher_id: uuid.UUID | None = Query(default=None),
    campus: str | None = Query(default=None),
    start: datetime | None = Query(default=None, description="周期起（含）"),
    end: datetime | None = Query(default=None, description="周期止（含）"),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PageOut[ReportBoardItemOut]:
    """公栏：全部教师已发布报告（含姓名/校区），教师只可编辑自己的报告，其余仅查看。"""
    items, total = report_crud.list_board_reports(
        db,
        type=type,
        teacher_id=teacher_id,
        campus=campus,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    outs = []
    for r in items:
        o = ReportBoardItemOut(
            id=r.id,
            type=r.type,
            teacher_id=r.teacher_id,
            teacher_name=r.teacher.name if r.teacher else None,
            campus=r.teacher.campus if r.teacher else None,
            period_start=r.period_start,
            period_end=r.period_end,
            title=r.title,
            content=r.content,
            stats=r.stats,
            ppt_url=r.ppt_url,
            published_at=r.published_at,
        )
        outs.append(o)
    return PageOut[ReportBoardItemOut](
        items=outs, total=total, limit=limit, offset=offset
    )


@router.post("", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def create_report(
    payload: ReportCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> ReportOut:
    """新建/幂等创建报告：同一教师同类型同周期仅一份（重复创建 = 更新）。"""
    if payload.period_end < payload.period_start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="周期结束不能早于开始")
    return _to_out(
        report_crud.upsert(
            db,
            type=payload.type,
            teacher_id=user.id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            title=payload.title,
            content=payload.content,
            stats=payload.stats,
        )
    )


@router.get("/{report_id}", response_model=ReportOut)
def get_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportOut:
    rep = report_crud.get(db, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    return _to_out(_ensure_visible(rep, user))


@router.patch("/{report_id}", response_model=ReportOut)
def update_report(
    report_id: uuid.UUID,
    payload: ReportUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> ReportOut:
    """编辑报告内容（发布后仍可撤回编辑；admin/staff 可代为维护）。"""
    rep = report_crud.get(db, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    _ensure_editable(rep, user)
    return _to_out(
        report_crud.update(
            db, rep, title=payload.title, content=payload.content, stats=payload.stats
        )
    )


@router.post("/{report_id}/publish", response_model=ReportOut)
def publish_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> ReportOut:
    """发布（提交归档）：草稿 -> 已发布；可重复发布（重新编辑后再次提交）。"""
    rep = report_crud.get(db, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    _ensure_editable(rep, user)
    return _to_out(report_crud.publish(db, rep))


@router.post("/{report_id}/unpublish", response_model=ReportOut)
def unpublish_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> ReportOut:
    """撤回：已发布 -> 草稿，供重新编辑（防止误提交）。"""
    rep = report_crud.get(db, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    _ensure_editable(rep, user)
    if rep.status != ReportStatus.PUBLISHED.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅已发布的报告可撤回")
    return _to_out(report_crud.unpublish(db, rep))


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> None:
    """删除报告（含已发布/公栏）：本人可删自己的，管理员/教务可删全部。"""
    rep = report_crud.get(db, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    if user.role not in (Role.ADMIN.value, Role.STAFF.value) and rep.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除该报告")
    report_crud.delete(db, rep)


@router.get("/weekly-stats/preview", response_model=WeeklyStatsOut)
def weekly_stats_preview(
    teacher_id: uuid.UUID | None = Query(default=None),
    start: datetime = Query(description="周起（周一）"),
    end: datetime = Query(description="周止（周日）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WeeklyStatsOut:
    """周报统计预览（FR-WR-02）：基于排课/考勤/学员自动汇总，供编辑页展示与回填。"""
    target = teacher_id if teacher_id is not None else user.id
    if target != user.id and user.role not in (Role.ADMIN.value, Role.STAFF.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看他人统计")
    return WeeklyStatsOut(
        **report_crud.compute_weekly_stats(db, teacher_id=target, start=start, end=end)
    )


@router.get("/daily-stats/preview", response_model=DailyStatsOut)
def daily_stats_preview(
    teacher_id: uuid.UUID | None = Query(default=None),
    day: datetime = Query(description="当日（00:00 起）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyStatsOut:
    """日报统计预览：应消耗课时 / 消耗课时 / 到课学员数 / 缺课人数（随日报提交）。"""
    target = teacher_id if teacher_id is not None else user.id
    if target != user.id and user.role not in (Role.ADMIN.value, Role.STAFF.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看他人统计")
    return DailyStatsOut(
        **report_crud.compute_daily_stats(db, teacher_id=target, day=day)
    )


@router.get("/period-stats/preview", response_model=PeriodStatsOut)
def period_stats_preview(
    teacher_id: uuid.UUID | None = Query(default=None),
    start: datetime = Query(description="周期起（含）"),
    end: datetime = Query(description="周期止（含）"),
    source: str = Query(default="auto", description="auto=年度优先聚合季度否则明细/周报"),
    report_type: str | None = Query(default=None, pattern="^(quarterly|yearly)$", description="yearly 走季度优先口径"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PeriodStatsOut:
    """季度/年度总结统计预览（FR-QS/FR-YS）。

    年度 quarters-first：report_type=yearly 时优先聚合本年度已发布季度总结 stats；
    无季度总结时回退明细重算/周报聚合（与季度口径一致）。
    """
    target = teacher_id if teacher_id is not None else user.id
    if target != user.id and user.role not in (Role.ADMIN.value, Role.STAFF.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看他人统计")
    if report_type == ReportType.YEARLY.value and source != "raw":
        quarters = report_crud.list_published_quarterlies(
            db, teacher_id=target, start=start, end=end
        )
        if quarters:
            raw = report_crud.compute_period_stats(db, teacher_id=target, start=start, end=end)
            stats = report_crud.rollup_period_to_annual(
                quarters, current_students=raw["current_students"]
            )
            stats["quarterly_count"] = len(quarters)
            return PeriodStatsOut(**stats)
    if source == "raw":
        stats = report_crud.compute_period_stats(db, teacher_id=target, start=start, end=end)
    elif source == "rollup":
        weeklies = report_crud.list_published_weeklies(db, teacher_id=target, start=start, end=end)
        raw = report_crud.compute_period_stats(db, teacher_id=target, start=start, end=end)
        stats = report_crud.rollup_weekly_to_period(weeklies, current_students=raw["current_students"])
    else:
        stats = report_crud.compute_period_stats(db, teacher_id=target, start=start, end=end)
        # 无原始明细（schedules=0）但有已发布周报：回退到周报聚合，避免冷窗口显示全 0
        if stats["schedules"] == 0 and stats["attended"] == 0:
            weeklies = report_crud.list_published_weeklies(db, teacher_id=target, start=start, end=end)
            if weeklies:
                stats = report_crud.rollup_weekly_to_period(
                    weeklies, current_students=stats["current_students"]
                )
    return PeriodStatsOut(**stats)


@router.get("/period-stats/monthly", response_model=list[PeriodMonthlyPoint])
def period_stats_monthly(
    teacher_id: uuid.UUID | None = Query(default=None),
    start: datetime = Query(description="周期起（含）"),
    end: datetime = Query(description="周期止（含）"),
    source: str = Query(
        default="auto",
        description="auto=有明细则重算否则聚合周报；raw 强制重算；rollup 只聚合周报",
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PeriodMonthlyPoint]:
    """折线图数据：期间逐月应耗课时/消耗课时/新增学员/上课人次。"""
    target = teacher_id if teacher_id is not None else user.id
    if target != user.id and user.role not in (Role.ADMIN.value, Role.STAFF.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看他人统计")
    if source == "rollup":
        weeklies = report_crud.list_published_weeklies(db, teacher_id=target, start=start, end=end)
        return [PeriodMonthlyPoint(**m) for m in report_crud.rollup_weekly_monthly(weeklies)]
    pts = report_crud.compute_period_monthly(db, teacher_id=target, start=start, end=end)
    if source == "auto" and all(
        p["expected_lessons"] == 0 and p["consumed_lessons"] == 0 and p["attendance"] == 0
        for p in pts
    ):
        weeklies = report_crud.list_published_weeklies(db, teacher_id=target, start=start, end=end)
        rolled = report_crud.rollup_weekly_monthly(weeklies)
        if rolled:
            return [PeriodMonthlyPoint(**m) for m in rolled]
    return [PeriodMonthlyPoint(**m) for m in pts]


@router.get("/period-stats/comparison", response_model=PeriodComparison)
def period_stats_comparison(
    teacher_id: uuid.UUID | None = Query(default=None),
    start: datetime = Query(description="周期起（含）"),
    end: datetime = Query(description="周期止（含）"),
    source: str = Query(default="auto", description="auto=有明细则重算否则聚合周报；raw 强制重算；rollup 只聚合周报"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PeriodComparison:
    """柱状图数据：当前期间 vs 上一对等期间（季度=上一季度；年度=上一年）课时消耗对比。"""
    target = teacher_id if teacher_id is not None else user.id
    if target != user.id and user.role not in (Role.ADMIN.value, Role.STAFF.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看他人统计")
    if source != "rollup":
        cmp = report_crud.compute_period_comparison(db, teacher_id=target, start=start, end=end)
        if source == "raw" or any(cmp["current"]) or any(cmp["previous"]):
            return PeriodComparison(**cmp)
    return PeriodComparison(
        **report_crud.compute_period_comparison_from_weeklies(
            db, teacher_id=target, start=start, end=end
        )
    )


@router.post("/{report_id}/ppt", response_model=ReportPptOut)
def generate_report_ppt(
    report_id: uuid.UUID,
    payload: ReportPptIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> ReportPptOut:
    """生成季度/年度总结 PPT 草稿（FR-QS-02 / FR-YS-02）：基于已保存 content+stats 构建。

    空数据门禁：正文 5 字段全空且期间统计全零时返回 422，避免空数据产出套话 PPT。
    PPT 落盘 uploads/ppt/ 并写入 reports.ppt_url，可在线下载预览；content 可继续修改后重新生成。
    include_sections（可选）：要点类字段勾选入页的条目下标，key 缺席=全选，空列表=整段跳过。
    """
    rep = report_crud.get(db, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    _ensure_editable(rep, user)
    if rep.type not in (ReportType.QUARTERLY.value, ReportType.YEARLY.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="仅季度/年度总结可生成 PPT"
        )

    _raise_if_summary_empty(db, rep)

    title = rep.title or (
        f"{rep.period_start.strftime('%Y年%m月')}~{rep.period_end.strftime('%m月%d日')} "
        f"{'季度' if rep.type == ReportType.QUARTERLY.value else '年度'}总结"
    )
    period_label = (
        f"{rep.period_start.strftime('%Y年%m月%d日')} ~ {rep.period_end.strftime('%Y年%m月%d日')}"
    )
    teacher_name = rep.teacher.name if rep.teacher else ""
    quarter_cards: list[dict] = []
    quarterly_stats_map: dict[str, dict] = {}
    if rep.type == ReportType.YEARLY.value:
        quarters = report_crud.list_published_quarterlies(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        for i, q in enumerate(quarters[:4]):
            summary = str((q.content or {}).get("summary") or "")
            quarter_cards.append(
                {
                    "label": f"Q{i + 1}",
                    "title": (q.title or "").strip(),
                    "summary": summary,
                }
            )
            quarterly_stats_map[str(q.id)] = q.stats or {}
    # 明细表快照：落库 content["ppt_breakdown"] 优先（与页面保存时一致）；
    # 存量报告缺快照时回退一次重算并回写，保证 PPT 数据与页面统计一致。
    breakdown = (rep.content or {}).get("ppt_breakdown")
    if not isinstance(breakdown, list) or not breakdown:
        breakdown = _build_ppt_breakdown_snapshot(db, rep, quarterly_stats_map)
        if breakdown:
            rep.content = {**(rep.content or {}), "ppt_breakdown": breakdown}
    try:
        ppt_url = pptx_builder.build_summary_ppt(
            title=title,
            period_label=period_label,
            teacher_name=teacher_name,
            created_at=datetime.now(),
            content=rep.content,
            stats={**(rep.stats or {}), "quarterly_count": len(quarter_cards)}
            if rep.type == ReportType.YEARLY.value else rep.stats,
            report_type=rep.type,
            quarter_summaries=quarter_cards,
            table_breakdown=breakdown or None,
            include_sections=(payload.include_sections if payload else None),
        )
    except Exception as e:  # noqa: BLE001 - 将 PPT 构建异常转为可读错误
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PPT 生成失败：{e}",
        )

    rep.ppt_url = ppt_url
    db.commit()
    db.refresh(rep)
    return ReportPptOut(ppt_url=rep.ppt_url, title=title)


@router.post("/{report_id}/ppt-chat")
def ppt_chat_stream(
    report_id: uuid.UUID,
    payload: PptChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> StreamingResponse:
    """对话式 PPT 定制（SSE 流式）：按阶段生成大纲/文案/排版建议，逐段回传。

    事件格式：`data: {"delta": "..."}` 增量文本；`data: {"done": true}` 结束；
    `data: {"error": "..."}` 出错。会话状态（大纲/文案）由前端持有并回传。
    """
    rep = report_crud.get(db, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    _ensure_editable(rep, user)
    if rep.type not in (ReportType.QUARTERLY.value, ReportType.YEARLY.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="仅季度/年度总结可使用 PPT 定制"
        )
    from app.services import llm_context as _llm_ctx
    ppt_resolved = _llm_ctx.require_llm(db, user_id=user.id, module="report")
    stage = payload.stage
    message = payload.message or ""
    outline = list(payload.outline or [])
    sections = list(payload.sections or [])
    stage_label = {
        "outline": "大纲", "copy": "文案", "layout": "排版建议", "chat": "回答",
    }.get(stage, "内容")

    def _frame(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    def event_stream():
        try:
            with _llm_ctx.use_llm(ppt_resolved):
                yield _frame({"phase": {"key": "read", "label": "读取报告数据与统计"}})
                material = ppt_chat.report_material(db, rep)
                yield _frame({"phase": {"key": "analyze", "label": "分析统计数据"}})
                prompt = ppt_chat.build_prompt(
                    stage=stage, material=material, user_message=message,
                    outline=outline, sections=sections,
                )
                yield _frame({"phase": {"key": "model", "label": f"AI 模型生成{stage_label}中"}})
                started = False
                for chunk in llm.stream_text(ppt_chat.SYSTEM_PROMPT, prompt):
                    if not started:
                        started = True
                        yield _frame({"phase": {"key": "stream", "label": "接收并整理结果"}})
                    yield _frame({"delta": chunk})
        except Exception as e:  # noqa: BLE001 —— 统一转可读错误
            yield _frame({"error": llm.friendly_llm_error(e)})
            return
        yield _frame({"done": True})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{report_id}/ppt-build", response_model=ReportPptOut)
def ppt_build(
    report_id: uuid.UUID,
    payload: PptBuildIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> ReportPptOut:
    """按对话确认的 slides 规格构建定制 PPT（自动注入数据表+趋势图）。"""
    rep = report_crud.get(db, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    _ensure_editable(rep, user)
    if rep.type not in (ReportType.QUARTERLY.value, ReportType.YEARLY.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="仅季度/年度总结可生成 PPT"
        )
    _raise_if_summary_empty(db, rep)

    title = (payload.title or rep.title or "工作总结").strip()
    period_label = (
        f"{rep.period_start.strftime('%Y年%m月%d日')} ~ {rep.period_end.strftime('%Y年%m月%d日')}"
    )
    teacher_name = rep.teacher.name if rep.teacher else ""
    breakdown = (rep.content or {}).get("ppt_breakdown")
    if not isinstance(breakdown, list) or not breakdown:
        breakdown = _build_ppt_breakdown_snapshot(db, rep)
    stats = dict(rep.stats or {})
    if rep.type == ReportType.YEARLY.value:
        quarters = report_crud.list_published_quarterlies(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        stats["quarterly_count"] = len(quarters)
    try:
        ppt_url = pptx_builder.build_custom_ppt(
            title=title,
            period_label=period_label,
            teacher_name=teacher_name,
            created_at=datetime.now(),
            stats=stats,
            breakdown=breakdown or [],
            slides=payload.slides or [],
            theme=payload.theme,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PPT 生成失败：{e}",
        )
    rep.ppt_url = ppt_url
    db.commit()
    db.refresh(rep)
    return ReportPptOut(ppt_url=rep.ppt_url, title=title)


@router.post("/{report_id}/ai-draft", response_model=ReportAiDraftOut)
def report_ai_draft(
    report_id: uuid.UUID,
    payload: ReportAiDraftIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> ReportAiDraftOut:
    """AI 报告草稿（同步兼容入口，FR-DR-02 / FR-WR-03）：

    建议新版前端使用下面的异步任务接口（ai-draft-jobs）：生成中可关弹窗/切页面，
    完成后轮询任务状态取回草稿。同步入口保留给旧客户端与测试。
    """
    draft = _generate_ai_draft_blocking(
        db,
        report_id=report_id,
        teacher_id=user.id,
        is_admin_staff=user.role in (Role.ADMIN.value, Role.STAFF.value),
        extra_note=payload.extra_note,
        source_quarter_ids=list(payload.source_quarter_ids or []),
    )
    return ReportAiDraftOut(
        title=draft["title"],
        content=draft["content"],
        model=draft["model"],
    )


# ---------------------------------------------------------------------------
# AI 草稿异步任务：生成耗时 20-60s，支持关闭弹窗/切换页面后回来取结果
#
# 流程：POST ai-draft-jobs -> 返回 job_id（202）-> 前端轮询 GET ai-draft-jobs/{id}
#   pending/running -> 继续等；succeeded -> 拿到 draft 回填；failed -> 展示错误
# 任务为进程内内存存储（单 worker 部署足够；多 worker 下前端 sticky 同一实例即可）。
# ---------------------------------------------------------------------------

_AI_JOBS: dict[str, dict[str, Any]] = {}
_AI_JOBS_LOCK = threading.Lock()
_AI_JOB_TTL_SECONDS = 30 * 60


def _ai_job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "report_id": job["report_id"],
        "report_type": job["report_type"],
        "status": job["status"],
        "title": job.get("title"),
        "content": job.get("content"),
        "model": job.get("model"),
        "error": job.get("error"),
        "created_at": job["created_at"],
        "finished_at": job.get("finished_at"),
        "elapsed_seconds": (
            (job.get("finished_at") or time.time()) - job["created_at"]
        ),
    }


def _generate_ai_draft_blocking(
    db_or_session: Session,
    *,
    report_id: uuid.UUID,
    teacher_id: uuid.UUID,
    is_admin_staff: bool,
    extra_note: str | None,
    source_quarter_ids: list[uuid.UUID],
) -> dict[str, Any]:
    """实际执行一次 AI 草稿生成（供同步接口与后台任务线程共用）。"""
    rep = report_crud.get(db_or_session, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    if not is_admin_staff and rep.teacher_id != teacher_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作该报告")

    from app.services import llm_context as _llm_ctx

    _draft_resolved = _llm_ctx.get_current()
    if _draft_resolved is None:
        _draft_resolved = _llm_ctx.optional_resolved(db_or_session, teacher_id, "report")
    if _draft_resolved is None:
        return {
            "title": rep.title,
            "content": {"note": "δ���� LLM_API_KEY��AI �ݸ��ݲ����ã����ֶ���д"},
            "model": None,
        }

    material = _collect_report_material(
        db_or_session,
        rep,
        payload=ReportAiDraftIn(
            extra_note=extra_note, source_quarter_ids=source_quarter_ids or None
        ),
    )
    with _llm_ctx.use_llm(_draft_resolved):
        try:
            if rep.type in (ReportType.QUARTERLY.value, ReportType.YEARLY.value):
                draft = llm.generate_period_summary(
                    report_type=rep.type,
                    material=material,
                    extra_note=extra_note,
                    from_quarters=rep.type == ReportType.YEARLY.value and "季度总结" in material,
                )
            else:
                draft = llm.generate_report_summary(
                    report_type=rep.type,
                    material=material,
                    extra_note=extra_note,
                )
        except llm.LLMConfigError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
        except Exception as e:  # noqa: BLE001 —— LLM 超时/断网/限流等未预见异常统一转 502
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=llm.friendly_llm_error(e),
            )

    return {
        "title": draft.get("title") or rep.title,
        "content": {k: v for k, v in draft.items() if k != "title" and v is not None},
        "model": _llm_ctx.active_model_name(),
    }


def _run_ai_draft_job(job_id: str) -> None:
    """后台线程执行体：独立 DB 会话，结果写回内存任务表。"""
    with _AI_JOBS_LOCK:
        job = _AI_JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "running"
    from app.services import llm_context as _llm_ctx

    db = SessionLocal()
    try:
        _job_resolved = _llm_ctx.optional_resolved(db, uuid.UUID(job["teacher_id"]), "report")
        with _llm_ctx.use_llm(_job_resolved):
                draft = _generate_ai_draft_blocking(
                db,
                report_id=uuid.UUID(job["report_id"]),
                teacher_id=uuid.UUID(job["teacher_id"]),
                is_admin_staff=job["is_admin_staff"],
                extra_note=job.get("extra_note"),
                source_quarter_ids=[uuid.UUID(i) for i in (job.get("source_quarter_ids") or [])],
            )
        with _AI_JOBS_LOCK:
            job = _AI_JOBS.get(job_id)
            if job is None:
                return
            job.update(
                status="succeeded",
                title=draft["title"],
                content=draft["content"],
                model=draft["model"],
                finished_at=time.time(),
            )
    except HTTPException as e:
        with _AI_JOBS_LOCK:
            job = _AI_JOBS.get(job_id)
            if job is None:
                return
            job.update(status="failed", error=str(e.detail), finished_at=time.time())
    except Exception as e:  # noqa: BLE001 —— 后台线程兜底，避免任务永久 pending
        with _AI_JOBS_LOCK:
            job = _AI_JOBS.get(job_id)
            if job is None:
                return
            job.update(status="failed", error=f"AI 生成失败：{e}", finished_at=time.time())
    finally:
        db.close()
        with _AI_JOBS_LOCK:
            now = time.time()
            expired = [
                jid
                for jid, j in _AI_JOBS.items()
                if now - j["created_at"] > _AI_JOB_TTL_SECONDS
            ]
            for jid in expired:
                del _AI_JOBS[jid]


@router.post(
    "/{report_id}/ai-draft-jobs", response_model=AiDraftJobOut, status_code=status.HTTP_202_ACCEPTED
)
def create_ai_draft_job(
    report_id: uuid.UUID,
    payload: ReportAiDraftIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> AiDraftJobOut:
    """提交 AI 草稿异步任务：立即返回 job_id，前端可关弹窗/切页面后轮询取结果。"""
    rep = report_crud.get(db, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    _ensure_editable(rep, user)

    job_id = uuid.uuid4().hex
    with _AI_JOBS_LOCK:
        _AI_JOBS[job_id] = {
            "job_id": job_id,
            "report_id": str(rep.id),
            "report_type": rep.type,
            "teacher_id": str(user.id),
            "is_admin_staff": user.role in (Role.ADMIN.value, Role.STAFF.value),
            "extra_note": payload.extra_note,
            "source_quarter_ids": [str(i) for i in (payload.source_quarter_ids or [])],
            "status": "pending",
            "title": None,
            "content": None,
            "model": None,
            "error": None,
            "created_at": time.time(),
            "finished_at": None,
        }
    thread = threading.Thread(target=_run_ai_draft_job, args=(job_id,), daemon=True)
    thread.start()
    return AiDraftJobOut(job_id=job_id, status="pending")


@router.get("/{report_id}/ai-draft-jobs/{job_id}", response_model=AiDraftJobStatusOut)
def get_ai_draft_job(
    report_id: uuid.UUID,
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*REPORT_ROLES)),
) -> AiDraftJobStatusOut:
    """查询 AI 草稿任务状态：pending/running/succeeded/failed。"""
    with _AI_JOBS_LOCK:
        job = _AI_JOBS.get(job_id)
        snapshot = dict(job) if job else None
    if snapshot is None or snapshot["report_id"] != str(report_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在或已过期")
    rep = report_crud.get(db, report_id)
    if rep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在")
    _ensure_editable(rep, user)
    return AiDraftJobStatusOut(**_ai_job_public(snapshot))


def _build_ppt_breakdown_snapshot(
    db: Session, rep: Report, quarterly_stats_map: dict[str, dict] | None = None
) -> list[dict]:
    """生成 PPT 明细表快照行：季度=逐月明细，年度=季度对照（取自已保存 stats/季度快照）。"""
    if rep.type == ReportType.YEARLY.value:
        quarters = report_crud.list_published_quarterlies(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        rows: list[dict] = []
        for i, q in enumerate(quarters[:4]):
            s = (quarterly_stats_map or {}).get(str(q.id)) or q.stats or {}
            rows.append(
                {
                    "label": f"Q{i + 1} {(q.title or '').strip()}".strip(),
                    "consumed_lessons": int(s.get("consumed_lessons") or 0),
                    "expected_lessons": int(s.get("expected_lessons") or 0),
                    "attendance_rate": float(s.get("attendance_rate") or 0),
                    "summary": str((q.content or {}).get("summary") or ""),
                }
            )
        return rows
    monthly = report_crud.compute_period_monthly(
        db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
    )
    return [
        {
            "month": m.get("month", ""),
            "consumed_lessons": int(m.get("consumed_lessons") or 0),
            "expected_lessons": int(m.get("expected_lessons") or 0),
            "attendance": int(m.get("attendance") or 0),
            "new_students": int(m.get("new_students") or 0),
        }
        for m in monthly
    ]


def _resolve_yearly_quarters(db: Session, rep: Report, payload: ReportAiDraftIn) -> list[Report]:
    """解析年度 AI 素材来源季度总结：显式勾选优先，否则自动带出本年度全部已发布。"""
    ids = payload.source_quarter_ids
    if ids:
        wanted = {str(i) for i in ids}
        all_quarters = report_crud.list_published_quarterlies(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        picked = [q for q in all_quarters if str(q.id) in wanted]
        if len(picked) != len(wanted):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="所选季度总结不存在、未发布或不在本年度周期内",
            )
        return picked
    return report_crud.list_published_quarterlies(
        db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
    )


def _collect_report_material(db: Session, rep: Report, payload: ReportAiDraftIn) -> str:
    """组装 AI 素材：日报=当日排课/考勤；周报=统计指标 + 本周已发布日报摘要。"""
    if rep.type == ReportType.DAILY.value:
        material = report_crud.collect_daily_material(
            db, teacher_id=rep.teacher_id, day=rep.period_start
        )
        lines = [f"- 日期：{rep.period_start.strftime('%Y-%m-%d')}"]
        daily_stats = report_crud.compute_daily_stats(
            db, teacher_id=rep.teacher_id, day=rep.period_start
        )
        lines.append(
            f"- 当日统计：排课 {daily_stats['schedules']} 节，"
            f"应到 {daily_stats['expected_attendance']} 人，"
            f"到课 {daily_stats['attended']} 人，缺课 {daily_stats['leave']} 人，"
            f"出勤率 {daily_stats['attendance_rate'] * 100:.1f}%，"
            f"应消耗 {daily_stats['expected_lessons']} 课时，"
            f"消耗 {daily_stats['consumed_lessons']} 课时，"
            f"达标率 {daily_stats['achievement_rate'] * 100:.1f}%"
        )
        if not material["courses"]:
            lines.append("- 当日暂无排课记录（课程列表为空）")
        for c in material["courses"]:
            lines.append(
                f"- {c['time']} {c['class_name']}（{c['subject']}）："
                f"已到 {c['attended']} 人，请假 {c['leave']} 人"
            )
        return "\n".join(lines)

    # 季度：聚合统计 + 周期内已发布周报摘要
    if rep.type == ReportType.QUARTERLY.value:
        stats = report_crud.compute_period_stats(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        period0 = rep.period_start.strftime("%Y-%m-%d")
        period1 = rep.period_end.strftime("%Y-%m-%d")
        lines = [
            f"- 周期：{period0} ~ {period1}",
            f"- 当前学员：{stats['current_students']} 人",
            f"- 应耗课时：{stats['expected_lessons']} 节，消耗课时：{stats['consumed_lessons']} 节",
            f"- 达标率：{stats['achievement_rate'] * 100:.1f}%",
            f"- 上课人次：{stats['attended']}，缺课人次：{stats['leave']}，"
            f"出勤率：{stats['attendance_rate'] * 100:.1f}%",
            f"- 新增学员：{stats['new_students']} 人",
            f"- 已发布周报：{stats['weekly_count']} 篇",
        ]
        weekly_summaries = report_crud.collect_period_material(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        if weekly_summaries:
            lines.append("\n各周周报摘要（季度内）：")
            for w in weekly_summaries:
                lines.append(
                    f"- 周[{w['week']}]：{w['summary'] or '（无总结）'}"
                    + (f" | 亮点：{w['highlights']}" if w["highlights"] else "")
                )
        else:
            lines.append("\n提示：季度内暂无已发布周报，建议先完善周报再生成总结。")
        return "\n".join(lines)

    # 年度：优先聚合已选/自动带出的已发布季度总结，无季度时回退周报口径
    if rep.type == ReportType.YEARLY.value:
        quarters = _resolve_yearly_quarters(db, rep, payload)
        if quarters:
            raw = report_crud.compute_period_stats(
                db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
            )
            stats = report_crud.rollup_period_to_annual(
                quarters, current_students=raw["current_students"]
            )
            period0 = rep.period_start.strftime("%Y-%m-%d")
            period1 = rep.period_end.strftime("%Y-%m-%d")
            lines = [
                f"- 周期：{period0} ~ {period1}（年度素材来自季度总结）",
                f"- 选用季度总结：{len(quarters)} 篇",
                f"- 当前学员：{stats['current_students']} 人",
                f"- 应耗课时：{stats['expected_lessons']} 节，消耗课时：{stats['consumed_lessons']} 节",
                f"- 达标率：{stats['achievement_rate'] * 100:.1f}%",
                f"- 上课人次：{stats['attended']}，缺课人次：{stats['leave']}，"
                f"出勤率：{stats['attendance_rate'] * 100:.1f}%",
                f"- 新增学员：{stats['new_students']} 人",
                "\n各季度总结摘要：",
            ]
            for q in quarters:
                c = q.content or {}
                qlabel = (q.title or "").strip() or q.period_start.strftime("%m-%d")
                lines.append(
                    f"- 季度总结[{qlabel}]：{c.get('summary') or '（无总体情况）'}"
                    + (f" | 亮点：{c.get('highlights')}" if c.get("highlights") else "")
                    + (f" | 问题：{c.get('problems')}" if c.get("problems") else "")
                    + (f" | 下阶段：{c.get('next_plan')}" if c.get("next_plan") else "")
                )
            return "\n".join(lines)
        stats = report_crud.compute_period_stats(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        period0 = rep.period_start.strftime("%Y-%m-%d")
        period1 = rep.period_end.strftime("%Y-%m-%d")
        lines = [
            f"- 周期：{period0} ~ {period1}",
            "- 提示：本年度暂无已发布季度总结，已回退为周报口径，建议先完善各季度总结",
            f"- 当前学员：{stats['current_students']} 人",
            f"- 应耗课时：{stats['expected_lessons']} 节，消耗课时：{stats['consumed_lessons']} 节",
            f"- 达标率：{stats['achievement_rate'] * 100:.1f}%",
            f"- 上课人次：{stats['attended']}，缺课人次：{stats['leave']}，"
            f"出勤率：{stats['attendance_rate'] * 100:.1f}%",
            f"- 新增学员：{stats['new_students']} 人",
            f"- 已发布周报：{stats['weekly_count']} 篇",
        ]
        weekly_summaries = report_crud.collect_period_material(
            db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
        )
        if weekly_summaries:
            lines.append("\n各周周报摘要（年度内）：")
            for w in weekly_summaries:
                lines.append(
                    f"- 周[{w['week']}]：{w['summary'] or '（无总结）'}"
                    + (f" | 亮点：{w['highlights']}" if w["highlights"] else "")
                )
        else:
            lines.append("\n提示：年度内暂无已发布周报，建议先完善周报再生成总结。")
        return "\n".join(lines)

    # 周报：统计指标 + 本周日报标题/工作摘要
    stats = report_crud.compute_weekly_stats(
        db, teacher_id=rep.teacher_id, start=rep.period_start, end=rep.period_end
    )
    lines = [
        f"- 周期：{rep.period_start.strftime('%Y-%m-%d')} ~ {rep.period_end.strftime('%Y-%m-%d')}",
        f"- 本周排课：{stats['schedules']} 节，应到 {stats['expected_attendance']} 人次",
        f"- 到课学员：{stats['attended']} 人，缺课：{stats['leave']} 人",
        f"- 出勤率：{stats['attendance_rate'] * 100:.1f}%，"
        f"达标率：{stats['achievement_rate'] * 100:.1f}%",
        f"- 应消耗课时：{stats['expected_lessons']} 节，消耗课时：{stats['consumed_lessons']} 节",
        f"- 缺课学员：{'、'.join(stats['absent_students']) or '无'}",
        f"- 新增学员：{stats['new_students']} 人",
    ]
    daily_items, _ = report_crud.list_reports(
        db,
        type=ReportType.DAILY.value,
        teacher_id=rep.teacher_id,
        start=rep.period_start,
        end=rep.period_end,
        limit=50,
        offset=0,
    )
    for d in daily_items:
        if d.status == ReportStatus.PUBLISHED.value:
            work = (d.content or {}).get("work")
            if work:
                lines.append(f"- 日报[{d.period_start.strftime('%m-%d')}]：{work[:80]}")
    return "\n".join(lines)
