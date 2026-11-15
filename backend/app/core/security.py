import secrets
import string
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import get_settings

settings = get_settings()

# 使用 bcrypt（对应 pwdlib[bcrypt] 依赖）
password_hash = PasswordHash([BcryptHasher()])


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


# —— 密码策略（生产最低要求：≥8 位，字母+数字，拒绝高频弱口令） ——
PASSWORD_MIN_LENGTH = 8
# 常见弱口令（小写比对）：覆盖默认口令、连续数字、键盘序等
_WEAK_PASSWORDS = {
    "123456", "1234567", "12345678", "123456789", "1234567890",
    "password", "password1", "passw0rd", "admin123", "abc123",
    "11111111", "00000000", "88888888", "qwerty12", "qwertyui",
    "student1", "teacher1", "parent1", "iloveyou",
}


def validate_password_strength(password: str) -> str:
    """密码强度校验；不合规时抛 ValueError（Pydantic validator 直接转 422）。"""
    pw = password or ""
    if len(pw) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"密码至少 {PASSWORD_MIN_LENGTH} 位")
    if len(pw) > 128:
        raise ValueError("密码最长 128 位")
    if pw.lower() in _WEAK_PASSWORDS:
        raise ValueError("密码过于简单，请勿使用常见弱口令")
    has_letter = any(c.isalpha() for c in pw)
    has_digit = any(c.isdigit() for c in pw)
    if not (has_letter and has_digit):
        raise ValueError("密码需同时包含字母和数字")
    if len(set(pw)) < 4:
        raise ValueError("密码重复字符过多，请使用更复杂的组合")
    return pw


def generate_temp_password(length: int = 10) -> str:
    """生成满足强度校验的随机临时密码（去混淆字符，便于口头转述）。"""
    alphabet = string.ascii_letters.replace("O", "").replace("l", "").replace("I", "")
    digits = string.digits.replace("0", "").replace("1", "")
    # 先保证字母+数字各至少 2 个，再补足长度后打乱
    chars = [
        secrets.choice(alphabet),
        secrets.choice(alphabet),
        secrets.choice(digits),
        secrets.choice(digits),
    ]
    pool = alphabet + digits
    chars += [secrets.choice(pool) for _ in range(max(0, length - len(chars)))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(subject: str) -> str:
    return _create_token(
        subject,
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(subject: str) -> str:
    return _create_token(
        subject,
        "refresh",
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: str | None = None) -> dict:
    """解码 JWT；type 不匹配时抛 jwt.InvalidTokenError。"""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("token type mismatch")
    return payload
