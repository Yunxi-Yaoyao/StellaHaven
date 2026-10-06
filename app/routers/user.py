"""Retained import compatibility only; single-owner mode exposes no user CRUD API.

Do not delete legacy User rows, IDs, foreign keys, workspaces, or invites.
"""
from fastapi import APIRouter

router = APIRouter(prefix='/users', tags=['users'])
