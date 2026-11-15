"""媒体 URL 签名服务。

背景：/uploads/ 下文件必须携带短期签名才可读取（防匿名盗链）。
API 响应中的 /uploads/ 字符串由中间件自动补签名；但前端有些场景需要
「运行时拼路径」（如 PPT 文件名 → 下载链接），此时由本接口按需换取签名 URL。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.media import sign_media_path
from app.models.user import User

router = APIRouter(prefix="/media", tags=["media"])


class SignMediaIn(BaseModel):
    """待签名路径：/uploads/xxx 或相对名（自动补前缀）。"""

    path: str = Field(min_length=1, max_length=512)


@router.post("/sign")
def sign_media(
    payload: SignMediaIn,
    _: User = Depends(get_current_user),
) -> dict:
    """鉴权用户换取媒体签名的访问 URL（有效期见 MEDIA_URL_TTL_SECONDS）。"""
    path = payload.path.strip()
    if path.startswith("http://") or path.startswith("https://"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持站内素材路径")
    if not path.startswith("/uploads/"):
        path = f"/uploads/{path.lstrip('/')}"
    if ".." in path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法路径")
    return {"url": sign_media_path(path)}
