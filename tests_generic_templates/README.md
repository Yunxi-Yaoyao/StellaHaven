# Generic website template backend verification

Run in a scratch working directory with the existing read-only Stella venv. Do not
use the application `.env` or `tests/conftest.py`:

```sh
STELLA_GENERIC_TEST_PG=1 PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/opt/hermes-workstation/stella-generic-backend-20261007 \
/opt/hermes-workstation/stella-usability-20261006/.venv/bin/python -m pytest \
  --noconftest -p no:cacheprovider \
  /opt/hermes-workstation/stella-generic-backend-20261007/tests_generic_templates \
  /opt/hermes-workstation/stella-generic-backend-20261007/tests_website_settings
```

The PG cases require the explicitly owned container receipt and synthetic env
file named in `test_pg_generic.py`. They validate container ID, loopback port,
tmpfs, database/user/server identity, use random per-test schemas, and verify
schema removal. Without the explicit PG flag those two cases skip (not a PG pass).
SQLite/loopback cases never connect application PG. No production data, secrets,
Nginx, service configuration or user browser are used.

## Operator cutover

After backup and DNS-only approval of the drive upstream, call:

```python
from app.services.website_migration import migrate_legacy
aliases = migrate_legacy(db, approved_ips=[approved_drive_ip], actor_id=owner_uuid,
                         main_origin=canonical_stella_origin)
```

It exports the effective preset plus enabled saved customization, archives legacy
draft/previous, creates ordinary modules and preserves effective navigation in
one transaction. It returns `{drive: module_id, gallery: module_id}`; secrets stay
only in targets/retained private snapshots. No GET/startup migration is registered.
The parent deployer must replace the old gallery script with
`<script src="https://STELLA/website-assets/MODULE_ID.js"></script>` without
`crossorigin=anonymous`. The script will return no saved code anonymously. Keep
original Immich/OIDC ingress. Do not change OpenList SITE_URL/customization merely
to migrate: the proxy strips only signed, complete legacy style/script elements.

Immediate rollback is `rollback_legacy(db)` together with the old application
release. It refuses intervening registry edits rather than discard new work.
Original connection/appearance/injection rows remain retained. A migrated module
can also use ordinary injection rollback independently. Deleted aliases do not
revive on migration retry.

## Coverage boundaries

Checks include complete visible code copies, independent template instances,
secret validation/readback redaction, exact saved-credential binding and races,
basepath permission gates, live grant revocation on policy changes, disabled code,
attachment streaming, no hidden runtime builtin reads, direct loader origin and
owner/session gates, original targets on legacy quota edits, PG migration locks
and rollback, and retired route denial. Existing website regression and selected
real auth/Host/WebSocket tests run separately. Browser rendering, nginx loader
installation, production migration/OIDC/data preservation require parent release
acceptance; an HTTP probe is not browser readiness.
