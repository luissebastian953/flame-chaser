---
name: commit
description: Commit work in flame-chaser - run tests, typecheck, lint and format, then write a Conventional Commit. Use before any git commit, when a hook rejects a message, or when asked to "commit this".
---

# Commit work in flame-chaser

One git repo at the root covers `reaver/`, `deliverer/`, docker, docs and
skills. No nested repos. JavaScript tooling is a pnpm workspace: `pnpm install`
at the root, never `npm install` (a `package-lock.json` anywhere is a bug).

## First time only - there is no `.git` yet

```
git init -b master && pnpm install && pnpm prepare   # prepare installs the husky hooks
```

Without `pnpm prepare` the hooks below do not run and nothing stops a bad message.

## 1. Green first: `pnpm check` at the root

```
pnpm check
```

runs, in order, and stops at the first failure:

1. `pnpm --filter deliverer run check` = `vue-tsc --noEmit && eslint . &&
   prettier --check . && node scripts/i18n-check.mjs && vitest run`
2. `reaver/check.sh` = `ruff check` + `ruff format --check` + `mypy` + every
   `tests/test_*.py` with plain `python3` + the `verify=False` grep guard
3. `scripts/check-version.sh` - tauri.conf.json, package.json, pyproject.toml
   and `coreflame/__init__.py` all carry the same version

Fix until green, then re-run. The fixers:

```
pnpm --filter deliverer format        # prettier --write .
pnpm --filter deliverer lint:fix      # eslint --fix (attribute order, unused imports)
cd reaver && ruff format . && ruff check . --fix
```

Order on the TS side: `format`, then `lint:fix`, then `check`. mypy needs
`--cache-dir` off the synced folder; `check.sh` already sets `/tmp/mypy_cache`.
Python tests are not pytest - a failing one prints a traceback and the
`check.sh` loop only shows the last line, so re-run `python3 tests/test_x.py`
directly to see it.

## 2. Stage exactly what belongs to this change

`git add -p` or explicit paths. Generated-but-committed files belong in the
same commit as the change that regenerated them: `src/auto-imports.d.ts`,
`src/components.d.ts`, `.eslintrc-auto-import.json`, `pnpm-lock.yaml`.
Never stage `.env`, `data/`, `*.db`, `resources/sidecar/`, `dist/`.

## 3. Write the message - Conventional Commits 1.0.0

`pnpm commit` (cz-git walks type → scope → subject → body → breaking) or by hand:

```
<type>(<scope>): <subject>          # imperative, lowercase, no period, ≤ 100 chars

<body: WHY, not what - the diff shows what>          # optional, ≤ 100 cols

BREAKING CHANGE: <what an existing install/db/config must do>   # when applicable
Closes #12                                                       # optional
```

Types (from `commitlint.config.js`): `feat` (user can see it) · `fix` · `perf` ·
`refactor` · `style` (formatting only) · `test` · `docs` (docs, CLAUDE.md,
skills, changelog) · `build` (bundling, PyInstaller, tauri config) · `ci` ·
`chore` · `revert`.

Scopes are a fixed enum - anything else is rejected: `deliverer` `reaver`
`coreflame` `dawnmaker` `design` `docker` `ci` `release` `docs` `skills` `deps`.
An empty scope only warns (`chore: bump toolchain` is fine for cross-cutting).

```
feat(deliverer): sign-in gate on first launch
fix(coreflame): probe skips fullwidth tags without a request
feat(dawnmaker)!: cursor format is base64url json

BREAKING CHANGE: cursors issued before 0.2 no longer decode; the UI drops them.
chore(release): v0.2.0
docs(skills): add commit skill
```

Breaking = schema, API contract or config-file format changed: put `!` after
the type/scope AND a `BREAKING CHANGE:` footer. commitlint rejects: an unknown
type, a scope outside the enum, a Sentence-case / Start-Case / UPPER subject,
a header over 100 chars, and a body line over 100 (warning).

## 4. What the hooks do (husky, `.husky/`)

- `pre-commit` → `pnpm exec lint-staged` on staged files only
  (`.lintstagedrc.json`): `prettier --write` + `eslint --fix` on
  `deliverer/**/*.{ts,vue,js,json,css,md}`; `ruff format` + `ruff check --fix`
  on `reaver/**/*.py`. It re-stages what it fixed; if it changed a file, look
  at the diff - it may have hidden a real lint error behind an auto-fix.
- `commit-msg` → `pnpm exec commitlint --edit "$1"`. A rejection prints the
  rule name; fix the message, do not `--no-verify`.

## 5. A feature commit moves more than code

A `feat`/`fix` that changes user-visible behaviour also includes, in the same
commit: a line under `## Unreleased` in `CHANGELOG.md` (`Added/Changed/Fixed/
Removed:`, written for the person using the app - Settings › Updates renders
it) and the `en` i18n keys it needs (`deliverer/src/locales/en/*.json`).
`i18n-check` fails on a missing key. See `feature-workflow` for the full list.

## Done means

`pnpm check` green, `git status` clean except intentionally unstaged work,
`git log -1` shows `type(scope): subject`, and the commit-msg hook accepted it
without `--no-verify`.
