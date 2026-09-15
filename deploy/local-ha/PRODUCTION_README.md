# Production app-only release

This is a real SSH/Docker transport, not the older `release.py` mock-only writer. The existing production installation has also passed real SSH/Docker releases and independent readback (2026-09-16). Unit tests alone are not evidence for a different installation. No PG stop/restart/promotion, migrations, frpc edits or host reboots are performed.

## Entry points

From repository root (Python 3.11+; tests additionally need PyYAML and Docker Compose CLI, no daemon):

```sh
python3 deploy/local-ha/production_release.py --validate-pack
python3 -m unittest discover -s deploy/local-ha/tests -v
# Read-only REMOTE checks, only after operator approval and variable setup:
python3 deploy/local-ha/production_release.py --dry-run
# ACTUAL application replacement, only after dry-run and operator approval:
python3 deploy/local-ha/production_release.py
```

`--validate-pack` is offline syntax validation only. `--dry-run` uses SSH, inspect, HTTP and SELECTs, but no login/pull/container writes. Default invocation performs deployment. Both remote modes require protected master/local-ha guards. Local test interpreter in the integration workspace: `/usr/local/lib/hermes-agent/venv/bin/python`.

GitLab job **local-ha-production-app** is blocking/manual, protected master only, target `local-ha`, resource group `stella-production`, non-interruptible. The build produces `production-image.env` with the immutable registry RepoDigest; the deployment emits `production-release-receipt.json`, preserved even on failure. Keep a trusted isolated runner and production-environment protected variables; YAML alone does not secure runner Docker sockets.

## Variables

| Variable | Source / required value |
|---|---|
| `CI_COMMIT_BRANCH` | GitLab: `master` |
| `CI_COMMIT_REF_PROTECTED` | GitLab: `true` |
| `STELLA_DEPLOY_TARGET` | protected variable: `local-ha`; **set explicitly**, unset still selects legacy k3s |
| `STELLA_PRODUCTION_INVENTORY` | protected File variable, operator-reviewed JSON below |
| `STELLA_PRODUCTION_SSH_KEY` | protected File variable, dedicated forced-command SSH private key; mode 0600 |
| `STELLA_PRODUCTION_KNOWN_HOSTS` | protected File variable, independently verified keys under aliases `stella-prod-nyarch` and `stella-prod-nas` |
| `STELLA_PRODUCTION_IMAGE` | build dotenv: `gitlab-registry.xiya.live/yaoyao/stellahaven@sha256:<64 lowercase hex>`; never a tag, commit SHA or config ID |
| `STELLA_EXPECTED_SCHEMA` | exact approved existing Alembic revision, equals inventory |
| `STELLA_RESOURCE_MANIFEST_SHA256` | exact full approved manifest SHA256, equals inventory |
| `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD` | GitLab registry pull credentials, password masked/protected; only needed for actual release |

No SSH key or registry password belongs in the repository. SSH uses `-F /dev/null`, strict known-host checking and explicit host aliases, with no interactive credential fallback. The helper source, request and registry password travel over encrypted stdin. Docker login uses `--password-stdin` in a temporary DOCKER_CONFIG; existing docker credentials are not changed.

## Operator-owned inventory

Shape is documented in `production_release.py` module docstring. Supply full reviewed values, not abbreviated hashes, and do not auto-approve a live inspect output. Required top-level fields:

- `scope: stella-production-app-v1`, `forward_compatible: true` (human compatibility approval, not an automatic proof).
- `schema_revision`, `manifest_sha256`, `signing_sha256` (full SHA256 of stripped `/data/secret_key` text).
- Exactly `nodes.nyarch` and `nodes.nas`: `host` = `10.66.0.2` / `10.66.0.3`, `alias` = `stella-prod-<node>`.
- Each node: complete existing `command` array containing `/shadow-start.py`, approved `startup_sha256`, integer Docker bytes `memory`, `nano_cpus`, exact `mounts` list of `{Source, Destination, RW}`.
- Mount sources must resolve within `/var/lib/stella-ha-app-shadow-20260916/`. Required destinations: `/app/data`, either `/tmp` or `/scratch`, `/data/secret_key`, `/run/secrets/app-password`, `/run/secrets/oidc-private.json`, `/shadow-start.py`. Optional destinations: `/data`, `/var/cache/stella`. Only `/data`, `/tmp`, `/scratch`, `/var/cache/stella` may be writable. No PGDATA allowed.

Operator must supply complete trusted manifest/startup hashes, exact mount paths, signing fingerprint and schema; the current installation has these pinned in protected CI variables and root-owned dispatcher inventory. Original source `.env` is neither read nor modified by the release transport.

## Current runtime contract

- Existing app container remains `stella-app-shadow-{nyarch,nas}` despite now being production. Host networking, `/app/.venv/bin/python`, workdir `/app`, read-only root, ALL capabilities dropped, no-new-privileges, bounded memory/CPU.
- Existing production `PGOPTIONS` must be exactly `-c statement_timeout=30000`. Old shadow read-only settings are rejected, not silently rewritten. Database/signing override variables are rejected.
- PG containers: `stella-pg-{nyarch,nas}-runtime`, scope `stella-pg`, source PGDATA `/var/lib/stella-ha-runtime/<node>/pgdata`. Helper reads the live Patroni `/run` config inside the PG container and validates `stella-pg`; no dependency on a PATRONI_SCOPE environment variable.
- App connects to local `127.0.0.1:24532`; probes query both WG addresses at PG 24532 and Patroni 24808, verify one writable primary, schema and matching peer observations. Probe SQL is SELECT-only.
- Stable app port 25131; temporary candidate port 25132 must be free. `/live` = 200, `/ready-primary` = 200 on primary and 503 on replica.
- Existing frpc is untouched: local `frpc@stella-ha`, `/opt/frpc/conf/stella-ha.toml`, proxy `stella-runtime-nyarch`; NAS existing unit/proxy `stella-runtime-nas`. Both remain pointed at stable port 25131 and `/ready-primary`; no assumed app systemd service.
- Registry digest is pulled separately per daemon; each candidate/replacement is checked against that daemon's resolved image inspect ID and content. No cross-daemon ID equality assumption.

## Deployment and recovery boundaries

Probe both nodes → release current standby → re-probe roles → release current active app. No PG role switch. Each node: pull digest, start candidate at 25132, validate resources/signing/schema/HTTP, stop and rename old app, create/start replacement at 25131, validate it, remove candidate. The approved ordinary application startup runs, bypassing image migration entrypoint. Existing stable restart policy (`no`, `always`, `unless-stopped`) is preserved; candidate uses `no`. Active app replacement can briefly disconnect requests/WebSockets.

Failure rolls back only containers created by that attempt and restores the exact old container ID/image. Successful old containers stay stopped under `-rollback-<id>`; cleanup is operator-owned. A completed standby update is not automatically undone if active update fails. Receipts preserve per-node results; this is not an atomic two-node transaction.

**Boundaries:** real registry/SSH/Docker execution was validated on the current two-node installation. The deploy job does not log in as a real business user or perform document/attachment mutations; separate acceptance covers those. It does not implement distributed fencing, durable crash recovery after SSH timeout/kill, or automatic inventory/PG/frpc management. Resource hashing and remote calls are bounded, but an unknown SSH outcome still requires exact-state readback. Sampled role checks are not fencing. Concurrent candidates share approved writable cache/tmp paths. Review release startup compatibility accordingly. On unknown SSH outcome or incomplete rollback, inspect exact receipt/container IDs before retrying; never broad-prune containers.

Production SSH is root on Nyarch and yaoyao on NAS; the dedicated key is forced to a root-owned dispatcher (specific sudo command on NAS). Dispatcher rejects helper hashes and inventories not pre-approved locally. Root SSH remains disabled on NAS. After the first manual deployment passes, protected STELLA_AUTO_DEPLOY=true enables on-success app releases; schema/resource changes still fail closed until approved inventory is updated.
