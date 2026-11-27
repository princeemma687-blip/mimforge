# Library proof — every practical in the library, through the full engine

**What this is.** The pendulum has its own standing proof in
`experiments/pendulum_proof/`. This package gives the rest of the
template library the same treatment, so no practical in the
library is a paper entry: each one is run end to end —

1. **Generate** — a synthetic demonstration video is rendered with
   known ground truth (the rendered spring obeys Hooke's law with
   an exact constant; the rendered balance obeys the principle of
   moments with an exact unknown mass).
2. **Track** — the app's improved colour tracker
   (`mimforge.perception.track_object`) follows the practical's
   filmed marker at the app's own import stride
   (`config.LEAN_PROFILE.keyframe_stride` = 5), and its coverage
   record is kept per clip.
3. **Analyse** — the settled marker position becomes a measured
   readings table at bench precision, fitted through the
   template's own derived-quantity chain
   (`mimforge.outcome.evaluate_derived`).
4. **Design** — the machine-design stage runs for the template:
   the platform design is built, the BOM is priced at all three
   tiers, the control panel is laid out from the template's own
   control list, and the panel code is generated.
5. **Verify** — `mimforge.verification.run_verification` judges
   the measured table against the template's worked table and its
   expected value, inside the template's own tolerance band (the
   static-fit shape the two static templates declare in their
   data).

**Honesty label.** Everything here is **synthetic**: the videos
are rendered by this package, not filmed; there is no real camera,
apparatus or teacher; everything ran in a Linux VM. It proves the
pipeline and the numerics for each library practical, not the
product on real hardware or real footage. Practical specifics live
in this directory and in template data only; `src/mimforge` stays
generic (the anti-leak scans in `tests/` still pass).

## Run it

```bash
# from the repository root, project venv active
PYTHONPATH=src:. python -m experiments.library_proof.run_proof
# writes output/scorecard.json and prints the scorecard
python -m pytest tests/test_library_proof.py   # reduced-size runs
```

The scorecard from the full run lives in
`docs/PRACTICALS_LIBRARY.md`.
