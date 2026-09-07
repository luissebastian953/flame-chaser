#!/usr/bin/env bash
# The definition of "done" for reaver: lint, format, types, tests. All offline.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"           # uv / pipx installs
# Prefer this project's venv when it holds a ruff that runs here, so `pnpm
# check` at the repo root works without activating anything. The probe is not
# paranoia: the repo is bind-mounted into the Docker container, where
# reaver/.venv is the host's macOS venv and its binaries cannot exec.
if .venv/bin/ruff --version >/dev/null 2>&1; then PATH="$PWD/.venv/bin:$PATH"; fi
CACHE="${MYPY_CACHE_DIR:-/tmp/mypy_cache}"   # off any mounted/synced folder:
                                             # mypy's sqlite cache needs real locking
step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
step "ruff check";        ruff check .
step "ruff format";       ruff format --check .
step "mypy";              mypy --cache-dir "$CACHE"
step "tests"
for t in tests/test_*.py; do
  printf '%-24s ' "$(basename "$t" .py)"
  python3 "$t" 2>&1 | tail -1
done
step "verify=False guard"
if grep -rnE 'verify\s*=\s*False' coreflame --include='*.py' | grep -v 'net.py'; then
  echo "FAIL: TLS verification disabled somewhere"; exit 1
fi
echo "clean"
printf '\n\033[32mall green\033[0m\n'
