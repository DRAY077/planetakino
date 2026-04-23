# Build PlanetaKino.exe on Windows. Run from repo root.
# Prereqs: Python 3.11+, pywebview, pyinstaller, pillow
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = python -c "from planetakino.config import APP_VERSION; print(APP_VERSION)"

Write-Host "▶ Cleaning previous build…"
Remove-Item -Recurse -Force build\PlanetaKino -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue

Write-Host "▶ Generating icons…"
python build\make_icon.py

Write-Host "▶ Running PyInstaller…"
python -m PyInstaller build\planetakino.spec --clean --noconfirm

$exe = "dist\PlanetaKino\PlanetaKino.exe"
if (-not (Test-Path $exe)) {
  Write-Error "PyInstaller failed: $exe not found"
  exit 1
}

Write-Host "▶ Compressing portable ZIP…"
$zipPath = "dist\PlanetaKino-$version-win64.zip"
Compress-Archive -Path "dist\PlanetaKino\*" -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "✅ Done:"
Write-Host "   Folder: dist\PlanetaKino\"
Write-Host "   Exe:    $exe"
Write-Host "   Zip:    $zipPath"
