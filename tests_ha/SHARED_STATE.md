# Opt-in OIDC / SMTP shared state

Default `STELLA_SHARED_STATE` unset or `legacy` retains the existing JSON/PVC implementation. `postgres` uses `ha_shared_state` JSONB rows and PostgreSQL row locks. Invalid values fail closed. No request-time legacy import, DB-failure file fallback, or private-key DB storage.

## Migration / cutover

1. Stop all OIDC/SMTP writers; snapshot clients.json, email_config.json and optionally runtime/state.json. Existing application access tokens/codes are lost unless explicitly importing runtime.
2. Apply Alembic revision `a6b7c8d9e0f1` (parent `f1e2d3a4b5c6`). Later blob migration should chain from this revision. Schema migration creates an empty table only; it does not enable PG mode.
3. Provision the SAME existing private JWK on all nodes with restrictive file permissions and mount read-only. Set `STELLA_OIDC_PRIVATE_KEY_FILE` to its path (defaults to data/oidc/private.json). PG mode refuses to generate a node-local signing key. Never print this file.
4. Explicitly import BEFORE any PG-mode requests (even reads initialize rows). From project root, with a mode-0600 DSN-only file:

   `PYTHONPATH=. python scripts/import_shared_state.py --database-url-file /private/dsn.txt --confirm-database stella_ha_integration --clients /snapshot/clients.json --smtp /snapshot/email_config.json`

   Optional `--runtime /snapshot/state.json`. Missing source options are untouched. Existing target rows are NEVER overwritten, even empty rows. All selected imports commit together or roll back; no overwrite flag. CLI output contains only state-key names or a generic error, not payloads/DSNs. Treat snapshots, DB and backups as secrets (client/SMTP secrets are not encrypted by this layer).
5. Set `STELLA_SHARED_STATE=postgres` consistently across nodes, restart and validate login and SMTP config masking. Keep issuer and signing key identical.

Rollback to legacy requires stopping writers first. Legacy JSON remains unchanged and therefore stale after PG writes; do not switch a live mixed-mode fleet. Downgrade deletes all shared-state rows; back up before downgrading.

## Verification

Use the existing venv, no installation needed:

`STELLA_HA_STATE_PG_TEST=1 PYTHONPATH=. /opt/Yunxi-workstation/Stella/.venv/bin/python -m pytest --noconftest tests_ha/test_shared_state.py tests/test_oidc_shared_state.py -q`

Fixture hard-checks `172.25.0.2:5432/stella_ha_poc`, creates/drops only random `ha_state_test_*` schemas, stubs app configuration/auth imports, and redirects files to pytest tmpdirs. Do not run legacy tests/conftest.py against the workstation's .env: its database naming replacement is not a safe isolation mechanism. Logs: `/tmp/stella-shared-state-{red,green,import-red,import-green,regression}.log`.

Limitations: one runtime row serializes OIDC operations; this is correctness-first, not high-throughput design. Signing and access-token persistence follow code consumption (existing behavior); a crash/signing failure after consumption requires a fresh authorization flow. No SMTP network message is sent by tests. Full auth/API tests need the parent's isolated application DB runner.
