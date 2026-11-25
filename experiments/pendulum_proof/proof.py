"""Orchestration: run the whole proof and wire it through the schema.

    synthetic videos -> Demonstration records (extraction)
    MuJoCo/fallback simulation -> identical readings-table path
    both tables + ground truth -> one VerificationRun

The VerificationRun's pass/fail uses the tolerance carried by the
template's own ObservationSpec (expected value + band), read from the
template data -- nothing about the demo is hard-coded here beyond the
experiment's file layout.
"""

from __future__ import annotations

import json
from pathlib import Path

from mimforge.models import VerificationRun
from mimforge.templates import load_template, load_template_data, observation_spec_from_data

from .common import G_TRUTH, LENGTHS_M, build_table_rows, percent_error, recover_from_table
from .extract import extract_demonstration
from .generate_video import generate_all
from .simulate import simulate_all


def run_proof(out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    video_dir = out_dir / "videos"
    ground_truth = generate_all(video_dir)
    truth_by_length = {r["length_m"]: r for r in ground_truth["records"]}

    template_data = load_template_data("pendulum")
    template = load_template("pendulum")
    practical = template.practical
    spec = observation_spec_from_data(template_data["observation_spec"])
    expected = spec.tolerance.expected_value
    band = spec.tolerance.band_percent
    spec_column_keys = [c.key for c in spec.columns]

    # --- Path 1: extraction from the synthetic demonstration videos ---
    demonstrations = []
    video_pairs = []
    video_period_errors = []
    for length_m in LENGTHS_M:
        record = truth_by_length[length_m]
        demo, analysis, pair = extract_demonstration(
            video_dir / record["video_file"],
            length_m,
            demo_id=f"synthetic-demo-L{int(round(100 * length_m))}cm",
            practical_id=practical.id,
        )
        demonstrations.append(demo)
        video_pairs.append(pair)
        video_period_errors.append(
            percent_error(analysis["period_s"], record["true_period_s"])
        )
    video_rows = build_table_rows(LENGTHS_M, video_pairs)
    video_fit = recover_from_table(video_rows)

    # --- Path 2: simulation through the identical table path ---
    sim_records, sim_engine, sim_engine_note = simulate_all(LENGTHS_M)
    sim_rows = build_table_rows(LENGTHS_M, [r["period_pair"] for r in sim_records])
    sim_fit = recover_from_table(sim_rows)
    sim_period_errors = [
        percent_error(r["period_s"], truth_by_length[r["length_m"]]["true_period_s"])
        for r in sim_records
    ]

    # --- Verification: extraction vs simulation vs ground truth ---
    video_err = percent_error(video_fit["recovered_value"], expected)
    sim_err = percent_error(sim_fit["recovered_value"], expected)
    cross_diff = percent_error(video_fit["recovered_value"], sim_fit["recovered_value"])
    passed = abs(video_err) <= band and abs(sim_err) <= band

    adjustments: list[str] = []
    checks = {c["id"]: c for c in template_data.get("discrepancy_checks", [])}
    worst_residual = max(
        video_fit["max_abs_residual_percent"], sim_fit["max_abs_residual_percent"]
    )
    if worst_residual > 2.0 and "oscillation-miscount" in checks:
        adjustments.append(checks["oscillation-miscount"]["diagnosis"])

    verification = VerificationRun(
        id="pendulum-proof-run-001",
        practical_id=practical.id,
        sim_trajectory_ref=(
            f"simulation engine: {sim_engine}"
            + (f" ({sim_engine_note})" if sim_engine_note else "")
        ),
        discrepancy_metrics={
            "video_recovered_percent_error": video_err,
            "sim_recovered_percent_error": sim_err,
            "video_vs_sim_percent_diff": cross_diff,
            "video_max_period_error_percent": max(
                abs(e) for e in video_period_errors
            ),
            "sim_max_period_error_percent": max(abs(e) for e in sim_period_errors),
            "video_max_table_residual_percent": video_fit["max_abs_residual_percent"],
            "sim_max_table_residual_percent": sim_fit["max_abs_residual_percent"],
        },
        outcome_result=(
            f"video path recovered {video_fit['recovered_value']:.3f} "
            f"({video_err:+.2f}% vs expected {expected}); simulation path "
            f"recovered {sim_fit['recovered_value']:.3f} ({sim_err:+.2f}%); "
            f"band +/-{band}% -> {'PASS' if passed else 'FAIL'}"
        ),
        passed=passed,
        adjustments=adjustments,
    )

    results = {
        "experiment": "pendulum_proof",
        "synthetic": True,
        "ground_truth_value": G_TRUTH,
        "expected_value_from_template": expected,
        "band_percent_from_template": band,
        "observation_spec_column_keys": spec_column_keys,
        "video_table": video_rows,
        "video_fit": video_fit,
        "sim_table": sim_rows,
        "sim_fit": sim_fit,
        "sim_engine": sim_engine,
        "sim_engine_note": sim_engine_note,
        "ground_truth_records": ground_truth["records"],
        "demonstrations": [
            {
                "id": d.id,
                "practical_id": d.practical_id,
                "video_hash": d.video_hash,
                "n_track_points": len(d.trajectories[0].points),
            }
            for d in demonstrations
        ],
        "verification_run": {
            "id": verification.id,
            "practical_id": verification.practical_id,
            "sim_trajectory_ref": verification.sim_trajectory_ref,
            "discrepancy_metrics": verification.discrepancy_metrics,
            "outcome_result": verification.outcome_result,
            "passed": verification.passed,
            "adjustments": verification.adjustments,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    # Keep the objects reachable for tests/inspection without re-running.
    results["_objects"] = {
        "demonstrations": demonstrations,
        "observation_spec": spec,
        "verification_run": verification,
        "template": template,
    }
    return results
