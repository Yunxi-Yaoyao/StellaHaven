"""Historical API proofs must work in shallow CI clones and source archives.

These are verbatim Git blobs pinned by the existing API evidence ledgers, not
current-source substitutes. Never update a ledger hash to accept fixture drift.
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'fixtures' / 'api_pinned_sources'


def read_pinned_source(source, revision=None, *, root=ROOT):
    revision = source.get('revision', revision)
    assert isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{40}', revision)
    relative = Path(source['file'])
    assert not relative.is_absolute() and '..' not in relative.parts
    raw = (root / revision / (str(relative) + '.txt')).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == source['sha256'], 'pinned source hash mismatch'
    return raw
