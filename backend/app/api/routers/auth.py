import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core import security
from app.core.database import get_db
from app.crud import user as user_crud
from app.models.user import Role
from app.schemas.auth import LoginIn, RegisterIn, TokenPair, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> UserOut:
    """注册。首版允许 admin/teacher/parent/student 前端注册；staff 由管理员后续管理端创建。"""
    if payload.role == Role.STAFF:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="STAFF role not self-registrable",
        )
    if user_crud.get_by_username(db, payload.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    if payload.phone and user_crud.get_by_phone(db, payload.phone):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone already exists")
    user = user_crud.create_user(
        db,
        role=payload.role,
        username=payload.username,
        password=payload.password,
        name=payload.name,
        phone=payload.phone,
        campus=payload.campus,
        title=payload.title,
    )
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> TokenPair:
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
def refresh(refresh_token: str, db: Session = Depends(get_db)) -> TokenPair:
    """用 refresh token 换取新的令牌对。"""
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
