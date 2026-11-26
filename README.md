# Mimforge

**Teachers demonstrate. Students watch once — then the apparatus is packed away.
Mimforge turns one demonstration into a machine that can teach it again, safely.**

Mimforge is a Windows-first, offline-first desktop application that creates
**teaching machines** from videos of teachers demonstrating practicals and
skills. It is built education-first (Nigerian schools, WAEC practicals), on a
**practical-agnostic engine**: any practical enters the system as data (a
`PracticalTemplate` + a recorded demonstration), never as special-case code.

## The pipeline

1. **Demonstration** — a teacher records (or imports) a video of a practical,
   with narration. The original is kept untouched and hashed.
2. **Extraction** — the engine tracks the task object the template
   names by colour through the video, measures periodic motion when
   the track supports it, and transcribes the narration locally.
   (Hand/body pose tracking is not in this build — the scope freeze
   keeps perception to the colour-prompt object track.)
3. **Structuring** — the demonstration is drafted into a teachable sequence of
   steps (title, narration, expected observation, learner check, safety
   notes). **The teacher edits and approves every step — nothing
   auto-publishes.**
4. **Design** — steps are matched to generic motion primitives; the
   machine is designed from the parameterised bench-gantry platform
   (the one platform in the V1 scope freeze) fitted to the school's
   bench and budget tier, with parametric CAD generated locally.
5. **Code + control panels** — a step-sequenced controller and a control panel
   are generated from templates. Generated code can only call the safety
   kernel's primitive API — it can never command motors directly or exceed
   the kernel's speed/force caps.
6. **Materials** — a bill of materials in three tiers (Prototype /
   Professional / Industrial) from a local, editable parts database. Tier
   changes materials, accuracy and durability — never the pedagogy.
7. **Simulation** — the machine is simulated (MuJoCo) from the same
   parameters as the CAD, before anything is allowed to move in the real
   world.
8. **Verification** — a discrepancy engine compares the simulation against
   the teacher's demonstration and against the practical's outcome
   specification (readings table, derived quantities, tolerance bands),
   flags discrepancies with concrete adjustments, and loops a bounded number
   of times before teacher review.
9. **Safety gate (blocking)** — every design carries a generated,
   teacher-signed risk assessment; exported lesson/machine packages
   (`.tmachine`) are Ed25519-signed and hash-verified before any controller
   will run them.

## First demonstration

The first worked example is the **WAEC Physics simple pendulum practical**
(determination of g) — chosen because it is the lowest-hazard WAEC practical
with an exactly simulable outcome. It is **demo #1 only**: it lives entirely
in template data under `src/mimforge/templates/`, and the core schema
contains only generic entities (`Practical`, `Demonstration`, `Step`,
`MotionPrimitive`, `ObservationSpec`, `MachineDesign`, `VerificationRun`,
`SafetyCase`). See `docs/SCOPE_FREEZE.md` for the scope freeze and the
anti-pendulum checklist that enforces this separation, and the test suite,
which scans the core for demo-specific terms and fails the build if any are
found.

## Design constraints

- **$0 services.** Every dependency is open source or genuinely free
  (see `docs/SBOM.md`). Muse Spark, when online, is reached only through
  the owner's Cloudflare Worker proxy (the API key is a Worker secret and
  never ships in the app) and is used for *advisory drafting only* — step
  text, explanations, draft code for review. The app calls it only when
  the Worker address is configured (`MIMFORGE_WORKER_URL`); unconfigured
  — the default — drafting is fully offline. Every Muse-assisted feature
  has a local offline fallback; safety limits, interlocks, signing and risk
  assessment are deterministic local code, never an LLM.
- **Firebase = Auth + Firestore metadata only** (free Spark plan). Firebase
  Storage is **not** used — it requires the paid Blaze plan. All video,
  CAD and package files stay local and move as signed packages.
- **Low-spec first ("lean mode").** Target machines are Core i3/i5 Windows
  10 PCs with 4 GB RAM. The engine therefore uses small models, loads and
  unloads models sequentially, samples keyframes instead of processing
  every frame, and runs CPU-first with the GPU strictly optional. Lesson
  *playback* is lighter still: precomputed simulation replay on any school
  PC, no engine required.
- **Safety is layered and none of it is an LLM**: inherently low-energy
  bench platforms, controller-enforced speed/force caps, a physical
  E-stop and monitored stop, per-practical interlocks (heat, electricity,
  chemicals, sharps), simulation-first execution, signed packages, and
  a filming protocol (`docs/FILMING_PROTOCOL.md`) that records the
  teacher, not the students, with consent settled before filming
  under Nigeria Data Protection Act guidance.

## Status

**Phase 0 — foundation package (done).** Scope freeze, software bill of
materials, teacher-validation and filming protocols, the generic core
schema as typed Python data models, the first template (as data), and a
Windows toolchain setup script.

**Phase 1 — skeleton (done).** Project storage (SQLite + content-hash
manifest), Ed25519-signed `.tmachine` packages, safety kernel (speed /
force caps, monitored stop, E-stop), Firebase metadata sync behind a
feature flag (offline-first), and the PySide6 mission-control shell.

**Phase 2 — perception & structuring (done).** Video ingest (ffprobe) +
colour-prompt object tracking with coverage reporting, periodic-motion
analysis, local faster-whisper narration (with an SRT transcript-file
fallback surfaced in the Author panel; typed manual lines exist in the
engine), transcript-to-template step segmentation with an offline
drafting fallback (Muse Spark advisor optional, never required), and
the teacher authoring editor (approve / reject / edit each draft step).

**Phase 5 (QNX) — controller (done, in parallel).** The timing
controller in C under `qnx/` (host build + 93-check test suite); the
QEMU / SDP cross-build step is still to be run on the Windows host.

**Phase 3 — gantry CAD + BOM (done).** Parametric bench gantry via
build123d (STEP re-import verified), three-tier bill of materials
(Prototype / Professional / Industrial, NGN estimates from an
editable parts DB), and the teacher-signed risk-assessment gate that
blocks export until signed.

**Phase 4 — codegen, simulation & discrepancy (done).** Template
codegen: a step-sequenced controller that only calls the safety
kernel's primitive API, plus a generated PySide6 control panel from
the template's control list — both checked by a static AST
allow-list checker that fails seeded malicious samples (network,
direct motor command, OS command, dynamic execution). MuJoCo
simulation of the gantry + suspended load built from the same
parameters as the CAD, recovering the constant within ±3% through the
identical table → graph → slope pipeline. Discrepancy engine
(trajectory shape + outcome comparison, diagnoses from template
data) and a bounded auto-adjust loop (max 3 iterations, reports
unfixable instead of silently passing).

**Phase 6 — playback, packaging, submission (done).** Lesson
playback: engine-free `LessonPackage` (steps, readings table,
fitted graph, precomputed replay track) with a self-contained HTML
export that plays offline in any browser (no external references,
hostile-text safe) and an in-app step-by-step player wired into
the Playback panel. Packaging: PyInstaller onedir spec
(`mimforge.spec`, LGPL libraries shipped as separate files),
Windows build script + Inno Setup installer script
(`setup/build-windows.ps1`, `setup/mimforge.iss`), packaging doc
with honest verification status. Submission: Devpost draft +
checklist (`docs/SUBMISSION.md`) and the demo-video script
(`docs/DEMO_VIDEO_SCRIPT.md`). **Phase 5 (QNX) stays parked:**
the SDP 8.0 install + first real `qcc` cross-build + QEMU run
need Prince's one-time myQNX sign-in; the C controller, host
build and 93-check suite are done and in the repo.

**Full spec audit (2026-11-26, done).** Every panel wired to its
engine and click-tested; the seven engine-only features surfaced
(Deliver section); the Design panel shows the full itemised
materials list per tier and the exported package carries it; a
line-by-line audit of the whole source tree against the platform
spec, the plan and the scope freeze — safety-kernel hardening
(non-finite commands and unconfigured force now fail closed),
package/project integrity hardened (media re-hashed on open,
single-read verified load), verification shape checks run against
the recorded demonstration when one exists, and the docs (this
file, `docs/SBOM.md`, `docs/SCOPE_FREEZE.md`, `docs/PACKAGING.md`)
corrected wherever they claimed more than the code does —
including three scope-freeze amendments: trajectory retargeting
deferred post-V1, Firebase Auth not integrated, SAM 2.1 not
integrated. The audit trail is in the project's progress log.

Next: Phase 5 unblocks on Prince's sign-in (SDP install → `qcc`
compile → QEMU run → timing log), then the Windows installer
test + demo-video recording on his laptop, then submission
(Prince registers from 10 Dec; internal submit-by 14 Dec).
The test suite is the acceptance gate for every phase: `pytest` —
currently 237 tests passing.

## Build / run

```bash
# Develop / run from source (Python 3.11+; FFmpeg on PATH)
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on POSIX
pip install -e .
python -m mimforge            # launches the app
python -m pytest              # the full acceptance suite
```

```powershell
# Windows installer: full test gate -> PyInstaller -> Inno Setup
./setup/build-windows.ps1
# The same build runs in GitHub Actions (.github/workflows/build-windows.yml)
# and publishes the installer as the `mimforge-windows-installer` artifact.
# Windows toolchain notes: setup/windows-toolchain.ps1
# (UNTESTED on Windows — see the script header).
```

## QNX target

The timing-critical controller loop exists as portable C under
`qnx/`: a generic kernel (cycle counting, watchdogs, latching
E-stop) with a host build and a 93-check test suite that runs
anywhere (`make -C qnx`), plus `Makefile.qnx` for the SDP 8.0
cross-build. The cross-build and the QEMU run are the one step
still outstanding: they need the free QNX SDP 8.0 installed from a
signed-in myQNX session (see `qnx/README.md`). Only the controller
loop targets QNX — by design; the desktop app itself never needs
QNX to run.

## Licence

Apache-2.0 — see `LICENSE`. Dependency licences are inventoried in
`docs/SBOM.md` (note the LGPL conditions for PySide6/FFmpeg and the
per-voice licence caveat for Piper TTS).
