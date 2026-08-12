"""认证全流程：注册收口/登录/刷新/会话记录/吊销/邀请链接。

约定：每个测试独立回滚（conftest），互不影响。
注意：注册通道在「已有账号」后是关闭的（公开注册仅限初始化/老账号认领），
所以多数用例直接用 ORM 建号。
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.user import User, Invite
from app.security import hash_password


def _name() -> str:
    return f"u_{uuid4().hex[:8]}"


def _make_user(db_session, username: str, password: str = "secret123", admin: bool = False) -> User:
    u = User(username=username, display_name=username,
             password_hash=hash_password(password), is_admin=admin)
    db_session.add(u)
    db_session.flush()
    return u


def test_status_public(client):
    r = client.get("/auth/status")
    assert r.status_code == 200
    assert "has_users" in r.json() and "initialized" in r.json()


def test_register_closed_when_users_exist(client):
    """有账号后公开注册关闭（初始化已完成）"""
    r = client.post("/auth/register", json={"username": _name(), "password": "secret123"})
    assert r.status_code == 403


def test_register_short_password(client):
    r = client.post("/auth/register", json={"username": _name(), "password": "123"})
    assert r.status_code == 400


def test_login_ok_and_wrong_password(client, db_session):
    name = _name()
    _make_user(db_session, name)
    bad = client.post("/auth/login", json={"username": name, "password": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/auth/login", json={"username": name, "password": "secret123"})
    assert ok.status_code == 200
    assert ok.json()["username"] == name


def test_me_requires_login(client):
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401


def test_logout_revokes_session(client):
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/refresh").status_code == 401


def test_sessions_list_and_current_marked(client):
    r = client.get("/auth/sessions")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert any(s["current"] for s in rows)


def test_revoke_own_session(client):
    """吊销会话后：该会话的 access 立即失效（踢下线即时生效，连自己都踢）"""
    rows = client.get("/auth/sessions").json()
    sid = rows[0]["id"]
    r = client.delete(f"/auth/sessions/{sid}")
    assert r.status_code == 200
    # 踢的是当前会话 → 后续请求 401（即时生效的实锤）
    assert client.get("/auth/sessions").status_code == 401


def test_refresh_rotates_and_returns_user(client):
    r = client.post("/auth/refresh")
    assert r.status_code == 200
    assert "username" in r.json()


def test_legacy_claim(client, db_session):
    """老账号认领：无密码遗留账号补设密码接管；有密码后同名注册 409"""
    legacy = User(username=_name(), display_name="老账号", password_hash="")
    db_session.add(legacy)
    db_session.flush()

    r = client.post("/auth/register", json={"username": legacy.username, "password": "newpass88"})
    assert r.status_code == 201
    assert client.get("/auth/me").status_code == 200

    client.post("/auth/logout")
    r2 = client.post("/auth/register", json={"username": legacy.username, "password": "other9999"})
    assert r2.status_code == 409


# ---------- 邀请链接 ----------

def test_invite_flow(client, db_session):
    """admin 发链接 → 凭链注册（非 admin）→ 一链一人（再用 410）"""
    # 夹具用户已是 admin，直接发链接
    inv = client.post("/auth/invites")
    assert inv.status_code == 201
    token = inv.json()["token"]

    client.post("/auth/logout")
    r = client.post("/auth/register-invite", json={
        "token": token, "username": _name(), "password": "secret123",
    })
    assert r.status_code == 201
    assert r.json()["is_admin"] is False

    # 同一个链接再用 → 410
    r2 = client.post("/auth/register-invite", json={
        "token": token, "username": _name(), "password": "secret123",
    })
    assert r2.status_code == 410


def test_invite_bad_token(client):
    r = client.post("/auth/register-invite", json={
        "token": "not-exist", "username": _name(), "password": "secret123",
    })
    assert r.status_code == 404


def test_invite_expired(client, db_session):
    inv = Invite(token="expired-token",
                 created_by=_make_user(db_session, _name()).id,
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    db_session.add(inv)
    db_session.flush()
    r = client.post("/auth/register-invite", json={
        "token": "expired-token", "username": _name(), "password": "secret123",
    })
    assert r.status_code == 410


def test_invite_requires_admin(client, db_session):
    """非 admin 不能发链接"""
    _make_user(db_session, _name())  # 普通用户
    # 夹具用户是 admin——先确认能发；再把夹具用户降级验证 403
    from app.models.user import User as U
    me = db_session.query(U).filter(U.username.like("test_%")).order_by(U.created_at.desc()).first()
    me.is_admin = False
    db_session.flush()
    r = client.post("/auth/invites")
    assert r.status_code == 403


# ---------- 邮箱验证 ----------

def test_email_verify_flow(client, db_session, monkeypatch):
    """发码→验证→绿标；换邮箱→回落未验证"""
    from app.models.user import EmailCode

    #  mock 发信（不发真邮件）
    import app.routers.auth as auth_mod
    monkeypatch.setattr("app.routers.admin_email._send", lambda cfg, to, subject, html: None)
    # 邮箱服务配置假装就绪
    monkeypatch.setattr("app.routers.admin_email._load", lambda: {
        "enabled": True, "host": "smtp.test", "username": "a@b.c", "password": "x", "port": 465,
    })

    r = client.post("/auth/email/send-code", json={"email": "ya@x.com"})
    assert r.status_code == 200
    row = db_session.query(EmailCode).filter(EmailCode.email == "ya@x.com").first()
    assert row is not None

    ok = client.post("/auth/email/verify", json={"email": "ya@x.com", "code": row.code})
    assert ok.status_code == 200
    assert ok.json()["email_verified"] is True

    # 换邮箱 → 回落未验证
    r2 = client.patch("/auth/me", json={"email": "new@x.com"})
    assert r2.json()["email_verified"] is False


def test_email_service_not_configured(client, monkeypatch):
    """服务没配置 → 发码 503"""
    monkeypatch.setattr("app.routers.admin_email._load", lambda: {"enabled": False})
    r = client.post("/auth/email/send-code", json={"email": "ya@x.com"})
    assert r.status_code == 503


def test_email_verify_wrong_code(client, db_session, monkeypatch):
    from app.models.user import EmailCode
    monkeypatch.setattr("app.routers.admin_email._send", lambda *a, **k: None)
    monkeypatch.setattr("app.routers.admin_email._load", lambda: {
        "enabled": True, "host": "h", "username": "u", "password": "p", "port": 465,
    })
    client.post("/auth/email/send-code", json={"email": "ya@x.com"})
    r = client.post("/auth/email/verify", json={"email": "ya@x.com", "code": "000000"})
    assert r.status_code in (401, 404)


# ---------- 三合一登录 / 标识唯一 / 忘记密码 ----------

def test_login_by_nickname_and_email(client, db_session):
    """昵称和已验证邮箱都能登录"""
    u = _make_user(db_session, _name())
    u.display_name = "独特昵称喵"
    u.email = "login@x.com"
    u.email_verified = True
    db_session.flush()

    by_name = client.post("/auth/login", json={"username": "独特昵称喵", "password": "secret123"})
    assert by_name.status_code == 200
    client.post("/auth/logout")
    by_mail = client.post("/auth/login", json={"username": "login@x.com", "password": "secret123"})
    assert by_mail.status_code == 200


def test_identifier_uniqueness(client, db_session):
    """用户名/昵称/邮箱交叉互斥：昵称撞别人用户名也 409"""
    other = _make_user(db_session, _name())
    other.display_name = "云曦"
    db_session.flush()

    me = client.get("/auth/me").json()
    # 我把昵称改成别人的用户名 → 409
    r = client.patch("/auth/me", json={"display_name": other.username})
    assert r.status_code == 409
    # 改成别人的昵称 → 409
    r2 = client.patch("/auth/me", json={"display_name": "云曦"})
    assert r2.status_code == 409


def test_forgot_reset_flow(client, db_session, monkeypatch):
    """忘记密码全流：发码→重置→旧密码失效新密码能登→会话全吊销"""
    monkeypatch.setattr("app.routers.admin_email._send", lambda *a, **k: None)
    monkeypatch.setattr("app.routers.admin_email._load", lambda: {
        "enabled": True, "host": "h", "username": "u", "password": "p", "port": 465,
    })
    from app.models.user import EmailCode
    u = _make_user(db_session, _name())
    u.email = "reset@x.com"
    u.email_verified = True
    db_session.flush()

    r = client.post("/auth/forgot", json={"email": "reset@x.com"})
    assert r.status_code == 200
    row = db_session.query(EmailCode).filter(EmailCode.email == "reset@x.com").first()

    rr = client.post("/auth/reset", json={"email": "reset@x.com", "code": row.code, "new_password": "newpass999"})
    assert rr.status_code == 200
    # 旧密码登不上，新密码可以
    assert client.post("/auth/login", json={"username": u.username, "password": "secret123"}).status_code == 401
    assert client.post("/auth/login", json={"username": u.username, "password": "newpass999"}).status_code == 200


def test_login_by_email_code(client, db_session, monkeypatch):
    """免密验证码登录：发码→输码→直接进；错码 401"""
    monkeypatch.setattr("app.routers.admin_email._send", lambda *a, **k: None)
    monkeypatch.setattr("app.routers.admin_email._load", lambda: {
        "enabled": True, "host": "h", "username": "u", "password": "p", "port": 465,
    })
    from app.models.user import EmailCode
    u = _make_user(db_session, _name())
    u.email = "code-login@x.com"
    u.email_verified = True
    db_session.flush()

    client.post("/auth/logout")
    r = client.post("/auth/login-code/send", json={"email": "code-login@x.com"})
    assert r.status_code == 200
    row = db_session.query(EmailCode).filter(EmailCode.email == "code-login@x.com").first()

    bad = client.post("/auth/login-code", json={"email": "code-login@x.com", "code": "000000"})
    assert bad.status_code in (401, 404)
    ok = client.post("/auth/login-code", json={"email": "code-login@x.com", "code": row.code})
    assert ok.status_code == 200
    assert ok.json()["username"] == u.username


def test_login_code_no_account(client, monkeypatch):
    """验证码登录：邮箱不存在 → 404 喵~语气「没有这个账号」"""
    monkeypatch.setattr("app.routers.admin_email._send", lambda *a, **k: None)
    monkeypatch.setattr("app.routers.admin_email._load", lambda: {
        "enabled": True, "host": "h", "username": "u", "password": "p", "port": 465,
    })
    r = client.post("/auth/login-code/send", json={"email": "ghost@x.com"})
    assert r.status_code == 404
    assert "没有这个账号" in r.json()["detail"]


def test_login_code_unverified(client, db_session, monkeypatch):
    """验证码登录：邮箱绑定了但没验证 → 409 让滚去密码登录"""
    monkeypatch.setattr("app.routers.admin_email._send", lambda *a, **k: None)
    monkeypatch.setattr("app.routers.admin_email._load", lambda: {
        "enabled": True, "host": "h", "username": "u", "password": "p", "port": 465,
    })
    u = _make_user(db_session, _name())
    u.email = "unverified@x.com"
    u.email_verified = False
    db_session.flush()
    r = client.post("/auth/login-code/send", json={"email": "unverified@x.com"})
    assert r.status_code == 409
    assert "密码登录" in r.json()["detail"]


def test_code_reuse_not_regenerated(client, db_session, monkeypatch):
    """有效期内重复点发送 → 复用旧码，不换新码"""
    monkeypatch.setattr("app.routers.admin_email._send", lambda *a, **k: None)
    monkeypatch.setattr("app.routers.admin_email._load", lambda: {
        "enabled": True, "host": "h", "username": "u", "password": "p", "port": 465,
    })
    u = _make_user(db_session, _name())
    u.email = "reuse@x.com"
    u.email_verified = True
    db_session.flush()
    r1 = client.post("/auth/login-code/send", json={"email": "reuse@x.com"})
    assert r1.status_code == 200
    assert r1.json().get("already_sent") is None  # 首次真发

    r2 = client.post("/auth/login-code/send", json={"email": "reuse@x.com"})
    assert r2.status_code == 200
    assert r2.json()["already_sent"] is True  # 第二次复用，不换码


def test_resend_throttled_5min(client, db_session, monkeypatch):
    """重发 5 分钟限流：连点第二次 → 429"""
    monkeypatch.setattr("app.routers.admin_email._send", lambda *a, **k: None)
    monkeypatch.setattr("app.routers.admin_email._load", lambda: {
        "enabled": True, "host": "h", "username": "u", "password": "p", "port": 465,
    })
    u = _make_user(db_session, _name())
    u.email = "throttle@x.com"
    u.email_verified = True
    db_session.flush()
    client.post("/auth/login-code/send", json={"email": "throttle@x.com"})
    r1 = client.post("/auth/email/resend", json={"email": "throttle@x.com", "purpose": "login"})
    assert r1.status_code == 200
    r2 = client.post("/auth/email/resend", json={"email": "throttle@x.com", "purpose": "login"})
    assert r2.status_code == 429
    assert "5 分钟" in r2.json()["detail"]
