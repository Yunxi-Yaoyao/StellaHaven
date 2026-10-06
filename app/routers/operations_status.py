"""Read-only operational evidence; no backup/restore/admin-write route."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.routers.auth import current_user, admin_user
from app.services.backup_health import read_backup_health, read_change_audit, AUDIT_LIMIT

router = APIRouter(prefix='/operations', tags=['operations'])

class BackupHealth(BaseModel):
    timestamp: str | None
    status: Literal['missing', 'invalid', 'verified', 'unverified', 'failed', 'stale']
    checksumverified: bool
    restoreverified: bool
    source: Literal['postgres-dump', 'postgres-snapshot'] | None

@router.get('/backup-health', response_model=BackupHealth)
def backup_health(response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return read_backup_health()

@router.get('/change-audit')
def change_audit(response: Response, user=Depends(admin_user), db: Session = Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        events = read_change_audit(db)
    except (ValueError, TypeError):
        raise HTTPException(503, '变更审计记录无效，请检查受控审计槽')
    return {'events': events, 'limit': AUDIT_LIMIT}
