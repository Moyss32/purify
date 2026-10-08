#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APPIMAGE_TOOL="${APPIMAGETOOL:-appimagetool}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 não encontrado" >&2
  exit 1
fi
if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller ausente. Instale-o no ambiente de build com python3 -m pip install pyinstaller." >&2
  exit 1
fi
if ! command -v "$APPIMAGE_TOOL" >/dev/null 2>&1; then
  echo "AppImageTool não encontrado. Defina APPIMAGETOOL para um executável verificado." >&2
  exit 1
fi

cd "$ROOT"
python3 -m PyInstaller --noconfirm --clean --windowed --onedir --name Purify purify.py

APPDIR="$ROOT/dist/Purify.AppDir"
rm -rf -- "$APPDIR"
mkdir -p "$APPDIR/usr/lib/Purify"
cp -a "$ROOT/dist/Purify/." "$APPDIR/usr/lib/Purify/"
cp "$ROOT/packaging/linux/AppRun" "$APPDIR/AppRun"
cp "$ROOT/packaging/linux/Purify.desktop" "$APPDIR/Purify.desktop"
cp "$ROOT/assets/purify.svg" "$APPDIR/purify.svg"
ln -sf purify.svg "$APPDIR/.DirIcon"
chmod +x "$APPDIR/AppRun"
"$APPIMAGE_TOOL" "$APPDIR" "$ROOT/dist/Purify-x86_64.AppImage"
echo "Artefato criado em dist/Purify-x86_64.AppImage; valide em cada distro da SUPPORT_MATRIX.md."
