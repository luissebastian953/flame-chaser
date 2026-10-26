---
name: i18n-locale
description: Add or update a language, translate a component, or add/rename a UI key in Curio's vue-i18n setup (deliverer/src/locales, i18n.ts, i18n-check). Use for any user-visible string work.
---

# i18n - keys, components, languages

vue-i18n 11, composition API, configured in `deliverer/src/i18n.ts`. English
is complete and the fallback; every other locale may be partial - a missing
key falls back to English silently in production and warns in dev.

## Layout and naming

```
deliverer/src/locales/<locale>/<namespace>.json
namespaces: app auth character crawl gallery pipeline settings updates
key = '<namespace>.<section>.<name>'     e.g. settings.theme.background
```

One file per page or component; the file name is the key prefix (glob in
`i18n.ts`, eager). Keys are camelCase, nested by UI section, short - the key
names the slot, not the sentence (`auth.source.signIn`, not
`auth.source.clickHereToSignIn`).

## Using a key

- Template: `{{ $t('gallery.aside.untitled') }}`; attributes are bound:
  `:placeholder="$t('character.tags.placeholder')"`, same for `title`,
  `aria-label`, `alt`.
- Script: `const { t } = useI18n()` (auto-imported), then `t('…')`. Never
  name a loop or callback variable `t` - it shadows the translator; use
  `tag`, `term`, `tb`.
- Interpolation: `"ready": "{version} ready"` → `$t('updates.banner.ready',
  { version })`.
- Plurals: `"postCount": "0 posts | 1 post | {n} posts"` (zero | one | many)
  → `t('gallery.gallery.postCount', n)` - a number as the second argument
  selects the form and fills `{n}` (`Gallery.vue`); with named args use
  `t(key, { n }, n)`.
- Rich text (bold, links, nested components):
  ```vue
  <i18n-t keypath="auth.source.browserModeLead" tag="span">
    <template #signIn><b>{{ $t('auth.source.signIn') }}</b></template>
  </i18n-t>
  ```
  with `"browserModeLead": "In the Curio desktop app, {signIn} opens …"`
  (`auth.json`, `SourceCard.vue`). Never build a
  sentence from concatenated fragments - word order differs per language.
- Not translated (it is data, not prose): tag text, artist names, job type
  ids, daemon error `code`s and messages, identifiers such as `PHPSESSID`,
  `auth_token`, example ids, file paths.

## Adding a key

1. Add it to `src/locales/en/<ns>.json` first, in the section it belongs to.
2. Use it (`$t` / `t()` / `keypath`).
3. `pnpm --filter deliverer i18n:check` - part of `pnpm check`. It fails on a
   `t('…')` whose key does not resolve in `en` and on literal prose left in
   a template (text nodes and `placeholder/title/aria-label/alt`); it warns
   on `en` keys nothing references statically. A dynamic key
   ``t(`pipeline.state.${job.state}`)`` counts every child of the prefix as
   used (`SourceCard.vue` does this for `auth.source.${source}.name`); any
   other dynamic construction shows up as a false "unused" warning.

## Renaming or removing a key

Change `en`, every other locale that has it, and every use (`grep -rn
"old.key" deliverer/src`). `i18n:check` catches a use pointing at the old
name; the unused warning catches a locale key left behind. Tests that
reference the key by literal string need updating too.

## Translating a component

Copy that component's namespace file from `en/` into `<locale>/` and
translate value by value; keep every key, every `{placeholder}` name and the
`|` plural slots (a language with one plural form still needs all slots
present - repeat the form). Leave data alone. Partial files are fine.

## Adding a language

Planned order and codes (`LOCALES` in `src/i18n.ts`): `ja` 日本語 first -
the source material is Japanese; shipped 2026-10-16, complete - then `id`
Bahasa Indonesia, `zh` 中文, `fil` Filipino. Steps:

1. `cp -r src/locales/en src/locales/<code>` and translate file by file.
2. Flip `ready: true` on that entry in `LOCALES` (`native` + `label`
   already present; a new code needs a new entry - `LocaleCode` derives
   from the array). Until then the language shows as "coming soon" in
   Settings › Language, and `coverage()` reports its key count there -
   partial folders are visible progress, not hidden.
3. `src/i18n.test.ts` asserts which locales are `ready` (`['en', 'ja']`
   today) and that `ja` has 0 pending keys: update those expectations, and
   add the same full-coverage assertion for the new locale once it is
   complete. `LanguagePanel.test.ts` checks row order and which rows are
   disabled. The test also loads every `en` namespace and checks
   interpolation, so keep `en` complete.
4. The stored choice (`curio.locale`) is a code or `'system'` (default =
   follow `navigator.language`); `setLocale()` resolves it and falls back
   to `en` while the wanted locale is not `ready`, keeping the wish
   stored so it takes effect the day the language ships.
   `src/components/LanguagePanel.vue` is the UI (list, follow-system,
   coverage bars, and the Formats block backed by `stores/formats.ts` -
   region/date/time/size are separate from the language on purpose).
5. Check layouts in the browser at 960 px width - chips, buttons and the
   rail wrap differently in longer languages.

## CJK notes

- Chakra Petch has no CJK glyphs; `--font-sans` falls back to Noto Sans JP
  Variable (bundled via `@fontsource-variable/noto-sans-jp`, unicode-range
  subsets). Put `class="jp"` on elements that are mostly Japanese text
  (titles, tag inputs) to use `--font-jp` directly.
- Prettier runs with `htmlWhitespaceSensitivity: ignore`, so a line break
  inside an inline element never inserts a space - safe for CJK, but it
  also means you cannot rely on a newline to separate two Latin words.
- Fullwidth vs halfwidth parentheses in tag text are data; never normalise
  them in the UI (the engine keeps `tag_raw` for that reason).

## Done means

`pnpm i18n:check` clean (no errors; only expected dynamic-key warnings),
`vitest run` green including `i18n.test.ts`, no literal prose in the diff,
and the new/changed keys exist in `en` plus every locale you touched.
