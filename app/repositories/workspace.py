from uuid import UUID
from sqlalchemy.orm import Session

from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate

def get_by_id(db: Session, ws_id: UUID) -> Workspace | None:
    """按 ID 查一个 workspace，找不到返回 None"""
    return db.query(Workspace).filter(Workspace.id == ws_id).first()

def list_all(db: Session, user_id: UUID,skip:int = 0,limit:int = 10  ) -> list[Workspace]:
    """列出某用户的所有 workspace"""
    return db.query(Workspace).filter(Workspace.user_id == user_id).offset(skip).limit(limit).all()

def create(db: Session, data: WorkspaceCreate) -> Workspace:
    """新建一个 workspace 并写入数据库"""
    """Pydantic对象-->字典-->解耦-->ORM对象"""
    ws = Workspace(**data.model_dump())
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def rename(db: Session, ws_id: UUID, name: str) -> Workspace | None:
    ws = get_by_id(db, ws_id)
    if ws is None:
        return None
    ws.name = name
    db.commit()
    db.refresh(ws)
    return ws


def delete(db: Session, ws_id: UUID) -> str:
    """删除工作区：里面还有文档就不给删（防手滑，先清空再说）"""
    from app.models.document import Document
    ws = get_by_id(db, ws_id)
    if ws is None:
        return "not_found"
    n = db.query(Document).filter(Document.workspace_id == ws_id).count()
    if n > 0:
        return "not_empty"
    db.delete(ws)
    db.commit()
    return "deleted"