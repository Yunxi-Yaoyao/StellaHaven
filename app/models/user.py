from app.models import Base, Mapped, mapped_column, UUID, uuid4
from datetime import datetime
from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import relationship


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(nullable=False)
    password_hash: Mapped[str] = mapped_column(nullable=False, default="")
    avatar_url: Mapped[str] = mapped_column(nullable=False, default="")  # 用户头像（优先级最高）
    email: Mapped[str] = mapped_column(nullable=False, default="")
    email_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    avatar_history: Mapped[str] = mapped_column(nullable=False, default="[]")  # 近 5 个历史头像 URL，JSON 数组
    home_bg: Mapped[str] = mapped_column(nullable=False, default="")  # 用户自选主页背景 URL（账号级，登录后各用各的）
    is_admin: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthSession(Base):
    """登录记录 = 一条会话。多地同时登录 = 多条并存，可单独吊销。"""

    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_hash: Mapped[str] = mapped_column(unique=True, nullable=False)
    device: Mapped[str] = mapped_column(nullable=False, default="未知设备")  # UA 粗解析
    ip: Mapped[str] = mapped_column(nullable=False, default="")
    remember: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    revoked: Mapped[bool] = mapped_column(nullable=False, default=False)

    user: Mapped[User] = relationship(back_populates="sessions")


class Invite(Base):
    """注册邀请链接：30 分钟过期、一链一人。初始化后唯一的注册通道。"""

    __tablename__ = "invites"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token: Mapped[str] = mapped_column(unique=True, nullable=False, index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)


class EmailCode(Base):
    """邮箱验证码：10 分钟过期，验证完即删。resent_at 记录上次重发时间（5 分钟重发限流）。"""

    __tablename__ = "email_codes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(nullable=False, index=True)
    code: Mapped[str] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    resent_at: Mapped[datetime | None] = mapped_column(nullable=True)
