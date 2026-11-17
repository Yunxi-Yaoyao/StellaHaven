from uuid import UUID
from sqlalchemy.orm import Session

from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate
from app.services.notes_lifecycle import lock_graph, locked_tree, rollback_on_error

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


@rollback_on_error
def delete(db: Session, ws_id: UUID, force: bool = False) -> str:
    """删除工作区（老婆 8.10 定稿规则）：
    - 有正常笔记且不 force → not_empty（前端弹提醒+二次确认）
    - 只有回收站且不 force → has_trash
    - force=True → 连同所有笔记（正常+回收站）一起物理删除，再删工作区
    """
    from app.models.document import Document
    lock_graph(db)
    ws = get_by_id(db, ws_id)
    if ws is None:
        return "not_found"
    docs = list(locked_tree(db, ws_id).values())
    active = sum(doc.deleted_at is None for doc in docs)
    trashed = len(docs) - active
    if active > 0 and not force:
        return "not_empty"
    if active == 0 and trashed > 0 and not force:
        return "has_trash"
    if active + trashed > 0:
        # force：笔记连工作区一起永久删除（连带标签/双链/版本/附件清理）
        from app.services.document import _delete_set
        # The protected template root belongs to this workspace's lifetime.
        # Remove its identity in the same transaction, not the ordinary note
        # protection globally; any later lifecycle conflict rolls this back.
        from app.models.config import AppConfig
        from app.services.notes_templates import PREFIX
        db.query(AppConfig).filter(AppConfig.key.in_([
            PREFIX + str(ws_id), 'notes-template-usage:' + str(ws_id),
        ])).delete(synchronize_session='fetch')
        _delete_set(db, docs)
    db.delete(ws)
    db.commit()
    from app.services.attachment_lifecycle import drain_file_gc
    drain_file_gc(db)
    return "deleted"