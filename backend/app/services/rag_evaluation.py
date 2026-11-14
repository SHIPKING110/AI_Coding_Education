"""RAG 评测运行器：检索指标 + 重排 A/B + Bad Case 分类。

复用 evals.metrics 的纯函数指标，评测只读，不修改生产数据。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crud import rag_admin as crud
from app.models.rag_admin import RagEvalResult, RagEvalRun
from evals.metrics import compare_runs, evaluate_retrieval, normalize_relevant_keys

logger = logging.getLogger(__name__)

_SESSION_FACTORY = None


def _session_factory():
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        from app.core.database import SessionLocal

        _SESSION_FACTORY = SessionLocal
    return _SESSION_FACTORY


def classify_bad_case(ranked: list[str], relevant: list[str]) -> str:
    rel = set(relevant or [])
    if not rel:
        return "unanswerable"
    if not rel.intersection(ranked):
        return "retrieval_miss"
    for i, key in enumerate(ranked):
        if key in rel:
            return "ok" if i == 0 else "ranking_low"
    return "retrieval_miss"


def effective_parent_mode(requested: bool | None, set_domain: str | None) -> bool:
    """评测口径落到哪个向量集合：显式指定优先，未指定时跟随评测集 domain。

    家长客服评测必须与生产链路同口径（parent_mode=True → 家长专属集合），
    否则数字看似漂亮却测的是教师库检索。
    """
    if requested is not None:
        return bool(requested)
    return str(set_domain or "").strip() == "parent_service"


def _case_kind(case) -> str:
    """区分可答 / 不可答 / 未标注：只有可答用例参与 hit@k 等检索指标。

    优先使用用例上显式声明的 answerability（录入/导入时确定），
    仅对历史数据（未声明）回退到备注文本推断。
    """
    declared = str(getattr(case, "answerability", "") or "").strip().lower()
    if declared == "answerable":
        return "answerable" if (getattr(case, "relevant", None) or []) else "unlabeled"
    if declared in ("unanswerable", "unlabeled"):
        return declared
    if getattr(case, "relevant", None):
        return "answerable"
    text = " ".join(str(x or "") for x in (
        getattr(case, "source", ""), getattr(case, "notes", ""),
        getattr(case, "gt_answer", ""), getattr(case, "query_type", ""),
    )).lower()
    if "unanswerable" in text or "未提供" in text or "不可答" in text or "无答案" in text:
        return "unanswerable"
    return "unlabeled"


def _dedupe_hits(hits: list[dict]) -> list[dict]:
    """按文档去重，保留首次命中的分片：doc 级指标与上下文都不该被同一文档霸榜。"""
    out: list[dict] = []
    seen: set[str] = set()
    for h in hits:
        key = str(h.get("doc_id") or h.get("title") or "")
        if key:
            if key in seen:
                continue
            seen.add(key)
        out.append(h)
    return out


_PROGRESS_LAST_COMMIT = 0.0


def _set_progress(
    db: Session, run: RagEvalRun, *, stage: str, processed: int,
    total: int, percent: int, force: bool = False,
) -> None:
    """写入运行进度；节流 commit，避免逐条提交拖慢评测。"""
    global _PROGRESS_LAST_COMMIT
    run.stage = stage
    run.processed_cases = max(0, min(int(processed), max(int(total), 0)))
    run.total_cases = max(int(total), 0)
    run.progress = max(0, min(int(percent), 100))
    now = time.monotonic()
    if force or now - _PROGRESS_LAST_COMMIT >= 1.0:
        try:
            db.commit()
            _PROGRESS_LAST_COMMIT = now
        except Exception:  # 进度不是关键路径，失败不阻断评测
            db.rollback()


def _advance(
    db: Session, run: RagEvalRun, state: dict, *, stage: str, processed: int,
) -> None:
    state["done"] = int(state.get("done", 0)) + 1
    total = max(int(state.get("total", 1)), 1)
    percent = int(round(state["done"] * 100 / total))
    _set_progress(
        db, run, stage=stage, processed=processed, total=run.total_cases,
        percent=percent, force=state["done"] >= total,
    )


def _dataset_hash(cases: list) -> str:
    """评测集内容指纹：同配置版本下，数据变了也能从哈希看出不是同一批用例。"""
    parts = sorted(
        json.dumps(
            {
                "query": c.query,
                "relevant": c.relevant or [],
                "answerability": getattr(c, "answerability", ""),
                "split": getattr(c, "split", ""),
                "business_criticality": getattr(c, "business_criticality", ""),
                "gt_answer": c.gt_answer or "",
                "gt_keywords": c.gt_keywords or [],
                "query_type": c.query_type or "",
                "difficulty": c.difficulty or "",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for c in cases
    )
    return hashlib.sha256("\x1e".join(parts).encode("utf-8")).hexdigest()[:16]


def _build_snapshot(db: Session, run: RagEvalRun, cases: list) -> dict:
    """冻结本次运行环境：检索配置、集合指纹、分块参数与数据哈希。

    只记模型名/配置版本无法保证可复现——检索参数、Embedding 集合与评测集
    内容都可能在两次运行之间变化，快照让历史结果可解释、可回滚。
    """
    from app.services import rag as rag_service
    from app.services import rag_settings

    try:
        cfg = rag_settings.get_config(db) or {}
    except Exception:
        cfg = {}
    try:
        from app.core.config import get_settings

        code_version = get_settings().APP_VERSION
    except Exception:
        code_version = ""
    try:
        collection = rag_service.active_collection_name(parent=bool(run.parent_mode))
    except Exception:
        collection = ""
    return {
        "eval_set_id": str(run.set_id),
        "eval_cases": len(cases),
        "eval_set_hash": _dataset_hash(cases),
        "config_version": run.config_version,
        "config": cfg,
        "top_k": run.top_k,
        "retrieval_mode": run.retrieval_mode or "auto",
        "parent_mode": bool(run.parent_mode),
        "collection": collection,
        "code_version": code_version,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def start_run(run_id) -> None:
    """后台线程执行评测，接口立即返回。"""
    threading.Thread(target=_run, args=(str(run_id),), daemon=True).start()


def _resolve_run_models(db: Session, run: RagEvalRun, llm_context):
    """解析本次运行的生成模型与评测模型；显式配置不可用时让运行失败而非静默换模型。"""
    if not run.answer_eval:
        try:
            resolved = llm_context.optional_resolved(db, run.owner_id, "rag_eval")
        except Exception:
            resolved = None
        return resolved, resolved

    def _pick(config_id):
        if config_id is None:
            try:
                return llm_context.optional_resolved(db, run.owner_id, "rag_eval")
            except Exception:
                return None
        return llm_context.resolve_override(
            db, run.owner_id, "rag_eval", config_id=config_id
        )

    return _pick(run.generation_config_id), _pick(run.judge_config_id)


def _run(run_id: str) -> None:
    factory = _session_factory()
    db: Session = factory()
    try:
        run = db.get(RagEvalRun, uuid.UUID(run_id))
        if run is None:
            return
        run.status = "running"
        run.stage = "pending"
        run.progress = 0
        run.processed_cases = 0
        db.commit()
        cases = crud.list_eval_cases(db, run.set_id)
        if not cases:
            run.status = "failed"
            run.stage = "failed"
            run.error = "评测集为空"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return
        run.total_cases = len(cases)
        # 冻结运行环境快照：配置/集合/评测集哈希，保证历史结果可复现
        run.eval_snapshot = _build_snapshot(db, run, cases)
        _set_progress(
            db, run, stage="retrieval_off", processed=0, total=len(cases),
            percent=0, force=True,
        )
        # 评测的 LLM 调用（生成回答 / 裁判打分）归因到 rag_eval 模块，
        # 以便在「用量与成本」中单独统计评测成本；无可用个人模型时优雅降级。
        from app.services import llm_context

        gen_resolved, judge_resolved = _resolve_run_models(db, run, llm_context)
        snapshot = dict(run.eval_snapshot or {})
        snapshot.update({
            "generation_model": getattr(gen_resolved, "model", "") if gen_resolved else run.generation_model,
            "judge_model": getattr(judge_resolved, "model", "") if judge_resolved else run.judge_model,
            "generation_config_id": str(run.generation_config_id) if run.generation_config_id else None,
            "judge_config_id": str(run.judge_config_id) if run.judge_config_id else None,
        })
        run.eval_snapshot = snapshot
        db.commit()
        progress_state = {"done": 0, "total": len(cases) * (3 if run.answer_eval else 2)}
        with llm_context.use_llm(gen_resolved):
            off_metrics, _, off_cases = _run_pass(
                db, run, cases, rerank=False, pass_name="off", progress_state=progress_state,
                gen_resolved=gen_resolved, judge_resolved=judge_resolved,
            )
            on_metrics, rows, on_cases = _run_pass(
                db, run, cases, rerank=True, pass_name="on", progress_state=progress_state,
                gen_resolved=gen_resolved, judge_resolved=judge_resolved,
            )
        run.metrics = {
            "off": off_metrics,
            "on": on_metrics,
            "answer": _aggregate_answer(rows),
            # 业务关键用例必须单独看：平均值会被大量普通用例稀释
            "critical": _slice_metrics(on_cases, "business_criticality", "critical"),
            "frozen": _slice_metrics(on_cases, "split", "frozen"),
            # 裁判可信度：先记录样本对数，人工复核后由校准接口重算 Kappa；
            # 发行候选运行在「同裁判+同生成模型+同数据集」时可继承基线运行的校准
            "calibration": _build_calibration(rows),
        }
        inherited = _inherit_calibration(db, run, run.metrics["calibration"])
        if inherited is not None:
            run.metrics["calibration"] = inherited
        run.compare = compare_runs(off_metrics, on_metrics, key="hit@3")
        try:
            prev = crud.previous_done_run(db, run.set_id, run.id)
            run.metrics["gate"] = evaluate_run_gate(
                run.metrics,
                prev.metrics if prev else None,
            )
        except Exception:  # noqa: BLE001
            logger.exception("评测闸门判断失败，不影响结果入库")
            run.metrics["gate"] = {"passed": None, "reasons": ["闸门判断异常"], "gate": "skip"}
        run.status = "done"
        run.stage = "done"
        run.progress = 100
        run.processed_cases = len(cases)
        run.finished_at = datetime.now(timezone.utc)
        # 保存 rerank=on 的逐条结果（与前端展示一致）
        for c, row in zip(cases, rows):
            db.add(RagEvalResult(
                run_id=run.id, case_id=c.id, query=c.query,
                ranked=row["ranked"], relevant=row["relevant"], hits=row["hits"],
                metrics=row["metrics"], retrieval_summary=row["retrieval_summary"],
                bad_case_type=row["bad_case_type"],
            ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("rag eval run failed")
        try:
            run = db.get(RagEvalRun, uuid.UUID(run_id))
            if run is not None:
                run.status = "failed"
                run.stage = "failed"
                run.error = str(exc) or exc.__class__.__name__
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _build_calibration(rows: list[dict]) -> dict:
    """把 LLM Judge 分数与（尚未打分的人工）配对，首次运行时人工分为空。"""
    pairs: list[dict] = []
    for r in rows:
        answer = r.get("metrics", {}).get("answer", {}) if isinstance(r.get("metrics"), dict) else {}
        judge = answer.get("judge") if isinstance(answer, dict) else None
        if not isinstance(judge, dict):
            continue
        pairs.append({
            "llm": {"correctness": judge.get("correctness")},
            "human_score": None,  # 运行时尚未人工复核
        })
    from evals.metrics import calibration_from_pairs
    return calibration_from_pairs(pairs, dimension="correctness")


def choose_inherited_calibration(
    current: dict, snapshot: dict, previous_runs: list[tuple[dict, dict]],
) -> dict | None:
    """发行候选运行的校准继承：同一裁判 + 同一生成模型 + 同一评测集哈希时，
    沿用此前运行已人工复核的 Kappa，避免对同一配置重复人工打分。

    previous_runs 为 [(eval_snapshot, metrics), ...]，按新→旧排列；只接受
    pairs ≥ GATE_KAPPA_MIN_PAIRS 的已完成校准。返回 None 表示无可继承样本。
    """
    if int((current or {}).get("pairs") or 0) >= GATE_KAPPA_MIN_PAIRS:
        return None
    set_hash = (snapshot or {}).get("eval_set_hash")
    judge = (snapshot or {}).get("judge_model")
    gen = (snapshot or {}).get("generation_model")
    if not set_hash or not judge:
        return None
    for prev_snap, prev_metrics in previous_runs:
        prev_snap = prev_snap or {}
        if prev_snap.get("eval_set_hash") != set_hash:
            continue
        if prev_snap.get("judge_model") != judge or prev_snap.get("generation_model") != gen:
            continue
        calib = (prev_metrics or {}).get("calibration")
        if isinstance(calib, dict) and int(calib.get("pairs") or 0) >= GATE_KAPPA_MIN_PAIRS:
            out = dict(calib)
            out["inherited_from_run"] = str(prev_snap.get("run_id") or "")
            return out
    return None


def _inherit_calibration(db: Session, run: RagEvalRun, current: dict) -> dict | None:
    """从同集历史运行中挑选可继承的校准（见 choose_inherited_calibration）。"""
    try:
        prev_runs = [r for r in crud.list_eval_runs(db, set_id=run.set_id, limit=50)
                     if r.id != run.id and r.status == "done" and r.answer_eval]
    except Exception:
        return None
    pairs: list[tuple[dict, dict]] = []
    for prev in prev_runs:
        snap = dict(prev.eval_snapshot or {})
        snap.setdefault("run_id", str(prev.id))
        pairs.append((snap, prev.metrics or {}))
    return choose_inherited_calibration(current, run.eval_snapshot or {}, pairs)


def _slice_metrics(cases: list[dict], field: str, value: str) -> dict:
    """按冻结集/关键度切片，避免关键用例被总体平均值掩盖。"""
    selected = [c for c in cases if c.get(field) == value]
    return evaluate_retrieval(selected, k_values=(1, 3, 5))


def _run_pass(
    db: Session, run: RagEvalRun, cases: list, *, rerank: bool,
    pass_name: str, progress_state: dict,
    gen_resolved=None, judge_resolved=None,
) -> tuple[dict, list[dict], list[dict]]:
    from app.services import rag as rag_service
    from app.services import rag_trace

    eval_cases: list[dict] = []
    rows: list[dict] = []
    total = len(cases)
    stage_retrieval = "retrieval_off" if pass_name == "off" else "retrieval_on"

    def _percent() -> int:
        return int(round(progress_state["done"] * 100 / max(progress_state["total"], 1)))

    for idx, c in enumerate(cases):
        _set_progress(
            db, run, stage=stage_retrieval, processed=idx, total=total,
            percent=_percent(),
        )
        diag: dict = {}
        exec_status = "ok"
        exec_error = None
        try:
            with rag_trace.trace_scope(
                domain="eval", owner_id=run.owner_id, conversation_id=run.id,
                route=f"eval:{'on' if rerank else 'off'}",
            ):
                hits = rag_service.retrieve(
                    c.query, db=db, owner_id=run.owner_id, top_k=run.top_k,
                    rerank=rerank, diag=diag, route_key="eval",
                    parent_mode=bool(run.parent_mode),
                    hybrid_override=(
                        True if run.retrieval_mode == "hybrid" else
                        False if run.retrieval_mode == "dense" else None
                    ),
                    # 评测是文档级指标：每个文档只取一个最佳分片，避免同一长文档霸榜
                    per_doc_cap=1,
                )
        except Exception as exc:  # noqa: BLE001
            # 服务异常不是普通漏召回：保留错误状态，指标层排除该 case 分母。
            hits = []
            exec_status = "error"
            exec_error = str(exc) or exc.__class__.__name__
        hits = _dedupe_hits(hits)
        retrieval_mode = (
            "error" if exec_status == "error"
            else str((diag or {}).get("retrieval_mode") or "unknown")
        )
        ranked = [h.get("title", "") for h in hits]
        relevant_raw = list(c.relevant or [])
        relevant = normalize_relevant_keys(ranked, relevant_raw)
        answerable = bool(relevant_raw)
        case_kind = _case_kind(c)
        criticality = str(getattr(c, "business_criticality", "") or "normal")
        split = str(getattr(c, "split", "") or "regression")
        one = {
            "query": c.query, "ranked": ranked, "relevant": relevant,
            "answerable": answerable, "case_kind": case_kind,
            "exec_status": exec_status,
            "business_criticality": criticality, "split": split,
            "retrieval_mode": retrieval_mode,
        }
        eval_cases.append(one)
        row_metrics: dict = {
            "answerable": answerable, "case_kind": case_kind,
            "exec_status": exec_status, "business_criticality": criticality,
            "split": split, "retrieval_mode": retrieval_mode,
            "vector": bool(diag.get("vector")), "keyword": bool(diag.get("keyword")),
            "rerank": bool(diag.get("rerank")),
            # 检索观测（ADR-0027）：关键词腿在最终 top-k 中的贡献数与低置信标记
            "keyword_leg_hits": int((diag or {}).get("keyword_leg_hits") or 0),
            "low_confidence": bool((diag or {}).get("low_confidence")),
        }
        if exec_error:
            row_metrics["error"] = exec_error
        if answerable and exec_status == "ok":
            row_metrics.update({
                "hit@1": 1.0 if ranked[:1] and set(ranked[:1]) & set(relevant) else 0.0,
                "hit@3": 1.0 if ranked[:3] and set(ranked[:3]) & set(relevant) else 0.0,
                "mrr": next((1.0 / (i + 1) for i, k in enumerate(ranked) if k in set(relevant)), 0.0),
            })
        rows.append({
            "query": c.query,
            "ranked": ranked,
            "relevant": relevant,
            "hits": [
                {
                    "doc_id": h.get("doc_id"), "title": h.get("title"),
                    "similarity": h.get("similarity"), "rerank_score": h.get("rerank_score"),
                    # 每条命中来自哪条召回腿（ADR-0027 观测）：vector / keyword / 双命中
                    "legs": h.get("legs") or (["vector"] if h.get("similarity") is not None else None),
                    "vector_rank": h.get("vector_rank"),
                    "keyword_rank": h.get("keyword_rank"),
                    "preview": (h.get("text") or "")[:300],
                }
                for h in hits
            ],
            "metrics": row_metrics,
            "retrieval_summary": rag_service.retrieval_summary(diag),
            "bad_case_type": (
                "retrieval_error" if exec_status == "error"
                else classify_bad_case(ranked, relevant) if answerable else case_kind
            ),
            "exec_status": exec_status,
            "trace_id": diag.get("trace_id"),
        })
        _advance(db, run, progress_state, stage=stage_retrieval, processed=idx + 1)
        if run.answer_eval and rerank and exec_status == "ok":
            _set_progress(
                db, run, stage="answer", processed=idx, total=total,
                percent=_percent(),
            )
            ans = _answer_case(
                c, hits, gen_resolved=gen_resolved, judge_resolved=judge_resolved,
                answerable=answerable,
            )
            rows[-1]["answer"] = ans
            rows[-1]["metrics"]["answer"] = ans
            _advance(db, run, progress_state, stage="answer", processed=idx + 1)
    return evaluate_retrieval(eval_cases, k_values=(1, 3, 5)), rows, eval_cases


_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cnum_to_arabic(s: str) -> str:
    """常见中文数字转阿拉伯数字（0-99）：七级→7级、十二周岁→12周岁、二十→20。

    关键词与回答两侧都做同一转换，避免「七级80分」与「7级80分」这类写法差异被误判为漏命中。
    """
    def repl_xy(m: re.Match) -> str:
        tens = _CN_DIGITS.get(m.group(1), 1)
        ones = _CN_DIGITS.get(m.group(2), 0) if m.group(2) else 0
        return str(tens * 10 + ones)

    s = re.sub(r"([一二两三四五六七八九])十([一二三四五六七八九])?", repl_xy, s)
    s = re.sub(r"十([一二三四五六七八九])", lambda m: str(10 + _CN_DIGITS[m.group(1)]), s)
    return "".join(str(_CN_DIGITS[c]) if c in _CN_DIGITS else c for c in s)


def _normalize_match(text: str) -> str:
    """关键词匹配前归一化：全半角、大小写、中文数字、比较符号与标点差异不应算漏命中。"""
    s = unicodedata.normalize("NFKC", text or "").lower()
    s = _cnum_to_arabic(s)
    s = re.sub(r"\s+", "", s)
    return re.sub(r"[，。！？、；：,.!?;:\"'“”‘’（）()【】\[\]《》<>—–\-_/≥≤≈~±+=|·…]", "", s)


def _keyword_appears(answer_norm: str, keyword: str) -> bool:
    """关键词命中判定。

    1) 归一化后连续包含 → 命中；
    2) 否则按子序列匹配，仅允许关键词字符之间插入 ASCII 字母/数字片段
       （覆盖「回答写免CSP-J第一轮、标注写免第一轮」这类编号插入写法）；
       间隔中出现中文则视为不同表述，不算命中，避免跨句拼接造成虚高。
    """
    key = _normalize_match(keyword)
    if not key:
        return True
    if key in answer_norm:
        return True
    i = 0
    prev_end: int | None = None
    for ch in key:
        j = answer_norm.find(ch, i)
        if j < 0:
            return False
        if prev_end is not None and j > prev_end:
            if not re.fullmatch(r"[a-z0-9]*", answer_norm[prev_end:j]):
                return False
        prev_end = j + 1
        i = j + 1
    return True


# 拒答判定只看回答开头：长答案中顺带说“片段未提及某细节”不代表整体拒答
# （曾导致三条可答用例被误计弃答，abstention_rate 虚高）。
_ABSTAIN_RE = re.compile(
    r"文档未提供|未提供|不知道|无法回答|无法确定|无法确认|未提及|并未提及|未说明|没有明确说明"
    r"|没有(?:相关|明确|具体)?(?:信息|内容|答案|数据)"
)
_ABSTAIN_HEAD_CHARS = 24

# 引用标记：兼容 [1]、[1,2]、[1][2]、^1,2^、【1】 等常见写法
_CITE_BRACKET_RE = re.compile(r"[\[【]\s*(\d+(?:\s*[,，、]\s*\d+)*)\s*[\]】]")
_CITE_CARET_RE = re.compile(r"\^\s*(\d+(?:\s*[,，、]\s*\d+)*)\s*\^")


def _parse_citations(answer: str, n_contexts: int) -> dict:
    """解析回答里的来源编号并校验范围，供引用覆盖率/无效引用统计。"""
    indices: set[int] = set()
    for pattern in (_CITE_BRACKET_RE, _CITE_CARET_RE):
        for m in pattern.finditer(answer or ""):
            for part in re.split(r"[,，、]", m.group(1)):
                part = part.strip()
                if part.isdigit():
                    indices.add(int(part))
    cited = sorted(indices)
    invalid = [i for i in cited if i < 1 or i > n_contexts]
    return {"indices": cited, "invalid": invalid, "present": bool(cited)}


def _answer_case(
    case, hits: list[dict], *, gen_resolved=None, judge_resolved=None,
    answerable: bool = True,
) -> dict:
    """Q-DOC-A：生成回答并计算关键词命中 + 引用校验 + LLM 质量评分。

    无依据回答（unsupported）判定：未拒答、非空回答，且裁判忠实度 < 3 分——
    流畅但没有片段依据的回答在企业知识库中属于失败，需要单独统计而不是
    被平均分掩盖。
    """
    from app.services import llm_context

    contexts = [h.get("text", "") for h in hits[:5]]
    with llm_context.use_llm(gen_resolved):
        answer = _generate_answer(case.query, contexts)
    keywords = [str(k).strip() for k in (case.gt_keywords or []) if str(k).strip()]
    answer_norm = _normalize_match(answer)
    missing = [k for k in keywords if not _keyword_appears(answer_norm, k)]
    keyword_hit = round((len(keywords) - len(missing)) / len(keywords), 4) if keywords else None
    abstained = bool(_ABSTAIN_RE.search((answer or "")[:_ABSTAIN_HEAD_CHARS]))
    citation = _parse_citations(answer, len(contexts))
    with llm_context.use_llm(judge_resolved):
        judge = _judge_quality(
            case.query, contexts, answer, gt_answer=case.gt_answer or "",
        )
    faithfulness = judge.get("faithfulness") if isinstance(judge, dict) else None
    unsupported = bool(
        answer and not abstained
        and isinstance(faithfulness, (int, float)) and faithfulness < 3
    )
    return {
        "answer": answer,
        "answerable": answerable,
        "abstained": abstained,
        "keyword_hit": keyword_hit,
        "keyword_missing": missing,
        "citation": citation,
        "unsupported": unsupported,
        "judge": judge,
    }


def _generate_answer(query: str, contexts: list[str]) -> str:
    try:
        from app.services import llm

        system = (
            "你是知识库问答助手。只能依据提供的片段回答，不得使用片段外的常识、记忆或猜测。"
            "请先通读全部片段并逐条提取相关信息；如果片段中列出了多项内容（课程、条件、数值、时间、流程），"
            "必须完整列出，不要遗漏。只有在全部片段都与问题无关、确实没有任何可用信息时，才输出：文档未提供。"
            "回答时在引用的句子后标注来源编号，如 [1]、[1][2]，编号对应片段序号。"
            "不要根据相似问题推断答案。"
        )
        prompt = (
            f"问题：{query}\n\n片段：\n"
            + ("\n---\n".join(f"[{i+1}] {c[:800]}" for i, c in enumerate(contexts)) or "（无检索片段）")
            + "\n\n请先完整阅读全部片段，判断是否有足以回答的信息；有则给出完整答案（含关键数值、条件与条目），确实没有才输出：文档未提供。"
        )
        return "".join(llm.stream_text(system, prompt)).strip()
    except Exception:
        return ""


def _judge_quality(
    query: str, contexts: list[str], answer: str, gt_answer: str = "",
) -> dict | None:
    try:
        from app.services import llm
        from app.services.rag_judge import parse_judge_json

        required = ["faithfulness", "relevance", "completeness", "logic", "correctness"]
        context_text = "\n---\n".join(
            f"[{i+1}] {c[:800]}" for i, c in enumerate(contexts[:5])
        ) or "（无）"
        system = "你是 RAG 答案质量裁判，只输出 JSON。"
        prompt = (
            "请严格按 0-5 整数打分，必须输出全部字段；缺失字段视为无效输出。\n"
            "维度：faithfulness（是否忠于片段）、relevance（是否回答问题）、"
            "completeness（是否覆盖关键信息）、logic（逻辑性）、"
            "correctness（与标准答案事实是否一致）。\n"
            "只输出一行 JSON：{\"faithfulness\":0,\"relevance\":0,\"completeness\":0,"
            "\"logic\":0,\"correctness\":0,\"reason\":\"...\"}\n\n"
            f"问题：{query}\n"
            f"标准答案（可为空）：{gt_answer[:1200] or '（无）'}\n"
            f"片段：\n{context_text}\n"
            f"回答：{answer[:2000] or '（空回答）'}"
        )
        text = llm.invoke_text(system, prompt, temperature=0.0, timeout=120).strip()
        parsed = parse_judge_json(text)
        missing = [k for k in required if f'"{k}"' not in text]
        if missing:
            retry_prompt = (
                "上一次输出缺少以下字段：" + "、".join(missing) + "。\n"
                "请只输出这些字段的 JSON（0-5 整数），不要重复解释。\n\n"
                f"问题：{query}\n"
                f"标准答案（可为空）：{gt_answer[:1200] or '（无）'}\n"
                f"片段：\n{context_text}\n"
                f"回答：{answer[:2000] or '（空回答）'}"
            )
            retry = parse_judge_json(
                llm.invoke_text(system, retry_prompt, temperature=0.0, timeout=120).strip()
            )
            for key in missing:
                if isinstance(retry.get(key), (int, float)):
                    parsed[key] = retry[key]
        return parsed
    except Exception:
        return None


def _agg_answer_subset(answers: list[dict]) -> dict:
    if not answers:
        return {"cases": 0}
    scored = [a for a in answers if isinstance(a.get("keyword_hit"), (int, float))]
    scored_non_abs = [
        a for a in answers
        if not a.get("abstained") and isinstance(a.get("keyword_hit"), (int, float))
    ]
    judged = [a["judge"] for a in answers if isinstance(a.get("judge"), dict)]
    out = {
        "cases": len(answers),
        "keyword_hit": round(sum(a["keyword_hit"] for a in scored) / len(scored), 4) if scored else None,
        # 剔除拒答（abstained）后的命中率：拒答场景由「不可答拒答率」单独衡量，
        # 混入平均会把真实覆盖短板与拒答行为搅在一起。
        "keyword_hit_non_abstained": (
            round(sum(a["keyword_hit"] for a in scored_non_abs) / len(scored_non_abs), 4)
            if scored_non_abs else None
        ),
        "abstention_rate": round(
            sum(1 for a in answers if a.get("abstained")) / len(answers), 4
        ) if answers else None,
    }
    non_abstained = [a for a in answers if not a.get("abstained") and a.get("answer")]
    cited = [a for a in non_abstained if (a.get("citation") or {}).get("present")]
    invalid_cite = [a for a in non_abstained if (a.get("citation") or {}).get("invalid")]
    if non_abstained:
        out["citation_coverage"] = round(len(cited) / len(non_abstained), 4)
        out["invalid_citation_rate"] = round(len(invalid_cite) / len(non_abstained), 4)
    out["unsupported_answer_rate"] = round(
        sum(1 for a in answers if a.get("unsupported")) / len(answers), 4
    ) if answers else None
    for key in ("faithfulness", "relevance", "completeness", "expression", "logic", "correctness"):
        vals = [j[key] for j in judged if isinstance(j.get(key), (int, float))]
        out[key] = round(sum(vals) / len(vals), 2) if vals else None
    return out


# 验收闸门阈值：冻结集/关键用例是最终判据，总体平均值不足以抵消回退。
GATE_FROZEN_HIT3_MAX_DROP = 0.02      # 冻结集 hit@3 下降容忍 2 个百分点
GATE_CRITICAL_HIT3_MAX_DROP = 0.02    # 关键用例 hit@3 下降容忍 2 个百分点
GATE_UNSUPPORTED_MAX = 0.05           # 无依据回答率上限 5%
GATE_ERROR_RATE_MAX = 0.001           # 检索异常率必须接近 0
GATE_KAPPA_MIN = 0.6                  # （观察指标：ADR-0027 起不再作为闸门依据）
GATE_KAPPA_MIN_PAIRS = 10             # 少于该样本对数不做校准判定


def _evaluate_calibration(report: dict | None) -> list[str]:
    """按四指标 SLA 判定人工校准（ADR-0027）；返回不达标原因列表。

    兼容旧数据：若无 exact/within1/severe 字段（旧版 calibration），仅提示
    需重算，不直接判 fail——避免历史运行被新口径误杀。
    """
    from evals.metrics import CALIB_MIN_PAIRS, calibration_sla

    if not isinstance(report, dict):
        return []
    pairs = int(report.get("pairs") or 0)
    if pairs < CALIB_MIN_PAIRS:
        return []
    if not all(k in report for k in ("exact_rate", "within1_rate", "severe_rate")):
        return ["人工校准数据为旧口径，重评任意一条即可按四指标 SLA 重算"]
    sla = report.get("sla") if isinstance(report.get("sla"), dict) else calibration_sla(report)
    if sla.get("passed") is False:
        return [f"人工校准未达 SLA：{r}" for r in (sla.get("reasons") or [])] or ["人工校准未达 SLA"]
    return []


def _slice_val(metrics: dict, *path: str):
    cur: dict | None = metrics
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur if isinstance(cur, (int, float)) else None


def evaluate_run_gate(current: dict, previous: dict | None) -> dict:
    """基于同评测集的当前运行与上一完成运行，做验收闸门判断。

    只对有 `frozen` / `critical` 切片的运行生效：没有冻结集时返回
    `passed=None`（提示先建冻结集），不阻断日常调参。

    裁判可信度（ADR-0027）：人工样本足够（≥10 对）时按四指标 SLA 判定——
    严重分歧率（|Δ|≥3）≤5%、±1 内一致率 ≥85%、严格一致率 ≥60%、
    |bias| ≤0.3；Kappa 保留为观察指标，不参与判定。尚未复核时跳过该项。
    """
    reasons: list[str] = []
    frozen_cur = _slice_val(current, "frozen", "hit@3")
    critical_cur = _slice_val(current, "critical", "hit@3")
    unsupported = _slice_val(current, "answer", "unsupported_answer_rate")
    error_rate = current.get("eval_error_rate") if isinstance(current, dict) else None

    # 裁判可信度校验（先于切片判断：校准不达标时结论整体不可信）
    calibration = current.get("calibration") if isinstance(current, dict) else None
    reasons.extend(_evaluate_calibration(calibration))

    if frozen_cur is None and critical_cur is None:
        if reasons:
            return {"passed": False, "reasons": reasons, "gate": "fail"}
        return {"passed": None, "reasons": ["未检测到冻结集/关键用例切片，跳过闸门判断"], "gate": "skip"}

    if previous:
        frozen_prev = _slice_val(previous, "frozen", "hit@3")
        critical_prev = _slice_val(previous, "critical", "hit@3")
        if frozen_cur is not None and frozen_prev is not None:
            drop = round(frozen_prev - frozen_cur, 4)
            if drop > GATE_FROZEN_HIT3_MAX_DROP:
                reasons.append(f"冻结集 hit@3 下降 {drop:.2%}，超过容忍 {GATE_FROZEN_HIT3_MAX_DROP:.2%}")
        if critical_cur is not None and critical_prev is not None:
            drop = round(critical_prev - critical_cur, 4)
            if drop > GATE_CRITICAL_HIT3_MAX_DROP:
                reasons.append(f"关键用例 hit@3 下降 {drop:.2%}，超过容忍 {GATE_CRITICAL_HIT3_MAX_DROP:.2%}")

    if unsupported is not None and unsupported > GATE_UNSUPPORTED_MAX:
        reasons.append(f"无依据回答率 {unsupported:.2%} 超过上限 {GATE_UNSUPPORTED_MAX:.2%}")
    if error_rate is not None and error_rate > GATE_ERROR_RATE_MAX:
        reasons.append(f"检索异常率 {error_rate:.2%} 超过上限 {GATE_ERROR_RATE_MAX:.2%}")

    passed = len(reasons) == 0
    return {"passed": passed, "reasons": reasons, "gate": "pass" if passed else "fail"}


def recompute_run_calibration(db: Session, run_id) -> dict:
    """人工复核后重算某次运行的 LLM-人工一致性并刷新闸门。

    仅在该 run 结果为 done 时生效；从每条 RagEvalResult 提取
    `metrics.answer.judge.correctness` 与 `human_score` 配对。
    """
    from evals.metrics import calibration_from_pairs

    run = db.get(RagEvalRun, run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id)))
    if run is None or run.status != "done" or not isinstance(run.metrics, dict):
        return {}
    pairs: list[dict] = []
    for r in crud.list_eval_results(db, run.id):
        answer = (r.metrics or {}).get("answer") if isinstance(r.metrics, dict) else None
        judge = answer.get("judge") if isinstance(answer, dict) else None
        pairs.append({
            "llm": {"correctness": judge.get("correctness")} if isinstance(judge, dict) else None,
            "human_score": r.human_score,
        })
    calibration = calibration_from_pairs(pairs, dimension="correctness")
    # metrics 是普通 JSON 列：对已加载对象的原地修改不会被 SQLAlchemy 变更追踪捕获
    # （commit 相当于空写）。必须整体重新赋值，否则人工复核后的 Kappa/闸门重算永不落库。
    metrics = dict(run.metrics)
    metrics["calibration"] = calibration
    try:
        prev = crud.previous_done_run(db, run.set_id, run.id)
        metrics["gate"] = evaluate_run_gate(metrics, prev.metrics if prev else None)
    except Exception:  # noqa: BLE001
        logger.exception("重算闸门失败")
    run.metrics = metrics
    db.commit()
    return calibration


def _aggregate_answer(rows: list[dict]) -> dict:
    answers = [r.get("answer") for r in rows if r.get("answer")]
    if not answers:
        return {"cases": 0}
    answerable = [a for a in answers if a.get("answerable", True)]
    unanswerable = [a for a in answers if not a.get("answerable", True)]
    out = _agg_answer_subset(answers)
    out["answerable_cases"] = len(answerable)
    out["unanswerable_cases"] = len(unanswerable)
    out["answerable"] = _agg_answer_subset(answerable)
    out["unanswerable"] = _agg_answer_subset(unanswerable)
    return out


def generate_cases(
    db: Session, *, set_id, doc_ids: list, count: int = 10,
    owner_id=None, use_llm: bool = False,
) -> dict:
    """从文档分片生成候选评测用例；LLM 不可用时退化为确定性模板。"""
    from app.services import rag as rag_service

    created = 0
    skipped = 0
    for doc_id in doc_ids:
        if created >= count:
            break
        chunks = rag_service.get_document_chunks(doc_id, limit=20)
        for ch in chunks:
            if created >= count:
                break
            title = ch.get("title") or "未命名文档"
            preview = ch.get("preview") or ""
            if len(preview.strip()) < 20:
                skipped += 1
                continue
            query = _template_query(title, preview)
            if use_llm:
                query = _llm_query(title, preview) or query
            relevant = [title]
            crud.add_eval_case(
                db, set_id=set_id, query=query, relevant=relevant,
                gt_answer=preview[:500], gt_keywords=[],
                query_type="fact", difficulty="normal",
                notes="自动生成候选，请人工复核后使用", source="llm" if use_llm else "template",
            )
            created += 1
    return {"created": created, "skipped": skipped}


def _template_query(title: str, text: str) -> str:
    snippet = re.sub(r"\s+", "", text)[:16] or "主要内容"
    return f"《{title}》中关于「{snippet}」的要点是什么？"


def _llm_query(title: str, text: str) -> str | None:
    try:
        from app.services import llm

        system = "你是 RAG 评测集生成器，只输出 JSON。"
        prompt = (
            "根据下面的文档片段，生成一个用户可能提出的、需要该片段才能回答的问题。\n"
            "只输出 JSON：{\"query\": \"...\"}\n\n"
            f"文档标题：{title}\n片段：{text[:800]}"
        )
        raw = "".join(llm.stream_text(system, prompt))
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None
        data = json.loads(m.group(0))
        q = str(data.get("query") or "").strip()
        return q or None
    except Exception:
        return None


__all__ = ["start_run", "classify_bad_case", "generate_cases"]
