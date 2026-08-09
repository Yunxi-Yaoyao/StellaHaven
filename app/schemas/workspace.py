from uuid  import UUID
from pydantic import BaseModel

class WorkspaceCreate(BaseModel):
    """创建工作区所需的字段"""
    user_id: UUID
    name: str
    description: str | None = None

class WorkspaceRead(BaseModel):
    """返回给前端的数据"""
    id: UUID
    name: str
    description: str | None
    user_id: UUID

    model_config = {"from_attributes": True}


