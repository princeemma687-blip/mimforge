"""Phase 4.3 (T4.3): the discrepancy engine flags the flawed run with
the correct diagnosis, passes the clean run, and catches a systematic
length offset. Trajectories here are synthesised from the same
oscillator the simulation uses, so the checks are exercised on known
good / known bad motion -- a real flawed video is still an open item.
"""

import math

import numpy as np
import pytest

from mimforge.design import GantryParameters
from mimforge.discrepancy import (
    CHECK_CONICAL,
    CHECK_LENGTH_OFFSET,
    CHECK_MISCOUNT,
    assess,
    attach_diagnoses,
    check_outcome_offset,
    check_period_outliers,
    check_planarity,
    ellipticity,
    to_verification_run,
)
from mimforge.outcome import evaluate_derived, table_from_timings
from mimforge.simulation import simulate_suspension
from mimforge.templates import load_template_data

LENGTHS_M = [0.90, 0.80, 0.70, 0.60, 0.50]
WORLD_CONSTANT = 9.81


def _planar_track(length_m=0.9, release_deg=8.0, seconds=12.0, hz=200):
    """A clean planar swing: x = L sin(theta(t)), y = -L cos(theta(t))."""
    result = simulate_suspension(
        GantryParameters(),
        length_m=length_m,
        release_deg=release_deg,
        world_constant=WORLD_CONSTANT,
        duration_s=seconds,
    )
    return result


def _conical_track(seconds=12.0, hz=200):
    """A deliberately flawed swing: the load traces an ellipse
    (transverse extent 40% of the main extent) instead of a line."""
    t = np.arange(0, seconds, 1.0 / hz)
    omega = 2.0 * math.pi / 1.9
    x = 0.15 * np.cos(omega * t)
    y = 0.06 * np.sin(omega * t)
    return np.column_stack((x, y)), t


@pytest.fixture(scope="module")
def template():
    return load_template_data("pendulum")


def test_clean_run_passes_all_checks(template):
    sim = _planar_track()
    report = assess(
        teacher_points_xy=sim.track_xy,
        sim_points_xy=sim.track_xy,
        teacher_angles_rad=sim.angles_rad,
        teacher_value=9.80,
        sim_value=9.80,
        band_percent=5.0,
    )
    assert report.passed
    assert report.findings == []
    # A planar swing traces an arc: small ellipticity, not zero.
    assert report.metrics["teacher_ellipticity"] == pytest.approx(0.035, abs=0.01)
    assert report.metrics["ellipticity_gap"] == pytest.approx(0.0, abs=1e-9)


def test_conical_run_is_flagged_with_the_template_diagnosis(template):
    """T4.3 (flawed run): the elliptical track fires conical-swing,
    and the template's own diagnosis text is attached."""
    conical_xy, _ = _conical_track()
    assert ellipticity(conical_xy) == pytest.approx(0.40, abs=0.02)
    found = check_planarity(conical_xy)
    assert found is not None
    assert found.check_id == CHECK_CONICAL
    sim = _planar_track()
    report = assess(
        teacher_points_xy=conical_xy,
        sim_points_xy=sim.track_xy,
        teacher_value=9.80,
        sim_value=9.80,
        band_percent=5.0,
    )
    assert not report.passed
    assert CHECK_CONICAL in report.check_ids
    attach_diagnoses(report, template["discrepancy_checks"])
    conical = next(f for f in report.findings if f.check_id == CHECK_CONICAL)
    assert "Conical oscillation" in conical.diagnosis


def test_seeded_length_offset_is_flagged(template):
    """T4.3 (systematic error): simulations run 8% long -- a
    miscalibrated length actuator scales every length -- but are
    labelled with the nominal lengths, so the recovered value comes
    out ~7% low: outside the 5% band, so the length-reference-offset
    check fires. (A constant additive offset would only move the
    fit's intercept, not its slope, so it is not the seeded error.)"""
    spec = template["observation_spec"]
    formula = spec["derived_quantities"][2]
    band = spec["tolerance"]["band_percent"]
    teacher_rows = spec["rows"]
    teacher = evaluate_derived(
        teacher_rows, x_key="L_m", y_key="T2_s2", formula=formula
    )
    pairs = []
    for length_m in LENGTHS_M:
        result = simulate_suspension(
            GantryParameters(),
            length_m=length_m * 1.08,  # seeded 8% proportional offset
            release_deg=8.0,
            world_constant=WORLD_CONSTANT,
        )
        pairs.append(result.period_pair)
    rows = table_from_timings(
        LENGTHS_M,
        pairs,
        x_key="L_m",
        t1_key="t1_s",
        t2_key="t2_s",
        mean_key="mean_t_s",
        period_key="T_s",
        derived_key="T2_s2",
        oscillations=20,
        derived_fn=lambda period: period * period,
    )
    sim = evaluate_derived(rows, x_key="L_m", y_key="T2_s2", formula=formula)
    assert sim["recovered_value"] < teacher["recovered_value"]
    found = check_outcome_offset(
        teacher["recovered_value"], sim["recovered_value"], band_percent=band
    )
    assert found is not None
    assert found.check_id == CHECK_LENGTH_OFFSET
    attach_diagnoses(
        assess(
            teacher_points_xy=_planar_track().track_xy,
            sim_points_xy=_planar_track().track_xy,
            teacher_value=teacher["recovered_value"],
            sim_value=sim["recovered_value"],
            band_percent=band,
        ),
        template["discrepancy_checks"],
    )


def test_period_outlier_row_is_flagged_as_miscount():
    residuals = [0.2, 0.3, 0.1, 4.5, 0.2]  # one row far from the rest
    found = check_period_outliers(residuals)
    assert found is not None
    assert found.check_id == CHECK_MISCOUNT
    assert check_period_outliers([0.2, 0.3, 0.1, 0.2, 0.25]) is None


def test_verification_run_records_the_assessment(template):
    sim = _planar_track()
    report = assess(
        teacher_points_xy=sim.track_xy,
        sim_points_xy=sim.track_xy,
        teacher_value=9.80,
        sim_value=9.80,
        band_percent=5.0,
    )
    run = to_verification_run(report, run_id="run-1", practical_id="demo")
    assert run.passed is True
    assert run.practical_id == "demo"
    assert run.discrepancy_metrics["teacher_ellipticity"] == pytest.approx(
        0.035, abs=0.01
    )
