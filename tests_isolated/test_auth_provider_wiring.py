"""Static wiring gate: must not import app or touch configured production DB."""
import ast
from pathlib import Path

def test_provider_management_router_registered_before_spa_fallback():
    root=Path(__file__).resolve().parents[1]
    source=(root/'main.py').read_text()
    ast.parse(source)
    assert 'from app.routers.auth_provider import router as auth_provider_router' in source
    assert source.index('app.include_router(auth_provider_router)') < source.index('@app.get("/{full_path:path}"')
