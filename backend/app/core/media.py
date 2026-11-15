"""上传素材访问控制：`/uploads/` 下文件必须携带短期签名才可读取。

- 签名 = HMAC-SHA256(派生密钥, 路径 + 过期时间)，密钥由 SECRET_KEY 派生（独立 info，避免与 JWT 复用）
- 过期时间 = 生成时刻 + MEDIA_URL_TTL_SECONDS
- 读取入口统一为 SignedMediaFiles（挂在 /uploads），未签名/篡改/过期一律 401
- API JSON 响应中的 `/uploads/...` 字符串由中间件统一补签名，前端无需改动
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import parse_qsl, urlsplit

from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings

_UPLOAD_PREFIX = "/uploads/"
_SIG_PARAM = "sig"
_EXP_PARAM = "exp"


def _signing_key() -> bytes:
    # 领域分离：即使 SECRET_KEY 泄漏影响面相同，也避免与其他用途的 HMAC 互通
    return hashlib.sha256(b"media-url-v1|" + get_settings().SECRET_KEY.encode()).digest()


def strip_media_signature(url: str) -> str:
    """去掉 URL 上的 exp/sig 查询串（持久化入库前调用，避免把过期签名写进数据库）。"""
    if not isinstance(url, str) or _UPLOAD_PREFIX not in url:
        return url
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in (_SIG_PARAM, _EXP_PARAM)]
    query = "&".join(f"{k}={v}" for k, v in kept)
    return f"{parts.path}?{query}" if query else parts.path


def sign_media_path(path: str, *, ttl_seconds: int | None = None) -> str:
    """为素材路径补签名；非 /uploads/ 路径（外链/空值）原样返回。"""
    if not isinstance(path, str) or not path.startswith(_UPLOAD_PREFIX):
        return path
    clean = strip_media_signature(path)
    ttl = ttl_seconds if ttl_seconds is not None else int(get_settings().MEDIA_URL_TTL_SECONDS)
    exp = int(time.time()) + max(30, ttl)
    sig = hmac.new(_signing_key(), f"{clean}|{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{clean}?{_EXP_PARAM}={exp}&{_SIG_PARAM}={sig}"


def verify_media_signature(path: str, exp: str | None, sig: str | None) -> bool:
    """校验签名与有效期。path 为 URL 路径（含 /uploads/ 前缀，不含查询串）。"""
    if not path.startswith(_UPLOAD_PREFIX) or not exp or not sig:
        return False
    try:
        exp_ts = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_ts < time.time():
        return False
    expected = hmac.new(_signing_key(), f"{path}|{exp_ts}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


class SignedMediaFiles(StaticFiles):
    """静态素材服务：先验签，再交给父类做真实文件读取（自带路径穿越防护）。"""

    async def get_response(self, path: str, scope):
        from urllib.parse import parse_qs

        query = parse_qs(scope.get("query_string", b"").decode())
        exp = (query.get(_EXP_PARAM) or [None])[0]
        sig = (query.get(_SIG_PARAM) or [None])[0]
        # Starlette 的 get_path 在 Windows 下用 os.path 拼接会产生反斜杠，统一归一为 URL 斜杠
        rel = path[1:] if path.startswith("/") else path
        rel = rel.replace("\\", "/")
        if not verify_media_signature(_UPLOAD_PREFIX + rel, exp, sig):
            return JSONResponse(
                status_code=401,
                content={"detail": "文件访问链接无效或已过期，请刷新页面后重试"},
            )
        return await super().get_response(path, scope)


def sign_urls_in_json(obj):
    """递归遍历 JSON 结构，为所有 /uploads/ 字符串补签名（响应中间件调用）。"""
    if isinstance(obj, str):
        return sign_media_path(obj) if obj.startswith(_UPLOAD_PREFIX) else obj
    if isinstance(obj, list):
        return [sign_urls_in_json(item) for item in obj]
    if isinstance(obj, dict):
        return {k: sign_urls_in_json(v) for k, v in obj.items()}
    return obj
