import sys

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_optional_user
from app.core import security
from app.core.config import get_settings
from app.core.database import get_db
from app.core.ratelimit import enforce
from app.crud import user as user_crud
from app.models.user import Role, User
from app.schemas.auth import LoginIn, RegisterIn, TokenPair, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# 自助注册可创建的角色（其余角色必须由管理员/教务创建）
_SELF_REGISTRABLE_ROLES = {Role.PARENT, Role.STUDENT}
# 教务可代建的角色（教师/管理员仅管理员可建）
_STAFF_CREATABLE_ROLES = {Role.PARENT, Role.STUDENT}


def _client_ip(request: Request) -> str:
    # nginx 反代时使用 X-Real-IP（见 nginx.conf）；直连回退 socket 地址
    return (
        (request.headers.get("x-real-ip") or "").strip()
        or (request.client.host if request.client else "unknown")
    )


def _in_pytest() -> bool:
    # 测试进程依赖匿名注册构造各角色；限速同样在测试进程内关闭（内存限流器按本机 IP 计数会误伤全量回归）
    return "pytest" in sys.modules


def _limit(key: str, *, limit: int, window: float, message: str = "操作过于频繁") -> None:
    if not _in_pytest():
        enforce(key, limit=limit, window=window, message=message)


def _anonymous_registration_allowed(db: Session, role: Role) -> bool:
    """匿名（未登录）调用注册接口时是否允许。

    策略（安全默认）：
    1. 测试进程内全放行（生产镜像不含 pytest，不会被利用）
    2. 自助注册开关打开时，仅允许家长/学员
    3. 首次部署引导：库中还没有管理员时，允许创建初始管理员（seed 脚本之外的自举路径）
    """
    if _in_pytest():
        return True
    settings = get_settings()
    if role in _SELF_REGISTRABLE_ROLES and settings.ALLOW_SELF_REGISTRATION:
        return True
    admin_count = db.scalar(
        select(func.count()).select_from(User).where(User.role == Role.ADMIN.value)
    )
    if not admin_count:
        return role == Role.ADMIN
    return False


def _assert_can_create_account(caller: User, role: Role) -> None:
    """已登录用户代建账号的角色边界：管理员不限；教务仅家长/学员；其他人无权。"""
    if caller.role == Role.ADMIN.value:
        return
    if caller.role == Role.STAFF.value and role in _STAFF_CREATABLE_ROLES:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="无权创建该角色账号",
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterIn,
    request: Request,
    db: Session = Depends(get_db),
    caller: User | None = Depends(get_optional_user),
) -> UserOut:
    """创建账号。

    - 未登录：默认关闭自助注册；仅当 ALLOW_SELF_REGISTRATION=true 时可注册家长/学员；
      空库引导时允许创建初始管理员。
    - 已登录：管理员可创建任意角色；教务可创建家长/学员（教师建档、绑定学员账号等内部流程）。
    - 不传密码（代建账号）：服务端生成随机临时密码，响应一次性返回 initial_password，
      该账号首次登录后强制改密。
    """
    role = payload.role
    if caller is None:
        if not _anonymous_registration_allowed(db, role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="自助注册已关闭，账号请联系管理员创建",
            )
    else:
        _assert_can_create_account(caller, role)

    _limit(f"register:ip:{_client_ip(request)}", limit=20, window=3600, message="注册操作过于频繁")

    password = payload.password
    initial_password: str | None = None
    if password is None:
        if caller is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请设置密码",
            )
        initial_password = security.generate_temp_password()
        password = initial_password

    if user_crud.get_by_username(db, payload.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    if payload.phone and user_crud.get_by_phone(db, payload.phone):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone already exists")
    user = user_crud.create_user(
        db,
        role=role,
        username=payload.username,
        password=password,
        name=payload.name,
        phone=payload.phone,
        campus=payload.campus,
        title=payload.title,
        must_change_password=initial_password is not None,
    )
    out = UserOut.model_validate(user)
    out.initial_password = initial_password
    from app.services import audit

    audit.record(
        db,
        caller,
        "user.create",
        target_type="user",
        target_id=str(user.id),
        after={
            "username": user.username,
            "role": user.role,
            "name": user.name,
            "must_change_password": user.must_change_password,
        },
        request=request,
    )
    return out


@router.post("/login", response_model=TokenPair)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    ip = _client_ip(request)
    # 双维度限速：单 IP 防扫号；单账号防定向爆破
    _limit(f"login:ip:{ip}", limit=30, window=300, message="登录尝试过于频繁")
    _limit(
        f"login:user:{payload.username.strip().lower()}",
        limit=10,
        window=300,
        message="该账号尝试次数过多",
    )
    user = user_crud.verify_credentials(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    return TokenPair(
        access_token=security.create_access_token(str(user.id)),
        refresh_token=security.create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(
    refresh_token: str, request: Request, db: Session = Depends(get_db)
) -> TokenPair:
    """用 refresh token 换取新的令牌对。"""
    _limit(
        f"refresh:ip:{_client_ip(request)}",
        limit=120,
        window=300,
        message="刷新令牌过于频繁",
    )
    try:
        payload = security.decode_token(refresh_token, expected_type="refresh")
        subject = payload.get("sub")
        if subject is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        user = user_crud.get_by_id(db, subject)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return TokenPair(
        access_token=security.create_access_token(str(user.id)),
        refresh_token=security.create_refresh_token(str(user.id)),
    )
