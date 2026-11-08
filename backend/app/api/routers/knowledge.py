"""RAG 知识库 API：上传 / 我的库 / 广场 / 收录。"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles, require_teacher_permission
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.crud import knowledge as kb_crud
from app.crud import notification as notif_crud
from app.models.notification import NotificationType
from app.models.user import Role, User
from app.services import rag

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

settings = get_settings()
ALLOWED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf", ".docx"}
MAX_BATCH_FILES = 10
MAX_UPLOAD_MB = 20
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


def _content_hash(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _doc_out(doc, *, collected: bool = False) -> dict:
    extra = doc.extra or {}
    return {
        "id": str(doc.id), "title": doc.title, "description": doc.description,
        "visibility": doc.visibility, "file_name": doc.file_name,
        "status": doc.status, "error": doc.error, "chunk_count": doc.chunk_count,
        "enabled": bool(getattr(doc, "enabled", True)),
        "visible_to_parents": bool(getattr(doc, "visible_to_parents", False)),
        "progress": extra.get("progress"),
        "collected": collected,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


def _mark_done(doc_id: uuid.UUID, chunk_count: int, error: str | None) -> None:
    db = _SESSION_FACTORY()
    try:
        kb_crud.mark_indexed(db, doc_id=doc_id, chunk_count=chunk_count, error=error)
        # 索引落定即发通知（成功/失败各一条，含文档标题）
        doc = kb_crud.get_document_any(db, doc_id=doc_id)
        if doc is not None:
            ok = error is None
            notif_crud.create(
                db, user_id=doc.owner_id, type=NotificationType.KNOWLEDGE_INDEXED.value,
                title=f"知识库文档「{doc.title}」索引{'完成' if ok else '失败'}",
                content=(
                    f"已切分为 {chunk_count} 块，可在对话中引用。"
                    if ok else f"失败原因：{error}，可在我的知识库中重新索引。"
                ),
                data={"doc_id": str(doc.id), "ok": ok},
            )
    finally:
        db.close()


def _mark_progress(doc_id: uuid.UUID, stage: str, percent: int, detail: str = "") -> None:
    db = _SESSION_FACTORY()
    try:
        kb_crud.mark_progress(db, doc_id=doc_id, stage=stage, percent=percent, detail=detail)
    finally:
        db.close()


# 后台索引线程的会话工厂（默认生产库；测试可替换为测试库会话工厂）
_SESSION_FACTORY = SessionLocal


def _save_upload(file: UploadFile) -> tuple[Path, str, int]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"暂不支持的文件类型（支持 txt/md/pdf/docx）：{suffix}",
        )
    kb_dir = Path(settings.UPLOAD_DIR) / "knowledge"
    kb_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{suffix}"
    dest = kb_dir / stored
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    size = dest.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {MAX_UPLOAD_MB}MB 上限：{file.filename or stored}",
        )
    return dest, suffix, size


def _create_document(
    db: Session,
    *,
    user: User,
    file_name: str,
    title: str,
    description: str,
    dest: Path,
    size: int,
    source_hash: str | None,
):
    doc = kb_crud.create_document(
        db, owner_id=user.id, title=title.strip(), description=description.strip(),
        file_name=file_name, file_path=str(dest),
    )
    doc.extra = {
        "source_hash": source_hash or "",
        "source_size": size,
        "original_name": file_name,
    }
    db.commit()
    db.refresh(doc)
    from app.services import llm_context as _llm_ctx

    rag.index_in_background(
        doc_id=doc.id, owner_id=user.id, title=doc.title,
        resolved=_llm_ctx.optional_resolved(db, user.id, "agent"),
        file_path=str(dest), file_name=file_name,
        mark_done=_mark_done, mark_progress=_mark_progress,
    )
    return doc


@router.post("/documents")
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("agent_doc_upload")),
) -> dict:
    """上传文档（标题必填，描述必填-广场工整性要求）：解析与向量化在后台进行。"""
    if not (title or "").strip():
        raise HTTPException(status_code=422, detail="请填写标题")
    if not (description or "").strip():
        raise HTTPException(status_code=422, detail="请填写描述")
    dest, _suffix, size = _save_upload(file)
    file_name = file.filename or dest.name
    doc = _create_document(
        db, user=user, file_name=file_name, title=title,
        description=description, dest=dest, size=size,
        source_hash=_content_hash(dest),
    )
    return _doc_out(doc)


def _parse_meta_list(raw: str, *, label: str) -> list[str]:
    if not (raw or "").strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail=f"{label} 必须是 JSON 字符串数组")
    if not isinstance(data, list):
        raise HTTPException(status_code=422, detail=f"{label} 必须是 JSON 字符串数组")
    return [str(x).strip() for x in data]


@router.post("/documents/bulk")
def upload_documents_bulk(
    files: list[UploadFile] = File(...),
    description: str = Form(default=""),
    titles: str = Form(default=""),
    descriptions: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("agent_doc_upload")),
) -> dict:
    """批量上传文档（单批最多 10 个，单文件 ≤ 20MB）。

    - `titles` / `descriptions` 可传与 files 对齐的 JSON 字符串数组，缺省用文件名/共享描述；
    - 同内容（SHA-256 相同）文档自动跳过，避免重复向量化消耗 Token；
    - 单文件失败不影响其余文件，返回 created / skipped / failed 明细。
    """
    if not files:
        raise HTTPException(status_code=422, detail="请选择要上传的文件")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=f"单次最多上传 {MAX_BATCH_FILES} 个文件")
    parsed_titles = _parse_meta_list(titles, label="titles")
    parsed_descs = _parse_meta_list(descriptions, label="descriptions")
    shared_desc = (description or "").strip()

    existing_hashes = {
        str((d.extra or {}).get("source_hash") or "")
        for d in kb_crud.list_my_documents(db, owner_id=user.id)
    }
    created: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    for idx, file in enumerate(files):
        file_name = file.filename or f"file-{idx + 1}"
        title = (parsed_titles[idx] if idx < len(parsed_titles) else "") or Path(file_name).stem
        desc = (parsed_descs[idx] if idx < len(parsed_descs) else "") or shared_desc
        if not title.strip():
            failed.append({"file": file_name, "error": "标题不能为空"})
            continue
        if not desc.strip():
            failed.append({"file": file_name, "error": "请填写描述（或为本批文件提供共享描述）"})
            continue
        dest: Path | None = None
        try:
            dest, _suffix, size = _save_upload(file)
            source_hash = _content_hash(dest)
            if source_hash and source_hash in existing_hashes:
                dest.unlink(missing_ok=True)
                skipped.append({"file": file_name, "reason": "已存在相同内容文档"})
                continue
            doc = _create_document(
                db, user=user, file_name=file_name, title=title,
                description=desc, dest=dest, size=size, source_hash=source_hash,
            )
            if source_hash:
                existing_hashes.add(source_hash)
            created.append(_doc_out(doc))
        except HTTPException as exc:
            if dest is not None:
                dest.unlink(missing_ok=True)
            failed.append({"file": file_name, "error": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001 —— 单文件失败不阻断整批
            if dest is not None:
                dest.unlink(missing_ok=True)
            failed.append({"file": file_name, "error": str(exc)[:200]})
    return {
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "counts": {"created": len(created), "skipped": len(skipped), "failed": len(failed)},
    }


@router.post("/documents/describe")
def describe_document(
    file: UploadFile = File(...),
    config_id: str = Form(default=""),
    title: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(require_teacher_permission("agent_doc_upload")),
) -> dict:
    """根据文档内容生成一句广场描述，供批量上传前预览/编辑。

    `config_id` 为教师已配置的模型 ID；调用会计入「用量与成本」。
    """
    dest, _suffix, _size = _save_upload(file)
    try:
        text = rag.extract_text(str(dest), file.filename or "")
    except Exception as exc:  # noqa: BLE001 —— 解析失败按 422 返回，前端可提示换文件
        raise HTTPException(status_code=422, detail=f"文档解析失败：{exc}") from exc
    finally:
        dest.unlink(missing_ok=True)

    body = (text or "").strip()
    if not body:
        raise HTTPException(status_code=422, detail="文档没有可解析的文本，无法生成描述")

    from app.services import llm, llm_context

    doc_title = (title or "").strip() or Path(file.filename or "").stem or "未命名文档"
    system = (
        "你是知识库编目助手。请根据文档标题和正文，生成一段 40～80 字的中文描述，"
        "概括文档主题、适用场景和关键内容。只依据给定内容，不编造；"
        "不要使用 Markdown，不要分点，不要加引号。"
    )
    prompt = (
        f"标题：{doc_title}\n\n"
        f"正文节选：\n{body[:6000]}\n\n"
        "请输出一段可直接展示在知识库广场的描述。"
    )
    try:
        resolved = llm_context.resolve_override(
            db, user.id, "knowledge" if config_id.strip() else "agent", config_id.strip() or None
        )
        with llm_context.use_llm(resolved):
            description = llm.invoke_text(system, prompt, temperature=0.2, timeout=60)
    except Exception as exc:  # noqa: BLE001 —— 统一转成前端可读的 400
        raise HTTPException(status_code=400, detail=str(exc) or "生成描述失败") from exc

    description = " ".join((description or "").split()).strip().strip('"“”')
    if not description:
        raise HTTPException(status_code=502, detail="模型没有返回有效描述，请重试或换一个模型")
    return {
        "description": description[:500],
        "model": resolved.model,
        "config_name": resolved.config_name,
    }


@router.get("/documents")
def my_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    docs = kb_crud.list_my_documents(db, owner_id=user.id)
    collected = set(kb_crud.collected_doc_ids(db, user_id=user.id))
    return {"items": [_doc_out(d, collected=(d.id in collected)) for d in docs]}


@router.post("/documents/{doc_id}/retry")
def retry_index(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """索引失败后重试：复用已存文件重新解析入库（不用重新上传）。"""
    doc = kb_crud.get_document(db, doc_id=doc_id, owner_id=user.id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.status == "ready":
        return _doc_out(doc)
    if not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(status_code=400, detail="源文件已丢失，请删除后重新上传")
    doc = kb_crud.mark_indexing(db, doc)
    from app.services import llm_context as _llm_ctx2

    rag.index_in_background(
        doc_id=doc.id, owner_id=user.id, title=doc.title,
        resolved=_llm_ctx2.optional_resolved(db, user.id, "agent"),
        file_path=doc.file_path, file_name=doc.file_name or "",
        mark_done=_mark_done, mark_progress=_mark_progress,
    )
    if getattr(doc, "visible_to_parents", False):
        rag.start_parent_index_sync()
    return _doc_out(doc)


@router.post("/documents/{doc_id}/publish")
def publish_to_plaza(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    doc = kb_crud.get_document(db, doc_id=doc_id, owner_id=user.id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.status != "ready":
        raise HTTPException(status_code=400, detail="文档尚未索引完成，暂不能发布")
    return _doc_out(kb_crud.set_visibility(db, doc, "plaza"))


@router.post("/documents/{doc_id}/unpublish")
def unpublish_from_plaza(
    doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    doc = kb_crud.get_document(db, doc_id=doc_id, owner_id=user.id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _doc_out(kb_crud.set_visibility(db, doc, "private"))


@router.post("/documents/{doc_id}/toggle-search")
def toggle_searchable(
    doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """检索开关：关闭后该文档不再参与 RAG（向量保留，重开即用，免重建）。"""
    doc = kb_crud.get_document(db, doc_id=doc_id, owner_id=user.id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _doc_out(kb_crud.set_enabled(db, doc, not bool(getattr(doc, "enabled", True))))


@router.post("/documents/{doc_id}/toggle-parent")
def toggle_parent_visible(
    doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """家长版可见开关：开=该文档参与家长客服 RAG；关=对家长隐藏（默认隐藏）。"""
    doc = kb_crud.get_document(db, doc_id=doc_id, owner_id=user.id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    visible = not bool(getattr(doc, "visible_to_parents", False))
    doc = kb_crud.set_parent_visible(db, doc, visible)
    if visible:
        rag.start_parent_index_sync()
    else:
        rag.delete_document_vectors(doc.id, parent=True)
    return _doc_out(doc)


@router.delete("/documents/{doc_id}")
def remove_document(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    doc = kb_crud.get_document(db, doc_id=doc_id, owner_id=user.id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    rag.delete_document_vectors(doc.id)
    rag.delete_document_vectors(doc.id, parent=True)
    try:
        Path(doc.file_path).unlink(missing_ok=True)
    except OSError:
        pass
    kb_crud.delete_document(db, doc)
    return {"ok": True}


@router.get("/plaza")
def plaza(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    docs = kb_crud.list_plaza(db)
    collected = set(kb_crud.collected_doc_ids(db, user_id=user.id))
    items = []
    for d in docs:
        item = _doc_out(d, collected=(d.id in collected))
        item["mine"] = d.owner_id == user.id
        items.append(item)
    return {"items": items}


@router.post("/plaza/{doc_id}/collect")
def collect(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    doc = kb_crud.get_document_any(db, doc_id=doc_id)
    if doc is None or doc.visibility != "plaza" or doc.status != "ready":
        raise HTTPException(status_code=404, detail="广场文档不存在或未就绪")
    if doc.owner_id == user.id:
        return {"ok": True, "mine": True}
    if not kb_crud.is_collected(db, user_id=user.id, doc_id=doc.id):
        kb_crud.collect(db, user_id=user.id, doc_id=doc.id)
    return {"ok": True}


@router.delete("/plaza/{doc_id}/collect")
def uncollect(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    kb_crud.uncollect(db, user_id=user.id, doc_id=doc_id)
    return {"ok": True}


# —— 运维：僵尸向量清理（管理员）——

@router.post("/maintenance/sweep-orphans")
def sweep_orphans(
    dry_run: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """清理僵尸向量：源文档已删除但向量库残留的分片（过时信息会污染回答）。

    dry_run=True 仅统计不删除。返回扫描分片数 / 僵尸文档数 / 已删除分片数。
    """
    from app.services import rag as rag_svc

    return rag_svc.sweep_orphan_vectors(db, delete=not dry_run)


@router.get("/maintenance/collections")
def knowledge_collections(_: User = Depends(require_roles(Role.ADMIN))) -> dict:
    """列出所有知识库向量集合（含历史 embedding 分片），便于运维查看。"""
    from app.services import rag as rag_svc

    return {"active": rag_svc._collection_name(), "collections": rag_svc.list_knowledge_collections()}


@router.get("/maintenance/metrics")
def knowledge_metrics(_: User = Depends(require_roles(Role.ADMIN))) -> dict:
    """检索运行指标：命中率/零结果率/平均时延/降级与 rerank 次数。

    零结果率上升、平均时延恶化 = 检索效果或链路出现滑坡的先行信号。
    """
    from app.services import rag as rag_svc

    return rag_svc.get_metrics_snapshot()


@router.post("/maintenance/sync")
def trigger_sync(
    limit: int = 50,
    _: User = Depends(require_roles(Role.ADMIN)),
) -> dict:
    """手动触发一次增量同步（日常由后台定时任务执行，此处用于即时排障）。"""
    from app.services import rag as rag_svc

    return rag_svc.sync_changed_documents(limit=limit)
