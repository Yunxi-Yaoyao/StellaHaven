# Backend browser prerequisites follow the execution plan

`run-backend-shard.py --requires-browser` is a stdlib-only **setup predicate**;
run it with system Python before uv installs project dependencies. It calls the
same `plan(root, index, total)` used by execution, then checks the explicit
`UNCONDITIONAL_BROWSER_TESTS` file metadata against that shard's commands. The
planner's deterministic setup-aware LPT assignment, grouped suite commands and
fail-fast per-file Python processes are shared. CI170 capacity acceptance now
selects six independent job budgets; the effective 20m cap and runner concurrency
are unchanged (see `../BACKEND_SHARDING.md`). No shard numbers
belong in the prerequisite script or its expected browser set.

The existing root README's independent `tests_isolated` process contract remains
in force. This predicate does not import test modules, collect pytest, parse
JavaScript imports, infer dependencies from filenames, or enable opt-in tests.
An import/filename scan cannot establish an unconditional browser requirement:
fixtures can skip before the browser call, including through inherited fixtures.
New unconditional browser test files must be added to the explicit metadata and
reviewed in the owning browser contract; sorting/inventory growth then requires
no shell or shard-list edit. Directory suite commands also match metadata below
their directory.

## Reviewed browser call boundaries

| Test file / command | Browser entry point | CI requirement |
|---|---|---|
| `tests_isolated/test_dual_entry.py` | `test_real_browser_bootstrap_cookie_refresh_replay` → `frontend/tests/dual-entry-browser.mjs` → Playwright Chromium | Unconditional; SQLite/loopback fixture, no owned-PG opt-in |
| `tests_isolated/test_web_project_html_bootstrap.py` | `test_real_chromium_bootstrap_order_and_nested_resources` → `frontend/tests/web-project-html-bootstrap.mjs` | Unconditional; source-extracted runtime, no application/PG import; needs BOOTSTRAP_NODE/EVIDENCE and legacy executable alias |
| `tests/test_notes_zip_browser.py` under `tests` | `frontend/tests/notes-zip-live.mjs` | Opt-in `STELLA_LIVE_BROWSER=1`; ordinary backend CI does not set it |
| `tests_isolated/test_full_web_project_e2e.py` | `frontend/tests/full-web-project-e2e.mjs` | Inherited `notes` fixture gates on `NOTES_BOUNDARY_PG_MANIFEST` |
| `tests_isolated/test_web_project_renewal_browser.py` | `frontend/tests/web-project-renewal-e2e.mjs` | Same owned-PG fixture; requires separately built dist/evidence |
| `tests_isolated/test_web_projects_pg.py` | `frontend/tests/web-project-browser.mjs` | Same owned-PG fixture |
| `tests_isolated/test_notes_timeline_contract_pg.py` | `frontend/tests/notes-timeline-contract-pg.mjs` | Same owned-PG fixture; new inventory entry changes later offsets but is not itself unconditional |

At the cb220b1 parent both unconditional files happen to belong to shard 2.
That observation is not an assignment contract. Adding files can move them to
other shards; tests exercise the current six-way plans and shifts, rejecting fixed `2`, fixed `2/4`,
install-everywhere and never-install mutations.

## Fail-closed and unchanged runtime boundary

Only explicit `required` / `not-required` responses are accepted. Missing planner,
invalid index/total, missing/empty plan or missing browser metadata files stop
before test execution. Unknown/empty stdout and planner errors are not treated
as an inert shard. Package/browser installer failures retain CI fail-fast behavior.

Required shards keep the original frontend lock `npm ci --ignore-scripts
--include=dev`, lock-matched Chromium headless shell + OS deps, locale, job-private
browser/evidence paths and disposable-container legacy alias. Inert shards do
not call any installer. No shared Runner, network, privilege, image, budget,
secret guard, production helper or prewarm change is needed.

Renderer receipts bind both the planner (including file metadata) and the setup
shell; `verify_bundle.py` requires their complete exact hash map. The existing
mandatory local-ha discovery re-exports both original and new browser contracts,
without adding a backend command. Shell units substitute all installers and
remap only the legacy alias destination to scratch; they are not evidence of a
real browser download, digest-pinned image run or successful GitLab pipeline.
