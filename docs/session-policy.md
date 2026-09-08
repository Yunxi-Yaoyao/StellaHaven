# Session lifetime contract

No migration or cleanup is required. Existing `created_at`, `last_seen`, `remember`, and `revoked` fields determine validity. Expired and revoked records are retained.

- Remembered: absolute deadline `created_at + 30 days`; refreshing cookies uses only remaining lifetime.
- Not remembered: idle deadline `last_seen + 30 minutes`; expiry checked on both access and refresh.
- `/auth/me`, arbitrary background polling and refresh do **not** update activity.
- Browser visible trusted pointer/key/wheel/touch input calls `POST /auth/activity`, throttled to one request/minute. Activity timestamps therefore have minute-level precision. Opening/focusing a tab alone does not extend lifetime.
- CLI/API clients must explicitly call authenticated `POST /auth/activity` when the user operates them, no more than once/minute; do not run an unconditional timer. Existing CLI clients without this integration expire after 30 minutes unless remembered. The endpoint checks expiry again under lock and cannot revive expired sessions.
- Logout revokes the presented refresh session, falling back to a verified access SID. Same-user login replaces only the presented valid session, never IP/UA-matched devices.
- `/auth/sessions` keeps its list response and now accepts `page`/`page_size` (default 20, max 100), only valid sessions.
- `/auth/sessions/history` returns `items,total,page,page_size`; normal users see their own rows, admins all rows. UI fetches history only when expanded.

Validation: `python -m pytest tests/test_session_policy.py`; `cd frontend && npx vitest run --config vitest.auth.config.mjs && npx vue-tsc -b`.
Tests use a private in-memory SQLite database, not the configured shared database. Frontend tests cover activity behavior plus source-level folded/history/watchdog contracts; they are not browser visual QA.

No deployment, restart, production data changes, or schema application performed.
