"""Display-only projection on the existing isolated draft fixture.

No production config/database import. PostgreSQL trigger/migration and full-main
old/new writer proofs live with the owned acceptance evidence; SQLite cannot
prove the database observation source.
"""
from datetime import datetime, timezone

import pytest

from test_api_draft_contract import env  # Explicit isolated SQLite fixture.


@pytest.mark.parametrize('event', [None, datetime(2026, 1, 2, 3, 4, 5)])
def test_unknown_or_unzoned_projection_never_labels_raw_utc(env, event):
    raw = datetime(2001, 2, 3, 4, 5, 6, 123456)
    doc = env.models.Document(updated_at=raw, saved_event_at=event)
    assert doc.updated_at_display is None
    assert doc.updated_at is raw


def test_proven_display_is_independent_of_raw_cas_and_draft(env):
    raw = datetime(2001, 2, 3, 4, 5, 6, 123456)
    instant = datetime(2026, 1, 2, 3, 4, 5, 654321, tzinfo=timezone.utc)
    doc = env.models.Document(updated_at=raw, saved_event_at=instant,
                              draft_updated_at=raw, draft_content='retained')
    assert doc.updated_at_display is instant
    assert doc.updated_at is raw and doc.draft_updated_at is raw
    assert doc.draft_content == 'retained'
