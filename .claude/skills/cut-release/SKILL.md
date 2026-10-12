---
name: cut-release
description: Cut a Curio release — version bump, sidecar build, tag, CI, and verifying the update actually shipped new backend code. Use when releasing, tagging a version, publishing an update, or debugging the Tauri updater.
---

# Cut a release

## Order matters

1. **`scripts/bump-version.sh X.Y.Z`.** `tauri.conf.json` is the single
   source (`__VERSION__` in CI substitutes from it); the script keeps
   `package.json`, `pyproject.toml` and `coreflame/__init__.py` in step and
   promotes the `## Unreleased` section of `CHANGELOG.md` -- which Settings ›
   Updates renders, so write it for the person using the app.
   `scripts/check-version.sh` fails CI on any drift or a tag that disagrees.
   The script also refreshes `pnpm-lock.yaml`.
2. **Green.** `pnpm check` at the root: deliverer `check` (vue-tsc, eslint,
   prettier, i18n-check, vitest), `reaver/check.sh` (ruff, mypy, every test,
   the `verify=False` grep) and `check-version.sh`. CI's `check` job runs the
   same three and gates the build matrix; a red check means no artifacts.
3. **Confirm migrations.** If the schema changed since the last tag: a
   `schema_version` step exists, it is forward-only and in one transaction, the
   daemon backs up the db file before running it, and `min_app_version` is
   recorded so an older shell refuses rather than half-reads.
4. **Commit, tag, push.** `git commit -am "chore(release): vX.Y.Z"` — that
   exact type/scope, commitlint enforces it — then
   `git tag vX.Y.Z && git push origin master --tags`.
   `.github/workflows/release.yml` does the rest and leaves a **draft**
   release; publish it only after the verification list below.

## One-time setup (placeholders in the repo until done)

- `pnpm tauri signer generate -w ~/.tauri/curio.key` → paste the public
  key over `REPLACE_WITH_PUBLIC_KEY` in `tauri.conf.json`; the private key and
  its password become the `TAURI_SIGNING_*` secrets.
- Replace `luissebastian953` in `tauri.conf.json` (updater endpoint) and
  `scripts/install-linux.sh` with the GitHub owner.
- Apple: without a Developer ID the dmg still builds; users right-click →
  Open once. Add the `APPLE_*` secrets when you have one.
- The runner needs `deliverer/src-tauri/icons/` (committed). The source is
  `src-tauri/app-icon.svg`; regenerate with `pnpm tauri icon src-tauri/app-icon.svg`
  from `deliverer/`, then delete `icons/android` and `icons/ios`.

## What CI must do, in this order

**Test the frozen sidecar, not just `python -m dawnmaker`.** The bundle
has its own import rules: PyInstaller's entry is `scripts/sidecar_entry.py`
(dawnmaker's `__main__.py` uses relative imports and dies as a bare script) and
`--paths ../reaver` (an editable install is an import hook PyInstaller cannot
follow). After `bash scripts/build-sidecar.sh`, run
`REAVER_HOME=$(mktemp -d) src-tauri/resources/sidecar/dawnmaker --no-heartbeat`:
it must print `DAWNMAKER_READY` and answer `/api/health` at once.

**Build the Python sidecar BEFORE `tauri-action`.** This is the step that gets
forgotten and it produces the worst bug in the system: the app updates, reports
the new version, and runs old backend code. On a clean runner
`resources/sidecar/` is empty; locally it holds last week's daemon.

Matrix: `macos-latest` (aarch64), `macos-13` (x86_64), `ubuntu-22.04`,
`windows-latest`; every job installs with `pnpm install --frozen-lockfile`
and runs Tauri via `pnpm tauri`.
Secrets: `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`,
plus Apple signing vars. On macOS the leaf-signing loop in `build-sidecar.sh`
runs before Tauri signs the app around it — notarization needs every `.so` and
`.dylib` signed with the hardened runtime, and `codesign --deep` is unreliable.

## The signing key

It is the root of trust for every install. Anyone holding it can ship arbitrary
code to every copy of the app; losing it strands every existing install
permanently, because they only accept the key they shipped with. Never in the
repo. Backed up where you back up passwords.

## Never install over running work

Downloading is free and touches nothing. **Installing** kills the sidecar and
relaunches, which can land between a blob write and its `media` row. So the
install gate is an idle job queue: with a job running the UI says "Update ready
— will install when the current crawl finishes". Then cancel cooperatively,
wait for the SQLite lock to release, relaunch. Never auto-install silently.

## Verification — the one that catches real breakage

- Install the update on a machine running the previous version
- Check the **backend** version, not just the shell's — `GET /health` on the
  daemon. Matching shell + stale daemon is the failure this whole procedure
  exists to prevent.
- Confirm `latest.json` is reachable at the endpoint (a draft release 404s)
- Trigger an update with a job running → it waits rather than killing the job
- On a machine that has never seen the app, the packaged build launches
  (the signing/notarization check)
