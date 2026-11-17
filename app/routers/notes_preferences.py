from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.routers.auth import current_user
from app.schemas.notes_preferences import NotesPreferencesRead, NotesPreferencesPatch
from app.services.notes_preferences import get_preferences, patch_preferences

router = APIRouter(prefix='/notes-preferences', tags=['notes-preferences'])


@router.get('', response_model=NotesPreferencesRead)
def read_preferences(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return get_preferences(db, user.id)


@router.patch('', response_model=NotesPreferencesRead)
def update_preferences(data: NotesPreferencesPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return patch_preferences(db, user.id, data)
