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
# 未配置 embedding（回退本地 Qwen）时的默认集合名，保持与历史数据兼容
DEFAULT_COLLECTION = COLLECTION_BASE

# rerank 熔断：连续失败达到阈值后临时短路，直接用向量序（避免每次查询都等超时）
_RERANK_FAIL_STREAK = 0
_RERANK_FAIL_LOCK = threading.Lock()
_RERANK_CIRCUIT_THRESHOLD = 3
_RERANK_CIRCUIT_UNTIL = 0.0
RERANK_TIMEOUT_S = 1.5


@lru_cache(maxsize=1)
def get_embed_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(str(MODEL_DIR))


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
        from app.core.database import SessionLocal
        from app.crud import retrieval_config as crud

        db = SessionLocal()
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


def _collection_name() -> str:
    """集合名按 embedding 指纹分片：不同向量空间绝不混存（修跨教师串味/维度错）。"""
    resolved = _resolve_embedding()
    if resolved is None:
        return DEFAULT_COLLECTION
    return f"{COLLECTION_BASE}__{resolved.fingerprint()}"


def get_collection():
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(_collection_name())


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


def _embed_batch_remote(batch: list[str], client, _depth: int = 0) -> list[list[float]]:
    """一批文本的 embedding。

    - 批大小/参数非法 → **二分拆批重试**（自适应各厂商限制，不写死条数）；
    - 限流/超时 → 指数退避重试；
    - 单条仍失败 → 上抛（交由上层 LLMConfigError 友好报错）。
    """
    delay = EMBED_BACKOFF_BASE
    last: Exception | None = None
    for attempt in range(EMBED_MAX_RETRY):
        try:
            vecs = client.embed_documents(batch)
            return [[float(x) for x in v] for v in vecs]
        except Exception as e:  # noqa: BLE001
            last = e
            # 批过大：二分后分别重试（递归），直到能通过
            if _is_batch_size_error(e) and len(batch) > 1 and _depth < 8:
                mid = len(batch) // 2
                return (
                    _embed_batch_remote(batch[:mid], client, _depth + 1)
                    + _embed_batch_remote(batch[mid:], client, _depth + 1)
                )
            if attempt == EMBED_MAX_RETRY - 1 or not _is_retryable(e):
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
        return _embed_batch_remote(batches[0], client)
    with ThreadPoolExecutor(max_workers=EMBED_CONCURRENCY) as ex:
        for part in ex.map(lambda b: _embed_batch_remote(b, client), batches):
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
        from app.core.database import SessionLocal
        from app.crud import knowledge as _kb

        db = SessionLocal()
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
    from app.core.database import SessionLocal
    from app.crud import knowledge as _kb

    db = SessionLocal()
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
    from app.core.database import SessionLocal
    from app.crud import knowledge as _kb

    db = SessionLocal()
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


def embed_texts(texts: list[str], resolved=None) -> list[list[float]]:
    """向量化（带持久化缓存 + 并发/批量/退避）。

    - **持久化缓存**：按 (embedding 指纹, 分片内容哈希) 缓存向量到本地 npz，
      文档更新时未变化的分片直接命中缓存，避免重复调用 API、重复消耗 Token。
    - **并发/批量/退避**：分批 + 多线程，失败指数退避重试，应对限流。
    - 回退链：系统级 Embedding（remote/local）→ 全局 env → 本地 Qwen。
    """
    from app.services.llm import LLMConfigError

    if resolved is None:
        resolved = _resolve_embedding()

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
    if not MODEL_DIR.exists():
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
    on_progress=None,
) -> int:
    """切块 → 向量化 → 写入 Chroma（当前 embedding 分片集合），返回 chunk 数。

    采用语义切片（标题/段落感知 + 重叠）；向量化走 embed_texts 的持久化缓存，
    文档更新时未变化的分片命中缓存、不重复消耗 Token。
    """
    chunks = chunk_semantic(text)
    if on_progress is not None:
        on_progress("chunk", 40, f"切块完成，共 {len(chunks)} 块")
    if not chunks:
        return 0
    col = get_collection()
    delete_document_vectors(doc_id)
    if on_progress is not None:
        on_progress("embed", 65, "向量化中…")
    embs = embed_texts(chunks)
    ids = [f"{doc_id}:{i}" for i in range(len(chunks))]
    col.upsert(
        ids=ids,
        embeddings=embs,
        documents=chunks,
        metadatas=[
            {"doc_id": str(doc_id), "owner_id": str(owner_id), "title": title, "chunk_no": i}
            for i in range(len(chunks))
        ],
    )
    return len(chunks)


def delete_document_vectors(doc_id: uuid.UUID) -> None:
    """删除某文档的全部分片向量（当前 embedding 分片集合）。

    注：若换过 embedding 模型，历史分片在旧集合里，切换后不会自动清理
    （数据不串味，但残留可在运维层离线清理）。
    """
    try:
        col = get_collection()
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
    with _RERANK_FAIL_LOCK:
        _RERANK_FAIL_STREAK += 1
        if _RERANK_FAIL_STREAK >= _RERANK_CIRCUIT_THRESHOLD:
            _RERANK_CIRCUIT_UNTIL = time.time() + 60.0


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


def rerank_documents(query: str, documents: list[str], resolved) -> tuple[list[int], list[float]]:
    """调 rerank 模型，返回 (按相关度降序的原文下标, 对应相关度分数)。

    分数为 rerank 模型的 relevance_score（不同厂商量纲不同，仅用于排序/展示）。
    失败抛异常由上层降级。
    """
    if not documents:
        return [], []
    if resolved.provider == "local":
        # 本地 rerank 预留：走 sentence-transformers CrossEncoder
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
    tried: list[str] = []
    last: Exception | None = None
    data: dict | None = None
    with httpx.Client(timeout=RERANK_TIMEOUT_S) as client:
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


def _apply_rerank(query: str, cands: list[dict], db, owner_id) -> tuple[list[dict], dict]:
    """对过召回候选做重排；任何失败/超时/熔断 → 原样返回向量序（静默降级）。

    返回 (重排后候选, 诊断)。诊断含是否真的重排成功、所用模型、候选数，
    供上层观测「向量检索与重排到底有没有生效」。重排命中的分片会带上 rerank_score。
    """
    meta = {"rerank": False, "rerank_model": None, "rerank_in": len(cands)}
    if len(cands) <= 1 or _rerank_circuit_open():
        return cands, meta
    try:
        from app.crud import retrieval_config as crud

        resolved = crud.resolve_rerank(db, owner_id)
        if resolved is None:
            return cands, meta
        order, scores = rerank_documents(query, [c["text"] for c in cands], resolved)
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


def retrieve(
    query: str, *, db, owner_id: uuid.UUID, collected_ids: list[uuid.UUID] | None = None,
    top_k: int = TOP_K_DEFAULT, min_similarity: float | None = None, per_doc_cap: int = 2,
    rerank: bool = True, diag: dict | None = None,
) -> list[dict]:
    """两阶段检索：向量过召回（top_k*5）→（可选）rerank 精排 → 取 top_k。

    精准性保障：
    - enabled=false / 非 ready / 已删除的文档，其分片一律过滤（作者关掉即不参与）；
    - similarity < min_similarity 的弱相关分片丢弃；
    - 单文档最多 per_doc_cap 块，避免长文档霸榜；
    - rerank 未配置或失败时自动退化为单层向量召回（保证不回归）。

    diag：若传入 dict，则回填本次检索的可观测诊断（向量/关键词/重排是否生效、
    各阶段计数），用于前端「引用来源」标注与运维排查。
    """
    from app.core.config import get_settings
    from app.crud import knowledge as _kb

    # 阈值门控：显式 min_similarity 优先，否则取全局 RAG_MIN_SIMILARITY（默认 0.35）。
    # 评估暴露 0.15 过松 → 低相关过度召回（反例「午餐吃什么」也捞到片段）。
    gate = float(min_similarity) if min_similarity is not None else float(get_settings().RAG_MIN_SIMILARITY)
    d = diag if diag is not None else {}
    d.update({"vector": False, "keyword": False, "rerank": False, "rerank_model": None, "gate": gate})
    t0 = time.time()
    where: dict
    collected = [str(d) for d in (collected_ids or [])]
    if collected:
        where = {"$or": [{"owner_id": str(owner_id)}, {"doc_id": {"$in": collected}}]}
    else:
        where = {"owner_id": str(owner_id)}
    n_fetch = max(top_k * (RERANK_OVERSAMPLE if rerank else 1), 10)

    # —— 第一阶段：向量召回（embedding 不可用/异常/无结果时静默降级到关键词） ——
    cands: list[dict] = []
    try:
        col = get_collection()
        q_emb = embed_texts([query])[0]
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
            })
        d["vector"] = True
        d["vector_in"] = len(cands)
        _bump("vector_ok")
    except Exception:
        cands = []
        d["vector"] = False
        _bump("vector_fail")

    # 文档级过滤：关闭检索 / 未就绪 / 已删除的文档，其分片一律不要
    usable = _kb.usable_doc_ids(db, doc_ids=[c["doc_id"] for c in cands]) if cands else set()
    cands = [c for c in cands if c["doc_id"] in usable]
    if not cands:
        # —— 兜底：向量召回为空 → 关键词检索，保证有结果可用 ——
        _bump("keyword_fallback")
        out = _keyword_search(query, db=db, owner_id=owner_id, collected_ids=collected_ids, top_k=top_k)
        d["keyword"] = bool(out)
        d["final"] = len(out)
        _sort_by_score(out)
        _record_query(out, t0)
        return out

    # 第二阶段：可选 rerank 重排（失败静默回落向量序）
    if rerank:
        cands, rmeta = _apply_rerank(query, cands, db, owner_id)
        d.update(rmeta)
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
    # 统一按「有效分」显式排序：有重排分用重排分，否则用向量相似度，
    # 避免出现「显示分与顺序不一致」（曾出现 0.468 排在 0.5334 之前）。
    _sort_by_score(out)
    d["final"] = len(out)
    _record_query(out, t0)
    return out


def _effective_score(hit: dict) -> float:
    """命中分片的排序依据分：重排分优先，否则向量相似度。"""
    rs = hit.get("rerank_score")
    if isinstance(rs, (int, float)):
        return float(rs)
    return float(hit.get("similarity") or 0.0)


def _sort_by_score(hits: list[dict]) -> None:
    """原地按有效分降序排序（稳定：分数相同保持原序）。"""
    hits.sort(key=_effective_score, reverse=True)


def retrieval_summary(diag: dict) -> str:
    """把检索诊断压成一句人话，用于「引用来源」标注：向量/关键词/重排是否生效。"""
    stages: list[str] = []
    if diag.get("vector"):
        stages.append(f"向量召回 {diag.get('vector_in', 0)} 条")
        if diag.get("gated_out"):
            stages.append(f"门控过滤 {diag.get('gated_out')} 条（相似度<{diag.get('gate')}）")
    if diag.get("rerank"):
        model = diag.get("rerank_model") or ""
        stages.append(f"重排精排（{model}）" if model else "重排精排")
    elif diag.get("vector"):
        stages.append("未重排")
    if diag.get("keyword"):
        stages.append("关键词兜底")
    return " → ".join(stages) if stages else "未检索"


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


def _keyword_search(query: str, *, db, owner_id, collected_ids=None, top_k: int = TOP_K_DEFAULT) -> list[dict]:
    """关键词兜底：在本人可见分片上按词元命中打分（无需 embedding，纯本地）。

    适用于向量检索不可用（未配 embedding / 接口异常）或向量召回为空时，
    保证 Agent 仍有可用检索结果，不因模型故障而完全失忆。
    """
    try:
        col = get_collection()
        collected = [str(d) for d in (collected_ids or [])]
        if collected:
            where = {"$or": [{"owner_id": str(owner_id)}, {"doc_id": {"$in": collected}}]}
        else:
            where = {"owner_id": str(owner_id)}
        got = col.get(where=where, include=["documents", "metadatas"])
        docs = got.get("documents") or []
        metas = got.get("metadatas") or []
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
    return [c.name for c in client.list_collections() if c.name.startswith(COLLECTION_BASE)]


def index_in_background(*, doc_id: uuid.UUID, owner_id: uuid.UUID, title: str,
                        file_path: str, file_name: str, mark_done, mark_progress=None,
                        resolved=None) -> None:
    """后台线程：解析 → 切块 → 入库 → 回调落状态，不阻塞上传接口。

    注：embedding 现为系统级，索引不依赖教师个人配置，resolved 参数保留兼容。
    """

    def _run_inner():
        try:
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
    "invalidate_embedding_cache",
    "sweep_orphan_vectors",
    "list_knowledge_collections",
]