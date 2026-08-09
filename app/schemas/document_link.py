from uuid import UUID
from pydantic import BaseModel


class DocumentLinkCreate(BaseModel):
    source_id: UUID
    target_id: UUID
    link_type: str = "ref"


class DocumentLinkRead(BaseModel):
    source_id: UUID
    target_id: UUID
    link_type: str

    model_config = {"from_attributes": True}
