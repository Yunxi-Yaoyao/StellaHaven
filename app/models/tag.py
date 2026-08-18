from sqlalchemy import ForeignKey, UniqueConstraint
from app.models import Base, Mapped, mapped_column, UUID, uuid4


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tags_user_name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    color: Mapped[str | None] = mapped_column(nullable=True)
