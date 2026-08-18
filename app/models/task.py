"""任务域：打流（iperf3/speedtest）、MTR、命令执行——工具页发起，结果存 JSON。"""
from datetime import datetime
from sqlalchemy import ForeignKey, Integer, DateTime, String, Text
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from app.models import Base, Mapped, mapped_column


class IperfTask(Base):
    """打流任务：自有服务器 iperf3 互打，或公共 speedtest 测公网。"""

    __tablename__ = "iperf_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_node_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("nodes.id"), nullable=True)  # NULL=公共 speedtest
    client_node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)       # iperf3 / speedtest
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="forward")  # forward / reverse（iperf3 -R）
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=10)   # 时长秒（-t，bytes 为空时用）
    bytes: Mapped[str | None] = mapped_column(String(16), nullable=True)         # 数据量（-n，如 100M），与时长二选一
    parallel: Mapped[int] = mapped_column(Integer, nullable=False, default=1)    # 并行流数
    udp: Mapped[bool] = mapped_column(nullable=False, default=False)             # UDP 模式（-u）
    bitrate: Mapped[str | None] = mapped_column(String(16), nullable=True)       # UDP 目标带宽（-b，如 100M）
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=5201)     # server 监听端口（-p）
    window: Mapped[str | None] = mapped_column(String(16), nullable=True)        # TCP 窗口（-w，如 256K）
    length: Mapped[str | None] = mapped_column(String(16), nullable=True)        # 缓冲区长度（-l）
    omit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)        # 预热忽略前 N 秒（-O）
    zerocopy: Mapped[bool] = mapped_column(nullable=False, default=False)        # 零拷贝（-Z）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending / running / done / failed
    server_started: Mapped[bool] = mapped_column(nullable=False, default=False)  # server 端是否已起 -s（独立标记，避免 server/client 竞争领取互抢）
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 含 interval 时序，供实时曲线
    progress_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 实时进度：[{ts, bitrate}, ...]，client agent 每秒回传
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ComponentTask(Base):
    """组件代装任务：前端点「安装」→ agent 轮询领取 → 执行安装 → 回传结果。"""

    __tablename__ = "component_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"), nullable=False)
    component: Mapped[str] = mapped_column(String(16), nullable=False)  # iperf3 / speedtest
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending / running / done / failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MtrTask(Base):
    """MTR 任务：从某节点到目标的逐跳路径/丢包/延迟。"""

    __tablename__ = "mtr_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"), nullable=False)
    target: Mapped[str] = mapped_column(String(256), nullable=False)
    protocol: Mapped[str] = mapped_column(String(8), nullable=False, default="icmp")  # icmp / udp / tcp
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending / running / done / failed
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 逐跳结果
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentCommand(Base):
    """命令执行记录（B 方案：命令执行框，非交互式终端）。"""

    __tablename__ = "agent_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending / running / done / failed
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NetTask(Base):
    """网络操作任务：改 IP（带回退）、防火墙修改。高危操作，agent 本地自包含执行回退。"""

    __tablename__ = "net_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # ip_change / firewall_apply
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {iface,new_ip,prefix,gateway,ping_target} 或 {tool,rule}
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending / running / done / failed
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {ok, rolled_back, old_ip, new_ip, error}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
