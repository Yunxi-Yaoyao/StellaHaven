# Home right-hand settings regression

Run from `frontend/`:

```sh
env -u NODE_ENV HOME_SETTINGS_EVIDENCE="$TMPDIR/home-right-settings" node tests/home-right-settings/run.mjs
```

Uses the real App, router, HomePage, SettingsPanel, background manager and cached NotesPage. Reuses the existing independent experience harness, with an isolated loopback port (`HOME_SETTINGS_PORT`, default 15561), `configFile:false`, no Vite proxy, fresh Chromium contexts, explicitly declared API/WebSocket fixtures and neutral offline media. No live account, production browser, database or upstream is used. `CHROME_PATH` can select the installed Chromium executable.

Four viewports: 1440×1000, 393×852, 320×568 and 852×393. Each exercises the right-hand entry, unchanged URL, labels, thumbnail/name, Escape/Tab focus, storage write failure with retained field values, quality persistence failure, account-background reset failure/retry/readback, background-manager focus and Escape, theme replacement, no duplicate settings-page form, cached NotesPage, elevation during crop preview, expired login, logout and a delayed reset response after logout.

The JSON report records exact commit, dirty status, before/after SHA-256 for product source and the reused fixture, all browser errors and rejected requests. The one deliberate HTTP 503 console message per viewport remains in the report; all other console errors and unknown requests fail. Screenshots show entry, drawer and scrolled background controls. These are isolated actual-component captures, not production or physical-device acceptance.

The legacy `src/modules/home/backgroundMedia.test.ts` now mounts the real HomePage trigger with a memory router and opens its Teleport drawer. Only visual theme components are stubbed in that jsdom fixture; the browser suites use the real themes. All original account-name, static-thumbnail, no-video, failed-reset and confirmed-reset assertions remain unchanged. An additional test follows the embedded compatibility link and verifies a single shared home drawer.

## Independent production-build review

Run from this worktree's `frontend/` (install its own `npm ci --include=dev` first):

```sh
env -u NODE_ENV npm run build -- --outDir "$TMPDIR/review-home-dist" --emptyOutDir
env -u NODE_ENV HOME_REVIEW_DIST="$TMPDIR/review-home-dist" HOME_SETTINGS_EVIDENCE="$TMPDIR/review-home-build" node tests/home-right-settings/review-build.mjs
```

`review-build.mjs` serves that exact build via a loopback-only static server on 15573, without Vite or a proxy. It does not inject or rebuild App components, and rejects source-module loads. Router transitions use the mounted app's real `$router`. API fixtures are offline and origin-bound; unknown HTTP/WebSocket requests fail closed. This Linux Chromium environment has WenQuanYi Micro Hei installed; the typography assertion explicitly checks its actual use via CDP, not merely a CSS font-family declaration.

Four viewports additionally exercise actual inert shell exclusion with an interactive body Teleport, field write/readback failure and retained focus, background PATCH-success/GET-failure and wrong-owner readback, nested Escape, pointer close, SettingsPage link, route cleanup during crop, Notes KeepAlive, and genuine watchdog 401+refresh rejection while crop is open. The source suite also verifies elevation and logout during crop, plus late reset after logout. Screenshot files cover the drawer, visible empty-input placeholders and the scrolled mobile close control.

Contrast receipts include computed colors, alpha-composited nested backgrounds, placeholder opacity and every ancestor opacity. Expanded dropdowns are sampled only after their real CSS opacity reaches 1; advancing the Playwright JS clock is not a substitute for CSS animation completion. Normal/weak/placeholder text must reach 4.5:1. Build hashes and source hashes are captured before/after, with commit/dirty status. Deliberate 503/401 console messages remain visible; unexpected console errors, page errors, failed requests and unmatched endpoints fail. Reports and screenshots are fixture evidence, not production data or physical-device acceptance.

## Home palettes and guide captures

```sh
env -u NODE_ENV HOME_SETTINGS_EVIDENCE="$TMPDIR/home-theme-delivery" node tests/home-right-settings/theme-delivery.mjs
```

This additional actual-App suite uses a separate loopback-only Vite server on 15579 with no project config/proxy. All unmatched HTTP/WebSocket requests are denied; the two geolocation URLs are explicitly answered with RFC 5737 example data, never sent upstream. It checks dark HTML before the entry module is released, global token contrast, nightfall jade vs classic violet, matching teleported drawers, stored theme surviving reload, no account-background write, retained four-theme/title/signature/date/particle controls, and the real NotesPage/DocEditor table/code plus system SettingsPage. Home selection must leave the root palette unchanged: home appearance and the fixed global dark shell remain independent. Screenshots are synthetic-account/neutral-media UI captures, not production or physical phone verification. Live2D model rendering is not exercised (the model asset is not bundled in this checkout); gallery screenshots prove entry/preview only, not upload/rename/delete network recovery.
