"""Verification pipeline (plan Phase 4, shell wiring).

Runs the whole Phase 4 judgement for one template in one call, the
way the phase tests drive the pieces by hand:

1. The template's own readings table is fitted and its derived
   formula evaluated -- the demonstrated outcome.
2. The platform simulation is run at each of the table's varied
   values, its periods are turned into the same derived quantity
   through the template's own formula chain, and the identical fit
   recovers the simulated outcome.
3. The discrepancy engine compares the two outcomes inside the
   template's tolerance band and checks the simulated motion's
   shape; the template's diagnosis text is attached to any finding.

Everything specific -- column keys, the formula chain, the expected
value, the tolerance band, the readings themselves -- comes from
template DATA. This module carries no practical-specific knowledge:
it knows the *shape* of an observation spec (a varied quantity, a
timed quantity, a derived quantity, a straight-line fit, a constant
recovered from the slope), never any one practical's values.

Note on the shape checks: when the project holds a recorded
demonstration track (the Author import saves one), the planarity
check compares THAT track against the simulated clean arc -- the
machine-versus-human comparison the platform promises -- and the
outcome says so (``track_basis == "demonstration"``). Until a
demonstration is imported, the shape checks run on the simulated
track itself and the outcome says that too
(``track_basis == "simulation"``): a stand-in, never presented as
a demonstrated comparison. The amplitude check needs swing angles,
which a pixel track cannot honestly give, so it always runs on the
simulated track. The outcome comparison -- demonstrated outcome
versus simulated outcome -- uses the readings table either way,
and the miscount check reads the demonstrated table's residuals.

The second shape: a template whose observation spec declares
``verification_mode == "static_fit"`` describes a practical with
no motion to simulate -- a static readings table whose graph fit
recovers the constant directly. Verification then judges the fit
itself: the recovered value must land inside the template's
tolerance band around its expected value, the fit's residuals are
checked for an outlier row, and when the caller supplies a second
table measured from a demonstration, that table is pushed through
the identical fit and must agree with the worked table and with
the expected value inside the same band. No shape checks apply to
a static practical and none are claimed (``track_basis`` is
``"readings"``, or ``"demonstration"`` when a measured table was
supplied). The mode is template DATA; this module knows the two
shapes, never any one practical.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Optional

from .design import GantryParameters
from .discrepancy import (
    DiscrepancyFinding,
    DiscrepancyReport,
    assess,
    attach_diagnoses,
    check_period_outliers,
    to_verification_run,
)
from .models import PracticalTemplate, VerificationRun
from .outcome import evaluate_derived, evaluate_formula
from .playback import LessonGraph, LessonReplay, LessonTable
from .simulation import SimResult, simulate_suspension

__all__ = [
    "VerificationOutcome",
    "VerificationUnavailable",
    "run_verification",
    "simulated_recovered",
]

# Small-angle release for the simulated runs, in degrees: inside the
# discrepancy engine's amplitude limit, large enough to measure.
RELEASE_DEG = 8.0

# Names the safe formula evaluator provides itself; anything else in
# a formula is a quantity the template defines or the caller passes.
_FORMULA_BUILTINS = {
    "pi", "e", "sqrt", "log", "log10", "exp", "sin", "cos", "tan",
}

# Check id for the static shape's acceptance judgement: the recovered
# constant against the template's own expected value. Templates word
# its diagnosis in their discrepancy_checks data, like any other id.
CHECK_EXPECTED = "outcome-vs-expected"


class VerificationUnavailable(Exception):
    """The template's data does not carry what verification needs."""


@dataclass
class VerificationOutcome:
    """Everything one verification run produces, ready for display
    in the Simulate panel and for assembly into a lesson package."""

    template_id: str
    practical_id: str
    x_key: str
    y_key: str
    band_percent: float
    expected_value: float
    teacher_rows: list[dict] = field(default_factory=list)
    sim_rows: list[dict] = field(default_factory=list)
    teacher_fit: dict = field(default_factory=dict)
    sim_fit: dict = field(default_factory=dict)
    report: Any = None  # discrepancy.DiscrepancyReport
    run: Optional[VerificationRun] = None
    table: Optional[LessonTable] = None
    graph: Optional[LessonGraph] = None
    replay: Optional[LessonReplay] = None
    engine: str = ""
    engine_note: str = ""
    #: What the shape checks were run against: "demonstration"
    #: when a recorded demonstration track was supplied, else
    #: "simulation" (the simulated track standing in for itself).
    #: A static-fit template runs no shape checks: its basis is
    #: "readings" (its worked table alone) or "demonstration" (a
    #: measured table was fitted alongside the worked one).
    track_basis: str = "simulation"

    @property
    def passed(self) -> bool:
        return bool(self.report and self.report.passed)

    @property
    def offset_percent(self) -> float:
        teacher = self.teacher_fit.get("recovered_value", 0.0)
        sim = self.sim_fit.get("recovered_value", 0.0)
        if not teacher:
            return 0.0
        return 100.0 * (sim - teacher) / teacher


# ------------------------------------------------------------ data mining


def _split_formula(formula: str) -> tuple[str, str]:
    """Split ``name = expression`` into (name, expression)."""
    if "=" not in formula:
        raise VerificationUnavailable(
            f"derived quantity is not an assignment: {formula!r}"
        )
    name, expr = formula.split("=", 1)
    return name.strip(), expr.strip()


def _expression_names(expr: str) -> list[str]:
    """Quantity names an expression reads (builtins removed)."""
    try:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise VerificationUnavailable(
            f"derived formula does not parse: {exc}"
        ) from exc
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }
    return sorted(names - _FORMULA_BUILTINS)


def _column_key(columns: list[dict], quantity: str) -> Optional[str]:
    """The readings-table column key for a quantity name: the key is
    the name itself, or the name plus a unit suffix (``name_unit``)."""
    keys = [c["key"] for c in columns]
    if quantity in keys:
        return quantity
    matches = [k for k in keys if k.startswith(quantity + "_")]
    if not matches:
        return None
    return min(matches, key=len)


def _quantity_for_key(chain_names: list[str], key: str) -> Optional[str]:
    """The derived-chain quantity a column key belongs to (longest
    name wins, so a squared quantity beats its own root)."""
    matches = [
        name for name in chain_names
        if key == name or key.startswith(name + "_")
    ]
    if not matches:
        return None
    return max(matches, key=len)


# ------------------------------------------------------- static shape


def _expected_finding(
    recovered: float, expected: float, band: float, *, source: str
) -> Optional[DiscrepancyFinding]:
    """The static shape's acceptance judgement: one fit's recovered
    constant against the template's expected value, inside the
    template's own band. ``source`` names the table in plain words."""
    if not expected:
        return None
    gap = 100.0 * (recovered - expected) / expected
    if abs(gap) <= band:
        return None
    return DiscrepancyFinding(
        check_id=CHECK_EXPECTED,
        metric="recovered_vs_expected_percent",
        value=gap,
        threshold=band,
        detail=(
            f"the {source} recovered {recovered:.3f}, which is "
            f"{gap:+.2f}% from the expected {expected:.3f}, outside "
            f"the +/-{band:.1f}% band"
        ),
    )


def _run_static_verification(
    template: PracticalTemplate,
    template_data: dict[str, Any],
    *,
    columns: list[dict],
    teacher_rows: list[dict],
    derived: list[str],
    x_key: str,
    y_key: str,
    expected: float,
    band: float,
    measured_rows: Optional[list[dict]] = None,
) -> VerificationOutcome:
    """Verify a static-fit template (see the module docstring).

    The worked table is fitted through the template's own formula
    chain and judged against the expected value. A measured table,
    when the caller supplies one, is fitted identically and must
    agree with the worked table and the expected value inside the
    same band -- the two-path judgement the timed shape gets from
    its simulation, with the demonstration in the second seat.
    """
    outcome_formula = derived[-1]
    teacher_fit = evaluate_derived(
        teacher_rows, x_key=x_key, y_key=y_key, formula=outcome_formula
    )
    teacher_value = float(teacher_fit["recovered_value"])
    measured = (
        [dict(r) for r in measured_rows] if measured_rows else None
    )
    second_rows = measured if measured is not None else teacher_rows
    second_fit = (
        evaluate_derived(
            second_rows, x_key=x_key, y_key=y_key, formula=outcome_formula
        )
        if measured is not None
        else teacher_fit
    )
    second_value = float(second_fit["recovered_value"])

    findings: list[DiscrepancyFinding] = []
    metrics: dict[str, float] = {"shape_checks_run": 0.0}
    found = _expected_finding(
        teacher_value, expected, band, source="worked table"
    )
    if found is not None:
        findings.append(found)
    metrics["recovered_vs_expected_percent"] = (
        100.0 * (teacher_value - expected) / expected if expected else 0.0
    )
    if measured is not None:
        found = _expected_finding(
            second_value, expected, band, source="demonstration table"
        )
        if found is not None:
            findings.append(found)
        offset = (
            100.0 * (second_value - teacher_value) / teacher_value
            if teacher_value
            else 0.0
        )
        metrics["outcome_offset_percent"] = offset
        if abs(offset) > band:
            findings.append(
                DiscrepancyFinding(
                    check_id="length-reference-offset",
                    metric="outcome_offset_percent",
                    value=offset,
                    threshold=band,
                    detail=(
                        f"demonstration table recovered {second_value:.3f} "
                        f"differs from the worked table's {teacher_value:.3f} "
                        f"by {offset:+.2f}%, outside the +/-{band:.1f}% "
                        "band: a systematic offset between the two"
                    ),
                )
            )
        metrics["measured_rows"] = float(len(measured))
    else:
        metrics["outcome_offset_percent"] = 0.0
    outlier = check_period_outliers(
        list(teacher_fit["residuals_percent"])
    )
    if outlier is not None:
        findings.append(outlier)
    metrics["max_abs_residual_percent"] = float(
        teacher_fit["max_abs_residual_percent"]
    )

    report = DiscrepancyReport(
        findings=findings, passed=not findings, metrics=metrics
    )
    attach_diagnoses(report, list(template_data.get("discrepancy_checks") or []))
    run = to_verification_run(
        report,
        run_id=f"verification-{template.id}",
        practical_id=template.practical.id,
    )
    headline = second_value if measured is not None else teacher_value
    run.outcome_result = f"recovered {headline:.3f}"

    table = LessonTable(
        columns=[
            {
                "key": c["key"],
                "label": c.get("label", c["key"]),
                "unit": c.get("unit", ""),
            }
            for c in columns
        ],
        rows=teacher_rows,
    )
    graph = LessonGraph(
        x_label=x_key,
        y_label=y_key,
        points=[
            (float(r[x_key]), float(r[y_key])) for r in teacher_rows
        ],
        slope=float(teacher_fit["slope"]),
        intercept=float(teacher_fit["intercept"]),
        notes="line of best fit",
    )
    if measured is not None:
        basis = "demonstration"
        note = (
            "Static practical: no motion to simulate. The worked table "
            "and a demonstration-measured table were fitted through the "
            "identical formula chain and judged against the template's "
            "expected value inside its tolerance band; no shape checks "
            "apply to a static practical."
        )
    else:
        basis = "readings"
        note = (
            "Static practical: no motion to simulate. The worked "
            "table's fit was judged against the template's expected "
            "value inside its tolerance band; no shape checks apply "
            "to a static practical."
        )
    return VerificationOutcome(
        template_id=template.id,
        practical_id=template.practical.id,
        x_key=x_key,
        y_key=y_key,
        band_percent=float(band),
        expected_value=float(expected),
        teacher_rows=teacher_rows,
        sim_rows=second_rows,
        teacher_fit=teacher_fit,
        sim_fit=second_fit,
        report=report,
        run=run,
        table=table,
        graph=graph,
        replay=None,
        engine="static-fit",
        engine_note=note,
        track_basis=basis,
    )


# -------------------------------------------------------------- pipeline


def run_verification(
    template: PracticalTemplate,
    template_data: dict[str, Any],
    *,
    params: Optional[GantryParameters] = None,
    release_deg: float = RELEASE_DEG,
    length_scale: float = 1.0,
    teacher_track: Optional[dict[str, Any]] = None,
    measured_rows: Optional[list[dict]] = None,
) -> VerificationOutcome:
    """Run the full verification for one template and return every
    artefact the shell needs (fits, report, run record, lesson
    table / graph / replay). Raises VerificationUnavailable when the
    template's data cannot support the run.

    ``measured_rows`` is a second readings table measured from a
    demonstration; only the static-fit shape consumes it (the timed
    shape takes its demonstration evidence as ``teacher_track``)."""
    params = params or GantryParameters()
    spec = template_data.get("observation_spec") or {}
    columns = list(spec.get("columns") or [])
    teacher_rows = [dict(r) for r in (spec.get("rows") or [])]
    derived = list(spec.get("derived_quantities") or [])
    graph_spec = spec.get("graph_spec") or {}
    tolerance = spec.get("tolerance") or {}
    if not columns or not teacher_rows:
        raise VerificationUnavailable(
            "the template carries no readings table to verify against"
        )
    if len(derived) < 2:
        raise VerificationUnavailable(
            "the template carries no derived-quantity chain to evaluate"
        )
    x_key = graph_spec.get("x_quantity")
    y_key = graph_spec.get("y_quantity")
    if not x_key or not y_key:
        raise VerificationUnavailable(
            "the template carries no graph quantities to fit"
        )
    expected = tolerance.get("expected_value")
    band = tolerance.get("band_percent")
    if expected is None or band is None:
        raise VerificationUnavailable(
            "the template carries no expected value / tolerance band"
        )

    if spec.get("verification_mode") == "static_fit":
        return _run_static_verification(
            template,
            template_data,
            columns=columns,
            teacher_rows=teacher_rows,
            derived=derived,
            x_key=x_key,
            y_key=y_key,
            expected=float(expected),
            band=float(band),
            measured_rows=measured_rows,
        )

    chain = derived[:-1]
    outcome_formula = derived[-1]
    chain_names = [_split_formula(f)[0] for f in chain]
    period_name, first_expr = _split_formula(chain[0])
    mean_names = _expression_names(first_expr)
    if len(mean_names) != 1:
        raise VerificationUnavailable(
            "the first derived quantity must read exactly one timed "
            "quantity, so the simulated timings can be aligned with it"
        )
    mean_name = mean_names[0]
    period_key = _column_key(columns, period_name)
    mean_key = _column_key(columns, mean_name)
    y_name = _quantity_for_key(chain_names, y_key)
    if period_key is None or mean_key is None or y_name is None:
        raise VerificationUnavailable(
            "the readings table does not carry the timed / derived "
            "columns the formula chain names"
        )

    # Oscillation count per timing run, from the template's own
    # example readings (mean time / period of the first full row).
    oscillations: Optional[int] = None
    for row in teacher_rows:
        mean_t, period = row.get(mean_key), row.get(period_key)
        if mean_t and period:
            oscillations = int(round(float(mean_t) / float(period)))
            break
    if not oscillations or oscillations < 1:
        raise VerificationUnavailable(
            "the readings table cannot say how many cycles each "
            "timing run covers"
        )

    teacher_fit = evaluate_derived(
        teacher_rows, x_key=x_key, y_key=y_key, formula=outcome_formula
    )

    # Simulate every varied value in the table, then push each
    # simulated period through the template's own formula chain to
    # land on the plotted derived quantity.
    precisions = {
        c["key"]: c.get("precision") for c in columns
    }

    def _round(key: str, value: float) -> float:
        precision = precisions.get(key)
        return round(value, precision) if precision is not None else value

    sims: list[SimResult] = []
    sim_rows: list[dict] = []
    for row in teacher_rows:
        length = float(row[x_key]) * length_scale
        sim = simulate_suspension(
            params,
            length_m=length,
            release_deg=release_deg,
            world_constant=float(expected),
        )
        sims.append(sim)
        variables: dict[str, float] = {
            period_name: sim.period_s,
            mean_name: sim.period_s * oscillations,
        }
        for formula in chain:
            name, _ = _split_formula(formula)
            if name in variables:
                continue
            variables[name] = evaluate_formula(formula, variables)
        sim_rows.append(
            {
                x_key: row[x_key],
                mean_key: _round(mean_key, sim.period_s * oscillations),
                period_key: _round(period_key, sim.period_s),
                y_key: _round(y_key, variables[y_name]),
            }
        )
    sim_fit = evaluate_derived(
        sim_rows, x_key=x_key, y_key=y_key, formula=outcome_formula
    )

    main_sim = max(sims, key=lambda s: s.length_m)
    # Shape checks: against the recorded demonstration track when
    # the project holds one (the serialised track the Author import
    # saved), otherwise against the simulated track itself, with
    # the basis recorded on the outcome either way.
    import numpy as np

    track_basis = "simulation"
    teacher_points = main_sim.track_xy
    if teacher_track:
        xs = list(teacher_track.get("xs_px") or [])
        ys = list(teacher_track.get("ys_px") or [])
        if len(xs) >= 3 and len(xs) == len(ys):
            teacher_points = np.array(
                list(zip(xs, ys)), dtype=float
            )
            track_basis = "demonstration"
    report = assess(
        teacher_points_xy=teacher_points,
        sim_points_xy=main_sim.track_xy,
        teacher_angles_rad=main_sim.angles_rad,
        teacher_value=float(teacher_fit["recovered_value"]),
        sim_value=float(sim_fit["recovered_value"]),
        band_percent=float(band),
        residuals_percent=list(teacher_fit["residuals_percent"]),
    )
    attach_diagnoses(report, list(template_data.get("discrepancy_checks") or []))
    run = to_verification_run(
        report,
        run_id=f"verification-{template.id}",
        practical_id=template.practical.id,
    )
    # The Phase 6 lesson summary carries the recovered value as the
    # outcome line; the pass/fail verdict travels as its own field.
    run.outcome_result = f"recovered {float(sim_fit['recovered_value']):.3f}"

    table = LessonTable(
        columns=[
            {
                "key": c["key"],
                "label": c.get("label", c["key"]),
                "unit": c.get("unit", ""),
            }
            for c in columns
        ],
        rows=teacher_rows,
    )
    graph = LessonGraph(
        x_label=x_key,
        y_label=y_key,
        points=[
            (float(r[x_key]), float(r[y_key])) for r in teacher_rows
        ],
        slope=float(teacher_fit["slope"]),
        intercept=float(teacher_fit["intercept"]),
        notes="line of best fit",
    )
    replay = LessonReplay.from_points(
        main_sim.track_points(),
        label="simulated track",
        sample_hz=200.0,
        x_label="x",
        y_label="y",
    )
    return VerificationOutcome(
        template_id=template.id,
        practical_id=template.practical.id,
        x_key=x_key,
        y_key=y_key,
        band_percent=float(band),
        expected_value=float(expected),
        teacher_rows=teacher_rows,
        sim_rows=sim_rows,
        teacher_fit=teacher_fit,
        sim_fit=sim_fit,
        report=report,
        run=run,
        table=table,
        graph=graph,
        replay=replay,
        engine=main_sim.engine,
        engine_note=main_sim.engine_note,
        track_basis=track_basis,
    )


def simulated_recovered(
    template: PracticalTemplate,
    template_data: dict[str, Any],
    *,
    params: Optional[GantryParameters] = None,
    length_scale: float = 1.0,
) -> float:
    """The simulated outcome alone, at a given length scale -- the
    evaluate step of the bounded auto-adjust loop (the shell adjusts
    the machine's length scale until this value lands on the
    demonstrated outcome inside the template's tolerance band)."""
    outcome = run_verification(
        template,
        template_data,
        params=params,
        length_scale=length_scale,
    )
    return float(outcome.sim_fit["recovered_value"])
