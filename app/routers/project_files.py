"""Project file controls, mounted independently from runtime authorization routes."""
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from app.database import get_db
from app.routers.auth import current_user
from app.services import web_projects

router = APIRouter(prefix='/web-project-files', tags=['web_project_files'], dependencies=[Depends(current_user)])

class EntryPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_id: UUID
    expected_entry_file_id: UUID | None

@router.patch('/{root_id}/entry')
def update_entry(root_id: UUID, data: EntryPatch, db=Depends(get_db), user=Depends(current_user)):
    result = web_projects.set_entry(db, user.id, root_id, data.file_id,
                                   str(data.expected_entry_file_id) if data.expected_entry_file_id else None)
    from app.routers.document import notify_list
    notify_list(UUID(result['workspace_id']), root_id)
    return result
