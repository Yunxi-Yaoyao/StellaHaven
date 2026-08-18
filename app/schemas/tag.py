from uuid import UUID
from pydantic import BaseModel


class TagCreate(BaseModel):
    name: str
    color: str | None = None
    user_id: UUID | None = None  # 由 router 用 current_user 覆盖，前端可不传


class TagRead(BaseModel):
    id: UUID
    name: str
    color: str | None = None
    user_id: UUID

    model_config = {"from_attributes": True}
