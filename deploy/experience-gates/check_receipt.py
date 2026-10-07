#!/usr/bin/env python3
"""Fail-closed, stdlib-only exact-commit experience receipt gate."""
import argparse
import json
import math
from pathlib import Path
import re
import statistics

CONTRACT = json.loads((Path(__file__).with_name('contract.json')).read_text())

def validate(receipt, commit, kind):
    errors = []
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        return ['expected commit must be an exact lowercase 40-character SHA; no normalization']
    if kind not in ('synthetic-process', 'production-readback'):
        return ['unknown gate kind']
    if not isinstance(receipt, dict):
        return ['receipt must be an object']
    for key, expected in [('schema', CONTRACT['schema']), ('kind', kind), ('commit', commit),
                          ('harness_commit', commit), ('dirty', False), ('status', 'passed'), ('errors', [])]:
        if key not in receipt or receipt[key] != expected or (key == 'dirty' and receipt[key] is not False):
            errors.append(f'{key}: missing or not {expected!r}')
    checks = receipt.get('checks')
    if not isinstance(checks, list) or not all(isinstance(c, dict) for c in checks):
        return errors + ['checks must be an explicit list of objects']
    ids = [c.get('id') for c in checks]
    if any(not isinstance(i, str) for i in ids) or sorted(ids) != sorted(CONTRACT[kind]):
        errors.append('core check set differs: missing, duplicated or unexpected checks')
    for c in checks:
        if c.get('status') != 'passed' or c.get('expected') != 'passed' or type(c.get('attempts')) is not int or c['attempts'] != 1 or c.get('errors') != []:
            errors.append(f"{c.get('id')}: failed/blocked/skipped/flaky/retried/unexpected/missing result")
        if not isinstance(c.get('evidence'), str) or not c['evidence'].strip():
            errors.append(f"{c.get('id')}: evidence missing")
    if kind == 'production-readback':
        expected = dict(host='Nyarch', cache='normal', route_mocks=False, ordinary_session=True, diagnostic_recording=False)
        if receipt.get('environment') != expected:
            errors.append('production requires Nyarch + ordinary session + normal cache, without mocks/diagnostic recording')
        perf = receipt.get('performance')
        if not isinstance(perf, dict) or set(perf) != set(CONTRACT['performance']):
            errors.append('all three raw performance sample sets are required')
        else:
            for name, budget in CONTRACT['performance'].items():
                samples = perf[name]
                if not isinstance(samples, list) or len(samples) != budget['count'] or not all(type(x) in (int, float) and math.isfinite(x) and x > 0 for x in samples):
                    errors.append(f'{name}: exactly five positive finite millisecond samples required')
                elif statistics.median(samples) > budget['median_ms'] or max(samples) > budget['max_ms']:
                    errors.append(f'{name}: fixed median/max budget exceeded')
    return errors

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--kind', required=True, choices=['synthetic-process', 'production-readback'])
    args = parser.parse_args()
    try:
        errors = validate(json.loads(args.receipt.read_text()), args.commit, args.kind)
    except (OSError, ValueError, TypeError) as exc:
        errors = [f'receipt unreadable/invalid: {exc}']
    print(json.dumps(dict(gate=args.kind, commit=args.commit, status='FAIL' if errors else 'PASS', errors=errors), ensure_ascii=False))
    return bool(errors)

if __name__ == '__main__': raise SystemExit(main())
