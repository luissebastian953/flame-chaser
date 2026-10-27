# deliverer - Tauri v2 shell + Vue 3 webview

```
deliverer/
├── src/                  Vue 3 + Vite (NOT Nuxt - see below)
│   ├── main.ts           createApp + pinia + router + i18n; bundled fonts
│   ├── App.vue           rail (BrandMark, UpdateBanner, NetworkCard), AuthGate, theme apply, ImageViewer, ShutdownConfirm and NetworkDetail over everything; useBackgroundController()
│   ├── router.ts         hash history; routes → pages/ (hand-written, lazy)
│   ├── i18n.ts (+ .test.ts)   LOCALES, glob-loaded messages, setLocale
│   ├── pages/            Gallery* · CharacterDetail* · Config* · PipelineList* · PipelineDetail* · Settings
│   ├── components/       AuthBadge* · AuthGate · BackupPanel* · BrandMark · DeleteMenu · DeleteSheet · DeleteToast* · DetailAside* · EmberField · GalleryTile* · GenderFilter* · Icon* · ImageViewer* ·
│   │                     InfoTip* · LabelFilter* · NetworkCard* · NetworkDetail* · NotificationsPanel* · QueuedPanel · RateBudget · RunToast* · RunToasts* · SelectionBar · ShutdownConfirm* · SignalBars ·
│   │                     SmartPanel · SourceCard* · StatCard* · StoragePanel* · ThemePanel* · ThemePreview · UpdateBanner* · UpdatesPanel · WatchForm* · WorkerAvatar   (* = has a .test.ts)
│   ├── stores/           background* · characterDefaults* · deletion* · endpoint · jobs* · library* · network* · sources* · theme* · toasts* · updater* · viewer*  (Pinia)
│   ├── lib/api.ts (+ .test.ts)   endpoint discovery, fetch wrapper, mediaUrl, EventSource
│   ├── lib/types.ts      the API shapes - keep in step with dawnmaker/app.py
│   ├── lib/related.ts (+ .test.ts)   the related set a post detail walks: its pages, then the linked post's images
│   ├── lib/labels.ts · lib/artists.ts   the label values and their i18n leaves; the `source:artist_id` key
│   ├── lib/shell.ts      openExternal (default browser) · revealInFolder (Finder / Explorer; desktop only)
│   ├── lib/pipeline.ts (+ .test.ts)   what the pipeline screens derive from a job: stages, character, counters, worker colour
│   ├── lib/netchart.ts (+ .test.ts)   the network modal's chart maths: 30 samples → smoothed line + area paths
│   ├── lib/uiState.ts (+ .test.ts)    every `curio.*` localStorage key as one object: what a backup carries and an import writes back
│   ├── lib/background.ts (+ .test.ts)   the background controller: mini window ticks, tray tooltip/menu, the one notification of notifications mode
│   ├── pip/              the mini window's own page (pip.html → main.ts · render.ts* · protocol.ts · pip.css): no Vue, no store, fed by `pipeline:tick` events
│   ├── lib/icons.ts (+ .test.ts)   the icon set's lookup; the test checks every name a template uses
│   ├── assets/icons/icons.json   the Curio icon set, verbatim from curio-icons.zip (86 line icons + refresh-plus + wifi-off)
│   ├── locales/en/       app auth character crawl gallery pip pipeline settings updates .json
│   ├── test/             Vitest setup.ts + utils.ts (mountWithPlugins, setTauri) + network.ts (the speed fixture)
│   ├── styles.css        Tailwind v4 entry: @theme tokens + @utility + component classes
│   └── auto-imports.d.ts · components.d.ts · globals.d.ts   generated / ambient types
├── scripts/build-sidecar.sh    PyInstaller --onedir → resources, + leaf signing
├── scripts/sidecar_entry.py    PyInstaller's entry: imports dawnmaker as a package (its __main__ is relative); `--gallery-dl …` runs gallery_dl instead (the app's gallery-dl)
├── scripts/i18n-check.mjs      keys resolve, no literal prose (part of `check`)
├── index.html · pip.html       the two Vite entries (the app, the mini window)
├── eslint.config.js · .prettierrc · .eslintrc-auto-import.json · tsconfig.json · vite.config.ts
├── .env.example                VITE_DAEMON_URL / VITE_DAEMON_TOKEN for browser-only dev
└── src-tauri/
    ├── tauri.conf.json         CSP + bundle.resources + updater (version source of truth)
    ├── capabilities/default.json   permissions for window `main`; pip.json for the mini window (events + drag only)
    ├── Cargo.toml · Cargo.lock · build.rs   crate `deliverer`, lib `deliverer_lib`; the lock is committed
    ├── resources/sidecar/      build output, gitignored
    ├── app-icon.svg            the app icon's source (the Curio mark, as components/BrandMark.vue, on the background)
    ├── icons/                  `pnpm tauri icon src-tauri/app-icon.svg` - needed for build, not dev; tray.png = the mark as a 44px monochrome template (macOS menu bar)
    └── src/{main.rs,lib.rs,sidecar.rs,auth.rs,pip.rs,tray.rs}   auth.rs = source_login window · pip.rs = the mini window (open/close/resize/snap) · tray.rs = tray icon + menu
```

Conventions in depth: `.claude/skills/conventions-typescript-vue`,
`conventions-rust-tauri`, `i18n-locale`.

## Definition of done

```
pnpm check         # vue-tsc --noEmit && eslint . && prettier --check . && i18n-check && vitest run
pnpm test          # vitest run (also the last step of `check`); `pnpm test:watch` while working
pnpm build         # vue-tsc + vite build
pnpm lint:fix      # eslint --fix (attribute order, unused imports, ...)
pnpm format        # prettier --write (110 cols, single quotes in TS, double in HTML attributes, trailing commas)
pnpm i18n:check    # node scripts/i18n-check.mjs (also inside `check`)
```

At the repo root `pnpm check` runs this `check`, then `reaver/check.sh`,
then `scripts/check-version.sh` - that is the real definition of done.

(pnpm workspace: `pnpm install` runs at the repo root, not here.)

ESLint (flat config, `eslint.config.js`) is Vue 3 + typescript-eslint
recommended with Prettier's rules disabled: ESLint reports what is wrong,
Prettier decides how it looks. Run `format` then `lint:fix` before `check`;
CI runs `check` and fails on either. Attribute order in templates follows
`vue/attributes-order` (v-if/v-for → ref/key → v-model → props → events).

`pnpm tauri dev` needs Rust on the host (not in a sandboxed shell). In the
browser alone, `pnpm dev` works against a hand-started daemon:
`python -m dawnmaker --no-heartbeat --dev`, then copy `.env.example` → `.env`
with the handshake's port and token.

## Tests - Vitest, happy-dom, behaviour not markup

`vitest run` picks up `src/**/*.test.ts`, next to the file under test
(`stores/theme.test.ts`, `components/SourceCard.test.ts`, `i18n.test.ts`).
The `test` block in `vite.config.ts` runs through the same Vite plugins as
the app, so auto-imports (`useTheme`, `api`, `defineStore`, …), the `@/`
alias, `import.meta.glob` and the `__APP_VERSION__` defines all work in a
test with no extra wiring; `globals: true` provides `describe/it/expect/vi`
(typed via `vitest/globals` in tsconfig, known to ESLint via `globals.vitest`).

- `src/test/setup.ts` runs before every file: a fresh Pinia per test, and
  after each test localStorage, `<html>` style/class, stubbed globals/env and
  the Tauri flag are reset.
- `src/test/utils.ts`: `mountWithPlugins(Component, { props, pinia })` wraps
  `@vue/test-utils` `mount` with `createTestingPinia` (real actions unless
  `pinia: { stubActions: true }`; seed stores with `pinia.initialState`) and
  the real `i18n`, so assertions read the English strings the user sees.
  `setTauri(true|false)` toggles `window.__TAURI_INTERNALS__` - call it
  BEFORE the first `useX()`, since stores decide desktop/browser at creation.
- The daemon is never contacted: mock the wrapper, not `fetch` -
  `vi.mock('@/lib/api', async (orig) => ({ ...(await orig()), api: { get: vi.fn(), … } }))`
  then `vi.mocked(api.get).mockResolvedValueOnce(...)` and assert on paths
  and bodies. Only `lib/api.test.ts` stubs `fetch` itself. Tauri plugins are
  `vi.mock`ed by package name.
- Test behaviour, not markup: what a getter answers, what URL/body an action
  sends, what text/buttons a state renders, what a click calls or emits.
  No snapshots, no CSS assertions. A literal `t('ns.key')` in a test counts
  as a key reference for `i18n-check`, so probe missing keys via a variable.

## Localisation - every string is a key

vue-i18n 11, composition API. `src/locales/<locale>/<namespace>.json`, one
file per page or component (`app auth character crawl gallery pipeline
settings updates`), loaded by glob in `src/i18n.ts`; the file name is the key
prefix: `$t('settings.theme.background')`. English is complete and the
fallback; other locales (`ja id zh fil`, listed in `LOCALES`) may be partial
and are enabled per locale with `ready: true` once they exist. Rules:

- No literal user-visible text in a template or in script-assigned UI text.
  `$t()` in templates, `const { t } = useI18n()` in script (auto-imported);
  attributes are bound (`:placeholder="$t(...)"`); rich text uses `<i18n-t>`
  with slots. Interpolate with `{name}`; plurals with `|` and a count.
- Add the English key first, then use it. `pnpm i18n:check` (part of
  `check`) fails on a key that does not resolve or on leftover literal prose,
  and warns on unreferenced keys.
- Data stays data: tag text, artist names, job types, daemon error strings
  and identifiers like `PHPSESSID` are not translated.
- A template loop variable named `t` shadows the translator - use `tag`,
  `term`, `tb`.

## Auto-imports - no import lines for the everyday things

`unplugin-auto-import` provides the `vue`, `vue-router`, `pinia` and `vue-i18n` APIs plus
every export of `src/stores/` and `src/lib/` (`useTheme`, `api`, `authedUrl`,
…) without an import statement; `unplugin-vue-components` does the same for
`src/components/*.vue` and Reka UI components (`SliderRoot`, `SwitchRoot`, …).
`src/auto-imports.d.ts`, `src/components.d.ts` and `.eslintrc-auto-import.json`
are generated on every dev/build run and committed, so vue-tsc, the editor and
ESLint all agree. Still written by hand: `import type { … }` (types are not
auto-imported), and anything from a package outside that list.

## Styling - Tailwind v4 + Reka UI, "cyber build"

- **Tailwind v4, CSS-first.** There is no `tailwind.config.js`; the theme is
  the `@theme` block in `src/styles.css`. Every token is both a CSS variable
  and a utility family. Do not add a JS config - v3 syntax silently does
  nothing under v4.
- **Spacing is a fixed px ladder** (`0 3 5 10 15 20 25 30 35 40 45 50 60 70
80 90 100 150 200 250 300 400 500`). `p-15` = 15px. `p-4`, `w-64`, `gap-2`
  do not exist - reach for the nearest step or an arbitrary value `p-[13px]`.
- **Type ramp** is `text-xsmall small base medium extra ultra` (10/12/14/18/
  24/36 with line-heights baked in). `text-sm`/`text-lg` do not exist.
- **Colors**: `bg/text/border-{bg,rail,surf,surf2,line,line-soft,tx,mut,dim,
ember,cyan,moss,rose}`. Ember is the one accent (magenta, hue 332); cyan is
  reserved for the cross-source link; moss = ok, rose = error. No Tailwind
  default palette - `text-gray-500` does not exist on purpose.
- **Signature utilities**: `cut` (clip-path corners, `--cut` overridable,
  `cut-sm`/`cut-lg`/`cut-tr`), `scan` (scanline overlay), `data` (mono
  tabular readout), `container` (centred, 10px padding, 100% ≤md, 1024 lg,
  1120 xl), `h-custom-screen` (100dvh).
- **Component classes** (`.btn .panel .chip .phead .ptitle .field .bar
.rk-*`) live in `@layer components` and are plain CSS on the same
  variables. Mix freely: `class="btn pri mt-10"`. Templates may still use
  `var(--ember)` - `:root` aliases the short names to `--color-*`.
- **Reka UI for behaviour, never for looks.** Use Reka for Dialog, Select,
  Slider, Switch, Checkbox, Tooltip, Popover - the focus/keyboard/aria parts.
  Skin them with the `.rk-*` classes. Do NOT install shadcn-vue: its
  pre-styled rounded components fight the cut-corner design.
- **Theme at runtime** (`stores/theme.ts`): a theme is five colours
  (primary, accent, canvas, surface) and three finishes (corners, glow,
  scanlines); `cssVars()` turns it into `--color-*`, `--glow`, `--scan-alpha`,
  `--window-alpha`, `--plate-*`, `--grid-alpha`, and `cssClasses()` into
  `corners-cut` / `corners-round` / `no-scan` on `<html>`. Settings › Theme
  edits a **draft** that only the Live preview (`ThemePreview`, the draft's
  variables scoped to its root) shows; Apply promotes it. Built-in presets +
  user presets and the theme live in localStorage only - the daemon never
  sees theme state. `useTheme().apply()` runs in `App.vue` setup, before
  first paint. The window is `transparent: true` (tauri.conf.json): the
  canvas paints its own alpha, so at `--window-alpha: 1` nothing shows
  through; "Blur background" is the OS effect via `setEffects`.
- Square by default: `--radius-*` is reset; only `rounded-chip` (2px) exists.

## Source sign-in

Curio never sees a password. `source_login` (auth.rs) opens the site's own
login page in a second window (label `source-login`, deliberately absent from
capabilities so remote content has no IPC), polls `cookies_for_url` until the
session cookie exists (`PHPSESSID`; `auth_token`+`ct0`), closes the window and
returns the cookie to the webview, which POSTs it to `/api/auth/<source>`.
The cookie is never kept in the webview or localStorage. Outside Tauri
(browser-mode Docker) `SourceCard` unfolds a paste form instead. The
first-launch `AuthGate` shows while nothing is connected; "Browse offline"
dismisses it per install (localStorage) and Settings › Accounts is the
permanent home.

## Rules specific to this package

- **Vue 3 + Vite, not Nuxt.** SSR, server routes and SEO are all irrelevant in a
  webview; `vue-router` with the hand-written table in `src/router.ts` is
  the only part worth having.
- **Sidecar lifecycle is three layers and all three are required:**
  managed `CommandChild` killed on `ExitRequested` _and_ `WindowEvent::Destroyed`;
  a daemon-side heartbeat timeout (covers `kill -9` and Rust panics, which the
  first layer cannot - the beats come from a thread in `sidecar.rs`, never from
  the webview, whose timers WebKit throttles when the window is hidden); a
  lockfile so a second daemon never races the first over the same SQLite
  file (the second reports `already_running`; `spawn` stops an orphaned
  holder and retries, and fails the launch when the holder's Curio is alive). Do not use parent-PID polling -
  `getppid()` is meaningless on Windows.
- **CSP silently breaks loopback.** It is off until set; once set, `fetch` and
  `<img src>` to 127.0.0.1 fail with no useful error and the gallery just goes
  blank. The port is ephemeral, so the policy wildcards it:
  `http://127.0.0.1:*` in both `connect-src` and `img-src`.
- **`bundle.resources`, never `externalBin`.** `externalBin` takes one file per
  target triple, forcing PyInstaller `--onefile` - which re-extracts the whole
  runtime on every launch and which the NSIS installer is known not to replace
  on update.
- **Tauri's fs scope does not sandbox the sidecar.** It constrains the webview
  and Rust only. What applies on macOS is TCC, and a denial reaches Python as a
  bare `PermissionError` it cannot re-prompt from - so default the library
  folder outside `~/Documents`, `~/Desktop`, `~/Downloads`.
- **Dev spawns `python -m dawnmaker` from the venv** when `cfg!(debug_assertions)`,
  so a Python edit costs a restart rather than a PyInstaller rebuild. Same
  handshake line either way.
- **Keyset pagination** on the character grid, never offset - a crawl inserting
  rows while the user scrolls makes offset duplicate and skip. Cursors are
  opaque strings from the daemon; never parse or construct them here.
- **`lib/api.ts` is the only file that knows the daemon's address or token.**
  `<img src>` and `EventSource` cannot set headers, so `mediaUrl()`,
  `authedUrl()` and `subscribe()` append `?token=` - the daemon accepts that
  on `/api/events`, `/api/media/*` and `/api/preview/*` only.
- **Hash history.** The webview loads `index.html` from a bundled path; there
  is no server to rewrite deep links.
- Rust: `lib.rs` holds the app (`run()`), `main.rs` only calls it - the Tauri v2
  convention that keeps a mobile target possible later.

## Background mode - mini window, tray, notifications

`lib/background.ts` (`useBackgroundController()`, run once from `App.vue`,
desktop only) owns what Curio does while it crawls and another app is in
front; `stores/background.ts` is the persisted choice (Settings ›
Notifications). The **mini window** is a second Tauri window (label `pip`,
`pip.html` → `src/pip/`, no Vue) that the controller asks the shell for
(`pip_open`) 1.5 s after the main window blurs with a worker running, feeds
with a `PipTick` (`src/pip/protocol.ts`) at most twice a second, and
**closes** (never hides - a hidden WebView keeps its memory) when the main
window is focused, × is pressed, or 2 s after the queue empties. The mini
window has no token and never fetches: everything it shows arrives in the
tick, and every click goes back as a `pip:*` event. Its capability
(`capabilities/pip.json`) grants events and drag only; the app's own `pip_*`
commands need no ACL entry. Placement is drag-and-snap in Rust (`pip_snap`:
the nearer horizontal edge of the monitor it is on, animated unless reduced
motion), persisted as side + height. The tray (`tray.rs`) is built in Rust;
its labels come from the webview (`tray_update`) so they follow the
language. Notifications mode sends exactly one OS notification per
finished crawl (`finishedNotice`) and nothing else. On Linux Wayland
(`pip_supported` → `wayland`) the floating window is impossible, the store
coerces a saved `mini` to `notify` and the panel says so.

## Updates

The sidecar ships inside the bundle, so one signed artifact updates shell and
daemon together. Download whenever; **install only when the job queue is idle**.
See `.claude/skills/cut-release/SKILL.md`.
