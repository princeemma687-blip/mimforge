"""Simulation of the same practical, through the identical table path.

Primary engine: MuJoCo (Apache-2.0) -- a hinge-jointed body with the
mass concentrated at distance L, released from rest at the same angle
as the synthetic demonstration, stepped at 1 ms and sampled at 200 Hz.

Fallback: if MuJoCo cannot be imported or run, an RK4 integration of
the pendulum equation sampled at the same rate. The fallback is never
silent: the returned engine record names what actually ran and, for the
fallback, why.
"""

from __future__ import annotations

import numpy as np

from .common import (
    AMPLITUDE_DEG,
    G_TRUTH,
    period_from_crossings,
    small_angle_period,
    split_period_estimates,
    upward_crossing_times,
)

_SAMPLE_HZ = 200
_MUJOCO_DT = 0.001
_STEPS_PER_SAMPLE = int(round(1.0 / (_MUJOCO_DT * _SAMPLE_HZ)))  # 5


def _period_pair_from_angles(times: np.ndarray, angles: np.ndarray) -> tuple[float, tuple[float, float]]:
    crossings = upward_crossing_times(times, angles)
    period, intervals = period_from_crossings(crossings)
    return period, split_period_estimates(intervals)


def _mujoco_angles(length_m: float, duration_s: float) -> tuple[np.ndarray, np.ndarray]:
    import mujoco

    xml = f"""
    <mujoco model="proof_pendulum">
      <option timestep="{_MUJOCO_DT}"/>
      <worldbody>
        <body pos="0 0 1">
          <joint type="hinge" axis="0 1 0"/>
          <geom type="sphere" size="0.02" mass="1.0" pos="0 0 {-length_m}"/>
        </body>
      </worldbody>
    </mujoco>"""
    model = mujoco.MjModel.from_xml_string(xml)
    if abs(float(model.opt.gravity[2]) + G_TRUTH) > 0.05:
        raise RuntimeError(f"unexpected MuJoCo gravity {model.opt.gravity}")
    data = mujoco.MjData(model)
    data.qpos[0] = np.radians(AMPLITUDE_DEG)
    n_steps = int(duration_s / _MUJOCO_DT)
    times, angles = [], []
    for i in range(n_steps):
        mujoco.mj_step(model, data)
        if i % _STEPS_PER_SAMPLE == 0:
            times.append(float(data.time))
            angles.append(float(data.qpos[0]))
    return np.array(times), np.array(angles)


def _rk4_angles(length_m: float, duration_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Fallback engine: RK4 on theta'' = -(g/L) sin(theta) at 1 kHz,
    sampled at _SAMPLE_HZ -- the same motion the video generator uses,
    integrated independently here."""
    dt = 0.001
    n = int(duration_s / dt) + 1
    theta = np.empty(n)
    omega = np.empty(n)
    theta[0] = np.radians(AMPLITUDE_DEG)
    omega[0] = 0.0

    def accel(th: float) -> float:
        return -(G_TRUTH / length_m) * np.sin(th)

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


def simulate_length(length_m: float) -> dict:
    """Simulate one length; return period estimates + engine record."""
    duration = 12.5 * small_angle_period(length_m)
    try:
        times, angles = _mujoco_angles(length_m, duration)
        engine, note = "mujoco", ""
    except Exception as exc:  # import failure, model failure, GL, ...
        times, angles = _rk4_angles(length_m, duration)
        engine = "rk4-ode-fallback"
        note = f"MuJoCo unavailable ({type(exc).__name__}: {exc}); RK4 ODE used."
    period, pair = _period_pair_from_angles(times, angles)
    return {
        "length_m": length_m,
        "period_s": period,
        "period_pair": pair,
        "engine": engine,
        "engine_note": note,
    }


def simulate_all(lengths_m) -> tuple[list[dict], str, str]:
    """Simulate every length. Returns (records, engine, engine_note);
    the engine record is taken from the first length and asserted
    consistent across lengths by the caller if it matters."""
    records = [simulate_length(length_m) for length_m in lengths_m]
    engines = {r["engine"] for r in records}
    engine = records[0]["engine"] if len(engines) == 1 else "mixed"
    note = records[0]["engine_note"]
    return records, engine, note
