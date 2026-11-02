#!/usr/bin/env bash
# Remove a user-level install made by install.sh
set -euo pipefail
PREFIX="${PREFIX:-$HOME/.local}"
rm -rf "$PREFIX/share/studio8085"
rm -f "$PREFIX/bin/studio8085" \
      "$PREFIX/share/applications/studio8085.desktop" \
      "$PREFIX/share/icons/hicolor/256x256/apps/studio8085.png"
echo "8085 Studio removed. Settings are kept in ~/.config/Studio8085 (delete it to reset)."
