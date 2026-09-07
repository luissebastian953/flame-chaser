#!/usr/bin/env sh
# Curio for Linux -- one line:
#   curl -fsSL https://github.com/luissebastian953/flame-chaser/releases/latest/download/install-linux.sh | sh
# Downloads the latest AppImage to ~/.local/bin/curio and adds a menu entry.
# The app updates itself after this; re-running is harmless.
set -eu
REPO="luissebastian953/flame-chaser"
case "$(uname -m)" in
  x86_64) ARCH=amd64 ;;
  *) echo "Curio ships x86_64 AppImages only for now (got $(uname -m))" >&2; exit 1 ;;
esac
BIN="$HOME/.local/bin"; APPS="$HOME/.local/share/applications"
mkdir -p "$BIN" "$APPS"
URL=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
  | grep -o "https://[^\"]*_${ARCH}\.AppImage" | head -1)
[ -n "$URL" ] || { echo "no AppImage in the latest release" >&2; exit 1; }
echo "downloading $URL"
curl -fL# "$URL" -o "$BIN/curio" && chmod +x "$BIN/curio"
cat > "$APPS/curio.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Curio
Comment=Character illustration archive
Exec=$BIN/curio
Icon=curio
Categories=Graphics;
DESK
echo "installed: $BIN/curio  (make sure ~/.local/bin is on your PATH)"
