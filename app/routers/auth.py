"""Single pinned owner, daily authentication and independent session-bound elevation.

Legacy user UUIDs and ownership guards remain; invitations/user CRUD are gone.
Multiple devices retain separate revocable AuthSessions. is_admin is legacy
metadata only; privileged operations use PostgreSQL-backed management grants.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, Query
from sqlalchemy import and_, or_
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.session_policy import expired, expires_at, utc
from app.models.user import User, AuthSession
from app.security import (
    ACCESS_MINUTES, REFRESH_DAYS,
    hash_password, verify_password,
    make_access_token, read_access_token,
    make_refresh_token, hash_refresh,
)

router = APIRouter(prefix="/auth", tags=["auth"])

AT_COOKIE = "stella_at"
RT_COOKIE = "stella_rt"


# ---------- 依赖：当前用户 ----------
def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(AT_COOKIE)
    claims = read_access_token(token) if token else None
    if not claims or not claims.get("uid"):
        raise HTTPException(401, "未登录")
    # 会话被吊销（别处踢下线）→ access 立即作废
    try:
        sid = UUID(claims.get("sid", ""))
        uid = UUID(claims["uid"])
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(401, "无效会话")
    session = db.get(AuthSession, sid)
    if not session or session.user_id != uid or session.revoked or expired(session):
        raise HTTPException(401, "会话已下线")
    user = db.get(User, uid)
    if not user or not user.is_active:
        raise HTTPException(401, "账号不可用")
    from app.services.admin_security import require_owner
    require_owner(db, user)
    request.state.auth_session = session
    return user


def admin_user(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    from app.services.admin_security import require_admin
    require_admin(db, request.state.auth_session)
    return user


@router.get('/security')
def security(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services.admin_security import security_status
    return security_status(db, request.state.auth_session)


# ---------- 数据隔离：资源归属校验 ----------
class SecurityIn(BaseModel):
    enabled: bool
    password: str | None = None


class AdminPasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.put('/security')
def update_security(data: SecurityIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services.admin_security import change_protection
    change_protection(db, data.enabled, data.password)
    return {'ok': True}


@router.post('/admin/password')
def change_management_password(data: AdminPasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services.admin_security import change_admin_password
    change_admin_password(db, user, data.current_password, data.new_password)
    return {'ok': True}


class AdminSetupIn(BaseModel):
    user_password: str
    new_password: str


class AdminUnlockIn(BaseModel):
    password: str


@router.post('/admin/setup')
def admin_setup(data: AdminSetupIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services.admin_security import setup
    setup(db, user, data.user_password, data.new_password)
    return {'ok': True}


@router.post('/admin/unlock')
def admin_unlock(data: AdminUnlockIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services.admin_security import unlock, security_status
    unlock(db, request.state.auth_session, data.password)
    return security_status(db, request.state.auth_session)


@router.post('/admin/lock')
def admin_lock(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services.admin_security import lock
    lock(db, request.state.auth_session)
    return {'ok': True}


def require_ws_owner(db: Session, ws_id: UUID, user: User):
    """工作区必须属于当前用户（多用户隔离），否则 404（不暴露存在性）"""
    from app.models.workspace import Workspace
    ws = db.get(Workspace, ws_id)
    if not ws or ws.user_id != user.id:
        raise HTTPException(404, "工作区不存在")
    return ws


def require_doc_owner(db: Session, doc_id: UUID, user: User):
    """文档必须属于当前用户（经 workspace 归属判定）"""
    from app.models.document import Document
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    require_ws_owner(db, doc.workspace_id, user)
    return doc


# ---------- 工具 ----------
def _device_label(ua: str) -> str:
    ua = ua.lower()
    for key, label in [("mobile", "手机"), ("micromessenger", "微信内嵌"), ("windows", "Windows"),
                       ("mac", "Mac"), ("linux", "Linux")]:
        if key in ua:
            if "mobile" in ua and key == "mobile":
                return "手机"
            if key != "mobile":
                return label
    return "未知设备"


def _issue_cookies(response: Response, user: User, session: AuthSession, remember: bool) -> None:
    at = make_access_token(str(user.id), str(session.id))
    import os
    secure = os.getenv('STELLA_COOKIE_SECURE', 'true').lower() != 'false'
    access_kwargs = {"httponly": True, "samesite": "lax", "path": "/", "secure": secure}
    if remember:
        access_kwargs["max_age"] = min(ACCESS_MINUTES * 60, max(0, int((expires_at(session) - datetime.now(timezone.utc)).total_seconds())))
    response.set_cookie(AT_COOKIE, at, **access_kwargs)
    # 记住我 → refresh cookie 30 天；否则会话级（无 max_age）
    rt_raw = session._rt_raw  # type: ignore[attr-defined]
    kwargs = {"httponly": True, "samesite": "lax", "path": "/", "secure": secure}
    if remember:
        kwargs["max_age"] = max(0, int((expires_at(session) - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(RT_COOKIE, rt_raw, **kwargs)


# ---------- 入参 ----------
class RegisterIn(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class LoginIn(BaseModel):
    username: str  # 三合一标识：用户名 / 昵称 / 邮箱（已验证的）
    password: str
    remember: bool = False
    device: str | None = None


def _find_by_identifier(db: Session, ident: str) -> User | None:
    """三合一登录：用户名 > 邮箱（须已验证）> 昵称 的顺序精确匹配"""
    ident = ident.strip()
    u = db.query(User).filter(User.username == ident).first()
    if u:
        return u
    u = db.query(User).filter(User.email != "", User.email == ident, User.email_verified == True).first()  # noqa: E712
    if u:
        return u
    return db.query(User).filter(User.display_name == ident).first()


def _assert_identifiers_free(db: Session, username: str = "", display_name: str = "", email: str = "", exclude: UUID | None = None) -> None:
    """用户名/昵称/邮箱全站互不相同（三个字段交叉查重，忽略空值）"""
    def taken(col, val: str) -> bool:
        if not val:
            return False
        q = db.query(User).filter(col == val)
        if exclude:
            q = q.filter(User.id != exclude)
        return q.count() > 0

    for label, val in [("用户名", username), ("昵称", display_name), ("邮箱", email)]:
        if not val:
            continue
        if taken(User.username, val) or taken(User.display_name, val) or taken(User.email, val):
            raise HTTPException(409, f"「{val}」这个名字被占了喵~（用户名/昵称/邮箱不能重复）")


# ---------- 端点 ----------
@router.get("/status")
def status(db: Session = Depends(get_db)):
    """公开：初始化状态 + 邮箱服务是否开启（登录页决定显不显示忘记密码）"""
    from app.routers.admin_email import _load as load_cfg
    total = db.query(User).count()
    cfg = load_cfg()
    email_on = bool(cfg.get("enabled") and cfg.get("host") and cfg.get("username") and cfg.get("password"))
    return {"has_users": total > 0, "initialized": total > 0, "email_enabled": email_on, "single_user": True}


@router.post("/register", status_code=201)
def register(data: RegisterIn, response: Response, request: Request, db: Session = Depends(get_db)):
    """Initialize a genuinely empty installation; never claim existing accounts."""
    from app.services.admin_security import locked_state
    locked_state(db)  # PostgreSQL transaction lock fences simultaneous initialization.
    if db.query(User).count() > 0:
        raise HTTPException(403, "单用户模式已初始化，注册通道关闭")
    username = data.username.strip()
    if not username or not 6 <= len(data.password) <= 256:
        raise HTTPException(400, "用户名不能为空，密码须为6至256位")

    _assert_identifiers_free(db, username=username, display_name=(data.display_name or username).strip())
    user = User(
        username=username,
        display_name=(data.display_name or username).strip(),
        password_hash=hash_password(data.password),
        is_admin=True,  # 初始化注册者 = admin
    )
    db.add(user)
    db.flush()
    _create_session(db, user, request, response, remember=True)  # 注册即登录
    db.commit()
    return _user_out(user)


@router.post("/login")
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """三合一登录：用户名 / 昵称 / 已验证邮箱 都行"""
    user = _find_by_identifier(db, data.username)
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "账号或密码错误")
    if not user.is_active:
        raise HTTPException(403, "账号已被禁用")
    _create_session(db, user, request, response, remember=data.remember, device=data.device)
    db.commit()
    return _user_out(user)


def _create_session(db: Session, user: User, request: Request, response: Response,
                    remember: bool, device: str | None = None) -> AuthSession:
    from app.services.admin_security import require_owner
    require_owner(db, user)
    previous = _presented_session(request, db)
    if previous and previous.user_id == user.id and not previous.revoked and not expired(previous):
        previous.revoked = True
    rt_raw, rt_hash = make_refresh_token()
    # The ASGI server may trust an explicitly configured proxy peer; do not
    # consume arbitrary client-supplied X-Forwarded-For here.
    ip = request.client.host if request.client else ""
    session = AuthSession(
        user_id=user.id,
        refresh_hash=rt_hash,
        device=device or _device_label(request.headers.get("user-agent", "")),
        ip=ip,
        remember=remember,
    )
    session._rt_raw = rt_raw  # type: ignore[attr-defined]  # 只活这一次，不落库
    db.add(session)
    db.flush()
    _issue_cookies(response, user, session, remember)
    return session


def rotate_refresh(request: Request, response: Response, db: Session) -> User:
    """用 refresh token 旋转出新 access token（Set-Cookie 到 response），返回 User。
    供 /auth/refresh 路由和 OIDC authorize 裸跳转的自动续期共用。"""
    raw = request.cookies.get(RT_COOKIE)
    if not raw:
        raise HTTPException(401, "无刷新令牌")
    # 行级锁：同域名多 tab 并发 refresh 时串行化，避免旋转制把对方 token 覆盖废掉
    session = db.query(AuthSession).filter(AuthSession.refresh_hash == hash_refresh(raw)).with_for_update().first()
    if not session or session.revoked or expired(session):
        raise HTTPException(401, "会话已失效")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "账号不可用")
    from app.services.admin_security import require_owner
    require_owner(db, user)
    # 旋转：旧 refresh 作废，发新的
    rt_raw, rt_hash = make_refresh_token()
    session.refresh_hash = rt_hash

    session._rt_raw = rt_raw  # type: ignore[attr-defined]
    _issue_cookies(response, user, session, session.remember)
    db.commit()
    return user


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    return _user_out(rotate_refresh(request, response, db))


def _presented_session(request: Request, db: Session):
    # Elevation is access-SID bound. Prefer that exact session even when a
    # stale/mixed refresh cookie names another device's session.
    claims = read_access_token(request.cookies.get(AT_COOKIE, "")) or {}
    try:
        session = db.get(AuthSession, UUID(claims["sid"]))
        if session and str(session.user_id) == claims.get("uid"):
            return session
    except (KeyError, ValueError, TypeError):
        pass
    raw = request.cookies.get(RT_COOKIE)
    if raw:
        return db.query(AuthSession).filter(AuthSession.refresh_hash == hash_refresh(raw)).first()
    return None


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session = _presented_session(request, db)
    if session:
        session.revoked = True
        from app.services.admin_security import lock
        lock(db, session)
    response.delete_cookie(AT_COOKIE, path="/")
    response.delete_cookie(RT_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _user_out(user)


@router.post("/activity")
def activity(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Explicit interaction only. Polling/refresh never extends idle lifetime."""
    claims = read_access_token(request.cookies.get(AT_COOKIE, "")) or {}
    sid = claims.get("sid")
    if not sid:
        raise HTTPException(401, "无会话")
    session = db.query(AuthSession).filter(AuthSession.id == UUID(sid)).with_for_update().populate_existing().first()
    if not session or session.user_id != user.id or session.revoked or expired(session):
        raise HTTPException(401, "会话已失效")
    session.last_seen = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "expires_at": expires_at(session).isoformat()}


class ProfileIn(BaseModel):
    display_name: str | None = None
    email: str | None = None
    home_bg: str | None = None


@router.patch("/me")
def update_profile(data: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """改昵称/邮箱"""
    if data.email is not None:
        mail = data.email.strip()
        if mail and "@" not in mail:
            raise HTTPException(400, "邮箱格式不对喵~")
        _assert_identifiers_free(db, email=mail, exclude=user.id)
        if mail != user.email:
            user.email_verified = False  # 换邮箱=回到未验证
        user.email = mail
    if data.display_name is not None:
        name = data.display_name.strip()
        if not name:
            raise HTTPException(400, "昵称不能为空")
        _assert_identifiers_free(db, display_name=name, exclude=user.id)
        user.display_name = name
    if data.home_bg is not None:
        user.home_bg = data.home_bg.strip()
    db.commit()
    return _user_out(user)


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/password")
def change_password(data: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """改密码：验旧密码，改完全部会话吊销（重登保平安）"""
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(401, "原密码不对")
    if len(data.new_password) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    from app.services.admin_security import require_owner, daily_password_changed
    require_owner(db, user)
    daily_password_changed(db, data.new_password)
    user.password_hash = hash_password(data.new_password)
    db.query(AuthSession).filter(AuthSession.user_id == user.id).update({"revoked": True})
    db.commit()
    return {"ok": True, "hint": "密码已改，所有会话已下线，请重新登录"}


@router.post("/avatar")
async def upload_avatar(file: UploadFile, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """上传头像（前端裁好方形再传）：存 data/assets/avatars/<uid>-<ts>.<ext>。
    历史头像留最近 5 个（含当前），超出的连文件一起删。"""
    import json as _json
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
        raise HTTPException(400, "头像仅支持 jpg/png/webp/gif")
    from app.services import blob_store
    if blob_store.enabled():
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(_upload_avatar_pg, db, user, file, ext)
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "头像不能超过 10MB")
    d = Path(__file__).resolve().parents[2] / "data" / "assets" / "avatars"
    d.mkdir(parents=True, exist_ok=True)
    fname = f"{user.id.hex[:12]}-{int(datetime.now().timestamp())}.{ext}"
    (d / fname).write_bytes(data)
    url = f"/assets/avatars/{fname}"

    # 历史队列：新头像进队首，保留 5 个，多出的删文件
    try:
        history = _json.loads(user.avatar_history or "[]")
    except Exception:
        history = []
    history = [u for u in history if u != url]
    history.insert(0, url)
    for old in history[5:]:
        old_file = d / old.rsplit("/", 1)[-1]
        old_file.unlink(missing_ok=True)
    history = history[:5]
    user.avatar_history = _json.dumps(history, ensure_ascii=False)
    user.avatar_url = url
    db.commit()
    return _user_out(user)


def _upload_avatar_pg(db, user, file, ext):
    import json
    import mimetypes
    from uuid import uuid4
    from sqlalchemy import select
    from app.services import blob_store
    try:
        user = db.execute(select(User).where(User.id == user.id).with_for_update()
                          .execution_options(populate_existing=True)).scalar_one()
        fname = f'{user.id.hex[:12]}-{uuid4().hex}.{ext}'
        url = '/assets/avatars/' + fname
        blob_store.put(db, 'avatars/' + fname, file.file,
                       mimetypes.guess_type(fname)[0] or 'application/octet-stream', 10 * 1024 * 1024)
        try:
            history = json.loads(user.avatar_history or '[]')
        except (ValueError, TypeError):
            history = []
        history = [url] + [u for u in history if u != url]
        for old in history[5:]:
            # Only delete avatar keys; never allow history to name other stores.
            if old.startswith('/assets/avatars/') and '/' not in old.removeprefix('/assets/avatars/'):
                blob_store.delete(db, old.removeprefix('/assets/'))
        user.avatar_history = json.dumps(history[:5], ensure_ascii=False)
        user.avatar_url = url
        db.commit()
    except blob_store.BlobTooLarge as exc:
        db.rollback()
        raise HTTPException(400, '头像不能超过 10MB') from exc
    except Exception:
        db.rollback()
        raise
    return _user_out(user)


@router.get("/avatars")
def avatar_history(user: User = Depends(current_user)):
    """近 5 个历史头像（当前在队首）"""
    import json as _json
    try:
        return _json.loads(user.avatar_history or "[]")
    except Exception:
        return []


# ---------- 邮箱验证码（绑定/换绑验证） ----------
CODE_MINUTES = 10
def _mail_for(purpose: str, code: str) -> tuple[str, str]:
    """按用途返回 (subject, html)——Stella 夜色 + 樱粉大码 + 喵~"""
    if purpose == "reset":
        subject = "StellaHaven 密码重置码喵~"
        line = "有人在重置你的密码喵~ 是你本人就用这个码（10 分钟内有效）："
    elif purpose == "bind":
        subject = "StellaHaven 邮箱验证码喵~"
        line = "你的验证码喵~（10 分钟内有效）"
    else:  # login
        subject = "StellaHaven 登录验证码喵~"
        line = "你的登录验证码喵~（10 分钟内有效，输完直接进港不用密码）："
    html = f"""
    <div style="font-family:Georgia,serif;background:#0d1017;padding:32px;border-radius:16px;color:#e8ecf4;max-width:420px">
      <div style="font-size:22px;color:#c9d4e8;letter-spacing:3px">✦ StellaHaven</div>
      <div style="margin-top:14px;font-size:14px;color:#9aa3b5;line-height:1.9">{line}</div>
      <div style="margin:18px 0;font-size:32px;letter-spacing:10px;color:#e8a0bf;font-weight:700">{code}</div>
      <div style="font-size:12px;color:#5c6474">不是你操作的就不要理这封信喵。—— 港务局</div>
    </div>
    """
    return subject, html


@router.get("/email-service")
def email_service_status(user: User = Depends(current_user)):
    """登录用户可查：邮箱服务状态（configured=填了配置，enabled=开了开关，ready=两者都齐）"""
    from app.routers.admin_email import _load as load_cfg
    cfg = load_cfg()
    configured = bool(cfg.get("host") and cfg.get("username") and cfg.get("password"))
    enabled = bool(cfg.get("enabled"))
    return {"ready": configured and enabled, "configured": configured, "enabled": enabled}


class SendCodeIn(BaseModel):
    email: str


def _verified_email_owner(db, email):
    from app.services.admin_security import owner_id
    user = db.get(User, owner_id(db))
    if not user or not user.is_active or not user.email_verified or user.email != email:
        raise HTTPException(404, "账号不可用")
    return user


def _send_purpose_code(db, email, purpose, *, resend=False):
    from app.routers.admin_email import _load, _send
    from app.services.email_attempts import issue_code
    cfg = _load()
    if not (cfg.get("enabled") and cfg.get("host") and cfg.get("username") and cfg.get("password")):
        raise HTTPException(503, "邮箱服务还没配置")
    if "@" not in email or len(email) > 254:
        raise HTTPException(400, "邮箱格式不对喵~")
    code = issue_code(db, email, purpose, resend=resend)
    if code is None:
        return {"ok": True, "already_sent": True, "minutes": CODE_MINUTES}
    subject, html = _mail_for(purpose, code)
    try:
        _send(cfg, email, subject, html)
    except Exception as exc:
        raise HTTPException(502, f"发送失败：{type(exc).__name__}") from None
    return {"ok": True, "minutes": CODE_MINUTES}


@router.post("/email/send-code")
def send_email_code(data: SendCodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _assert_identifiers_free(db, email=data.email.strip(), exclude=user.id)
    return _send_purpose_code(db, data.email.strip(), "bind")


class VerifyCodeIn(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=64)


# ---------- 忘记密码（邮箱服务开启时可用） ----------
class ForgotIn(BaseModel):
    email: str


@router.post("/forgot")
def forgot_password(data: ForgotIn, db: Session = Depends(get_db)):
    email = data.email.strip()
    from app.services.admin_security import owner_id
    user = db.get(User, owner_id(db))
    if user.email == email and user.email_verified and user.is_active:
        return _send_purpose_code(db, email, "reset")
    return {"ok": True, "minutes": CODE_MINUTES}


class ResetIn(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=64)
    new_password: str


# ---------- 验证码登录（免密：邮箱+码直接进） ----------
class LoginCodeSendIn(BaseModel):
    email: str


@router.post("/login-code/send")
def send_login_code(data: LoginCodeSendIn, db: Session = Depends(get_db)):
    email = data.email.strip()
    from app.services.admin_security import owner_id
    user = db.get(User, owner_id(db))
    if user.email != email or not user.is_active:
        raise HTTPException(404, "没有这个账号喵~ 检查下邮箱有没有输错")
    if not user.email_verified:
        raise HTTPException(409, "这个邮箱绑定了但还没验证喵~ 先去密码登录，再到「我的资料」重新验证邮箱")
    return _send_purpose_code(db, email, "login")


class LoginCodeIn(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=64)
    remember: bool = False
    device: str | None = None


@router.post("/login-code")
def login_by_code(data: LoginCodeIn, request: Request, response: Response, db: Session = Depends(get_db)):
    from app.services.email_attempts import consume_code
    user = _verified_email_owner(db, data.email.strip())
    consume_code(db, data.email.strip(), "login", data.code)
    _create_session(db, user, request, response, remember=data.remember, device=data.device)
    db.commit()
    return _user_out(user)


@router.post("/reset")
def reset_password(data: ResetIn, db: Session = Depends(get_db)):
    """凭重置码改密码：全部会话下线"""
    from app.services.email_attempts import consume_code
    if not 6 <= len(data.new_password) <= 256:
        raise HTTPException(400, "新密码须为6至256位")
    user = _verified_email_owner(db, data.email.strip())
    from app.services.admin_security import require_owner, daily_password_changed
    require_owner(db, user)
    consume_code(db, data.email.strip(), "reset", data.code)
    daily_password_changed(db, data.new_password)
    user.password_hash = hash_password(data.new_password)
    db.query(AuthSession).filter(AuthSession.user_id == user.id).update({"revoked": True})
    db.commit()
    return {"ok": True, "hint": "密码已重置，全部会话已下线，用新密码登录喵~"}


@router.post("/email/verify")
def verify_email_code(data: VerifyCodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services.email_attempts import consume_code
    _assert_identifiers_free(db, email=data.email.strip(), exclude=user.id)
    consume_code(db, data.email.strip(), "bind", data.code)
    user.email = data.email.strip()
    user.email_verified = True
    db.commit()
    return _user_out(user)


class ResendIn(BaseModel):
    email: str
    purpose: Literal["login", "bind", "reset"] = "login"


@router.post("/email/resend")
def resend_code(data: ResendIn, request: Request, db: Session = Depends(get_db)):
    if data.purpose == "bind":
        user = current_user(request, db)
        _assert_identifiers_free(db, email=data.email.strip(), exclude=user.id)
    else:
        _verified_email_owner(db, data.email.strip())
    return _send_purpose_code(db, data.email.strip(), data.purpose, resend=True)


class AvatarPickIn(BaseModel):
    url: str


@router.post("/avatar-pick")
def pick_avatar(data: AvatarPickIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """从历史头像里选一个当当前头像（提到队首）"""
    import json as _json
    from app.services import blob_store
    if blob_store.enabled():
        from sqlalchemy import select
        user = db.execute(select(User).where(User.id == user.id).with_for_update()
                          .execution_options(populate_existing=True)).scalar_one()
    try:
        history = _json.loads(user.avatar_history or "[]")
    except Exception:
        history = []
    if data.url not in history:
        raise HTTPException(404, "这个头像不在你的历史记录里")
    history.remove(data.url)
    history.insert(0, data.url)
    user.avatar_history = _json.dumps(history, ensure_ascii=False)
    user.avatar_url = data.url
    db.commit()
    return _user_out(user)


# Explicit tombstones close legacy clients without reviving multi-user behavior.
@router.api_route('/invites', methods=['GET', 'POST'])
@router.post('/register-invite')
def retired_invitation_api():
    raise HTTPException(410, '单用户模式已移除邀请与新增账号功能')


# Historical invitation/user rows remain for non-destructive migration.

@router.get("/sessions")
def my_sessions(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db),
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    """登录记录：普通用户看自己的；admin 看所有人的（带归属）"""
    raw = request.cookies.get(RT_COOKIE)
    current_hash = hash_refresh(raw) if raw else None
    q = db.query(AuthSession).filter(_active_sessions())
    q = q.filter(AuthSession.user_id == user.id)
    rows = q.order_by(AuthSession.last_seen.desc(), AuthSession.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    out = []
    for s in rows:
        owner = db.get(User, s.user_id)
        out.append({
            "id": str(s.id),
            "device": s.device,
            "ip": s.ip,
            "remember": s.remember,
            "created_at": utc(s.created_at).isoformat(),
            "last_seen": utc(s.last_seen).isoformat(),
            "current": s.refresh_hash == current_hash,
            "owner": owner.display_name if owner else "?",
            "mine": s.user_id == user.id,
        })
    return out


def _active_sessions():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return and_(AuthSession.revoked == False, or_(  # noqa: E712
        and_(AuthSession.remember == True, AuthSession.created_at > now - timedelta(days=30)),
        and_(AuthSession.remember == False, AuthSession.last_seen > now - timedelta(minutes=30))))


@router.get("/sessions/history")
def session_history(user: User = Depends(current_user), db: Session = Depends(get_db),
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    q = db.query(AuthSession).filter(~_active_sessions())
    q = q.filter(AuthSession.user_id == user.id)
    total = q.count()
    rows = q.order_by(AuthSession.created_at.desc(), AuthSession.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [{"id": str(s.id), "device": s.device, "ip": s.ip,
        "remember": s.remember, "created_at": utc(s.created_at).isoformat(),
        "last_seen": utc(s.last_seen).isoformat(), "expires_at": expires_at(s).isoformat(),
        "state": "revoked" if s.revoked else "expired", "mine": s.user_id == user.id,
        "owner": s.user.display_name, "current": False} for s in rows],
        "total": total, "page": page, "page_size": page_size}


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """踢下线：吊销指定会话（只能操作自己的；admin 可管别人的）"""
    session = db.get(AuthSession, session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    if session.user_id != user.id:
        raise HTTPException(403, "只能吊销自己的会话")
    session.revoked = True
    db.commit()
    return {"ok": True}


def _user_out(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "avatar_url": user.avatar_url,
        "home_bg": user.home_bg,
        "email": user.email,
        "email_verified": user.email_verified,
    }
