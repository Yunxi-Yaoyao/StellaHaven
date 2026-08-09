from sqlalchemy import ForeignKey
from app.models import Base, Mapped, mapped_column, UUID


class DocTag(Base):
    __tablename__ = "doc_tags"

    doc_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey("tags.id"), primary_key=True)
