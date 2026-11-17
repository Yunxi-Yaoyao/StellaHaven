# Unified root Agent acceptance

Linux `.19` keeps one Agent service. The main loop supervises a separate root
file worker (and a bounded preparation process); it does not run file operations
inline and does not create a companion service. Authenticated
`GET /agent/files/config` must explicitly grant the root before a worker starts.
Explicit legacy local roots remain supported. Windows/nonroot collection is
unchanged and does not acquire a root file worker.

The stdlib bootstrap downloads the complete manifest-pinned Agent/file-module
pair, checks exact size/hash/version/protocol, verifies safe ownership and every
package-store ancestor, runs the actual interpreter load probe, and atomically
publishes a generation. SHA256 integrity over authenticated HTTPS is not a
cryptographic signature. Tokens enter the subprocess via stdin, not argv/env.
The parent guard also covers the interpreter load probe.

## Execution

Local OS isolation (real root, readonly host, private network, synthetic `/root`):

```sh
TMPDIR=/root/.hermes/cache/scratch \
  /opt/hermes-workstation/stella-production-closure-20261017/.venv/bin/python \
  tests_agent_unified/run_owned.py <new-phase> \
  tests_agent_unified/test_unified_agent.py \
  tests_agent_unified/test_root_installer.py
```

`run_owned.py` is only the local acceptance entry, not the CI job launcher.
Mandatory CI may run the same tests inside its nonce-admitted nonprivileged
container with trusted job-private `/mnt` overlay and no Docker socket or
SYS_ADMIN. `conftest.py` verifies admission, and missing isolation fails instead
of skipping. `unified_root_fixture` marks root/installer cases explicitly.
Installer tests inherit all original cases, relocate filesystem destinations,
and use fixture service/account commands; no real PID1 or host installer runs.

## Verified in this lane

- 30 owning cases plus 3 unittest subtests passed under local OS isolation.
- The same 30 owning cases plus 3 subtests passed under the nonprivileged
  container/owning-runner admission. Only the evidence harness extended the old
  runner's directory admission in memory; production CI files were not edited.
- Parent SIGKILL: preparation, authenticated running worker, and in-progress
  interpreter-load probe; the disposable subreaper waits every descendant and
  requires an empty children list.
- Real UID0 managed worker: automatic config/manifest/bootstrap, root-private
  preview and create, ungranted-root denial, bounded cleanup. The HTTP center is
  a synthetic local protocol fixture, not a deployed center.
- Real fabricated chroot: UID0 private `/root` read/write, plus readonly grant,
  foreign-root, traversal and symlink negatives. No operation targets host `/`.
- Original 18 Files owning files / 156 cases all executed: 155 passed, one stale
  synchronous-hook assertion failed (`test_pipeline.py::test_agent_entry_optional_hook`).
  It still expects `Agent._file_tick()` to finish a job synchronously. This lane
  does not own that test and does not reintroduce inline execution to satisfy it.
- The actual `725d2e7` `.18` updater accepted and interpreter-loaded the complete
  `.19` candidate with both httpx and stdlib transports (2 evidence-only cases).
  The old version-pinned update/continuity/privilege suites were also run
  unchanged: 43 pass / 10 fail, with failures retained for the integration owner.

Evidence is in
`/opt/hermes-workstation/docs/records/2026-10-24-stella-agent-unified/agent/finalize/`:
`path-red.xml`, `probe-orphan-red.xml`, `final-full-green.xml`,
`final-new-ci/`, `final-source/`, `old-update-red.xml`, and
`final-real-0618-upgrade.xml`.

Not claimed: remote CI green, deployed root UID/service health, real systemd
PID1 lifecycle, Windows execution, or production migration. No push, SSH,
production changes, or Studio session operations were performed.
