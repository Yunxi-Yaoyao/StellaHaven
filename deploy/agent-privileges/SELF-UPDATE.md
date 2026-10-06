# Agent self-update safety contract

This change keeps `AGENT_VERSION = "0.6.10"` and does not publish, restart, or alter any node.

## Protocol and rollout

- Only canonical `major.minor.patch` numeric releases strictly newer than the running version are eligible. Same version, older version, whitespace, leading-zero components, prereleases and malformed values are ignored.
- `/agent/version` adds `sha256` (lowercase SHA-256) and `size` (bytes) only when the advertised version matches the actual served artifact. `/agent/script` serves the original bytes, including original line endings. Existing 0.6.9 clients still read the existing `version` field and script endpoint.
- `STELLA_AGENT_ROLLOUT_VERSION=0.6.9` remains the existing global hold. It advertises no misleading manifest for the newer script. No per-node canary mechanism is added.
- A patched client rejects a newer announcement without a valid manifest. Against an older backend it keeps running instead of accepting an unchecked update.
- Already-installed **unpatched** 0.6.10 clients cannot receive this same-version fix through the new version gate. Reinstall the patched artifact explicitly for such canaries, or separately approve a future version bump. Ordinary 0.6.9 clients get the patched 0.6.10 artifact when the existing global hold is released. Do not assume cherry-picking retrofits running clients.

## Download, replacement and recovery

Both HTTP transports require HTTP 200, reject redirects and compressed content encodings, send Bearer credentials only in Authorization, and stream raw bytes with a 2 MiB maximum and manifest-size budget. A 30s read timeout plus per-chunk elapsed checks bounds network work; a stalled read can consume its read timeout after the elapsed deadline. UTF-8 decoding, exact byte count/hash, Python parse/compile, and literal top-level target version are checked before any installed-file change.

A unique same-directory staging file is fsynced and retains the installed mode/owner/group. The same Python interpreter actually loads it without `__main__`, then an fsynced old-script recovery copy is made and replacement is atomic. The installed bytes are hashed and the installed path is actually loaded again. Loaded version and callable entrypoints are verified even under `PYTHONOPTIMIZE`; probe success uses a dedicated exit status so an early `sys.exit(0)` is not mistaken for load success.

The agent uses `execv` with the existing interpreter/arguments, preserving the supervised PID instead of invoking `systemctl restart` and killing itself before checks finish. Preflight, filesystem and exec failures return to the original live process. Failures after replacement attempt atomic restoration of the old bytes and permissions. If the filesystem also refuses restoration, the old-script recovery file is retained and its path is logged; do not claim the on-disk script was restored in that case.

A successful real exec leaves `.stella-rollback-*.py` beside the installed script for manual recovery; the path is logged before exec. An operator can restore that exact approved backup in a maintenance window. Recovery copies are not automatically garbage-collected. This is not a crash/power-loss transaction, executable-code sandbox, release signature, post-exec heartbeat guarantee, or automatic rollback from arbitrary runtime failure. SHA-256 binds the announcement to bytes, not to an independent trust root: the existing center and transport remain trusted (use HTTPS on untrusted networks).

## Isolated verification

`tests_isolated/test_agent_update.py` uses its own loopback server and scratch scripts. It covers both transports, downgrade/no-op/malformed gates, status/redirect rejection, size/hash/syntax/version errors, import failures/timeouts/early exits, actual full-agent module loading without running main, successful staged+installed loading, filesystem/exec rollback, retained recovery copies when rollback fails, and a real exec into a harmless relocated fixture which writes only a scratch marker.

Safe regression command (do not blindly run the legacy installer base class; the relocated subclass covers all its cases):

```sh
python3 -B -m unittest \
  tests_isolated.test_agent_update \
  tests_isolated.test_agent_scheduler \
  tests_isolated.test_agent_privileges.TransportTests \
  tests_isolated.test_agent_privileges.InstallerPrivilegeTests \
  tests_isolated.test_agent_privileges.AgentDockerTests \
  tests_isolated.test_agent_privileges.DockerHelperTests \
  tests_isolated.test_agent_privileges.RelocatedInstallerRegressionTests -v
```

No production self-update or production agent restart is part of these tests.
