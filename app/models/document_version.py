from datetime import datetime
from sqlalchemy import ForeignKey, Text, Integer, DateTime
from sqlalchemy.sql import func
from app.models import Base, Mapped, mapped_column, UUID, uuid4


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    doc_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
