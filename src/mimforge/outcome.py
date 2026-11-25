"""Generic outcome evaluation (plan Phase 4.2/4.3).

A readings table plus a straight-line fit is how many practicals are
marked: plot the derived quantity against the varied quantity, take
the slope, and evaluate a constant from the slope with the formula the
template itself carries (``derived_quantities``). This module knows
nothing about any one practical: it fits whatever (x, y) columns the
caller names, and it evaluates whatever formula string the template
supplies -- through a small safe evaluator that admits only arithmetic
and a fixed set of maths names, never attribute access, calls to
unknown functions, or imports.

The same functions serve the teacher's table, the simulation's table
and the machine's table, so all three are judged identically.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "FormulaError",
    "LinearFit",
    "evaluate_derived",
    "evaluate_formula",
    "linear_fit",
    "table_from_timings",
]


class FormulaError(ValueError):
    """A derived-quantity formula is not a safe arithmetic expression."""


@dataclass
class LinearFit:
    slope: float
    intercept: float
    residuals_percent: list[float] = field(default_factory=list)
    max_abs_residual_percent: float = 0.0


# Names the safe formula evaluator may use, besides the caller-supplied
# variables (slope, intercept, n, ...). No attribute access, no calls
# to anything outside this table.
_SAFE_NAMES: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}


def linear_fit(xs: list[float], ys: list[float]) -> LinearFit:
    """Least-squares straight line through (xs, ys)."""
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("linear_fit needs at least two (x, y) pairs")
    x = np.array(xs, dtype=float)
    y = np.array(ys, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    residuals = 100.0 * (y - fitted) / np.where(fitted == 0, np.nan, fitted)
    residuals = [float(r) for r in residuals]
    return LinearFit(
        slope=float(slope),
        intercept=float(intercept),
        residuals_percent=residuals,
        max_abs_residual_percent=float(np.nanmax(np.abs(residuals))),
    )


def _eval_node(node: ast.AST, variables: dict[str, float]) -> float:
    """Recursive safe evaluation of one AST node."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise FormulaError(f"constant {node.value!r} is not a number")
    if isinstance(node, ast.Name):
        if node.id in variables:
            return float(variables[node.id])
        if node.id in _SAFE_NAMES and isinstance(_SAFE_NAMES[node.id], float):
            return _SAFE_NAMES[node.id]
        raise FormulaError(f"unknown name {node.id!r} in formula")
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise FormulaError(f"operator {type(node.op).__name__} not allowed")
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand, variables)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return +value
        raise FormulaError(f"operator {type(node.op).__name__} not allowed")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise FormulaError("only plain function names may be called")
        fn = _SAFE_NAMES.get(node.func.id)
        if not callable(fn):
            raise FormulaError(f"function {node.func.id!r} is not allowed")
        args = [_eval_node(a, variables) for a in node.args]
        if node.keywords:
            raise FormulaError("keyword arguments are not allowed")
        return float(fn(*args))
    raise FormulaError(f"AST node {type(node).__name__} not allowed in a formula")


def evaluate_formula(formula: str, variables: dict[str, float]) -> float:
    """Evaluate a template-supplied arithmetic formula safely.

    ``formula`` may be a bare expression (``"4 * pi ** 2 / slope"``) or
    an assignment (``"k = 4 * pi ** 2 / slope"``) -- the right-hand
    side is what is evaluated. Anything else raises FormulaError.
    """
    text = formula.strip()
    if "=" in text:
        text = text.split("=", 1)[1].strip()
    # Templates write powers with ^, as a human would; rewrite to **
    # BEFORE parsing, because ^ parses with the wrong precedence
    # (``4 * pi^2`` would group as ``(4 * pi) ^ 2``).
    text = text.replace("^", "**")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"formula does not parse: {exc}") from exc
    return _eval_node(tree, variables)


def table_from_timings(
    x_values: list[float],
    timing_pairs: list[tuple[float, float]],
    *,
    x_key: str,
    t1_key: str,
    t2_key: str,
    mean_key: str,
    period_key: str,
    derived_key: str,
    oscillations: int,
    derived_fn,
    x_precision: int = 3,
    t_precision: int = 1,
    period_precision: int = 2,
    derived_precision: int = 2,
) -> list[dict]:
    """Build readings-table rows from two timing estimates per x value.

    Each pair is (estimate_a, estimate_b) for ``oscillations`` cycles;
    the mean time gives the per-cycle period, and ``derived_fn`` turns
    the period into the plotted derived quantity (e.g. its square).
    Column keys and precisions come from the template's observation
    spec, so the table shape is template data, not code.
    """
    if len(x_values) != len(timing_pairs):
        raise ValueError("one timing pair is needed per x value")
    if oscillations <= 0:
        raise ValueError("oscillations must be positive")
    rows = []
    for x_value, (est_a, est_b) in zip(x_values, timing_pairs):
        t1 = oscillations * est_a
        t2 = oscillations * est_b
        mean_t = 0.5 * (t1 + t2)
        period = mean_t / oscillations
        rows.append(
            {
                x_key: round(float(x_value), x_precision),
                t1_key: round(t1, t_precision),
                t2_key: round(t2, t_precision),
                mean_key: round(mean_t, t_precision),
                period_key: round(period, period_precision),
                derived_key: round(float(derived_fn(period)), derived_precision),
            }
        )
    return rows


def evaluate_derived(
    rows: list[dict],
    *,
    x_key: str,
    y_key: str,
    formula: str,
) -> dict:
    """Fit y against x from the table rows, then evaluate the
    template's derived-constant formula with ``slope``, ``intercept``
    and ``n`` available as variables.

    Returns the fit plus the recovered value, so callers can compare
    the teacher's, the simulation's and the machine's recovered values
    through the identical deduction.
    """
    xs = [float(r[x_key]) for r in rows]
    ys = [float(r[y_key]) for r in rows]
    fit = linear_fit(xs, ys)
    value = evaluate_formula(
        formula,
        {"slope": fit.slope, "intercept": fit.intercept, "n": float(len(rows))},
    )
    return {
        "slope": fit.slope,
        "intercept": fit.intercept,
        "residuals_percent": fit.residuals_percent,
        "max_abs_residual_percent": fit.max_abs_residual_percent,
        "recovered_value": value,
    }
