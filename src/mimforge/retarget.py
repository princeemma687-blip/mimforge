"""Trajectory retargeting: the machine follows the human's path.

The recorded demonstration holds the demonstrator's actual motion
-- a timed track in video pixels. This module maps that path into
the machine's own coordinate frame and produces the trajectory
the machine would follow: the same path shape, inside the current
design's reach envelope, at speeds the safety limits allow.

The mapping is a plain similarity transform, stated openly so the
fidelity numbers mean what they say:

- One uniform scale (mm per pixel), anchored on the vertical:
  the frame's height maps to the suspension range's drop -- the
  direction the machine itself sets and measures. The frame's
  centre maps to the workspace's centre. Horizontally the path
  then lands wherever the design's carriage travel puts it,
  which is exactly what makes reach feasibility a real question
  rather than a foregone conclusion.
- A mapped point outside the workspace is INFEASIBLE. It is
  clamped to the boundary, counted, and its deviation (the
  distance it was moved, in mm) feeds the fidelity report. If
  more than a quarter of the path is infeasible, the retarget
  refuses outright in plain words -- a machine that cannot reach
  a quarter of the path is not following the demonstration.
- Timing: segment speeds are computed from the recorded times.
  If the fastest segment exceeds the safety cap, the whole
  trajectory is time-warped by one uniform factor (the path is
  untouched; only the clock stretches) and the result records
  that honestly. The cap is the safety kernel's own limit value
  (``SafetyLimits.max_tool_speed_mm_s``), so the replay can never
  command a speed the kernel would refuse.

Nothing here touches the safety kernel's state or the recorded
track; the result is data the Simulate surface can show and the
lesson builder can replay.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .design import GantryParameters
from .models import SafetyLimits

#: If more than this fraction of the recorded path falls outside
#: the machine's reach, the retarget refuses instead of clamping.
MAX_CLAMP_FRACTION = 0.25


class RetargetError(Exception):
    """The recorded path cannot be retargeted onto this design.
    The message is plain words for the teacher."""


@dataclass
class RetargetResult:
    """A machine trajectory plus its fidelity report."""

    #: (t_s, x_mm, y_mm): carriage position along the beam and
    #: drop below the suspension range's top, in machine frame.
    points: list[tuple[float, float, float]] = field(default_factory=list)
    feasible_percent: float = 0.0
    clamped_points: int = 0
    total_points: int = 0
    timing_adjusted: bool = False
    warp_factor: float = 1.0
    deviation_mean_mm: float = 0.0
    deviation_max_mm: float = 0.0
    cap_mm_s: float = 250.0
    scale_mm_per_px: float = 0.0
    peak_speed_mm_s: float = 0.0  # after any time warp

    @property
    def timing_note(self) -> str:
        """The honest one-liner the surfaces show."""
        if self.timing_adjusted:
            return (
                "PATH EXACT — TIMING ADJUSTED TO THE SAFETY CAP "
                f"(SLOWED {self.warp_factor:.2f}×)"
            )
        return "PATH AND TIMING EXACT"

    def to_dict(self) -> dict:
        return {
            "points": [[t, x, y] for t, x, y in self.points],
            "feasible_percent": self.feasible_percent,
            "clamped_points": self.clamped_points,
            "total_points": self.total_points,
            "timing_adjusted": self.timing_adjusted,
            "warp_factor": self.warp_factor,
            "deviation_mean_mm": self.deviation_mean_mm,
            "deviation_max_mm": self.deviation_max_mm,
            "cap_mm_s": self.cap_mm_s,
            "scale_mm_per_px": self.scale_mm_per_px,
            "peak_speed_mm_s": self.peak_speed_mm_s,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RetargetResult":
        return cls(
            points=[tuple(p) for p in data.get("points", [])],
            feasible_percent=float(data.get("feasible_percent", 0.0)),
            clamped_points=int(data.get("clamped_points", 0)),
            total_points=int(data.get("total_points", 0)),
            timing_adjusted=bool(data.get("timing_adjusted", False)),
            warp_factor=float(data.get("warp_factor", 1.0)),
            deviation_mean_mm=float(data.get("deviation_mean_mm", 0.0)),
            deviation_max_mm=float(data.get("deviation_max_mm", 0.0)),
            cap_mm_s=float(data.get("cap_mm_s", 250.0)),
            scale_mm_per_px=float(data.get("scale_mm_per_px", 0.0)),
            peak_speed_mm_s=float(data.get("peak_speed_mm_s", 0.0)),
        )


def workspace_envelope(params: GantryParameters) -> tuple[float, float]:
    """The machine's working rectangle, in mm: (travel, drop).

    Travel is the carriage centre's range along the beam (span
    minus both uprights minus the carriage's own width); drop is
    the suspension range the design serves."""
    travel = params.span_mm - 2 * params.section_mm - params.carriage_width_mm
    low, high = params.suspension_range_mm
    drop = high - low
    if travel <= 0 or drop <= 0:
        raise RetargetError(
            "This design has no working space to replay a "
            "demonstration in — check its dimensions."
        )
    return travel, drop


def retarget_track(
    track: dict,
    frame_width: float,
    frame_height: float,
    params: GantryParameters,
    limits: SafetyLimits | None = None,
) -> RetargetResult:
    """Map a recorded demonstration track onto the machine.

    ``track`` is the Demonstration record's serialised track
    (``times_s`` / ``xs_px`` / ``ys_px``). Raises RetargetError in
    plain words when there is no usable path or too much of it
    lies outside this design's reach."""
    limits = limits or SafetyLimits()
    cap = float(limits.max_tool_speed_mm_s)
    times = [float(t) for t in track.get("times_s", [])]
    xs = [float(v) for v in track.get("xs_px", [])]
    ys = [float(v) for v in track.get("ys_px", [])]
    n = min(len(times), len(xs), len(ys))
    if n < 2:
        raise RetargetError(
            "The recorded demonstration has no tracked path to "
            "replay — import a demonstration with tracking first."
        )
    times, xs, ys = times[:n], xs[:n], ys[:n]
    if frame_width <= 0 or frame_height <= 0:
        raise RetargetError(
            "The recorded demonstration does not say how large "
            "its frame was, so its path cannot be measured."
        )
    if max(xs) - min(xs) < 1.0 and max(ys) - min(ys) < 1.0:
        raise RetargetError(
            "The recorded path does not move — there is no "
            "trajectory to follow."
        )
    travel, drop = workspace_envelope(params)
    scale = drop / frame_height

    mapped: list[tuple[float, float, float]] = []
    deviations: list[float] = []
    clamped = 0
    for t, px, py in zip(times, xs, ys):
        x = (px - frame_width / 2.0) * scale + travel / 2.0
        y = (py - frame_height / 2.0) * scale + drop / 2.0
        cx = min(max(x, 0.0), travel)
        cy = min(max(y, 0.0), drop)
        deviation = math.hypot(cx - x, cy - y)
        if deviation > 0.0:
            clamped += 1
        deviations.append(deviation)
        mapped.append((t, cx, cy))
    if clamped / n > MAX_CLAMP_FRACTION:
        raise RetargetError(
            f"Too much of the recorded path lies outside this "
            f"machine's reach — {clamped} of {n} points would have "
            "to be clamped to the edge. A larger design, or a "
            "demonstration framed inside the machine's workspace, "
            "is needed."
        )

    def peak_speed(points) -> float:
        peak = 0.0
        for (t0, x0, y0), (t1, x1, y1) in zip(points, points[1:]):
            dt = t1 - t0
            if dt <= 0:
                continue
            peak = max(peak, math.hypot(x1 - x0, y1 - y0) / dt)
        return peak

    peak = peak_speed(mapped)
    warp = 1.0
    adjusted = False
    if peak > cap > 0:
        warp = peak / cap
        adjusted = True
        mapped = [(t * warp, x, y) for t, x, y in mapped]
        peak = peak_speed(mapped)
    return RetargetResult(
        points=mapped,
        feasible_percent=100.0 * (n - clamped) / n,
        clamped_points=clamped,
        total_points=n,
        timing_adjusted=adjusted,
        warp_factor=warp,
        deviation_mean_mm=(
            sum(deviations) / len(deviations) if deviations else 0.0
        ),
        deviation_max_mm=max(deviations) if deviations else 0.0,
        cap_mm_s=cap,
        scale_mm_per_px=scale,
        peak_speed_mm_s=peak,
    )
