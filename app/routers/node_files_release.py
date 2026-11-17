"""Authenticated complete package for the optional file-domain worker.

Read-only source distribution, not a rollout announcement or implicit install.
"""
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import agent_token
from app.services.node_files import node_agent
from agent.node_files_delivery import FILES, build_release, canonical, release_id

router = APIRouter()


def snapshot():
    try:
        return build_release(Path(__file__).resolve().parents[2] / 'agent')
    except (OSError, ValueError, SyntaxError):
        raise HTTPException(503, 'file_release_unavailable') from None


@router.get('/release')
def manifest(token: str = Depends(agent_token), db: Session = Depends(get_db)):
    node_agent(db, token)
    value, _ = snapshot()
    return Response(canonical(value), media_type='application/json', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/release/{identity}/{name}')
def artifact(identity: str, name: str, token: str = Depends(agent_token), db: Session = Depends(get_db)):
    node_agent(db, token)
    if name not in FILES:
        raise HTTPException(404, 'file_release_artifact_not_found')
    value, bodies = snapshot()
    if identity != release_id(value):
        raise HTTPException(409, 'file_release_changed')
    return Response(bodies[name], media_type='application/octet-stream', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'X-Artifact-SHA256': value['files'][name]['sha256']})
