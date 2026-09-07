#!/usr/bin/env bash
# pre-commit guard: refuse any staged file over 2 MB. Icons are ~100 KB; the
# sidecar and installers are gitignored; anything bigger is a mistake.
set -euo pipefail
LIMIT=$((2 * 1024 * 1024))
bad=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  size=$(wc -c < "$f")
  if [ "$size" -gt "$LIMIT" ]; then
    printf 'staged file too large (%d KB): %s\n' "$((size / 1024))" "$f" >&2
    bad=1
  fi
done < <(git diff --cached --name-only --diff-filter=AM)
[ "$bad" -eq 0 ] || { echo "unstage it, or add it to .gitignore; large binaries do not belong in this repo" >&2; exit 1; }
