"""Stella 邮箱服务（admin）：SMTP 配置 + 测试邮件。
用于网站外发邮件（重置密码验证码等）。配置落盘 data/email_config.json。
"""
import json
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.auth import admin_user
from app.models.user import User

router = APIRouter(prefix="/admin/email", tags=["admin-email"])

CONFIG_FILE = Path(__file__).resolve().parents[2] / "data" / "email_config.json"

DEFAULTS = {
    "host": "",
    "port": 465,
    "username": "",
    "password": "",
    "from_name": "StellaHaven 港务局",
    "enabled": False,
}


def _load() -> dict:
    if not CONFIG_FILE.exists():
        return dict(DEFAULTS)
    cfg = dict(DEFAULTS)
    cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    return cfg


def _save(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


class EmailConfigIn(BaseModel):
    host: str
    port: int = 465
    username: str
    password: str
    from_name: str = "StellaHaven 港务局"
    enabled: bool = False


@router.get("/config")
def get_config(user: User = Depends(admin_user)):
    cfg = _load()
    cfg["password"] = "••••••" if cfg.get("password") else ""  # 掩码回显
    return cfg


@router.put("/config")
def put_config(data: EmailConfigIn, user: User = Depends(admin_user)):
    cfg = data.model_dump()
    if cfg["password"] == "••••••":  # 没动掩码就保留旧密钥
        cfg["password"] = _load().get("password", "")
    _save(cfg)
    return {"ok": True}


class TestMailIn(BaseModel):
    to: str


def _send(cfg: dict, to: str, subject: str, html: str) -> None:
    msg = MIMEText(html, "html", "utf-8")
    # formataddr 才是 RFC 合规的 From（Header() 直接 str 会折行，QQ 按 RFC5322 拒收）
    msg["From"] = formataddr((str(Header(cfg.get("from_name") or "StellaHaven", "utf-8")), cfg["username"]))
    msg["To"] = to
    msg["Subject"] = Header(subject, "utf-8")
    if int(cfg["port"]) == 465:
        smtp = smtplib.SMTP_SSL(cfg["host"], int(cfg["port"]), timeout=15)
    else:
        smtp = smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=15)
        smtp.starttls()
    with smtp:
        smtp.login(cfg["username"], cfg["password"])
        smtp.sendmail(cfg["username"], [to], msg.as_string())


@router.post("/test")
def test_mail(data: TestMailIn, user: User = Depends(admin_user)):
    cfg = _load()
    if not cfg.get("host") or not cfg.get("username"):
        raise HTTPException(400, "先填邮箱服务配置喵~")
    html = """
    <div style="font-family:Georgia,serif;background:#0d1017;padding:32px;border-radius:16px;color:#e8ecf4">
      <div style="font-size:22px;color:#c9d4e8;letter-spacing:3px">✦ StellaHaven</div>
      <div style="margin-top:14px;font-size:14px;color:#9aa3b5;line-height:1.9">
        港务局试航成功喵~<br/>
        这封信从 Stella 的邮箱服务出发，安全抵达了你的信箱。<br/>
        以后重置密码的验证码也走这条路。
      </div>
      <div style="margin-top:18px;font-size:12px;color:#5c6474">—— 娅娅代笔 · 夜有星辰，晨有曦光</div>
    </div>
    """
    try:
        _send(cfg, data.to, "StellaHaven 邮箱服务测试喵~", html)
    except Exception as e:
        raise HTTPException(502, f"发送失败：{type(e).__name__}: {e}")
    return {"ok": True, "to": data.to}
