# Fixed-HEAD Notes joint QA

Product snapshot: `6b01e8e7714b7cd87c425ae71cb74ca3df956a65`.
These files are test harnesses only. Do not run against production. No existing DSN is accepted.

## Evidence layers

- `test_live_http.py`: real TCP Uvicorn / full main / owner auth / dedicated PG. Real register → setup → logout → login → unlock, then a distinct ordinary owner session. Direct SQL is limited to guarded synthetic setup, failure/concurrency interleavings and fresh readback.
- `joint.spec.ts`: actual locked-dependency production build, Chromium, real HTTP/WS and PG. No business-response mocks. Playwright routes only abort requests, lose a genuine response, delay a genuine response or deny non-origin traffic. `db_bridge.py` seeds synthetic draft/tree conditions and independently reads committed results.
- `test_independent_corrections.py`: F8 rollback is read before retry, then retry cleanup is verified. F9 forwards service kwargs and only a real controlled HTTPException may pass; raw FK/500 still fails, and orphan rows are checked.
- `audit_original.py`: hashes unchanged original RED and retains a kwargs-only diagnostic demonstrating the original exception wrapper still turns controlled rejection into failure.
- `run_suites.py`: supplemental unchanged lifecycle/boundary/draft/tag/PG and frontend suites. Its original PG fixture replaces only DB dependency; do not confuse it with the override-free full-main TCP proof.
- `aggregate.py`: parses exact JUnit case IDs, records source hashes and actual runtime auth-policy schema. Does not add overlapping suites into one total.

## Owned resources / execution

`control.py provision` archives the fixed product commit without `.env`, installs `npm ci --include=dev --ignore-scripts` in scratch, provisions a fresh random-role/database/label PG with random loopback ports, caps CPU=1 and memory=768MiB, and denies external egress only in its own network namespace. The 512MiB data tmpfs includes WAL/index budget. It never changes the host firewall.

`control.py build` runs vue-tsc and Vite on that archive. `control.py serve` is a foreground service to track and terminate explicitly. `netns_browser.py relay` starts a raw, byte-preserving loopback TCP relay inside the owned namespace; it is not Vite or an HTTP/business proxy. `netns_browser.py run` runs Chrome and the browser harness in the same externally denied namespace. Only own PG/app loopback ports and established responses are allowed; direct external connectivity is probed and must fail.

`server.py` keeps real production dependencies and `dependency_overrides == {}`. SQL identity is checked on checkout and the exact DDL connection. SMTP is an outbound sink. Socket/process audit hooks deny non-PG connections and process execution. The optional private fault file only injects failure at the actual orphan-tag SQL boundary. It is never a product endpoint.

All runtime files live under the fixed audit scratch directory `/root/.hermes/cache/scratch/notes-joint-6b01e8e`. This is a single-run forensic harness, not an idempotent deployment script: for another run choose a new owned scratch directory consistently in all harness paths before provisioning. Never reuse a disposed container ID or another lane's DSN.

Stop the exact relay and Uvicorn processes before `control.py cleanup`. Cleanup verifies Docker ID/label, checks the same DB identity, drops only the random audit schema, reads schema absence/public emptiness, removes only the exact container, and reads back container absence. Remove synthetic cookie state after evidence redaction.

## Reporting rules

Final evidence is in `/opt/hermes-workstation/docs/Stella-API/remediation/review-notes-joint*`.
Preserve earlier attempts; final browser evidence must be from frozen-lockfile packages, not borrowed UI-lane versions. Initial borrowed DOMPurify/Vue versions differed and their runs are explicitly superseded. `npm ci --include=dev` is mandatory because ambient production mode can omit test/build dependencies.

Known non-green gates are retained as failures, not skips/xfails: stale/unclassified response contracts (including delete-preview), original contradictory RED harness, and the two fixed-snapshot Home tests. Review of later test-only Home commit is not execution on that commit. Do not call this a full final-tree/deployment acceptance.
