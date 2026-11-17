# Historical contract closure (QA only)

The approved successor to the legacy coverage adapter. No application code,
frontend/src, production guard, credentials, or live configuration is changed.
The original pytest IDs are retained; 8 obsolete contract expectations and
3 in-body fixed targets are explicitly migrated, not xfailed/deselected.

## Scope and IDs

- `test_unreferenced_attachment_deleted_on_save`: retained versions protect bytes.
- `test_pg_attachment_no_file_and_delete`: pending upload survives unrelated save.
- `test_attachment_follows_doc_physical_delete` and `test_delete_trashed_purges`:
  repeated DELETE stays soft; `/permanent` removes records and bytes, retry is 204.
- `test_manual_save_clears_draft`: title-only save retains the slot; exact hash/time
  consumption clears it, verified through a fresh session.
- `test_expired_trash_readonly_until_explicit_elevated_purge`: GET is read-only;
  ordinary owner can explicitly purge; anonymous/foreign requests remain denied.
- `test_smtp_postgres_transaction_and_mask`: PublicSMTPConfig plus actual HTTP
  GET/PUT, masked-secret preservation and transaction rollback readback.
- `test_real_browser_zip_template_roundtrip`: navigate the real More menu;
  every original JS assertion remains. Python original ID is unchanged.
- Audit concurrent insertion, memory JSONB roundtrip, CLI private-output originals
  accept `owned_target`. The imported default fixture returns **None**, preserving
  the literal old host/port/socket/database guards and CLI confirmation name.

`test_owned_target_guard.py` independently tests default rejection/skip behavior,
unbound/foreign namespace/binding refusal, wrong URL and DBAPI targets **before
connection**, ambient libpq overrides, and real same-connection SQL identity.
A temporary owned role exercises actual identity mismatch (no fabricated result).

## Run and evidence

Use `/opt/Yunxi-workstation/Stella/.venv/bin/python`; never install into that venv.
`control.py provision` creates a git archive without `.env` and a new random
PG17 container/database/role/password/loopback published port. It never accepts
an arbitrary DSN or existing container. Task-specific paths are in control.py.
The approved test-only overlay is recorded by SHA and exact diff separately
from the untouched production archive. Tests run exclusively in the new PG
network namespace: OUTPUT deny except PG, namespace-only HTTP and established
responses; IPv6 OUTPUT deny; host firewall untouched.

Before every `run`, the launcher verifies the actual Docker ID, label, running
PID and published binding. The owned-target fixture verifies the private binding
receipt and actual namespace; URL validation precedes connect, DBAPI validation
precedes the driver, and SQL identity is checked on checkout and the same
connection before DDL. Only random owned schemas are created/dropped, with
absence readback. No production `testdb_guard` changes.

Frontend is built in the owned scratch archive with scrubbed environment and
`npm ci --include=dev --ignore-scripts`; installed package versions are compared
to this candidate's lockfile. `control.py browser-artifacts` admits only the
owned namespace HTTP listener. Never borrow a stale lockfile's bundle.

`batch.py final all` runs the exact 312-case collection in separate serial
processes, including all formerly unrun 27 files, 97 PG opt-ins and real Chromium.
The retained 10 independent positive equivalents are counted separately from
the 302 original IDs; they are not additional business coverage.
`control.py run <file> owning --full-owning` includes previously passing cases
for modified owning suites. Guard proofs use a separate `guard-acceptance` label.
`aggregate.py` requires exact prior-ID-set equality, reconciles JUnit elements,
declared counts and actual subtest reports, and distinguishes attempts from
final unique cases. No old failure is removed from the inventory.

Full-main schemas run real Alembic and register/setup/login/unlock. Only get_db
is rebound. Historical partial service fixtures keep their original limited
scope (e.g. SMTP safe_modules auth stubs); they are not advertised as full-main
auth proof. Full-main SMTP is independently exercised by test_current_contracts.

Evidence lives outside git under
`/opt/hermes-workstation/docs/Stella-API/remediation/historical-contract-close/`:
RED/failed attempts, final XML and per-ID event receipts, old/new assertion
mapping, exact diff, source/guard hashes, browser screenshots, schema cleanup
and exact container-removal readbacks. `finalize.py` verifies approved edits,
untouched product files and cleanup. No push, deployment or task-card changes.
