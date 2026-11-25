"""Bounded auto-adjust loop (plan Phase 4.4).

After the discrepancy engine flags a systematic gap, the loop tries
to close it by adjusting the machine's parameters -- never the
teacher's readings, and never silently. Each iteration re-runs the
evaluation (a simulation, or a measurement) with the adjusted
parameters. The loop stops as soon as the outcome lands inside the
tolerance band, after ``max_iterations`` attempts, or when an
adjustment step changes nothing. The result always says plainly
whether the error was fixed or is still open -- a run that cannot be
fixed is reported as unfixable, never passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = ["AdjustmentAttempt", "AdjustmentResult", "auto_adjust"]


@dataclass
class AdjustmentAttempt:
    iteration: int
    parameters: dict[str, Any]
    outcome: float
    within_tolerance: bool


@dataclass
class AdjustmentResult:
    fixed: bool
    attempts: list[AdjustmentAttempt] = field(default_factory=list)
    final_parameters: dict[str, Any] = field(default_factory=dict)
    message: str = ""


def auto_adjust(
    initial_parameters: dict[str, Any],
    *,
    evaluate: Callable[[dict[str, Any]], float],
    adjust: Callable[[dict[str, Any], float, float], dict[str, Any]],
    target: float,
    band_percent: float,
    max_iterations: int = 3,
) -> AdjustmentResult:
    """Try to bring ``evaluate(parameters)`` within ``band_percent``
    of ``target``.

    ``evaluate`` runs the model/measurement for a parameter set and
    returns the outcome value. ``adjust`` proposes the next parameter
    set from (current parameters, observed outcome, target). Both are
    caller-supplied: the loop itself knows no physics, only the
    stopping rules.
    """
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    if target == 0:
        raise ValueError("target must be non-zero for a percent band")
    if band_percent < 0:
        raise ValueError("band_percent must not be negative")

    parameters = dict(initial_parameters)
    attempts: list[AdjustmentAttempt] = []
    for iteration in range(1, max_iterations + 1):
        outcome = evaluate(parameters)
        within = abs(100.0 * (outcome - target) / target) <= band_percent
        attempts.append(
            AdjustmentAttempt(
                iteration=iteration,
                parameters=dict(parameters),
                outcome=outcome,
                within_tolerance=within,
            )
        )
        if within:
            return AdjustmentResult(
                fixed=True,
                attempts=attempts,
                final_parameters=dict(parameters),
                message=(
                    f"fixed in {iteration} iteration(s): outcome {outcome:.4f} "
                    f"is within +/-{band_percent:.1f}% of target {target:.4f}"
                ),
            )
        if iteration == max_iterations:
            break
        next_parameters = adjust(parameters, outcome, target)
        if next_parameters == parameters:
            return AdjustmentResult(
                fixed=False,
                attempts=attempts,
                final_parameters=dict(parameters),
                message=(
                    "unfixable: the adjustment rule proposes no change, so "
                    "further iterations cannot help"
                ),
            )
        parameters = dict(next_parameters)
    return AdjustmentResult(
        fixed=False,
        attempts=attempts,
        final_parameters=dict(parameters),
        message=(
            f"unfixable after {max_iterations} iteration(s): outcome "
            f"{attempts[-1].outcome:.4f} is still outside "
            f"+/-{band_percent:.1f}% of target {target:.4f}; needs teacher review"
        ),
    )
