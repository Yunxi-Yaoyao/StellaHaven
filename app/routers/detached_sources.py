"""Mount independently: app.include_router(detached_sources.router)."""
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from app.database import get_db
from app.routers.auth import current_user
from app.services import detached_sources

router = APIRouter(prefix='/detached-sources', tags=['detached_sources'], dependencies=[Depends(current_user)])

class SourcePatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    updated_at: datetime
    content: str = Field(max_length=5 * 1024 * 1024)

@router.get('')
def catalog(workspace_id: UUID, db=Depends(get_db), user=Depends(current_user)):
    return detached_sources.catalog(db, user.id, workspace_id)

@router.get('/{file_id}')
def read(file_id: UUID, db=Depends(get_db), user=Depends(current_user)):
    return detached_sources.read(db, user.id, file_id)

@router.put('/{file_id}')
def save(file_id: UUID, data: SourcePatch, db=Depends(get_db), user=Depends(current_user)):
    result = detached_sources.save(db, user.id, file_id, data.updated_at, data.content)
    from app.routers.document import notify_list
    notify_list(UUID(result['workspace_id']), file_id)
    return result
