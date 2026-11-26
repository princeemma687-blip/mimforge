"""MuJoCo simulation of a platform + suspended load (plan Phase 4.2).

The model is built from the SAME parameters as the CAD platform
(``GantryParameters``) plus a suspension length, a release angle and
the world's acceleration constant, which the caller supplies from
template data. The simulated swing is returned as a timed angle
series, from which the period is recovered with the generic
crossing analysis in ``mimforge.perception`` -- the identical
measurement the video path performs.

Primary engine: MuJoCo. Fallback: an independent RK4 integration of
the same one-degree-of-freedom swing equation, sampled at the same
rate. The fallback is never silent: the returned engine record names
what actually ran and, for the fallback, why.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .design import GantryParameters
from .perception import (
    period_from_crossings,
    split_period_estimates,
    upward_crossing_times,
)

__all__ = [
    "SimResult",
    "build_model_xml",
    "simulate_suspension",
]

_SAMPLE_HZ = 200
_DT = 0.001
_STEPS_PER_SAMPLE = int(round(1.0 / (_DT * _SAMPLE_HZ)))  # 5
_XML_PATH = Path(__file__).parent / "templates" / "mujoco_platform.xml"


@dataclass
class SimResult:
    """One simulated swing: timed angle series + period estimates."""

    length_m: float
    release_deg: float
    times_s: np.ndarray
    angles_rad: np.ndarray
    period_s: float
    period_pair: tuple[float, float]
    engine: str  # "mujoco" | "rk4-ode-fallback"
    engine_note: str = ""
    # Planar track of the load (x, y) relative to the pivot, metres,
    # for the discrepancy engine's shape checks.
    track_xy: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))

    def track_points(self) -> list[tuple[float, float, float]]:
        """(t, x, y) points in the generic Trajectory shape."""
        return [
            (float(t), float(x), float(y))
            for t, (x, y) in zip(self.times_s, self.track_xy)
        ]


def build_model_xml(
    params: GantryParameters,
    *,
    length_m: float,
    world_constant: float,
) -> str:
    """Fill the platform model template from CAD parameters.

    ``world_constant`` is the downward acceleration of the simulated
    world (metres per second squared), supplied by the caller from
    template data -- this module carries no assumed value for it.
    """
    params.validate()
    if length_m <= 0:
        raise ValueError("suspension length must be positive")
    template = _XML_PATH.read_text(encoding="utf-8")
    s_mm = params.section_mm
    height_m = params.height_mm / 1000.0
    return template.format(
        accel_z=-world_constant,
        section_half=s_mm / 2000.0,
        upright_half_height=height_m / 2.0,
        upright_x=(params.span_mm - s_mm) / 2000.0,
        beam_half=params.span_mm / 2000.0,
        beam_z=height_m + s_mm / 2000.0,
        pivot_z=height_m,
        length_m=length_m,
    )


def _mujoco_angles(
    xml: str, length_m: float, release_deg: float, duration_s: float
) -> tuple[np.ndarray, np.ndarray]:
    import mujoco

    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    data.qpos[0] = math.radians(release_deg)
    n_steps = int(duration_s / _DT)
    times, angles = [], []
    for i in range(n_steps):
        mujoco.mj_step(model, data)
        if i % _STEPS_PER_SAMPLE == 0:
            times.append(float(data.time))
            angles.append(float(data.qpos[0]))
    return np.array(times), np.array(angles)


def _rk4_angles(
    length_m: float,
    release_deg: float,
    world_constant: float,
    duration_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Fallback engine: RK4 on angle'' = -(k/L) sin(angle) at 1 kHz,
    sampled at _SAMPLE_HZ -- the same motion the video generator in
    the experiment proof integrates, written independently here."""
    dt = 0.001
    n = int(duration_s / dt) + 1
    theta = np.empty(n)
    omega = np.empty(n)
    theta[0] = math.radians(release_deg)
    omega[0] = 0.0

    def accel(th: float) -> float:
        return -(world_constant / length_m) * math.sin(th)

    for i in range(n - 1):
        th, om = theta[i], omega[i]
        k1_th, k1_om = om, accel(th)
        k2_th, k2_om = om + 0.5 * dt * k1_om, accel(th + 0.5 * dt * k1_th)
        k3_th, k3_om = om + 0.5 * dt * k2_om, accel(th + 0.5 * dt * k2_th)
        k4_th, k4_om = om + dt * k3_om, accel(th + dt * k3_th)
        theta[i + 1] = th + dt * (k1_th + 2 * k2_th + 2 * k3_th + k4_th) / 6.0
        omega[i + 1] = om + dt * (k1_om + 2 * k2_om + 2 * k3_om + k4_om) / 6.0
    t = np.arange(n) * dt
    stride = int(round(1.0 / (dt * _SAMPLE_HZ)))
    return t[::stride], theta[::stride]


def _period_pair(times: np.ndarray, angles: np.ndarray) -> tuple[float, tuple[float, float]]:
    crossings = upward_crossing_times(times, angles)
    period, intervals = period_from_crossings(crossings)
    return period, split_period_estimates(intervals)


def simulate_suspension(
    params: GantryParameters,
    *,
    length_m: float,
    release_deg: float,
    world_constant: float,
    duration_s: float | None = None,
) -> SimResult:
    """Simulate one suspension length; return the swing + period.

    ``duration_s`` defaults to 12.5 small-angle periods, long enough
    for two independent half-run period estimates.
    """
    if not math.isfinite(world_constant) or world_constant <= 0:
        raise ValueError(
            "world_constant must be a positive finite number, got "
            f"{world_constant!r}"
        )
    if not math.isfinite(length_m) or length_m <= 0:
        raise ValueError(
            f"length_m must be a positive finite number, got {length_m!r}"
        )
    if duration_s is None:
        small_angle_period = 2.0 * math.pi * math.sqrt(length_m / world_constant)
        duration_s = 12.5 * small_angle_period
    xml = build_model_xml(params, length_m=length_m, world_constant=world_constant)
    try:
        times, angles = _mujoco_angles(xml, length_m, release_deg, duration_s)
        engine, note = "mujoco", ""
    except Exception as exc:  # import failure, model failure, GL, ...
        times, angles = _rk4_angles(length_m, release_deg, world_constant, duration_s)
        engine = "rk4-ode-fallback"
        note = f"MuJoCo unavailable ({type(exc).__name__}: {exc}); RK4 ODE used."
    period, pair = _period_pair(times, angles)
    track_xy = np.column_stack(
        (length_m * np.sin(angles), -length_m * np.cos(angles))
    )
    return SimResult(
        length_m=length_m,
        release_deg=release_deg,
        times_s=times,
        angles_rad=angles,
        period_s=period,
        period_pair=pair,
        engine=engine,
        engine_note=note,
        track_xy=track_xy,
    )
