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

## Review-fix regressions

- Same-origin authenticated media in note previews, rich image node views, attachment panels and the lightbox uses epoch-bound `fetch` → Blob → object URL, rather than native authenticated `src` loads. HTML is guarded in an inert template before insertion; private srcset and SVG image URLs cannot bypass admission. Markdown/ProseMirror source URLs are never replaced with blobs.
- Expiry aborts pending producers and clears undecoded blob sources. Already-loaded media and editor instances survive same-owner resume. Replacement, removal, identity/generation change and controller teardown revoke owned URLs. HTML/Markdown ZIP exports retain original/relative source URLs; public assets still use native loaders.
- Exactly `GET /homebg/media` is public, matching the backend router. The real background consumer is tested for compressed1 and poster; library lists, optimization and other writes are still protected.
- Auth producers capture both lifecycle generation and request epoch, including the post-JSON commit. A same-owner resume may retain the editor generation but never revive old profile results.
- Logout is single-flight. Pending logout keeps the protected page mounted but inert, displays a busy overlay, and prevents login/registration/code-login requests until the cookie-clearing response completes. Successful logout alone clears owner state. HTTP/transport failures restore an interactive retry button with an explicit failure alert. The browser regression uses real HTTP Set-Cookie handling with fixture-only cookies to prove logout/new-login ordering.
- Third-party cached iframes are still **destroyed on suspension**. This is a security boundary, not a promise to preserve third-party drafts.

The extra video is a tiny ffmpeg-generated neutral fixture, not user media. All new regressions are part of `test:login-modal`; none are skipped and the original focus/narrow/management/draft cases run again.

## Independent suites

`test:full` is a separate wider regression gate; a passing login gate must not be reported as a passing full suite. On the `ff6fd06` baseline, `src/modules/servers/performance.test.ts` / `turning live off during a slow window load never restarts polling` fails with two signals instead of one. Keep that unrelated failure visible, and verify against the exact baseline rather than weakening its assertion or calling the full suite green.
