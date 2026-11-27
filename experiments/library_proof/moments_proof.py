"""Principle-of-moments proof: a synthetic balanced metre rule.

Ground truth: the unknown mass is X_TRUTH; at balance the rendered
marker rests at b = M * a / X_TRUTH exactly. The measured table
comes only from the tracker + the settled marker position.
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

KNOWN_MASS_G = 100
X_TRUTH = 80.0  # g -- the rendered unknown mass's exact value
A_VALUES = [12.0, 16.0, 20.0, 24.0, 28.0]  # cm, the template's settings

FRAME_W, FRAME_H = 800, 480
PIVOT_X = 400
RULE_TOP, RULE_BOTTOM = 250, 266
DISC_R = 13
DISC_Y = 302
PX_PER_CM = 8.0

BG = (96, 88, 78)
RULE = (90, 140, 190)
PIVOT = (60, 60, 60)
BLOCK = (118, 108, 96)
THREAD = (200, 200, 200)
DISC = (30, 30, 235)


def render_clip(
    a_cm: float,
    path: Path,
    *,
    fps: int = 30,
    duration: float = 3.0,
) -> dict:
    """Render one balance setting: the unknown marker slides along
    the rule and settles, wobbling slightly, at the balance point."""
    b_true = KNOWN_MASS_G * a_cm / X_TRUTH
    x_target = PIVOT_X + b_true * PX_PER_CM
    x_start = x_target - 54.0
    known_x = PIVOT_X - a_cm * PX_PER_CM
    n_frames = int(round(fps * duration))
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (FRAME_W, FRAME_H)
    )
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer for {path}")
    try:
        for k in range(n_frames):
            t = k / fps
            decay = math.exp(-t / 0.7) * math.cos(2 * math.pi * 1.05 * t)
            x = x_target + (x_start - x_target) * decay
            frame = np.full((FRAME_H, FRAME_W, 3), BG, dtype=np.uint8)
            # pivot + bench
            cv2.fillPoly(
                frame,
                [
                    np.array(
                        [[PIVOT_X, RULE_BOTTOM], [368, 330], [432, 330]],
                        dtype=np.int32,
                    )
                ],
                PIVOT,
            )
            cv2.line(frame, (40, 330), (760, 330), PIVOT, 3)
            # the rule, with centimetre ticks
            cv2.rectangle(
                frame, (40, RULE_TOP), (760, RULE_BOTTOM), RULE, -1
            )
            for cm in range(0, 91):
                tx = 40 + cm * 8
                cv2.line(
                    frame,
                    (tx, RULE_TOP),
                    (tx, RULE_TOP + (8 if cm % 5 == 0 else 5)),
                    PIVOT,
                    1,
                )
            # known mass, left of the pivot
            kx = int(round(known_x))
            cv2.line(frame, (kx, RULE_BOTTOM), (kx, 274), THREAD, 2)
            cv2.rectangle(frame, (kx - 19, 274), (kx + 19, 318), BLOCK, -1)
            # unknown mass: red marker disc on a thread, right side
            cx = int(round(x))
            cv2.line(frame, (cx, RULE_BOTTOM), (cx, DISC_Y - DISC_R), THREAD, 2)
            cv2.circle(frame, (cx, DISC_Y), DISC_R, DISC, -1)
            writer.write(frame)
    finally:
        writer.release()
    return {
        "a_cm": a_cm,
        "file": path.name,
        "true_b_cm": b_true,
        "settled_x_truth_px": x_target,
    }


def run(
    out_dir: Path,
    *,
    fps: int = 30,
    duration: float = 3.0,
    stride: int = APP_STRIDE,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = load_template_data("moments")
    template = load_template("moments")

    clips = [
        render_clip(a, out_dir / f"moments_a{int(a):02d}.mp4", fps=fps, duration=duration)
        for a in A_VALUES
    ]
    per_clip = []
    rows = []
    for record in clips:
        result = track(out_dir / record["file"], data, stride=stride)
        settled_x = settled_position(result, "x")
        b_cm = (settled_x - PIVOT_X) / PX_PER_CM
        rows.append(
            {
                "known_mass_g": KNOWN_MASS_G,
                "a_cm": record["a_cm"],
                "b_cm": round(b_cm, 1),
            }
        )
        per_clip.append({"file": record["file"], **coverage_record(result)})

    outcome = run_verification(template, data, measured_rows=rows)
    recovered = float(outcome.sim_fit["recovered_value"])
    coverages = [c["measured_coverage"] for c in per_clip]
    return {
        "template": "moments",
        "title": data["practical"]["title"],
        "ground_truth": {"unknown_mass_g": X_TRUTH},
        "worked_table_recovered": round(
            float(outcome.teacher_fit["recovered_value"]), 3
        ),
        "measured_rows": rows,
        "measured_recovered": round(recovered, 3),
        "error_percent_vs_truth": round(
            100.0 * (recovered - X_TRUTH) / X_TRUTH, 2
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
            "mean_measured_coverage": round(float(np.mean(coverages)), 4),
        },
        "design": design_evidence(data),
    }
