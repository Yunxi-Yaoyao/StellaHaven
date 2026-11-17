"""监控项域：监控项定义 + 探测结果（可用率历史）。"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import ForeignKey, Integer, BigInteger, DateTime, String, UniqueConstraint, Boolean, true
from sqlalchemy.sql import func
from app.models import Base, Mapped, mapped_column


class Monitor(Base):
    """监控项定义：TCP/UDP/ICMP/HTTP(s) 可达性探测。

    node_id 必填：探测源节点（统一 agent 探测，无中心探测）。
    """

    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    type: Mapped[str] = mapped_column(String(16), nullable=False)    # ping / tcp / udp / http / https
    target: Mapped[str] = mapped_column(String(256), nullable=False)  # IP、IP:port、URL
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=60)   # 探测间隔秒
    timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=5)     # 超时秒
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")  # up / down / unknown
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_latency_ms: Mapped[float | None] = mapped_column(nullable=True)


class MonitorGroup(Base):
    """Explicit display grouping only; does not create probes or rewrite child history."""
    __tablename__ = 'monitor_groups'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Immutable archive identity: names, members and numeric IDs are not proof.
    stable_uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, default=lambda: str(uuid4()))
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    failure_policy: Mapped[str] = mapped_column(String(8), nullable=False, default='any')
    rotation_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MonitorGroupMember(Base):
    __tablename__ = 'monitor_group_members'
    group_id: Mapped[int] = mapped_column(ForeignKey('monitor_groups.id', ondelete='CASCADE'), primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey('monitors.id', ondelete='CASCADE'), primary_key=True, unique=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class MonitorCheck(Base):
    """探测结果：每次探测插一行，算可用率历史（成功/失败 + 延迟 + 丢包）。"""

    __tablename__ = "monitor_checks"
    __table_args__ = (
        # 幂等兜底（与补传同理）
        UniqueConstraint("monitor_id", "ts", name="uq_monitor_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    monitor_id: Mapped[int] = mapped_column(Integer, ForeignKey("monitors.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    success: Mapped[bool] = mapped_column(nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(nullable=True)
    loss_pct: Mapped[float | None] = mapped_column(nullable=True)   # ping 丢包率
