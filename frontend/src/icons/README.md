# Navigation icon subset

- **122 selectable drawings**, **9 semantic groups**, **2 compatibility aliases** (`file-text → note`, `hard-drive → drive`). Aliases are accepted keys, not duplicate picker entries.
- Source: official `lucide-static@1.57.0` npm archive, https://registry.npmjs.org/lucide-static/-/lucide-static-1.57.0.tgz
- npm integrity: `sha512-nuf4YoaKt3Pq9scXVQ71SLr0Q1/UZiTcfBBivFsCVL6biAzPplTikVWXLetBmK3oFEJS6f2L1rzgEsoJN/Ce0Q==`
- Downloaded archive SHA-512: `9ee7f862868ab773eaf6c717550ef548baf4435fd46624dc7c1062bc5b0254be9b880ccfa654e29155972deb4198ade8144252e9fd8bd6bce012ca0937f09ed1`.
- License: ISC for Lucide, MIT for the Feather-derived icons listed by upstream. The **complete upstream license and attribution** is copied to `frontend/public/licenses/lucide-1.57.0.txt` and ships in the built site at `/licenses/lucide-1.57.0.txt`.
- The 30 pre-existing `Icon.vue` path definitions remain untouched and take rendering precedence, including shell-only utility icons. The new catalog supplies missing/new drawings in the same 24px, 1.8-stroke, rounded line style. Baseline paths are regression-tested against the e432700 fixture.

`navigation-icons.json` is generated static data, not a runtime library or SVG markup. No CDN, external fetch, `v-html`, arbitrary SVG or dynamic icon package import is used. Only finite shape tags and numeric/path attributes are accepted by the generator and tests. Rendered shapes are checked for duplicates; aliases are excluded from the selectable count.

## Regenerate

Download and verify the pinned npm tarball against the integrity above; extract into a scratch directory. Run from repository root:

```
python scripts/generate_navigation_icons.py /scratch/lucide-static/package
```

This emits the JSON catalog, the backend `app/navigation_icons.py` allowlist and the public license. Curated labels/categories/synonyms live in the generator; edit there, regenerate, then run parity and rendering tests. There is no runtime dependency addition and no lockfile change. The frontend and both backend services derive their legal keys from these parity-tested outputs.

## Compatibility

Existing legal keys remain accepted unchanged. All old `cloud/code/monitor/...` choices now have real drawings; `file-text` and `hard-drive` remain aliases. Opening/filtering/cancelling a picker emits no value update. Unknown stored keys are retained in the model, named explicitly in the trigger, and get a visual fallback only. The existing backend rejects unknown keys on save with 422 rather than silently rewriting them; this lane does not relax that validation or change website business logic.

## Verification

From `frontend/` (clear inherited NODE_ENV; use local writable cache directories):

```
./node_modules/.bin/vitest run --config vitest.settings.config.mjs
./node_modules/.bin/vitest run --config vitest.full.config.mjs
npm run build
TMPDIR=/root/.hermes/cache/scratch/stella-icons-qa node e2e/icons/run.mjs
```

The browser runner builds the **real picker/icon components** into an isolated static fixture, disables proxy/config inheritance, refuses other origins, exercises desktop/mobile/small/landscape/half-width reflow, and writes `icons-*.png` plus a hash-bound report. Half-width reflow is explicitly **not native browser zoom or physical-phone acceptance**. Synthetic parent fields demonstrate that changing the icon does not edit the name/address; this is not full SettingsPage/App integration.

Backend: use a scratch cwd/HOME/TMPDIR, PYTHONPATH pointing at this checkout, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, and a test interpreter containing pytest and project dependencies:

```
python -m pytest --noconftest -p tests_website_settings.review_isolation /absolute/checkout/tests_navigation_icons -q
```

The isolation plugin substitutes synthetic auth/SQLite and forbids production connections. Tests exercise all 124 legal keys through real Pydantic schemas and create/read/update/read HTTP routes; unrelated name-only edits keep every icon. This is not PostgreSQL lock/concurrency testing. Broader Vitest coverage does not include the separate native Node test suite.
