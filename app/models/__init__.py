# app/models/__init__.py
from uuid import UUID, uuid4
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

from app.models.tag import Tag
from app.models.user import User
from app.models.workspace import Workspace
from app.models.document import Document
from app.models.doc_tag import DocTag
from app.models.document_link import DocumentLink
from app.models.document_version import DocumentVersion
