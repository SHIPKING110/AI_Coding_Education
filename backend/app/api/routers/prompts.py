import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.crud import prompt as prompt_crud
from app.models.prompt import PromptScope
from app.models.user import Role, User
from app.schemas.prompt import PromptTemplateCreate, PromptTemplateOut, PromptTemplateUpdate

router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])

# 模板管理：admin/staff/teacher 可使用（家长/学员无反馈模块）
MANAGE_ROLES = (Role.ADMIN, Role.STAFF, Role.TEACHER)


def _to_out(t) -> PromptTemplateOut:
    out = PromptTemplateOut.model_validate(t)
    if t.owner:
        out.owner_name = t.owner.name
    return out


@router.get("", response_model=list[PromptTemplateOut])
def list_prompt_templates(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
    scene: str | None = Query(default=None, pattern="^(feedback|report|evaluation)$"),
) -> list[PromptTemplateOut]:
    """当前用户可见的提示词模板。

    普通用户：system + published + 本人 personal（账号隔离）；
    管理员：额外可见全部 personal（便于管理/发布优秀模板）。
    scene 按使用场景过滤（feedback/report/evaluation），不传则全量。
    """
    # 系统预设幂等补齐：保证报告/反馈五套自带提示词始终存在
    prompt_crud.ensure_system_presets(db)
    items = prompt_crud.list_visible(db, user.id, is_admin=user.role == Role.ADMIN.value)
    if scene:
        items = [t for t in items if (t.scene or "feedback") == scene]
    return [_to_out(t) for t in items]


@router.post("", response_model=PromptTemplateOut, status_code=status.HTTP_201_CREATED)
def create_prompt_template(
    payload: PromptTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
) -> PromptTemplateOut:
    """新建个人自定义模板（scope=personal，账号隔离）。"""
    return _to_out(
        prompt_crud.create(
            db,
            name=payload.name,
            content=payload.content,
            scope=PromptScope.PERSONAL,
            owner_id=user.id,
            scene=payload.scene,
        )
    )


@router.patch("/{template_id}", response_model=PromptTemplateOut)
def update_prompt_template(
    template_id: uuid.UUID,
    payload: PromptTemplateUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
) -> PromptTemplateOut:
    """编辑模板：personal 仅 owner；system/published 仅管理员。"""
    t = prompt_crud.get(db, template_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    is_admin = user.role == Role.ADMIN.value
    if t.scope == PromptScope.SYSTEM.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="系统内置模板不可删除，仅可编辑修改",
        )
    if t.scope == PromptScope.PERSONAL.value and not (is_admin or t.owner_id == user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权编辑他人的个人模板")
    if t.scope in (PromptScope.SYSTEM.value, PromptScope.PUBLISHED.value) and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可编辑该模板")
    return _to_out(prompt_crud.update(db, t, name=payload.name, content=payload.content))


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
) -> None:
    """删除模板：personal 仅 owner；system/published 仅管理员。"""
    t = prompt_crud.get(db, template_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    is_admin = user.role == Role.ADMIN.value
    if t.scope == PromptScope.PERSONAL.value and not (is_admin or t.owner_id == user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除他人的个人模板")
    if t.scope in (PromptScope.SYSTEM.value, PromptScope.PUBLISHED.value) and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可删除该模板")
    prompt_crud.delete(db, t)


@router.post("/{template_id}/publish", response_model=PromptTemplateOut)
def publish_prompt_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> PromptTemplateOut:
    """管理员发布模板（personal → published），全校教师可用。"""
    t = prompt_crud.get(db, template_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    if t.scope == PromptScope.SYSTEM.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="系统内置模板无需发布")
    return _to_out(prompt_crud.set_scope(db, t, PromptScope.PUBLISHED))


@router.post("/{template_id}/unpublish", response_model=PromptTemplateOut)
def unpublish_prompt_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.ADMIN)),
) -> PromptTemplateOut:
    """管理员取消发布（published → personal，仅创建者保留）。"""
    t = prompt_crud.get(db, template_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模板不存在")
    if t.scope != PromptScope.PUBLISHED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="仅已发布模板可取消发布"
        )
    return _to_out(prompt_crud.set_scope(db, t, PromptScope.PERSONAL))
