"""教师自配模型：CRUD + 模块映射 + 连通性检查。密钥只进不出（列表脱敏）。"""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.secretbox import decrypt_secret
from app.crud import llm_config as crud
from app.models.llm_config import LLM_MODULES
from app.models.user import Role, User

router = APIRouter(prefix="/llm-configs", tags=["llm-configs"])

TEACH_ROLES = (Role.ADMIN.value, Role.STAFF.value, Role.TEACHER.value)


class LLMConfigIn(BaseModel):
    name: str
    base_url: str
    api_key: str
    model: str
    embed_model: str | None = None
    make_default: bool = False


class LLMConfigUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    embed_model: str | None = None
    make_default: bool | None = None


def _out(cfg, masked_key: str = "***") -> dict:
    return {
        "id": str(cfg.id),
        "name": cfg.name,
        "base_url": cfg.base_url,
        "api_key_masked": masked_key,
        "model": cfg.model,
        "embed_model": cfg.embed_model,
        "is_default": cfg.is_default,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


def _owned(db: Session, config_id: uuid.UUID, user: User):
    cfg = crud.get_config(db, config_id)
    if cfg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配置不存在")
    if user.role != Role.ADMIN.value and cfg.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能操作自己的模型配置")
    return cfg


@router.get("")
def list_my_configs(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    _require_role(user)
    return {"items": [_out(c) for c in crud.list_configs(db, user.id)], "modules": list(LLM_MODULES)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_config(
    payload: LLMConfigIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_role(user)
    _validate(payload)
    try:
        cfg = crud.create_config(
            db,
            owner_id=user.id,
            name=payload.name,
            base_url=payload.base_url,
            api_key=payload.api_key,
            model=payload.model,
            embed_model=payload.embed_model,
            make_default=payload.make_default,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _out(cfg)


@router.patch("/{config_id}")
def update_config(
    config_id: uuid.UUID,
    payload: LLMConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_role(user)
    cfg = _owned(db, config_id, user)
    try:
        cfg = crud.update_config(
            db,
            cfg,
            name=payload.name,
            base_url=payload.base_url,
            api_key=payload.api_key,
            model=payload.model,
            embed_model=payload.embed_model,
            make_default=payload.make_default,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _out(cfg)


@router.delete("/{config_id}")
def delete_config(
    config_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_role(user)
    cfg = _owned(db, config_id, user)
    crud.delete_config(db, cfg)
    return {"deleted": True}


@router.post("/{config_id}/test")
def test_config(
    config_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """连通性检查：用该配置调一次最小对话，返回延迟；失败返回可读原因。"""
    from app.crud import llm_config as _crud
    from app.services import llm as llm_svc

    _require_role(user)
    cfg = _owned(db, config_id, user)
    resolved = _crud.ResolvedLLM(
        base_url=cfg.base_url,
        api_key=decrypt_secret(cfg.api_key_enc),
        model=cfg.model,
        embed_model=cfg.embed_model,
        config_id=cfg.id,
        config_name=cfg.name,
    )
    started = time.time()
    try:
        reply = llm_svc.ping(resolved)
    except Exception as exc:
        return {"ok": False, "error": llm_svc.friendly_llm_error(exc)}
    return {"ok": True, "latency_ms": int((time.time() - started) * 1000), "reply": reply[:200]}


@router.get("/modules/mapping")
def get_module_mapping(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    _require_role(user)
    mapping = crud.get_mapping(db, user.id)
    return {"mapping": {m: (str(v) if v else None) for m, v in mapping.items()}}


class ModuleMappingIn(BaseModel):
    mapping: dict[str, str | None]


@router.put("/modules/mapping")
def set_module_mapping(
    payload: ModuleMappingIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_role(user)
    cleaned: dict[str, uuid.UUID | None] = {}
    for module, cid in payload.mapping.items():
        if module not in LLM_MODULES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"未知模块：{module}"
            )
        cleaned[module] = uuid.UUID(cid) if cid else None
    try:
        mapping = crud.set_mapping(db, user.id, cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"mapping": {m: (str(v) if v else None) for m, v in mapping.items()}}


def _require_role(user: User) -> None:
    if user.role not in TEACH_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权配置模型")


def _validate(payload: LLMConfigIn) -> None:
    if not payload.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="配置名称不能为空")
    if not payload.base_url.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="接口地址不能为空")
    if not payload.api_key.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API Key 不能为空")
    if not payload.model.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="模型名称不能为空")
