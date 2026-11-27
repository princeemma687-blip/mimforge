"""Full spec audit (2026-11-26): the verification pipeline's shape
checks run against the recorded demonstration track when the
project holds one -- the machine-versus-human comparison -- and
say so; without one they run against the simulation and say that.
"""

from __future__ import annotations

import math

from mimforge.templates import load_template, load_template_data
from mimforge.verification import run_verification


def _conical_track(points: int = 240) -> dict:
    """A circular (fully conical) recorded track, in pixels."""
    xs, ys = [], []
    for i in range(points):
        angle = 2 * math.pi * i / 60.0
        xs.append(500.0 + 120.0 * math.cos(angle))
        ys.append(400.0 + 120.0 * math.sin(angle))
    return {"xs_px": xs, "ys_px": ys, "coverage": 1.0}


def test_shape_checks_use_the_recorded_demonstration():
    template = load_template("pendulum")
    data = load_template_data("pendulum")
    outcome = run_verification(
        template, data, teacher_track=_conical_track()
    )
    assert outcome.track_basis == "demonstration"
    assert outcome.engine  # the simulation engine is named
    assert "conical-swing" in outcome.report.check_ids


def test_without_a_demonstration_the_basis_is_simulation():
    template = load_template("pendulum")
    data = load_template_data("pendulum")
    outcome = run_verification(template, data)
    assert outcome.track_basis == "simulation"
    # The simulated clean arc does not flag itself.
    assert "conical-swing" not in outcome.report.check_ids
    assert outcome.report.metrics["planarity_checked"] == 1.0
