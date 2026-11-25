# Pendulum proof — first working pipeline proof

**What this is.** The first end-to-end working proof of the Mimforge
pipeline, on the Phase 0 foundation: a demonstration goes in, an
extracted readings table and a recovered constant come out, and a
physics simulation is pushed through the *identical* table/slope path
so the two can be verified against each other and against ground truth
through the generic core schema (`Demonstration`, `ObservationSpec`,
`VerificationRun` in `src/mimforge/models.py`).

**Honesty label — read first.** Everything here is **synthetic**:

- The "demonstration videos" are rendered by this package, not filmed.
  No real camera, no real apparatus, no teacher.
- Everything ran in a **Linux VM** (Python 3.12). **Nothing here has
  been run on Windows**, and nothing here tests the low-spec school-PC
  targets. It proves the *pipeline and the numerics*, not the product
  on real hardware or real footage.
- The pendulum specifics live in this directory and in template data
  only; `src/mimforge` stays generic (the anti-pendulum test in
  `tests/` still passes).

## Pipeline

1. **Generate** (`generate_video.py`) — for each length in the
   template's set (90/80/70/60/50 cm), render a 320x240 @ 30 fps clip
   of a red bob on a plain background. The motion is an RK4 integration
   of the true pendulum equation released from rest at 8°, *not* the
   small-angle sinusoid, so ground truth carries the real amplitude
   effect. Ground truth per length is measured from the full-rate
   angle series.
2. **Extract** (`extract.py`) — the lean, low-spec path: colour
   threshold + mask centroid per frame (no learned model), period from
   interpolated equilibrium crossings of the horizontal track, split
   into two half-run estimates as the analogue of timing twice. Each
   clip becomes a schema `Demonstration` (SHA-256 of the file + the
   timed centroid track).
3. **Simulate** (`simulate.py`) — MuJoCo (Apache-2.0): hinge body,
   mass at distance L, same release angle, 1 ms steps sampled at
   200 Hz. If MuJoCo cannot be imported or run, an RK4 ODE integration
   is used instead and the substitution is **recorded, never silent**
   (see "Fallback" below).
4. **Verify** (`proof.py`) — both paths build readings tables keyed
   exactly to the template's `ObservationSpec` columns, fit the
   straight line, recover the constant from the slope, and produce one
   schema `VerificationRun` whose pass/fail uses the tolerance the
   template itself carries (expected 9.81, band ±5%, target ±3%).

## Run it

```bash
# from the repository root, project venv active
pip install numpy opencv-python-headless mujoco
python experiments/pendulum_proof/run_proof.py            # writes output/
python -m pytest tests/test_pendulum_proof.py             # end-to-end tests
```

## Results (this VM, 2026-11-25)

| Path | Recovered g (m/s²) | Error vs 9.81 | Band |
|---|---|---|---|
| Video extraction (centroid tracking) | **9.796** | **−0.14%** | ±5% (target ±3%) ✅ |
| MuJoCo simulation | **9.796** | **−0.14%** | ±5% (target ±3%) ✅ |

- Both fits: slope 4.030 s²/m, intercept ≈ 0.003 s²; max table residual
  0.14%. The extracted table reproduces the plan's worked-example
  readings (mean t for 20 oscillations: 38.1 / 35.9 / 33.6 / 31.1 /
  28.4 s for L = 90…50 cm).
- Per-length period accuracy vs the true period of the motion:
  extraction ≤ 0.027%, simulation ≤ 0.032%. The two paths agree with
  each other to table precision (their unrounded period estimates
  differ in the third decimal of a percent).
- Error budget: the −0.14% is dominated by physics, not measurement —
  the 8° release amplitude lengthens the true period (~+0.12%), and
  the practical's own small-angle deduction converts that into a
  slightly low g, exactly as a real bench run behaves. Table rounding
  (t to 0.1 s, T² to 0.01 s²) contributes the rest.
- Full test suite: **17 passed** (11 Phase 0 + 6 proof tests), ~6 s.

## Fallback

MuJoCo 4.0.1 installed and ran headless in this VM, so the primary
engine produced the numbers above. The RK4 fallback was separately
exercised by blocking the MuJoCo import: it engaged automatically,
recorded the reason in the run's engine note, and recovered the true
period of the test length exactly (1.9054 s at L = 0.90 m).

## Still unproven (explicitly)

- Real camera footage: lighting, motion blur, occlusion, camera shake,
  non-plain backgrounds, length-setting by hand. The colour threshold
  here works because the synthetic bob is pure red on near-white.
- Windows execution of anything in this directory.
- Performance on the 4 GB RAM school-PC targets.
- Any practical other than this one; any machine output (design,
  codegen, BOM) — this proof covers ingest → extraction → table →
  verification only.
