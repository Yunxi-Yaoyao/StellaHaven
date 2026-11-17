# Outline layout acceptance (isolated only)

Run from `frontend`, using this worktree's private dependency copy:

```sh
env -u NODE_ENV STELLA_LAYOUT_OUTPUT=/path/to/evidence/components node --experimental-strip-types e2e/outline-layout/run.mjs
env -u NODE_ENV npm run build
env -u NODE_ENV STELLA_LAYOUT_OUTPUT=/path/to/evidence/app node node_modules/@playwright/test/cli.js test --config e2e/outline-layout/app.config.ts
env -u NODE_ENV STELLA_CALLBACK_OUTPUT=/path/to/evidence/callback node e2e/callback-form/run.mjs
env -u NODE_ENV node node_modules/vitest/vitest.mjs run --config vitest.settings.config.mjs
```

- `run.mjs` renders actual SettingsNavigation/ProfileSettings/ServiceSettings/SecuritySettings/ServersSideBar components and shared CSS. Account/security state and service responses are synthetic. Profile save is held explicitly to verify actual loading geometry, then rejected to check preserved draft and multiline errors. Unknown HTTP requests fail closed. Vite dependency entries and cache are isolated; no development proxy is loaded.
- App tests serve this worktree's built `dist` through the existing static-only loopback server (15207). Auth, preferences, SMTP and empty server/task data are exact synthetic HTTP responses. All unknown HTTP/WS operations are blocked. No database, real identity, email, server installation or real credential mutation is used.
- Viewports: 1365, 1920, 390, 320. Actual browser 200% zoom uses a temporary extension and private Chromium profile; `chrome.tabs.getZoom`, innerWidth, devicePixelRatio and menu geometry are asserted. It is not CSS zoom or a scaled screenshot. The native zoom case needs Playwright's installed Chromium; ordinary cases use discovered `/usr/sbin/google-chrome-stable` (override with `CHROMIUM_PATH`).
- The built-App screenshots wait for the Vue email disclosure's enter classes to settle. SMTP has top and bottom screenshots because its App main container scrolls internally. Keyboard focus return, long Chinese actions, square icon faces, neutral submit behavior, palette consumption, fold persistence/readback and mobile tool routes are asserted.

## Shared product CSS contract

- `src/shell/secondary-navigation.css`: `.st-secondary-nav`, `.st-secondary-heading`, `.st-secondary-label`, `.st-secondary-group`, `.st-secondary-item`, `.st-secondary-subnav`, `.is-sub`, `.st-secondary-mobile`.
- `src/shell/controls.css`: `.st-button`, explicit `.is-primary` / `.is-ghost` / `.is-danger` / `.is-icon`; default is neutral. `type="submit"` does not choose visual priority. Ordinary desktop buttons have a natural width and 32px starting height; mobile target is 44px with an inset compact face.
- Stable busy rendering: preserve an original `.st-button-label` in flow and set `aria-busy="true"`; disabled and accessible busy label remain the component's responsibility. A shared spinner replaces only the visible face of the label without changing geometry.
- Control surface tokens use `--control-bg` / `--control-border` / `--control-hover` with existing Stella token fallbacks. No A/B defaults are changed. No backend preference or appearance-store contract is changed by this lane.

Evidence for this execution lives outside the repository at `/opt/hermes-workstation/docs/Stella-Outline优化-20261020/layout/`. The broad settings suite has three exact baseline failures (two old BackupCenter text expectations and the old appearance-copy button count) and one opt-in PG skip; see `baseline-comparison.json`. The independent callback/browser suites remain unchanged.
