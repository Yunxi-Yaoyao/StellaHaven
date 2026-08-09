from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class DocumentVersionCreate(BaseModel):
    doc_id: UUID
    content: str
    diff: str
    version_no: int


class DocumentVersionRead(BaseModel):
    id: UUID
    doc_id: UUID
    content: str
    diff: str
    version_no: int
    created_at: datetime

    model_config = {"from_attributes": True}
