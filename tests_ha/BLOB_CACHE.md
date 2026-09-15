# Blob cache acceptance contract

Validated 2026-09-16 against disposable `poc@172.25.0.2:5432/stella_test_ha_integration`; no production migration, etcd, or WireGuard changes.

## Implemented behavior

- `STELLA_BLOB_CACHE` defaults to `data/blob-cache`. Linux local filesystem required (`flock`, `posix_fallocate`, `O_NOFOLLOW`). All processes sharing the directory must use the same quota/TTL configuration.
- `STELLA_BLOB_CACHE_MAX_BYTES` defaults to 256 MiB. Quota covers managed payload allocations, including in-progress fills and pinned downloads; directory/lock metadata and unrelated files are excluded. Reservations round up to filesystem block size; actual allocation is checked before publication.
- Global exclusive flock serializes reservation/fill/publication. SHA-256 names deduplicate payloads. Per-inode shared FD locks pin active responses; eviction only removes files for which an exclusive nonblocking lock succeeds. No unlink-and-forget active-byte loophole.
- mtime LRU eviction; `STELLA_BLOB_CACHE_TTL_SECONDS=86400` by default. TTL is lazy, on access—not a background deletion deadline. Crash-abandoned `.fill-*` files are reclaimed on subsequent access. Foreign files/subdirectories/symlinks are not deleted.
- Quota exhaustion, ENOSPC and EDQUOT produce 503, `Retry-After: 5`, `Cache-Control: no-store`. Partial fills are removed. ENOSPC tests inject the allocation/fsync OS error; they do not fill the host disk.
- Metadata/chunks are read in an independent PostgreSQL REPEATABLE READ READ ONLY session. No FOR SHARE locks; session closes before response body IO. Caller dirty state is not committed or rolled back by `blob_store.response`.
- Attachment GET/HEAD close the route's read-only authentication/authorization session before response creation. Private successful responses, conditional 304, Range 206/416 and cache-capacity failures use `no-store`. HEAD is an actual router method, metadata-only, empty-body, full Content-Length; Range is ignored on HEAD. Public avatar/background URLs remain public.
- FileResponse pathsend is disabled so its lifetime cannot outlive the pin. Response `finally` closes the FD on completion, disconnect or cancellation, including cancellation while response-start is blocked before the first body. Real TCP disconnect is separately exercised.

## Final evidence

Artifacts: `/opt/hermes-workstation/stella-ha-poc/evidence/cache-final/`.

- `13-final-cache.txt/.xml`: **49 passed**, including 8 real uvicorn loopback HTTP + PostgreSQL tests, blob function regressions, cross-process cache tests and exact test-DB guard tests.
- `14-final-attachments.txt/.xml`: **6 passed**, existing full-main-app attachment tests including PG uploads, range, deletion and upload idempotency.
- `final-summary.json`: parsed JUnit total **55**, zero failures/errors/skips; read-back identity `[stella_test_ha_integration, poc, 172.25.0.2, 5432, ha-integration-test-only]`; zero remaining `cache_test_*` schemas.
- Real HEAD: 200, body 0 bytes, Content-Length 1638400, Cache-Control no-store.
- Artificially stalled HTTP body: pool checked-out count 0; pg_stat_activity idle-in-transaction count 0 for the test application's connections; concurrent DELETE committed in 0.012219 s with a 500 ms lock timeout. Completed old download SHA-256: `99d3806fc5c92c2474e343fd846cc74da3e1f0054af613d14c968a5b298258fc`; subsequent GET 404.
- Real HTTP verified: quota-zero HEAD succeeds/GET503; active download blocks eviction and second fill with503, then recovers after release; TCP disconnect releases flock; injected ENOSPC503 cleans up and next GET succeeds. Independent RR snapshot continues intact while concurrent chunk DELETE commits; caller's dirty state survives.
- `git diff --check` clean. Existing Starlette/httpx and Authlib deprecation warnings remain; no warning-driven dependency changes in this patch.

## Exact rerun

One runner at a time: the existing `tests/conftest.py` creates/drops tables in the explicitly guarded disposable database.

```sh
/opt/Yunxi-workstation/Stella/.venv/bin/python /opt/hermes-workstation/stella-ha-poc/evidence/cache-final/rerun.py
```

The script derives only the exact allowlisted test target from the worktree settings, never prints the password, runs the two suites sequentially, saves logs/JUnit, then reads DB identity and schema cleanup back. The self-contained HTTP fixture now uses `testdb_guard` too; its old stage-only assertion was the only observed remaining failure (`10-isolation-red.txt`). Guard rejects URL overrides/ambient PG variables and rechecks actual connection identity before DDL.

## Scope and limits

This is a verified bounded disk-cache materialization design, not direct PostgreSQL-to-client streaming: a cold GET fills the entire object before the body starts, and fills serialize under the global lock. Thus cold-fill latency and connections waiting for that lock are not claimed eliminated. A file larger than the configured cap receives503. Quota measures managed payloads, not a filesystem-wide hard quota; operate on a trusted private local cache directory. These tests do not prove live two-node failover, replica recovery-conflict handling, production migration, performance under sustained load, or blanket no-store on authentication middleware failures before the attachment route executes. Those are outside this acceptance run.
