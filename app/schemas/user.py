from uuid import UUID
from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    display_name: str


class UserRead(BaseModel):
    id: UUID
    username: str
    display_name: str

    model_config = {"from_attributes": True}
