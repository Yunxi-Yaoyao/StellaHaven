"""认证：注册/登录/刷新/登出/我/登录记录。

- 访问令牌 30min（httpOnly cookie: stella_at），刷新令牌走 auth_sessions 表（cookie: stella_rt）
- 首个注册用户自动成为 admin
- 允许多地同时登录：一条会话一行记录，可单独吊销（踢下线）
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, AuthSession, EmailCode
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
    sid = claims.get("sid")
    if sid:
        session = db.get(AuthSession, UUID(sid))
        if not session or session.revoked:
            raise HTTPException(401, "会话已下线")
    user = db.get(User, UUID(claims["uid"]))
    if not user or not user.is_active:
        raise HTTPException(401, "账号不可用")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return user


# ---------- 数据隔离：资源归属校验 ----------
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
    response.set_cookie(AT_COOKIE, at, max_age=ACCESS_MINUTES * 60,
                        httponly=True, samesite="lax", path="/")
    # 记住我 → refresh cookie 30 天；否则会话级（无 max_age）
    rt_raw = session._rt_raw  # type: ignore[attr-defined]
    kwargs = {"httponly": True, "samesite": "lax", "path": "/"}
    if remember:
        kwargs["max_age"] = REFRESH_DAYS * 86400
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
    has_admin = db.query(User).filter(User.is_admin == True).count() > 0  # noqa: E712
    cfg = load_cfg()
    email_on = bool(cfg.get("enabled") and cfg.get("host") and cfg.get("username") and cfg.get("password"))
    return {"has_users": total > 0, "initialized": has_admin, "email_enabled": email_on}


@router.post("/register", status_code=201)
def register(data: RegisterIn, response: Response, request: Request, db: Session = Depends(get_db)):
    """公开注册仅限两种情况：①初始化（无任何账号）②老账号认领（遗留账号密码为空）。
    其余一律走邀请链接。"""
    username = data.username.strip()
    if not username or len(data.password) < 6:
        raise HTTPException(400, "用户名不能为空，密码至少 6 位")

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        # 老账号认领：密码为空的遗留账号允许补设密码接管
        if existing.password_hash != "":
            raise HTTPException(409, "用户名已存在")
        new_name = (data.display_name or "").strip()
        _assert_identifiers_free(db, display_name=new_name, exclude=existing.id)
        existing.password_hash = hash_password(data.password)
        if new_name:
            existing.display_name = new_name
        if db.query(User).filter(User.is_admin == True).count() == 0:  # noqa: E712
            existing.is_admin = True
        _create_session(db, existing, request, response, remember=True)
        db.commit()
        return _user_out(existing)

    if db.query(User).count() > 0:
        raise HTTPException(403, "注册通道已关闭，请向管理员要邀请链接喵~")
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
    rt_raw, rt_hash = make_refresh_token()
    # 真实 IP：反代/开发代理后面读 X-Forwarded-For 第一跳
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
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


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(RT_COOKIE)
    if not raw:
        raise HTTPException(401, "无刷新令牌")
    session = db.query(AuthSession).filter(AuthSession.refresh_hash == hash_refresh(raw)).first()
    if not session or session.revoked:
        raise HTTPException(401, "会话已失效")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "账号不可用")
    # 旋转：旧 refresh 作废，发新的
    rt_raw, rt_hash = make_refresh_token()
    session.refresh_hash = rt_hash
    session.last_seen = datetime.now(timezone.utc)
    session._rt_raw = rt_raw  # type: ignore[attr-defined]
    _issue_cookies(response, user, session, session.remember)
    db.commit()
    return _user_out(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(RT_COOKIE)
    if raw:
        session = db.query(AuthSession).filter(AuthSession.refresh_hash == hash_refresh(raw)).first()
        if session:
            session.revoked = True
            db.commit()
    response.delete_cookie(AT_COOKIE, path="/")
    response.delete_cookie(RT_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _user_out(user)


class ProfileIn(BaseModel):
    display_name: str | None = None
    email: str | None = None


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
    data = await file.read()
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
RESEND_WINDOW_MINUTES = 5


def _code_expired(row) -> bool:
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    return expires < datetime.now(timezone.utc)


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


def _valid_code(db: Session, email: str) -> EmailCode | None:
    """邮箱当前在有效期内的验证码（没有或过期返回 None）"""
    row = db.query(EmailCode).filter(EmailCode.email == email).first()
    if not row or _code_expired(row):
        return None
    return row


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


@router.post("/email/send-code")
def send_email_code(data: SendCodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """发 6 位验证码到指定邮箱（10 分钟有效）。服务未配置 → 503 + reason"""
    import random
    from app.routers.admin_email import _load as load_cfg, _send

    cfg = load_cfg()
    if not (cfg.get("enabled") and cfg.get("host") and cfg.get("username") and cfg.get("password")):
        raise HTTPException(503, "邮箱服务还没配置")

    email = data.email.strip()
    if "@" not in email:
        raise HTTPException(400, "邮箱格式不对喵~")
    if _valid_code(db, email):
        return {"ok": True, "already_sent": True, "minutes": CODE_MINUTES}
    code = f"{random.randint(0, 999999):06d}"
    db.query(EmailCode).filter(EmailCode.email == email).delete()  # 同邮箱只留最新
    db.add(EmailCode(email=email, code=code,
                     expires_at=datetime.now(timezone.utc) + timedelta(minutes=CODE_MINUTES)))
    db.commit()

    html = f"""
    <div style="font-family:Georgia,serif;background:#0d1017;padding:32px;border-radius:16px;color:#e8ecf4;max-width:420px">
      <div style="font-size:22px;color:#c9d4e8;letter-spacing:3px">✦ StellaHaven</div>
      <div style="margin-top:14px;font-size:14px;color:#9aa3b5;line-height:1.9">你的验证码喵~（10 分钟内有效）</div>
      <div style="margin:18px 0;font-size:32px;letter-spacing:10px;color:#e8a0bf;font-weight:700">{code}</div>
      <div style="font-size:12px;color:#5c6474">不是你操作的就不要理这封信喵。—— 港务局</div>
    </div>
    """
    try:
        _send(cfg, email, "StellaHaven 邮箱验证码喵~", html)
    except Exception as e:
        raise HTTPException(502, f"发送失败：{type(e).__name__}")
    return {"ok": True, "minutes": CODE_MINUTES}


class VerifyCodeIn(BaseModel):
    email: str
    code: str


# ---------- 忘记密码（邮箱服务开启时可用） ----------
class ForgotIn(BaseModel):
    email: str


@router.post("/forgot")
def forgot_password(data: ForgotIn, db: Session = Depends(get_db)):
    """发重置码到账号绑定的已验证邮箱。无论账号存不存在都回 ok（不暴露账号存在性）"""
    import random
    from app.routers.admin_email import _load as load_cfg, _send

    cfg = load_cfg()
    if not (cfg.get("enabled") and cfg.get("host") and cfg.get("username") and cfg.get("password")):
        raise HTTPException(503, "邮箱服务还没配置")

    email = data.email.strip()
    user = db.query(User).filter(User.email == email, User.email_verified == True).first()  # noqa: E712
    if user:
        if _valid_code(db, email):
            return {"ok": True, "already_sent": True, "minutes": CODE_MINUTES}
        code = f"{random.randint(0, 999999):06d}"
        db.query(EmailCode).filter(EmailCode.email == email).delete()
        db.add(EmailCode(email=email, code=code,
                         expires_at=datetime.now(timezone.utc) + timedelta(minutes=CODE_MINUTES)))
        db.commit()
        html = f"""
        <div style="font-family:Georgia,serif;background:#0d1017;padding:32px;border-radius:16px;color:#e8ecf4;max-width:420px">
          <div style="font-size:22px;color:#c9d4e8;letter-spacing:3px">✦ StellaHaven</div>
          <div style="margin-top:14px;font-size:14px;color:#9aa3b5;line-height:1.9">有人在重置你的密码喵~ 是你本人就用这个码（10 分钟内有效）：</div>
          <div style="margin:18px 0;font-size:32px;letter-spacing:10px;color:#e8a0bf;font-weight:700">{code}</div>
          <div style="font-size:12px;color:#5c6474">不是你操作的赶紧改密码喵。—— 港务局</div>
        </div>
        """
        try:
            _send(cfg, email, "StellaHaven 密码重置码喵~", html)
        except Exception as e:
            raise HTTPException(502, f"发送失败：{type(e).__name__}")
    return {"ok": True, "minutes": CODE_MINUTES}


class ResetIn(BaseModel):
    email: str
    code: str
    new_password: str


# ---------- 验证码登录（免密：邮箱+码直接进） ----------
class LoginCodeSendIn(BaseModel):
    email: str


@router.post("/login-code/send")
def send_login_code(data: LoginCodeSendIn, db: Session = Depends(get_db)):
    """发登录验证码。账号不存在 / 邮箱未验证 都明确提示（个人工具，不藏存在性）"""
    import random
    from app.routers.admin_email import _load as load_cfg, _send

    cfg = load_cfg()
    if not (cfg.get("enabled") and cfg.get("host") and cfg.get("username") and cfg.get("password")):
        raise HTTPException(503, "邮箱服务还没配置")

    email = data.email.strip()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(404, "没有这个账号喵~ 检查下邮箱有没有输错")
    if not user.email_verified:
        raise HTTPException(409, "这个邮箱绑定了但还没验证喵~ 先去密码登录，再到「我的资料」重新验证邮箱")
    if _valid_code(db, email):
        return {"ok": True, "already_sent": True, "minutes": CODE_MINUTES}

    code = f"{random.randint(0, 999999):06d}"
    db.query(EmailCode).filter(EmailCode.email == email).delete()
    db.add(EmailCode(email=email, code=code,
                     expires_at=datetime.now(timezone.utc) + timedelta(minutes=CODE_MINUTES)))
    db.commit()
    html = f"""
    <div style="font-family:Georgia,serif;background:#0d1017;padding:32px;border-radius:16px;color:#e8ecf4;max-width:420px">
      <div style="font-family:Georgia,serif;font-size:22px;color:#c9d4e8;letter-spacing:3px">✦ StellaHaven</div>
      <div style="margin-top:14px;font-size:14px;color:#9aa3b5;line-height:1.9">你的登录验证码喵~（10 分钟内有效，输完直接进港不用密码）：</div>
      <div style="margin:18px 0;font-size:32px;letter-spacing:10px;color:#e8a0bf;font-weight:700">{code}</div>
      <div style="font-size:12px;color:#5c6474">不是你操作的就不要理这封信喵。—— 港务局</div>
    </div>
    """
    try:
        _send(cfg, email, "StellaHaven 登录验证码喵~", html)
    except Exception as e:
        raise HTTPException(502, f"发送失败：{type(e).__name__}")
    return {"ok": True, "minutes": CODE_MINUTES}


class LoginCodeIn(BaseModel):
    email: str
    code: str
    remember: bool = False
    device: str | None = None


@router.post("/login-code")
def login_by_code(data: LoginCodeIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """验证码免密登录：码对就进"""
    row = db.query(EmailCode).filter(EmailCode.email == data.email.strip()).first()
    if not row:
        raise HTTPException(404, "没发过验证码，先点发送喵~")
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(410, "验证码过期了，重新发一个喵~")
    if row.code != data.code.strip():
        raise HTTPException(401, "验证码不对喵~")
    user = db.query(User).filter(User.email == data.email.strip(), User.email_verified == True).first()  # noqa: E712
    if not user or not user.is_active:
        raise HTTPException(404, "账号不可用")
    db.delete(row)
    _create_session(db, user, request, response, remember=data.remember, device=data.device)
    db.commit()
    return _user_out(user)


@router.post("/reset")
def reset_password(data: ResetIn, db: Session = Depends(get_db)):
    """凭重置码改密码：全部会话下线"""
    row = db.query(EmailCode).filter(EmailCode.email == data.email.strip()).first()
    if not row:
        raise HTTPException(404, "没发过重置码，先点发送喵~")
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(410, "重置码过期了，重新发一个喵~")
    if row.code != data.code.strip():
        raise HTTPException(401, "重置码不对喵~")
    if len(data.new_password) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    user = db.query(User).filter(User.email == data.email.strip(), User.email_verified == True).first()  # noqa: E712
    if not user:
        raise HTTPException(404, "账号不存在")
    user.password_hash = hash_password(data.new_password)
    db.query(AuthSession).filter(AuthSession.user_id == user.id).update({"revoked": True})
    db.delete(row)
    db.commit()
    return {"ok": True, "hint": "密码已重置，全部会话已下线，用新密码登录喵~"}


@router.post("/email/verify")
def verify_email_code(data: VerifyCodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """验证码校验：过了就绑定+标绿"""
    row = db.query(EmailCode).filter(EmailCode.email == data.email.strip()).first()
    if not row:
        raise HTTPException(404, "没发过验证码，先点发送喵~")
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(410, "验证码过期了，重新发一个喵~")
    if row.code != data.code.strip():
        raise HTTPException(401, "验证码不对喵~")
    user.email = data.email.strip()
    user.email_verified = True
    db.delete(row)
    db.commit()
    return _user_out(user)


class ResendIn(BaseModel):
    email: str
    purpose: str = "login"  # login | bind | reset（决定邮件文案）


@router.post("/email/resend")
def resend_code(data: ResendIn, db: Session = Depends(get_db)):
    """重新发送验证码：5 分钟内只允许一次；换新码、旧码作废"""
    import random
    from app.routers.admin_email import _load as load_cfg, _send

    cfg = load_cfg()
    if not (cfg.get("enabled") and cfg.get("host") and cfg.get("username") and cfg.get("password")):
        raise HTTPException(503, "邮箱服务还没配置")

    email = data.email.strip()
    row = db.query(EmailCode).filter(EmailCode.email == email).first()
    if not row:
        raise HTTPException(404, "先发一次验证码喵~")
    if row.resent_at:
        rt = row.resent_at if row.resent_at.tzinfo else row.resent_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - rt).total_seconds() < RESEND_WINDOW_MINUTES * 60:
            raise HTTPException(429, "喵~ 5 分钟内只能重发一次，先用刚才那个码")

    code = f"{random.randint(0, 999999):06d}"
    row.code = code
    row.expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_MINUTES)
    row.resent_at = datetime.now(timezone.utc)
    db.commit()
    subject, html = _mail_for(data.purpose, code)
    try:
        _send(cfg, email, subject, html)
    except Exception as e:
        raise HTTPException(502, f"发送失败：{type(e).__name__}")
    return {"ok": True, "minutes": CODE_MINUTES}


class AvatarPickIn(BaseModel):
    url: str


@router.post("/avatar-pick")
def pick_avatar(data: AvatarPickIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """从历史头像里选一个当当前头像（提到队首）"""
    import json as _json
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


# ---------- 邀请链接（初始化后唯一的注册通道：30min、一链一人） ----------
INVITE_MINUTES = 30


class InviteOut(BaseModel):
    token: str
    created_at: str
    expires_at: str
    used: bool


@router.post("/invites", status_code=201)
def create_invite(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    """admin 生成注册链接"""
    from secrets import token_urlsafe
    from app.models.user import Invite

    inv = Invite(
        token=token_urlsafe(24),
        created_by=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=INVITE_MINUTES),
    )
    db.add(inv)
    db.commit()
    return {"token": inv.token, "url": f"/invite/{inv.token}", "expires_in_minutes": INVITE_MINUTES}


@router.get("/invites")
def list_invites(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    from app.models.user import Invite

    now = datetime.now(timezone.utc)
    rows = db.query(Invite).order_by(Invite.created_at.desc()).limit(50).all()
    return [
        {
            "token": i.token,
            "created_at": i.created_at.isoformat(),
            "expires_at": i.expires_at.isoformat(),
            "used": i.used_by is not None,
            "expired": i.expires_at.replace(tzinfo=timezone.utc) < now if i.expires_at.tzinfo is None else i.expires_at < now,
        }
        for i in rows
    ]


class InviteRegisterIn(BaseModel):
    token: str
    username: str
    password: str
    display_name: str | None = None


@router.post("/register-invite", status_code=201)
def register_invite(data: InviteRegisterIn, response: Response, request: Request, db: Session = Depends(get_db)):
    """凭邀请链接注册：30min 内、未使用、一链一人"""
    from app.models.user import Invite

    inv = db.query(Invite).filter(Invite.token == data.token).first()
    if not inv:
        raise HTTPException(404, "邀请链接不存在")
    if inv.used_by is not None:
        raise HTTPException(410, "这个链接已经被用过了喵~")
    expires = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(410, "链接过期了，找管理员再要一个喵~")

    username = data.username.strip()
    if not username or len(data.password) < 6:
        raise HTTPException(400, "用户名不能为空，密码至少 6 位")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "用户名已存在")
    _assert_identifiers_free(db, username=username, display_name=(data.display_name or username).strip())

    user = User(
        username=username,
        display_name=(data.display_name or username).strip(),
        password_hash=hash_password(data.password),
        is_admin=False,
    )
    db.add(user)
    db.flush()
    inv.used_by = user.id
    inv.used_at = datetime.now(timezone.utc)
    _create_session(db, user, request, response, remember=True)
    db.commit()
    return _user_out(user)


@router.get("/sessions")
def my_sessions(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """登录记录：普通用户看自己的；admin 看所有人的（带归属）"""
    raw = request.cookies.get(RT_COOKIE)
    current_hash = hash_refresh(raw) if raw else None
    q = db.query(AuthSession).filter(AuthSession.revoked == False)  # noqa: E712
    if not user.is_admin:
        q = q.filter(AuthSession.user_id == user.id)
    rows = q.order_by(AuthSession.last_seen.desc()).all()
    out = []
    for s in rows:
        owner = db.get(User, s.user_id)
        out.append({
            "id": str(s.id),
            "device": s.device,
            "ip": s.ip,
            "remember": s.remember,
            "created_at": s.created_at.isoformat(),
            "last_seen": s.last_seen.isoformat(),
            "current": s.refresh_hash == current_hash,
            "owner": owner.display_name if owner else "?",
            "mine": s.user_id == user.id,
        })
    return out


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """踢下线：吊销指定会话（只能操作自己的；admin 可管别人的）"""
    session = db.get(AuthSession, session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    if session.user_id != user.id and not user.is_admin:
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
        "email": user.email,
        "email_verified": user.email_verified,
    }
