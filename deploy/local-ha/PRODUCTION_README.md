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
| `STELLA_APPROVED_AGENT_ROLLOUT_VERSION` | explicit protected approval matching both nodes' `application_env_overrides.STELLA_AGENT_ROLLOUT_VERSION`; this validator allows `0.6.9` through `0.6.15`, unset defaults to `0.6.9`. Candidate Agent source `0.6.18` is not approved by that allowlist; changing the announcement or fleet requires separate compatibility/helper approval. |
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

Agent `0.6.12` originally extended read-only cross-platform storage/GPU collection; that historical approval is not a rollout approval for every later source revision. The current validator's exact allowed versions are listed above. Retain the fleet privilege-helper approval/readback prerequisite and explicitly review any new announcement version. A parked older announcement returns only its version, never a manifest pretending that newer script bytes are the announced release.

## Current runtime contract

- Existing app container remains `stella-app-shadow-{nyarch,nas}` despite now being production. Host networking, `/app/.venv/bin/python`, workdir `/app`, read-only root, ALL capabilities dropped, no-new-privileges, bounded memory/CPU.
- Existing production `PGOPTIONS` must be exactly `-c statement_timeout=30000`. Old shadow read-only settings are rejected, not silently rewritten. Database/signing override variables are rejected.
- PG containers: `stella-pg-{nyarch,nas}-runtime`, scope `stella-pg`, source PGDATA `/var/lib/stella-ha-runtime/<node>/pgdata`. Helper reads the live Patroni `/run` config inside the PG container and validates `stella-pg`; no dependency on a PATRONI_SCOPE environment variable.
- App connects to local `127.0.0.1:24532`; probes query both WG addresses at PG 24532 and Patroni 24808, verify one writable primary, schema and matching peer observations. Probe SQL is SELECT-only.
- Stable app port 25131; temporary candidate port 25132 must be free. `/live` = 200, `/ready-primary` = 200 on primary and 503 on replica.
- Existing frpc is untouched: local `frpc@stella-ha`, `/opt/frpc/conf/stella-ha.toml`, proxy `stella-runtime-nyarch`; NAS existing unit/proxy `stella-runtime-nas`. Both remain pointed at stable port 25131 and `/ready-primary`; no assumed app systemd service.
- Registry digest is pulled separately per daemon; each candidate/replacement is checked against that daemon's resolved image inspect ID and content. No cross-daemon ID equality assumption.

## Exact application environment approval versions

`application_env_overrides` remains a complete, non-secret, operator-owned approval, identical on both nodes. The validator accepts only these two exact key sets, not arbitrary environment keys or a partial extension:

- **Legacy six fields:** `STELLA_TRUSTED_ORIGINS`, `STELLA_MAIN_ORIGIN`, `STELLA_OWNER_ID`, `STELLA_COOKIE_SECURE`, `STELLA_AGENT_ROLLOUT_VERSION`, `STELLA_BACKUP_RECEIPT_DIR`. Their existing validation and initial/rollback tolerance are unchanged; no cache mount is newly required for this version.
- **Entry/backup eight fields:** exactly the legacy six plus **both** `STELLA_ENTRY_REGISTRY` and `STELLA_BACKUP_DIRECTORY`. All existing owner UUID, secure-cookie, explicit agent rollout and read-only receipt-bundle approvals still apply. This is not permission to override database/signing variables, use `target_mounts`, or copy a live Env into an approval.

The new registry is a JSON array encoded as one environment string (no literal newlines). Each row has exactly `{service_id, public}` or `{service_id, public, private}`. Service IDs match `[a-zA-Z0-9_-]{1,64}` and are unique; JSON member names and origins must also be unique. Accepted origins are the exact canonical HTTPS authorities below: no credentials, path (including trailing `/`), query, fragment, wildcard, explicit port, uppercase/trailing-dot host or unrelated external API.

| Service ID | Public | Private |
|---|---|---|
| `stella` (required) | exactly `STELLA_MAIN_ORIGIN`: `https://stella.xiya.live` or `https://stella.yunxi.life` | exactly `https://stella.p.xiya.live` (required) |
| `web-project-runtime` (if present) | `https://pages.xiya.live` | `https://pages.p.xiya.live` (required when this record is present) |
| `gallery` (if present) | `https://immich.xiya.live` | `https://immich.p.xiya.live` (required when this record is present) |
| Other stable module ID `ID` | exactly `https://app-ID.xiya.live` | if provided, exactly `https://app-ID.p.xiya.live` |

The module rule verifies the **explicit row**, matching `app/services/integrations.py::derived_origin`; it does not rewrite URLs or discover private peers. `app-ID` must itself be a canonical lowercase DNS label of at most 63 characters. IDs that cannot form that exact hostname (for example underscores, uppercase, overlong labels or trailing hyphens) are rejected rather than repaired. A module may explicitly register only public; a missing private lane is not synthesized. External/direct sites outside these owned app authorities need a separately reviewed contract, not a suffix-wide exception.

The main origin must remain a trusted **public** origin. In the eight-field version, `https://stella.p.xiya.live` must be both the exact registered Stella private lane and explicitly listed in `STELLA_TRUSTED_ORIGINS`. Both loopback health origins `http://127.0.0.1:25131` and `http://127.0.0.1:25132` remain mandatory. The public Stella aliases may remain trusted. Registry entries for pages/gallery/modules do **not** grant main-site trust; they need not and must not be added to this main-site trusted-origin approval. A `.p.xiya.live` suffix alone grants nothing. The six-field version still rejects the private Stella origin.

`STELLA_BACKUP_DIRECTORY` accepts only **`/var/cache/stella/backups`**, not arbitrary environment paths. Both the offline inventory validator and Node constructor/create boundary require an already approved bind with exactly `Source=/var/lib/stella-ha-app-shadow-20260916/cache`, `Destination=/var/cache/stella`, `RW=true`. The unchanged running-container validator then verifies the exact actual mount inventory. Do not add a mount, make `/app/data` writable, use its model/receipt bundle as backup output, point at the cache's `blobs` source, or borrow `/tmp`, `/scratch` or PGDATA. These checks do not create the backup directory or perform a backup. The environment supplies an application default only; a user-selected runtime directory remains an application-level choice subject to existing mounted/reachable paths and read-only-root permissions. It does not authorize a new environment path or host mount.

**Compatibility is unchanged:** ordinary release still requires explicit `forward_compatible=true`, candidate-first standby/active ordering and exact old-container/Env rollback. Do not set that flag to admit a non-compatible migration. That migration still needs a separately reviewed maintenance controller/barrier; this environment extension neither implements one nor makes the old automatic rollback safe after a schema commit. Updated helper hashes and complete per-node inventories/forced-command approvals must be independently reviewed before any real use; this code change does not apply them.

## Separately approved startup-only normalization

`normalize_manual_runtime.py` is an opt-in local-node repair, not a relaxed ordinary release guard. Its default/`--dry-run` performs local read-only Docker/probe checks; only `--validate-pack` is fully offline. `--apply` requires independent review of a complete stdin approval: exact `scope=stella-manual-runtime-normalize-v1`, node, golden inventory, both expected roles, full local PG ID, approved local image content, and `approved_old` containing the full `Id`, `Image`, `Config`, `HostConfig`, `Mounts` snapshot. Never generate and automatically approve that payload or log its Env.

The original historical weak manual shape remains unchanged. The additional secure-inline legacy shape accepts **only** Python entrypoint `['/app/.venv/bin/python']` and command `['-c', START, '25131']`, where `START` is the exact fixed secret-file/uvicorn string in `node_production.py`, without suffixes, wrappers or alternate ports. It requires golden read-only root/resource/capability pins, exactly `['no-new-privileges']`, and restart `{'Name': 'unless-stopped', 'MaximumRetryCount': 0}`. Only `Cmd` is changed in a validation **copy** to `['/shadow-start.py']`; the entire unchanged `Node.validate` contract then checks all other security, environment, mount and startup-hash pins. Unsafe secure-inline snapshots cannot borrow the historical weak shape's sandbox repair substitutions.

Before an ordinary release, serialize standby-first externally: validate the complete candidate constructor before start, verify strict candidate health at 25132, restore the golden `/shadow-start.py` command at stable port 25131, and independently read back both nodes. Image, exact Env and PG are not changed by normalization. Failure restores and verifies the original complete snapshot, including the original secure-inline command and restart policy; failed app containers are retained, never broadly removed. Unconfirmed create outcomes remain blocked even when the old app is healthy. This helper does not approve CI variables/helper hashes or provide distributed fencing.

## Deployment and recovery boundaries

- **Edge-first release gate:** a green app CI/release does not establish HK edge asset readiness. Before app release, stage the exact immutable image digest's `dist` on HK, verify its manifest/files, and use the existing `deploy/usability/deploysafe.py apply <new-stage> --primary-stage <approved-current-stage> --expected-vhost-sha256 <exact-reviewed-hash> --approve-production-write` path to retain current and new assets. Independently read back the HK exact static allowlist and both stages' asset responses/hashes, then release the app and read back both HA nodes plus public HTML/assets. Do not release on an unverified edge or invent new CI orchestration.
- **Startup/retry gate:** an old app may still carry the approved secure-inline startup, and later retries can require restoration of the golden startup again. Use the existing strictly approved `normalize_manual_runtime.py` recovery path and exact-state readback before retry; do not relax ordinary guards, rewrite inventory automatically, or replace it with a new mechanism.

Probe both nodes → release current standby → re-probe roles → release current active app. No PG role switch. Each node: pull digest, start candidate at 25132, validate resources/signing/schema/HTTP, stop and rename old app, create/start replacement at 25131, validate it, remove candidate. The approved ordinary application startup runs, bypassing image migration entrypoint. Existing stable restart policy (`no`, `always`, `unless-stopped`) is preserved; candidate uses `no`. Active app replacement can briefly disconnect requests/WebSockets.

Failure rolls back only containers created by that attempt and restores the exact old container ID/image. Successful old containers stay stopped under `-rollback-<id>`; cleanup is operator-owned. A completed standby update is not automatically undone if active update fails. Receipts preserve per-node results; this is not an atomic two-node transaction.

**Boundaries:** real registry/SSH/Docker execution was validated on the current two-node installation. The deploy job does not log in as a real business user or perform document/attachment mutations; separate acceptance covers those. It does not implement distributed fencing, durable crash recovery after SSH timeout/kill, or automatic inventory/PG/frpc management. Resource hashing and remote calls are bounded, but an unknown SSH outcome still requires exact-state readback. Sampled role checks are not fencing. Concurrent candidates share approved writable cache/tmp paths. Review release startup compatibility accordingly. On unknown SSH outcome or incomplete rollback, inspect exact receipt/container IDs before retrying; never broad-prune containers.

Production SSH is root on Nyarch and yaoyao on NAS; the dedicated key is forced to a root-owned dispatcher (specific sudo command on NAS). Dispatcher rejects helper hashes and inventories not pre-approved locally. Root SSH remains disabled on NAS. The current CI deployment job is manual: `STELLA_AUTO_DEPLOY=true` does not override its `when: manual` rule. Re-read the target commit's complete CI rules before any push or deployment. After maintenance releases, reconcile the exact approved schema and complete environment with both running nodes before a new release; never modify inventory merely to make a failing guard pass. Schema/resource changes still require explicit review and the appropriate maintenance procedure.
