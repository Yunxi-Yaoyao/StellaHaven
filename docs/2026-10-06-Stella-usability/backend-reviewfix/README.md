# Backend review fixes

Isolated TDD fixes: R2, R3 backend compatibility, R5, R6, and R7.

Run from this worktree using the explicit opt-in review isolation plugin:

```sh
PYTHONPATH=/opt/hermes-workstation/stella-usability-reviewfix-backend UV_PROJECT_ENVIRONMENT=/opt/hermes-workstation/stella-usability-reviewfix-backend/.venv /opt/hermes-workstation/stella-usability-20261006/.venv/bin/python -m pytest tests_website_settings --noconftest -p tests_website_settings.review_isolation -q -k "not real_auth_identity" --junitxml=docs/2026-10-06-Stella-usability/backend-reviewfix/evidence/final.xml
```

`review_isolation.py` pre-injects synthetic database/auth/package bootstrap and fails closed on non-loopback TCP and database ports. It is not automatically enabled in normal project tests. The actual target services, routers, transport, audit, model, and SQLite transaction code execute. Real-auth test must remain deselected for this harness.

See `REPORT.json`, final XML/log, and failing RED XML evidence. Source hashes bind this report to the tested implementation. Counts are from parsed XML, not summed duplicate re-runs.

R6 uses the explicitly requested frozen HTTP80→HTTPS443 compatibility. The fetched latest CSP3 WD differs; exact frozen and latest source excerpts are retained and the report does not assert current-browser equivalence.
