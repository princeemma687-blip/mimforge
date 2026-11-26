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

## Clean-room rule (2026-11-26)

**A frozen build is only trusted when it was built AND self-tested
from a venv containing only the project's declared dependencies.**

Why: run #6 crashed on launch on the user's laptop with
``No module named 'scipy'`` while all 295 tests passed here. The
dev venv had scipy installed (a build123d transitive), so every
test passed -- but `mimforge.spec` listed scipy in its PyInstaller
`excludes`, so the shipped bundle did not contain it, and
build123d imports scipy at module load. A rich dev environment
masks exactly this class of defect; a clean room cannot.

The gate, in three layers:

1. `Mimforge.exe --self-test` imports the full module graph
   (every app module + every runtime package), constructs the
   real main window offscreen, prints `SELF-TEST OK` and exits 0;
   any missing module exits non-zero. Both the Windows workflow
   and `setup/build-windows.ps1` run it after PyInstaller and
   BEFORE Inno Setup packages anything.
2. `tests/test_frozen_bundle.py` pins the spec to the app's real
   import graph: every runtime package must be collect_all'd or
   hiddenimported, none may be excluded, and scipy is named
   explicitly (removing it from the spec fails the suite).
3. Before a build is called good, reproduce the packaging in a
   clean venv (`pip install -e .` + pyinstaller only), build with
   the spec, and run the frozen binary's `--self-test`.

## What was verified, and where

| Check | Where | Result |
|---|---|---|
| Full pytest suite | this VM, 2026-11-25 | pass (count in the progress log) |
| PyInstaller build from `mimforge.spec` | this VM (Linux smoke build) | binary starts headless offscreen — see below |
| Clean-room build + frozen `--self-test` | this VM, 2026-11-26 | fresh venv (declared deps only): the pre-fix spec reproduced the laptop's `No module named 'scipy'` crash exactly; the fixed spec's bundle passes `--self-test` (SELF-TEST OK, exit 0) and a plain launch stays running |
| Windows installer build (`iscc`) | **not run here** — Inno Setup is Windows-only | Prince's laptop step |
| Clean-profile install test: fresh install → open demo project → run simulation → play lesson, no dev tools | **not run here** — needs Windows | Prince's laptop step (the 6.2 test) |
| SmartScreen | unsigned build — Windows will warn on first run | expected; explain, do not bypass. An Authenticode certificate is a paid convenience, not required |

## Linux smoke build (this VM, 2026-11-25)

```bash
pip install pyinstaller
pyinstaller --noconfirm mimforge.spec
# Smoke test (2026-11-26): the frozen binary's --self-test imports
# the full module graph and constructs the window offscreen; it
# must print SELF-TEST OK and exit 0. A plain launch must then stay
# running offscreen (exit 124 from `timeout`) -- a traceback /
# immediate exit means the build is broken. Record the outcome in
# the progress log.
QT_QPA_PLATFORM=offscreen ./dist/Mimforge/Mimforge --self-test; echo "exit=$?"
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
  (~150 MB, needs a connection once). The SAM 2.1 click tracker's
  weights are likewise **not bundled**: they download once on
  first use (~130 MB, needs a connection once, then work offline;
  see `docs/SBOM.md`). The full profile is a runtime switch, not a
  second installer.
- **QNX evidence is separate.** The QNX C controller (`qnx/`) is
  not inside the Windows installer; its build/run evidence lives
  in the repo and the submission package (see `docs/SUBMISSION.md`).
