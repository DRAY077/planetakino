#!/usr/bin/env bash
# Build .app and .dmg on macOS.
# Prereqs: pyinstaller, create-dmg (via Homebrew)
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
VERSION="$(python3 -c 'from planetakino.config import APP_VERSION; print(APP_VERSION)')"
APP_NAME="PlanetaKino"

echo "▶ Cleaning previous build…"
rm -rf build/PlanetaKino build/__pycache__ dist/

echo "▶ Generating icons…"
python3 build/make_icon.py

echo "▶ Running PyInstaller…"
python3 -m PyInstaller build/planetakino.spec --clean --noconfirm

APP_PATH="dist/${APP_NAME}.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "✗ $APP_PATH not found — PyInstaller failed" >&2
  exit 1
fi

echo "▶ Patching Info.plist (arm64 + x86_64)…"
/usr/libexec/PlistBuddy -c "Add :LSArchitecturePriority array" "$APP_PATH/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :LSArchitecturePriority:0 string arm64" "$APP_PATH/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :LSArchitecturePriority:1 string x86_64" "$APP_PATH/Contents/Info.plist" 2>/dev/null || true

echo "▶ Verifying app launches (cold-start check)…"
codesign --force --deep --sign - "$APP_PATH" || true
xattr -rd com.apple.quarantine "$APP_PATH" || true

DMG_PATH="dist/${APP_NAME}-${VERSION}.dmg"
echo "▶ Packaging DMG → $DMG_PATH"

if command -v create-dmg >/dev/null 2>&1; then
  rm -f "$DMG_PATH"
  create-dmg \
    --volname "Planeta Kino ${VERSION}" \
    --volicon "build/icon/icon.icns" \
    --window-size 600 400 \
    --icon-size 128 \
    --icon "${APP_NAME}.app" 150 180 \
    --app-drop-link 450 180 \
    --hdiutil-quiet \
    "$DMG_PATH" \
    "$APP_PATH"
else
  echo "  (create-dmg not found — falling back to hdiutil)"
  hdiutil create -volname "Planeta Kino" -srcfolder "$APP_PATH" -ov -format UDZO "$DMG_PATH"
fi

echo ""
echo "✅ Done:"
echo "   App: $APP_PATH"
echo "   DMG: $DMG_PATH"
ls -lh "$DMG_PATH"
