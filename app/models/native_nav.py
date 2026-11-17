"""Native navigation aggregate, independent of Notes and integrations/session state."""
from uuid import UUID
from sqlalchemy import ForeignKey, Integer, JSON, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class NavState(Base):
    __tablename__ = 'nav_states'
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    mutation_id: Mapped[str] = mapped_column(String(36), nullable=False, default='')
    mutation_hash: Mapped[str] = mapped_column(String(64), nullable=False, default='')

class NavAsset(Base):
    __tablename__ = 'nav_assets'
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mime: Mapped[str] = mapped_column(String(40), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False, default='uncategorized', server_default='uncategorized')
