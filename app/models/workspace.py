from sqlalchemy import ForeignKey
from app.models import Base, Mapped, mapped_column, UUID, uuid4


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

