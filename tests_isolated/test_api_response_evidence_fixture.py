"""Name-bound immutable approval lookup, independent of registry positions."""
import hashlib
import json
from pathlib import Path

import pytest
import api_response_evidence_fixture as evidence
from evidence_graph_copy_cases import (
    test_fresh_graph_aliases_cycles_and_mutation_are_preserved,
    test_custom_objects_and_non_json_keys_use_original_copy_semantics,
    test_plain_graph_is_equal_and_independently_mutable,
    test_explicit_memo_is_honored_and_dependency_patch_is_scoped,
)

METADATA = 'api_response_v13_source_metadata_review.json'
DIGEST = '0f9d5694370840dcccf02807726070bacde0b3eb0a5162f275d28f6c508b0e39'


def test_named_metadata_survives_registry_reordering_and_a_new_layer(monkeypatch):
    original = evidence.reviews()
    metadata = json.loads((evidence.ROOT/'app'/METADATA).read_bytes())
    assert evidence.REVIEW_DIGESTS[METADATA] == DIGEST
    assert hashlib.sha256((evidence.ROOT/'app'/METADATA).read_bytes()).hexdigest() == DIGEST
    new_name = 'api_response_future_fixture.json'
    new_body = b'{"release_approval":false,"operation_source_updates":[]}'
    registry = dict(reversed(tuple(evidence.REVIEW_DIGESTS.items())))
    registry[new_name] = hashlib.sha256(new_body).hexdigest()
    read = Path.read_bytes
    monkeypatch.setattr(evidence, 'REVIEW_DIGESTS', registry)
    monkeypatch.setattr(Path, 'read_bytes', lambda p: new_body if p == evidence.ROOT/'app'/new_name else read(p))
    named = evidence.named_reviews()
    assert named[METADATA] == metadata
    assert named[new_name] == json.loads(new_body)
    assert list(named) == list(registry)
    assert list(named.values())[:-1] == list(reversed(original))
    assert evidence.reviews() == list(named.values())


@pytest.mark.parametrize('damage', ['missing', 'digest', 'release_approval'])
def test_named_review_lookup_keeps_fail_closed_pins(monkeypatch, damage):
    target = evidence.ROOT/'app'/METADATA
    read = Path.read_bytes
    def changed(path):
        body = read(path)
        if path != target:
            return body
        if damage == 'missing':
            raise FileNotFoundError(METADATA)
        if damage == 'release_approval':
            body = json.dumps(dict(json.loads(body), release_approval=True)).encode()
        else:
            body += b' '
        return body
    monkeypatch.setattr(Path, 'read_bytes', changed)
    if damage == 'release_approval':
        # Even a correctly digest-bound fixture cannot become release approval.
        registry = dict(evidence.REVIEW_DIGESTS)
        registry[METADATA] = hashlib.sha256(changed(target)).hexdigest()
        monkeypatch.setattr(evidence, 'REVIEW_DIGESTS', registry)
    with pytest.raises(FileNotFoundError if damage == 'missing' else AssertionError):
        evidence.named_reviews()


# Keep the existing owning command; these synthetic controls add no CI process.
from evidence_exact_cache_cases import (
    test_repeated_exact_body_parses_once_and_parser_identity_invalidates,
    test_same_filename_size_and_mtime_changed_body_cannot_reuse_metadata,
    test_expected_metadata_is_not_validation_result_or_mutable_ast,
    test_bounded_eviction_oversize_bypass_and_segmenter_identity,
    test_duplicates_nested_assignments_unicode_and_function_only,
    test_exact_json_derivation_is_fresh_and_parser_replacement_is_not_cached,
    test_exact_json_byte_bound_eviction_oversize_and_decode_errors,
)
