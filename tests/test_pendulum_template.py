"""The pendulum template (data) must match the plan's worked example
(section 5.1): lengths 90-50 cm, the published readings, T^2 vs L graph,
and a recovered g inside the acceptance band.
"""

import math

import pytest

from mimforge.templates import load_template_data

EXPECTED_LENGTHS_CM = [90.0, 80.0, 70.0, 60.0, 50.0]
EXPECTED_MEAN_T = [38.1, 35.9, 33.6, 31.1, 28.4]
EXPECTED_T2 = [3.63, 3.22, 2.82, 2.42, 2.02]
OSCILLATIONS = 20


@pytest.fixture(scope="module")
def spec():
    return load_template_data("pendulum")["observation_spec"]


def test_lengths_are_the_waec_set_90_down_to_50(spec):
    rows = spec["rows"]
    assert [r["L_cm"] for r in rows] == EXPECTED_LENGTHS_CM
    assert [r["L_m"] for r in rows] == [0.9, 0.8, 0.7, 0.6, 0.5]


def test_readings_match_the_worked_example(spec):
    rows = spec["rows"]
    assert [r["mean_t_s"] for r in rows] == EXPECTED_MEAN_T
    assert [r["T2_s2"] for r in rows] == EXPECTED_T2
    for r in rows:
        # mean of the two timings, and T derived from the mean
        assert r["mean_t_s"] == pytest.approx((r["t1_s"] + r["t2_s"]) / 2)
        assert r["T_s"] == pytest.approx(r["mean_t_s"] / OSCILLATIONS, abs=0.01)
        assert r["T2_s2"] == pytest.approx(
            (r["mean_t_s"] / OSCILLATIONS) ** 2, abs=0.01
        )


def test_graph_is_t_squared_against_l(spec):
    graph = spec["graph_spec"]
    assert graph["y_quantity"] == "T2_s2"
    assert graph["x_quantity"] == "L_m"
    column_keys = {c["key"] for c in spec["columns"]}
    assert {"L_cm", "L_m", "t1_s", "t2_s", "mean_t_s", "T_s", "T2_s2"} == column_keys


def test_worked_result_recovers_g_inside_acceptance_band(spec):
    result = spec["worked_result"]
    (x1, y1), (x2, y2) = result["slope_points"]
    slope = (y2 - y1) / (x2 - x1)
    assert slope == pytest.approx(result["slope"], abs=0.01)
    g = 4 * math.pi**2 / slope
    assert g == pytest.approx(result["derived_constant"], abs=0.1)
    expected = spec["tolerance"]["expected_value"]
    band = spec["tolerance"]["band_percent"]
    assert abs(g - expected) / expected * 100 <= band


def test_two_creditworthy_precautions_present():
    data = load_template_data("pendulum")
    assert len(data["precautions"]) == 2
    joined = " ".join(data["precautions"]).lower()
    assert "conical" in joined
    assert "fiducial" in joined
