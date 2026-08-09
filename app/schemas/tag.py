from uuid import UUID
from pydantic import BaseModel


class TagCreate(BaseModel):
    name: str
    color: str | None = None


class TagRead(BaseModel):
    id: UUID
    name: str
    color: str | None = None

    model_config = {"from_attributes": True}
