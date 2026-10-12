"""RAG 底座：本地 Qwen3-Embedding-0.6B + Chroma 持久化。

- 切块：模型 tokenizer 按 token 切，窗口 512、重叠 100。
- 物理存储：单一 collection + metadata（owner_id / visibility / doc_id / title）。
- 收录 = 引用不复制：检索范围 = 本人私有库 + 本人已收录的广场文档。
"""

from __future__ import annotations

import re
import threading
import uuid
from functools import lru_cache
from pathlib import Path

CHUNK_SIZE = 512
CHUNK_OVERLAP = 100
TOP_K_DEFAULT = 5
MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "Qwen3-Embedding-0.6B"
CHROMA_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma"
COLLECTION_NAME = "knowledge"


@lru_cache(maxsize=1)
def get_embed_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(str(MODEL_DIR))


def chunk_by_token(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按字符切分（中文 1 字≈1 token，英文约 4 字符≈1 token，取保守窗口）。

    不依赖模型 tokenizer：sentence-transformers 各版本 tokenizer 接口不一，
    曾导致 Rust 端 TextInputSequence 类型错误使索引失败。
    """
    text = (text or "").strip()
    if not text:
        return []
    # 保守换算：512 token ≈ 900 中文字符
    win = max(200, int(chunk_size * 1.75))
    ov = max(40, int(overlap * 1.75))
    step = max(1, win - ov)
    return [text[i : i + win].strip() for i in range(0, len(text), step) if text[i : i + win].strip()]


def get_collection():
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(COLLECTION_NAME)


_embed_client_cache: dict = {}


def _api_embeddings(resolved):
    from langchain_openai import OpenAIEmbeddings

    key = (resolved.base_url or "", resolved.api_key or "", resolved.embed_model or "")
    client = _embed_client_cache.get(key)
    if client is None:
        client = OpenAIEmbeddings(
            model=resolved.embed_model,
            api_key=resolved.api_key,
            base_url=resolved.base_url or None,
            timeout=60,
            max_retries=1,
            # 非 OpenAI 厂商不支持按模型查上下文长度，关掉该探测
            check_embedding_ctx_length=False,
        )
        _embed_client_cache[key] = client
    return client


def embed_texts(texts: list[str], resolved=None) -> list[list[float]]:
    """向量化。resolved 缺省时取当前请求上下文（路由层 use_teacher_llm 已压入）。

    - 有个人配置：走模型商 embedding API（免本地拉取，生产可用）；
      未填 embedding 模型则抛中文引导（部分厂商如 DeepSeek 无 embedding 接口）。
    - 无个人配置：回退本地 Qwen（开发机已下载权重时可用）。
    """
    from app.services import llm_context as _ctx
    from app.services.llm import LLMConfigError

    if resolved is None:
        resolved = _ctx.get_current()
    use_api = (
        resolved is not None
        and bool((resolved.embed_model or "").strip())
    )
    if use_api:
        try:
            vecs = _api_embeddings(resolved).embed_documents(list(texts))
        except LLMConfigError:
            raise
        except Exception as e:
            from app.services.llm import friendly_llm_error

            raise LLMConfigError(friendly_llm_error(e)) from e
        return [[float(x) for x in v] for v in vecs]
    if resolved is not None and not use_api and resolved.config_id is not None:
        # 教师自配但没填 embedding 模型：明确引导（部分厂商如 DeepSeek 无 embedding 接口）
        raise LLMConfigError(
            f"模型「{resolved.config_name or resolved.model}」未填写 embedding 模型，"
            "请到 设置 → 模型配置 中补充（如硅基流动/Zhipu 的 embedding 模型）后再试"
        )
    if not MODEL_DIR.exists():
        raise LLMConfigError(
            "未配置 embedding 模型：请到 设置 → 模型配置 添加并填写 embedding 模型"
        )
    model = get_embed_model()
    embs = model.encode(texts, convert_to_numpy=False)
    if hasattr(embs, "tolist"):
        embs = embs.tolist()
    return [[float(x) for x in e] for e in embs]


def extract_text(file_path: str, file_name: str = "") -> str:
    """解析 txt/md/pdf/docx 为纯文本；缺解析库时抛中文可读错误。"""
    suffix = Path(file_name or file_path).suffix.lower()
    if suffix in (".txt", ".md", ".markdown"):
        return Path(file_path).read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("未安装 pypdf，请先执行 uv pip install pypdf")
        reader = PdfReader(file_path)
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if suffix in (".docx",):
        try:
            import docx
        except ImportError:
            raise RuntimeError("未安装 python-docx，请先执行 uv pip install python-docx")
        return "\n".join(p.text for p in docx.Document(file_path).paragraphs)
    raise ValueError(f"暂不支持的文件类型：{suffix or '未知'}（支持 txt/md/pdf/docx）")


def index_document(
    *, doc_id: uuid.UUID, owner_id: uuid.UUID, title: str, text: str,
    on_progress=None,
) -> int:
    """切块 → 向量化 → 写入 Chroma，返回 chunk 数（on_progress(stage, percent, detail) 回调进度）。"""
    chunks = chunk_by_token(text)
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
    col = get_collection()
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


def retrieve(
    query: str, *, db, owner_id: uuid.UUID, collected_ids: list[uuid.UUID] | None = None,
    top_k: int = TOP_K_DEFAULT, min_similarity: float = 0.15, per_doc_cap: int = 2,
) -> list[dict]:
    """检索范围 = 本人文档 + 已收录的广场文档；按相似度取 top-K。

    精准性三件套（文档多了也不飘）：
    - enabled=false / 非 ready 的文档直接过滤（作者关掉即不参与）；
    - similarity < min_similarity 的弱相关切块丢弃；
    - 单文档最多 per_doc_cap 块，避免一个长文档霸榜。
    """
    from app.crud import knowledge as _kb

    col = get_collection()
    q_emb = embed_texts([query])[0]
    where: dict
    collected = [str(d) for d in (collected_ids or [])]
    if collected:
        where = {"$or": [{"owner_id": str(owner_id)}, {"doc_id": {"$in": collected}}]}
    else:
        where = {"owner_id": str(owner_id)}
    try:
        res = col.query(query_embeddings=[q_emb], n_results=max(top_k * 3, 10), where=where)
    except Exception:
        return []
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    cands: list[dict] = []
    for doc, meta, dist in zip(docs, metas, dists):
        sim = round(1 - float(dist) / 2, 4) if dist is not None else 0.0
        if sim < min_similarity:
            continue
        cands.append({
            "text": doc, "title": (meta or {}).get("title", ""),
            "doc_id": (meta or {}).get("doc_id", ""), "similarity": sim,
        })
    if not cands:
        return []
    # 文档级过滤：关闭检索 / 未就绪 / 已删除的文档，其切块一律不要
    usable = _kb.usable_doc_ids(db, doc_ids=[c["doc_id"] for c in cands])
    per_doc: dict[str, int] = {}
    out: list[dict] = []
    for c in cands:
        if c["doc_id"] not in usable:
            continue
        if per_doc.get(c["doc_id"], 0) >= per_doc_cap:
            continue
        per_doc[c["doc_id"]] = per_doc.get(c["doc_id"], 0) + 1
        out.append(c)
        if len(out) >= top_k:
            break
    return out


def index_in_background(*, doc_id: uuid.UUID, owner_id: uuid.UUID, title: str,
                        file_path: str, file_name: str, mark_done, mark_progress=None,
                        resolved=None) -> None:
    """后台线程：解析 → 切块 → 入库 → 回调落状态，不阻塞上传接口。"""

    def _run():
        from app.services import llm_context as _llm_ctx

        # 后台线程不继承请求上下文，用提交时快照的个人配置做 embedding
        with _llm_ctx.use_llm(resolved):
            _run_inner()

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
        except Exception as e:  # noqa: BLE001 —— 错误写入文档状态
            mark_done(doc_id, 0, str(e) or e.__class__.__name__)

    threading.Thread(target=_run, daemon=True).start()


__all__ = [
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "TOP_K_DEFAULT",
    "chunk_by_token",
    "embed_texts",
    "extract_text",
    "index_document",
    "delete_document_vectors",
    "retrieve",
    "index_in_background",
    "get_collection",
]
