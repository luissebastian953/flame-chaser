---
name: conventions-rust-tauri
description: Conventions for deliverer/src-tauri/ (Tauri v2): commands, capabilities, sidecar handshake and shutdown, cookies_for_url, CSP, updater, first cargo build. Use when touching Rust or tauri.conf.json.
---

# Rust / Tauri conventions - `deliverer/src-tauri/`

Tauri v2, crate `deliverer` with lib name `deliverer_lib` (`Cargo.toml`).
Files: `src/main.rs` (only calls `deliverer_lib::run()`), `src/lib.rs`
(builder, plugins, `generate_handler!`, window/run events), `src/sidecar.rs`
(spawn / handshake / shutdown / `daemon_endpoint`), `src/auth.rs`
(`source_login` window), `src/pip.rs` (the pipeline mini window:
`pip_supported` / `pip_open` / `pip_close` / `pip_resize` / `pip_snap`),
`src/tray.rs` (tray icon + menu, `tray_update`, `show_main`), `build.rs`,
`tauri.conf.json`, `capabilities/default.json` + `capabilities/pip.json`.
The Rust surface is deliberately small: a window, a tray, a sidecar.
Policy lives in Python, UI in Vue; Rust only bridges.

## Commands and state

- A command is `#[tauri::command] fn name(...) -> Result<T, String>`; errors
  are strings (`map_err(|e| e.to_string())`) because the webview only needs a
  message. Register every command in `generate_handler![...]` in `lib.rs` or
  `invoke()` fails at runtime with "command not found".
- Shared state is a struct `.manage()`d in the builder and read with
  `tauri::State<T>` / `app.state::<T>()`; interior mutability via
  `std::sync::Mutex` (`Sidecar { child, endpoint }`). Hold a lock briefly;
  never across an `.await`.
- Plugins registered: `dialog`, `opener`, `updater`, `process`,
  `notification`. Tauri features: `macos-private-api`, `tray-icon`,
  `image-png` (the tray's embedded PNG). Adding a plugin
  means: `Cargo.toml` dependency, `.plugin(...)` in `run()`, the JS package in
  `deliverer/package.json`, and a permission in `capabilities/default.json`.

## Windows other than `main`

- `source-login` (auth.rs): remote content, **no capability** (below).
- `pip` (pip.rs): the pipeline mini window, `pip.html` → `src/pip/` (no
  Vue). `capabilities/pip.json` grants `core:event:default` and
  `core:window:allow-start-dragging` only. The app's own commands
  (`pip_*`, `show_main`) need no ACL entry: without an app ACL manifest a
  local window may call them. Create it from an **async** command
  (Windows deadlocks on sync creation), always-on-top, undecorated,
  transparent, `focused(false)`, `shadow(false)`; close it (`w.close()`),
  never hide - a hidden WebView keeps its memory. `skip_taskbar` is
  `cfg(not(macos))` (a no-op that warns there). The panel is built **bare
  and hidden** (`WindowBuilder`, feature `unstable`), `prepare` runs on the
  main thread, the WebView is added after it (`add_child`, same label so
  `get_webview_window` still finds it), and `reveal` shows it last
  (`orderFrontRegardless` / `SW_SHOWNOACTIVATE` / `show()`). That order is
  load-bearing twice: Spaces and virtual desktops read a window's flags
  when it is first ordered in, and WebKit KVO-observes its window from the
  moment the view is installed, which pins the class - re-classing a window
  that already holds a WebView aborts the app at close (`removeObserver:`
  throws). On macOS a regular app's `NSWindow` never joins
  another app's full-screen Space whatever its collection behaviour (only
  the desktops), while a non-activating `NSPanel` joins every Space - so
  `prepare` re-classes tao's window to `CurioPanel` (`NSPanel`
  subclass via objc2 `define_class!`, keeping tao's key/main/drag
  overrides; objc2 0.6 + objc2-app-kit 0.3, the lines tao uses), adds the
  `NonactivatingPanel` style and `CanJoinAllSpaces | FullScreenAuxiliary`.
  Measure Spaces membership with `CGSCopySpacesForWindows` (SkyLight,
  private; a throwaway Swift script), not with `isVisible`;
  Windows sets `WS_EX_TOOLWINDOW` (windows-sys 0.61) so virtual desktops do
  not pin it. Neither can be compiled on the other OS: a change there is
  verified by the release workflow's matrix. `pip_supported` answers
  `wayland` when `XDG_SESSION_TYPE=wayland` and `GDK_BACKEND` is not
  `x11`: always-on-top and `set_position` silently no-op on Wayland.
- Tray (`tray.rs`): `TrayIconBuilder::with_id("main")`, built in `setup`
  after the sidecar. macOS gets `icons/tray.png` (44 px monochrome
  template, rendered from the BrandMark paths - alpha only, the system
  tints it), elsewhere `default_window_icon()`. Menu ids `pause`,
  `show-pip`, `quit` → `emit_to("main", "tray:…")`; quit = the Cmd-Q
  path (`sidecar::shutdown` then `app.exit`). The webview owns the labels
  (`tray_update`), so the menu follows the language.

## Capabilities - the login window gets none

`capabilities/default.json` applies to `"windows": ["main"]` only:
`core:default`, `dialog:allow-open`, `opener:allow-open-url`,
`opener:allow-reveal-item-in-dir` (the detail panel's Reveal: the daemon
hands the blob's absolute path, the webview never reads the disk itself),
`updater:default`, `process:allow-restart`, `core:window:allow-set-effects`
(Settings › Theme's desktop blur; the window is `transparent: true` with
`macOSPrivateApi` for it). The `source-login` window
(`auth.rs`, label `LABEL`) loads remote content (pixiv / x.com login pages)
and MUST NOT appear in any capability, so that content has no IPC. Do not
"fix" a missing-permission error by widening `windows`.

## Sidecar - resources, handshake, three-layer shutdown

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
- Shutdown, three layers: (1) `sidecar::shutdown` on the **main** window's
  `WindowEvent::Destroyed` (the handler fires for every window; the
  `source-login` window is destroyed right after the cookies are read, and
  an unfiltered handler SIGKILLed the daemon there, so every sign-in failed)
  and on `RunEvent::ExitRequested | RunEvent::Exit` (both arms - Cmd-Q and
  the `shutdown_app` command take different paths); (2) the daemon's own
  heartbeat timeout covers `kill -9` and Rust panics - `sidecar.rs` sends the
  beats from a native thread with a raw HTTP/1.1 POST over loopback, never from
  a webview timer (WebKit/App Nap throttle those past the timeout); (3) the daemon lockfile
  keeps a second daemon off the SQLite file (`already_running`, exit 3);
  `spawn` SIGTERMs a holder whose parent is gone (a crashed Curio's daemon,
  alive until its heartbeat runs out) and retries ≤ 20 s, and fails the
  launch when the holder's Curio is alive. Never
  parent-PID polling (`getppid()` is meaningless on Windows).

## `cookies_for_url` - async, and it returns HttpOnly cookies

`source_login` opens the site's own login page in a second window and polls
`win.cookies_for_url(url)` every 500 ms (timeout 300 s) until every cookie in
`needed` exists (`PHPSESSID`; `auth_token` + `ct0`), closes the window and
returns the map. It is `async fn` on purpose: in a sync command
`cookies_for_url` can deadlock on Windows, and the poll must not block the
main thread. Keep any new cookie-reading code in an async command. The
cookies go straight to the webview → `POST /api/auth/<source>`; nothing in
Rust stores them.

## `tauri.conf.json` takes no comments

JSON has none, and `"//"` keys are not a workaround: `tauri-build` reads the
config with unknown fields denied, so `cargo check` fails with ``unknown field
`//` `` before any Rust compiles (it did, on the first-ever build). The reasons
behind the config live in `deliverer/CLAUDE.md` and in this skill: CSP below,
`bundle.resources` under Sidecar, the updater key in `cut-release`, and
`bundle.targets` stays `all` for local builds while CI passes `--bundles` per OS.

## CSP - the config that blanks the gallery

Once `app.security.csp` is set, loopback is blocked unless listed; the port is
ephemeral, so both `connect-src` and `img-src` carry `http://127.0.0.1:*`
(`connect-src` also `ipc: http://ipc.localhost`). A blank gallery with no
console error after a CSP edit is this.

## Updater

`plugins.updater.pubkey` = `REPLACE_WITH_PUBLIC_KEY` and the endpoint contains
`luissebastian953` until the one-time setup in `cut-release` is done; until
then an update check errors and `stores/updater.ts` shows phase `error`,
which is expected in dev. `bundle.createUpdaterArtifacts: true` and `tauri-action` produce
`latest.json`. Version source of truth is `tauri.conf.json` - change it only
via `scripts/bump-version.sh`.

## Dev and build on the host

`pnpm tauri dev` (from the root) needs Rust stable ≥ 1.77 and, on macOS, the
Xcode Command Line Tools; on Linux the webkit2gtk-4.1 deps from
`release.yml`. Icons are not needed for `dev`, only `build`
(`pnpm tauri icon src-tauri/app-icon.svg` from `deliverer/`). Neither works from a
sandboxed shell without a display.

## Before commit

```
cd deliverer/src-tauri && cargo fmt && cargo clippy -- -D warnings
```

**Tray + mini window (2026-10-25, macOS arm64):** `cargo clippy -D warnings`
passes with `tray-icon` + `image-png`; `default_window_icon()` returns a
borrowed `Image`, so `.map(|i| i.to_owned())` for a `'static` one.

**First compile (2026-10-13, macOS arm64):** `cargo check`, `cargo fmt` and
`cargo clippy -- -D warnings` pass; `Cargo.lock` is committed (an app pins its
dependencies). The one blocker was `"//"` comment keys in `tauri.conf.json`
(see above). Linux and Windows are first compiled by the release workflow.
After a Rust change: `pnpm tauri dev` must print the handshake, the gallery
must show images (CSP), and closing the window must leave no `dawnmaker`
process (`pgrep -f dawnmaker`). Never paper over a warning with `#[allow]`.
