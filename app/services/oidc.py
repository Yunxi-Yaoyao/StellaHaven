"""Stella 作为 OIDC Provider（IdP）：供 OpenList / Immich 等 RP 统一登录。

实现授权码流程（Authorization Code Flow）：
  - /.well-known/openid-configuration  发现文档
  - /oauth/jwks                        签名公钥
  - /oauth/authorize                   授权端点（用户已登录 Stella 则直接放行发码）
  - /oauth/token                       令牌端点（授权码换 id_token + access_token）
  - /oauth/userinfo                    用户信息

id_token 用 RS256 签名，密钥持久化在 data/oidc/。
"""
import secrets
import time
from pathlib import Path

from authlib.jose import JsonWebKey, jwt

# ── 基础配置 ──
# issuer = Stella 对外地址（OpenList/Immich 容器 + 浏览器都要能访问）。
# 注意：Immich 的 openid-client v6 强制 HTTPS issuer，故用公网域名（nginx/frp 终结 TLS 反代到本服务）。
ISSUER = "https://stella.xiya.live"

OIDC_DIR = Path(__file__).resolve().parents[2] / "data" / "oidc"
PRIVATE_KEY_PATH = OIDC_DIR / "private.json"  # 私钥 JWK（含公钥）

# ── 客户端注册（OpenList） ──
# client_secret 首次启动时生成并持久化
CLIENT_FILE = OIDC_DIR / "clients.json"
DEFAULT_CLIENT = {
    "client_id": "openlist",
    "client_secret": None,  # 首次生成
    "redirect_uris": [
        "http://192.168.1.5:5244/api/auth/sso_callback",
        "http://127.0.0.1:5244/api/auth/sso_callback",
        "http://localhost:5244/api/auth/sso_callback",
    ],
}

# ── 内存态：授权码 / access token ──
_codes: dict[str, dict] = {}   # code -> {client_id, user_id, username, email, redirect_uri, nonce, expires}
_tokens: dict[str, dict] = {}  # access_token -> {user_id, username, email, expires}

CODE_TTL = 600          # 授权码 10 分钟
ACCESS_TOKEN_TTL = 86400  # access token 1 天


# ── 密钥管理 ──
def _get_key():
    import json as _json
    OIDC_DIR.mkdir(parents=True, exist_ok=True)
    if PRIVATE_KEY_PATH.exists():
        return JsonWebKey.import_key(_json.loads(PRIVATE_KEY_PATH.read_text()))
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    key_dict = key.as_dict(is_private=True)
    key_dict["kid"] = KID
    PRIVATE_KEY_PATH.write_text(_json.dumps(key_dict))
    return JsonWebKey.import_key(key_dict)


KID = "stella-oidc-1"


def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj)


# ── 客户端管理 ──
def _load_clients() -> dict:
    if CLIENT_FILE.exists():
        import json
        return json.loads(CLIENT_FILE.read_text())
    return {}


def _get_client(client_id: str) -> dict | None:
    if client_id == DEFAULT_CLIENT["client_id"]:
        return DEFAULT_CLIENT
    return _load_clients().get(client_id)


def get_client_secret(client_id: str) -> str:
    """取 client_secret（首次生成并持久化）。"""
    if client_id == DEFAULT_CLIENT["client_id"] and DEFAULT_CLIENT["client_secret"]:
        return DEFAULT_CLIENT["client_secret"]
    clients = _load_clients()
    if client_id in clients and clients[client_id].get("client_secret"):
        return clients[client_id]["client_secret"]
    # 首次生成
    secret = secrets.token_hex(32)
    if client_id == DEFAULT_CLIENT["client_id"]:
        DEFAULT_CLIENT["client_secret"] = secret
    clients[client_id] = {
        "client_secret": secret,
        "redirect_uris": DEFAULT_CLIENT["redirect_uris"],
    }
    import json
    OIDC_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_FILE.write_text(json.dumps(clients, indent=2))
    return secret


# ── 发现文档 / JWKS ──
def openid_configuration() -> dict:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/oauth/authorize",
        "token_endpoint": f"{ISSUER}/oauth/token",
        "userinfo_endpoint": f"{ISSUER}/oauth/userinfo",
        "jwks_uri": f"{ISSUER}/oauth/jwks",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "profile"],
        "claims_supported": ["sub", "name", "email", "preferred_username"],
    }


def jwks() -> dict:
    key = _get_key()
    pub = key.as_dict()
    pub["kid"] = KID
    return {"keys": [pub]}


# ── id_token 签发 ──
def _sign_id_token(user_id: str, username: str, email: str, nonce: str | None,
                   client_id: str) -> str:
    key = _get_key()
    now = int(time.time())
    header = {"alg": "RS256", "kid": KID, "typ": "JWT"}
    claims = {
        "iss": ISSUER,
        "sub": str(user_id),
        "aud": client_id,
        "iat": now,
        "exp": now + 3600,
        "name": username,
        "preferred_username": username,
        "email": email or "",
    }
    if nonce:
        claims["nonce"] = nonce
    token = jwt.encode(header, claims, key)
    return token.decode() if isinstance(token, bytes) else token


# ── 授权码流程 ──
def create_authorization_code(client_id: str, redirect_uri: str, user_id: str,
                              username: str, email: str, nonce: str | None) -> str:
    code = secrets.token_urlsafe(32)
    _codes[code] = {
        "client_id": client_id,
        "user_id": str(user_id),
        "username": username,
        "email": email or "",
        "redirect_uri": redirect_uri,
        "nonce": nonce,
        "expires": time.time() + CODE_TTL,
    }
    return code


def exchange_code(code: str, client_id: str, client_secret: str,
                  redirect_uri: str | None) -> dict | None:
    """授权码换 token。返回 id_token 等，失败返回 None。"""
    rec = _codes.get(code)
    if not rec:
        return None
    if rec["expires"] < time.time():
        _codes.pop(code, None)
        return None
    if rec["client_id"] != client_id:
        return None
    if rec["redirect_uri"] != redirect_uri:
        return None
    # client_secret 校验
    if client_secret != get_client_secret(client_id):
        return None
    _codes.pop(code, None)

    id_token = _sign_id_token(rec["user_id"], rec["username"], rec["email"],
                              rec["nonce"], client_id)
    access_token = secrets.token_urlsafe(32)
    _tokens[access_token] = {
        "user_id": rec["user_id"],
        "username": rec["username"],
        "email": rec["email"],
        "expires": time.time() + ACCESS_TOKEN_TTL,
    }
    return {
        "access_token": access_token,
        "id_token": id_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL,
    }


def userinfo(access_token: str) -> dict | None:
    rec = _tokens.get(access_token)
    if not rec or rec["expires"] < time.time():
        return None
    return {
        "sub": rec["user_id"],
        "name": rec["username"],
        "preferred_username": rec["username"],
        "email": rec["email"],
    }


def verify_redirect_uri(client_id: str, redirect_uri: str) -> bool:
    client = _get_client(client_id)
    if not client:
        return False
    return redirect_uri in client.get("redirect_uris", [])
