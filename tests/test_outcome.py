"""Phase 4.2/4.3, outcome pipeline: the generic table -> fit -> constant
path. Uses the template's own rows and formula, so the teacher's table,
the simulation's table and the machine's table are all judged by the
identical deduction.
"""

import math

import pytest

from mimforge.outcome import (
    FormulaError,
    evaluate_derived,
    evaluate_formula,
    linear_fit,
    table_from_timings,
)
from mimforge.templates import load_template_data

LENGTHS_M = [0.90, 0.80, 0.70, 0.60, 0.50]
# Two timing estimates per length, from the template's worked rows
# (mean_t / 20, split into two close runs).
PERIOD_PAIRS = [
    (38.2 / 20, 38.0 / 20),
    (36.0 / 20, 35.8 / 20),
    (33.7 / 20, 33.5 / 20),
    (31.2 / 20, 31.0 / 20),
    (28.5 / 20, 28.3 / 20),
]


@pytest.fixture(scope="module")
def template():
    return load_template_data("pendulum")


def test_table_from_timings_reproduces_the_template_rows(template):
    rows = table_from_timings(
        LENGTHS_M,
        PERIOD_PAIRS,
        x_key="L_m",
        t1_key="t1_s",
        t2_key="t2_s",
        mean_key="mean_t_s",
        period_key="T_s",
        derived_key="T2_s2",
        oscillations=20,
        derived_fn=lambda period: period * period,
    )
    expected = template["observation_spec"]["rows"]
    assert len(rows) == len(expected) == 5
    for got, want in zip(rows, expected):
        assert got["L_m"] == want["L_m"]
        assert got["mean_t_s"] == pytest.approx(want["mean_t_s"], abs=0.05)
        assert got["T2_s2"] == pytest.approx(want["T2_s2"], abs=0.01)


def test_linear_fit_recovers_the_worked_example_slope(template):
    rows = template["observation_spec"]["rows"]
    fit = linear_fit([r["L_m"] for r in rows], [r["T2_s2"] for r in rows])
    assert fit.slope == pytest.approx(4.03, abs=0.02)  # plan's worked slope
    assert fit.max_abs_residual_percent < 1.0


def test_evaluate_derived_uses_the_template_formula(template):
    rows = template["observation_spec"]["rows"]
    formula = template["observation_spec"]["derived_quantities"][2]
    assert formula.startswith("g =")
    result = evaluate_derived(rows, x_key="L_m", y_key="T2_s2", formula=formula)
    assert result["recovered_value"] == pytest.approx(9.81, rel=0.005)
    assert result["slope"] == pytest.approx(4.03, abs=0.02)


def test_evaluate_formula_accepts_plain_and_assignment_forms():
    variables = {"slope": 4.03, "intercept": 0.01, "n": 5.0}
    assert evaluate_formula("4 * pi ** 2 / slope", variables) == pytest.approx(
        4 * math.pi**2 / 4.03, rel=1e-9
    )
    assert evaluate_formula("g = 4 * pi ** 2 / slope", variables) == pytest.approx(
        4 * math.pi**2 / 4.03, rel=1e-9
    )
    # Templates write powers with ^, as a human would.
    assert evaluate_formula("4 * pi^2 / slope", variables) == pytest.approx(
        4 * math.pi**2 / 4.03, rel=1e-9
    )
    assert evaluate_formula("sqrt(slope) + 1", variables) == pytest.approx(
        math.sqrt(4.03) + 1, rel=1e-9
    )


def test_evaluate_formula_rejects_hostile_expressions():
    variables = {"slope": 4.03}
    for hostile in (
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "slope.__class__",
        "(lambda: 1)()",
        "eval('1')",
        "slope + unknown_name",
    ):
        with pytest.raises(FormulaError):
            evaluate_formula(hostile, variables)


def test_linear_fit_needs_two_points():
    with pytest.raises(ValueError):
        linear_fit([1.0], [2.0])
    with pytest.raises(ValueError):
        table_from_timings(
            [1.0],
            [(1.0, 1.0), (2.0, 2.0)],
            x_key="x",
            t1_key="t1",
            t2_key="t2",
            mean_key="m",
            period_key="T",
            derived_key="y",
            oscillations=20,
            derived_fn=lambda p: p,
        )
