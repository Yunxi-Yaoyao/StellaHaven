"""节点域：纳管节点 + 时序数据（流量/系统指标/状态事件）。

主键用 int/bigint 而非 UUID：node_metrics 千万级/年，node_id 外键 int 省 4 倍空间。
时间戳统一 timezone=True（timestamptz）：agent 分布 HK/LA，跨时区必须带时区。

status 状态机：pending（已添加未报到）→ online（心跳正常）→ offline（超时）/ removed（移除）。
"""
from datetime import datetime
from sqlalchemy import ForeignKey, Integer, BigInteger, DateTime, String, Text, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from app.models import Base, Mapped, mapped_column


class Node(Base):
    """纳管节点：一台被监控的服务器（含中心自己）"""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)          # 显示名
    platform: Mapped[str] = mapped_column(String(16), nullable=False)      # linux / windows / fnos
    host: Mapped[str] = mapped_column(String(128), nullable=False)         # IP 或 hostname
    arch: Mapped[str | None] = mapped_column(String(32), nullable=True)    # 架构
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 心跳=最后上报时间
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending / online / offline / removed
    token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)  # agent 鉴权凭证（添加节点时生成，安装命令里带）
    interfaces: Mapped[dict | None] = mapped_column(JSONB, nullable=True)          # 网卡清单（注册时上报，含默认出口标记）
    monitored_ifaces: Mapped[dict | None] = mapped_column(JSONB, nullable=True)    # 监控网卡列表（设置勾选后下发）
    storage: Mapped[list | None] = mapped_column(JSONB, nullable=True)             # 存储视图：挂载点列表（容量/已用/占用率/类型，agent 首次上报）
    components: Mapped[dict | None] = mapped_column(JSONB, nullable=True)          # 组件检测状态：{"iperf3": bool, "speedtest": bool}（agent 心跳上报）
    os_name: Mapped[str | None] = mapped_column(String(128), nullable=True)        # 发行版友好名（agent 采集 /etc/os-release PRETTY_NAME）
    sys_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)            # 基本信息面板：{kernel, cpu_model, cpu_cores, load1/5/15, boot_time}
    # ── 标记：内网/公网 + 公网 IP 信息 ──
    net_type: Mapped[str] = mapped_column(String(16), nullable=False, default="internal")  # internal / public
    public_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)               # 公网 IP
    public_ip_source: Mapped[str | None] = mapped_column(String(16), nullable=True)        # auto / manual
    ip_version: Mapped[str | None] = mapped_column(String(8), nullable=True)               # IPv4 / IPv6
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)                  # 地区（中文）
    uninstall_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 卸载状态 pending/running/done/failed（null=未卸载）
    uninstall_error: Mapped[str | None] = mapped_column(Text, nullable=True)          # 卸载异常信息
    installed: Mapped[bool] = mapped_column(nullable=False, default=False)            # 是否装过 agent（托管）。卸载后回 False
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NodeMetric(Base):
    """流量数据：5s 颗粒，按网卡。存增量（bytes），速率现算。"""

    __tablename__ = "node_metrics"
    __table_args__ = (
        # 补传幂等：同一节点同一网卡同一采样时刻唯一
        UniqueConstraint("node_id", "iface", "ts", name="uq_node_metric"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"), nullable=False)
    iface: Mapped[str] = mapped_column(String(32), nullable=False)           # 网卡名
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 采样时间（agent 传，非入库时间）
    rx_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)        # 该 5s 窗口下行字节增量
    tx_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)        # 该 5s 窗口上行字节增量


class NodeSysMetric(Base):
    """系统指标：60s 颗粒（CPU/内存/磁盘，变化慢，不需要 5s）"""

    __tablename__ = "node_sys_metrics"
    __table_args__ = (
        UniqueConstraint("node_id", "ts", name="uq_node_sys_metric"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cpu_pct: Mapped[float | None] = mapped_column(nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(nullable=True)
    disk_pct: Mapped[float | None] = mapped_column(nullable=True)


class NodeStatusEvent(Base):
    """节点状态变化：在线/脱管历史，算可用率用。状态变化时插一行。"""

    __tablename__ = "node_status_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)          # online / offline / removed
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)    # 心跳超时 / 主动下线 / 移除等
