"""Lean extraction: classical colour/centroid tracking of the bob.

This is deliberately the low-spec path from the plan (no learned model):
threshold the bob's colour, take the mask centroid per frame, and
estimate the period from equilibrium crossings of the horizontal track.
The resulting timed 2-D track is stored in a generic ``Demonstration``
(schema: mimforge.models), exactly as the product stores an extracted
demonstration.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

from mimforge.models import Demonstration, Trajectory

from .common import period_from_crossings, split_period_estimates, upward_crossing_times


def _bob_mask(frame: np.ndarray) -> np.ndarray:
    """Pixels that are strongly red and weakly green/blue = the bob."""
    b = frame[:, :, 0].astype(np.int16)
    g = frame[:, :, 1].astype(np.int16)
    r = frame[:, :, 2].astype(np.int16)
    return ((r > 150) & (g < 110) & (b < 110)).astype(np.uint8)


def track_video(video_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Return (times, x_px, y_px, fps) -- the bob centroid per frame."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video {video_path}")
    fps = int(round(cap.get(cv2.CAP_PROP_FPS))) or 30
    times, xs, ys = [], [], []
    frame_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            moments = cv2.moments(_bob_mask(frame))
            if moments["m00"] == 0:
                raise RuntimeError(f"bob lost at frame {frame_idx} of {video_path}")
            xs.append(moments["m10"] / moments["m00"])
            ys.append(moments["m01"] / moments["m00"])
            times.append(frame_idx / fps)
            frame_idx += 1
    finally:
        cap.release()
    return np.array(times), np.array(xs), np.array(ys), fps


def analyse_track(times: np.ndarray, xs: np.ndarray) -> dict:
    """Period from upward crossings of the horizontal track about its
    equilibrium (midpoint of the track's extremes)."""
    x_mid = 0.5 * (float(xs.max()) + float(xs.min()))
    crossings = upward_crossing_times(times, xs - x_mid)
    period, intervals = period_from_crossings(crossings)
    period_a, period_b = split_period_estimates(intervals)
    return {
        "period_s": period,
        "period_pair": (period_a, period_b),
        "n_crossings": int(crossings.size),
        "x_extent_px": float(xs.max() - xs.min()),
    }


def extract_demonstration(
    video_path: Path, length_m: float, demo_id: str, practical_id: str
) -> tuple[Demonstration, dict, dict]:
    """Track one clip and package it as a schema Demonstration.

    Returns (demonstration, analysis, period_pair) where period_pair is
    the (t1-analogue, t2-analogue) period estimates for the table build.
    """
    times, xs, ys, _fps = track_video(video_path)
    analysis = analyse_track(times, xs)
    video_hash = hashlib.sha256(video_path.read_bytes()).hexdigest()
    demonstration = Demonstration(
        id=demo_id,
        practical_id=practical_id,
        video_hash=video_hash,
        trajectories=[
            Trajectory(
                label="task-object centroid track",
                points=[
                    (float(t), float(x), float(y)) for t, x, y in zip(times, xs, ys)
                ],
            )
        ],
    )
    return demonstration, analysis, analysis["period_pair"]
