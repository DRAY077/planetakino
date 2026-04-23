# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Planeta Kino Dashboard.

Usage (from repo root):
    python3 -m PyInstaller build/planetakino.spec --clean --noconfirm

Cross-platform:
- macOS: produces ``dist/PlanetaKino.app`` (bundled)
- Windows: produces ``dist/PlanetaKino/PlanetaKino.exe`` (folder mode)
  — folder mode is preferred on Windows because single-file triggers SmartScreen
    warnings more aggressively and bloats startup due to temp-dir extraction.
"""
from pathlib import Path
import sys

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent

is_macos = sys.platform == "darwin"
is_windows = sys.platform == "win32"

# Resources bundled inside the app
datas = [
    (str(ROOT / "web"), "web"),
]

# Empty data directory is created on first run; we only ship `data/.keep` so the
# folder exists. User state lives in the OS-specific user-data dir when frozen.
data_keep = ROOT / "data" / ".keep"
data_keep.parent.mkdir(parents=True, exist_ok=True)
if not data_keep.exists():
    data_keep.write_text("")
datas.append((str(data_keep), "data"))

# Hidden imports PyInstaller's analyzer sometimes misses for pywebview
hiddenimports = [
    "webview",
    "webview.platforms.cocoa" if is_macos else "webview.platforms.winforms",
]

block_cipher = None

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",           # not used, huge on Windows
        "test",
        "unittest",
        "pydoc",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon_path = str(ROOT / "build" / "icon" / ("icon.icns" if is_macos else "icon.ico"))

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PlanetaKino",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX triggers macOS notarization failures
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PlanetaKino",
)

if is_macos:
    app = BUNDLE(
        coll,
        name="PlanetaKino.app",
        icon=icon_path,
        bundle_identifier="ua.planetakino.dashboard",
        info_plist={
            "CFBundleName": "Planeta Kino",
            "CFBundleDisplayName": "Planeta Kino Dashboard",
            "CFBundleShortVersionString": "0.2.0",
            "CFBundleVersion": "0.2.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.utilities",
        },
    )
