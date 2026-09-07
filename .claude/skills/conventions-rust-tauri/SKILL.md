---
name: conventions-rust-tauri
description: Conventions for deliverer/src-tauri/ (Tauri v2): commands, capabilities, sidecar handshake and shutdown, cookies_for_url, CSP, updater, first cargo build. Use when touching Rust or tauri.conf.json.
---

# Rust / Tauri conventions — `deliverer/src-tauri/`

Tauri v2, crate `deliverer` with lib name `deliverer_lib` (`Cargo.toml`).
Files: `src/main.rs` (only calls `deliverer_lib::run()`), `src/lib.rs`
(builder, plugins, `generate_handler!`, window/run events), `src/sidecar.rs`
(spawn / handshake / shutdown / `daemon_endpoint`), `src/auth.rs`
(`source_login` window), `build.rs`, `tauri.conf.json`,
`capabilities/default.json`. The Rust surface is deliberately tiny: three
commands. Policy lives in Python, UI in Vue; Rust only bridges.

## Commands and state

- A command is `#[tauri::command] fn name(...) -> Result<T, String>`; errors
  are strings (`map_err(|e| e.to_string())`) because the webview only needs a
  message. Register every command in `generate_handler![...]` in `lib.rs` or
  `invoke()` fails at runtime with "command not found".
- Shared state is a struct `.manage()`d in the builder and read with
  `tauri::State<T>` / `app.state::<T>()`; interior mutability via
  `std::sync::Mutex` (`Sidecar { child, endpoint }`). Hold a lock briefly;
  never across an `.await`.
- Plugins registered: `dialog`, `opener`, `updater`, `process`. Adding one
  means: `Cargo.toml` dependency, `.plugin(...)` in `run()`, the JS package in
  `deliverer/package.json`, and a permission in `capabilities/default.json`.

## Capabilities — the login window gets none

`capabilities/default.json` applies to `"windows": ["main"]` only:
`core:default`, `dialog:allow-open`, `opener:allow-open-url`,
`updater:default`, `process:allow-restart`. The `source-login` window
(`auth.rs`, label `LABEL`) loads remote content (pixiv / x.com login pages)
and MUST NOT appear in any capability, so that content has no IPC. Do not
"fix" a missing-permission error by widening `windows`.

## Sidecar — resources, handshake, three-layer shutdown

- The daemon ships as `bundle.resources` (`resources/sidecar/` → `sidecar/`),
  never `externalBin` (forces `--onefile`, re-extracts on every launch, not
  replaced by NSIS on update). Release resolves
  `sidecar/dawnmaker` under `BaseDirectory::Resource`.
- Dev (`cfg!(debug_assertions)`) runs `python -m dawnmaker` from whatever
  venv is active, or `REAVER_DEV_CMD="…"` overrides the whole command line.
  So `pnpm tauri dev` needs the venv activated in the same shell.
- **The token travels only over stdout.** `spawn()` blocks until one line
  `DAWNMAKER_READY {"port":…,"token":…,"pid":…}`; argv is visible in `ps`
  and a file is readable by anything. Never log it, never put it in argv.
- Shutdown, three layers: (1) `sidecar::shutdown` on `WindowEvent::Destroyed`
  and on `RunEvent::ExitRequested | RunEvent::Exit` (both arms — Cmd-Q and
  the `shutdown_app` command take different paths); (2) the daemon's own
  heartbeat timeout covers `kill -9` and Rust panics; (3) the daemon lockfile
  makes a second launch attach instead of racing the SQLite file. Never
  parent-PID polling (`getppid()` is meaningless on Windows).

## `cookies_for_url` — async, and it returns HttpOnly cookies

`source_login` opens the site's own login page in a second window and polls
`win.cookies_for_url(url)` every 500 ms (timeout 300 s) until every cookie in
`needed` exists (`PHPSESSID`; `auth_token` + `ct0`), closes the window and
returns the map. It is `async fn` on purpose: in a sync command
`cookies_for_url` can deadlock on Windows, and the poll must not block the
main thread. Keep any new cookie-reading code in an async command. The
cookies go straight to the webview → `POST /api/auth/<source>`; nothing in
Rust stores them.

## CSP — the config that blanks the gallery

Once `app.security.csp` is set, loopback is blocked unless listed; the port is
ephemeral, so both `connect-src` and `img-src` carry `http://127.0.0.1:*`
(`connect-src` also `ipc: http://ipc.localhost`). A blank gallery with no
console error after a CSP edit is this.

## Updater

`plugins.updater.pubkey` = `REPLACE_WITH_PUBLIC_KEY` and the endpoint contains
`luissebastian953` until the one-time setup in `cut-release` is done; until
then an update check errors and `stores/updater.ts` shows phase `error`,
which is expected in dev. `bundle.createUpdaterArtifacts: true` and `tauri-action` produce
`latest.json`. Version source of truth is `tauri.conf.json` — change it only
via `scripts/bump-version.sh`.

## Dev and build on the host

`pnpm tauri dev` (from the root) needs Rust stable ≥ 1.77 and, on macOS, the
Xcode Command Line Tools; on Linux the webkit2gtk-4.1 deps from
`release.yml`. Icons are not needed for `dev`, only `build`
(`pnpm tauri icon <1024.png>` — `icons/README.md`). Neither works from a
sandboxed shell without a display.

## Before commit

```
cd deliverer/src-tauri && cargo fmt && cargo clippy -- -D warnings
```

**Honest note:** the Rust here has never been compiled in this environment —
`src-tauri/target/` is empty and there is no `Cargo.lock`. The first `cargo
check` will likely surface API-shape errors (plugin builder names, the
`cookies_for_url` signature, `RunEvent` variants). Resolve them against the
installed crate versions (`cargo doc --open` or the tauri 2.x docs), keep the
intent documented in the comments, commit the resulting `Cargo.lock`, and do
not paper over a warning with `#[allow]`. After it compiles: `pnpm tauri dev`
must print the handshake, the gallery must show images (CSP), and closing the
window must leave no `dawnmaker` process (`pgrep -f dawnmaker`).
