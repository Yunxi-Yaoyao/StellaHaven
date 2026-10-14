# Login modal regression gate

Run from `frontend/`:

```sh
env -u NODE_ENV npm run test:login-modal
```

This builds the actual product App (including its router, sidebar, stores, NotesPage and global CSS), runs the focused unit regressions, and serves only that build on `127.0.0.1:15274`. The static server has **no proxy or backend connection**. Browser API responses, initialization, login credentials, notes, expiry and WebSockets are explicit synthetic fixtures; these are not production authentication or production-data results. Foreign HTTP origins are blocked. No personal data is written. Playwright uses its disposable browser context, not Studio or an existing user browser.

Artifacts default to `$TMPDIR/stella-login-modal-evidence`; set `STELLA_LOGIN_QA_OUTPUT` to an absolute scratch path to retain JSON results, traces and screenshots. The test uses `/usr/sbin/google-chrome-stable`; change the launch executable in the isolated config if that binary is unavailable.

## Lifecycle contract

- Public login opens above the current route. A protected guest route keeps its URL but its wrapper cannot import or mount its private business component.
- `/login?next=` resolves a safe same-site destination and requests the same modal. Existing authenticated sessions do not see a second login form.
- A confirmed refresh rejection suspends the current owner rather than discarding the editor. `loggedIn` is false while suspended; the blurred shell is inert and hidden from accessibility navigation.
- Private fetch results and socket messages are fenced; polling cannot fetch new private content while suspended. `requestEpoch` invalidates delayed responses independently of `sessionGeneration`, which controls the mounted editor lifetime.
- Explicit reauthentication of the same suspended owner preserves the editor instance. Other identities, explicit logout and leaving the expired modal for the public home clear private state. Management-password elevation remains separate and a rejected management password is not an ordinary-login refresh.
- Public close restores the opener, or the visible hamburger if the mobile drawer has closed. Protected close returns to the public home without rendering private content.

The browser cases cover desktop and narrow viewports, Tab/Escape, focus return, error retry, initialization, direct NotesPage login, unsaved editor expiry/resume, protected cancellation, legacy links, logout and the existing administrator-elevation dialog.

## Independent suites

`test:full` is a separate wider regression gate; a passing login gate must not be reported as a passing full suite. On the `ff6fd06` baseline, `src/modules/servers/performance.test.ts` / `turning live off during a slow window load never restarts polling` fails with two signals instead of one. Keep that unrelated failure visible, and verify against the exact baseline rather than weakening its assertion or calling the full suite green.
