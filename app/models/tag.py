from app.models import Base, Mapped, mapped_column, UUID, uuid4

class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(unique=True, nullable=False)
    color: Mapped[str | None] = mapped_column(nullable=True)
