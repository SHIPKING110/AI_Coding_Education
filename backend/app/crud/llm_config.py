"""教师自配模型 CRUD + 模块映射 + 连通性检查。"""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.secretbox import decrypt_secret, encrypt_secret
from app.models.llm_config import LLM_MODULES, TeacherLLMConfig, TeacherModuleModel


@dataclass
class ResolvedLLM:
    base_url: str
    api_key: str
    model: str
    embed_model: str | None
    config_id: uuid.UUID | None
    config_name: str | None


def list_configs(db: Session, owner_id: uuid.UUID) -> list[TeacherLLMConfig]:
    return list(
        db.scalars(
            select(TeacherLLMConfig)
            .where(TeacherLLMConfig.owner_id == owner_id)
            .order_by(TeacherLLMConfig.is_default.desc(), TeacherLLMConfig.created_at)
        ).all()
    )


def get_config(db: Session, config_id: uuid.UUID) -> TeacherLLMConfig | None:
    return db.get(TeacherLLMConfig, config_id)


def create_config(
    db: Session,
    *,
    owner_id: uuid.UUID,
    name: str,
    base_url: str,
    api_key: str,
    model: str,
    embed_model: str | None = None,
    make_default: bool = False,
) -> TeacherLLMConfig:
    cfg = TeacherLLMConfig(
        owner_id=owner_id,
        name=name.strip(),
        base_url=_normalize_base_url(base_url),
        api_key_enc=encrypt_secret(api_key.strip()),
        model=model.strip(),
        embed_model=(embed_model or "").strip() or None,
        is_default=make_default,
    )
    db.add(cfg)
    db.flush()
    if make_default:
        _set_default(db, owner_id, cfg.id)
    elif db.scalar(
        select(TeacherLLMConfig.id).where(
            TeacherLLMConfig.owner_id == owner_id, TeacherLLMConfig.is_default.is_(True)
        )
    ) is None:
        _set_default(db, owner_id, cfg.id)
    db.commit()
    db.refresh(cfg)
    return cfg


def update_config(
    db: Session,
    cfg: TeacherLLMConfig,
    *,
    name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    embed_model: str | None = None,
    make_default: bool | None = None,
) -> TeacherLLMConfig:
    if name is not None:
        cfg.name = name.strip()
    if base_url is not None:
        cfg.base_url = _normalize_base_url(base_url)
    if api_key is not None and api_key.strip():
        cfg.api_key_enc = encrypt_secret(api_key.strip())
    if model is not None:
        cfg.model = model.strip()
    if embed_model is not None:
        cfg.embed_model = (embed_model or "").strip() or None
    if make_default:
        _set_default(db, cfg.owner_id, cfg.id)
    db.commit()
    db.refresh(cfg)
    return cfg


def delete_config(db: Session, cfg: TeacherLLMConfig) -> bool:
    """删除配置；是默认时自动把最早的另一个顶为默认。返回是否删掉了默认。"""
    was_default = cfg.is_default
    db.execute(
        delete(TeacherModuleModel).where(
            TeacherModuleModel.owner_id == cfg.owner_id,
            TeacherModuleModel.config_id == cfg.id,
        )
    )
    db.delete(cfg)
    db.flush()
    if was_default:
        nxt = db.scalar(
            select(TeacherLLMConfig.id)
            .where(TeacherLLMConfig.owner_id == cfg.owner_id)
            .order_by(TeacherLLMConfig.created_at)
            .limit(1)
        )
        if nxt is not None:
            _set_default(db, cfg.owner_id, nxt)
    db.commit()
    return was_default


def _set_default(db: Session, owner_id: uuid.UUID, config_id: uuid.UUID) -> None:
    for c in list_configs(db, owner_id):
        c.is_default = c.id == config_id
    db.flush()


def _normalize_base_url(url: str) -> str:
    base = (url or "").strip().rstrip("/")
    if base and not base.endswith("/v1"):
        base += "/v1"
    return base


def get_mapping(db: Session, owner_id: uuid.UUID) -> dict[str, uuid.UUID | None]:
    rows = db.scalars(
        select(TeacherModuleModel).where(TeacherModuleModel.owner_id == owner_id)
    ).all()
    return {r.module: r.config_id for r in rows}


def set_mapping(
    db: Session, owner_id: uuid.UUID, mapping: dict[str, uuid.UUID | None]
) -> dict[str, uuid.UUID | None]:
    for module, config_id in mapping.items():
        if module not in LLM_MODULES:
            continue
        if config_id is not None:
            cfg = get_config(db, config_id)
            if cfg is None or cfg.owner_id != owner_id:
                raise ValueError(f"模块 {module} 指向的配置不存在或不属于你")
        row = db.get(TeacherModuleModel, {"owner_id": owner_id, "module": module})
        if row is None:
            row = TeacherModuleModel(owner_id=owner_id, module=module, config_id=config_id)
            db.add(row)
        else:
            row.config_id = config_id
    db.commit()
    return get_mapping(db, owner_id)


def resolve(db: Session, owner_id: uuid.UUID, module: str) -> ResolvedLLM | None:
    """解析某教师某模块用的模型：模块映射 → 个人默认 → 全局环境变量。"""
    from app.core.config import get_settings

    cfg: TeacherLLMConfig | None = None
    if module in LLM_MODULES:
        row = db.get(TeacherModuleModel, {"owner_id": owner_id, "module": module})
        if row is not None and row.config_id is not None:
            cand = get_config(db, row.config_id)
            if cand is not None and cand.owner_id == owner_id:
                cfg = cand
    if cfg is None:
        cfg = db.scalar(
            select(TeacherLLMConfig)
            .where(TeacherLLMConfig.owner_id == owner_id, TeacherLLMConfig.is_default.is_(True))
            .limit(1)
        )
    if cfg is not None:
        return ResolvedLLM(
            base_url=cfg.base_url,
            api_key=decrypt_secret(cfg.api_key_enc),
            model=cfg.model,
            embed_model=cfg.embed_model,
            config_id=cfg.id,
            config_name=cfg.name,
        )
    settings = get_settings()
    if (settings.LLM_API_KEY or "").strip():
        return ResolvedLLM(
            base_url=_normalize_base_url(settings.LLM_BASE_URL or ""),
            api_key=settings.LLM_API_KEY.strip(),
            model=settings.LLM_MODEL,
            # 系统级 embedding：.env 配了则 RAG 直接可用，否则沿用教师自配
            embed_model=(settings.LLM_EMBED_MODEL or "").strip() or None,
            config_id=None,
            config_name="系统默认",
        )
    return None
