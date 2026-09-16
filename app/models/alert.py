"""告警域：规则 + 当前状态（槽位覆写）+ 事件流水 + 站内通知。

设计定稿（2026-09-16 老婆拍板）：
- 告警是「选择性添加」——用户对某个节点/监控项/WG链路单独加规则，不做全局默认。
- 当前状态槽位覆写（alert_states 一规则一行），历史进 alert_events 流水表。
- 惰性判断：评估挂在已有数据落库路径上（agent心跳/探测结果入库/地图快照保存），不开独立轮询进程。
"""
from datetime import datetime
from sqlalchemy import ForeignKey, Integer, BigInteger, DateTime, String, Boolean, UniqueConstraint
from sqlalchemy.sql import func
from app.models import Base, Mapped, mapped_column

RULE_KINDS = ("node_offline", "monitor_down", "wg_link")
SEVERITIES = ("warning", "critical")


class AlertRule(Base):
    """告警规则：对单个目标（节点/监控项/WG链路）的一类条件。

    target 语义随 kind：
      node_offline → str(node_id)
      monitor_down → str(monitor_id)
      wg_link      → 地图拓扑的 link id（接口对指纹，见 server_map._links）
    """

    __tablename__ = "alert_rules"
    __table_args__ = (
        UniqueConstraint("kind", "target", name="uq_alert_rule"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")  # 显示名快照（节点名/监控项名/链路名）
    link: Mapped[str] = mapped_column(String(128), nullable=False, default="/status")  # 通知跳转的前端路由
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    debounce: Mapped[int] = mapped_column(Integer, nullable=False, default=2)        # 连续 N 次异常才触发
    repeat_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)  # firing 期间重复提醒间隔
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)       # 站内通知永远开，邮件可选
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertState(Base):
    """规则当前状态：槽位覆写，一规则一行。"""

    __tablename__ = "alert_states"

    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("alert_rules.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(String(8), nullable=False, default="ok")  # ok / firing
    consecutive: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 连续异常计数（防抖用）
    last_change_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str | None] = mapped_column(String(256), nullable=True)


class AlertEvent(Base):
    """告警事件流水：触发/恢复各插一行，历史追溯用。"""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False)
    event: Mapped[str] = mapped_column(String(8), nullable=False)  # fired / resolved
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    message: Mapped[str] = mapped_column(String(256), nullable=False, default="")


class Notification(Base):
    """站内通知（铃铛）：告警触发/恢复/重复提醒落一行，前端未读角标。"""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)  # 来源规则；规则删除后通知保留
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="alert")  # alert / alert_resolved
    link: Mapped[str | None] = mapped_column(String(128), nullable=True)            # 前端路由（如 /servers/19）
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
