from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.document import DocumentRead
from app.services.notes_tools import quick_record
from app.routers.auth import current_user, require_ws_owner

router = APIRouter(prefix='/notes-tools', tags=['notes_tools'], dependencies=[Depends(current_user)])


class QuickRecord(BaseModel):
    workspace_id: UUID
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=200000)


@router.post('/quick-record', response_model=DocumentRead, status_code=201)
def capture(data: QuickRecord, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_ws_owner(db, data.workspace_id, user)
    result = quick_record(db, data.workspace_id, data.title, data.content)
    from app.routers.document import notify_list
    notify_list(result.workspace_id, result.id)
    return result


class NoteNode(BaseModel):
    node_id: int | None = Field(default=None, ge=1)


def owned_active_doc(db, doc_id, user):
    from app.routers.auth import require_doc_owner
    from fastapi import HTTPException
    doc = require_doc_owner(db, doc_id, user)
    if doc.deleted_at is not None:
        raise HTTPException(404, '文档不存在')
    return doc


@router.get('/documents/{doc_id}/node')
def read_node(doc_id: UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.services.notes_tools import note_node
    owned_active_doc(db, doc_id, user)
    return {'node_id': note_node(db, doc_id)}


@router.put('/documents/{doc_id}/node')
def link_node(doc_id: UUID, data: NoteNode, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.services.notes_tools import set_note_node
    from app.models.node import Node
    from fastapi import HTTPException
    owned_active_doc(db, doc_id, user)
    if data.node_id is not None:
        node = db.get(Node, data.node_id)
        if node is None or node.status == 'removed':
            raise HTTPException(404, '节点不存在')
    set_note_node(db, doc_id, data.node_id)
    return {'node_id': data.node_id}
