# 8. Deployment diagram, and how a version travels

Two deployment shapes exist: the **desktop app** (the product) and the
**browser-mode stack** (Docker, for development without Rust). Both run the
same daemon and the same Vue bundle; only the shell differs.

## 8.1 Desktop deployment

```mermaid
flowchart TB
  subgraph dev["developer machine"]
    repo["git checkout · master<br/>pnpm workspace · reaver venv"]
    bump["scripts/bump-version.sh X.Y.Z<br/>→ chore(release): vX.Y.Z · tag"]
  end

  subgraph gha["GitHub Actions · release.yml (on tag v*)"]
    chk["check job · ubuntu-latest<br/>check-version.sh · reaver/check.sh · deliverer check"]
    subgraph matrix["build matrix · fail-fast off"]
      m1["macos-latest<br/>aarch64 · dmg"]
      m2["macos-15-intel<br/>x86_64 · app,dmg"]
      m3["windows-latest<br/>x86_64 · nsis"]
      m4["ubuntu-22.04<br/>x86_64 · appimage + deb"]
    end
    order["in every job, in order:<br/>1 build-sidecar.sh (PyInstaller --onedir, macOS leaf signing)<br/>2 smoke: sidecar --help<br/>3 tauri-action: build · sign (minisign) · upload"]
    lin["linux-installer job<br/>attach install-linux.sh"]
  end

  subgraph ghr["GitHub Releases · draft until verified"]
    assets["Curio_X.Y.Z_*.dmg · -setup.exe · .AppImage · .deb · .sig files"]
    latest["latest.json<br/>version · platforms{url, signature}"]
  end

  subgraph user["user's machine (macOS · Windows · Linux)"]
    subgraph bundle["Curio.app / Curio install · one artifact"]
      exe["deliverer (Rust binary)<br/>Tauri v2 runtime · tauri-plugin-updater (pubkey compiled in)"]
      wv["system webview<br/>WebKit (macOS) · WebView2 (Windows) · webkit2gtk (Linux)<br/>runs the Vite bundle: index.html + pip.html"]
      sc["resources/sidecar/dawnmaker<br/>PyInstaller --onedir: Python 3.12 runtime · coreflame · dawnmaker ·<br/>httpx · Pillow · gallery_dl · fastapi/uvicorn · onnxruntime (classify)"]
    end
    subgraph home["~/.reaver (REAVER_HOME)"]
      db[("reaver.db + -wal")]
      cfg["config.json · secrets.json 0600 · twitter-cookies.txt 0600"]
      lock["dawnmaker.lock {pid, port, started_at}"]
      models["models/ (downloaded on first use, ~1.3 GB total)"]
      exports["exports/ · import/<stamp>/ (staging)"]
    end
    subgraph libr["library folder (user-chosen, not a sync root)"]
      blobs[("blobs/ · thumbs/ · by-character/ · trash/")]
    end
  end

  subgraph net["internet"]
    pixiv["pixiv.net · i.pximg.net"]
    x["x.com"]
    hf["huggingface.co"]
    other["danbooru · wikidata · speed.cloudflare.com · ipinfo.io"]
    doh["DoH: 1.1.1.1 · 8.8.8.8 (optional resolver)"]
  end

  repo --> bump -- "git push --tags" --> chk --> matrix --> order --> ghr
  order --> lin --> ghr
  assets -- "first install: download by hand" --> bundle
  latest -- "daily check · signed · install when idle" --> exe
  exe -- "spawn · stdout handshake · heartbeat · kill" --> sc
  exe -- "IPC: invoke / emit" --> wv
  wv -- "HTTP + SSE 127.0.0.1:<ephemeral>, Bearer" --> sc
  sc --> db & cfg & lock & models & exports
  sc --> blobs
  blobs -- "thumbs over HTTP, never file://" --> wv
  sc -- "httpx · Referer · token buckets · optional proxy" --> pixiv
  sc -- "gallery-dl subprocess (the same exe, --gallery-dl)" --> x
  sc -- "first classify" --> hf
  sc --> other
  sc -. "resolver = doh" .-> doh
```

Execution environments, by node:

| Node | Runtime | Process boundary | Notes |
|---|---|---|---|
| `deliverer` | Rust, Tauri v2 | the app process | owns the window, tray, login window, mini window, updater, and the daemon's lifetime |
| webview | the OS webview | same process, separate origin (`tauri://localhost` or `http://tauri.localhost`) | no filesystem, no cookies for the sites; CSP allows `http://127.0.0.1:*` for `connect-src` and `img-src` only |
| `dawnmaker` | frozen CPython 3.12 (PyInstaller) in release; the venv's `python -m dawnmaker` in a debug build | child process | one per machine, enforced by the lockfile; exits ~30 s after the shell's beats stop (graced once) |
| gallery-dl | the same frozen executable re-entered with `--gallery-dl`, or `python -m gallery_dl` | grandchild process per X request | so a user needs nothing on `PATH` |
| classifier models | ONNX, run in-process by onnxruntime | inside the worker thread | optional; absent in a build without the `classify` extra |

## 8.2 Browser-mode deployment (Docker)

```mermaid
flowchart LR
  subgraph host["host"]
    browser["any browser<br/>http://localhost:5173"]
    data[("./data or CURIO_DATA<br/>reaver.db · blobs · thumbs")]
    env[".env: PIXIV_PHPSESSID · REAVER_PROXY · REAVER_RESOLVER"]
  end
  subgraph c["container curio-dev (python:3.12-slim + Node 22)"]
    entry["entrypoint.sh<br/>start daemon → wait for DAWNMAKER_READY → export VITE_DAEMON_URL / _TOKEN → exec vite"]
    dm["dawnmaker --host 0.0.0.0 --port 8765 --no-heartbeat --dev"]
    vite["vite --host 0.0.0.0 --port 5173"]
  end
  browser -- "127.0.0.1:5173" --> vite
  browser -- "127.0.0.1:8765 · Bearer from the Vite env" --> dm
  entry --> dm & vite
  dm --> data
  env --> dm
```

Three things do not exist here: the sign-in window (paste the cookie), the
updater (the store is born `unsupported`), and the mini window / tray
(`pip_supported` answers `browser`). Compose publishes both ports on
`127.0.0.1` only; `0.0.0.0` inside the container is allowed only with
`--dev`.

## 8.3 Versioning: one number, five places, one gate

```mermaid
flowchart LR
  src["deliverer/src-tauri/tauri.conf.json<br/>version: X.Y.Z  (source of truth)"]
  bump["scripts/bump-version.sh X.Y.Z"]
  pkg["deliverer/package.json"]
  py["reaver/pyproject.toml"]
  init["reaver/coreflame/__init__.py __version__"]
  cl["CHANGELOG.md<br/>## Unreleased → ## X.Y.Z - date"]
  lockf["pnpm-lock.yaml refreshed"]
  gate["scripts/check-version.sh<br/>all four equal · tag vX.Y.Z matches<br/>(in pnpm check and CI)"]
  tag["git tag vX.Y.Z"]
  ci["release.yml: tauri-action tagName v__VERSION__"]
  json["latest.json version"]
  appv["shell: __APP_VERSION__ (Vite define from package.json)"]
  health["daemon: GET /api/health version = coreflame.__version__"]
  mismatch["Settings › Updates daemonMismatch<br/>shell ≠ daemon ⇒ a release shipped without a new sidecar"]
  schema["schema_version table<br/>int 1..12 · name · applied_at · min_app_version = X.Y.Z"]
  bundlev["bundle manifest<br/>app_version · schema_version → bundle_too_new"]

  bump --> src & pkg & py & init & cl & lockf
  src --> gate
  pkg --> gate
  py --> gate
  init --> gate
  tag --> gate
  gate --> ci --> json
  pkg --> appv
  init --> health
  appv --> mismatch
  health --> mismatch
  init -- "stamped when a migration applies" --> schema
  init --> bundlev
  schema --> bundlev
```

What is versioned, how, and what reads it:

| Thing | Scheme | Written by | Read by | Skew guard |
|---|---|---|---|---|
| The app (shell + webview + sidecar) | semver `X.Y.Z`, one number for the whole bundle | `bump-version.sh` into four files | the updater (`latest.json` vs installed), Settings › Storage header, `/api/health` | `check-version.sh` fails `pnpm check` and CI on drift; `tauri-action` substitutes `__VERSION__` from `tauri.conf.json` so tag, release name and manifest cannot disagree |
| Git history | one repo, `master`, Conventional Commits with a fixed scope list, annotated tags `vX.Y.Z` | `pnpm commit` (cz-git), commitlint on `commit-msg` | `release.yml` triggers on `v*` | the tag must equal the version in the files (`check-version.sh` under `GITHUB_REF_NAME`) |
| Database schema | integer, forward-only (`@migration(n, name)`), currently 12 | `migrations.apply` at `Store()` open, inside one transaction per step, after backing the file up | every `Store`, `/api/health`, `/api/storage` | `min_app_version` stamped with the app version that applied it: an older daemon refuses the db instead of half-reading it |
| API contract | unversioned on purpose | `dawnmaker/app.py`, mirrored by hand in `lib/types.ts` | the webview | shell and daemon ship as one artifact (`bundle.resources`), so there is never a version to negotiate; `daemonMismatch` catches a build that broke that promise |
| Backup bundle | manifest carries `app_version` and `schema_version`; two codecs (`.curio`, `.zip`) | `bundle.export` | `bundle.inspect` | `bundle_too_new` when the schema is newer than the importing daemon; the staged db is migrated forward on the copy before merging |
| Classifier verdicts | the model id stored on each `image_kinds` / `image_people` / `image_identity` row | the labeler on ingest | backlog passes (`unlabeled_media(model)`) | a new model is a re-label of stored bytes, never a re-fetch |
| Raw payloads | content-addressed (`raw_payloads.sha256`), `kind` names the spec | adapters via `put_raw` | `raws_for(source, kind)` | a spec fix is a re-parse of retained JSON |
| User-facing changes | `CHANGELOG.md`, newest first, `Added / Changed / Fixed / Removed` | every feature commit under `## Unreleased` | Settings › Updates renders it | `bump-version.sh` promotes the section with the date |
| Dependencies | `pnpm-lock.yaml` (frozen in CI), `pyproject.toml` ranges with `gallery-dl` kept current | `pnpm install`, `pip` | the Docker image, CI | `--frozen-lockfile` everywhere; gallery-dl owns the X protocol so updating it is the fix for an X breakage |

Release procedure and the post-release verification list (install over the
previous version, check the *daemon's* version, confirm `latest.json`
resolves, confirm an update waits on a running job): `.claude/skills/cut-release`.
