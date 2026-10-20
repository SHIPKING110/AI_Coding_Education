"""RAG 知识库 CRUD：文档 / 收录。"""

from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeCollection, KnowledgeDocument


def create_document(
    db: Session, *, owner_id, title: str, description: str = "",
    file_name: str = "", file_path: str = "",
) -> KnowledgeDocument:
    doc = KnowledgeDocument(
        owner_id=owner_id, title=title.strip() or "未命名文档",
        description=description or "", file_name=file_name, file_path=file_path,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def get_document(db: Session, *, doc_id, owner_id=None) -> KnowledgeDocument | None:
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    if owner_id is not None:
        stmt = stmt.where(KnowledgeDocument.owner_id == owner_id)
    return db.scalars(stmt).first()


def get_document_any(db: Session, *, doc_id) -> KnowledgeDocument | None:
    return db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)).first()


def list_my_documents(db: Session, *, owner_id) -> list[KnowledgeDocument]:
    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.owner_id == owner_id
    ).order_by(desc(KnowledgeDocument.created_at))
    return list(db.scalars(stmt).all())


def list_plaza(db: Session, *, limit: int = 50) -> list[KnowledgeDocument]:
    stmt = (
        select(KnowledgeDocument)
        .where(KnowledgeDocument.visibility == "plaza", KnowledgeDocument.status == "ready")
        .order_by(desc(KnowledgeDocument.updated_at))
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def set_visibility(db: Session, doc: KnowledgeDocument, visibility: str) -> KnowledgeDocument:
    doc.visibility = visibility
    db.commit()
    db.refresh(doc)
    return doc


def set_enabled(db: Session, doc: KnowledgeDocument, enabled: bool) -> KnowledgeDocument:
    """检索开关：关闭后该文档切块不再参与任何 RAG 检索（向量保留，重开即用）。"""
    doc.enabled = enabled
    db.commit()
    db.refresh(doc)
    return doc


def set_parent_visible(db: Session, doc: KnowledgeDocument, visible: bool) -> KnowledgeDocument:
    """家长版开关：仅 visible_to_parents=true 的文档参与家长端 RAG（白名单制）。"""
    doc.visible_to_parents = visible
    db.commit()
    db.refresh(doc)
    return doc


def usable_doc_ids(db: Session, *, doc_ids: list[str]) -> set[str]:
    """候选 doc_id 中可参与检索的：存在 + 已就绪 + 开关打开。"""
    uniq = {str(d) for d in doc_ids if d}
    if not uniq:
        return set()
    rows = db.scalars(
        select(KnowledgeDocument.id).where(
            KnowledgeDocument.status == "ready",
            KnowledgeDocument.enabled.is_(True),
        )
    ).all()
    ready = {str(r) for r in rows}
    return uniq & ready


def all_document_ids(db: Session) -> list[str]:
    """数据库中仍存在的全部文档 id（含未就绪/停用）——用于僵尸向量清理比对。"""
    rows = db.scalars(select(KnowledgeDocument.id)).all()
    return [str(r) for r in rows]


def mark_indexing(db: Session, doc: KnowledgeDocument) -> KnowledgeDocument:
    """重试索引：回到 pending，清空旧错误。"""
    doc.status = "pending"
    doc.error = None
    db.commit()
    db.refresh(doc)
    return doc


def mark_progress(db: Session, *, doc_id, stage: str, percent: int, detail: str = "") -> None:
    """索引进度跟踪：写入 extra.progress，前端轮询展示（解析→切块→向量化→入库）。"""
    doc = get_document_any(db, doc_id=doc_id)
    if doc is None:
        return
    extra = dict(doc.extra or {})
    extra["progress"] = {"stage": stage, "percent": max(0, min(100, percent)), "detail": detail}
    doc.extra = extra
    db.commit()


def mark_indexed(db: Session, *, doc_id, chunk_count: int, error: str | None = None) -> None:
    doc = get_document_any(db, doc_id=doc_id)
    if doc is None:
        return
    doc.status = "ready" if error is None else "failed"
    doc.error = error
    doc.chunk_count = chunk_count
    extra = dict(doc.extra or {})
    extra.pop("progress", None)
    doc.extra = extra
    db.commit()


def delete_document(db: Session, doc: KnowledgeDocument) -> None:
    db.delete(doc)
    db.commit()


def mark_failed(db: Session, doc: KnowledgeDocument, error: str) -> None:
    """将文档标记为失败（用于增量同步时源文件丢失等场景）。"""
    doc.status = "failed"
    doc.error = error
    doc.extra = {k: v for k, v in dict(doc.extra or {}).items() if k != "progress"}
    db.commit()


def list_all_documents(db: Session, *, limit: int = 1000) -> list[KnowledgeDocument]:
    """全部文档（含未就绪/停用）——供增量同步扫描。按更新时间升序，优先处理旧的。"""
    return list(
        db.scalars(
            select(KnowledgeDocument)
            .order_by(KnowledgeDocument.updated_at.asc())
            .limit(limit)
        ).all()
    )


def collected_doc_ids(db: Session, *, user_id) -> list[uuid.UUID]:
    stmt = select(KnowledgeCollection.doc_id).where(KnowledgeCollection.user_id == user_id)
    return list(db.scalars(stmt).all())


def is_collected(db: Session, *, user_id, doc_id) -> bool:
    stmt = select(KnowledgeCollection).where(
        KnowledgeCollection.user_id == user_id, KnowledgeCollection.doc_id == doc_id
    )
    return db.scalars(stmt).first() is not None


def collect(db: Session, *, user_id, doc_id) -> KnowledgeCollection:
    row = KnowledgeCollection(user_id=user_id, doc_id=doc_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def uncollect(db: Session, *, user_id, doc_id) -> bool:
    stmt = select(KnowledgeCollection).where(
        KnowledgeCollection.user_id == user_id, KnowledgeCollection.doc_id == doc_id
    )
    row = db.scalars(stmt).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


__all__ = [
    "create_document", "get_document", "get_document_any", "list_my_documents",
    "list_plaza", "set_visibility", "mark_indexed", "delete_document",
    "collected_doc_ids", "is_collected", "collect", "uncollect",
]
