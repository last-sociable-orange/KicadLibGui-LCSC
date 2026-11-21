#!/usr/bin/env bash
# Build the one-file Linux executable for KiCad LibGen LCSC.
#
#   ./build/build_linux.sh
#
# Produces dist/kicad-lib-gen-lcsc plus a SHA256 file.  PyInstaller cannot
# cross-compile: run this on Linux, and build_windows.ps1 on Windows.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; fi
echo "Using interpreter: $PYTHON"

echo "== version =="
"$PYTHON" gui_main.py --version

echo "== tests =="
"$PYTHON" -m pytest -q

echo "== lint =="
"$PYTHON" -m ruff check .

echo "== self-test =="
"$PYTHON" gui_main.py --self-test

echo "== pyinstaller =="
"$PYTHON" -m PyInstaller --clean --noconfirm build/kicad_lib_gen_lcsc.spec

OUT=dist/kicad-lib-gen-lcsc
if [ ! -f "$OUT" ]; then
  # PyInstaller names the binary after the spec's EXE name.
  if [ -f dist/KiCadLibGenLCSC ]; then OUT=dist/KiCadLibGenLCSC; else
    echo "expected an executable in dist/" >&2; exit 1
  fi
fi
chmod +x "$OUT"
sha256sum "$OUT" > "$OUT.sha256"
echo
echo "Built $OUT ($(du -h "$OUT" | cut -f1))"
cat "$OUT.sha256"

echo "== packaged self-test =="
"$OUT" --self-test
