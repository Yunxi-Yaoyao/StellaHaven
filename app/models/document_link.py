from sqlalchemy import ForeignKey
from app.models import Base, Mapped, mapped_column, UUID


class DocumentLink(Base):
    __tablename__ = "document_links"

    source_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    target_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    link_type: Mapped[str] = mapped_column(default="ref")
