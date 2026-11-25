# Mimforge — Windows build script (plan Phase 6.2)
#
# Run from the repo root on Prince's Windows laptop (PowerShell):
#   .\setup\build-windows.ps1
#
# What it does, in order:
#   1. Creates .venv if missing and installs the app + PyInstaller.
#   2. Runs the FULL pytest suite -- the build stops if any test fails.
#   3. Builds dist\Mimforge with PyInstaller (onedir; see mimforge.spec).
#   4. If Inno Setup's compiler (iscc.exe) is on PATH, builds the
#      installer Mimforge-Setup-0.0.1.exe next to it. If iscc is not
#      found, it stops with the download link instead of failing
#      silently -- install Inno Setup 6 (free) and re-run.
#
# The script never downloads a paid tool and never touches the
# network beyond pip / PyInstaller (both free). FFmpeg is NOT bundled
# by this script: the app shells out to a system FFmpeg for video
# ingest, and setup\windows-toolchain.ps1 installs an LGPL build.
# (A future step may vendor the LGPL FFmpeg binaries into the
# installer; until then the toolchain script is a stated
# prerequisite -- see docs/PACKAGING.md.)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment .venv ..."
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { python -m venv .venv }
}
& .\.venv\Scripts\Activate.ps1

Write-Host "Installing app + build tools ..."
pip install --upgrade pip
pip install -e .
pip install pyinstaller pytest

Write-Host "Running FULL test suite (build gate) ..."
pytest -q
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed -- build stopped. Fix the failures before packaging."
}

Write-Host "Building with PyInstaller ..."
pyinstaller --noconfirm mimforge.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$AppDir = Join-Path $RepoRoot "dist\Mimforge"
if (-not (Test-Path (Join-Path $AppDir "Mimforge.exe"))) {
    throw "Expected dist\Mimforge\Mimforge.exe was not produced."
}
Write-Host "App built: $AppDir"

$iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    Write-Host ""
    Write-Host "Inno Setup compiler (iscc.exe) not found on PATH."
    Write-Host "Install Inno Setup 6 (free) from https://jrsoftware.org/isdl.php"
    Write-Host "then re-run this script -- the PyInstaller build above is already done."
    Write-Host "App folder ready for a manual install test: $AppDir"
    exit 0
}

Write-Host "Building installer with Inno Setup ..."
iscc setup\mimforge.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed." }
Write-Host "Installer built: dist\Mimforge-Setup-0.0.1.exe"
Write-Host "Next: install on a clean Windows profile and run the 6.2 test (docs/PACKAGING.md)."
