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

Note on the shape checks: at this stage there is no recorded
demonstration track, so the planarity / amplitude checks run on the
simulated track itself (the clean-run pattern the Phase 4 tests
use); the substantive comparison -- demonstrated outcome versus
simulated outcome -- uses the template's readings table.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Optional

from .design import GantryParameters
from .discrepancy import assess, attach_diagnoses, to_verification_run
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


# -------------------------------------------------------------- pipeline


def run_verification(
    template: PracticalTemplate,
    template_data: dict[str, Any],
    *,
    params: Optional[GantryParameters] = None,
    release_deg: float = RELEASE_DEG,
    length_scale: float = 1.0,
) -> VerificationOutcome:
    """Run the full verification for one template and return every
    artefact the shell needs (fits, report, run record, lesson
    table / graph / replay). Raises VerificationUnavailable when the
    template's data cannot support the run."""
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
    report = assess(
        teacher_points_xy=main_sim.track_xy,
        sim_points_xy=main_sim.track_xy,
        teacher_angles_rad=main_sim.angles_rad,
        teacher_value=float(teacher_fit["recovered_value"]),
        sim_value=float(sim_fit["recovered_value"]),
        band_percent=float(band),
        residuals_percent=list(sim_fit["residuals_percent"]),
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
