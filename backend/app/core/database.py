from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


settings = get_settings()

# 业务时间统一按北京时区解释：前端提交的是无时区的本地naive串（如 09:00），
# 若不固定会话时区，容器（UTC）会把它当 09:00 UTC 存，读回偏移成 17:00。
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG,
    connect_args={"options": f"-c timezone={settings.BUSINESS_TIMEZONE}"},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI 依赖：提供数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
