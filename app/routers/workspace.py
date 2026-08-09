from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.workspace import WorkspaceCreate, WorkspaceRead
from app.services.workspace import (
    get_workspace, list_user_workspaces, create_workspace,
    rename_workspace, delete_workspace,
)

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


@router.put("/{ws_id}", response_model=WorkspaceRead)
def rename_one(ws_id: UUID, name: str, db: Session = Depends(get_db)):
    """重命名工作区"""
    from fastapi import HTTPException
    ws = rename_workspace(db, ws_id, name)
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return ws


@router.delete("/{ws_id}", status_code=204)
def delete_one(ws_id: UUID, force: bool = False, db: Session = Depends(get_db)):
    """删除工作区：有正常笔记 409；只有回收站 → 需 force=true（连回收站永久删）"""
    from fastapi import HTTPException
    result = delete_workspace(db, ws_id, force)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="工作区不存在")
    if result == "not_empty":
        raise HTTPException(status_code=409, detail={"code": "not_empty", "message": "工作区里还有笔记，先清空再删"})
    if result == "has_trash":
        raise HTTPException(status_code=409, detail={"code": "has_trash", "message": "回收站里还有笔记，删除工作区会把它们一起永久删除"})