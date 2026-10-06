"""Bounded metadata search. Never hydrates saved/draft bodies or task results."""
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.document import Document
from app.models.node import Node
from app.routers.auth import current_user, require_ws_owner

router = APIRouter(tags=['search'], dependencies=[Depends(current_user)])


@router.get('/search')
def search(q: str = Query('', max_length=200), workspace_id: UUID | None = None,
           limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db), user=Depends(current_user)):
    if workspace_id is not None:
        require_ws_owner(db, workspace_id, user)
    term = q.strip()
    if not term:
        return {'items': []}
    # Treat wildcards literally to prevent broad scans from a single % or _.
    like = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    items = []
    if workspace_id is not None:
        for id_, title, updated in db.query(Document.id, Document.title, Document.updated_at).filter(
                Document.workspace_id == workspace_id, Document.deleted_at.is_(None),
                Document.title.ilike(like, escape='\\')).order_by(Document.updated_at.desc(), Document.id).limit(limit).all():
            items.append({'kind': 'note', 'id': str(id_), 'label': title, 'path': '/notes?doc=' + str(id_), 'ts': updated})
    for id_, name in db.query(Node.id, Node.name).filter(Node.status != 'removed', Node.name.ilike(like, escape='\\')).order_by(Node.id).limit(limit).all():
        items.append({'kind': 'node', 'id': str(id_), 'label': name, 'path': '/status/' + str(id_)})
    from app.services.timeline import timeline_records
    history = timeline_records(db, workspace_id=None, limit=limit, q=term)['items']
    items.extend(history)
    return {'items': items[:limit]}
