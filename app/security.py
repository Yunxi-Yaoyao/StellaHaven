"""密码哈希 + JWT 签发/校验。全站唯一的密钥与算法出口。

- 密码：pwdlib（bcrypt），不可逆
- 访问令牌：JWT，30 分钟，走 httpOnly cookie
- 刷新令牌：随机串（非 JWT），哈希后存 auth_sessions 表——可吊销、可多地并存
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

# 本地自托管单实例：密钥落盘 data/secret_key（首次自动生成）
from pathlib import Path

_KEY_FILE = Path(__file__).resolve().parents[2] / "data" / "secret_key"


def _load_key() -> str:
    if _KEY_FILE.exists():
        return _KEY_FILE.read_text().strip()
    key = secrets.token_urlsafe(48)
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_text(key)
    _KEY_FILE.chmod(0o600)
    return key


SECRET_KEY = _load_key()
ALGORITHM = "HS256"
ACCESS_MINUTES = 30
REFRESH_DAYS = 30  # 勾了「记住我」的时长；不勾=会话级（浏览器关就没）

pwd = PasswordHash.recommended()


def hash_password(raw: str) -> str:
    return pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd.verify(raw, hashed)


def make_access_token(user_id: str, session_id: str = "") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "sid": session_id,  # 会话 id——吊销会话后 access 立即失效（踢下线即时生效）
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ACCESS_MINUTES)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def read_access_token(token: str) -> dict | None:
    """返回 {uid, sid}；过期/伪造返回 None"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("typ") != "access":
            return None
        return {"uid": payload.get("sub"), "sid": payload.get("sid", "")}
    except jwt.PyJWTError:
        return None


def make_refresh_token() -> tuple[str, str]:
    """返回 (明文给 cookie, 哈希存库)。明文只出现这一次。"""
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
