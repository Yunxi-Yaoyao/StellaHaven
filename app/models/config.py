"""全局配置：key-value 存储（公网地址、监控配置版本号等）。"""
from sqlalchemy import String, Text

from app.models import Base, Mapped, mapped_column


class AppConfig(Base):
    """应用级配置表（单 key 单 value）。

    - public_host：公网 IP/域名（设置页配置，给 agent 安装命令 --url 用）
    - monitors_version：监控项配置版本号（增删改监控项时 +1，agent 心跳 diff 用）
    """

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
