"""小密钥加密：教师自配 API Key 落库前 Fernet 加密。

密钥由 SECRET_KEY 派生；密文带版本前缀 `v1:`，解密时依次尝试
「当前 SECRET_KEY + SECRET_KEY_PREVIOUS 旧密钥」，支持密钥轮换不丢数据。
历史密文（无前缀，旧格式）按 v1 同派生规则兼容解密。
"""

import base64
import hashlib
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from cryptography.fernet import Fernet, MultiFernet

_VERSION_PREFIX = "v1:"


def _fernet_for(secret_key: str) -> "Fernet":
    from cryptography.fernet import Fernet

    raw = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def _multi_fernet() -> "MultiFernet":
    """当前密钥在前、历史密钥在后：加密用首个，解密依次尝试。"""
    from cryptography.fernet import MultiFernet

    cfg = get_settings()
    keys = [cfg.SECRET_KEY]
    for old in (cfg.SECRET_KEY_PREVIOUS or "").split(","):
        old = old.strip()
        if old:
            keys.append(old)
    return MultiFernet([_fernet_for(k) for k in keys])


def encrypt_secret(plain: str) -> str:
    return _VERSION_PREFIX + _multi_fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    raw = token[len(_VERSION_PREFIX):] if token.startswith(_VERSION_PREFIX) else token
    return _multi_fernet().decrypt(raw.encode()).decode()
