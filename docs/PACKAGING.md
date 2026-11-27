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
# 1. Toolchain first (Python 3.12):
.\setup\windows-toolchain.ps1

# 2. Build + installer (stages the bundled runtime assets, runs
#    the FULL pytest suite as a gate, then the frozen self-test):
.\setup\build-windows.ps1
```

## Stage 0: everything inside the app (2026-11-26)

The installed app carries every runtime asset it needs, staged at
packaging time by `setup/fetch_bundled_assets.py` into the
repo-local `bundled/` folder and folded into the bundle by
`mimforge.spec` under `mimforge_resources/`:

- **ffmpeg + ffprobe** — BtbN `win64-lgpl` **shared** build,
  release `autobuild-2026-11-26-12-56` pinned by SHA-256
  (`7c762769…`); LGPL only, never a GPL build (the product is
  proprietary). `LGPL-3.0.txt` + a source-offer notice ship in
  `mimforge_resources/licenses/`.
- **SAM 2.1 weights** (130 MB, publisher hashes) and the
  **Whisper base model** (~150 MB, pinned revision) — first use
  needs no download and no network.
- **Firebase web config** — generated at packaging time from the
  developer's `.env.local` (or `FIREBASE_*` environment variables
  in CI) into `bundled/config/firebase_config.json`; the values
  are never printed by the fetch script, and the generated file
  is gitignored like `.env.local` itself.

At runtime `mimforge.resources` is the ONLY resolver: bundled →
per-user data → developer override. No module looks up ffmpeg,
model weights, or the config on its own.

**Gate v2.** The frozen `--self-test` now runs real-flow probes
(`mimforge.selftest_flows`) in the frozen build: with the OS PATH
scrubbed, it probes the bundled sample clip with the bundled
ffprobe, extracts its audio with the bundled ffmpeg, colour-
tracks frames, segments a frame with the bundled SAM weights,
loads the bundled Whisper model, and loads the bundled Firebase
config — asserting each resource's source is the bundle itself.
A build whose resources are missing fails HERE, not on a user's
machine. (In a source checkout the probes run via
`python -m mimforge --self-test=flows` once the fetch step has
staged `bundled/`.)

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
| Gate v2 flow probes (Stage 0) | this VM, 2026-11-26 | `python -m mimforge --self-test=flows` with `bundled/` staged: all 12 probes pass — resources resolve as bundled with PATH scrubbed; bundled ffprobe probes the sample clip, bundled ffmpeg extracts its audio, colour tracking 18/18 examined frames, Whisper base loads from the bundle, SAM segments a frame, Firebase config loads usable |
| Stage 0 clean-room frozen proof | this VM, 2026-11-26 | clean-room venv rebuilt from declared deps only; frozen build's `--self-test` run with an EMPTY environment (scratch HOME + empty PATH dir, no `.env.local` reachable): all 12 flow probes resolve from `_internal/mimforge_resources`, SELF-TEST OK, exit 0; plain launch stays running |
| Gate v2 machine-view probes (Stage 1) | this VM, 2026-11-26 | probe 13 renders the designed machine offscreen (front/side/top alive + mutually distinct, median frame time under the 100 ms budget); probe 14 asserts the forced-fallback widget draws its canvas performance + internals pages. Where no GL renderer exists the probe passes on the fallback assertion instead |
| Stage 1 clean-room frozen proof | this VM, 2026-11-26 | clean-room venv rebuilt from declared deps only (PyOpenGL now a declared dep + collect_all — its platform loader fails frozen otherwise); frozen `--self-test` in an EMPTY environment: all 14 flow probes pass, machine view renders via EGL at 3.9 ms/frame median (320×240), SELF-TEST OK, exit 0; plain launch (offscreen) stays running |
| Gate v2 narration probes (Stage 2) | this VM, 2026-11-26 | probes 15–18: the bundled Piper voice resolves through the Resource Layer; one neutral step synthesizes to non-silent audio (RMS-checked); `attach_narration` stamps the step with the plain-words AI voice label; the bundled Kokoro-82M (gate-passed, see SBOM) also synthesizes non-silent audio. Narration is rendered at lesson BUILD time only; playback stays silent-safe |
| Kokoro measured gate (Stage 2) | this VM, 2026-11-26 | full 9-step lesson pre-render with the fp16 model: 66.8 s wall / 657 MB peak RSS on this VM (1.5 shared vCPUs) vs plan limits 180 s / 360 s / 1.5 GB — passed with headroom, so Kokoro ships (preferred voice; Piper fallback). Whisper round-trip intelligibility: Kokoro 0.935, Piper 0.802. Independently re-measured at Stage 2 completion (first session: 50.8 s / 701 MB, 0.947 / 0.789 — same verdict) |
| Stage 2 clean-room frozen proof | this VM, 2026-11-26 | clean-room venv rebuilt from declared deps only; frozen `--self-test` in an EMPTY environment (scratch HOME + empty PATH dir, scratch cwd, no `.env.local` reachable): all 18 flow probes pass — including the four narration probes (bundled Piper voice resolves; one step synthesizes to non-silent audio, RMS 0.066; `attach_narration` stamps the AI voice label; bundled Kokoro synthesizes non-silent audio, RMS 0.070) — SELF-TEST OK, exit 0; plain launch stays running |
| Gate v2 assembly + dossier probes (Stage 3) | this VM, 2026-11-26 | probes 19–22: the coupling sequence generates from the default design + parts DB (9 steps, each part once, priced); the wiring diagram and panel layout generate from design data (all run endpoints exist; the panel guarantees a stop); the assembly player constructs and advances two steps; the production dossier refuses an unsigned assessment BEFORE writing anything, then a signed export carries every section with machine images from the real image path. All probe data is platform data — the probes prove the generators, not any one practical |
| Stage 3 clean-room frozen proof | this VM, 2026-11-26 | clean-room venv (declared deps only, editable source); frozen `--self-test` in an EMPTY environment (scratch HOME + empty PATH dir, scratch cwd): all 22 flow probes pass — including the four Stage 3 probes (assembly sequence priced at NGN 69,500; wiring + panel generation; player advance; dossier gate + signed export, 209,660 bytes with renderer images) — SELF-TEST OK, exit 0; plain launch stays running. Stage 3 adds no dependency and no bundled asset: code only |
| Gate v2 library probe (practicals library) | this VM, 2026-11-27 | probe 24: the bundle must carry the WHOLE template library as data — every registered template loads from its bundled data, and every template whose data declares the static verification shape verifies through it from the bundled data alone. The probe is generic (registry + the templates' own declarations; it names no practical) |
| Practicals library clean-room frozen proof | this VM, 2026-11-27 | clean-room venv (declared deps only); frozen `--self-test` in an EMPTY environment (scratch HOME, no `.env.local` reachable): all 24 flow probes pass — including the library probe (3 templates in bundle; static-shape templates verified: 2) — SELF-TEST OK, exit 0; plain launch (offscreen) stays running. The library adds no dependency: two template data files, the static verification shape, and the neutral picker |
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

- **No code signing.** The installer is unsigned; SmartScreen will
  warn. A signing certificate costs money and is a convenience
  only — not bought, per the no-money rule.
- **Lean mode is the default.** The Whisper model is the `base`
  size, bundled (see above). The SAM 2.1 first-run download code
  remains only as a repair path if the bundled weights ever fail
  their hash check. The full profile is a runtime switch, not a
  second installer.
- **CI needs the Firebase values once.** The Windows workflow
  generates the bundled config from repository **Variables**
  (`FIREBASE_API_KEY` etc. — public identifiers, not secrets).
  Until they are set, the fetch step stages everything else and
  warns, and the frozen Gate v2 self-test then fails the build on
  the missing config — by design, so a config-less installer can
  never ship silently again (walk finding #5).
- **QNX evidence is separate.** The QNX C controller (`qnx/`) is
  not inside the Windows installer; its build/run evidence lives
  in the repo and the submission package (see `docs/SUBMISSION.md`).
