from datetime import datetime
from sqlalchemy import ForeignKey, Integer, DateTime
from sqlalchemy.sql import func
from app.models import Base, Mapped, mapped_column, UUID, uuid4


class Attachment(Base):
    """附件（图片等）：文件落磁盘，DB 记元信息。
    生命周期：保存时引用计数清理——正文不再引用的附件连文件带记录删除。"""
    __tablename__ = "attachments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    doc_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"))
    filename: Mapped[str] = mapped_column(nullable=False)      # 原始文件名
    mime: Mapped[str] = mapped_column(nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
