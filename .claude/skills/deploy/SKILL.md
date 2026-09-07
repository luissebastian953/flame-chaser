---
name: deploy
description: Deploy Curio: the desktop release pipeline (tag → CI → installers → in-app update), the Docker browser-mode stack, and the secrets each needs. Use when shipping or running compose.
---

# Deploy Curio

Two deployment targets, nothing else: the **desktop app** users install
(and which updates itself), and the **Docker browser-mode stack** for
development without Tauri. There is no server deployment — the daemon is a
loopback sidecar, never a network service.

## Desktop release — summary (full procedure: `cut-release`)

```
scripts/bump-version.sh X.Y.Z                 # tauri.conf.json is the source; syncs package.json,
                                              # pyproject.toml, coreflame/__init__.py, CHANGELOG, lockfile
pnpm check                                    # includes scripts/check-version.sh
git commit -am "chore(release): vX.Y.Z"
git tag vX.Y.Z && git push origin master --tags
```

`.github/workflows/release.yml` on a `v*` tag: job `check` (check-version,
`reaver/check.sh`, deliverer `check`) → matrix `build` on macos-latest
(aarch64 dmg), macos-13 (x86_64 dmg), windows-latest (nsis), ubuntu-22.04
(appimage,deb). In every build job the **sidecar is built before
`tauri-action`** (`deliverer/scripts/build-sidecar.sh`, PyInstaller
`--onedir` → `src-tauri/resources/sidecar/`, smoke-tested with `--help`),
then `tauri-action` bundles, signs and uploads a **draft** release with
`latest.json` (`includeUpdaterJson: true`). Job `linux-installer` attaches
`scripts/install-linux.sh`. Publish the draft only after the verification
list in `cut-release` (install over the previous version, `GET /api/health`
reports the new backend version, `latest.json` reachable).

### Secrets (GitHub → Settings → Secrets → Actions)

- `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` —
  required; from `pnpm tauri signer generate -w ~/.tauri/curio.key`. Losing
  the key strands every install; it is never in the repo.
- Optional until there is a Developer ID: `APPLE_CERTIFICATE`,
  `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`,
  `APPLE_PASSWORD`, `APPLE_TEAM_ID`. Without them the dmg builds unsigned
  and users right-click → Open once.
- `GITHUB_TOKEN` is automatic (`permissions: contents: write`).

### One-time placeholders still in the repo

- `deliverer/src-tauri/tauri.conf.json`: `REPLACE_WITH_PUBLIC_KEY`
  (updater pubkey) and `luissebastian953` in the updater endpoint URL.
- `scripts/install-linux.sh`: `luissebastian953` (twice: comment and `REPO=`).
- `deliverer/src-tauri/icons/` holds only a README; `pnpm tauri icon
  <1024.png>` before the first `build`.
Until these are replaced a release builds but no install can update.

### How users install and update

macOS: open the dmg, drag to Applications. Windows: run the NSIS `.exe`
(per-user install, passive update mode). Linux:
`curl -fsSL https://github.com/<owner>/flame-chaser/releases/latest/download/install-linux.sh | sh`
(AppImage to `~/.local/bin/curio` + a `.desktop` entry; x86_64 only). After
that the app checks `latest.json` daily and on demand (Settings › Updates),
downloads freely, and **installs only when the job queue is idle** — never
over a running crawl. Shell and sidecar update together in one artifact.

## Docker — browser-mode dev stack

```
docker compose up -d --build          # first time, or after a Dockerfile / compose change
open http://localhost:5173
docker compose logs -f dev
docker compose run --rm dev coreflame status     # the CLI inside the container
docker compose down
```

One service `dev` (`docker/Dockerfile`, python:3.12-slim + Node 22 + pnpm via
corepack): `entrypoint.sh` starts `python -m dawnmaker --host 0.0.0.0 --port
8765 --no-heartbeat --dev`, waits for the `DAWNMAKER_READY` line, exports
the token to Vite via the environment, then runs Vite on 5173. The repo is
bind-mounted at `/app`; `node_modules` are container-only volumes.

- The daemon binds `0.0.0.0` **inside** the container only because `--dev`
  is passed (`__main__.py` refuses otherwise); compose publishes both ports
  on `127.0.0.1` only, so nothing is on the LAN. The bearer token still applies.
- Archive: `./data` by default, or `CURIO_DATA=/path` in `.env`
  (`REAVER_HOME=/data` inside). Hardlinks need one mount.
- Secrets: root `.env` (gitignored): `PIXIV_PHPSESSID=`, `REAVER_PROXY=`,
  `REAVER_RESOLVER=`. Prefer signing in through Settings › Accounts; an env
  value overrides it. Never put a value in `docker-compose.yml`.
- The Tauri window cannot run in Docker; that is `pnpm tauri dev` on the host.

### Restart, rebuild or recreate?

| You changed | Do |
|---|---|
| Python or Vue source | nothing — editable install + Vite HMR pick it up |
| a Python test/lint run | `docker compose run --rm dev sh -c 'cd reaver && ./check.sh'` |
| `deliverer/package.json` / lockfile | `docker compose restart dev` (entrypoint runs `pnpm install --frozen-lockfile`) |
| `reaver/pyproject.toml` deps | `docker compose up -d --build` (pip install is an image layer) |
| `docker/Dockerfile`, `docker-compose.yml`, `entrypoint.sh` | `docker compose up -d --build` |
| `.env` | `docker compose up -d --force-recreate` (env is read at container creation) |

## Verification

- Desktop: Settings › Updates shows X.Y.Z (`__APP_VERSION__`) AND
  `GET /api/health` on the sidecar returns `"version": "X.Y.Z"`; a machine on X.Y.Z-1 sees and installs the update; an
  update offered mid-crawl waits; a fresh machine launches the packaged build.
- Docker: `docker compose ps` healthy; `logs` show `DAWNMAKER_READY` then the
  `curio: webview …` line; the gallery renders thumbnails (token reached
  Vite); `curl http://127.0.0.1:8765/api/health` without a token → 401.
