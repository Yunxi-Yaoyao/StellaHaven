from uuid import UUID
from pydantic import BaseModel


class DocTagCreate(BaseModel):
    doc_id: UUID
    tag_id: UUID


class DocTagRead(BaseModel):
    doc_id: UUID
    tag_id: UUID

    model_config = {"from_attributes": True}
