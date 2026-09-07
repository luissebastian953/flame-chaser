#!/usr/bin/env bash
# CI gate: every place a version is written must agree, and a tag must match.
set -euo pipefail
cd "$(dirname "$0")/.."
T=$(python3 -c 'import json;print(json.load(open("deliverer/src-tauri/tauri.conf.json"))["version"])')
P=$(python3 -c 'import json;print(json.load(open("deliverer/package.json"))["version"])')
Y=$(sed -n 's/^version = "\(.*\)"/\1/p' reaver/pyproject.toml | head -1)
I=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' reaver/coreflame/__init__.py)
if [[ "$T" != "$P" || "$T" != "$Y" || "$T" != "$I" ]]; then
  echo "version drift: tauri.conf=$T package.json=$P pyproject=$Y coreflame=$I" >&2; exit 1
fi
if [[ -n "${GITHUB_REF_NAME:-}" && "${GITHUB_REF_NAME}" == v* && "${GITHUB_REF_NAME#v}" != "$T" ]]; then
  echo "tag ${GITHUB_REF_NAME} does not match version $T" >&2; exit 1
fi
echo "version $T (consistent)"
