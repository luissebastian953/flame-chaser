# Building and running Curio

Developer guide: how to get the desktop app, the browser-mode stack and the
installers running from a checkout. Every command here is taken from the repo's
own scripts (`package.json`, `deliverer/package.json`, `reaver/check.sh`,
`docker-compose.yml`, `.github/workflows/release.yml`).

## Prerequisites

| | What | Why |
|---|---|---|
| All | **Node ≥ 22.12** and **pnpm 10** via corepack (`corepack enable`; the version is pinned in `package.json#packageManager`) | pnpm workspace: root tooling + `deliverer/` |
| All | **Python ≥ 3.10** (`pyproject.toml`; CI uses 3.12) with a venv in `reaver/` | `coreflame` + `dawnmaker` |
| All | **Rust stable** (`rustup`) | the Tauri shell; needed for `pnpm tauri dev` and `build`, not for browser mode |
| macOS | Xcode Command Line Tools (`xcode-select --install`) | linker, codesign |
| Windows | Visual Studio Build Tools with the C++ workload, WebView2 runtime (present on Windows 10/11) | MSVC target |
| Linux | `libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf` (Debian/Ubuntu names, as in `release.yml`) | webkit2gtk-based webview, AppImage packaging |
| Optional | Docker with Compose | the browser-mode stack without installing Python/Node locally |

`gallery-dl` is a Python dependency of `reaver` and is installed with it; the
X adapter shells out to the `gallery-dl` binary on `PATH`, so keep the venv
active when running the daemon by hand.

## One-time setup

```sh
git clone https://github.com/luissebastian953/flame-chaser && cd flame-chaser
pnpm install                                   # root: workspace install + husky hooks
python -m venv reaver/.venv
. reaver/.venv/bin/activate                    # Windows: reaver\.venv\Scripts\activate
pip install -e "reaver[daemon,dev]"            # engine + FastAPI/uvicorn + ruff/mypy
```

`pnpm install` at the root is the only JavaScript install; never run `npm
install` anywhere (a `package-lock.json` is a bug). The `prepare` script wires
husky; if you cloned without `.git` (or ran `git init` afterwards), run
`pnpm prepare` once so the `pre-commit` (lint-staged) and `commit-msg`
(commitlint) hooks exist.

`pip install -e` is editable: a Python edit is live in the next daemon start.
The `[daemon]` extra adds FastAPI and uvicorn, `[dev]` adds ruff and mypy;
`pyinstaller` is only needed to build installers.

## Running the desktop app

```sh
. reaver/.venv/bin/activate
cd deliverer
pnpm tauri dev
```

`tauri.conf.json` runs `pnpm run dev` (Vite on `127.0.0.1:5173`, strict port)
as `beforeDevCommand`, compiles the Rust shell, and opens the window. In a debug
build the shell does not look for a PyInstaller bundle: `sidecar.rs` spawns
`python -m dawnmaker` from whatever `python` is first on `PATH` - hence the
active venv - and reads the same `DAWNMAKER_READY` handshake line a packaged
build would. Override the command with `REAVER_DEV_CMD`, e.g.

```sh
REAVER_DEV_CMD="python -m dawnmaker -v" pnpm tauri dev
```

Notes:

- The first `cargo` compile of the shell takes several minutes; later runs are
  incremental. A Python change costs a restart of the app, not a rebuild.
- `pnpm tauri dev` needs Rust on the host, not in a sandboxed shell.
- Icons live in `deliverer/src-tauri/icons/` and are generated with
  `pnpm tauri icon <1024x1024.png>` (run from `deliverer/`). They are required
  for `tauri build`, not for `dev`.
- The daemon exits ~30 s after the shell stops heartbeating, so a killed shell
  never leaves a crawler behind.

## Running the web / browser mode

Browser mode is the Vue app in a normal browser tab talking to a hand-started
daemon. It is what Docker provides and what you use when Rust is not an option.
Three things do not exist outside the Tauri shell:

- **No sign-in window.** A browser tab cannot read another site's cookies, so
  `SourceCard` unfolds a "developer: paste a session cookie" form (`PHPSESSID`
  for pixiv; `auth_token` + `ct0` for X). The daemon verifies and stores it the
  same way.
- **No updater.** `useUpdater` reports `unsupported`; Settings › Updates says so.
- **No Shutdown button.** Stop the daemon or the container yourself.

### (a) Docker

```sh
docker compose up -d --build            # first time, and after Dockerfile/dependency changes
open http://localhost:5173
docker compose logs -f dev
docker compose run --rm dev coreflame status     # the CLI inside the same image
```

`docker/entrypoint.sh` starts `python -m dawnmaker --host 0.0.0.0 --port 8765
--no-heartbeat --dev`, waits for `DAWNMAKER_READY`, passes the port and token
to Vite through `VITE_DAEMON_URL` / `VITE_DAEMON_TOKEN`, then runs Vite in the
foreground. Compose publishes both ports on `127.0.0.1` only (`5173` webview,
`8765` daemon), so the daemon is loopback from the host's point of view even
though it binds `0.0.0.0` inside the container - which `--host` only allows
together with `--dev`.

- Secrets go in a root `.env` (gitignored): `PIXIV_PHPSESSID=…`, optionally
  `REAVER_PROXY=` and `REAVER_RESOLVER=`. Env overrides whatever is stored.
- The archive (db, blobs, thumbs) is bind-mounted from `./data`, or from
  `CURIO_DATA=/path` if set. Hardlinks work because both trees are in one mount.
- The repo is bind-mounted live at `/app`; `node_modules` are container-only
  volumes so macOS binaries never leak in.

When to do what:

| Change | Command |
|---|---|
| Python or Vue source | nothing - editable install + Vite HMR pick it up; the daemon needs `docker compose restart dev` for Python |
| A dependency added to `package.json` / `pnpm-lock.yaml` | `docker compose restart dev` - the entrypoint runs `pnpm install --frozen-lockfile` on every start |
| A Python dependency in `pyproject.toml`, or `docker/Dockerfile` | `docker compose up -d --build` |
| `docker-compose.yml` (ports, volumes, env) | `docker compose up -d` recreates the container |
| Wipe `node_modules` volumes | `docker compose down -v` (the archive in `./data` is a bind mount and survives) |

### (b) Without Docker

Terminal 1 - the daemon, from the venv:

```sh
. reaver/.venv/bin/activate
cd reaver && python -m dawnmaker --no-heartbeat --dev
# DAWNMAKER_READY {"port": 51234, "token": "…", "pid": 8123}
```

`--no-heartbeat` stops the daemon from exiting after 30 s without a shell;
`--dev` allows `http://localhost:*` and `http://127.0.0.1:*` as request
origins (Vite). Without it every browser request is refused with 403
`bad_origin`.

Terminal 2 - the webview. Copy `deliverer/.env.example` to `deliverer/.env`
and paste the handshake values:

```
VITE_DAEMON_URL=http://127.0.0.1:51234
VITE_DAEMON_TOKEN=<token from DAWNMAKER_READY>
```

```sh
pnpm dev            # root alias for `pnpm --filter deliverer run dev`
```

The port and token change on every daemon start (unless you pass `--port`),
so re-paste after a restart.

## Building installers locally

```sh
. reaver/.venv/bin/activate && pip install pyinstaller
cd deliverer
pnpm tauri build
```

`beforeBuildCommand` in `tauri.conf.json` is `pnpm run build &&
./scripts/build-sidecar.sh`: it type-checks and bundles the webview into
`deliverer/dist/`, then PyInstaller builds `dawnmaker` as a `--onedir` bundle
(`--collect-all gallery_dl`) into `deliverer/src-tauri/resources/sidecar/`,
which `bundle.resources` ships inside the app. On macOS with
`APPLE_SIGNING_IDENTITY` set, the script also signs every Mach-O leaf with the
hardened runtime before Tauri signs the app around it.

Bundles land under `deliverer/src-tauri/target/release/bundle/` (`dmg/`,
`macos/`, `nsis/`, `appimage/`, `deb/`; per-target builds under
`target/<triple>/release/bundle/`). `bundle.targets` is `all` for local builds;
restrict it the way CI does:

```sh
pnpm tauri build --bundles dmg                       # macOS
pnpm tauri build --bundles nsis                      # Windows
pnpm tauri build --bundles appimage,deb              # Linux
rustup target add x86_64-apple-darwin
pnpm tauri build --target x86_64-apple-darwin --bundles dmg   # Intel from an Apple Silicon Mac
```

`createUpdaterArtifacts` is on, so `tauri build` also wants to emit the `.sig`
files the updater checks and expects `TAURI_SIGNING_PRIVATE_KEY` (and
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD`) in the environment, the same way CI has
them. For a purely local, manually installed build, export the key from
`pnpm tauri signer generate` or expect the bundler to complain about a missing
private key.

## The release build (CI)

The full procedure and the verification list live in
`.claude/skills/cut-release/SKILL.md`. In short:

```sh
scripts/bump-version.sh 0.2.0        # tauri.conf.json, package.json, pyproject, __init__, CHANGELOG, lockfile
git commit -am "chore(release): v0.2.0"
git tag v0.2.0 && git push origin master --tags
```

`.github/workflows/release.yml` runs on `v*` tags (and by hand via
`workflow_dispatch`):

1. **check** - `scripts/check-version.sh` (all four version strings agree and
   match the tag), `reaver/check.sh`, and `pnpm --filter deliverer run check`.
2. **build** matrix - `macos-latest` (aarch64, dmg), `macos-15-intel` (x86_64, dmg),
   `windows-latest` (nsis), `ubuntu-22.04` (appimage,deb). Each job builds the
   sidecar **before** `tauri-action`, smokes the built binary (`--help` must
   print the right version), then `tauri-action` builds, signs and uploads to a
   **draft** release named `Curio v<version>` with `latest.json` (the updater
   endpoint) generated from the `.sig` files.
3. **linux-installer** - attaches `scripts/install-linux.sh` to the same draft.

Publish the draft by hand after the verification list in the skill; a draft's
`latest.json` 404s, so nobody updates until you do.

Required repository secrets: `TAURI_SIGNING_PRIVATE_KEY`,
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (from `pnpm tauri signer generate -w
~/.tauri/curio.key`; the public key goes over `REPLACE_WITH_PUBLIC_KEY` in
`tauri.conf.json`). Optional, for notarised macOS builds: `APPLE_CERTIFICATE`,
`APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`,
`APPLE_PASSWORD`, `APPLE_TEAM_ID`. `GITHUB_TOKEN` is provided by Actions.
Replace `luissebastian953` in `tauri.conf.json` (updater endpoint) and
`scripts/install-linux.sh` before the first tag; the signing key is the update
channel's root of trust - losing it strands every install.

## Checks

```sh
pnpm check          # root: deliverer check + reaver/check.sh + scripts/check-version.sh
```

- `pnpm --filter deliverer run check` = `vue-tsc --noEmit && eslint . &&
  prettier --check . && node scripts/i18n-check.mjs && vitest run`.
- `reaver/check.sh` = `ruff check`, `ruff format --check`, `mypy`, every
  `tests/test_*.py` (all offline), and a grep that fails on any `verify=False`.
  mypy's cache is put in `/tmp/mypy_cache` on purpose - a synced folder breaks
  its SQLite cache.
- `scripts/check-version.sh` - the four version strings agree.

Day to day, from `deliverer/`: `pnpm test` (Vitest once), `pnpm test:watch`,
`pnpm lint:fix`, `pnpm format`, `pnpm i18n:check`. From `reaver/`:
`ruff format . && ruff check . --fix`. Commit with `pnpm commit` at the root.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Rail says **daemon unreachable**; console shows `no daemon endpoint` | Browser mode without `VITE_DAEMON_URL` / `VITE_DAEMON_TOKEN` | Fill `deliverer/.env` from the `DAWNMAKER_READY` line and restart Vite |
| Every request 403 `bad_origin` in a browser tab | Daemon started without `--dev` | Restart it with `--no-heartbeat --dev` |
| 421 `bad_host` | Reaching the daemon through a name other than `127.0.0.1`/`localhost` (a LAN IP, a tunnel) | The daemon is loopback-only by design; use `127.0.0.1` |
| 401 `unauthorized` on every call | Stale token in `.env` after a daemon restart, or `?token=` used on a route other than `/api/events`, `/api/media/*`, `/api/preview/*` | Re-paste the token; send it as `Authorization: Bearer` elsewhere |
| Daemon prints `{"error": "already_running", …}` and exits 3 | `~/.reaver/dawnmaker.lock` names a live daemon on a port that answers | Stop the other daemon (or attach to it). A stale lock from a dead pid is reclaimed automatically |
| Gallery blank inside Tauri, no error | CSP in `tauri.conf.json` no longer wildcards `http://127.0.0.1:*` in `connect-src` and `img-src` | Restore it; the port is ephemeral |
| Docker: `ModuleNotFoundError` after adding a Python dependency | Image built before the change | `docker compose up -d --build` |
| Docker: Vite cannot resolve a newly added package | Container `node_modules` volume behind the lockfile | `docker compose restart dev` (entrypoint reinstalls) |
| pixiv 401 / "search needs a signed-in session" | Not signed in, or the stored `PHPSESSID` expired | Settings › Accounts → Sign in (or paste in browser mode). `poll` refuses to start unauthenticated |
| Tag probe shows `⚠ 0 - fullwidth（）won't match` | pixiv's exact-tag search does not match fullwidth parentheses | Use ASCII `( )` |
| `ERR_BLOCKED_BY_CLIENT` on `/api/media/...` or `/api/preview/...` in a browser tab | An ad/tracker blocker extension matching the URL | Allow-list `127.0.0.1` in the extension, or test in the Tauri window |
| `resolver_blocked` from `coreflame net` inside a sandbox or container | The sandbox's own egress rules, not your ISP | Run `coreflame net www.pixiv.net` from a normal terminal on the host (or `docker compose run --rm dev coreflame net`) |
| mypy dies with a sqlite I/O error | Cache directory on a synced folder | `mypy --cache-dir /tmp/mypy_cache` (what `check.sh` does) |
| `tauri build` fails on missing icons | `src-tauri/icons/` not generated | `pnpm tauri icon <1024.png>` from `deliverer/` |
| macOS refuses to open the built app | Unsigned / un-notarised build | Right-click → Open once; add the `APPLE_*` secrets for notarised releases |
