from datetime import datetime
from sqlalchemy import ForeignKey, Integer, DateTime, CheckConstraint, Index, text
from sqlalchemy.sql import func
from app.models import Base, Mapped, mapped_column, UUID, uuid4


class Attachment(Base):
    """Ordinary uploads belong to a document; project objects may outlive it.

    owner_id is server-owned project provenance, never an upload/API field.
    A detached project object keeps its UUID/blob key and owner authorization.
    """
    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint('doc_id IS NOT NULL OR owner_id IS NOT NULL', name='attachment_has_custodian'),
        Index('ix_attachments_detached_owner', 'owner_id', 'id', postgresql_where=text('doc_id IS NULL')),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    doc_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    filename: Mapped[str] = mapped_column(nullable=False)      # 原始文件名
    mime: Mapped[str] = mapped_column(nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
