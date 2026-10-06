from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.node import Node
from app.routers.auth import current_user, require_ws_owner
from app.services.timeline import timeline_records

router = APIRouter(tags=['timeline'], dependencies=[Depends(current_user)])


@router.get('/timeline')
def read_timeline(node_id: int = Query(..., ge=1), workspace_id: UUID | None = None,
                  limit: int = Query(100, ge=1, le=100), db: Session = Depends(get_db), user=Depends(current_user)):
    if workspace_id is not None:
        require_ws_owner(db, workspace_id, user)
    if db.get(Node, node_id) is None:
        raise HTTPException(404, '节点不存在')
    return timeline_records(db, node_id, workspace_id, limit)
