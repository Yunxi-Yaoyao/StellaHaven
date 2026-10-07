"""No dual authority after the operator migration commits."""
from fastapi import Depends
from app.database import get_db


def legacy_available(db=Depends(get_db)):
    from app.services.website_migration import require_unmigrated
    require_unmigrated(db)
