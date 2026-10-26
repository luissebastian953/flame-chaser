#!/usr/bin/env bash
# No em-dash (U+2014) in any tracked file: code, comments, docs, i18n strings.
# It is a different code point from the hyphen-minus and renders wider; the
# owner wants the plain "-" everywhere. Part of `pnpm check` at the root.
set -euo pipefail
cd "$(dirname "$0")/.."
if git ls-files -z | xargs -0 grep -nF -- "$(printf '\xe2\x80\x94')" 2>/dev/null; then
  echo "FAIL: em-dash (U+2014) found; use the plain hyphen-minus '-'" >&2
  exit 1
fi
echo "no em-dash"
