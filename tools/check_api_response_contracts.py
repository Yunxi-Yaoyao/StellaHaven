#!/usr/bin/env python3
"""Offline API response gate. No main/config/database imports or live requests.

Default: fail on unclassified/new/stale operations, source drift or corrupt
contracts; report explicitly incomplete reviews. --require-complete also fails
for any incomplete operation. The latter is the normalization-complete gate.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests_isolated')]
from tests_isolated import api_response_guard  # noqa: E402,F401
from test_api_openapi_contract import source_shaped_app, static_inventory  # noqa: E402
from app import api_response_contracts as responses  # noqa: E402
from app.openapi_contract import install_openapi_contract, validate_contract, ContractError  # noqa: E402


def document_errors(schema):
    """Offline metaschema and document-root ref closure, including mappings."""
    from jsonschema import Draft202012Validator, SchemaError
    from fastapi.openapi.models import OpenAPI
    from pydantic import ValidationError
    errors = []
    try:
        OpenAPI.model_validate(schema)
    except ValidationError as exc:
        errors.append('Invalid OpenAPI root: ' + str(exc))
    references = set()

    def visit(value):
        if isinstance(value, str) and value.startswith('#/'):
            references.add(value)
        elif isinstance(value, dict):
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)

    visit(schema)
    for ref in sorted(references):
        target = schema
        try:
            for part in ref[2:].split('/'):
                target = target[part.replace('~1', '/').replace('~0', '~')]
        except (KeyError, TypeError):
            errors.append('Unresolved document reference: ' + ref)
    for name, value in schema.get('components', {}).get('schemas', {}).items():
        try:
            Draft202012Validator.check_schema(value)
        except SchemaError as exc:
            errors.append('Invalid component schema ' + name + ': ' + exc.message)
    for path, methods in schema.get('paths', {}).items():
        for method, operation in methods.items():
            if method.upper() not in {'GET','PUT','POST','DELETE','OPTIONS','HEAD','PATCH','TRACE'}:
                continue
            for code, response in operation.get('responses', {}).items():
                for media in response.get('content', {}).values():
                    try:
                        Draft202012Validator.check_schema(media['schema'])
                    except SchemaError as exc:
                        errors.append(f'Invalid response schema {method} {path} {code}: {exc.message}')
    return errors


def run(require_complete=False, output=None):
    records, mounted, excluded = static_inventory()
    errors = responses.validate_response_sources(ROOT, records)
    app, _ = source_shaped_app()
    install_openapi_contract(app)
    schema = app.openapi()
    errors.extend(document_errors(schema))
    try:
        validate_contract(app, require_all_overrides=True)
    except ContractError as exc:
        errors.extend(str(exc).splitlines())
    source_and_classification_passed = not errors
    if require_complete:
        for (method, path), declaration in responses.DECLARATIONS.items():
            if declaration['status'] == 'incomplete':
                errors.append(f'{method} {path}: incomplete response contract: ' + declaration['reason'])
    counts = Counter()
    operations = []
    for method, path, endpoint, _ in records:
        operation = schema['paths'][path][method.lower()]
        status = operation['x-stella-contract-status']
        counts[status] += 1
        operations.append(dict(method=method, path=path, endpoint=endpoint, status=status,
            reason=operation['x-stella-contract-reason'],
            success_statuses=[code for code in operation['responses'] if code.startswith(('2', '3'))],
            declared_statuses=list(operation['responses']),
            source_symbols=responses.DECLARATIONS[(method, path)]['sources'] if (method, path) in responses.DECLARATIONS else []))
    result = dict(evidence_level='source-shaped OpenAPI; NOT full-main or PostgreSQL execution',
        operation_count=len(records), classification=dict(sorted(counts.items())),
        normalization_complete=not errors and counts.get('incomplete', 0) == 0,
        source_and_classification_gate_passed=source_and_classification_passed,
        require_complete=require_complete, errors=errors, operations=operations,
        pending_upstream_operations=[dict(method=m, path=p, revision=r['revision']) for (m,p),r in responses.UPSTREAM_DECLARATIONS.items()],
        mounted_routers=sorted(mounted), exclusions=excluded)
    if output is not None:
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        def save(name, value):
            (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        save('response-completion-coverage.json', result)
        save('response-completion-openapi.json', schema)
        save('response-completion-source-mapping.json', dict(
            evidence=responses.SOURCE_EVIDENCE,
            operations=[dict(method=r['method'], path=r['path'], endpoint=r['endpoint'], sources=r['sources']) for r in responses.INVENTORY],
            pending_upstream=list(responses.UPSTREAM_DECLARATIONS.values())))
    print(json.dumps({k: v for k, v in result.items() if k not in {'operations', 'mounted_routers', 'exclusions'}}, ensure_ascii=False, indent=2))
    assert not {'main', 'app.config', 'app.database'}.intersection(sys.modules)
    return 1 if errors else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-complete', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.require_complete, args.output))
