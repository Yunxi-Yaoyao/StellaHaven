# Hardware fixtures

`node-55.captured.json` and `node-57.captured.json` are unchanged production detail responses captured during the read-only investigation (2026-10-10).

`*.contract-fixture.json` are **test fixtures, not new real API captures**. Their base is the corresponding captured response. Storage and GPU inventory extend the proposed contract using public topology/volume observations in `docs/stella-hardware-refine-20261010/investigation/collector-reconciliation.json`. Physical used/percent are null; no sharing, averaging or false zero is invented. NAS retains its captured unknown machine classification. AMD GPU id is explicitly a fixture identity, not a discovered hardware id. Sample times remain the captured times; browser freezes its clock, never rewrites a sample as recent.

`hardware.testFixtures.ts` is a synthetic edge-case fixture for zero/null/multiple GPU and legacy compatibility; it is not a real capture.
