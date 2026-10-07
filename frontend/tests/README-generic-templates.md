# Generic website template frontend acceptance

Only `frontend/**` changes, based on `913efda53cbd696c70ee536349b93ae55543339a`.

## Behavior
- `WebsiteSettings.vue` is the sole active website editor. Blank/OpenList/Immich are template choices loaded from `/website-templates`, not separate adapters or singleton service forms.
- Selecting a template copies the API draft and opens editable CSS/JS. Existing sites initially show complete active code; retained saved drafts are explicit alternatives. Switching preserves unsaved buffers. Metadata-only saves omit unchanged custom code, preserving distinct drafts.
- Common connection controls use `auto/proxy/direct`, `original/header/oidc`, `proxy/loader`; masked token input sends null when unchanged. Old records without connection metadata omit the field, preserving quota proxy targets.
- Save/check/readback/delete continue through `/website-settings`, `/external-modules`, and `/navigation`. Active and draft code, connection, background, policy, and navigation values are reconciled before success. Uncertain updates freeze and re-read, without replaying PATCH. Unknown create outcomes retain the existing idempotency-key recovery.
- Native navigation contains home/notes/status/settings only. `/drive`, `/gallery`, and settings `module` aliases resolve `navigation.legacy_routes`; no active DrivePage/GalleryPage/ServiceSettings imports, dedicated endpoints, or build chunks. Dormant legacy source files remain unregistered.
- `ExternalModulePage` supports solid/home backgrounds, including video. It never mutates upstream DOM; optional visible template code handles transparency through an origin-targeted message. Session cleanup, POST bootstrap, ordinary browsing, and cached iframe identity are preserved.

## Isolation and commands
Use per-package node_modules overlay (not whole-directory symlink); exclude `.vite`, `.cache`, `.tmp`, `.vite-temp`. The owned fixture allows explicit localhost Vite assets, exact endpoint/method mocks and the exact HMR socket; unknown HTTP/WebSocket requests abort and are asserted empty. It never calls production APIs, LAN services, user CDP, or SSH. Template bytes in the fixture are deliberately illustrative owned values, not fabricated production exports.

Run from `frontend/`:
```sh
NODE_ENV=development node node_modules/@playwright/test/cli.js test --config tests/website-settings.playwright.config.ts
STELLA_SESSION_ARTIFACTS=/opt/hermes-workstation/docs/2026-10-07-Stella-generic-templates/frontend/session NODE_ENV=development node node_modules/@playwright/test/cli.js test --config playwright.external-session.config.ts
node node_modules/vitest/vitest.mjs run --config vitest.settings.config.mjs
node node_modules/vitest/vitest.mjs run --config vitest.shell.config.mjs
node node_modules/vitest/vitest.mjs run --config vitest.low-config.config.mjs
npm run build
```

## Verified results
- `generic-templates.spec.ts`: 19 passed.
- `website-settings.spec.ts`: 32 passed.
- `external-session.spec.ts`: 20 passed.
- `vitest-settings.log`: 32 passed.
- `vitest-shell.log`: 8 passed.
- `vitest-low-config.log`: 10 passed.
- Browser total 71; targeted Vitest total 50; no failures. These are targeted suites, not a claim of a full repository test run.
- Vue typecheck and production build pass; build reports notes dynamic-import and large-chunk warnings.
- RED evidence includes template selection/active editing, legacy aliases, draft retention, background, and mismatched active readback before fixes. An enabled retry button is asserted after reconciliation finishes, not the temporary visible pending state.
- Desktop/mobile screenshot DOM assertions: one website form, no native select, 220px name field, no horizontal overflow. Screenshots inspected directly.

Evidence root: `/opt/hermes-workstation/docs/2026-10-07-Stella-generic-templates/frontend/`.
Screenshots: `stella-generic-template-1440.png`, `stella-generic-template-390.png` (non-empty owned CSS/JS); `stella-website-1440.png`, `stella-website-390.png` (existing layout regressions).

## Not claimed
Real backend template bytes, generic loader installation, actual upstream injection effects, migrated production accounts/photos/files/OIDC and deployed proxies require parent-lane integration/release acceptance. This lane neither migrated nor altered any service, database, credentials or ingress.
