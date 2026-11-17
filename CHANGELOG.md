# Changelog

## Unreleased — candidate

These changes are present in the integration candidate. They are not a statement that production has been upgraded.

### Fixed

- Accept and preserve speedtest-go `test_duration` objects (`ping`, `download`, `upload`, `total`, nanoseconds or null); keep invalid values rejected in both Agent and result ingestion.
- Show a persistent server-list completion message and valid server count; clear stale completion on retry or client changes.
- Correct iperf multi-stream accounting, receiver loss semantics, process cleanup and terminal-result validation.
- Install and bind a centre-specific host Agent during eligible first initialization; preserve independent centres and reject stale installation attempts.
- Respect strict installer umasks without exposing private Agent credentials.
- Use the applied installation address consistently; do not generate commands without an eligible address or enter offline/pending node detail pages.
- Repair Markdown file append readiness and simplify import target selection, safe reading preview, format switching and opening imported results.
- Preserve representable ordered/nested HTML lists and code whitespace; report unsupported numbering and merged-table conversion risks.
- Render task checkboxes as disabled, read-only controls in import previews instead of missing-image placeholders.

### Validation and limits

- Candidate verification includes real host installation, empty-database API initialization, MD/HTML/ZIP import and readback, bounded iperf tests, server selection/cancellation and a complete speedtest result.
- This is not exhaustive WAN, platform, PostgreSQL concurrency or hardware-failure certification. Windows component and server-list support differs from Linux.
- Complex HTML conversion is not lossless. Original files remain available; warnings describe unsupported structure and behaviour.
- Existing strict documentation incompletes remain visible; targeted passing suites are not advertised as an all-repository green result.
- Agent source changes at an unchanged version require explicit repair installation; automatic fleet rollout is a separate release action.

See [release policy](docs/RELEASING.md) before tagging or deploying.
