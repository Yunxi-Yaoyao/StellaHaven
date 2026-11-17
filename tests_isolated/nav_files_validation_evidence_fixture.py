"""Named immutable v18 edges; retain the exact historical v17 input row."""
from api_response_evidence_fixture import named_reviews

REVIEW = 'api_response_v18_nav_files_validation_review.json'


def advance_validation_row(row, *, current=True):
    review = named_reviews()[REVIEW]
    updates = [u for u in review['operation_source_updates']
               if (u['method'], u['path']) == (row['method'], row['path'])]
    from unified_files_evidence_fixture import advance_row
    if not updates:
        return advance_row(row) if current else row
    update, = updates
    assert row == update['before_operation']
    assert row['endpoint'] == update['endpoint']
    assert row['sources'] == update['before_sources']
    result = {**row, 'sources': list(update['sources'])}
    return advance_row(result) if current else result


def validation_source_maps(row):
    review = named_reviews()[REVIEW]
    from unified_files_evidence_fixture import source_maps
    return source_maps(row, ['app/api_response_v17_nav_files_review.json'] + (
        ['app/' + REVIEW] if any((u['method'], u['path'], u['endpoint']) ==
            (row['method'], row['path'], row['endpoint'])
            for u in review['operation_source_updates']) else []))
