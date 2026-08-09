from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.document import DocumentCreate, DocumentUpdate, DocumentRead
from app.services.document import get_document, list_documents, create_document, update_document, delete_document

from app.routers.ws import notify_sync

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{doc_id}", response_model=DocumentRead)
def read_one(doc_id: UUID, db: Session = Depends(get_db)):
    return get_document(db, doc_id)


@router.get("/", response_model=list[DocumentRead])
def read_all(workspace_id: UUID, parent_id: UUID | None = None, skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    return list_documents(db, workspace_id, parent_id, skip, limit)


@router.post("/", response_model=DocumentRead, status_code=201)
def create_one(data: DocumentCreate, db: Session = Depends(get_db)):
    return create_document(db, data)


@router.put("/{doc_id}")
def update_one(doc_id: UUID, data: DocumentUpdate, request: Request, db: Session = Depends(get_db)):
    try:
        result = update_document(db, doc_id, data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail={
            "message": str(e) if str(e) == "Conflict" else "文档已被修改或不存在，请刷新",
            "editor": {
                "ip": request.client.host,
                "ua": request.headers.get("User-Agent", "")
            }
        })

    # 保存成功 → 通知其他设备
    try:
        notify_sync(doc_id, {
            "type": "doc_saved",
            "by": {
                "ip": request.client.host,
                "ua": request.headers.get("User-Agent", ""),
                "saved_at": result.updated_at.isoformat()
            }
        })
    except Exception:
        pass

    return result



@router.delete("/{doc_id}", status_code=204)
def delete_one(doc_id: UUID, db: Session = Depends(get_db)):
    delete_document(db, doc_id)
