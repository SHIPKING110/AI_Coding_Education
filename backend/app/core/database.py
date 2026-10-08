import enum

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def enum_values(e: type[enum.Enum]) -> list[str]:
    """SQLAlchemy Enum 列统一按成员 value（小写）存取。

    默认行为按成员名（ADMIN/SCHEDULED…）校验，库里历史数据是小写 value
    （admin/scheduled…），读行直接 LookupError 全页 500；所有模型统一用它。
    """
    return [m.value for m in e]


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
