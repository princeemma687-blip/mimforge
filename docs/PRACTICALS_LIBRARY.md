# The practicals library

Mimforge ships a **library of practicals**, not a single-purpose
tool (Prince's rule, 2026-11-26: the app must never look like it
was made for one demonstration only). Every practical is a
template — pure DATA in `src/mimforge/templates/*.json` (steps,
apparatus, readings table, graph, formula chain, tolerance,
machine-design hint, tracker colour, discrepancy diagnoses). The
core engine knows only the generic shapes; the anti-leak scans in
`tests/` fail the build if any practical's specifics appear in
core code.

The library today:

| Template | Practical | Analysis shape |
|---|---|---|
| `pendulum` | Simple pendulum: determination of g from period and length | Timed simulation (swing simulated per length; identical table path) |
| `hooke` | Hooke's law: spring constant from extension vs load | Static fit (declared `verification_mode: "static_fit"` in its data) |
| `moments` | Principle of moments: unknown mass from a balanced metre rule | Static fit (same declaration) |

The two shapes are both data-declared. A static practical has no
motion to simulate, so verification judges its readings fit
directly: the recovered constant must land inside the template's
own tolerance band around its expected value, and a second table
measured from a demonstration must agree through the identical
chain. No shape checks are claimed for static practicals.

The Projects picker lists the whole library behind a neutral
prompt — no practical is pre-selected, the loader has no default
template, and a fresh first run shows the library, not any one
practical's project.

## Scorecard — full-engine proof, 2026-11-27

Each practical was run through the full engine on synthetic
demonstration footage with known ground truth: improved colour
tracker (at the app's own import stride, 5) → measured readings
table at bench precision → the template's own fit → machine
design stage (platform built, BOM priced at all three tiers,
panel laid out from the template's control list, panel code
generated) → verification. Reproduce with
`PYTHONPATH=src:. python -m experiments.library_proof.run_proof`
(raw record: `experiments/library_proof/output/scorecard.json`;
the pendulum's recovered value comes from re-running its standing
proof, `experiments/pendulum_proof`, in the same session).

| Practical | Ground truth | Worked table recovers | Filmed (measured) table recovers | Error vs truth | Tracker measured coverage | Verification |
|---|---|---|---|---|---|---|
| Pendulum — g | 9.81 m/s² | 9.821 m/s² | **9.796 m/s²** | **−0.14%** | 1.0000 (90 cm clip, 132/132 examined frames) | PASS (band ±5%) |
| Hooke — spring constant k | 25.0 N/m | 25.09 N/m | **24.898 N/m** | **−0.41%** | 1.0000 min & mean (6 clips) | PASS (band ±5%) |
| Moments — unknown mass | 80.0 g | 80.16 g | **80.0 g** | **−0.00%** | 1.0000 min & mean (5 clips) | PASS (band ±5%) |

Reading the moments row honestly: its settled marker positions
landed within the 0.1 cm bench rounding of the true balance
points, so the recorded table is exact and the error rounds to
zero — excellent tracking, but the headline flatters it. The
pendulum's −0.14% is the smallest *earned* error: it is dominated
by real physics (the 8° release amplitude lengthens the true
period), not by rounding, and it is confirmed by a second,
independent path — the MuJoCo simulation recovers the same
9.796 m/s² through the identical table path. Hooke's −0.41% is
honest bench scatter across five loads, twelve times inside its
band.

Machine-design stage, per practical (same bench platform, priced
identically — the template-specific output is the panel and its
code): pendulum panel 6 controls / 3,687 code chars; Hooke panel
6 controls / 3,478 chars; moments panel 6 controls / 3,281 chars;
BOM totals ₦69,500 / ₦159,000 / ₦359,500 at the three tiers for
each.

## Recommended submission demo: the pendulum

On the evidence, not on incumbency:

1. **Strongest verification.** It is the only practical verified
   by two independent paths (video extraction and physics
   simulation) that agree with each other, plus motion shape
   checks against the demonstration track. The static practicals
   verify through one path each — sound, but thinner.
2. **Best earned accuracy.** −0.14% with a physical, explainable
   error budget; the moments zero is a rounding artefact (above).
3. **It shows the machine working.** A swinging mass is
   continuous, visible motion — the Stage 1 machine view performs
   it in 3D; a sliding marker settling (moments) or a slowly
   stretching spring (Hooke) reads far less on a 3-minute demo
   video.
4. **Coverage is perfect** on its tracked clip (1.0000 measured),
   as on the others — tracking does not separate them; the
   verification depth does.

Runner-up: **Hooke's law** — the most classroom-recognisable
graph of the three and an honest −0.41%; if the pendulum footage
ever underperforms on real hardware, Hooke is the fallback demo.
Moments stays in the library as a full equal — proven, just not
the strongest *demonstration*.

Prince confirms the demo choice at the final stage; this page is
the evidence for that decision.

## Honesty label

All proof footage is synthetic (rendered by the experiment
packages, known ground truth, Linux VM) — the same label the
pendulum proof has always carried. Real filmed practicals on
Prince's hardware remain a final-stage validation, as does the
WAEC teacher sign-off on each template's syllabus references
(the two new templates' references are marked unverified in
their data until then — see `docs/TEACHER_VALIDATION.md`).
