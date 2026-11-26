# Mimforge — Windows build script (plan Phase 6.2)
#
# Run from the repo root on Prince's Windows laptop (PowerShell):
#   .\setup\build-windows.ps1
#
# What it does, in order:
#   1. Creates .venv if missing and installs the app + PyInstaller.
#   2. Runs the FULL pytest suite -- the build stops if any test fails.
#   3. Builds dist\Mimforge with PyInstaller (onedir; see mimforge.spec).
#   4. If Inno Setup's compiler (iscc.exe) is found -- on PATH or in
#      a standard install folder (Inno's installer does not add it to
#      PATH) -- builds the installer Mimforge-Setup-0.0.1.exe next to
#      it. If iscc is not found anywhere, it stops with the download
#      link instead of failing silently -- install Inno Setup 6
#      (free) and re-run.
#
# The script never downloads a paid tool and never touches the
# network beyond pip / PyInstaller (both free). FFmpeg is NOT bundled
# by this script and NOT installed by the toolchain script either:
# the app shells out to a system FFmpeg for video ingest, and
# installing an LGPL FFmpeg build is a manual prerequisite
# (see docs/PACKAGING.md).

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment .venv ..."
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { python -m venv .venv }
}
& .\.venv\Scripts\Activate.ps1

Write-Host "Installing app + build tools ..."
pip install --upgrade pip
pip install -e .
pip install pyinstaller pytest

Write-Host "Running FULL test suite (build gate) ..."
# Same environment the GitHub Actions gate verifies with.
$env:QT_QPA_PLATFORM = "offscreen"
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

# Frozen-bundle gate (2026-11-26): the exe is windowed, so launch
# the self-test with Start-Process -Wait and gate on its exit code.
# A module missing from the bundle (the scipy launch crash) fails
# HERE, before Inno Setup packages it. QT_QPA_PLATFORM=offscreen
# is already set above for the test gate.
Write-Host "Self-testing the frozen app (missing-module gate) ..."
$proc = Start-Process -FilePath (Join-Path $AppDir "Mimforge.exe") -ArgumentList "--self-test" -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    throw "Frozen-app self-test failed with exit code $($proc.ExitCode) -- a module is missing from the bundle. Do not package this build."
}
Write-Host "Self-test passed."

Write-Host "Locating the Inno Setup compiler (iscc.exe) ..."
$isccDirs = @(
    "C:\Program Files (x86)\Inno Setup 6",
    "C:\Program Files\Inno Setup 6",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6")
)
$isccPath = $null
$isccCommand = Get-Command iscc.exe -ErrorAction SilentlyContinue
if ($isccCommand) { $isccPath = $isccCommand.Source }
if (-not $isccPath) {
    foreach ($dir in $isccDirs) {
        $candidate = Join-Path $dir "ISCC.exe"
        if (Test-Path $candidate) { $isccPath = $candidate; break }
    }
}
if (-not $isccPath) {
    Write-Host ""
    Write-Host "Inno Setup compiler (iscc.exe) not found on PATH or in a standard install folder."
    Write-Host "Install Inno Setup 6 (free) from https://jrsoftware.org/isdl.php"
    Write-Host "then re-run this script -- the PyInstaller build above is already done."
    Write-Host "App folder ready for a manual install test: $AppDir"
    # No installer was produced, so this run FAILED -- say so in
    # the exit code too, never as a quiet success.
    exit 1
}

Write-Host "Using ISCC: $isccPath"
Write-Host "Building installer with Inno Setup ..."
& $isccPath setup\mimforge.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed." }
Write-Host "Installer built: dist\Mimforge-Setup-0.0.1.exe"
Write-Host "Next: install on a clean Windows profile and run the 6.2 test (docs/PACKAGING.md)."
