"""Discrepancy engine (plan Phase 4.3/4.4).

Compares the teacher's demonstration against the simulation on two
levels:

1. **Trajectory** -- the shape of the motion: is the swing planar
   (ellipticity near zero), is the release amplitude inside the
   small-angle range, and does the simulated track follow the
   demonstrated one?
2. **Outcome** -- the practical's own numbers: does the value the
   simulation recovers agree with the teacher's value inside the
   template's tolerance band, and is any single timing row an outlier
   against its neighbours?

Findings carry a stable ``check_id`` from a small shared vocabulary
(``conical-swing``, ``excess-amplitude``, ``length-reference-offset``,
``oscillation-miscount``). The teacher-facing diagnosis text for each
id lives in template data (``discrepancy_checks``); this module only
decides *which* checks fired, so a new practical can add or reword
its checks without touching the engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .models import VerificationRun

__all__ = [
    "DiscrepancyFinding",
    "DiscrepancyReport",
    "assess",
    "attach_diagnoses",
    "check_amplitude",
    "check_outcome_offset",
    "check_period_outliers",
    "check_planarity",
    "ellipticity",
    "max_amplitude_deg",
]

# Shared finding vocabulary: check_id -> the metric that fires it.
CHECK_CONICAL = "conical-swing"
CHECK_AMPLITUDE = "excess-amplitude"
CHECK_LENGTH_OFFSET = "length-reference-offset"
CHECK_MISCOUNT = "oscillation-miscount"

# Defaults from the plan's worked example: a swing whose transverse
# extent exceeds 15% of its main extent is not planar; a release
# beyond 15 degrees leaves the small-angle range.
DEFAULT_ELLIPTICITY_LIMIT = 0.15
DEFAULT_AMPLITUDE_LIMIT_DEG = 15.0
DEFAULT_OUTLIER_FACTOR = 3.0


@dataclass
class DiscrepancyFinding:
    check_id: str
    metric: str
    value: float
    threshold: float
    detail: str
    diagnosis: str = ""  # filled by attach_diagnoses from template data


@dataclass
class DiscrepancyReport:
    findings: list[DiscrepancyFinding] = field(default_factory=list)
    passed: bool = True
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def check_ids(self) -> list[str]:
        return [f.check_id for f in self.findings]


def ellipticity(points_xy: np.ndarray) -> float:
    """Minor/major axis ratio of the 2-D track (0 = a straight line,
    1 = a circle). Computed from the principal components of the
    centred points, so it needs no assumption about the motion."""
    pts = np.asarray(points_xy, dtype=float)
    if len(pts) < 3:
        return 0.0
    centred = pts - pts.mean(axis=0)
    cov = np.cov(centred.T)
    eig = np.linalg.eigvalsh(cov)
    major = math.sqrt(max(eig[-1], 0.0))
    minor = math.sqrt(max(eig[0], 0.0))
    if major == 0:
        return 0.0
    return float(minor / major)


def max_amplitude_deg(angles_rad: np.ndarray) -> float:
    """Largest absolute swing angle, in degrees."""
    angles = np.asarray(angles_rad, dtype=float)
    if len(angles) == 0:
        return 0.0
    return float(np.degrees(np.max(np.abs(angles))))


def check_planarity(
    points_xy: np.ndarray, *, limit: float = DEFAULT_ELLIPTICITY_LIMIT
) -> DiscrepancyFinding | None:
    value = ellipticity(points_xy)
    if value <= limit:
        return None
    return DiscrepancyFinding(
        check_id=CHECK_CONICAL,
        metric="ellipticity",
        value=value,
        threshold=limit,
        detail=(
            f"track ellipticity {value:.2f} exceeds {limit:.2f}: the motion "
            "is not confined to one vertical plane"
        ),
    )


def check_amplitude(
    angles_rad: np.ndarray, *, limit_deg: float = DEFAULT_AMPLITUDE_LIMIT_DEG
) -> DiscrepancyFinding | None:
    value = max_amplitude_deg(angles_rad)
    if value <= limit_deg:
        return None
    return DiscrepancyFinding(
        check_id=CHECK_AMPLITUDE,
        metric="max_amplitude_deg",
        value=value,
        threshold=limit_deg,
        detail=(
            f"release amplitude {value:.1f} deg exceeds the {limit_deg:.0f} deg "
            "small-angle range: periods will run long"
        ),
    )


def check_outcome_offset(
    teacher_value: float, sim_value: float, *, band_percent: float
) -> DiscrepancyFinding | None:
    """A systematic gap between the demonstrated outcome and the
    simulated one, larger than the template's tolerance band."""
    if teacher_value == 0:
        raise ValueError("teacher_value must be non-zero for an offset check")
    diff_percent = 100.0 * (sim_value - teacher_value) / teacher_value
    if abs(diff_percent) <= band_percent:
        return None
    return DiscrepancyFinding(
        check_id=CHECK_LENGTH_OFFSET,
        metric="outcome_offset_percent",
        value=diff_percent,
        threshold=band_percent,
        detail=(
            f"simulated outcome {sim_value:.3f} differs from the demonstrated "
            f"{teacher_value:.3f} by {diff_percent:+.2f}%, outside the "
            f"+/-{band_percent:.1f}% band: a systematic parameter offset"
        ),
    )


def check_period_outliers(
    residuals_percent: list[float], *, factor: float = DEFAULT_OUTLIER_FACTOR
) -> DiscrepancyFinding | None:
    """One timing row whose fit residual is far larger than the rest
    usually means a miscounted run, not a wrong model."""
    residuals = np.array([abs(r) for r in residuals_percent], dtype=float)
    if len(residuals) < 3:
        return None
    median = float(np.median(residuals))
    worst = int(np.argmax(residuals))
    if residuals[worst] <= 1.0:
        return None
    if median == 0:
        # Every other row fits exactly and one row is off: that is
        # the clearest miscount case there is, and a median of zero
        # must not silence it (any positive residual is infinitely
        # far from a zero median).
        return DiscrepancyFinding(
            check_id=CHECK_MISCOUNT,
            metric="worst_residual_percent",
            value=float(residuals[worst]),
            threshold=0.0,
            detail=(
                f"row {worst} residual {residuals[worst]:.2f}% while "
                "every other row fits exactly: one timing run looks "
                "miscounted"
            ),
        )
    if residuals[worst] > factor * median:
        return DiscrepancyFinding(
            check_id=CHECK_MISCOUNT,
            metric="worst_residual_percent",
            value=float(residuals[worst]),
            threshold=factor * median,
            detail=(
                f"row {worst} residual {residuals[worst]:.2f}% is "
                f"{residuals[worst] / median:.1f}x the median "
                f"({median:.2f}%): one timing run looks miscounted"
            ),
        )
    return None


def assess(
    *,
    teacher_points_xy: np.ndarray,
    sim_points_xy: np.ndarray,
    teacher_angles_rad: np.ndarray | None = None,
    teacher_value: float,
    sim_value: float,
    band_percent: float,
    residuals_percent: list[float] | None = None,
    ellipticity_limit: float = DEFAULT_ELLIPTICITY_LIMIT,
    amplitude_limit_deg: float = DEFAULT_AMPLITUDE_LIMIT_DEG,
) -> DiscrepancyReport:
    """Run every check and return the findings + overall verdict.

    ``teacher_points_xy`` / ``sim_points_xy`` are (n, 2) planar tracks.
    ``teacher_value`` / ``sim_value`` are the outcomes the two paths
    recovered through the identical table pipeline. The simulation's
    own track is checked for planarity too -- a simulation that does
    not swing cleanly is a model fault, not a teacher fault.
    """
    findings: list[DiscrepancyFinding] = []
    metrics: dict[str, float] = {}

    teacher_points = np.asarray(teacher_points_xy, dtype=float)
    metrics["teacher_track_points"] = float(len(teacher_points))
    sim_ell = ellipticity(sim_points_xy)
    metrics["sim_ellipticity"] = sim_ell
    if len(teacher_points) >= 3:
        metrics["planarity_checked"] = 1.0
        teacher_ell = ellipticity(teacher_points)
        metrics["teacher_ellipticity"] = teacher_ell
        # A planar swing traces an arc, not a line, so a clean track has
        # a small but non-zero ellipticity (about 0.035 at an 8-degree
        # release). The check is therefore differential: the teacher's
        # track is flagged only when it is *more* elliptical than the
        # simulation's clean arc by more than the limit.
        ell_gap = teacher_ell - sim_ell
        metrics["ellipticity_gap"] = ell_gap
        if ell_gap > ellipticity_limit:
            findings.append(
                DiscrepancyFinding(
                    check_id=CHECK_CONICAL,
                    metric="ellipticity_gap",
                    value=ell_gap,
                    threshold=ellipticity_limit,
                    detail=(
                        f"[teacher] track ellipticity {teacher_ell:.2f} exceeds "
                        f"the simulated clean arc ({sim_ell:.2f}) by "
                        f"{ell_gap:.2f}, over the {ellipticity_limit:.2f} limit: "
                        "the motion is not confined to one vertical plane"
                    ),
                )
            )
    else:
        # Too few points to judge planarity: the check is recorded
        # as not run, never as passed -- a missing track must not
        # read as a clean planar swing.
        metrics["planarity_checked"] = 0.0

    if teacher_angles_rad is not None:
        amp = max_amplitude_deg(teacher_angles_rad)
        metrics["teacher_max_amplitude_deg"] = amp
        found = check_amplitude(teacher_angles_rad, limit_deg=amplitude_limit_deg)
        if found is not None:
            findings.append(found)

    offset = check_outcome_offset(teacher_value, sim_value, band_percent=band_percent)
    metrics["outcome_offset_percent"] = (
        100.0 * (sim_value - teacher_value) / teacher_value if teacher_value else 0.0
    )
    if offset is not None:
        findings.append(offset)

    if residuals_percent:
        found = check_period_outliers(residuals_percent)
        if found is not None:
            findings.append(found)
        metrics["max_abs_residual_percent"] = max(abs(r) for r in residuals_percent)

    return DiscrepancyReport(
        findings=findings,
        passed=not findings,
        metrics=metrics,
    )


def attach_diagnoses(
    report: DiscrepancyReport, template_checks: list[dict]
) -> DiscrepancyReport:
    """Fill each finding's ``diagnosis`` from the template's
    ``discrepancy_checks`` (``{id, detects, diagnosis}``). A check id
    the template does not carry keeps an empty diagnosis -- the
    finding still stands, it is just worded generically."""
    by_id = {c.get("id"): c.get("diagnosis", "") for c in template_checks}
    for finding in report.findings:
        finding.diagnosis = by_id.get(finding.check_id, "")
    return report


def to_verification_run(
    report: DiscrepancyReport, *, run_id: str, practical_id: str
) -> VerificationRun:
    """Record the assessment in the generic VerificationRun schema."""
    return VerificationRun(
        id=run_id,
        practical_id=practical_id,
        sim_trajectory_ref="",
        discrepancy_metrics=dict(report.metrics),
        outcome_result=(
            "passed" if report.passed else "; ".join(f.detail for f in report.findings)
        ),
        passed=report.passed,
        adjustments=[f.check_id for f in report.findings],
    )
