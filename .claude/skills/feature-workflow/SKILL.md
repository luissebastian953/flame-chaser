---
name: feature-workflow
description: Adding or changing a feature in Curio: the ordered checklist of everything that must move together (design, engine, daemon, types, UI, i18n, tests, docs, changelog). Read first for any feature.
---

# Feature workflow — what moves together

Read this before any "add / change / remove <feature>" request. A feature in
Curio crosses four layers (`coreflame` → `dawnmaker` → `lib/api.ts` +
`lib/types.ts` → store → page/component) and three kinds of documentation.
Do the steps in this order; each one makes the next mechanical.

## 0. Decide the shape before writing code

- Which layer owns the behaviour? Policy and data → `coreflame`. HTTP shape →
  `dawnmaker`. Presentation and interaction → `deliverer`. Rust only if the
  webview physically cannot (files, cookies, process). Never invert
  `dawnmaker imports coreflame`.
- Does it touch a **load-bearing decision** (root `CLAUDE.md`, "The decisions
  that are load-bearing")? Load-bearing = anything about: the visited gate
  and its four states, pixiv-discovers/X-follows, two-level dedupe scope,
  monotonic watermarks, `Referer`, `verify=False`, loopback-only media,
  thumbnails at ingest, db location, one worker thread, retry policy,
  handshake-over-stdout, `bundle.resources`, capabilities for remote windows.
  If yes: say so, explain the trade-off, and stop for a decision. Do not
  quietly change it.
- Does the schema, API contract or config-file format change? Then it is a
  **breaking** change and needs a migration (below) and `!` in the commit.

## 1. Design note

`docs/design/architecture.md` is the reference. Add or amend the section
the feature belongs to (§4 jobs, §4b visited set, §5 pages, §6 API contract,
§8 failure modes). If a runtime flow changed (job stages, auth, update
install), draw it as a mermaid block; `docs/flows.md` does not exist yet —
create it on first need and link it from architecture.md. One paragraph of
"why" beats a page of "what".

## 2. Engine — `reaver/coreflame/` with tests

Function(s) that take a `Store`; pydantic models `extra="forbid"`, ids `str`,
UTC datetimes; `ctx.check()` in loops; honest `total`. Test offline in the
matching `reaver/tests/test_*.py` (fake adapters from `test_smoke.py`).
Conventions: `conventions-python`.

## 3. Daemon route — `reaver/dawnmaker/app.py` with test

`XIn` model → route with `Depends(store)` → `HTTPException(code, {code,
message})` → test in `tests/test_dawnmaker.py` via `TestClient`. Update §6 of
architecture.md. `cd reaver && ./check.sh`.

## 4. `deliverer/src/lib/types.ts`

Mirror the new/changed response and body shapes. This is the only contract
the webview has; a field renamed in Python and not here is a runtime
`undefined`, not a type error.

## 5. Store — `deliverer/src/stores/<name>.ts`

Option syntax; call `api.*` from actions; keep desktop/browser branching in
state creation. Test: `<name>.test.ts` mocking `@/lib/api`.

## 6. Component / page + i18n + test

Template with `$t('ns.key')` only; keys added to `src/locales/en/<ns>.json`
FIRST (`i18n-locale`); `Name.test.ts` with `mountWithPlugins`; route in
`router.ts` for a page. Conventions: `conventions-typescript-vue`.
Rust needed? `conventions-rust-tauri`, and register the command.

## 7. Instructions and skills

- `CLAUDE.md` (root / `deliverer/` / `reaver/`): update the directory tree
  when a file was added; add or reword a rule only when a load-bearing
  decision changed. Remove what became false.
- Skills: if the feature introduces a repeatable procedure (a new kind of
  source, a new deploy step, a new check), it gets a `SKILL.md` under
  `.claude/skills/<name>/` (frontmatter `name`, `description`; 60–120 lines;
  commands, paths, order, done-criteria, traps). If it changes an existing
  procedure, update that skill in the same commit. Add new skills to the
  index in root `CLAUDE.md`.
- `README.md`: the repo root has none yet; `reaver/README.md` exists. Touch a
  README only when user-facing setup (install, first run, env vars) changed.

## 8. `CHANGELOG.md` → `## Unreleased`

One line per user-visible change, `Added:` / `Changed:` / `Fixed:` /
`Removed:`, written for the person using the app (Settings › Updates renders
it). Internal refactors get no line. `bump-version.sh` promotes the section.

## 9. Check, then commit

```
pnpm check            # deliverer check → reaver/check.sh → check-version
```

Green, then the `commit` skill: `feat(scope): subject`, body = why,
`BREAKING CHANGE:` footer when step 0 said so.

## When a change needs a migration

Any change to a table, column, index or the meaning of stored values.
`coreflame/migrations.py`: register a DDL-only step with
`@migration(<next int version>, "name")` on a function returning the SQL
(`;`-separated, no `;` inside strings); forward-only (no down migration
exists); `apply()` backs up the db file first and runs each step in its own
transaction, stamping the row with the current app version as
`min_app_version` so an older daemon refuses the db instead of half-reading
it. Existing raw payloads are re-parsed via `store.raws_for()`
if the spec changed — never re-fetched. Mention the migration in the
CHANGELOG line and in `cut-release` step 2 when the release is cut.

## Done means

Every layer the feature touches has a test; `pnpm check` green; types,
docs, CLAUDE.md tree, skills and CHANGELOG updated in the same commit; the
commit message names the scope and, if breaking, says what an existing
install must do.
