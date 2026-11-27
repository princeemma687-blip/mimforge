"""Run every library practical's proof and write the scorecard.

    python -m experiments.library_proof.run_proof

Writes ``output/scorecard.json`` beside this file and prints the
scorecard. The pendulum's numbers come from re-running its own
standing proof (``experiments/pendulum_proof``) in the same
session; its tracker coverage is measured by running the improved
colour tracker over that proof's freshly rendered 90 cm clip.
"""

from __future__ import annotations

import json
from pathlib import Path

from mimforge.templates import load_template_data

from . import hooke_proof, moments_proof
from .common import coverage_record, design_evidence, track

HERE = Path(__file__).parent
OUT = HERE / "output"


def pendulum_entry() -> dict:
    from experiments.pendulum_proof.proof import run_proof as _run

    results = _run(OUT / "pendulum")
    video_fit = results["video_fit"]
    recovered = float(video_fit["recovered_value"])
    truth = float(results["ground_truth_value"])
    clip = OUT / "pendulum" / "videos" / "demo_L090cm.mp4"
    result = track(clip, load_template_data("pendulum"))
    cov = coverage_record(result)
    # The template's own worked table, fitted through the generic
    # analysis chain -- the same "worked recovery" the static
    # entries report from their verification outcome.
    from mimforge.outcome import evaluate_derived

    spec = load_template_data("pendulum")["observation_spec"]
    worked = evaluate_derived(
        spec["rows"],
        x_key=spec["graph_spec"]["x_quantity"],
        y_key=spec["graph_spec"]["y_quantity"],
        formula=spec["derived_quantities"][-1],
    )
    return {
        "template": "pendulum",
        "title": load_template_data("pendulum")["practical"]["title"],
        "ground_truth": {"g_m_per_s2": truth},
        "worked_table_recovered": round(
            float(worked["recovered_value"]), 3
        ),
        "measured_rows": results["video_table"],
        "measured_recovered": round(recovered, 3),
        "error_percent_vs_truth": round(
            100.0 * (recovered - truth) / truth, 2
        ),
        "band_percent": float(results["band_percent_from_template"]),
        "verification_passed": bool(results["verification_run"]["passed"]),
        "verification_findings": results["verification_run"]["adjustments"],
        "tracker": {
            "stride": 5,
            "per_clip": [{"file": clip.name, **cov}],
            "min_measured_coverage": cov["measured_coverage"],
            "mean_measured_coverage": cov["measured_coverage"],
            "note": (
                "coverage measured on the 90 cm clip with the improved "
                "tracker; the recovered value comes from the standing "
                "proof's own extraction over all five lengths"
            ),
        },
        "design": design_evidence(load_template_data("pendulum")),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    entries = [
        hooke_proof.run(OUT / "hooke"),
        moments_proof.run(OUT / "moments"),
        pendulum_entry(),
    ]
    scorecard = {"synthetic": True, "entries": entries}
    (OUT / "scorecard.json").write_text(
        json.dumps(scorecard, indent=2), encoding="utf-8"
    )
    for e in entries:
        print(
            f"{e['template']:>9}: recovered {e['measured_recovered']} "
            f"(err {e['error_percent_vs_truth']:+.2f}%, band "
            f"+/-{e['band_percent']:.0f}%) verification "
            f"{'PASS' if e['verification_passed'] else 'FAIL'} "
            f"tracker measured coverage min "
            f"{e['tracker']['min_measured_coverage']:.4f} mean "
            f"{e['tracker']['mean_measured_coverage']:.4f}"
        )
    print(f"scorecard written to {OUT / 'scorecard.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
