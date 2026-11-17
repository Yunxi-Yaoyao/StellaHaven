"""Run unchanged original settings projections inside each nonce-owned PG schema."""
import inspect
import pytest
from tests_isolated.test_native_nav_pg import lane,pytestmark
from tests_backups import test_projection as original

NAMES=sorted(n for n in dir(original) if n.startswith('test_'))

@pytest.mark.parametrize('name',NAMES)
def test_original_backup_domain_regressions(lane,tmp_path,monkeypatch,name):
    from sqlalchemy import text
    from app.database import Base
    import app.models
    from app.services.ha_state import metadata
    monkeypatch.setenv('STELLA_BLOB_STORAGE','postgres');monkeypatch.setenv('STELLA_SHARED_STATE','postgres')
    client,factory,uid,other,nav,app=lane
    engine=factory.kw['bind']
    with engine.begin() as conn:
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
        Base.metadata.create_all(conn);metadata.create_all(conn)
    # The old tests intentionally assert every profile in their empty fixture.
    # Remove only this lane's synthetic auth seeds before calling them unchanged.
    from app.models.config import AppConfig
    from app.models.user import User
    with factory() as db:
        db.query(AppConfig).delete();db.query(User).delete();db.commit()
    kwargs={'engine':engine,'tmp_path':tmp_path,'monkeypatch':monkeypatch}
    function=getattr(original,name)
    function(**{k:kwargs[k] for k in inspect.signature(function).parameters})
