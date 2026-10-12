#!/usr/bin/env bash
# Build dawnmaker as a --onedir PyInstaller bundle and stage it where
# tauri.conf.json > bundle.resources expects it.
#
# --onedir, not --onefile: onefile re-extracts the whole Python runtime to a
# temp dir on every launch (1-3s cold start) and that extract-and-exec pattern
# is what Windows AV heuristics flag.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="src-tauri/resources/sidecar"

python -m PyInstaller \
  --noconfirm --clean --onedir --name dawnmaker \
  --distpath .build/dist --workpath .build/work --specpath .build \
  --collect-all gallery_dl \
  --paths ../reaver `# coreflame + dawnmaker from source: an editable install is an import hook PyInstaller cannot follow` \
  scripts/sidecar_entry.py   # not dawnmaker/__main__.py: see the entry's docstring

rm -rf "$OUT" && mkdir -p "$(dirname "$OUT")"
cp -R .build/dist/dawnmaker "$OUT"

# macOS: notarization requires EVERY Mach-O signed with the hardened runtime --
# the exe and every .so/.dylib PyInstaller drags in. `codesign --deep` is
# unreliable for this; sign the leaves here, then `tauri build` signs the .app.
if [[ "$(uname)" == "Darwin" && -n "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  find "$OUT" \( -name '*.so' -o -name '*.dylib' -o -type f -perm +111 \) \
    -exec codesign --force --timestamp --options runtime \
                   -s "$APPLE_SIGNING_IDENTITY" {} \;
fi
