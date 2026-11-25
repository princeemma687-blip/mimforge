"""Synthetic demonstration-video generator.

Renders a swinging bob against a plain background for each length in the
template's set. The rendered motion is NOT the small-angle sinusoid: it
is an RK4 integration of the true pendulum equation
theta'' = -(g/L) sin(theta), released from rest at AMPLITUDE_DEG, so the
ground truth carries the same small amplitude effect a real bench swing
has. Ground truth per length is measured from the full-rate angle series
with the same crossing estimator the extraction path uses.

Output: one video file per length plus ground_truth.json. Videos are
small on purpose (320x240, 30 fps, ~10 oscillations per length).
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from .common import (
    AMPLITUDE_DEG,
    G_TRUTH,
    LENGTHS_M,
    small_angle_period,
    upward_crossing_times,
    period_from_crossings,
)

FPS = 30
FRAME_W, FRAME_H = 320, 240
PIVOT_XY = (160, 24)
PX_PER_M = 190.0
BOB_RADIUS_PX = 9
BOB_BGR = (0, 0, 255)  # pure red bob: trivially separable by colour
BACKGROUND_BGR = (235, 235, 235)
ROD_BGR = (90, 90, 90)
INTERNAL_HZ = 480  # ODE integration rate; frames sample every 16th step


def _integrate_angles(length_m: float, duration_s: float) -> tuple[np.ndarray, np.ndarray]:
    """RK4 on theta'' = -(g/L) sin(theta), released from rest."""
    dt = 1.0 / INTERNAL_HZ
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
    return t, theta


def _open_writer(path: Path, fps: int) -> tuple[cv2.VideoWriter, Path]:
    """Prefer mp4/mp4v; fall back to MJPG .avi if the codec is missing."""
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (FRAME_W, FRAME_H)
    )
    if writer.isOpened():
        return writer, path
    writer.release()
    alt = path.with_suffix(".avi")
    writer = cv2.VideoWriter(
        str(alt), cv2.VideoWriter_fourcc(*"MJPG"), fps, (FRAME_W, FRAME_H)
    )
    if not writer.isOpened():
        raise RuntimeError(f"could not open any video writer for {path}")
    return writer, alt


def render_length(length_m: float, out_dir: Path, n_oscillations: int = 10) -> dict:
    """Render one length's clip; return its ground-truth record."""
    duration = (n_oscillations + 1.5) * small_angle_period(length_m)
    t_full, theta_full = _integrate_angles(length_m, duration)
    crossings = upward_crossing_times(t_full, theta_full)
    true_period, _ = period_from_crossings(crossings)

    steps_per_frame = INTERNAL_HZ // FPS
    n_frames = int(duration * FPS)
    rod_px = PX_PER_M * length_m
    stem = f"demo_L{int(round(100 * length_m)):03d}cm"
    writer, video_path = _open_writer(out_dir / f"{stem}.mp4", FPS)
    try:
        for k in range(n_frames):
            theta = float(theta_full[k * steps_per_frame])
            cx = PIVOT_XY[0] + rod_px * np.sin(theta)
            cy = PIVOT_XY[1] + rod_px * np.cos(theta)
            frame = np.full((FRAME_H, FRAME_W, 3), BACKGROUND_BGR, dtype=np.uint8)
            cv2.line(frame, PIVOT_XY, (int(round(cx)), int(round(cy))), ROD_BGR, 2)
            cv2.circle(frame, PIVOT_XY, 4, ROD_BGR, -1)
            cv2.circle(
                frame, (int(round(cx)), int(round(cy))), BOB_RADIUS_PX, BOB_BGR, -1
            )
            cv2.putText(
                frame,
                f"L = {length_m:.2f} m",
                (8, 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                ROD_BGR,
                1,
                cv2.LINE_AA,
            )
            writer.write(frame)
    finally:
        writer.release()

    return {
        "length_m": length_m,
        "video_file": video_path.name,
        "n_frames": n_frames,
        "fps": FPS,
        "amplitude_deg": AMPLITUDE_DEG,
        "small_angle_period_s": small_angle_period(length_m),
        "true_period_s": true_period,
    }


def generate_all(out_dir: Path, lengths_m=LENGTHS_M) -> dict:
    """Render every length and write ground_truth.json beside the videos."""
    out_dir.mkdir(parents=True, exist_ok=True)
    records = [render_length(length_m, out_dir) for length_m in lengths_m]
    ground_truth = {
        "g_truth": G_TRUTH,
        "amplitude_deg": AMPLITUDE_DEG,
        "synthetic": True,
        "records": records,
    }
    (out_dir / "ground_truth.json").write_text(
        json.dumps(ground_truth, indent=2), encoding="utf-8"
    )
    return ground_truth
