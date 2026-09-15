"""Immutable-sized BYTEA chunks; caller transaction owns metadata and bytes."""
from sqlalchemy import String, Integer, BigInteger, LargeBinary, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class BlobObject(Base):
    __tablename__='blob_objects'
    key: Mapped[str]=mapped_column(String(512),primary_key=True)
    size: Mapped[int]=mapped_column(BigInteger,nullable=False)
    sha256: Mapped[str]=mapped_column(String(64),nullable=False)
    mime: Mapped[str]=mapped_column(String(200),nullable=False)
    __table_args__=(CheckConstraint('size >= 0'),)

class BlobChunk(Base):
    __tablename__='blob_chunks'
    key: Mapped[str]=mapped_column(ForeignKey('blob_objects.key',ondelete='CASCADE'),primary_key=True)
    number: Mapped[int]=mapped_column(Integer,primary_key=True)
    data: Mapped[bytes]=mapped_column(LargeBinary,nullable=False)
    __table_args__=(CheckConstraint('number >= 0'),)
