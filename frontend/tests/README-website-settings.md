# Website settings isolated browser tests

Run from `frontend/`:

```sh
env -u NODE_ENV node node_modules/@playwright/test/cli.js test --config tests/website-settings.playwright.config.ts
env -u NODE_ENV node node_modules/vitest/vitest.mjs run --config vitest.settings.config.mjs
env -u NODE_ENV npm test
env -u NODE_ENV npm run build
```

The dedicated Vite config has **no backend proxy** and binds only loopback. Browser routes permit Vite source/dependency files from that exact origin and explicitly implement fixture APIs. Every other request is aborted and the tests assert the unmatched list is empty. No production data, real password, login or upstream is used. `auth.me` is a test-only current-user context, not actual login acceptance.

Tests mount the real Vue SettingsPage/NavigationSettings/WebsiteSettings/Icon and ExternalModulePage. An actual isolated iframe document proves load is not readiness. The backend fixture implements the published IMPLEMENTATION-CONTRACT; this is frontend behavior evidence, **not real PostgreSQL, DNS/CSP transport or production acceptance**. Parent integration must exercise the real backend separately.

Artifacts live only in `$TMPDIR`: `stella-website-report.json`, `stella-website-1440.png`, `stella-website-390.png`, and `stella-website-e2e/`. The JSON report includes measured DOM widths, selected-row ID and close-button counts as attachments.

Each implemented behavior slice was first executed against missing behavior (RED), then implemented and rerun (GREEN). Existing-lifecycle coverage was added as regression tests without claiming an artificial RED. Core slices: unified inline list, current-draft check and 422 help, real icons and authoritative sidebar, new disabled CSS/JS drafts, exact readback, idempotent uncertain create, builtin editor, unique builtin connection source, truthful frame load/blocked feedback, explicit activation, mobile close/layout, delete/rollback, builtin dirty guard, cross-origin script disarm, draft readback mismatch, non-shadow navigation persistence and optional name.

Integration requirements: register `/website-settings` before SPA, include it in API prefixes and add the ordinary development Vite proxy entry when serving this API via Vite. The frontend uses the existing shared `api()` client for once-per-operation management elevation. CSS/JS default disabled; explicit `custom.enabled=true` is a separately user-selected execution action. The backend save transaction validates syntax, detects again, stores draft and explicitly activates only enabled code. Existing rollback remains its authenticated legacy endpoint; every mutation is followed by exact readback.
