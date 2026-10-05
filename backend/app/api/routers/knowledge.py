"""RAG 知识库 API：上传 / 我的库 / 广场 / 收录。"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.crud import knowledge as kb_crud
from app.crud import notification as notif_crud
from app.models.notification import NotificationType
from app.models.user import User
from app.services import rag

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

settings = get_settings()
ALLOWED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf", ".docx"}


def _doc_out(doc, *, collected: bool = False) -> dict:
    extra = doc.extra or {}
    return {
        "id": str(doc.id), "title": doc.title, "description": doc.description,
        "visibility": doc.visibility, "file_name": doc.file_name,
        "status": doc.status, "error": doc.error, "chunk_count": doc.chunk_count,
        "enabled": bool(getattr(doc, "enabled", True)),
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


@router.post("/documents")
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """上传文档（标题必填，描述必填-广场工整性要求）：解析与向量化在后台进行。"""
    if not (title or "").strip():
        raise HTTPException(status_code=422, detail="请填写标题")
    if not (description or "").strip():
        raise HTTPException(status_code=422, detail="请填写描述")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"暂不支持的文件类型（支持 txt/md/pdf/docx）：{suffix}")

    kb_dir = Path(settings.UPLOAD_DIR) / "knowledge"
    kb_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{suffix}"
    dest = kb_dir / stored
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    doc = kb_crud.create_document(
        db, owner_id=user.id, title=title.strip(), description=description.strip(),
        file_name=file.filename or stored, file_path=str(dest),
    )
    from app.services import llm_context as _llm_ctx

    rag.index_in_background(
        doc_id=doc.id, owner_id=user.id, title=doc.title,
        resolved=_llm_ctx.optional_resolved(db, user.id, "agent"),
        file_path=str(dest), file_name=file.filename or stored,
        mark_done=_mark_done, mark_progress=_mark_progress,
    )
    return _doc_out(doc)


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
    rag.index_in_background(
        doc_id=doc.id, owner_id=user.id, title=doc.title,
        file_path=doc.file_path, file_name=doc.file_name or "",
        mark_done=_mark_done, mark_progress=_mark_progress,
    )
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


@router.delete("/documents/{doc_id}")
def remove_document(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    doc = kb_crud.get_document(db, doc_id=doc_id, owner_id=user.id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    rag.delete_document_vectors(doc.id)
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
