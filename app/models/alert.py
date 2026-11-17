"""告警域：规则 + 当前状态（槽位覆写）+ 事件流水 + 站内通知。

设计定稿（2026-09-16 老婆拍板）：
- 新建节点自动添加上报中断规则；其它规则仍选择性添加，不回填存量节点。
- 当前状态槽位覆写（alert_states 一规则一行），历史进 alert_events 流水表。
- 节点中断由应用生命周期轻量定时器推进，其它规则沿数据落库路径评估。
"""
from datetime import datetime
from sqlalchemy import ForeignKey, Integer, BigInteger, DateTime, String, Boolean, Index, text
from sqlalchemy.dialects.postgresql import JSONB
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
        Index("uq_alert_rule_legacy", "kind", "target", unique=True, postgresql_where=text("schema_version = 1 AND NOT archived")),
        Index("uq_alert_rule_fingerprint", "target", "fingerprint", unique=True, postgresql_where=text("schema_version = 2 AND NOT archived")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")  # 显示名快照（节点名/监控项名/链路名）
    link: Mapped[str] = mapped_column(String(128), nullable=False, default="/status")  # 通知跳转的前端路由
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    debounce: Mapped[int] = mapped_column(Integer, nullable=False, default=2)        # 连续 N 次异常才触发
    repeat_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 不重复；不改存量选择
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)      # 仅新建默认；不改存量选择
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    condition: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preview: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AlertEvent(Base):
    """告警事件流水：触发/恢复各插一行，历史追溯用。"""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False)
    event: Mapped[str] = mapped_column(String(8), nullable=False)  # fired / resolved
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    message: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


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
    dedupe_key: Mapped[str | None] = mapped_column(String(192), nullable=True, unique=True)
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
