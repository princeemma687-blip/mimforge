# Packaging — Mimforge (plan Phase 6.2)

## What ships

- **App**: the PySide6 desktop shell (`python -m mimforge`, console
  script `mimforge`), built with PyInstaller **onedir** into
  `dist/Mimforge/Mimforge.exe`.
- **Installer**: Inno Setup 6 script `setup/mimforge.iss` produces
  `dist/Mimforge-Setup-0.0.1.exe`.
- **Lesson export**: any finished lesson also exports as a single
  self-contained HTML file that plays offline in a browser
  (`mimforge.playback.export_html_lesson`) — no install needed to
  play a lesson on a school PC.

Onedir, not onefile, is deliberate: PySide6/Qt and the OCCT kernel
are LGPL, so their libraries ship as separate files next to the
executable with the licence notices (`LICENSE` + `docs/SBOM.md`
are copied into the app folder by the spec). See `docs/SBOM.md`
for the licence conditions.

## Build on Windows (Prince's laptop)

```powershell
# 1. Toolchain first (Python 3.12; FFmpeg is a separate manual
#    install -- see the packaging limits below):
.\setup\windows-toolchain.ps1

# 2. Build + installer (runs the FULL pytest suite as a gate first):
.\setup\build-windows.ps1
```

The script stops if tests fail, and stops with instructions (not a
silent skip) if Inno Setup is not installed.

## What was verified, and where

| Check | Where | Result |
|---|---|---|
| Full pytest suite | this VM, 2026-11-25 | pass (count in the progress log) |
| PyInstaller build from `mimforge.spec` | this VM (Linux smoke build) | binary starts headless offscreen — see below |
| Windows installer build (`iscc`) | **not run here** — Inno Setup is Windows-only | Prince's laptop step |
| Clean-profile install test: fresh install → open demo project → run simulation → play lesson, no dev tools | **not run here** — needs Windows | Prince's laptop step (the 6.2 test) |
| SmartScreen | unsigned build — Windows will warn on first run | expected; explain, do not bypass. An Authenticode certificate is a paid convenience, not required |

## Linux smoke build (this VM, 2026-11-25)

```bash
pip install pyinstaller
pyinstaller --noconfirm mimforge.spec
# Smoke test: the binary has no --help flag; it opens the app window.
# Offscreen, with a timeout, it must stay running (exit 124 from
# `timeout`) -- a traceback / immediate exit means the build is
# broken. Record the outcome in the progress log.
QT_QPA_PLATFORM=offscreen timeout 15 ./dist/Mimforge/Mimforge; echo "exit=$?"
```

The Linux binary is **not** a deliverable: it only proves the spec
collects every module (PySide6, build123d/OCCT, MuJoCo,
faster-whisper, OpenCV) and the app starts. The Windows build is
the deliverable and is verified on Prince's laptop.

## Known packaging limits (honest)

- **FFmpeg is not bundled.** Video ingest shells out to a system
  FFmpeg. Installing FFmpeg is a **manual prerequisite** (the
  toolchain script deliberately does not install it — see its
  header); a machine without it gets a plain "the video tools are
  not available" message from the app, not a crash. A future step
  may vendor the LGPL FFmpeg binaries into the installer.
- **No code signing.** The installer is unsigned; SmartScreen will
  warn. A signing certificate costs money and is a convenience
  only — not bought, per the no-money rule.
- **Lean mode is the default.** The Whisper model is the `base`
  size and is **not bundled**: it downloads on first transcription
  (~150 MB, needs a connection once). SAM 2.1 is **not in this
  build** at all (see `docs/SBOM.md` status section). The full
  profile is a runtime switch, not a second installer.
- **QNX evidence is separate.** The QNX C controller (`qnx/`) is
  not inside the Windows installer; its build/run evidence lives
  in the repo and the submission package (see `docs/SUBMISSION.md`).
