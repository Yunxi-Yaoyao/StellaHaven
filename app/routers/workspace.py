from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.workspace import WorkspaceCreate, WorkspaceRead
from app.routers.auth import current_user, require_ws_owner
from app.services.workspace import (
    get_workspace, list_user_workspaces, create_workspace,
    rename_workspace, delete_workspace,
)
from app.models.user import User

router = APIRouter(dependencies=[Depends(current_user)], prefix="/workspaces", tags=["workspaces"])

@router.get("/{ws_id}", response_model=WorkspaceRead)
def read_one(ws_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """查询单工作区信息（仅自己的）"""
    return require_ws_owner(db, ws_id, user)

@router.get("/", response_model=list[WorkspaceRead])
def read_user_workspaces(user: User = Depends(current_user), db: Session = Depends(get_db), skip: int = 0, limit: int = 50):
    """列出当前用户的工作区（隔离：只出自己的）"""
    return list_user_workspaces(db, user.id, skip, limit)

@router.post("/", response_model=WorkspaceRead, status_code=201)
def create_one(data: WorkspaceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """创建工作区（归属当前用户，无视传入的 user_id）。
    新工作区自动种「样式展示厅」示例笔记（可删，新用户引导用）"""
    data.user_id = user.id
    ws = create_workspace(db, data)
    _seed_showcase(db, ws.id)
    return ws


def _seed_showcase(db: Session, ws_id: UUID) -> None:
    """种示例笔记：走正规 create 服务（hash/word_count 等字段由服务层算好）。
    内容在 app/seed/showcase.md（附件走 public/seed/ 静态路径，永不失效）"""
    from app.services.document import create_document
    from app.schemas.document import DocumentCreate
    seed = Path(__file__).resolve().parents[1] / "seed" / "showcase.md"
    if not seed.exists():
        return
    create_document(db, DocumentCreate(
        workspace_id=ws_id,
        title="🎨 Stella 样式展示厅",
        content=seed.read_text(encoding="utf-8"),
        file_path="/notes/showcase.md",
    ))


@router.put("/{ws_id}", response_model=WorkspaceRead)
def rename_one(ws_id: UUID, name: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """重命名工作区（仅自己的）"""
    require_ws_owner(db, ws_id, user)
    ws = rename_workspace(db, ws_id, name)
    return ws


@router.delete("/{ws_id}", status_code=204)
def delete_one(ws_id: UUID, force: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """删除工作区（仅自己的）：有笔记不 force → 409 提醒；force=true → 连笔记一起永久删"""
    from fastapi import HTTPException
    require_ws_owner(db, ws_id, user)
    result = delete_workspace(db, ws_id, force)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="工作区不存在")
    if result == "not_empty":
        raise HTTPException(status_code=409, detail={"code": "not_empty", "message": "工作区里还有笔记"})
    if result == "has_trash":
        raise HTTPException(status_code=409, detail={"code": "has_trash", "message": "回收站里还有笔记，删除工作区会把它们一起永久删除"})