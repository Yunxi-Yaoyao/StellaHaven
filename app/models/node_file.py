"""Durable dedicated file journal. A claimed operation is NEVER requeued."""
from sqlalchemy import String, Integer, Float, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class FileAgent(Base):
    __tablename__ = 'node_file_agents'
    node_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seen: Mapped[float] = mapped_column(Float)
    roots: Mapped[dict] = mapped_column(JSON)

class FileJob(Base):
    __tablename__ = 'node_file_jobs'
    __table_args__ = (UniqueConstraint('owner', 'session', 'request_key'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(36), index=True)
    session: Mapped[str] = mapped_column(String(36))
    request_key: Mapped[str] = mapped_column(String(36))
    node_id: Mapped[int] = mapped_column(Integer, index=True)
    root: Mapped[str] = mapped_column(String(64))
    policy: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), index=True, default='pending')
    expires: Mapped[float] = mapped_column(Float)
    lease: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bytes_received: Mapped[int] = mapped_column(Integer, default=0)
