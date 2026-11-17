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
import json
import os
import fcntl
from contextlib import contextmanager
import time
from pathlib import Path

from authlib.jose import JsonWebKey, jwt
from app.services import ha_state

# ── 基础配置 ──
# issuer = Stella 对外地址（OpenList/Immich 容器 + 浏览器都要能访问）。
# 注意：Immich 的 openid-client v6 强制 HTTPS issuer，故用公网域名（nginx/frp 终结 TLS 反代到本服务）。
DEFAULT_ISSUER = "https://stella.xiya.live"

# 支持多域名入口冗余：根据请求 Host 返回对应 issuer，让 xiya.live / yunxi.life 都能做 IdP。
ALLOWED_HOSTS = {
    "stella.xiya.live": "https://stella.xiya.live",
    "stella.yunxi.life": "https://stella.yunxi.life",
}


def resolve_issuer(host: str) -> str:
    from urllib.parse import urlsplit
    from fastapi import HTTPException
    from app.services.entry_registry import records, _origin
    # Explicit operator identity wins over legacy host-based production aliases.
    # Only the exact issuer authority and registered parent browser entries may
    # serve it. Never infer signing identity from Host/Forwarded or entry lane.
    configured = os.getenv('STELLA_OIDC_ISSUER')
    if configured is not None:
        try:
            issuer = _origin(configured)
        except ValueError:
            raise HTTPException(503, 'OIDC issuer 配置无效') from None
        hosts = {urlsplit(issuer).netloc}
        hosts.update(urlsplit(origin).netloc for origin in records()['stella'].values())
        if host not in hosts:
            raise HTTPException(421, 'OIDC Host 未登记')
        return issuer
    if host in ALLOWED_HOSTS:
        return ALLOWED_HOSTS[host]
    parent = records()['stella']
    if host == urlsplit(parent.get('private', '')).netloc and parent['public'] in ALLOWED_HOSTS.values():
        return parent['public']
    raise HTTPException(421, 'OIDC Host 未登记')


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

def _prune_runtime(state):
    now = time.time()
    for key in ('codes', 'tokens'):
        state[key] = {k: v for k, v in state[key].items() if v['expires'] > now}


# Shared PVC state; one lock covers validation + one-time code consumption.
@contextmanager
def _shared_state(locked_runtime=None):
    if locked_runtime is not None:
        _prune_runtime(locked_runtime)
        yield locked_runtime
        return
    if ha_state.enabled():
        with ha_state.locked_state('oidc.runtime', {"codes": {}, "tokens": {}}) as state:
            _prune_runtime(state)
            yield state
        return
    directory = OIDC_DIR / "runtime"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "state.lock").open("a+") as lock:
        os.chmod(directory / "state.lock", 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / "state.json"
        state = json.loads(path.read_text()) if path.exists() else {"codes": {}, "tokens": {}}
        _prune_runtime(state)
        try:
            yield state
            tmp = directory / ("state." + secrets.token_hex(8) + ".tmp")
            try:
                with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
                    json.dump(state, out)
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)

CODE_TTL = 600          # 授权码 10 分钟
ACCESS_TOKEN_TTL = 86400  # access token 1 天


# ── 密钥管理 ──
def _get_key():
    import json as _json
    if ha_state.enabled():
        path = Path(os.getenv('STELLA_OIDC_PRIVATE_KEY_FILE', str(PRIVATE_KEY_PATH)))
        if not path.is_file():
            raise RuntimeError('provision the same OIDC private key file on all nodes')
        return JsonWebKey.import_key(_json.loads(path.read_text()))
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


# ── Client management: one row/file lock, never load/modify/save ──
SUPPORTED_SCOPES = ['openid', 'profile', 'email']


@contextmanager
def _locked_clients(write=True):
    if ha_state.enabled():
        with ha_state.locked_state('oidc.clients', {}) as clients:
            yield clients
        return
    CLIENT_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = CLIENT_FILE.with_suffix('.lock')
    with lock_path.open('a+') as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            clients = json.loads(CLIENT_FILE.read_text()) if CLIENT_FILE.exists() else {}
            from copy import deepcopy
            original = deepcopy(clients)
            yield clients
            if write and clients != original:
                tmp = CLIENT_FILE.with_name('clients.' + secrets.token_hex(8) + '.tmp')
                try:
                    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
                        json.dump(clients, out)
                    os.replace(tmp, CLIENT_FILE)
                finally:
                    tmp.unlink(missing_ok=True)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def _locked_client_runtime(write_clients=True):
    """One HA transaction, or the unchanged legacy clients -> runtime locks."""
    if ha_state.enabled():
        with ha_state.locked_states({'oidc.clients': {},
                                     'oidc.runtime': {'codes': {}, 'tokens': {}}}) as states:
            yield states['oidc.clients'], states['oidc.runtime']
        return
    with _locked_clients(write=write_clients) as clients:
        # Delay the legacy runtime file lock until client validation succeeds.
        yield clients, None


def _load_clients() -> dict:
    from copy import deepcopy
    with _locked_clients(write=False) as clients:
        return deepcopy(clients)


def _get_client(client_id: str) -> dict | None:
    client = _load_clients().get(client_id)
    if client is None and not ha_state.enabled() and not CLIENT_FILE.exists() and client_id == DEFAULT_CLIENT['client_id']:
        return dict(DEFAULT_CLIENT)
    return client


def get_client_secret(client_id: str) -> str:
    """Internal compatibility getter, not a management reveal API."""
    with _locked_clients() as clients:
        client = clients.get(client_id)
        if client is None:
            if ha_state.enabled() or CLIENT_FILE.exists() or client_id != DEFAULT_CLIENT['client_id']:
                raise ValueError('unknown client')
            client = clients[client_id] = dict(DEFAULT_CLIENT)
        if not client.get('client_secret'):
            client['client_secret'] = secrets.token_urlsafe(48)
        return client['client_secret']


def reveal_client_secret(client_id: str, *, authorize=None) -> dict:
    """Read an existing credential only; never initialize, rotate or update it.

    The optional admission check runs AFTER acquiring the credential lock, so a
    management grant that expired while waiting cannot disclose a credential.
    HA uses SELECT FOR SHARE, not locked_state (which inserts/updates payloads).
    """
    def selected(clients):
        if authorize is not None:
            authorize()
        client = clients.get(client_id)
        if client is None:
            raise KeyError(client_id)
        value = client.get('client_secret')
        if not isinstance(value, str) or not value:
            raise ValueError('client has no existing secret')
        return {'client_id': client_id, 'client_secret': value}

    if ha_state.enabled():
        from sqlalchemy import select
        engine = ha_state._engine()
        if engine.dialect.name != 'postgresql':
            raise RuntimeError('shared state requires PostgreSQL')
        with engine.begin() as conn:
            clients = conn.execute(select(ha_state.state_table.c.payload)
                .where(ha_state.state_table.c.key == 'oidc.clients')
                .with_for_update(read=True)).scalar_one_or_none()
            return selected(clients or {})
    if not CLIENT_FILE.exists():
        raise KeyError(client_id)
    with _locked_clients(write=False) as clients:
        return selected(clients)


def _public_client(client_id, client):
    return {'client_id': client_id, 'name': client.get('name') or client_id,
            'enabled': client.get('enabled', True),
            'redirect_uris': list(client.get('redirect_uris', [])),
            'has_secret': bool(client.get('client_secret')),
            'scopes': list(client.get('scopes', SUPPORTED_SCOPES)),
            'last_used_at': client.get('last_used_at')}


def list_clients():
    return [_public_client(cid, client) for cid, client in sorted(_load_clients().items())]


def _validate_client_changes(changes, previous=None):
    import re
    from urllib.parse import urlsplit, unquote
    if set(changes) - {'name', 'enabled', 'redirect_uris', 'scopes'}:
        raise ValueError('unsupported client field')
    if 'name' in changes and (not isinstance(changes['name'], str) or not changes['name'].strip() or len(changes['name']) > 128):
        raise ValueError('name must contain 1 to 128 characters')
    if 'enabled' in changes and type(changes['enabled']) is not bool:
        raise ValueError('enabled must be boolean')
    if 'scopes' in changes:
        scopes = changes['scopes']
        if not isinstance(scopes, list) or not scopes or 'openid' not in scopes or any(not isinstance(s, str) or s not in SUPPORTED_SCOPES for s in scopes) or len(set(scopes)) != len(scopes):
            raise ValueError('unsupported scopes; openid is required')
    if 'redirect_uris' in changes:
        uris = changes['redirect_uris']
        if not isinstance(uris, list) or not 1 <= len(uris) <= 32:
            raise ValueError('provide 1 to 32 exact redirect URIs')
        for uri in uris:
            if not isinstance(uri, str) or not uri or len(uri) > 2048:
                raise ValueError('invalid redirect URI')
            decoded = unquote(uri)
            if re.search(r'[\s\\*\x00-\x1f\x7f]', decoded) or '?' in uri or '#' in uri:
                raise ValueError('redirect URI cannot contain wildcard, query or fragment')
            try:
                parsed = urlsplit(uri)
                # Preserve an exact pre-registered native-app callback. This does
                # not allow newly supplied custom schemes or redirect expansion.
                if (previous and uri in previous.get('redirect_uris', [])
                        and re.fullmatch(r'[a-z][a-z0-9+.-]*', parsed.scheme)
                        and parsed.scheme not in ('http', 'https', 'file', 'data', 'javascript')
                        and not parsed.netloc and parsed.path.startswith('/')
                        and uri.startswith(parsed.scheme + ':///')):
                    continue
                parsed.port  # reject invalid/non-numeric ports
                host = parsed.hostname
                if not host or parsed.username is not None or parsed.password is not None or '%' in parsed.netloc:
                    raise ValueError('invalid authority')
                from ipaddress import ip_address
                try:
                    address = ip_address(host)
                    local = address.is_private or address.is_loopback
                except ValueError:
                    ascii_host = host.encode('idna').decode('ascii')
                    if len(ascii_host) > 253 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in ascii_host.rstrip('.').split('.')):
                        raise ValueError('invalid hostname')
                    local = host == 'localhost' or host.endswith('.localhost') or '.' not in host
            except (ValueError, UnicodeError):
                raise ValueError('invalid redirect URI') from None
            legacy = previous and uri in previous.get('redirect_uris', []) and parsed.scheme == 'http' and local
            if parsed.scheme != 'https' and not legacy:
                raise ValueError('new redirect URIs must use HTTPS')
        if len(set(uris)) != len(uris):
            raise ValueError('duplicate redirect URI')


def create_client(client_id, *, name, redirect_uris, enabled=True, scopes=None):
    import re
    if not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', client_id):
        raise ValueError('invalid client_id')
    _validate_client_changes({'name': name, 'redirect_uris': redirect_uris, 'enabled': enabled,
                              'scopes': SUPPORTED_SCOPES if scopes is None else scopes})
    with _locked_clients() as clients:
        if client_id in clients:
            raise ValueError('client already exists')
        client = {'name': name, 'enabled': enabled, 'redirect_uris': list(redirect_uris),
                  'scopes': list(scopes or SUPPORTED_SCOPES),
                  'client_secret': secrets.token_urlsafe(48),
                  'credential_version': secrets.token_hex(16)}
        clients[client_id] = client
        return {**_public_client(client_id, client), 'client_secret': client['client_secret']}


def update_client(client_id, changes):
    with _locked_clients() as clients:
        if client_id not in clients:
            raise KeyError(client_id)
        client = clients[client_id]
        _validate_client_changes(changes, previous=client)
        client.update(changes)
        if any(key in changes for key in ('enabled', 'redirect_uris', 'scopes')):
            client['credential_version'] = secrets.token_hex(16)
        return _public_client(client_id, client)


def rotate_client_secret(client_id):
    with _locked_clients() as clients:
        if client_id not in clients:
            raise KeyError(client_id)
        client = clients[client_id]
        client['client_secret'] = secrets.token_urlsafe(48)
        client['credential_version'] = secrets.token_hex(16)
        return {**_public_client(client_id, client), 'client_secret': client['client_secret']}


def delete_client(client_id):
    with _locked_clients() as clients:
        if client_id not in clients:
            raise KeyError(client_id)
        del clients[client_id]


# ── 发现文档 / JWKS ──
def openid_configuration(issuer: str = DEFAULT_ISSUER) -> dict:
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "userinfo_endpoint": f"{issuer}/oauth/userinfo",
        "jwks_uri": f"{issuer}/oauth/jwks",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": list(SUPPORTED_SCOPES),
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
        "claims_supported": ["sub", "name", "email", "preferred_username"],
    }


def jwks() -> dict:
    from fastapi import HTTPException
    from app.services.small_public_outputs import PublicJWKS, public_signing_jwk

    # Public reads must not invoke the signing helper's first-run key generation.
    path = (Path(os.getenv('STELLA_OIDC_PRIVATE_KEY_FILE', str(PRIVATE_KEY_PATH)))
            if ha_state.enabled() else PRIVATE_KEY_PATH)
    try:
        stored = json.loads(path.read_text(encoding='utf-8'))
        pub = public_signing_jwk(stored, kid=KID)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise HTTPException(503, 'OIDC 签名密钥配置无效或不支持，请检查服务器配置') from None
    return PublicJWKS(keys=[pub]).model_dump()


# ── id_token 签发 ──
def _sign_id_token(user_id: str, username: str, email: str, nonce: str | None,
                   client_id: str, issuer: str = DEFAULT_ISSUER, scope='openid profile email', session_id=None) -> str:
    key = _get_key()
    now = int(time.time())
    header = {"alg": "RS256", "kid": KID, "typ": "JWT"}
    claims = {
        "iss": issuer,
        "sub": str(user_id),
        "aud": client_id,
        "iat": now,
        "exp": now + 3600,
    }
    if 'profile' in scope.split():
        claims.update(name=username, preferred_username=username)
    if 'email' in scope.split():
        claims['email'] = email or ''
    if nonce:
        claims["nonce"] = nonce
    if session_id is not None:
        claims['sid'] = session_id
    token = jwt.encode(header, claims, key)
    return token.decode() if isinstance(token, bytes) else token


# ── 授权码流程 ──
def validate_authorization(client, redirect_uri, scope='openid', code_challenge=None, code_challenge_method=None):
    import re
    if not client or not client.get('enabled', True):
        raise ValueError('invalid_client')
    if redirect_uri not in client.get('redirect_uris', []):
        raise ValueError('invalid_redirect_uri')
    scopes = scope.split()
    if 'openid' not in scopes or any(s not in client.get('scopes', SUPPORTED_SCOPES) or s not in SUPPORTED_SCOPES for s in scopes):
        raise ValueError('invalid_scope')
    if code_challenge is not None or code_challenge_method is not None:
        if code_challenge_method != 'S256' or not code_challenge or not re.fullmatch(r'[A-Za-z0-9_-]{43}', code_challenge):
            raise ValueError('invalid_request')
    return ' '.join(dict.fromkeys(scopes))


def create_authorization_code(client_id: str, redirect_uri: str, user_id: str,
                              username: str, email: str, nonce: str | None,
                              issuer: str = DEFAULT_ISSUER, *, code_challenge=None,
                              code_challenge_method=None, scope='openid', session_id=None) -> str:
    code = secrets.token_urlsafe(32)
    # Global lock ordering: clients -> runtime, including exchange and userinfo.
    with _locked_client_runtime(write_clients=False) as (clients, runtime):
        client = clients.get(client_id)
        scope = validate_authorization(client, redirect_uri, scope, code_challenge, code_challenge_method)
        with _shared_state(runtime) as state:
            state['codes'][code] = {
                'client_id': client_id, 'user_id': str(user_id), 'username': username,
                'email': email or '', 'redirect_uri': redirect_uri, 'nonce': nonce,
                'issuer': issuer, 'expires': time.time() + CODE_TTL,
                'scope': scope, 'code_challenge': code_challenge,
                'session_id': session_id,
                'credential_version': client.get('credential_version', 0),
            }
    return code


def exchange_code(code: str, client_id: str, client_secret: str,
                  redirect_uri: str | None, *, code_verifier=None) -> dict | None:
    import base64
    import hashlib
    import re
    with _locked_client_runtime() as (clients, runtime):
        client = clients.get(client_id)
        if not client or not client.get('enabled', True) or not client.get('client_secret') or not isinstance(client_secret, str):
            return None
        if not secrets.compare_digest(client_secret.encode(), client['client_secret'].encode()):
            return None
        with _shared_state(runtime) as state:
            rec = state['codes'].get(code)
            if (not rec or rec['expires'] <= time.time() or rec['client_id'] != client_id
                    or rec['redirect_uri'] != redirect_uri
                    or redirect_uri not in client.get('redirect_uris', [])
                    or rec.get('credential_version', 0) != client.get('credential_version', 0)):
                return None
            challenge = rec.get('code_challenge')
            # An unbound code must not accept a verifier (PKCE downgrade).
            # Confidential legacy flows supplying neither field remain valid.
            if not challenge and code_verifier is not None:
                return None
            if challenge:
                if not isinstance(code_verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', code_verifier):
                    return None
                actual = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode('ascii')).digest()).rstrip(b'=').decode()
                if not secrets.compare_digest(actual, challenge):
                    return None
            issuer = rec.get('issuer', DEFAULT_ISSUER)
            id_token = _sign_id_token(rec['user_id'], rec['username'], rec['email'],
                                      rec['nonce'], client_id, issuer=issuer, scope=rec.get('scope', 'openid profile email'),
                                      session_id=rec.get('session_id'))
            access_token = secrets.token_urlsafe(32)
            state['codes'].pop(code)
            state['tokens'][access_token] = {
                'user_id': rec['user_id'], 'username': rec['username'], 'email': rec['email'],
                'expires': time.time() + ACCESS_TOKEN_TTL, 'scope': rec.get('scope', 'openid'),
                'client_id': client_id, 'credential_version': client.get('credential_version', 0),
            }
        from datetime import datetime, timezone
        client['last_used_at'] = datetime.now(timezone.utc).isoformat()
        return {'access_token': access_token, 'id_token': id_token, 'token_type': 'Bearer',
                'expires_in': ACCESS_TOKEN_TTL, 'scope': rec.get('scope', 'openid')}


def userinfo(access_token: str) -> dict | None:
    with _locked_client_runtime(write_clients=False) as (clients, runtime):
        with _shared_state(runtime) as state:
            rec = state['tokens'].get(access_token)
            if not rec or rec['expires'] <= time.time():
                return None
            client = clients.get(rec.get('client_id'))
            if (not client or not client.get('enabled', True)
                    or rec.get('credential_version', 0) != client.get('credential_version', 0)):
                return None
            info = {'sub': rec['user_id']}
            scopes = rec.get('scope', 'openid profile email').split()
            if 'profile' in scopes:
                info.update(name=rec['username'], preferred_username=rec['username'])
            if 'email' in scopes:
                info['email'] = rec['email']
            return info


def verify_redirect_uri(client_id: str, redirect_uri: str) -> bool:
    client = _get_client(client_id)
    if not client:
        return False
    return redirect_uri in client.get("redirect_uris", [])
