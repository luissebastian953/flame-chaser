#!/usr/bin/env bash
# Set the release version everywhere it is written down.
#   scripts/bump-version.sh 0.2.0
# Source of truth is deliverer/src-tauri/tauri.conf.json (what the updater
# compares against); this script keeps the other three in step so
# `scripts/check-version.sh` -- run by CI -- stays green. Then:
#   git commit -am "chore(release): v0.2.0" && git tag v0.2.0 && git push --tags
set -euo pipefail
V="${1:?usage: bump-version.sh X.Y.Z}"
[[ "$V" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not a semver: $V" >&2; exit 1; }
cd "$(dirname "$0")/.."

python3 - "$V" <<'PY'
import json, re, sys
from pathlib import Path
v = sys.argv[1]
def sub(path, pattern, repl):
    p = Path(path); s = p.read_text(); n = re.subn(pattern, repl, s, count=1)
    assert n[1] == 1, f"{path}: pattern not found"
    p.write_text(n[0]); print(f"  {path}")
for jf in ("deliverer/src-tauri/tauri.conf.json", "deliverer/package.json"):
    sub(jf, r'"version": "[^"]+"', f'"version": "{v}"')
sub("reaver/pyproject.toml", r'^version = "[^"]+"', f'version = "{v}"')
sub("reaver/coreflame/__init__.py", r'__version__ = "[^"]+"', f'__version__ = "{v}"')
# changelog: promote Unreleased to this version, open a fresh Unreleased
cl = Path("CHANGELOG.md"); s = cl.read_text()
import datetime
today = datetime.date.today().isoformat()
if "## Unreleased" in s:
    s = s.replace("## Unreleased", f"## Unreleased\n\n## {v} - {today}", 1)
    cl.write_text(s); print("  CHANGELOG.md")
PY
pnpm install --lockfile-only >/dev/null && echo "  pnpm-lock.yaml"
echo "version: $V"
