"""小密钥加密：教师自配 API Key 落库前 Fernet 加密，密钥由 SECRET_KEY 派生。"""

import base64
import hashlib
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from cryptography.fernet import Fernet


def _fernet() -> "Fernet":
    from cryptography.fernet import Fernet

    raw = hashlib.sha256(get_settings().SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
