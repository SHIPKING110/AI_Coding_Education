"""RAG 评测运行器：检索指标 + 重排 A/B + Bad Case 分类。

复用 evals.metrics 的纯函数指标，评测只读，不修改生产数据。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crud import rag_admin as crud
from app.models.rag_admin import RagEvalResult, RagEvalRun
from evals.metrics import compare_runs, evaluate_retrieval

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
        return "false_positive" if ranked else "ok"
    if not rel.intersection(ranked):
        return "retrieval_miss"
    for i, key in enumerate(ranked):
        if key in rel:
            return "ok" if i == 0 else "ranking_low"
    return "retrieval_miss"


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
        db.commit()
        cases = crud.list_eval_cases(db, run.set_id)
        if not cases:
            run.status = "failed"
            run.error = "评测集为空"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return
        # 评测的 LLM 调用（生成回答 / 裁判打分）归因到 rag_eval 模块，
        # 以便在「用量与成本」中单独统计评测成本；无可用个人模型时优雅降级。
        from app.services import llm_context

        gen_resolved, judge_resolved = _resolve_run_models(db, run, llm_context)
        with llm_context.use_llm(gen_resolved):
            off_metrics, _ = _run_pass(
                db, run, cases, rerank=False,
                gen_resolved=gen_resolved, judge_resolved=judge_resolved,
            )
            on_metrics, rows = _run_pass(
                db, run, cases, rerank=True,
                gen_resolved=gen_resolved, judge_resolved=judge_resolved,
            )
        run.metrics = {"off": off_metrics, "on": on_metrics, "answer": _aggregate_answer(rows)}
        run.compare = compare_runs(off_metrics, on_metrics, key="hit@3")
        run.status = "done"
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
                run.error = str(exc) or exc.__class__.__name__
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _run_pass(
    db: Session, run: RagEvalRun, cases: list, *, rerank: bool,
    gen_resolved=None, judge_resolved=None,
) -> tuple[dict, list[dict]]:
    from app.services import rag as rag_service
    from app.services import rag_trace

    eval_cases: list[dict] = []
    rows: list[dict] = []
    for c in cases:
        diag: dict = {}
        try:
            with rag_trace.trace_scope(
                domain="eval", owner_id=run.owner_id, conversation_id=run.id,
                route=f"eval:{'on' if rerank else 'off'}",
            ):
                hits = rag_service.retrieve(
                    c.query, db=db, owner_id=run.owner_id, top_k=run.top_k,
                    rerank=rerank, diag=diag, route_key="eval",
                )
        except Exception:
            hits = []
        ranked = [h.get("title", "") for h in hits]
        relevant = list(c.relevant or [])
        one = {"query": c.query, "ranked": ranked, "relevant": relevant}
        eval_cases.append(one)
        rows.append({
            "query": c.query,
            "ranked": ranked,
            "relevant": relevant,
            "hits": [
                {
                    "doc_id": h.get("doc_id"), "title": h.get("title"),
                    "similarity": h.get("similarity"), "rerank_score": h.get("rerank_score"),
                    "preview": (h.get("text") or "")[:300],
                }
                for h in hits
            ],
            "metrics": {
                "hit@1": 1.0 if ranked[:1] and set(ranked[:1]) & set(relevant) else 0.0,
                "hit@3": 1.0 if ranked[:3] and set(ranked[:3]) & set(relevant) else 0.0,
                "mrr": next((1.0 / (i + 1) for i, k in enumerate(ranked) if k in set(relevant)), 0.0),
            },
            "retrieval_summary": rag_service.retrieval_summary(diag),
            "bad_case_type": classify_bad_case(ranked, relevant),
            "trace_id": diag.get("trace_id"),
        })
        if run.answer_eval and rerank:
            ans = _answer_case(c, hits, gen_resolved=gen_resolved, judge_resolved=judge_resolved)
            rows[-1]["answer"] = ans
            rows[-1]["metrics"]["answer"] = ans
    return evaluate_retrieval(eval_cases, k_values=(1, 3, 5)), rows


def _answer_case(case, hits: list[dict], *, gen_resolved=None, judge_resolved=None) -> dict:
    """Q-DOC-A：生成回答并计算关键词命中 + LLM 质量评分。"""
    from app.services import llm_context

    contexts = [h.get("text", "") for h in hits[:5]]
    with llm_context.use_llm(gen_resolved):
        answer = _generate_answer(case.query, contexts)
    keywords = [str(k).strip() for k in (case.gt_keywords or []) if str(k).strip()]
    missing = [k for k in keywords if k not in answer]
    keyword_hit = round((len(keywords) - len(missing)) / len(keywords), 4) if keywords else None
    with llm_context.use_llm(judge_resolved):
        judge = _judge_quality(case.query, contexts, answer)
    return {
        "answer": answer,
        "keyword_hit": keyword_hit,
        "keyword_missing": missing,
        "judge": judge,
    }


def _generate_answer(query: str, contexts: list[str]) -> str:
    try:
        from app.services import llm

        system = "你是知识库问答助手。只依据提供的片段回答；片段不足时明确说不知道，不要编造。"
        prompt = (
            f"问题：{query}\n\n片段：\n"
            + ("\n---\n".join(f"[{i+1}] {c[:800]}" for i, c in enumerate(contexts)) or "（无检索片段）")
        )
        return "".join(llm.stream_text(system, prompt)).strip()
    except Exception:
        return ""


def _judge_quality(query: str, contexts: list[str], answer: str) -> dict | None:
    try:
        from app.services import llm
        from app.services.rag_judge import parse_judge_json

        system = "你是 RAG 答案质量裁判，只输出 JSON。"
        prompt = (
            "请对回答按 0-5 打分：faithfulness（是否忠于片段）、relevance（是否回答问题）、"
            "completeness（是否覆盖关键信息）、expression（表述清晰度）、logic（逻辑性）。\n"
            "只输出 JSON：{\"faithfulness\":0,\"relevance\":0,\"completeness\":0,"
            "\"expression\":0,\"logic\":0,\"reason\":\"...\"}\n\n"
            f"问题：{query}\n片段：\n"
            + ("\n---\n".join(f"[{i+1}] {c[:800]}" for i, c in enumerate(contexts[:5])) or "（无）")
            + f"\n回答：{answer[:2000] or '（空回答）'}"
        )
        text = llm.invoke_text(system, prompt, temperature=0.0, timeout=120).strip()
        return parse_judge_json(text)
    except Exception:
        return None


def _aggregate_answer(rows: list[dict]) -> dict:
    answers = [r.get("answer") for r in rows if r.get("answer")]
    if not answers:
        return {"cases": 0}
    scored = [a for a in answers if isinstance(a.get("keyword_hit"), (int, float))]
    judged = [a["judge"] for a in answers if isinstance(a.get("judge"), dict)]
    out = {
        "cases": len(answers),
        "keyword_hit": round(sum(a["keyword_hit"] for a in scored) / len(scored), 4) if scored else None,
    }
    for key in ("faithfulness", "relevance", "completeness", "expression", "logic"):
        vals = [j[key] for j in judged if isinstance(j.get(key), (int, float))]
        out[key] = round(sum(vals) / len(vals), 2) if vals else None
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
