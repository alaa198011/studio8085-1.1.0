#!/usr/bin/env bash
# Build the ORIGINAL GNUSim8085 CPU core into a shared library so diff_test.py can use it as an oracle.
# usage: ./build.sh /path/to/GNUSim8085-master/src
# Requires gcc and the GLib development files (libglib2.0-dev). The GNUSim8085 sources (GPL) are
# compiled on your machine only; nothing from them is copied into this repository.
set -euo pipefail
SRC="${1:?usage: build.sh /path/to/GNUSim8085/src}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
printf '#define PACKAGE "gnusim8085"\n#define VERSION "oracle"\n#define GETTEXT_PACKAGE "gnusim8085"\n' > "$TMP/config.h"
gcc -O1 -shared -fPIC -w -I"$TMP" -I"$SRC" $(pkg-config --cflags glib-2.0) \
    "$HERE/ref_lib.c" "$SRC/8085.c" "$SRC/8085-instructions.c" "$SRC/8085-memblock.c" \
    $(pkg-config --libs glib-2.0) -o "$HERE/libref.so"
echo "built $HERE/libref.so"
