#!/bin/sh
# Sourced by the Python job: never borrow frontend sibling artifacts/caches.
# Before uv sync only system Python + stdlib are available. A failed/missing
# plan is NOT an inert shard: never proceed to backend tests without setup.
if ! backend_browser_requirement="$(python3 deploy/ci/run-backend-shard.py --requires-browser)"; then
  printf '%s\n' 'Cannot determine backend browser prerequisites' >&2
  return 1
fi
case "$backend_browser_requirement" in
  required)
    export LANG=C.UTF-8 LC_ALL=C.UTF-8
    export PLAYWRIGHT_BROWSERS_PATH="$TMPDIR/playwright"
    export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
    export BOOTSTRAP_NODE="$(command -v node)"
    export BOOTSTRAP_EVIDENCE="$TMPDIR/web-project-html-bootstrap"
    mkdir -p "$BOOTSTRAP_EVIDENCE"
    unset NODE_ENV
    python3 deploy/ci/runner-isolation/backend_dependencies.py npm
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --prefix frontend --ignore-scripts --include=dev --prefer-offline
    python3 deploy/ci/runner-isolation/backend_dependencies.py playwright
    node frontend/node_modules/playwright/cli.js install --only-shell chromium
    # The unchanged standalone bootstrap fixture requests a legacy absolute
    # Chrome name. Alias only inside this disposable job container to the SAME
    # lock-pinned headless shell; never install another browser or touch host.
    headless_shell="$(node -e 'const {registry}=require("./frontend/node_modules/playwright-core/lib/server/registry/index.js"); process.stdout.write(registry.findExecutable("chromium-headless-shell").executablePath());')"
    test -x "$headless_shell"
    export STELLA_CHROMIUM="$headless_shell"
    export STELLA_CI_NODE="$BOOTSTRAP_NODE"
    test ! -e /usr/sbin/google-chrome-stable
    ln -s "$headless_shell" /usr/sbin/google-chrome-stable
    ;;
  not-required) ;;
  *) printf '%s\n' 'Unknown backend browser requirement' >&2; return 1 ;;
esac
unset backend_browser_requirement
