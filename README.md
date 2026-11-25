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
2. **Extraction** — the engine recovers the task-object and hand/body
   trajectories from the video and transcribes the narration locally.
3. **Structuring** — the demonstration is drafted into a teachable sequence of
   steps (title, narration, expected observation, learner check, safety
   notes). **The teacher edits and approves every step — nothing
   auto-publishes.**
4. **Design** — steps are matched to generic motion primitives; a machine is
   designed from a parameterised platform library (bench gantry, bench arm,
   presentation rig) fitted to the school's bench, power and budget tier, with
   parametric CAD generated locally.
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
  text, explanations, draft code for review. Every Muse-assisted feature
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
  Nigeria Data Protection Act consent records — record the teacher, not
  the students.

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
analysis, local faster-whisper narration (with SRT / manual transcript
fallbacks), transcript-to-template step segmentation with an offline
drafting fallback (Muse Spark advisor optional, never required), and
the teacher authoring editor (approve / reject / edit each draft step).

**Phase 5 (QNX) — controller (done, in parallel).** The timing
controller in C under `qnx/` (host build + 93-check test suite); the
QEMU / SDP cross-build step is still to be run on the Windows host.

Next: Phase 3 (gantry CAD + BOM) and Phase 4 (codegen, control panel,
MuJoCo simulation, discrepancy scoring). The test suite is the
acceptance gate for every phase: `pytest` — currently 54 tests passing.

## Build / run (placeholder)

Application build instructions will land with Phase 1. For now:

```powershell
# Windows toolchain setup (UNTESTED on Windows — see the script header)
./setup/windows-toolchain.ps1
```

```bash
# Run the Phase 0 test suite (any platform with Python 3.11+)
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on POSIX
pip install pytest
pytest
```

## QNX target (placeholder note)

A later phase ports the timing-critical machine controller loop to C on
**QNX 8.0** (cross-built with the free QNX SDP 8.0, run under QEMU), with
the Windows app acting as the host tool that builds, deploys and tests it.
Only the controller loop is ported — by design. Nothing QNX-related is in
this package beyond this note.

## Licence

Apache-2.0 — see `LICENSE`. Dependency licences are inventoried in
`docs/SBOM.md` (note the LGPL conditions for PySide6/FFmpeg and the
per-voice licence caveat for Piper TTS).
