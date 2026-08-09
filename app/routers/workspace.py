from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.workspace import WorkspaceCreate, WorkspaceRead
from app.services.workspace import get_workspace, list_user_workspaces, create_workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

@router.get("/{ws_id}", response_model=WorkspaceRead)
def read_one(ws_id:UUID, db: Session = Depends(get_db)):
    """查询单工作区信息"""
    return get_workspace(db,ws_id)

@router.get("/", response_model=list[WorkspaceRead])
def read_user_workspaces(user_id: UUID, db: Session = Depends(get_db), skip: int = 0, limit: int = 10):
    """列出某用户的工作区"""
    return list_user_workspaces(db, user_id, skip, limit)

@router.post("/", response_model=WorkspaceRead, status_code=201)
def create_one(data: WorkspaceCreate,db: Session = Depends(get_db)):
    """创建工作区"""
    return create_workspace(db, data)