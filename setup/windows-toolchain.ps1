# ============================================================================
#  Mimforge - Phase 0 Windows toolchain setup
# ============================================================================
#  STATUS: UNTESTED ON WINDOWS. This script was authored on Linux and has
#  never been executed on a Windows machine. Run it step by step, read every
#  error, and do not treat a clean run as proven until the version report at
#  the end prints and the pytest suite passes.
#
#  What it does:
#    1. Checks for Python 3.11+ (install from python.org first if missing -
#       tick "Add python.exe to PATH" in the installer).
#    2. Creates a virtual environment in .\.venv
#    3. Installs the Phase 0 Python toolchain (plan section 3 / docs/SBOM.md):
#       PySide6, MuJoCo, build123d, faster-whisper, MediaPipe, ONNX Runtime,
#       pytest.
#    4. Prints versions so they can be pinned in docs/SBOM.md (Phase 0.4
#       licence audit).
#
#  What it does NOT do (manual steps, deliberately):
#    - FFmpeg: download an LGPL-configured build ONLY (no --enable-gpl, no
#      libx264) and verify with:  ffmpeg -L   and   ffmpeg -buildconf
#      A GPL build must never be bundled (see docs/SBOM.md).
#    - QNX SDP 8.0: install separately via QNX Everywhere (free
#      non-commercial licence) - a later phase, not Phase 0 Python setup.
#    - Model weights (SAM 2.1 tiny, Whisper base, MediaPipe Lite) are
#      downloaded and hash-pinned in a later phase, not here.
#
#  Run from the repository root in PowerShell:
#    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#    .\setup\windows-toolchain.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

Write-Host "== Mimforge Phase 0 toolchain setup (UNTESTED on Windows) =="

# --- 1. Python check ---------------------------------------------------------
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python not found on PATH. Install Python 3.11+ from python.org (tick 'Add python.exe to PATH'), then re-run."
}
$version = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "Found Python $version"
if ([version]$version -lt [version]"3.11") {
    throw "Python 3.11+ is required; found $version."
}

# --- 2. Virtual environment --------------------------------------------------
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment in .venv ..."
    python -m venv .venv
} else {
    Write-Host ".venv already exists - reusing it."
}
& .\.venv\Scripts\Activate.ps1

# --- 3. Toolchain ------------------------------------------------------------
Write-Host "Upgrading pip ..."
python -m pip install --upgrade pip

Write-Host "Installing Phase 0 toolchain (this can take a while on 4 GB RAM machines) ..."
# Core schema + tests need nothing third-party; the packages below are the
# Phase 0-audited engine dependencies from docs/SBOM.md.
python -m pip install `
    PySide6 `
    mujoco `
    build123d `
    faster-whisper `
    mediapipe `
    onnxruntime `
    pytest

# --- 4. Version report (pin these in docs/SBOM.md) ---------------------------
Write-Host ""
Write-Host "== Installed versions =="
python -m pip list --format=columns | Select-String -Pattern "PySide6|mujoco|build123d|faster-whisper|mediapipe|onnxruntime|pytest"

Write-Host ""
Write-Host "== Running the Phase 0 test suite =="
python -m pytest

Write-Host ""
Write-Host "Done. REMINDER: FFmpeg (LGPL build only) and QNX SDP 8.0 are manual"
Write-Host "steps - see the header of this script and docs/SBOM.md."
