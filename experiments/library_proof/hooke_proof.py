"""Hooke's law proof: a synthetic filmed spring, tracked, fitted.

Ground truth: the spring in the rendered world obeys Hooke's law
with K_TRUTH exactly; each load's true extension is F / K_TRUTH.
The measured table comes only from the tracker + the settled
marker position -- the fit never sees the truth.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from mimforge.templates import load_template, load_template_data
from mimforge.verification import run_verification

from .common import (
    APP_STRIDE,
    coverage_record,
    design_evidence,
    settled_position,
    track,
)

K_TRUTH = 25.0  # N/m -- the rendered spring's exact constant
LOADS = [  # (mass_g, load_N) -- the template's own bench settings
    (0, 0.0),
    (100, 0.981),
    (200, 1.962),
    (300, 2.943),
    (400, 3.924),
    (500, 4.905),
]

FRAME_W, FRAME_H = 640, 480
AXIS_X = 300
BAR_TOP, BAR_BOTTOM = 48, 66
DISC_R = 15
Y0 = 176  # marker centre (px) with no load
PX_PER_CM = 8.0

BG = (96, 88, 78)
BAR = (52, 52, 56)
SPRING = (205, 205, 205)
RULER = (170, 170, 170)
BLOCK = (118, 108, 96)
DISC = (30, 30, 235)


def _spring_points(top_y: int, bottom_y: int) -> np.ndarray:
    coils = 8
    n = coils * 2 + 1
    ys = np.linspace(top_y, bottom_y, n)
    xs = np.full(n, AXIS_X, dtype=float)
    xs[1:-1:2] = AXIS_X - 16
    xs[2:-1:2] = AXIS_X + 16
    return np.stack([xs, ys], axis=1).astype(np.int32)


def render_clip(
    mass_g: int,
    load_n: float,
    y_start: float,
    path: Path,
    *,
    fps: int = 30,
    duration: float = 3.5,
) -> dict:
    """Render one load setting: the marker oscillates with a
    decaying amplitude and settles at the true extension."""
    e_cm = 100.0 * load_n / K_TRUTH
    y_settled = Y0 + e_cm * PX_PER_CM
    n_frames = int(round(fps * duration))
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (FRAME_W, FRAME_H)
    )
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer for {path}")
    try:
        for k in range(n_frames):
            t = k / fps
            decay = math.exp(-t / 0.85) * math.cos(2 * math.pi * 1.7 * t)
            y = y_settled + (y_start - y_settled) * decay
            frame = np.full((FRAME_H, FRAME_W, 3), BG, dtype=np.uint8)
            cv2.rectangle(frame, (60, BAR_TOP), (580, BAR_BOTTOM), BAR, -1)
            # vertical scale beside the spring
            cv2.line(frame, (452, 90), (452, 430), RULER, 2)
            for cm in range(0, 43):
                x2 = 466 if cm % 5 == 0 else 460
                cv2.line(
                    frame, (452, 90 + cm * 8), (x2, 90 + cm * 8), RULER, 1
                )
            pts = _spring_points(BAR_BOTTOM, int(round(y)) - DISC_R)
            cv2.polylines(frame, [pts], False, SPRING, 2)
            cy = int(round(y))
            if mass_g > 0:
                cv2.line(
                    frame, (AXIS_X, cy + DISC_R), (AXIS_X, cy + 20), SPRING, 2
                )
                cv2.rectangle(
                    frame,
                    (AXIS_X - 27, cy + 20),
                    (AXIS_X + 27, cy + 56),
                    BLOCK,
                    -1,
                )
            cv2.circle(frame, (AXIS_X, cy), DISC_R, DISC, -1)
            writer.write(frame)
    finally:
        writer.release()
    return {
        "mass_g": mass_g,
        "load_N": load_n,
        "file": path.name,
        "true_extension_cm": e_cm,
        "settled_y_truth_px": y_settled,
    }


def run(
    out_dir: Path,
    *,
    fps: int = 30,
    duration: float = 3.5,
    stride: int = APP_STRIDE,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = load_template_data("hooke")
    template = load_template("hooke")

    clips = []
    y_start = Y0 - 26.0
    for mass_g, load_n in LOADS:
        record = render_clip(
            mass_g,
            load_n,
            y_start,
            out_dir / f"hooke_{mass_g:03d}g.mp4",
            fps=fps,
            duration=duration,
        )
        y_start = record["settled_y_truth_px"]
        clips.append(record)

    per_clip = []
    settled_y: dict[int, float] = {}
    for record in clips:
        result = track(out_dir / record["file"], data, stride=stride)
        settled_y[record["mass_g"]] = settled_position(result, "y")
        per_clip.append(
            {"file": record["file"], **coverage_record(result)}
        )
    zero_y = settled_y[0]
    rows = []
    for record in clips:
        if record["mass_g"] == 0:
            continue
        e_cm = (settled_y[record["mass_g"]] - zero_y) / PX_PER_CM
        rows.append(
            {
                "mass_g": record["mass_g"],
                "load_N": record["load_N"],
                "extension_cm": round(e_cm, 1),
                "extension_m": round(e_cm / 100.0, 3),
            }
        )

    outcome = run_verification(template, data, measured_rows=rows)
    recovered = float(outcome.sim_fit["recovered_value"])
    coverages = [c["measured_coverage"] for c in per_clip]
    return {
        "template": "hooke",
        "title": data["practical"]["title"],
        "ground_truth": {"spring_constant_N_per_m": K_TRUTH},
        "worked_table_recovered": round(
            float(outcome.teacher_fit["recovered_value"]), 3
        ),
        "measured_rows": rows,
        "measured_recovered": round(recovered, 3),
        "error_percent_vs_truth": round(
            100.0 * (recovered - K_TRUTH) / K_TRUTH, 2
        ),
        "band_percent": float(outcome.band_percent),
        "verification_passed": bool(outcome.passed),
        "verification_findings": [
            f.check_id for f in outcome.report.findings
        ],
        "tracker": {
            "stride": stride,
            "per_clip": per_clip,
            "min_measured_coverage": min(coverages),
            "mean_measured_coverage": round(
                float(np.mean(coverages)), 4
            ),
        },
        "design": design_evidence(data),
    }
