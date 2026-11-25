# Scope Freeze — Phase 0 (Hackathon Build)

**Status: FROZEN for the QNX Global Hackathon build.** Changes to this
scope require an explicit owner decision recorded in this file. The freeze
implements Phase 0, step 0.1 of the project plan: freeze the demonstration
slice + the generic architecture.

## What the hackathon build INCLUDES

- **One worked demonstration**: the WAEC Physics simple pendulum practical
  (determination of g), end to end — ingest → extraction → structuring →
  machine design → code/panel generation → tiered BOM → MuJoCo simulation →
  discrepancy verification — present **only as template data** (see the
  anti-pendulum checklist below).
- **The generic engine**: the core schema (`Practical`, `Demonstration`,
  `Step`, `MotionPrimitive`, `ObservationSpec`, `MachineDesign`,
  `VerificationRun`, `SafetyCase`) and a pipeline designed for *any*
  practical, with the pendulum as its first instance.
- **One platform**: the parameterised bench gantry (the pendulum machine is
  a configuration of it, not a bespoke design).
- **Deterministic trajectory retargeting** (kinematic mapping, time-scaling,
  primitive sequencing) built in-house.
- **Template-based codegen** over the safety-kernel primitive API, plus a
  generated control panel. Muse Spark (via the owner's Cloudflare Worker)
  may *draft* text/code for review; offline fallbacks exist for every
  Muse-assisted feature.
- **Safety kernel**: controller-enforced speed/force caps, monitored stop,
  generated risk assessment with a blocking teacher sign-off gate,
  Ed25519-signed `.tmachine` packages with hash verification.
- **Firebase Auth + Firestore metadata sync** (free Spark plan), behind a
  feature flag, with a hard offline gate: every core workflow must work
  with the network off and Firebase disabled.
- **QNX target (later phase, placeholder in this package)**: the
  timing-critical controller loop ported to C on QNX 8.0 under QEMU; the
  Windows app as host tool. Category: **Robotics & Medical**.
- **Lean mode from day one** (target hardware: Core i3/i5, 4 GB RAM,
  Windows 10): small model variants only (Whisper *base*, SAM 2.1 *tiny*),
  sequential model load/unload, keyframe sampling, CPU-first inference,
  precomputed simulation replay for lesson playback on school PCs.
- **Lesson playback** on low-end school PCs (no engine, no models, no
  network).

## What the hackathon build EXCLUDES

- **Learned robot policies** (LeRobot / SmolVLA or any VLA model) — they
  require robot episode datasets and GPU training; named post-V1 research
  track only.
- **Every other practical** beyond the pendulum demo (Hooke's law is the
  first post-hackathon addition; Chemistry titration is a stretch goal
  beyond school-ready V1, never a V1 promise).
- **Any physical machine build** — the hackathon entry is software +
  simulation + the QNX/QEMU target. Physical tiers are Phase 7.
- **Firebase Storage** — requires the paid Blaze plan. All files are
  local; sharing is by signed package files.
- **Llama Guard** — not bundled. It is a content classifier for AI text,
  not machine safety; V1 uses deterministic lists + a teacher moderation
  queue for shared text. (Optional, post-V1, for screening shared skill
  descriptions only.)
- **A whole-app QNX port** — only the controller timing loop is ported.
- **Student accounts** — teachers hold accounts; learners use playback
  without sign-in. No student video by design.
- **Free-form machine invention** — designs come from the parameterised
  platform library, not arbitrary generated morphology.
- **NECO marketing claims** — NECO template references are added only
  after validation against the NECO syllabus.
- **ISO certification/compliance claims** — the safety design *aligns to*
  ISO 10218 / ISO/TS 15066 principles from public summaries; the standards
  are paid texts and were not read. Nothing may claim certification.
- **Paid anything** — no paid API, subscription, cloud tier, licence or
  certificate is used anywhere in the build (see `docs/SBOM.md`).

## ANTI-PENDULUM CHECKLIST (acceptance rule)

The pendulum is **one instance of a generic `PracticalTemplate`** — exactly
as a titration or a food test will be later. Pendulum specifics live
**only** in template data under `src/mimforge/templates/`.

A design review — and the automated test suite — **FAILS** if any of the
following appear in core (non-template) code, schema, or UI strings:

- [ ] The words `pendulum` or `bob` (in any casing, including inside
      longer identifiers or comments).
- [ ] The symbols `T²` / `T^2` used as a core field, variable or label.
- [ ] The constant of the demo: `9.81`, `9.8` as an expected value, the
      word `gravity`, or the slope formula `4π²/s` in core logic.
- [ ] Demo apparatus names (`retort`, `fiducial`) in core code or schema.
- [ ] Any core field, enum value, or function whose meaning only makes
      sense for the demo practical.
- [ ] Graph-form assumptions (a specific plotted relationship) anywhere
      outside a template's `ObservationSpec` / `graph_spec` data.

Enforcement: `tests/test_anti_pendulum.py` scans every core module under
`src/mimforge/` (excluding `src/mimforge/templates/`) for the forbidden
terms and fails the suite if any are found. The pendulum template itself
is loaded by the tests as **data** and checked against the worked example
— proving the separation rather than asserting it.

Reviewer sign-off for this freeze: ____________________  Date: __________
