"""Phase 4.2 (T4.2, the credibility test): the MuJoCo gantry model,
built from the SAME parameters as the CAD, recovers the constant
within +/-3% through the identical table -> graph -> slope pipeline
the teacher's readings use.
"""

import pytest

from mimforge.design import GantryParameters
from mimforge.outcome import evaluate_derived, table_from_timings
from mimforge.simulation import simulate_suspension
from mimforge.templates import load_template_data

LENGTHS_M = [0.90, 0.80, 0.70, 0.60, 0.50]
RELEASE_DEG = 8.0
WORLD_CONSTANT = 9.81  # the value the simulated world is built with
OSCILLATIONS = 20


@pytest.fixture(scope="module")
def template():
    return load_template_data("pendulum")


def test_mujoco_engine_runs_not_the_fallback():
    result = simulate_suspension(
        GantryParameters(),
        length_m=0.90,
        release_deg=RELEASE_DEG,
        world_constant=WORLD_CONSTANT,
    )
    assert result.engine == "mujoco", result.engine_note
    assert result.period_s == pytest.approx(1.906, abs=0.01)


def test_simulated_periods_recover_the_constant_within_3_percent(template):
    """T4.2: simulate all five lengths, build the readings table with
    the core pipeline, fit the line, evaluate the template's formula.
    """
    spec = template["observation_spec"]
    formula = spec["derived_quantities"][2]
    band = spec["tolerance"]["target_band_percent"]
    pairs = []
    for length_m in LENGTHS_M:
        result = simulate_suspension(
            GantryParameters(),
            length_m=length_m,
            release_deg=RELEASE_DEG,
            world_constant=WORLD_CONSTANT,
        )
        assert result.engine == "mujoco", result.engine_note
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
        oscillations=OSCILLATIONS,
        derived_fn=lambda period: period * period,
    )
    recovered = evaluate_derived(rows, x_key="L_m", y_key="T2_s2", formula=formula)
    error_percent = 100.0 * (recovered["recovered_value"] - WORLD_CONSTANT) / WORLD_CONSTANT
    assert abs(error_percent) <= band, (
        f"recovered {recovered['recovered_value']:.3f} is "
        f"{error_percent:+.2f}% from {WORLD_CONSTANT} (band +/-{band}%)"
    )
    assert recovered["max_abs_residual_percent"] < 1.0


def test_simulation_track_is_planar():
    """The simulated swing stays in one vertical plane: its track is
    an arc, so its ellipticity is small (about 0.035 at an 8-degree
    release) but not zero -- the discrepancy engine compares against
    this value rather than demanding zero."""
    import numpy as np

    from mimforge.discrepancy import ellipticity

    result = simulate_suspension(
        GantryParameters(),
        length_m=0.70,
        release_deg=RELEASE_DEG,
        world_constant=WORLD_CONSTANT,
    )
    assert ellipticity(result.track_xy) == pytest.approx(0.035, abs=0.01)
    assert len(result.times_s) > 1000  # sampled at 200 Hz over ~23 s
    assert np.max(np.abs(result.angles_rad)) == pytest.approx(
        8.0 * 3.141592653589793 / 180.0, abs=1e-3
    )


# ------------------------------------------- full spec audit (2026-11-26)


@pytest.mark.parametrize("bad", [0.0, -9.8, float("nan"), float("inf")])
def test_world_constant_is_validated(bad):
    """A bad world constant is a named validation failure, not a
    ZeroDivisionError / math-domain crash mid-simulation."""
    with pytest.raises(ValueError):
        simulate_suspension(
            GantryParameters(),
            length_m=0.9,
            release_deg=8.0,
            world_constant=bad,
        )
