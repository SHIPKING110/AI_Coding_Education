from collections.abc import Iterable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import security
from app.core.database import get_db
from app.crud import user as user_crud
from app.models.user import Role, User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = security.decode_token(credentials.credentials, expected_type="access")
        subject = payload.get("sub")
        if subject is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = user_crud.get_by_id(db, subject)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_roles(*roles: Role):
    """返回一个依赖，校验当前用户角色是否在允许集合内。"""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        allowed: Iterable[Role] = roles or Role
        if current_user.role not in {r.value for r in allowed}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return current_user

    return dependency


def require_teacher_permission(key: str, *, staff_allowed: bool = True):
    """教师操作权限校验：管理员直接放行；教务默认放行（staff_allowed=False 时除外）；
    教师按权限配置逐项校验。"""

    def dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        from app.models.permission import PERMISSION_KEYS, check

        if key not in PERMISSION_KEYS:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="未知权限键"
            )
        if current_user.role == Role.ADMIN.value:
            return current_user
        if current_user.role == Role.TEACHER.value:
            if not check(db, current_user, key):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="暂无该操作权限，请联系管理员开通")
            return current_user
        if not staff_allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return current_user

    return dependency
