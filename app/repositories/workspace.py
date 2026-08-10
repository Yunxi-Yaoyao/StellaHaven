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


def delete(db: Session, ws_id: UUID, force: bool = False) -> str:
    """删除工作区（老婆 8.10 定稿规则）：
    - 有正常笔记且不 force → not_empty（前端弹提醒+二次确认）
    - 只有回收站且不 force → has_trash
    - force=True → 连同所有笔记（正常+回收站）一起物理删除，再删工作区
    """
    from app.models.document import Document
    ws = get_by_id(db, ws_id)
    if ws is None:
        return "not_found"
    q = db.query(Document).filter(Document.workspace_id == ws_id)
    active = q.filter(Document.deleted_at.is_(None)).count()
    trashed = q.filter(Document.deleted_at.isnot(None)).count()
    if active > 0 and not force:
        return "not_empty"
    if active == 0 and trashed > 0 and not force:
        return "has_trash"
    if active + trashed > 0:
        # force：笔记连工作区一起永久删除（连带标签/双链/版本/附件清理）
        from app.services.document import _physical_delete
        for d in q.all():
            _physical_delete(db, d)
    db.delete(ws)
    db.commit()
    return "deleted"