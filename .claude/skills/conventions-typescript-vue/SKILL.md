---
name: conventions-typescript-vue
description: Conventions for deliverer/ (Vue 3 + TS + Pinia + Tailwind v4 + vue-i18n + Vitest) — auto-imports, styling tokens, i18n, lint/format, tests, and the checklist for adding a page or component.
---

# TypeScript / Vue conventions — `deliverer/`

Vue 3 + Vite, not Nuxt. `<script setup lang="ts">` in every SFC. TS `strict`
plus `noUncheckedIndexedAccess` (`tsconfig.json`): `arr[0]` is `T | undefined`,
so destructure with `!` only when the regex/shape guarantees it, else guard.

## Definition of done

```
pnpm check     # vue-tsc --noEmit && eslint . && prettier --check . && i18n-check && vitest run
pnpm build     # vue-tsc + vite build — run it too; check does not bundle
pnpm format && pnpm lint:fix     # the fixers, in this order
```

Run from `deliverer/` or with `pnpm --filter deliverer <script>` at the root.
`pnpm install` only ever runs at the repo root (workspace).

## Auto-imports — do not write the everyday imports

`unplugin-auto-import` provides `vue`, `vue-router`, `pinia`, `vue-i18n` and
every export of `src/stores/` and `src/lib/` (`useJobs`, `api`, `mediaUrl`,
`subscribe`, …). `unplugin-vue-components` registers `src/components/*.vue`
and Reka UI (`DialogRoot`, `SliderRoot`, …). So: never `import { ref } from
'vue'`; never import a store or a sibling component. DO write
`import type { Job } from '@/lib/types'` — types are not auto-imported — and
imports from packages outside that list (`@tauri-apps/plugin-*`,
`@vue/test-utils`). The generated `src/auto-imports.d.ts`,
`src/components.d.ts`, `.eslintrc-auto-import.json` are committed; a new
export shows up there after the next `dev`/`build`/`vitest` run.

## Stores — Pinia option syntax

`defineStore('name', { state: () => ({...}), getters: {...}, actions: {...} })`
— see `stores/sources.ts`. Stores decide desktop vs browser at creation
(`'__TAURI_INTERNALS__' in window`). The daemon is reached only through
`lib/api.ts` (`api.get/post/put/patch/delete`, `mediaUrl`, `subscribe`,
`startHeartbeat`); it is the only file that knows the daemon URL or token.
`?token=` rides on `<img src>` and `EventSource` URLs only (`mediaUrl`,
`authedUrl`, `subscribe`). Theme state is localStorage only.

## Styling — Tailwind v4, CSS-first (`src/styles.css`)

- No `tailwind.config.js`; the `@theme` block is the config. No default
  palette: `text-gray-500`, `text-sm`, `p-4`, `gap-2`, `rounded-lg` do not exist.
- Spacing is a px ladder: `0 3 5 10 15 20 25 30 35 40 45 50 60 70 80 90 100
  150 200 250 300 400 500` → `p-15` is 15px. Arbitrary `p-[13px]` when needed.
- Type ramp: `text-xsmall small base medium extra ultra` (10/12/14/18/24/36).
- Colours: `bg/text/border-{bg,rail,surf,surf2,line,line-soft,tx,mut,dim,
  ember,cyan,moss,rose}`. Ember is the one accent; cyan only for the
  cross-source link; moss = ok; rose = error.
- Utilities: `cut` (clip-path corners; `cut-sm`/`cut-lg`/`cut-tr`), `scan`,
  `data` (mono tabular), `container`, `h-custom-screen`.
- Component classes in `@layer components`: `.btn` (`.pri .gh .on .sm
  .danger`), `.panel` (`.poly .scan`), `.chip` (`.on .off .err`), `.phead`,
  `.ptitle`, `.field`, `.bar`, `.rk-*`. Panels are square (`--radius-*` reset;
  only `rounded-chip` = 2px); buttons and chips are cut top-right + bottom-left.
- Reka UI for behaviour only (focus, keyboard, aria); skin with `.rk-*`.
  Never install shadcn-vue. `.jp` switches to Noto Sans JP for Japanese text.

## i18n — every string is a key

`src/locales/en/<ns>.json`, namespaces = `app auth character crawl gallery
pipeline settings updates`; key = `ns.section.name`. `$t('…')` in templates,
`const { t } = useI18n()` in script, `:placeholder="$t(…)"` for attributes,
`<i18n-t keypath tag>` with slots for rich text, plurals `'none | one | {n}
many'` with a count. Never name a loop variable `t`. Data (tags, artist
names, ids, `PHPSESSID`, daemon error strings) is not translated. Add the
`en` key first; `pnpm i18n:check` fails on unresolved keys and literal prose
in templates. Details: the `i18n-locale` skill.

## Lint and format

ESLint 9 flat config (`eslint.config.js`): Vue recommended + typescript-eslint
recommended + `eslint-config-prettier`; `vue/no-v-html` is an error; unused
bindings must start with `_`. `@stylistic/padding-line-between-statements`
demands blank lines after the import block and around functions, multi-line
`const`, multi-line expressions (`watch()`, `onMounted()`), types and exports.
Prettier: 110 cols, single quotes in TS, double quotes in HTML attributes,
trailing commas, `htmlWhitespaceSensitivity: ignore` (so line breaks inside
inline elements are safe, including around CJK).

## Tests — Vitest + @vue/test-utils + happy-dom

`src/**/*.test.ts` next to the file under test; `globals: true`
(`describe/it/expect/vi` need no import). `src/test/setup.ts` gives a fresh
Pinia and resets localStorage/`<html>`/Tauri flag after each test.
`mountWithPlugins(Component, { props, pinia: { stubActions, initialState } })`
from `src/test/utils.ts` mounts with a testing Pinia and the real `i18n`, so
assert on the English text the user sees. `setTauri(true)` BEFORE the first
`useX()`. Never contact the daemon: `vi.mock('@/lib/api', async (orig) => ({
...(await orig()), api: { get: vi.fn(), post: vi.fn() } }))` then
`vi.mocked(api.get).mockResolvedValueOnce(...)`; assert on paths and bodies.
Tauri plugins are `vi.mock`ed by package name. Test behaviour — getter
answers, request paths/bodies, rendered text and buttons, emitted events —
not markup: no snapshots, no CSS assertions. A literal `t('ns.key')` in a test
counts as a key reference for `i18n-check`; probe a missing key via a variable.

## Adding a page or component — checklist

1. `src/pages/Name.vue` + a route in `src/router.ts` (hash history, lazy
   `() => import('@/pages/Name.vue')`), or `src/components/Name.vue`
   (auto-registered — no import at the use site).
2. `src/locales/en/<ns>.json`: a new namespace for a new page, or keys in the
   owning component's namespace. Every visible string, including attributes.
3. Store in `src/stores/<name>.ts` (option syntax) if it holds state shared
   across pages; API shapes in `src/lib/types.ts` matching `dawnmaker/app.py`.
4. `Name.test.ts` beside it: mount with `mountWithPlugins`, mock `@/lib/api`,
   assert text/buttons/calls.
5. `deliverer/CLAUDE.md` tree: add the file to `pages/ components/ stores/`.
6. `pnpm check && pnpm build` green; `CHANGELOG.md` `## Unreleased` line;
   commit `feat(deliverer): …`.
