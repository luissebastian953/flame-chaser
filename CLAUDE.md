# Curio — project instructions

**Curio** is a personal archive for illustrations of specific characters. It
crawls pixiv and X (with more sources planned), dedupes across them, and stores
the result in a folder on the user's own machine.

```
flame-chaser/                 one git repo, one pnpm workspace
├── reaver/                   Python project. Packages: `coreflame` (engine) + `dawnmaker` (daemon).
│   ├── check.sh              definition of done (ruff, mypy, tests, verify=False grep)
│   └── tests/                plain python3 test files, all offline
├── deliverer/                Tauri v2 shell + Vue 3 webview. The app the user opens.
├── docs/design/architecture.md   the reference; API contract in §6
├── scripts/                  bump-version.sh · check-version.sh · install-linux.sh
├── docker/ + docker-compose.yml   browser-mode dev stack (no Tauri window)
├── .github/workflows/release.yml  tag → installers → draft release + latest.json
├── .claude/skills/           procedures for future sessions (index below)
├── .husky/ · .lintstagedrc.json · commitlint.config.js   commit tooling
├── CHANGELOG.md              user-facing; Settings › Updates renders it
└── package.json              root scripts: check · commit · dev · tauri
```

`dawnmaker` imports `coreflame`; `coreflame` never imports `dawnmaker`; `deliverer` knows
neither beyond the HTTP contract. **Do not invert this.** It is what keeps the
CLI working as an escape hatch while the UI is mid-refactor.

Full architecture, API contract and failure-mode tables: `docs/design/architecture.md`.
Read it before changing anything structural — most "obvious improvements" below
were already considered and rejected for a stated reason.

---

## The decisions that are load-bearing

Undoing any of these silently breaks something. If you think one is wrong, say
so and stop — don't just change it.

1. **pixiv discovers, X follows.** A character is a first-class *tag* on pixiv
   (`s_mode=s_tag_full` matches exactly). X has no character metadata and no
   free search tier since Feb 2026. So pixiv finds artworks → artworks give
   artists → artist pixiv profiles give X handles → X supplies those artists'
   timelines. `TwitterAdapter.supports_discovery` is `False` and
   `discover()` raises on purpose.
2. **Check the visited set before spending a request.** The search listing hands
   over `illustId` for free; `seen_posts` is consulted there, not after the
   detail fetch. `posts` is NOT the gate — it only holds what we kept.
3. **`seen_posts` has four states and they are four retry policies:**
   `indexed` (never revisit) · `skipped` (only if the config that rejected it
   changes — store the `threshold`) · `gone` (404/410, never) · `failed`
   (after `retry_after`). Collapsing them means either re-fetching deleted
   artworks forever or permanently blacklisting a transient 500.
4. **Dedupe is two levels.** sha256 for exact; dHash (Hamming ≤ 6) **scoped to
   one artist** for the pixiv-PNG vs X-JPEG case. Scoping is what keeps it
   O(hundreds) instead of O(archive).
5. **Watermarks are monotonic ids, not timestamps** — and the poller walks one
   full page *past* the floor before stopping.
6. **`Referer` is mandatory on i.pximg.net.** Every image 403s without it.
7. **Never `verify=False`.** An Indonesian ISP has been observed attempting TLS
   interception with a spoofed cert. A validation failure is evidence of an
   active MITM; disabling verification hands over `PHPSESSID` and `auth_token`.
   This must not exist as an option, a debug flag, or a fallback.
8. **The webview never touches the filesystem.** Images reach the UI over
   `http://127.0.0.1:<port>/api/media/{sha}/thumb`, never `file://` or `asset:`.
9. **Thumbnails are generated at ingest.** A grid pointing at full-size PNGs
   moves gigabytes through the webview.
10. **The db lives in `~/.reaver/`, not the library folder.** SQLite on a synced
    or network folder is how databases get corrupted. Only blobs move.

---

## Conventions

- **Python ≥ 3.10** (`requires-python` in `reaver/pyproject.toml`): no
  `datetime.UTC`, no `StrEnum`. Engine deps: `httpx`, `Pillow`, `gallery-dl`,
  `pydantic`, `glom`. Daemon adds `fastapi`, `uvicorn`. Keep the engine
  importable without the daemon's deps.
- **IDs are `str`, always.** Snowflakes exceed JS safe-integer range.
- **Datetimes are tz-aware UTC** at the adapter edge. Never naive.
- **Tags keep two forms:** `tag_raw` (what pixiv matches on) and `tag_norm`
  (NFKC, for grouping and dedupe). `申鶴（原神）` and `申鶴(原神)` are the same
  character and different search terms.
- **Every write is an idempotent upsert on a natural key.** That is what makes
  the deliberate re-read window safe rather than a duplicate factory.
- Normalization happens **at the adapter edge**. Nothing downstream of
  `models.py` ever sees a source-shaped dict.
- Validation failures go to **quarantine with the raw payload hash**, never to a
  crash and never to a silent drop.

## Testing

`reaver/tests/test_*.py` (smoke, normalize, seen, tags, jobs, net, dawnmaker)
are plain `python3` files, run by `reaver/check.sh`; all offline — fixture
payloads and generated images, no network. Any adapter change needs a fixture.
`deliverer/src/**/*.test.ts` run under Vitest (happy-dom) and mock `@/lib/api`.
Never write a test that hits pixiv or X.

## Working on this repo

- **Definition of done is `pnpm check` at the root**: deliverer `check`
  (vue-tsc, eslint, prettier, i18n-check, vitest) → `reaver/check.sh` (ruff,
  mypy, tests, `verify=False` grep) → `scripts/check-version.sh`. Green
  before claiming anything is finished.
- Prefer minimal targeted changes. This codebase is small and deliberate.
- Read the `feature-workflow` skill before any feature request; the `commit`
  skill before committing; `add-source-adapter` before adding a source.
- Verify external facts (API tiers, rate limits, endpoint shapes) against
  primary sources before designing around them. They change.
- Run commands from the repo root unless a package's own CLAUDE.md says otherwise.

## Legal

pixiv's ajax endpoints are not a public API; automated access to X is against
its terms. This is a private archive of publicly posted work: attribution
permalinks stored on every post, no redistribution, no monetisation,
conservative request rates, deleted or privated works removed. Keep it that way.

## Commits — one repo, Conventional Commits

`flame-chaser/` is a single git repo covering `reaver/`, `deliverer/`, docker
and docs; there are no nested repos. JavaScript tooling is a **pnpm workspace**
(`pnpm-workspace.yaml`): one `pnpm install` at the root installs the commit
tooling here and the app in `deliverer/`; never `npm install` anywhere (no
`package-lock.json` should exist). Commit with `pnpm commit` at the root
(cz-git walks you through type → scope → subject) or write the message by
hand in the same shape — `commitlint` rejects anything else on `commit-msg`:

```
feat(deliverer): sign-in gate on first launch
fix(coreflame): probe skips fullwidth tags without a request
chore(release): v0.2.0
```

Scopes are fixed: `deliverer reaver coreflame dawnmaker design docker ci
release docs skills deps`. `pre-commit` runs lint-staged (prettier + eslint on
deliverer files, ruff on reaver files) on what is staged only. Hooks come from
husky: `pnpm install` at the root once, and `pnpm prepare` after `git init`
(remote: `https://github.com/luissebastian953/flame-chaser`, branch `master`; after a fresh clone: `pnpm install && pnpm prepare`).
Full procedure and what commitlint rejects: `.claude/skills/commit`.

## Releasing

`scripts/bump-version.sh X.Y.Z` → `pnpm check` →
`git commit -am "chore(release): vX.Y.Z"` → `git tag vX.Y.Z` → push tags.
`.github/workflows/release.yml` builds dmg (arm64 + x86_64), NSIS, AppImage +
deb, always building the Python sidecar first, and drafts a GitHub Release
with `latest.json` for the in-app updater. `CHANGELOG.md` is user-facing (the
app renders it). Full procedure and verification: `.claude/skills/cut-release`.

## Docker (browser-mode stack only)

`docker compose up -d --build` runs dawnmaker + Vite in one container at
http://localhost:5173, archive in `./data` (or `CURIO_DATA=/path`). Secrets go
in a root `.env` (`PIXIV_PHPSESSID=...`). `docker compose run --rm dev
coreflame <cmd>` for the CLI. The daemon binds `0.0.0.0` inside the container
-- allowed only with `--dev`, and compose publishes on `127.0.0.1` only. The
Tauri window cannot run in Docker; that is still `pnpm tauri dev` on the host.
Restart-vs-rebuild table and release pipeline summary: `.claude/skills/deploy`.

## Skills — `.claude/skills/<name>/SKILL.md`

Read `feature-workflow` before any feature request and `commit` before
committing. Each is written for a future session: commands, paths, order,
done-criteria, traps.

| Skill | Use it when |
|---|---|
| `feature-workflow` | adding or changing a feature — everything that must move together, in order |
| `commit` | committing: `pnpm check`, fixers, hooks, Conventional Commit types/scopes |
| `conventions-python` | working in `reaver/`: toolchain, offline tests, http, models, secrets, adding an endpoint |
| `conventions-typescript-vue` | working in `deliverer/src`: auto-imports, Tailwind tokens, i18n, tests, adding a page |
| `conventions-rust-tauri` | touching `deliverer/src-tauri`: commands, capabilities, sidecar, CSP, first compile |
| `i18n-locale` | adding/renaming a UI key, translating a component, adding a language |
| `add-source-adapter` | adding or evaluating a new illustration source |
| `diagnose-network` | requests to pixiv/X fail, hang or reset; DoH or proxy setup |
| `cut-release` | tagging a version, the release workflow, verifying an update shipped |
| `deploy` | release pipeline summary, secrets and placeholders, the Docker dev stack |
