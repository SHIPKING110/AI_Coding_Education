"""RAG 底座：系统级 Embedding + Chroma 持久化（集合按 embedding 指纹分片）+ 可选 Rerank。

设计要点（生产落地）：
- **Embedding 系统级**：单一向量集合不能混存不同 embedding 的向量（不同向量
  空间会跨教师串味、维度不同直接查询失败）。故集合名带 embedding 指纹
  `knowledge__{fingerprint}`，换模型即落新集合，旧集合可离线清理/重建。
- **Rerank 可选（两阶段检索）**：query → 向量过召回 top_k*5 → 若教师配了
  rerank 则重排取 top_k。rerank 独立超时 + 熔断 + 失败降级回向量序，
  未配置时完全等价于单层向量召回（行为与现状一致）。
- 兼容：未配置系统级 embedding 时回退全局 env（LLM_EMBED_MODEL 等），
  再回退本地 Qwen，保证既有部署不中断。
"""

from __future__ import annotations

import hashlib
import random
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

CHUNK_SIZE = 512
CHUNK_OVERLAP = 100
TOP_K_DEFAULT = 5
# rerank 过召回数：向量先粗排 N*5，rerank 再精排到 N
RERANK_OVERSAMPLE = 5
MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "Qwen3-Embedding-0.6B"
CHROMA_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma"
COLLECTION_BASE = "knowledge"
# 家长客服独立检索域：配置专属 Embedding 后落到独立集合，只索引家长可见文档；
# 未配置（或与系统 Embedding 指纹一致）时复用系统集合，行为与现状一致。
PARENT_COLLECTION_BASE = "parent_knowledge"
# 未配置 embedding（回退本地 Qwen）时的默认集合名，保持与历史数据兼容
DEFAULT_COLLECTION = COLLECTION_BASE

# rerank 熔断：连续失败达到阈值后临时短路，直接用向量序（避免每次查询都等超时）
_RERANK_FAIL_STREAK = 0
_RERANK_FAIL_LOCK = threading.Lock()
_RERANK_CIRCUIT_THRESHOLD = 3
_RERANK_CIRCUIT_UNTIL = 0.0
RERANK_TIMEOUT_S = 1.5

# 批量上传可能同时触发多篇索引；限制并发，避免 Embedding 请求瞬间打爆网关限流
INDEX_CONCURRENCY = 2
_INDEX_SEMAPHORE = threading.Semaphore(INDEX_CONCURRENCY)

# 后台线程/测试可替换的 Session 工厂（测试需指向隔离库，避免读取开发库的模型配置）
_SESSION_FACTORY = None


def _session_factory():
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        from app.core.database import SessionLocal

        _SESSION_FACTORY = SessionLocal
    return _SESSION_FACTORY


@lru_cache(maxsize=1)
def get_embed_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(str(MODEL_DIR))


def local_embedding_ready() -> bool:
    """本地 Qwen 模型是否真的可用：只判断目录存在会把空目录当成可用，导致首次检索卡在加载。"""
    if not MODEL_DIR.is_dir():
        return False
    if not (MODEL_DIR / "config.json").exists():
        return False
    return any(MODEL_DIR.glob("*.safetensors")) or any(MODEL_DIR.glob("*.bin"))


def _char_windows(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按字符定长开窗切分（超长块的兜底层）。中文 1 字≈1 token，取保守窗口。"""
    text = (text or "").strip()
    if not text:
        return []
    win = max(200, int(chunk_size * 1.75))
    ov = max(40, int(overlap * 1.75))
    step = max(1, win - ov)
    return [text[i : i + win].strip() for i in range(0, len(text), step) if text[i : i + win].strip()]


# Markdown 标题（#/##/###…，含可选前导 # 空格）
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")


def _split_blocks(text: str) -> list[str]:
    """按空行/标题切成语义块，保留 Markdown 结构标记。"""
    blocks: list[str] = []
    buf: list[str] = []
    for line in (text or "").splitlines():
        # 遇到标题：先收束当前块，再以标题开新块（标题与正文不拆散）
        if _HEADING_RE.match(line):
            if buf:
                cur = "\n".join(buf).strip()
                if cur:
                    blocks.append(cur)
            buf = [line]
        elif not line.strip():
            if buf:
                cur = "\n".join(buf).strip()
                if cur:
                    blocks.append(cur)
            buf = []
        else:
            buf.append(line)
    if buf:
        cur = "\n".join(buf).strip()
        if cur:
            blocks.append(cur)
    return blocks


def chunk_semantic(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """语义切片：Markdown 标题为硬边界，章节正文按窗口聚合，超长块定长开窗 + 重叠。

    - 标题开启新块 → 每个章节至少独立成块，检索命中时能带上标题语境；
    - 章节内按段落聚合、不超窗口 → 不切断语义；
    - 超大单块退化为带重叠的定长窗口，避免超长 embedding。
    """
    blocks = _split_blocks(text)
    if not blocks:
        return _char_windows(text, chunk_size, overlap)
    win = max(200, int(chunk_size * 1.75))
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0

    def flush():
        nonlocal cur, cur_len
        if cur:
            joined = "\n\n".join(cur).strip()
            if joined:
                chunks.append(joined)
        cur, cur_len = [], 0

    for b in blocks:
        if _HEADING_RE.match(b):
            flush()  # 标题 = 硬边界，先收束上一章节
            cur, cur_len = [b], len(b)
            continue
        if len(b) > win:
            flush()
            chunks.extend(_char_windows(b, chunk_size, overlap))
            continue
        if cur_len + len(b) > win and cur:
            flush()
        cur.append(b)
        cur_len += len(b) + 2
    flush()
    return [c for c in chunks if c]


def _build_parent_texts(chunks: list[str], parent_size: int) -> list[str | None]:
    """父子切分：把连续子块聚合成父块作为 LLM 上下文。

    父块只用于“命中后回填上下文”，不参与向量化；parent_size<=0 时关闭。
    """
    if parent_size <= 0 or not chunks:
        return [None] * len(chunks)
    out: list[str | None] = []
    buf: list[str] = []
    buf_len = 0
    for c in chunks:
        if buf and buf_len + len(c) > parent_size:
            parent = "\n\n".join(buf).strip()
            out.extend([parent] * len(buf))
            buf, buf_len = [], 0
        buf.append(c)
        buf_len += len(c) + 2
    if buf:
        parent = "\n\n".join(buf).strip()
        out.extend([parent] * len(buf))
    return out


_embed_resolved_cache: tuple[float, object] = (0.0, None)
_EMBED_TTL_S = 30.0
_EMBED_CACHE_LOCK = threading.Lock()


def _resolve_embedding(force: bool = False):
    """解析当前生效的系统级 embedding（短 TTL 缓存，避免每次查询都开连接）。

    配置变更后最多 30s 生效；管理员可等待或重启立即生效。
    """
    global _embed_resolved_cache
    now = time.time()
    if not force and now - _embed_resolved_cache[0] < _EMBED_TTL_S:
        return _embed_resolved_cache[1]
    resolved = None
    try:
        from app.crud import retrieval_config as crud

        db = _session_factory()()
        try:
            resolved = crud.resolve_embedding(db)
        finally:
            db.close()
    except Exception:
        resolved = None
    with _EMBED_CACHE_LOCK:
        _embed_resolved_cache = (now, resolved)
    return resolved


def invalidate_embedding_cache() -> None:
    """系统级 embedding 配置变更后调用：立即生效，无需等 TTL。"""
    global _embed_resolved_cache
    with _EMBED_CACHE_LOCK:
        _embed_resolved_cache = (0.0, None)


_parent_embed_resolved_cache: tuple[float, object] = (0.0, None)


def _resolve_parent_embedding(force: bool = False):
    """解析家长客服专属 embedding；未配置返回 None（由调用方回退系统级）。"""
    global _parent_embed_resolved_cache
    now = time.time()
    if not force and now - _parent_embed_resolved_cache[0] < _EMBED_TTL_S:
        return _parent_embed_resolved_cache[1]
    resolved = None
    try:
        from app.crud import retrieval_config as crud

        db = _session_factory()()
        try:
            resolved = crud.resolve_parent_embedding(db)
        finally:
            db.close()
    except Exception:
        resolved = None
    with _EMBED_CACHE_LOCK:
        _parent_embed_resolved_cache = (now, resolved)
    return resolved


def _effective_parent_embedding(force: bool = False):
    """家长域实际使用的 embedding：专属配置优先，未配置回退系统级。"""
    return _resolve_parent_embedding(force) or _resolve_embedding(force)


def invalidate_parent_embedding_cache() -> None:
    """家长客服 embedding 配置变更后调用：立即生效。"""
    global _parent_embed_resolved_cache
    with _EMBED_CACHE_LOCK:
        _parent_embed_resolved_cache = (0.0, None)


def _parent_uses_dedicated_collection() -> bool:
    """家长专属 Embedding 是否真正独立（配置了且与系统指纹不同）。"""
    parent = _resolve_parent_embedding()
    if parent is None:
        return False
    system = _resolve_embedding()
    if system is not None and parent.fingerprint() == system.fingerprint():
        return False
    return True


def _collection_name(parent: bool = False) -> str:
    """集合名按 embedding 指纹分片：不同向量空间绝不混存（修跨教师串味/维度错）。"""
    if parent:
        parent_resolved = _resolve_parent_embedding()
        if parent_resolved is None:
            return _collection_name(False)
        system = _resolve_embedding()
        if system is not None and parent_resolved.fingerprint() == system.fingerprint():
            return _collection_name(False)
        return f"{PARENT_COLLECTION_BASE}__{parent_resolved.fingerprint()}"
    resolved = _resolve_embedding()
    if resolved is None:
        return DEFAULT_COLLECTION
    return f"{COLLECTION_BASE}__{resolved.fingerprint()}"


def get_collection(parent: bool = False):
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(_collection_name(parent=parent))


def active_collection_name(parent: bool = False) -> str:
    """当前生效集合名（embedding 指纹分片）。"""
    return _collection_name(parent=parent)


def collection_stats() -> dict:
    """当前集合与历史集合的文档/分片计数，供后台运维展示。"""
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    active_system = _collection_name(False)
    active_parent = _collection_name(True)
    items: list[dict] = []
    for col in client.list_collections():
        if not (col.name.startswith(COLLECTION_BASE) or col.name.startswith(PARENT_COLLECTION_BASE)):
            continue
        try:
            count = int(col.count())
        except Exception:
            count = 0
        items.append({
            "name": col.name,
            "count": count,
            "active": col.name in {active_system, active_parent},
            "domain": "parent" if col.name.startswith(PARENT_COLLECTION_BASE) else "teacher",
        })
    return {"active": active_system, "parent_active": active_parent, "collections": items}


def get_document_chunks(doc_id: uuid.UUID | str, *, limit: int = 500) -> list[dict]:
    """读取某文档的分片（当前集合），供后台详情/检索反查。"""
    from app.services import pricing

    try:
        col = get_collection()
        got = col.get(where={"doc_id": str(doc_id)}, include=["documents", "metadatas"])
    except Exception:
        return []
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []
    ids = got.get("ids") or []
    out: list[dict] = []
    for i, (vid, text, meta) in enumerate(zip(ids, docs, metas)):
        if i >= limit:
            break
        meta = meta or {}
        text = text or ""
        parent_text = meta.get("parent_text") or ""
        out.append({
            "id": vid,
            "chunk_no": meta.get("chunk_no"),
            "title": meta.get("title", ""),
            "chars": len(text),
            "tokens_est": pricing.estimate_tokens(text),
            "preview": text[:600],
            "has_parent": bool(parent_text),
            "parent_chars": len(parent_text),
        })
    out.sort(key=lambda x: (x.get("chunk_no") is None, x.get("chunk_no") or 0))
    return out


def document_storage_profile(doc, *, parent: bool = False) -> dict:
    """单篇文档的索引/向量化存储档案（后台可观测）。

    优先返回索引时落库的快照（extra.index_profile），并实时读取当前集合的分块与
    向量维度用于校验；历史文档没有快照时退化为按当前配置实时统计（live=True）。
    """
    from app.services import pricing, rag_settings

    try:
        cfg = rag_settings.get_config()
    except Exception:
        cfg = {}
    docs: list[str] = []
    vector_dim: int | None = None
    vector_sample: list[float] = []
    try:
        col = get_collection(parent=parent)
        got = col.get(where={"doc_id": str(doc.id)}, include=["documents"], limit=500)
        docs = [d or "" for d in (got.get("documents") or [])]
        # 只取首块向量用于维度/样例展示，避免大文档把全部向量读进内存
        one = col.get(where={"doc_id": str(doc.id)}, include=["embeddings"], limit=1)
        embs = one.get("embeddings")
        if embs is not None and len(embs):
            try:
                vector_dim = len(embs[0])
                vector_sample = [round(float(x), 6) for x in list(embs[0])[:8]]
            except Exception:
                vector_dim = None
                vector_sample = []
    except Exception:
        docs = []
    lengths = [len(d) for d in docs]
    total_chars = sum(lengths)
    resolved = _effective_parent_embedding() if parent else _resolve_embedding()
    if resolved is None:
        embedding = {
            "provider": "local",
            "model": "local-qwen",
            "base_url": "",
            "fingerprint": "local-qwen",
        }
    else:
        embedding = {
            "provider": resolved.provider,
            "model": resolved.model,
            "base_url": resolved.base_url or "",
            "fingerprint": resolved.fingerprint(),
        }
    extra = dict(doc.extra or {})
    snapshot = extra.get("parent_index_profile" if parent else "index_profile")
    dedicated = bool(_parent_dedicated_fingerprint()) if parent else None
    try:
        file_size = Path(doc.file_path).stat().st_size if doc.file_path else 0
    except OSError:
        file_size = 0
    return {
        "collection": _collection_name(parent=parent),
        "parent_dedicated": dedicated,
        "embedding": embedding,
        "vector_dim": vector_dim,
        "vector_sample": vector_sample,
        "chunk_count": int(doc.chunk_count or len(docs)),
        "char_count": total_chars,
        "tokens_est": pricing.estimate_tokens_many(docs) if docs else 0,
        "chunk_chars": {
            "min": min(lengths) if lengths else 0,
            "max": max(lengths) if lengths else 0,
            "avg": round(total_chars / len(lengths), 1) if lengths else 0,
        },
        "chunk_config": {
            "chunk_size": cfg.get("chunk_size", CHUNK_SIZE),
            "chunk_overlap": cfg.get("chunk_overlap", CHUNK_OVERLAP),
            "parent_chunk_size": cfg.get("parent_chunk_size", 0),
        },
        "source": {
            "file_name": doc.file_name or "",
            "file_size": file_size,
            "file_hash": extra.get("source_hash") or extra.get("indexed_hash") or "",
        },
        "indexed_at": (snapshot or {}).get("indexed_at")
        or (doc.updated_at.isoformat() if doc.updated_at else None),
        "profile_snapshot": snapshot,
        "live": snapshot is None,
    }


def _store_index_profile(doc_id, *, parent: bool = False) -> None:
    """索引完成后把本次实际使用的分块/embedding/集合参数冻结进 doc.extra。"""
    try:
        from datetime import UTC, datetime

        from app.crud import knowledge as _kb

        db = _session_factory()()
        try:
            doc = _kb.get_document_any(db, doc_id=doc_id)
            if doc is None:
                return
            profile = document_storage_profile(doc, parent=parent)
            profile["indexed_at"] = datetime.now(UTC).isoformat()
            profile["live"] = False
            profile.pop("profile_snapshot", None)
            extra = dict(doc.extra or {})
            key = "parent_index_profile" if parent else "index_profile"
            extra[key] = profile
            if not parent and profile["source"]["file_hash"]:
                extra["source_hash"] = profile["source"]["file_hash"]
            doc.extra = extra
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


_embed_client_cache: dict = {}


def _api_embeddings(resolved):
    from langchain_openai import OpenAIEmbeddings

    key = (resolved.base_url or "", resolved.api_key or "", resolved.model or "")
    client = _embed_client_cache.get(key)
    if client is None:
        client = OpenAIEmbeddings(
            model=resolved.model,
            api_key=resolved.api_key,
            base_url=resolved.base_url or None,
            timeout=60,
            max_retries=1,
            # 非 OpenAI 厂商不支持按模型查上下文长度，关掉该探测
            check_embedding_ctx_length=False,
        )
        _embed_client_cache[key] = client
    return client


# —— 向量化并发/批量/退避（应对 API 限流与各家 batch size 限制） ——
# EMBED_BATCH 只是「首轮尝试」的上限；若厂商拒绝（batch size is invalid），
# _embed_batch_remote 会自适应二分拆批，故这里无需按厂商写死。
EMBED_BATCH = 16
# 单批字符总量上限：多数 embedding 接口对单请求总 token 也有上限，超了同样报 invalid
EMBED_MAX_CHARS_PER_BATCH = 8000
EMBED_CONCURRENCY = 4
EMBED_MAX_RETRY = 3
EMBED_BACKOFF_BASE = 0.8


def _is_retryable(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("429", "rate", "timeout", "timed out", "overload", "500", "502", "503", "504", "connection", "temporar"))


def _is_batch_size_error(exc: Exception) -> bool:
    """识别「单批条数/总长度超限」类参数错误（各厂商限制不同，需自适应拆批）。

    例：通义/百炼 InternalError.Algo.InvalidParameter: Value error, batch size is invalid
        部分 embedding 接口单批最多 N 条，或单批总字符/token 超上限。
    """
    s = str(exc).lower()
    batchish = ("batch" in s) or ("invalidparameter" in s) or ("invalid parameter" in s) or ("invalid_parameter" in s)
    sizeish = ("batch size" in s) or ("too large" in s) or ("too long" in s) or ("exceed" in s) \
        or ("invalid" in s) or ("batch" in s and ("size" in s or "number" in s or "count" in s))
    return batchish and sizeish


def _embed_batch_remote(batch: list[str], client, resolved=None, _depth: int = 0) -> list[list[float]]:
    """一批文本的 embedding。

    - 批大小/参数非法 → **二分拆批重试**（自适应各厂商限制，不写死条数）；
    - 限流/超时 → 指数退避重试；
    - 单条仍失败 → 上抛（交由上层 LLMConfigError 友好报错）。
    - 成功/失败都记一笔 usage（估算型：OpenAIEmbeddings 不透出网关 usage）。
    """
    from app.services import usage_meter

    delay = EMBED_BACKOFF_BASE
    last: Exception | None = None
    for attempt in range(EMBED_MAX_RETRY):
        t0 = time.monotonic()
        try:
            vecs = client.embed_documents(batch)
            usage_meter.record_embedding(
                resolved,
                texts=list(batch),
                latency_ms=int((time.monotonic() - t0) * 1000),
                status="ok",
                attempt=attempt + 1,
            )
            return [[float(x) for x in v] for v in vecs]
        except Exception as e:  # noqa: BLE001
            last = e
            # 批过大：二分后分别重试（递归），直到能通过
            if _is_batch_size_error(e) and len(batch) > 1 and _depth < 8:
                mid = len(batch) // 2
                return (
                    _embed_batch_remote(batch[:mid], client, resolved, _depth + 1)
                    + _embed_batch_remote(batch[mid:], client, resolved, _depth + 1)
                )
            if attempt == EMBED_MAX_RETRY - 1 or not _is_retryable(e):
                usage_meter.record_embedding(
                    resolved,
                    texts=list(batch),
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    status="error",
                    attempt=attempt + 1,
                )
                raise
            # 指数退避 + 抖动，避免并发重试打爆限流
            time.sleep(delay * (2 ** attempt) * (0.5 + random.random()))
    raise last  # type: ignore[misc]


def _make_batches(texts: list[str]) -> list[list[str]]:
    """按「条数上限 + 单批字符总量」切批，避免触发厂商的 batch size / 长度限制。"""
    batches: list[list[str]] = []
    cur: list[str] = []
    cur_chars = 0
    for t in texts:
        n = len(t or "")
        if cur and (len(cur) >= EMBED_BATCH or cur_chars + n > EMBED_MAX_CHARS_PER_BATCH):
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(t)
        cur_chars += n
    if cur:
        batches.append(cur)
    return batches


def _embed_remote_concurrent(texts: list[str], resolved) -> list[list[float]]:
    """分批 + 多线程并发 embedding（限流友好；批大小由 _make_batches 与自适应拆批兜底）。"""
    batches = _make_batches(list(texts))
    client = _api_embeddings(resolved)
    out: list[list[float]] = []
    if len(batches) == 1:
        return _embed_batch_remote(batches[0], client, resolved)
    with ThreadPoolExecutor(max_workers=EMBED_CONCURRENCY) as ex:
        for part in ex.map(lambda b: _embed_batch_remote(b, client, resolved), batches):
            out.extend(part)
    return out


def _text_key(text: str) -> str:
    """分片内容哈希：作为 embedding 缓存的 key（内容不变→向量不变）。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# —— 检索监控（运行时指标，内存计数；用于发现效果/延迟滑坡） ——
_metrics_lock = threading.Lock()
_metrics: dict[str, float] = {
    "queries": 0, "hits": 0, "zero_results": 0,
    "vector_ok": 0, "vector_fail": 0,
    "keyword_fallback": 0,
    "rerank_ok": 0, "rerank_fail": 0,
    "latency_ms_sum": 0.0,
}


def _bump(key: str, n: float = 1) -> None:
    with _metrics_lock:
        _metrics[key] = _metrics.get(key, 0) + n


def get_metrics_snapshot() -> dict:
    """检索指标快照：查询量/命中率/零结果率/降级次数/平均时延。

    零结果率与平均时延是效果滑坡的先行指标（召回变差→零结果上升）。
    """
    with _metrics_lock:
        m = dict(_metrics)
    q = m["queries"] or 0
    return {
        **m,
        "hit_rate": round(m["hits"] / q, 4) if q else None,
        "zero_result_rate": round(m["zero_results"] / q, 4) if q else None,
        "avg_latency_ms": round(m["latency_ms_sum"] / q, 2) if q else None,
    }


def _file_hash(path: str) -> str | None:
    """源文件内容哈希：用于增量同步判断文档是否变更。"""
    if not path or not Path(path).exists():
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _store_index_hash(doc_id, file_hash: str | None) -> None:
    """把本次索引对应的源文件哈希写入文档 extra，供增量比对。"""
    if not file_hash:
        return
    try:
        from app.crud import knowledge as _kb

        db = _session_factory()()
        try:
            doc = _kb.get_document_any(db, doc_id=doc_id)
            if doc is not None:
                extra = dict(doc.extra or {})
                extra["indexed_hash"] = file_hash
                doc.extra = extra
                db.commit()
        finally:
            db.close()
    except Exception:
        pass


def sync_changed_documents(*, limit: int = 50) -> dict:
    """增量同步：检测新增/变更文档并触发重新索引（未变化的跳过，省Token）。

    - 变更判定：源文件内容哈希 != 已索引哈希（或从未索引）；
    - 源文件丢失：标记失败并清理其残留向量（僵尸）；
    - 正在索引中的跳过，避免并发重复处理。
    """
    from app.crud import knowledge as _kb

    db = _session_factory()()
    stats = {"scanned": 0, "reindexed": 0, "missing_source": 0, "skipped_indexing": 0}
    try:
        docs = _kb.list_all_documents(db)
        stats["scanned"] = len(docs)
        for doc in docs[:limit]:
            if doc.status == "indexing":
                stats["skipped_indexing"] += 1
                continue
            fh = _file_hash(doc.file_path)
            if fh is None:
                # 源文件已丢失/被外部删除：清理向量 + 标记失败，防僵尸污染
                stats["missing_source"] += 1
                delete_document_vectors(doc.id)
                try:
                    _kb.mark_failed(db, doc, "源文件已丢失，无法重新索引")
                except Exception:
                    pass
                continue
            prev = (doc.extra or {}).get("indexed_hash")
            if prev == fh and doc.status == "ready":
                continue  # 未变更，跳过（省 Token）
            stats["reindexed"] += 1
            index_in_background(
                doc_id=doc.id, owner_id=doc.owner_id, title=doc.title,
                file_path=doc.file_path, file_name=doc.file_name or "",
                mark_done=lambda d, n, e: _sync_mark_done(d, n, e, fh),
                mark_progress=None,
            )
    finally:
        db.close()
    return stats


def _sync_mark_done(doc_id, chunk_count: int, error: str | None, file_hash: str) -> None:
    """增量同步专用的落状态回调（写状态 + 记录已索引哈希）。"""
    from app.crud import knowledge as _kb

    db = _session_factory()()
    try:
        _kb.mark_indexed(db, doc_id=doc_id, chunk_count=chunk_count, error=error)
        if error is None:
            doc = _kb.get_document_any(db, doc_id=doc_id)
            if doc is not None:
                extra = dict(doc.extra or {})
                extra["indexed_hash"] = file_hash
                doc.extra = extra
                db.commit()
    finally:
        db.close()


class _EmbedCache:
    """分片向量持久化缓存（本地 npz）。

    用途：文档更新/重建索引时，未变化的分片直接命中缓存，不重复调用 embedding
    API、不重复消耗 Token。key = 分片内容哈希；按 embedding 指纹分目录，
    换模型自动隔离，不会串用不同向量空间的缓存。

    注：容器内 pyarrow/pandas 不可用，故用等效的 numpy .npz（同样持久化、
    零额外依赖），后续若引入 pyarrow 可平滑换成 parquet。
    """

    def __init__(self, path: Path):
        self.path = path
        self._d: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._load()

    def _load(self) -> None:
        import numpy as np

        try:
            if self.path.exists():
                with np.load(self.path, allow_pickle=False) as z:
                    keys = z["keys"]
                    vecs = z["vecs"]
                self._d = {str(k): vecs[i].tolist() for i, k in enumerate(keys)}
        except Exception:
            self._d = {}  # 缓存损坏不致命，当空缓存重建

    def get(self, key: str) -> list[float] | None:
        with self._lock:
            return self._d.get(key)

    def put_many(self, items: dict[str, list[float]]) -> None:
        with self._lock:
            self._d.update(items)
            self._dirty = True

    def save(self) -> None:
        import numpy as np

        with self._lock:
            if not self._dirty or not self._d:
                return
            keys = list(self._d.keys())
            dim = len(self._d[keys[0]])
            # 维度不一致（理论上不会，指纹已隔离）→ 放弃落盘，下次重建
            if any(len(v) != dim for v in self._d.values()):
                return
            arr = np.asarray([self._d[k] for k in keys], dtype=np.float32)
            karr = np.asarray(keys, dtype=str)
            self._dirty = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp.npz")
            np.savez(tmp, keys=karr, vecs=arr)
            tmp.replace(self.path)  # 原子替换，避免半写文件
        except Exception:
            pass  # 缓存落盘失败不影响主流程

    def __len__(self) -> int:
        with self._lock:
            return len(self._d)


_embed_caches: dict[str, _EmbedCache] = {}
_embed_cache_lock = threading.Lock()
EMBED_CACHE_DIR = CHROMA_DIR.parent / "embed_cache"


def _get_embed_cache(fingerprint: str) -> _EmbedCache:
    with _embed_cache_lock:
        c = _embed_caches.get(fingerprint)
        if c is None:
            c = _EmbedCache(EMBED_CACHE_DIR / fingerprint / "cache.npz")
            _embed_caches[fingerprint] = c
        return c


def embed_texts(texts: list[str], resolved=None, *, parent: bool = False) -> list[list[float]]:
    """向量化（带持久化缓存 + 并发/批量/退避）。

    - **持久化缓存**：按 (embedding 指纹, 分片内容哈希) 缓存向量到本地 npz，
      文档更新时未变化的分片直接命中缓存，避免重复调用 API、重复消耗 Token。
    - **并发/批量/退避**：分批 + 多线程，失败指数退避重试，应对限流。
    - 回退链：家长专属 Embedding / 系统级 Embedding（remote/local）→ 全局 env → 本地 Qwen。
    """

    if resolved is None:
        resolved = _effective_parent_embedding() if parent else _resolve_embedding()

    # 本地 provider（sentence-transformers / Qwen）自带批处理，无需远程缓存与并发
    if resolved is not None and resolved.provider == "local" and resolved.model_path:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(resolved.model_path)
        embs = model.encode(texts, convert_to_numpy=False)
        if hasattr(embs, "tolist"):
            embs = embs.tolist()
        return [[float(x) for x in e] for e in embs]

    fp = resolved.fingerprint() if resolved is not None else "local-qwen"
    cache = _get_embed_cache(fp)

    # 1) 先查缓存（未命中的才需调用 API）
    keys = [_text_key(t) for t in texts]
    vecs_by_key: dict[str, list[float]] = {}
    misses: list[str] = []
    for t, k in zip(texts, keys):
        hit = cache.get(k)
        if hit is not None:
            vecs_by_key[k] = hit
        else:
            misses.append(t)
    # 去重后只嵌入未命中且唯一的文本
    unique_miss = list(dict.fromkeys(misses))

    if unique_miss:
        new_vecs = _embed_missing(unique_miss, resolved)
        for t, v in zip(unique_miss, new_vecs):
            vecs_by_key[_text_key(t)] = v
        cache.put_many({_text_key(t): v for t, v in zip(unique_miss, new_vecs)})
        # 索引场景（批量）才落盘；查询场景(单条)留在内存，避免每次查询都写盘
        if len(unique_miss) >= 2:
            cache.save()

    return [vecs_by_key[k] for k in keys]


def _embed_missing(texts: list[str], resolved) -> list[list[float]]:
    """真正调用模型向量化（remote 走并发+退避；无配置回退本地 Qwen）。"""
    from app.services.llm import LLMConfigError

    if resolved is not None and resolved.provider == "local":
        if resolved.model_path:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(resolved.model_path)
            embs = model.encode(texts, convert_to_numpy=False)
            if hasattr(embs, "tolist"):
                embs = embs.tolist()
            return [[float(x) for x in e] for e in embs]
        raise LLMConfigError("本地 Embedding 模型路径未配置")
    if resolved is not None:
        try:
            return _embed_remote_concurrent(list(texts), resolved)
        except LLMConfigError:
            raise
        except Exception as e:
            from app.services.llm import friendly_llm_error

            raise LLMConfigError(friendly_llm_error(e)) from e
    if not local_embedding_ready():
        raise LLMConfigError("未配置 Embedding 模型：请到 设置 → 模型配置 配置系统级 Embedding 后再试")
    model = get_embed_model()
    embs = model.encode(texts, convert_to_numpy=False)
    if hasattr(embs, "tolist"):
        embs = embs.tolist()
    return [[float(x) for x in e] for e in embs]


# —— 格式清洗（去页眉/页脚/水印/冗余空白，避免污染分片语义） ——
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\ufeff]")
_MULTI_BLANK = re.compile(r"\n{3,}")
_WATERMARK_HINTS = ("水印", "仅供", "版权所有", "请勿外传", "保密", "样书", "试读")
_PAGE_NOISE_RE = re.compile(r"^[\s\-—_=·\.]{0,6}\s*(第\s*\d+\s*[页頁]|page\s*\d+|-\s*\d+\s*-)\s*[\s\-—_=·\.]{0,6}$", re.IGNORECASE)


def _norm_text(text: str) -> str:
    """通用规整：去零宽字符、行尾空白、压缩 3+ 空行。"""
    t = _ZERO_WIDTH.sub("", text or "")
    t = "\n".join(line.rstrip() for line in t.splitlines())
    return _MULTI_BLANK.sub("\n\n", t).strip()


def _detect_page_furniture(pages: list[str]) -> set[str]:
    """检测跨页重复出现的页眉/页脚/水印行（出现于 >=40% 页面的首/尾行）。"""
    if len(pages) < 3:  # 页数太少，重复可能是正文，不做处理
        return set()
    head: dict[str, int] = {}
    foot: dict[str, int] = {}
    for page in pages:
        lines = [ln.strip() for ln in (page or "").splitlines() if ln.strip()]
        if not lines:
            continue
        head[lines[0]] = head.get(lines[0], 0) + 1
        foot[lines[-1]] = foot.get(lines[-1], 0) + 1
    threshold = max(3, int(len(pages) * 0.5))
    # 只剔除「短行」：长句更可能是正文而非页眉页脚，避免误删真实内容
    noise = {ln for ln, c in head.items() if c >= threshold and len(ln) <= 40}
    noise |= {ln for ln, c in foot.items() if c >= threshold and len(ln) <= 40}
    # 水印提示词：跨页反复出现即判为水印
    for page in pages:
        for ln in {x.strip() for x in (page or "").splitlines() if x.strip()}:
            if len(ln) <= 80 and any(h in ln for h in _WATERMARK_HINTS):
                noise.add(ln)
    return noise


def _clean_pages(pages: list[str]) -> str:
    """按页清洗：剔除页眉/页脚/水印/页码行，再规整空白。"""
    noise = _detect_page_furniture(pages)
    cleaned_pages: list[str] = []
    for page in pages:
        kept = [
            ln for ln in (page or "").splitlines()
            if ln.strip() not in noise and not _PAGE_NOISE_RE.match(ln.strip())
        ]
        cleaned_pages.append("\n".join(kept))
    return _norm_text("\n\n".join(cleaned_pages))


def _clean_plain(text: str) -> str:
    """纯文本/md/docx 清洗：仅去页码行与规整空白（保留 Markdown 结构，不删重复正文）。"""
    kept = [ln for ln in (text or "").splitlines() if not _PAGE_NOISE_RE.match(ln.strip())]
    return _norm_text("\n".join(kept))


def extract_text(file_path: str, file_name: str = "") -> str:
    """解析 txt/md/pdf/docx 为纯文本（自动清洗页眉页脚/水印/冗余空白）。"""
    suffix = Path(file_name or file_path).suffix.lower()
    if suffix in (".txt", ".md", ".markdown"):
        return _clean_plain(Path(file_path).read_text(encoding="utf-8", errors="ignore"))
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("未安装 pypdf，请先执行 uv pip install pypdf")
        reader = PdfReader(file_path)
        pages = [(p.extract_text() or "") for p in reader.pages]
        return _clean_pages(pages)
    if suffix in (".docx",):
        try:
            import docx
        except ImportError:
            raise RuntimeError("未安装 python-docx，请先执行 uv pip install python-docx")
        return _clean_plain("\n".join(p.text for p in docx.Document(file_path).paragraphs))
    raise ValueError(f"暂不支持的文件类型：{suffix or '未知'}（支持 txt/md/pdf/docx）")


def index_document(
    *, doc_id: uuid.UUID, owner_id: uuid.UUID, title: str, text: str,
    on_progress=None, parent: bool = False,
) -> int:
    """切块 → 向量化 → 写入 Chroma（当前 embedding 分片集合），返回 chunk 数。

    采用语义切片（标题/段落感知 + 重叠）；向量化走 embed_texts 的持久化缓存，
    文档更新时未变化的分片命中缓存、不重复消耗 Token。
    parent=True 时写入家长客服独立集合，并使用家长专属 Embedding（未配置回退系统级）。
    """
    try:
        from app.services import rag_settings

        cfg = rag_settings.get_config()
        chunk_size = int(cfg.get("chunk_size", CHUNK_SIZE))
        overlap = int(cfg.get("chunk_overlap", CHUNK_OVERLAP))
        parent_size = int(cfg.get("parent_chunk_size", 0) or 0)
    except Exception:
        chunk_size, overlap, parent_size = CHUNK_SIZE, CHUNK_OVERLAP, 0
    chunks = chunk_semantic(text, chunk_size, overlap)
    if on_progress is not None:
        on_progress("chunk", 40, f"切块完成，共 {len(chunks)} 块")
    if not chunks:
        return 0
    parent_texts = _build_parent_texts(chunks, parent_size)
    col = get_collection(parent=True) if parent else get_collection()
    delete_document_vectors(doc_id, parent=parent)
    if on_progress is not None:
        on_progress("embed", 65, "向量化中…")
    embs = embed_texts(chunks, parent=True) if parent else embed_texts(chunks)
    ids = [f"{doc_id}:{i}" for i in range(len(chunks))]
    metas = []
    for i in range(len(chunks)):
        meta = {"doc_id": str(doc_id), "owner_id": str(owner_id), "title": title, "chunk_no": i}
        if parent_texts[i]:
            meta["parent_text"] = parent_texts[i]
        metas.append(meta)
    col.upsert(ids=ids, embeddings=embs, documents=chunks, metadatas=metas)
    return len(chunks)


def delete_document_vectors(doc_id: uuid.UUID, *, parent: bool = False) -> None:
    """删除某文档的全部分片向量（当前 embedding 分片集合）。

    注：若换过 embedding 模型，历史分片在旧集合里，切换后不会自动清理
    （数据不串味，但残留可在运维层离线清理）。
    """
    try:
        col = get_collection(parent=True) if parent else get_collection()
    except Exception:
        return
    try:
        col.delete(where={"doc_id": str(doc_id)})
    except Exception:
        pass


_SMALLTALK_RE = re.compile(
    r"^(你好|您好|你们好|嗨|嗨嗨|hi+|hello+|hey+|在吗|在么|在不在|谢谢|谢谢你|感谢|多谢|"
    r"再见|拜拜|拜|辛苦了|辛苦|好的|好嘞|收到|明白|嗯|嗯嗯|哦|哦哦|哈哈|哈哈哈|呵呵|hi|ok+|okk?)[!！~～。.，,、\s]*$",
    re.IGNORECASE,
)


def needs_retrieval(text: str) -> bool:
    """寒暄/无实质内容不检索：省一次向量化 + 提速首字响应，由模型直接寒暄回复。"""
    t = (text or "").strip()
    if not t:
        return False
    if len(t) <= 12 and _SMALLTALK_RE.match(t):
        return False
    return True


def _rerank_circuit_open() -> bool:
    return time.time() < _RERANK_CIRCUIT_UNTIL


def _rerank_on_fail() -> None:
    global _RERANK_FAIL_STREAK, _RERANK_CIRCUIT_UNTIL
    try:
        from app.services import rag_settings

        cfg = rag_settings.get_config()
        threshold = int(cfg.get("rerank_circuit_threshold", _RERANK_CIRCUIT_THRESHOLD))
        cooldown = int(cfg.get("rerank_circuit_cooldown_s", 60))
    except Exception:
        threshold, cooldown = _RERANK_CIRCUIT_THRESHOLD, 60
    with _RERANK_FAIL_LOCK:
        _RERANK_FAIL_STREAK += 1
        if _RERANK_FAIL_STREAK >= threshold:
            _RERANK_CIRCUIT_UNTIL = time.time() + cooldown


def _rerank_on_success() -> None:
    global _RERANK_FAIL_STREAK, _RERANK_CIRCUIT_UNTIL
    with _RERANK_FAIL_LOCK:
        _RERANK_FAIL_STREAK = 0
        _RERANK_CIRCUIT_UNTIL = 0.0


def _rerank_url_candidates(base: str) -> list[str]:
    """生成候选 rerank 端点，按「最可能通」排序。

    阿里百炼的坑（实测 2026）：
    - 对话模型网关 `.../compatible-mode/v1` **不提供 rerank**（/rerank、/reranks 都 404）；
    - rerank 在 **`.../compatible-api/v1/reranks`**（compatible-**api** 且路径复数 /reranks）；
    - 或 DashScope 原生 `.../api/v1/services/rerank/text-rerank/text-rerank`。
    用户通常只填 compatible-mode 的 base，故这里自动做网关/路径变换，无需填两遍。
    其他厂商（硅基流动/智谱）用 /rerank，反之。
    """
    low = (base or "").lower()
    is_bailian = ("aliyuncs.com" in low) or ("dashscope" in low) or ("maas." in low)
    cands: list[str] = []
    if is_bailian:
        # compatible-mode → compatible-api 网关（rerank 真正所在）
        if "compatible-mode" in base:
            cands.append(base.replace("compatible-mode", "compatible-api") + "/reranks")
        if "compatible-api" in base:
            cands.append(base + "/reranks")
        # 用户可能已填对，原样再试
        cands.append(base + "/reranks")
        cands.append(base + "/rerank")
        # DashScope 原生兜底（host 根 + 固定服务路径）
        host = base.split("/compatible")[0].split("/api/v1")[0].rstrip("/")
        cands.append(host + "/api/v1/services/rerank/text-rerank/text-rerank")
    else:
        cands.append(base + "/rerank")
        cands.append(base + "/reranks")
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _parse_rerank_results(data: dict) -> list:
    """兼容三种 rerank 响应格式，统一取 results 列表。"""
    if not isinstance(data, dict):
        return []
    res = data.get("results") or data.get("data")  # OpenAI 兼容
    if res:
        return res
    out = data.get("output")  # DashScope 原生 {"output":{"results":[...]}}
    if isinstance(out, dict) and out.get("results"):
        return out["results"]
    return []


def rerank_documents(
    query: str,
    documents: list[str],
    resolved,
    *,
    owner_id=None,
    platform: bool = False,
) -> tuple[list[int], list[float]]:
    """调 rerank 模型，返回 (按相关度降序的原文下标, 对应相关度分数)。

    分数为 rerank 模型的 relevance_score（不同厂商量纲不同，仅用于排序/展示）。
    失败抛异常由上层降级。每次实际请求都记账（估算 tokens；教师自配个人成本 / 共享平台成本）。
    """
    if not documents:
        return [], []
    from app.services import usage_meter

    if resolved.provider == "local":
        # 本地 rerank 预留：走 sentence-transformers CrossEncoder（本机无费用，不记账）
        from sentence_transformers import CrossEncoder

        model = CrossEncoder(resolved.model_path)
        scores = [float(s) for s in model.predict([(query, d) for d in documents])]
        order = sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)
        return order, [scores[i] for i in order]
    import httpx

    base = (resolved.base_url or "").rstrip("/")
    payload = {
        "model": resolved.model,
        "query": query,
        "documents": documents,
        "top_n": len(documents),
        "return_documents": False,
    }
    headers = {"Authorization": f"Bearer {resolved.api_key}"}
    try:
        from app.services import rag_settings

        timeout_s = float(rag_settings.get_config().get("rerank_timeout_s", RERANK_TIMEOUT_S))
    except Exception:
        timeout_s = RERANK_TIMEOUT_S
    tried: list[str] = []
    last: Exception | None = None
    data: dict | None = None
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=timeout_s) as client:
            for url in _rerank_url_candidates(base):
                tried.append(url)
                try:
                    r = client.post(url, json=payload, headers=headers)
                    if r.status_code == 404:
                        last = Exception("404")
                        continue  # 路径/网关不对，试下一个
                    r.raise_for_status()
                    data = r.json()
                    break
                except httpx.HTTPStatusError as e:
                    if e.response is not None and e.response.status_code == 404:
                        last = e
                        continue
                    raise
            else:
                raise last or Exception("rerank 端点未找到，已尝试：" + "；".join(tried))
    except Exception:
        usage_meter.record_rerank(
            resolved,
            query=query,
            documents=list(documents),
            owner_id=owner_id,
            platform=platform,
            latency_ms=int((time.monotonic() - t0) * 1000),
            status="error",
        )
        raise
    usage_meter.record_rerank(
        resolved,
        query=query,
        documents=list(documents),
        owner_id=owner_id,
        platform=platform,
        latency_ms=int((time.monotonic() - t0) * 1000),
        status="ok",
    )
    results = _parse_rerank_results(data or {})
    order = [int(x.get("index", i)) for i, x in enumerate(results)]
    scores = [float(x.get("relevance_score", x.get("score", 0.0)) or 0.0) for x in results]
    # 兼容只返回 top_n 子集：补齐剩余，保持稳定（补位分数取该子集最低分之下）
    tail_score = min(scores) - 1e-6 if scores else 0.0
    for i in range(len(documents)):
        if i not in order:
            order.append(i)
            scores.append(tail_score)
    return order, scores


def _apply_rerank(query: str, cands: list[dict], db, owner_id, *, parent_mode: bool = False) -> tuple[list[dict], dict]:
    """对过召回候选做重排；任何失败/超时/熔断 → 原样返回向量序（静默降级）。
    返回 (重排后候选, 诊断)。诊断含是否真的重排成功、所用模型、候选数，
    供上层观测「向量检索与重排到底有没有生效」。重排命中的分片会带上 rerank_score。
    """
    meta = {"rerank": False, "rerank_model": None, "rerank_in": len(cands)}
    if len(cands) <= 1 or _rerank_circuit_open():
        return cands, meta
    try:
        from app.crud import retrieval_config as crud

        resolved = crud.resolve_parent_rerank(db) if parent_mode else crud.resolve_rerank(db, owner_id)
        if resolved is None:
            return cands, meta
        order, scores = rerank_documents(
            query,
            [c["text"] for c in cands],
            resolved,
            owner_id=None if parent_mode else owner_id,
            platform=parent_mode,
        )
        _rerank_on_success()
        ordered = [cands[i] for i in order if 0 <= i < len(cands)]
        # 把重排分附着到分片（与向量相似度区分：rerank_score 为交叉编码器得分）
        for i, c in enumerate(ordered):
            if i < len(scores):
                c["rerank_score"] = round(float(scores[i]), 4)
        meta.update({"rerank": True, "rerank_model": resolved.model, "rerank_out": len(ordered)})
        return ordered, meta
    except Exception:
        _rerank_on_fail()
        return cands, meta


_QUERY_SYNONYMS = {
    "退费": "退款 退费 退课",
    "请假": "请假 缺勤 缺席",
    "收费": "收费 费用 价格",
    "课时": "课时 课次 剩余课时",
    "排课": "排课 上课时间 课程安排",
}


def _rewrite_query(query: str, cfg: dict) -> tuple[str, bool]:
    """轻量 query 改写：仅在配置开启时做业务同义词扩展。"""
    q = _norm_text(query)
    if not cfg.get("query_rewrite_enabled"):
        return q, False
    extras: list[str] = []
    for k, v in _QUERY_SYNONYMS.items():
        if k in q:
            extras.extend(x for x in v.split() if x not in q)
    if not extras:
        return q, False
    return f"{q} {' '.join(dict.fromkeys(extras))}", True


def _rrf_merge(vector_cands: list[dict], keyword_cands: list[dict], *, k: int = 60) -> list[dict]:
    """RRF 融合向量与关键词候选：只看排名，不比较量纲。"""
    merged: dict[tuple[str, str], dict] = {}
    scores: dict[tuple[str, str], float] = {}
    for source, items in (("v", vector_cands), ("k", keyword_cands)):
        for rank, c in enumerate(items):
            key = (str(c.get("doc_id") or ""), (c.get("text") or "")[:120])
            if key not in merged:
                merged[key] = dict(c)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    out = []
    for key, c in merged.items():
        c["rrf_score"] = round(scores[key], 6)
        out.append(c)
    out.sort(key=lambda x: x.get("rrf_score", 0.0), reverse=True)
    return out


def _rrf_merge_many(hit_lists: list[list[dict]], *, k: int = 60) -> list[dict]:
    """多路子查询的 RRF 融合：每一路独立排名，按 1/(k+rank) 累加。"""
    merged: dict[tuple[str, str], dict] = {}
    scores: dict[tuple[str, str], float] = {}
    for items in hit_lists:
        for rank, c in enumerate(items):
            key = (str(c.get("doc_id") or ""), (c.get("text") or "")[:120])
            if key not in merged:
                merged[key] = dict(c)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    out = []
    for key, c in merged.items():
        c["rrf_score"] = round(scores[key], 6)
        out.append(c)
    out.sort(key=lambda x: x.get("rrf_score", 0.0), reverse=True)
    return out


_MULTI_INTENT_MARKERS = ("同时", "以及", "并且", "另外", "此外", "还有", "；", ";")
# 过短的片段（“真的假的”“那银牌呢”“我咋核实”）不是独立检索意图，
# 拆出来只会引入噪声；只把足够长的并列问句当作子查询。
_MULTI_SUBQUERY_MIN_LEN = 8
# auto 模式只在 baseline top1/top2 分差很小、排序本身不自信时才启用多意图，
# 避免把已经稳定命中的 FAQ 大文档从 top1 挤下去。
_MULTI_QUERY_MARGIN = 0.15
# 标题命中加成：query 与文档标题有实体词重叠时，给该文档一个轻量加分，
# 让“GESP 报考、退费流程、教师评估”这类具体问题优先落到对应制度文档，
# 而不是永远被大而全的 FAQ 压住。FAQ 本身不加成，避免自我强化。
_TITLE_MATCH_BOOST = 0.12
# FAQ 只在“几乎并列”时让位给具体制度文档；差距明显时仍保留 FAQ，
# 避免把本来命中 FAQ 的宽泛问题强行改成具体文档。
_FAQ_TIE_MARGIN = 0.01
_FAQ_TITLE_MARKERS = ("常见", "540", "FAQ", "问答", "百科")


def _split_multi_intent(query: str) -> list[str]:
    """轻量多意图拆分子查询：只对明显的并列/多问句生效，避免误伤单问句。

    不依赖额外 LLM 调用：命中并列词、分号或两个问号时，按句子边界拆开。
    返回长度 >=2 才表示值得多路检索。
    """
    q = _norm_text(query)
    if not q:
        return [q]
    question_marks = q.count("？") + q.count("?")
    if question_marks < 2 and not any(m in q for m in _MULTI_INTENT_MARKERS):
        return [q]
    parts = re.split(r"[。！？!?；;]|同时|另外|此外|并且|以及|还有", q)
    intent = next(
        (m for m in ("怎么判断", "如何判断", "怎么选", "如何选择", "怎么办", "怎么处理") if m in q),
        "",
    )
    cleaned: list[str] = []
    for part in parts:
        p = part.strip(" ，,、")
        # 去掉“文档里/资料中……分别怎么判断”这类元话语尾巴
        p = re.sub(r"^(?:文档里|文档中|资料里|资料中|其中)", "", p)
        p = re.sub(r"^(?:对)?(?:这|那)?(?:两|三|几)?个?(?:信号|环节|问题|方面)[，,、]?", "", p)
        p = re.sub(r"(?:分别|各自)?(?:怎么|如何|怎样)?(?:判断|处理|选择|看|算|做)?[？?]?$", "", p)
        p = p.strip(" ，,、")
        if len(p) >= _MULTI_SUBQUERY_MIN_LEN:
            if intent and intent not in p:
                p = f"{p}，{intent}"
            cleaned.append(p)
    cleaned = list(dict.fromkeys(cleaned))
    return cleaned if len(cleaned) >= 2 else [q]


def _retrieve_multi_query(
    query: str, *, subqueries: list[str], db, owner_id, collected_ids=None,
    top_k: int = 5, min_similarity=None, per_doc_cap: int = 2,
    rerank: bool = True, route_key: str | None = None,
    parent_mode: bool = False, diag: dict | None = None,
    hybrid_override: bool | None = None,
) -> list[dict]:
    """多意图：逐个子查询检索，再用 RRF 融合，最后做 per_doc_cap/top_k 截断。

    子查询多取一些候选（top_k*2）并允许同一文档出现 2 个分片，这样“一篇大文档
    分别覆盖多个子问题”时不会因为单文档只留一个分片而被挤掉；融合后按 doc_id
    汇总 RRF 分，多分片文档给一点覆盖加成。
    """
    sub_top_k = max(int(top_k) * 2, int(top_k) + 5)
    sub_cap = max(int(per_doc_cap), 2)
    hit_lists: list[list[dict]] = []
    subdiags: list[dict] = []
    for sub in subqueries:
        sub_diag: dict = {}
        try:
            hits = retrieve(
                sub, db=db, owner_id=owner_id, collected_ids=collected_ids,
                top_k=sub_top_k, min_similarity=min_similarity, per_doc_cap=sub_cap,
                rerank=rerank, diag=sub_diag, route_key=route_key,
                parent_mode=parent_mode, multi_query=False, record_trace=False,
                hybrid_override=hybrid_override,
            )
        except Exception:
            hits = []
        hit_lists.append(hits)
        subdiags.append(sub_diag)
    merged = _rrf_merge_many(hit_lists)

    # 文档级聚合：同一文档多个分片的 RRF 分累加，保留分最高的分片作为代表
    doc_scores: dict[str, float] = {}
    doc_best: dict[str, dict] = {}
    doc_chunks: dict[str, int] = {}
    for c in merged:
        doc_id = str(c.get("doc_id") or "")
        if not doc_id:
            continue
        score = float(c.get("rrf_score") or 0.0)
        doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + score
        doc_chunks[doc_id] = doc_chunks.get(doc_id, 0) + 1
        if doc_id not in doc_best or score > float(doc_best[doc_id].get("rrf_score") or 0.0):
            doc_best[doc_id] = c
    # 覆盖加成：同一文档覆盖多个分片（可能对应多个子问题）时略加分
    for doc_id, n in doc_chunks.items():
        if n > 1:
            doc_scores[doc_id] += 0.002 * (n - 1)
    ordered = sorted(doc_scores, key=lambda d: doc_scores[d], reverse=True)
    out: list[dict] = []
    for doc_id in ordered:
        c = dict(doc_best[doc_id])
        c["rrf_score"] = round(doc_scores[doc_id], 6)
        c["multi_chunk_count"] = doc_chunks[doc_id]
        out.append(c)
        if len(out) >= top_k:
            break
    if diag is not None:
        diag.update({
            "multi_query": True,
            "multi_query_sub": subqueries,
            "multi_query_sub_diag": subdiags,
            "vector": any(d.get("vector") for d in subdiags),
            "keyword": any(d.get("keyword") for d in subdiags),
            "hybrid": any(d.get("hybrid") for d in subdiags),
            "rerank": any(d.get("rerank") for d in subdiags),
            "final": len(out),
        })
        diag["retrieval_mode"] = _compute_retrieval_mode(diag)
    return out


def _compute_retrieval_mode(diag: dict) -> str:
    """把诊断压成单一检索模式标签，供 trace / 评测按架构切片。

    dense / dense_multi / hybrid / keyword_fallback / none / error：
    - hybrid 与 keyword_fallback 是两种不同契约：前者是并行召回+RRF，
      后者是向量不可用时的降级兜底，指标不能混在一起比较。
    """
    if diag.get("error"):
        return "error"
    if diag.get("hybrid") or diag.get("hybrid_enabled"):
        return "hybrid"
    if diag.get("vector"):
        return "dense_multi" if diag.get("multi_query") else "dense"
    if diag.get("keyword"):
        return "keyword_fallback"
    if diag.get("multi_query"):
        return "dense_multi"
    return "none"


def _hit_preview(hit: dict, *, limit: int = 500) -> dict:
    """trace 里只保留命中预览，避免重复存储整篇文档。"""
    return {
        "doc_id": str(hit.get("doc_id") or ""),
        "title": hit.get("title", ""),
        "similarity": hit.get("similarity"),
        "rerank_score": hit.get("rerank_score"),
        "rrf_score": hit.get("rrf_score"),
        "preview": (hit.get("text") or "")[:limit],
    }


def _is_general_faq(title: str) -> bool:
    return any(m in (title or "") for m in _FAQ_TITLE_MARKERS)


def _bigrams(text: str) -> set[str]:
    s = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text or "")
    return {s[i : i + 2] for i in range(max(0, len(s) - 1))}


def _title_overlap(query: str, title: str) -> float:
    """query 与标题的字符 bigram 覆盖率，用来做轻量“实体命中”判断。"""
    qg = _bigrams(query)
    tg = _bigrams(re.sub(r"^[A-Z]\d+\s*", "", title or ""))
    if not qg or not tg:
        return 0.0
    return len(qg & tg) / len(qg)


def _apply_title_boost(cands: list[dict], query: str, boost: float) -> None:
    if boost <= 0:
        return
    for c in cands:
        if _is_general_faq(c.get("title", "")):
            continue
        ratio = _title_overlap(query, c.get("title", ""))
        if ratio > 0:
            c["title_boost"] = round(float(boost) * ratio, 6)


def _demote_faq_on_tie(out: list[dict], margin: float) -> list[dict]:
    """FAQ 与具体文档几乎并列时，让具体制度文档优先；差距明显则不干预。"""
    if margin <= 0 or len(out) < 2 or not _is_general_faq(out[0].get("title", "")):
        return out
    second = next((h for h in out[1:] if not _is_general_faq(h.get("title", ""))), None)
    if second is None:
        return out
    faq_score = float(out[0].get("rerank_score") or out[0].get("similarity") or 0.0)
    second_score = float(second.get("rerank_score") or second.get("similarity") or 0.0)
    if faq_score - second_score < float(margin):
        return [second, *[h for h in out if h is not second]]
    return out


def retrieve(
    query: str, *, db, owner_id: uuid.UUID, collected_ids: list[uuid.UUID] | None = None,
    top_k: int | None = None, min_similarity: float | None = None, per_doc_cap: int | None = None,
    rerank: bool = True, diag: dict | None = None, route_key: str | None = None,
    parent_mode: bool = False, multi_query: bool | str = "auto", record_trace: bool = True,
    hybrid_override: bool | None = None,
) -> list[dict]:
    """两阶段检索：向量过召回（top_k*oversample）→（可选）rerank 精排 → 取 top_k。

    精准性保障：
    - enabled=false / 非 ready / 已删除的文档，其分片一律过滤（作者关掉即不参与）；
    - similarity < min_similarity 的弱相关分片丢弃；
    - 单文档最多 per_doc_cap 块，避免长文档霸榜；
    - rerank 未配置或失败时自动退化为单层向量召回（保证不回归）。

    diag：若传入 dict，则回填本次检索的可观测诊断（向量/关键词/重排是否生效、
    各阶段计数、trace_id），用于前端「引用来源」标注与运维排查。
    """
    from app.core.config import get_settings
    from app.crud import knowledge as _kb
    from app.services import rag_settings, rag_trace

    trace = rag_trace.current_trace()
    try:
        cfg = rag_settings.get_config(db)
    except Exception:
        cfg = {}
    route_key = route_key or (trace.route if trace else "") or "default"
    overrides = (cfg.get("route_overrides") or {}).get(route_key) or {}
    if top_k is None:
        top_k = int(overrides.get("top_k", cfg.get("top_k", TOP_K_DEFAULT)))
    if per_doc_cap is None:
        per_doc_cap = int(overrides.get("per_doc_cap", cfg.get("per_doc_cap", 2)))
    if min_similarity is None:
        min_similarity = overrides.get("min_similarity", cfg.get("min_similarity"))
    if min_similarity is None:
        min_similarity = get_settings().RAG_MIN_SIMILARITY
    gate = float(min_similarity)
    oversample = int(overrides.get("rerank_oversample", cfg.get("rerank_oversample", RERANK_OVERSAMPLE)))
    # 路由级 hybrid 开关：评测路由（eval）可单独开 Hybrid 做 A/B，不影响生产路由；
    # 评测运行可显式传 hybrid_override 做同环境 dense/hybrid 对比。
    hybrid_enabled = bool(overrides.get("hybrid_enabled", cfg.get("hybrid_enabled")))
    if hybrid_override is not None:
        hybrid_enabled = bool(hybrid_override)

    always_multi = multi_query is True
    auto_multi = multi_query == "auto"
    auto_parts: list[str] = []
    if always_multi or auto_multi:
        parts = _split_multi_intent(query)
        if len(parts) > 1:
            if always_multi:
                return _retrieve_multi_query(
                    query, subqueries=parts, db=db, owner_id=owner_id,
                    collected_ids=collected_ids, top_k=int(top_k),
                    min_similarity=min_similarity, per_doc_cap=int(per_doc_cap),
                    rerank=rerank, route_key=route_key, parent_mode=parent_mode,
                    diag=diag, hybrid_override=hybrid_override,
                )
            auto_parts = parts
        else:
            auto_multi = False

    d = diag if diag is not None else {}
    d.update({
        "vector": False, "keyword": False, "rerank": False, "rerank_model": None,
        "gate": gate, "route": route_key, "stage_timings": {},
        "hybrid_enabled": hybrid_enabled,
    })
    title_boost = float(cfg.get("title_match_boost", _TITLE_MATCH_BOOST) or 0.0)
    faq_tie_margin = float(cfg.get("faq_tie_margin", _FAQ_TIE_MARGIN) or 0.0)
    d["title_match_boost"] = title_boost
    d["faq_tie_margin"] = faq_tie_margin
    if auto_multi:
        d["auto_multi_query"] = False
        d["auto_margin"] = None
        d["auto_multi_threshold"] = _MULTI_QUERY_MARGIN
    if trace is not None:
        d["trace_id"] = trace.trace_id
    t0 = time.time()
    where: dict
    collected = [str(x) for x in (collected_ids or [])]
    if collected:
        where = {"$or": [{"owner_id": str(owner_id)}, {"doc_id": {"$in": collected}}]}
    else:
        where = {"owner_id": str(owner_id)}
    n_fetch = max(int(top_k) * (oversample if rerank else 1), 10)

    rewritten, did_rewrite = _rewrite_query(query, cfg)
    d["query_rewritten"] = did_rewrite
    search_query = rewritten if did_rewrite else query

    keyword_candidates = 0
    rerank_in = 0
    parent_texts: dict[int, str] = {}

    def _emit(out: list[dict], *, error: str | None = None) -> None:
        # 模式标签先于 trace 判断计算：无 trace 时 diag 也要可读
        d["retrieval_mode"] = _compute_retrieval_mode(d)
        if trace is None or not record_trace:
            return
        elapsed_ms = int((time.time() - t0) * 1000)
        timings = dict(trace.stage_timings)
        timings.update(d.get("stage_timings") or {})
        rag_trace.record(
            trace,
            query=query,
            rewritten_query=search_query,
            filters=where,
            embedding_fingerprint=active_collection_name(parent=parent_mode) if not error else "",
            vector_candidates=int(d.get("vector_in", 0) or 0),
            keyword_candidates=keyword_candidates,
            rerank_candidates=rerank_in,
            gated_out=int(d.get("gated_out", 0) or 0),
            vector_ok=bool(d.get("vector")),
            keyword_used=bool(d.get("keyword")),
            rerank_ok=bool(d.get("rerank")),
            rerank_model=d.get("rerank_model") or "",
            zero_result=not out,
            is_error=bool(error),
            error=error,
            latency_ms=elapsed_ms,
            stage_timings=timings,
            hits=[_hit_preview(h) for h in out],
        )

    def _maybe_auto_multi(out: list[dict]) -> list[dict]:
        """auto 模式：先看 baseline 的 top1/top2 分差，不自信时才跑多意图。"""
        if not auto_multi or not d.get("vector") or len(out) < 2:
            return out
        margin = _effective_score(out[0]) - _effective_score(out[1])
        d["auto_margin"] = round(margin, 4)
        if margin > _MULTI_QUERY_MARGIN:
            return out
        try:
            multi = _retrieve_multi_query(
                query, subqueries=auto_parts, db=db, owner_id=owner_id,
                collected_ids=collected_ids, top_k=int(top_k),
                min_similarity=min_similarity, per_doc_cap=int(per_doc_cap),
                rerank=rerank, route_key=route_key, parent_mode=parent_mode,
                diag=d,
            )
        except Exception:
            multi = []
        if multi:
            d["auto_multi_query"] = True
            d["final"] = len(multi)
            return multi
        return out

    try:
        # —— 第一阶段：向量召回（embedding 不可用/异常/无结果时静默降级到关键词） ——
        cands: list[dict] = []
        t_vec = time.time()
        try:
            col = get_collection(parent=True) if parent_mode else get_collection()
            q_emb = (embed_texts([search_query], parent=True) if parent_mode
                     else embed_texts([search_query]))[0]
            res = col.query(query_embeddings=[q_emb], n_results=n_fetch, where=where)
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            for doc, meta, dist in zip(docs, metas, dists):
                sim = round(1 - float(dist) / 2, 4) if dist is not None else 0.0
                if sim < gate:
                    d["gated_out"] = d.get("gated_out", 0) + 1
                    continue
                cands.append({
                    "text": doc, "title": (meta or {}).get("title", ""),
                    "doc_id": (meta or {}).get("doc_id", ""), "similarity": sim,
                    "parent_text": (meta or {}).get("parent_text"),
                })
            d["vector"] = True
            d["vector_in"] = len(cands)
            _bump("vector_ok")
        except Exception:
            cands = []
            d["vector"] = False
            _bump("vector_fail")
        d["stage_timings"]["vector"] = round((time.time() - t_vec) * 1000, 2)

        # 文档级过滤：关闭检索 / 未就绪 / 已删除的文档，其分片一律不要
        usable = _kb.usable_doc_ids(db, doc_ids=[c["doc_id"] for c in cands]) if cands else set()
        cands = [c for c in cands if c["doc_id"] in usable]

        # 正式 Hybrid：无论向量是否有结果，都执行关键词召回，再用 RRF 融合。
        # 向量异常/空结果时，关键词结果仍属于可解释的 hybrid 运行，不伪装成
        # 普通 keyword fallback；两种模式在诊断和评测中分开统计。
        if hybrid_enabled:
            t_kw = time.time()
            kw = _keyword_search(
                search_query, db=db, owner_id=owner_id,
                collected_ids=collected_ids, top_k=int(cfg.get("hybrid_candidates", 50)),
                parent=parent_mode,
            )
            keyword_candidates = len(kw)
            if kw:
                cands = _rrf_merge(cands, kw)
                d["hybrid"] = True
            d["stage_timings"]["keyword"] = round((time.time() - t_kw) * 1000, 2)

        if not cands:
            # —— 兜底：向量/Hybrid 均为空 → 关键词检索，保证有结果可用 ——
            if cfg.get("keyword_fallback_enabled", True) and not hybrid_enabled:
                _bump("keyword_fallback")
                t_kw = time.time()
                out = _keyword_search(
                    search_query, db=db, owner_id=owner_id,
                    collected_ids=collected_ids, top_k=int(top_k),
                    parent=parent_mode,
                )
                keyword_candidates = len(out)
                d["stage_timings"]["keyword_fallback"] = round((time.time() - t_kw) * 1000, 2)
            else:
                out = []
            d["keyword"] = bool(out)
            d["final"] = len(out)
            for c in out:
                pt = c.pop("parent_text", None)
                if pt:
                    c["child_text"] = c.get("text", "")
                    c["text"] = pt
            _sort_by_score(out)
            out = _demote_faq_on_tie(out, faq_tie_margin)
            out = _maybe_auto_multi(out)
            _record_query(out, t0)
            _emit(out)
            return out

        # 第二阶段：可选 rerank 重排（失败静默回落向量序）
        if rerank:
            t_rr = time.time()
            rerank_in = len(cands)
            cands, rmeta = _apply_rerank(search_query, cands, db, owner_id, parent_mode=parent_mode)
            d.update(rmeta)
            d["rerank_in"] = rerank_in
            d["stage_timings"]["rerank"] = round((time.time() - t_rr) * 1000, 2)

        # 标题/实体命中加成 + FAQ 并列让位：在重排之后、截断之前做，
        # 只调整“具体制度文档”的排序，不改变向量召回与 rerank 原始分。
        _apply_title_boost(cands, search_query, title_boost)
        if title_boost > 0 and cands:
            cands.sort(key=_effective_score, reverse=True)

        # 父子切分：子块检索/重排，命中后回填父块作为 LLM 上下文
        for c in cands:
            if c.get("parent_text"):
                parent_texts[id(c)] = c["parent_text"]

        # per_doc_cap + top_k 截断
        per_doc: dict[str, int] = {}
        out: list[dict] = []
        for c in cands:
            if per_doc.get(c["doc_id"], 0) >= per_doc_cap:
                continue
            per_doc[c["doc_id"]] = per_doc.get(c["doc_id"], 0) + 1
            out.append(c)
            if len(out) >= top_k:
                break

        # 回填父块上下文（如果有），保留 child_text 便于排障
        for c in out:
            pt = parent_texts.get(id(c)) or c.pop("parent_text", None)
            if pt:
                c["child_text"] = c.get("text", "")
                c["text"] = pt

        # 统一按「有效分」显式排序：有重排分用重排分，否则用 RRF/向量相似度
        _sort_by_score(out)
        out = _demote_faq_on_tie(out, faq_tie_margin)
        out = _maybe_auto_multi(out)
        d["final"] = len(out)
        _record_query(out, t0)
        _emit(out)
        return out
    except Exception as exc:  # noqa: BLE001 —— 观测到异常后继续抛出，不改变调用方行为
        d["error"] = str(exc)
        _emit([], error=str(exc) or exc.__class__.__name__)
        raise


def _effective_score(hit: dict) -> float:
    """命中分片的排序依据分：重排分优先，其次 RRF，最后向量相似度。"""
    base = float(hit.get("similarity") or 0.0)
    for key in ("rerank_score", "rrf_score"):
        v = hit.get(key)
        if isinstance(v, (int, float)):
            base = float(v)
            break
    return base + float(hit.get("title_boost") or 0.0)


def _sort_by_score(hits: list[dict]) -> None:
    """原地按有效分降序排序（稳定：分数相同保持原序）。"""
    hits.sort(key=_effective_score, reverse=True)


def retrieval_summary(diag: dict) -> str:
    """把检索诊断压成一句人话，用于「引用来源」标注：向量/关键词/重排是否生效。"""
    stages: list[str] = []
    if diag.get("multi_query"):
        stages.append(f"多意图拆分 {len(diag.get('multi_query_sub') or [])} 路")
    if diag.get("vector"):
        stages.append(f"向量召回 {diag.get('vector_in', 0)} 条")
        if diag.get("gated_out"):
            stages.append(f"门控过滤 {diag.get('gated_out')} 条（相似度<{diag.get('gate')}）")
    if diag.get("hybrid"):
        stages.append("混合检索 RRF")
    if diag.get("rerank"):
        model = diag.get("rerank_model") or ""
        stages.append(f"重排精排（{model}）" if model else "重排精排")
    elif diag.get("vector"):
        stages.append("未重排")
    if diag.get("keyword"):
        stages.append("关键词兜底")
    summary = " → ".join(stages) if stages else "未检索"
    mode = diag.get("retrieval_mode")
    return f"[{mode}] {summary}" if mode else summary


def _record_query(out: list[dict], t0: float) -> None:
    """记录一次检索的命中/时延指标。"""
    _bump("queries")
    _bump("hits", 1 if out else 0)
    _bump("zero_results", 1 if not out else 0)
    _bump("latency_ms_sum", (time.time() - t0) * 1000)


# —— 关键词兜底检索（向量不可用/无结果时）——

_STOP_CHARS = set("的了和是我你他她它们在有就不都与及或对为以于被把将从到")

def _query_terms(query: str) -> list[str]:
    """查询词元：中文取双字滑窗（无分词依赖）+ 英文/数字整词。"""
    q = _norm_text(query).lower()
    terms = set(re.findall(r"[a-z0-9_]+", q))
    cjk = re.sub(r"[^\u4e00-\u9fff]+", "", q)
    for i in range(len(cjk) - 1):
        bg = cjk[i : i + 2]
        if not (set(bg) & _STOP_CHARS):
            terms.add(bg)
    return [t for t in terms if len(t) >= 2]


def _keyword_collections(parent: bool = False) -> list:
    """关键词兜底可读的集合：当前集合为空时，自动兼容旧版 ``knowledge`` 集合。

    背景：配置/更换 Embedding 后，指纹会切到新的空集合；此时文档仍 ready，
    但新集合还没有向量。若关键词兜底也只读新集合，用户会看到「明明有文档却检索不到」。
    关键词检索是纯文本、与向量空间无关，因此可安全地回退到旧集合读取。
    家长域同理：父索引尚未建好时，用系统集合做纯文本兜底（白名单仍二次过滤）。
    """
    cols = []
    try:
        active = get_collection(parent=True) if parent else get_collection()
        cols.append(active)
        if parent:
            try:
                sys_col = get_collection()
                if sys_col.name != active.name:
                    cols.append(sys_col)
            except Exception:
                pass
        elif active.name != DEFAULT_COLLECTION:
            try:
                import chromadb

                client = chromadb.PersistentClient(path=str(CHROMA_DIR))
                legacy = client.get_collection(DEFAULT_COLLECTION)
                if int(legacy.count()) > 0 and int(active.count()) == 0:
                    cols.append(legacy)
            except Exception:
                pass
    except Exception:
        pass
    return cols


def _keyword_search(
    query: str, *, db, owner_id, collected_ids=None, top_k: int = TOP_K_DEFAULT,
    parent: bool = False,
) -> list[dict]:
    """关键词兜底：在本人可见分片上按词元命中打分（无需 embedding，纯本地）。

    适用于向量检索不可用（未配 embedding / 接口异常）或向量召回为空时，
    保证 Agent 仍有可用检索结果，不因模型故障而完全失忆。
    """
    docs: list = []
    metas: list = []
    try:
        collected = [str(d) for d in (collected_ids or [])]
        if collected:
            where = {"$or": [{"owner_id": str(owner_id)}, {"doc_id": {"$in": collected}}]}
        else:
            where = {"owner_id": str(owner_id)}
        for col in _keyword_collections(parent=parent):
            try:
                got = col.get(where=where, include=["documents", "metadatas"])
            except Exception:
                continue
            docs.extend(got.get("documents") or [])
            metas.extend(got.get("metadatas") or [])
    except Exception:
        return []
    if not docs:
        return []
    terms = _query_terms(query)
    if not terms:
        return []
    from app.crud import knowledge as _kb

    usable = _kb.usable_doc_ids(db, doc_ids=[(m or {}).get("doc_id", "") for m in metas])
    scored: list[dict] = []
    for doc, meta in zip(docs, metas):
        meta = meta or {}
        doc_id = meta.get("doc_id", "")
        if doc_id not in usable:
            continue
        low = (doc or "").lower()
        hits = sum(low.count(t) for t in terms)
        if hits <= 0:
            continue
        scored.append({
            "text": doc, "title": meta.get("title", ""), "doc_id": doc_id,
            "similarity": round(min(1.0, hits / max(len(terms), 1) / 3), 4),
            "parent_text": meta.get("parent_text"),
        })
    if not scored:
        return []
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    per_doc: dict[str, int] = {}
    out: list[dict] = []
    for c in scored:
        if per_doc.get(c["doc_id"], 0) >= 2:
            continue
        per_doc[c["doc_id"]] = per_doc.get(c["doc_id"], 0) + 1
        out.append(c)
        if len(out) >= top_k:
            break
    return out


def sweep_orphan_vectors(db, *, delete: bool = True) -> dict:
    """僵尸向量清理：删除「文档已删除/不存在」但向量库仍残留的分片。

    源文档删除或过期后若不同步清理，过时信息会污染大模型回答。
    返回统计：{"scanned": 分片总数, "orphan_docs": 僵尸文档数, "deleted": 删除分片数}
    """
    from app.crud import knowledge as _kb

    col = get_collection()
    got = col.get(include=["metadatas"])
    metas = got.get("metadatas") or []
    ids = got.get("ids") or []
    live_doc_ids = {
        str(d) for d in _kb.all_document_ids(db)
    }  # 数据库中仍存在的全部文档
    by_doc: dict[str, list[str]] = {}
    for vid, meta in zip(ids, metas):
        doc_id = (meta or {}).get("doc_id", "")
        if doc_id and doc_id not in live_doc_ids:
            by_doc.setdefault(doc_id, []).append(vid)
    deleted = 0
    if delete and by_doc:
        for doc_id, vids in by_doc.items():
            try:
                col.delete(ids=vids)
                deleted += len(vids)
            except Exception:
                continue
    return {
        "collection": _collection_name(),
        "scanned": len(ids),
        "orphan_docs": len(by_doc),
        "deleted": deleted,
    }


def list_knowledge_collections() -> list[str]:
    """列出所有知识库集合（含历史 embedding 分片），便于运维查看/清理。"""
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return [
        c.name for c in client.list_collections()
        if c.name.startswith(COLLECTION_BASE) or c.name.startswith(PARENT_COLLECTION_BASE)
    ]


# —— 家长客服独立索引（配置专属 Embedding 后才有意义） ——

_parent_sync_state: dict = {"running": False, "result": None}
_parent_sync_lock = threading.Lock()


def _parent_dedicated_fingerprint() -> str:
    """家长专属集合的 embedding 指纹；复用系统集合/未配置时返回空串。"""
    if not _parent_uses_dedicated_collection():
        return ""
    resolved = _resolve_parent_embedding()
    return resolved.fingerprint() if resolved else ""


def parent_index_status(db=None) -> dict:
    """家长索引状态：可见文档数、已按当前指纹索引数、待同步数。"""
    from app.crud import knowledge as _kb

    own = db is None
    if own:
        db = _session_factory()()
    try:
        try:
            docs = _kb.list_parent_visible_documents(db=db)
        except Exception:
            # 存量库尚未迁移出 visible_to_parents 等字段时，不让状态接口 500
            return {
                "configured": _resolve_parent_embedding() is not None,
                "dedicated": False, "fingerprint": "", "collection": _collection_name(parent=True),
                "documents": 0, "indexed": 0, "pending": 0,
                "running": bool(_parent_sync_state.get("running")),
                "last_result": _parent_sync_state.get("result"),
                "error": "家长可见字段缺失，请先执行数据库迁移（upgrade head）",
            }
        fp = _parent_dedicated_fingerprint()
        dedicated = bool(fp)
        if dedicated:
            indexed = sum(
                1 for d in docs
                if (d.extra or {}).get("parent_index_fingerprint") == fp
            )
        else:
            indexed = len(docs)
        return {
            "configured": _resolve_parent_embedding() is not None,
            "dedicated": dedicated,
            "fingerprint": fp,
            "collection": _collection_name(parent=True),
            "documents": len(docs),
            "indexed": indexed,
            "pending": max(0, len(docs) - indexed),
            "running": bool(_parent_sync_state.get("running")),
            "last_result": _parent_sync_state.get("result"),
        }
    finally:
        if own:
            db.close()


def sync_parent_index(limit: int = 200) -> dict:
    """把家长可见文档按当前家长 Embedding 重建到独立集合（增量：未变跳过）。"""
    from app.crud import knowledge as _kb

    fp = _parent_dedicated_fingerprint()
    if not fp:
        return {
            "dedicated": False, "documents": 0, "indexed": 0, "skipped": 0, "failed": 0,
            "hint": "未配置家长专属 Embedding（或与系统一致），家长端复用系统索引，无需重建",
        }
    with _parent_sync_lock:
        if _parent_sync_state.get("running"):
            return {"dedicated": True, "running": True, "documents": 0, "indexed": 0, "skipped": 0, "failed": 0}
        _parent_sync_state["running"] = True
    stats = {"dedicated": True, "documents": 0, "indexed": 0, "skipped": 0, "failed": 0}
    db = _session_factory()()
    try:
        try:
            docs = _kb.list_parent_visible_documents(db=db, limit=limit)
        except Exception as exc:  # noqa: BLE001 —— 存量库未迁移时给出可读错误
            stats["error"] = f"读取家长可见文档失败：{exc}"
            return stats
        stats["documents"] = len(docs)
        for doc in docs:
            extra = dict(doc.extra or {})
            fh = _file_hash(doc.file_path)
            if extra.get("parent_index_fingerprint") == fp and extra.get("parent_indexed_hash") == fh:
                stats["skipped"] += 1
                continue
            try:
                if not doc.file_path or not Path(doc.file_path).exists():
                    raise FileNotFoundError("源文件已丢失")
                text = extract_text(doc.file_path, doc.file_name or "")
                index_document(
                    doc_id=doc.id, owner_id=doc.owner_id, title=doc.title,
                    text=text, parent=True,
                )
                extra["parent_index_fingerprint"] = fp
                extra["parent_indexed_hash"] = fh
                extra.pop("parent_index_error", None)
                doc.extra = extra
                db.commit()
                _store_index_profile(doc.id, parent=True)
                stats["indexed"] += 1
            except Exception as exc:  # noqa: BLE001 —— 单篇失败不阻断其余文档
                extra["parent_index_error"] = str(exc)[:500]
                doc.extra = extra
                db.commit()
                stats["failed"] += 1
    finally:
        db.close()
        with _parent_sync_lock:
            _parent_sync_state["running"] = False
            _parent_sync_state["result"] = stats
    return stats


def start_parent_index_sync() -> bool:
    """后台异步重建家长索引；未启用独立 Embedding 时直接返回 False。"""
    if not _parent_dedicated_fingerprint():
        return False
    if _parent_sync_state.get("running"):
        return True
    threading.Thread(target=sync_parent_index, name="parent-index-sync", daemon=True).start()
    return True


def index_in_background(*, doc_id: uuid.UUID, owner_id: uuid.UUID, title: str,
                        file_path: str, file_name: str, mark_done, mark_progress=None,
                        resolved=None) -> None:
    """后台线程：解析 → 切块 → 入库 → 回调落状态，不阻塞上传接口。

    注：embedding 现为系统级，索引不依赖教师个人配置，resolved 参数保留兼容。
    """

    def _run_inner():
        try:
            if mark_progress is not None:
                mark_progress(doc_id, "queued", 5, "排队等待索引…")
            with _INDEX_SEMAPHORE:
                if mark_progress is not None:
                    mark_progress(doc_id, "parse", 10, "正在解析文档…")
                text = extract_text(file_path, file_name)
                if mark_progress is not None:
                    mark_progress(doc_id, "parse", 25, f"解析完成，共 {len(text)} 字")
                n = index_document(
                    doc_id=doc_id, owner_id=owner_id, title=title, text=text,
                    on_progress=(lambda s, p, d: mark_progress(doc_id, s, p, d)) if mark_progress else None,
                )
                if n == 0:
                    mark_done(doc_id, 0, "文档解析为空，未生成切块")
                else:
                    mark_done(doc_id, n, None)
                    # 记录已索引的源文件哈希：增量同步据此判断是否需要重跑（未变则跳过，省 Token）
                    _store_index_hash(doc_id, _file_hash(file_path))
                    # 冻结本次索引档案（分块参数/embedding/集合/向量维度），供后台观测
                    _store_index_profile(doc_id)
        except Exception as e:  # noqa: BLE001 —— 错误写入文档状态
            mark_done(doc_id, 0, str(e) or e.__class__.__name__)

    threading.Thread(target=_run_inner, daemon=True).start()


__all__ = [
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "TOP_K_DEFAULT",
    "chunk_semantic",
    "embed_texts",
    "extract_text",
    "index_document",
    "delete_document_vectors",
    "rerank_documents",
    "retrieve",
    "index_in_background",
    "get_collection",
    "local_embedding_ready",
    "active_collection_name",
    "collection_stats",
    "document_storage_profile",
    "get_document_chunks",
    "invalidate_embedding_cache",
    "invalidate_parent_embedding_cache",
    "sweep_orphan_vectors",
    "list_knowledge_collections",
    "parent_index_status",
    "sync_parent_index",
    "start_parent_index_sync",
]
