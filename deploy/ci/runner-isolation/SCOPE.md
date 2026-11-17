# Runner isolation implementation and activation contracts

The validation branch activates the candidate in `.gitlab-ci.yml`. Live project
configuration is separately operator-owned; this directory contains no tokens.
Production is manual + protected master + explicit READY, and the deploy runner
must remain paused until a separate release approval.

- `render_candidate.py --out <owned-directory>` compiles the current CI into a
  complete tagged candidate, three placeholder-only Runner TOMLs, manager Compose,
  explicit GitLab API payloads and a reviewable CI patch.
- `verify_bundle.py <directory> [--smoke-metadata <file>]` checks exact proposal
  boundaries and real BuildKit exporter metadata; no live config/token is read.
- `validate_activation.py --out <evidence-directory> --base <pre-activation-SHA>`
  uses a disposable archive of the explicitly selected current base and exercises the candidate plus the exact
  replacement of obsolete automatic/legacy deployment test expectations. Its
  `activation-contract-tests.patch` accompanies `candidate-ci.patch` on activation.
- `test_candidate.py` tests boundaries and rejects serialized privilege/socket,
  root-user, host-network, old-runner eligibility and automatic-release mutations.
- `build-rootless.sh` and `image_receipt.py` are the validation branch build path.
- `prewarm-before-build.sh` runs as an independent fail-closed shell after the
  original 8GiB admission/auth/worker flags, before any app solve. It warms only
  that job's rootless content store with a COPY-only canonical PG18 platform
  manifest (`885953...dc5b`); the Dockerfile's public index (`74935e...4336`),
  sandbox, job budgets, push policy and full-SHA tags stay unchanged. Private
  auth/context/output directories are outside the checkout and removed on exit.
  Both scripts are bound in renderer receipts. `test_prewarm.py` runs from the
  existing candidate and mandatory local-ha gates, including offline command
  substitutes; these are not evidence of a completed app image or live pipeline.
- `egress.nft` is a proposal scoped to NEW bridges, not an installation command.

Adoption requires explicit approval, a final-base rebase/rerender, candidate tests,
metadata-only GitLab readback, owned network/Runner acceptance, canonical HTTPS
clone/pull/push checks and an exact source/registry digest readback. No automatic
release path remains in the candidate: deployment is protected-master + explicit
local-ha + operator READY flag + blocking manual confirmation. READY is unset by
default; obsolete k3s/preview/live-readonly CI jobs are disabled, not migrated to a
socket-bearing exception. The production controller and node helper stay exact.

The three trusted Docker-executor managers retain a control-plane Docker socket;
no job receives it. BuildKit is a per-job rootless daemon, not the production
Docker build service. This is a shared-kernel boundary, not a VM or a guarantee
against a compromised manager/kernel/other host-root workload. Protected master
and approval owners remain trusted. Production secret scopes remain protected and
production-only. Public HTTPS egress is not a domain allowlist.
