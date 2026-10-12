from asyncio import sleep
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.core.config import get_settings
from app.services.llm import LLMConfigError

settings = get_settings()


async def _order_expiry_sweeper() -> None:
    """后台兜底：每 60s 撤销过期的待支付订单（家长关页面也生效）。"""
    from app.core.database import SessionLocal
    from app.crud import order as order_crud

    while True:
        try:
            await sleep(60)
            db = SessionLocal()
            try:
                order_crud.expire_stale_orders(db)
            finally:
                db.close()
        except Exception:
            continue


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    import asyncio

    from app.core.database import engine
    from app.core.schema_ensure import ensure_business_schema

    ensure_business_schema(engine)
    task = asyncio.create_task(_order_expiry_sweeper())
    try:
        yield
    finally:
        task.cancel()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

_extra_origins = [o.strip() for o in (settings.CORS_ORIGINS or "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", *_extra_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_PREFIX)


@app.middleware("http")
async def _no_store_api_cache(request: Request, call_next):
    """管理端高频变更的基础资料（校区/科目等）禁止浏览器启发式缓存，避免排序调整后下拉仍显示旧顺序。"""
    response = await call_next(request)
    if request.url.path.startswith(settings.API_PREFIX):
        response.headers["Cache-Control"] = "no-store"
    return response

# 素材静态服务（反馈照片/视频等，本地存储 OQ-04 决策）
_upload_dir = Path(settings.UPLOAD_DIR)
_upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_upload_dir)), name="uploads")


@app.get(f"{settings.API_PREFIX}/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.exception_handler(LLMConfigError)
async def _friendly_llm_errors(request: Request, exc: LLMConfigError):
    return JSONResponse(status_code=400, content={'detail': str(exc)})
