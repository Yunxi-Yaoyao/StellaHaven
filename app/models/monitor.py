"""监控项域：监控项定义 + 探测结果（可用率历史）。"""
from datetime import datetime
from sqlalchemy import ForeignKey, Integer, BigInteger, DateTime, String, UniqueConstraint
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
    type: Mapped[str] = mapped_column(String(16), nullable=False)    # ping / tcp / udp / http / https
    target: Mapped[str] = mapped_column(String(256), nullable=False)  # IP、IP:port、URL
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=60)   # 探测间隔秒
    timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=5)     # 超时秒
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")  # up / down / unknown
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_latency_ms: Mapped[float | None] = mapped_column(nullable=True)


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
