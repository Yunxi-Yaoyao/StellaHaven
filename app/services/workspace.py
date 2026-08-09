from uuid import UUID
from sqlalchemy.orm import Session

from app.repositories.workspace import get_by_id, list_all, create, rename, delete
from app.schemas.workspace import WorkspaceCreate
from app.models.workspace import Workspace

def get_workspace(db: Session, ws_id: UUID) -> Workspace | None:
    """查一个 workspace"""
    return get_by_id(db, ws_id)


def list_user_workspaces(db: Session, user_id: UUID, skip: int = 0, limit: int = 10) -> list[Workspace]:
    """列出某用户的工作区"""
    return list_all(db, user_id, skip, limit)


def create_workspace(db: Session, data: WorkspaceCreate) -> Workspace:
    """创建工作区"""
    return create(db, data)


def rename_workspace(db: Session, ws_id: UUID, name: str) -> Workspace | None:
    return rename(db, ws_id, name)


def delete_workspace(db: Session, ws_id: UUID) -> str:
    return delete(db, ws_id)