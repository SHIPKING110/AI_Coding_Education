"""Agent 行为评测 API（管理员）：评测集 / 用例 / 运行 / 结果 / 对比 / 人工复核。

复用 RAG 评测的权限键（rag_eval_view / rag_eval_case_add），不新增权限项；
运行由后台线程执行（services.agent_eval_runner），前端轮询进度。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_teacher_permission
from app.core.database import get_db
from app.crud import llm_config as llm_crud
from app.models.rag_admin import AgentEvalCase, AgentEvalResult, AgentEvalRun, AgentEvalSet
from app.models.user import User
from app.services import agent_eval_runner

router = APIRouter(prefix="/admin/agent-eval", tags=["agent-eval"])

_VIEW = Depends(require_teacher_permission("rag_eval_view", staff_allowed=False))
_EDIT = Depends(require_teacher_permission("rag_eval_case_add", staff_allowed=False))


# ---------- 序列化 ----------

def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _set_dict(x: AgentEvalSet) -> dict:
    return {
        "id": str(x.id),
        "name": x.name,
        "description": x.description or "",
        "agent_scope": x.agent_scope,
        "created_at": _iso(x.created_at),
        "updated_at": _iso(x.updated_at),
    }


def _case_dict(x: AgentEvalCase) -> dict:
    return {
        "id": str(x.id),
        "set_id": str(x.set_id),
        "query": x.query,
        "messages": x.messages,
        "expected_tools": x.expected_tools or [],
        "allowed_extra_tools": x.allowed_extra_tools or [],
        "forbidden_tools": x.forbidden_tools or [],
        "expect_abstain": bool(x.expect_abstain),
        "expected_facts": x.expected_facts or [],
        "split": x.split,
        "business_criticality": x.business_criticality,
        "notes": x.notes or "",
        "source": x.source,
        "created_at": _iso(x.created_at),
    }


def _run_dict(x: AgentEvalRun) -> dict:
    return {
        "id": str(x.id),
        "set_id": str(x.set_id),
        "status": x.status,
        "stage": x.stage,
        "progress": x.progress,
        "total_cases": x.total_cases,
        "processed_cases": x.processed_cases,
        "agent_id": x.agent_id,
        "model_config_id": str(x.model_config_id) if x.model_config_id else None,
        "model_name": x.model_name or "",
        "metrics": x.metrics,
        "gate": x.gate,
        "error": x.error,
        "created_at": _iso(x.created_at),
        "finished_at": _iso(x.finished_at),
    }


def _result_dict(x: AgentEvalResult) -> dict:
    return {
        "id": str(x.id),
        "run_id": str(x.run_id),
        "case_id": str(x.case_id) if x.case_id else None,
        "query": x.query,
        "trace_run_id": x.trace_run_id,
        "final_text": x.final_text,
        "expected_tools": x.expected_tools or [],
        "tool_calls": x.tool_calls or [],
        "metrics": x.metrics,
        "error": x.error,
        "human_score": x.human_score,
        "human_judge": x.human_judge,
        "human_at": _iso(x.human_at),
        "human_reason": x.human_reason,
    }


# ---------- 评测集 ----------

class SetIn(BaseModel):
    name: str
    description: str = ""
    agent_scope: str = "teacher"


@router.get("/sets", dependencies=[_VIEW])
def list_sets(db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(AgentEvalSet).order_by(AgentEvalSet.created_at)).all()
    out = []
    for s in rows:
        d = _set_dict(s)
        d["case_count"] = db.scalar(
            select(func.count()).select_from(AgentEvalCase).where(AgentEvalCase.set_id == s.id)
        ) or 0
        out.append(d)
    return {"items": out}


@router.post("/sets", dependencies=[_EDIT])
def create_set(body: SetIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    row = AgentEvalSet(
        name=body.name.strip() or "未命名评测集",
        description=body.description,
        agent_scope=body.agent_scope or "teacher",
        owner_id=user.id,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _set_dict(row)


@router.delete("/sets/{set_id}", dependencies=[_EDIT])
def delete_set(set_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    row = db.get(AgentEvalSet, set_id)
    if row is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    db.delete(row)  # 用例/运行/结果 级联删除
    db.commit()
    return {"ok": True}


@router.post("/seed-default", dependencies=[_EDIT])
def seed_default(db: Session = Depends(get_db)) -> dict:
    """一键载入默认 30 条种子用例（幂等）。"""
    from scripts.agent_eval_seed import DEFAULT_SET_NAME, seed_default_set

    created, skipped = seed_default_set(db, name=DEFAULT_SET_NAME)
    eset = db.scalars(
        select(AgentEvalSet).where(AgentEvalSet.name == DEFAULT_SET_NAME)
    ).first()
    return {
        "ok": True,
        "set_id": str(eset.id) if eset else None,
        "created": created,
        "skipped": skipped,
    }


# ---------- 用例 ----------

class CaseIn(BaseModel):
    query: str
    messages: list[dict] | None = None
    expected_tools: list[str] = Field(default_factory=list)
    allowed_extra_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expect_abstain: bool = False
    expected_facts: list[str] = Field(default_factory=list)
    split: str = "regression"
    business_criticality: str = "normal"
    notes: str = ""
    source: str = "manual"


@router.get("/sets/{set_id}/cases", dependencies=[_VIEW])
def list_cases(
    set_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    split: str = "",
    db: Session = Depends(get_db),
) -> dict:
    if db.get(AgentEvalSet, set_id) is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    base = select(AgentEvalCase).where(AgentEvalCase.set_id == set_id)
    if split:
        base = base.where(AgentEvalCase.split == split)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    rows = db.scalars(
        base.order_by(AgentEvalCase.created_at.asc(), AgentEvalCase.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": [_case_dict(x) for x in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/sets/{set_id}/cases", dependencies=[_EDIT])
def add_case(set_id: uuid.UUID, body: CaseIn, db: Session = Depends(get_db)) -> dict:
    if db.get(AgentEvalSet, set_id) is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    row = AgentEvalCase(
        set_id=set_id,
        query=body.query.strip(),
        messages=body.messages,
        expected_tools=body.expected_tools,
        allowed_extra_tools=body.allowed_extra_tools,
        forbidden_tools=body.forbidden_tools,
        expect_abstain=body.expect_abstain,
        expected_facts=body.expected_facts,
        split=body.split,
        business_criticality=body.business_criticality,
        notes=body.notes,
        source=body.source,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _case_dict(row)


class CaseBulkIn(BaseModel):
    cases: list[dict]
    skip_duplicates: bool = True


@router.post("/sets/{set_id}/cases/bulk", dependencies=[_EDIT])
def add_cases_bulk(set_id: uuid.UUID, body: CaseBulkIn, db: Session = Depends(get_db)) -> dict:
    """批量导入：逐行校验，坏行跳过并返回行号；默认按 query 去重。"""
    if db.get(AgentEvalSet, set_id) is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    if len(body.cases) > 500:
        raise HTTPException(status_code=400, detail="单次导入最多 500 条，请分批")
    existing = {
        (c.query or "").strip().lower()
        for c in db.scalars(select(AgentEvalCase).where(AgentEvalCase.set_id == set_id)).all()
    }
    created: list[dict] = []
    errors: list[dict] = []
    skipped = 0
    for idx, raw in enumerate(body.cases, start=1):
        try:
            c = CaseIn.model_validate(raw)
        except Exception as exc:  # 坏行跳过
            errors.append({"line": idx, "error": str(exc)[:200]})
            continue
        key = (c.query or "").strip().lower()
        if not key:
            errors.append({"line": idx, "error": "query 为空"})
            continue
        if body.skip_duplicates and key in existing:
            skipped += 1
            continue
        row = AgentEvalCase(
            set_id=set_id,
            query=c.query.strip(),
            messages=c.messages,
            expected_tools=c.expected_tools,
            allowed_extra_tools=c.allowed_extra_tools,
            forbidden_tools=c.forbidden_tools,
            expect_abstain=c.expect_abstain,
            expected_facts=c.expected_facts,
            split=c.split,
            business_criticality=c.business_criticality,
            notes=c.notes,
            source=c.source or "import",
        )
        db.add(row)
        existing.add(key)
        created.append({"query": row.query})
    db.commit()
    return {"created": len(created), "skipped": skipped, "errors": errors}


@router.put("/cases/{case_id}", dependencies=[_EDIT])
def update_case(case_id: uuid.UUID, body: CaseIn, db: Session = Depends(get_db)) -> dict:
    row = db.get(AgentEvalCase, case_id)
    if row is None:
        raise HTTPException(status_code=404, detail="用例不存在")
    row.query = body.query.strip() or row.query
    row.messages = body.messages
    row.expected_tools = body.expected_tools
    row.allowed_extra_tools = body.allowed_extra_tools
    row.forbidden_tools = body.forbidden_tools
    row.expect_abstain = body.expect_abstain
    row.expected_facts = body.expected_facts
    row.split = body.split
    row.business_criticality = body.business_criticality
    row.notes = body.notes
    db.commit()
    return _case_dict(row)


@router.delete("/cases/{case_id}", dependencies=[_EDIT])
def delete_case(case_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    row = db.get(AgentEvalCase, case_id)
    if row is None:
        raise HTTPException(status_code=404, detail="用例不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------- 运行 ----------

class RunIn(BaseModel):
    agent_id: str = "assistant"
    model_config_id: uuid.UUID | None = None


@router.post("/sets/{set_id}/runs", dependencies=[_VIEW])
def create_run(
    set_id: uuid.UUID,
    body: RunIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    eset = db.get(AgentEvalSet, set_id)
    if eset is None:
        raise HTTPException(status_code=404, detail="评测集不存在")
    total = db.scalar(
        select(func.count()).select_from(AgentEvalCase).where(AgentEvalCase.set_id == set_id)
    ) or 0
    if not total:
        raise HTTPException(status_code=400, detail="评测集为空，请先添加用例")
    # 工具名漂移防线：用例引用的工具必须在 agent_tools 注册表中
    cases = db.scalars(select(AgentEvalCase).where(AgentEvalCase.set_id == set_id)).all()
    tool_errors = agent_eval_runner.validate_tool_names(list(cases))
    if tool_errors:
        raise HTTPException(status_code=400, detail="工具名校验失败：" + "; ".join(tool_errors))
    if db.scalars(select(AgentEvalRun).where(AgentEvalRun.status.in_(("pending", "running")))).first():
        raise HTTPException(status_code=409, detail="已有评测运行进行中，请等待完成")
    model_name = ""
    if body.model_config_id is not None:
        cfg = llm_crud.get_config(db, body.model_config_id)
        if cfg is None:
            raise HTTPException(status_code=404, detail="模型配置不存在")
        model_name = cfg.model or ""
    run = AgentEvalRun(
        set_id=set_id,
        status="pending",
        stage="pending",
        total_cases=total,
        agent_id=body.agent_id or "assistant",
        model_config_id=body.model_config_id,
        model_name=model_name,
        created_by=user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    agent_eval_runner.start_run(run.id)
    return _run_dict(run)


@router.get("/runs", dependencies=[_VIEW])
def list_runs(
    set_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    base = select(AgentEvalRun)
    if set_id:
        base = base.where(AgentEvalRun.set_id == set_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    rows = db.scalars(
        base.order_by(AgentEvalRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": [_run_dict(x) for x in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/runs/{run_id}", dependencies=[_VIEW])
def run_detail(run_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    run = db.get(AgentEvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评测运行不存在")
    return {"run": _run_dict(run)}


@router.get("/runs/{run_id}/results", dependencies=[_VIEW])
def run_results(
    run_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    only_bad: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(AgentEvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评测运行不存在")
    base = select(AgentEvalResult).where(AgentEvalResult.run_id == run_id)
    rows = db.scalars(base.order_by(AgentEvalResult.created_at.asc(), AgentEvalResult.id.asc())).all()
    if only_bad:
        rows = [
            r
            for r in rows
            if (r.metrics or {}).get("bad_case_type") not in (None, "ok")
        ]
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    rows = rows[(page - 1) * page_size : page * page_size]
    return {"items": [_result_dict(x) for x in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/runs/{run_id}/compare", dependencies=[_VIEW])
def compare_runs(run_id: uuid.UUID, base_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """与基线运行对比：整体与冻结集指标差 + 逐条用例变化。"""
    run = db.get(AgentEvalRun, run_id)
    base = db.get(AgentEvalRun, base_id)
    if run is None or base is None:
        raise HTTPException(status_code=404, detail="评测运行不存在")
    cur_rows = {r.case_id: r for r in db.scalars(select(AgentEvalResult).where(AgentEvalResult.run_id == run_id)).all()}
    base_rows = {r.case_id: r for r in db.scalars(select(AgentEvalResult).where(AgentEvalResult.run_id == base_id)).all()}
    changes = []
    for case_id, cur in cur_rows.items():
        old = base_rows.get(case_id)
        if old is None:
            continue
        cur_passed = bool((cur.metrics or {}).get("passed"))
        old_passed = bool((old.metrics or {}).get("passed"))
        if cur_passed != old_passed:
            changes.append(
                {
                    "case_id": str(case_id),
                    "query": cur.query,
                    "was": "pass" if old_passed else "fail",
                    "now": "pass" if cur_passed else "fail",
                    "old_type": (old.metrics or {}).get("bad_case_type"),
                    "new_type": (cur.metrics or {}).get("bad_case_type"),
                }
            )
    return {
        "run": _run_dict(run),
        "base": _run_dict(base),
        "overall_diff": _metrics_diff(run.metrics, base.metrics),
        "frozen_diff": _metrics_diff(
            _split_metrics(run.metrics, "frozen"), _split_metrics(base.metrics, "frozen")
        ),
        "changes": changes,
    }


def _split_metrics(metrics: dict | None, split: str) -> dict:
    return ((metrics or {}).get("splits") or {}).get(split) or {}


def _metrics_diff(cur: dict | None, base: dict | None) -> dict:
    cur_o = (cur or {}).get("overall") if "overall" in (cur or {}) else (cur or {})
    base_o = (base or {}).get("overall") if "overall" in (base or {}) else (base or {})
    cur_o, base_o = cur_o or {}, base_o or {}
    out: dict[str, dict] = {}
    for key in ("tool_recall", "tool_precision", "seq_score", "first_tool_hit", "pass_rate", "abstention_rate", "fact_coverage"):
        a, b = base_o.get(key), cur_o.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out[key] = {"base": a, "now": b, "delta": round(b - a, 4)}
    return out


class HumanScoreIn(BaseModel):
    score: int = Field(ge=0, le=1)
    judge: str = ""
    reason: str = ""


@router.post("/results/{result_id}/human-score", dependencies=[_EDIT])
def set_human_score(
    result_id: uuid.UUID,
    body: HumanScoreIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    row = db.get(AgentEvalResult, result_id)
    if row is None:
        raise HTTPException(status_code=404, detail="评测结果不存在")
    row.human_score = body.score
    row.human_judge = body.judge or user.username or None
    row.human_at = datetime.now(UTC)
    row.human_reason = body.reason or None
    db.commit()
    return _result_dict(row)


__all__ = ["router"]
