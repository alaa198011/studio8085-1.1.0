#!/usr/bin/env bash
# Install 8085 Studio for the current user (no root needed).
#   ./packaging/linux/install.sh            -> installs under ~/.local
#   PREFIX=/opt/studio8085 ./install.sh     -> custom prefix (may need sudo)
# It creates a private virtual environment, so nothing touches your system Python.
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
APPDIR="$PREFIX/share/studio8085"
VENV="$APPDIR/venv"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    echo "Python 3.9 or newer is required (found: $("$PYTHON" --version 2>&1 || echo none))." >&2
    echo "On Debian/Ubuntu:  sudo apt install python3 python3-venv" >&2
    exit 1
fi
"$PYTHON" -c 'import venv, ensurepip' 2>/dev/null || {
    echo "The venv module is missing. On Debian/Ubuntu:  sudo apt install python3-venv" >&2
    exit 1
}

echo ">> Creating environment in $VENV"
mkdir -p "$APPDIR" "$PREFIX/bin" "$PREFIX/share/applications" "$PREFIX/share/icons/hicolor/256x256/apps"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
echo ">> Installing 8085 Studio and PySide6 (this downloads Qt, ~100 MB)"
"$VENV/bin/python" -m pip install --quiet "$SRC"

LIBS="$(ldconfig -p 2>/dev/null || true)"   # (not piped into grep -q: with pipefail that gives false alarms)
if command -v ldconfig >/dev/null 2>&1 && ! grep -q 'libxcb-cursor\.so\.0' <<<"$LIBS"; then
    echo
    echo "NOTE: Qt 6 needs the libxcb-cursor library to open its window. Install it first:"
    echo "    Debian/Ubuntu:  sudo apt install libxcb-cursor0"
    echo "    Fedora:         sudo dnf install xcb-util-cursor"
    echo "    Arch:           sudo pacman -S xcb-util-cursor"
    echo
fi

ln -sf "$VENV/bin/studio8085" "$PREFIX/bin/studio8085"
install -m 644 "$SRC/packaging/icons/studio8085-256.png" \
    "$PREFIX/share/icons/hicolor/256x256/apps/studio8085.png"
sed "s|@EXEC@|$PREFIX/bin/studio8085|" "$SRC/packaging/linux/studio8085.desktop" \
    > "$PREFIX/share/applications/studio8085.desktop"
chmod 644 "$PREFIX/share/applications/studio8085.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true

echo
echo "Installed. Start it from your application menu (\"8085 Studio\") or run:"
echo "    $PREFIX/bin/studio8085"
case ":$PATH:" in *":$PREFIX/bin:"*) ;; *) echo "(add $PREFIX/bin to your PATH to run 'studio8085' from any terminal)";; esac
