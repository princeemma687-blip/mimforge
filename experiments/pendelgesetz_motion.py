"""Pendelgesetz swing-window motion diagnostic (Phase 2 follow-up).

Why this exists: the colour-prompt tracker CANNOT track the lead bob in
this clip -- sampled BGR shows the bob (median 30-35, 54-59, 81-88) is
indistinguishable from the chalkboard beside it (35, 57, 86). Any BGR
band that catches the bob also catches the board, so a colour prompt
"tracks" the board's centroid (the same failure mode caught on the first
attempt). The bob is only separable by MOTION.

This diagnostic is an experiment probe, not core code: it builds a
background from the temporal median of the window, differences each
frame against it, and takes the centroid of the largest moving blob
inside a fixed region that excludes the on-screen seconds counter
(counter digits end at x ~480; the string/bob live at x ~600-660).

CORRECTION to the 2026-11-25 verdict: the 01:50-02:35 trim is NOT at
rest. The full-video scan found sustained ~1.85%/s change at 121-134 s
absolute time (11-24 s into the trim) -- the real timed run. The earlier
rest-check averaged the whole 45 s trim (most of it genuinely at rest),
which masked the 14 s of swing, and a single frame at the equilibrium
crossing looks identical to rest. Frames at 122 s (string tilted) vs
128 s (string vertical) prove the swing visually.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cv2
import numpy as np

from mimforge.perception import TrackResult, analyse_periodic

ASSETS = Path.home() / "workspace" / "mimforge-assets"
TRIM = ASSETS / "commons_pendelgesetz_swing_trim.mp4"

# Region (original 1920x1080 coords): excludes the seconds counter
# (x < ~480) and the chalk writing, keeps the string + bob path.
X0, X1, Y0, Y1 = 480, 720, 0, 700
# Bob band (experiment data for this clip): the load only ever moves in
# the lower part of the frame (y >= 500). Blobs above that are string
# fragments / pivot noise and must not be tracked as the load.
BOB_BAND_Y_MIN = 500
MIN_BLOB_AREA = 100
GROUND_TRUTH_PERIOD_S = 1.42  # lesson's own figure: 10 oscillations ~14.2 s
GROUND_TRUTH_LENGTH_M = 0.5


def motion_track(path: Path) -> TrackResult:
    cap = cv2.VideoCapture(str(path))
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
    frames: list[np.ndarray] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(frame[Y0:Y1, X0:X1], cv2.COLOR_BGR2GRAY))
    cap.release()
    if not frames:
        raise ValueError(f"no frames decoded from {path}")
    stack = np.stack(frames)
    background = np.median(stack, axis=0).astype(np.uint8)
    xs: list[float] = []
    ys: list[float] = []
    times: list[float] = []
    gaps: list[tuple[int, int]] = []
    gap_start: int | None = None
    for i, grey in enumerate(frames):
        diff = cv2.absdiff(grey, background)
        _, mask = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)
        )
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        # Only blobs in the load's band, big enough to be the load --
        # string fragments near the pivot (y ~ 20) are not the load.
        candidates = []
        for contour in contours:
            if cv2.contourArea(contour) < MIN_BLOB_AREA:
                continue
            m = cv2.moments(contour)
            if m["m00"] <= 0:
                continue
            cy = m["m01"] / m["m00"] + Y0
            if cy >= BOB_BAND_Y_MIN:
                candidates.append((cv2.contourArea(contour), contour))
        if candidates:
            biggest = max(candidates, key=lambda c: c[0])[1]
            m = cv2.moments(biggest)
            xs.append(m["m10"] / m["m00"] + X0)
            ys.append(m["m01"] / m["m00"] + Y0)
            times.append(i / fps)
            if gap_start is not None:
                gaps.append((gap_start, i - 1))
                gap_start = None
            continue
        if gap_start is None:
            gap_start = i
    if gap_start is not None:
        gaps.append((gap_start, len(frames) - 1))
    return TrackResult(
        frames_total=len(frames),
        frames_tracked=len(xs),
        fps=fps,
        gaps=gaps,
        xs=np.asarray(xs),
        ys=np.asarray(ys),
        times=np.asarray(times),
    )


def main() -> None:
    print("--- Pendelgesetz swing window 120-135 s (motion-difference track)")
    track = motion_track(TRIM)
    print(
        f"    tracked {track.frames_tracked}/{track.frames_total} frames "
        f"-> coverage {track.coverage:.1%}"
    )
    print(f"    gaps: {track.gaps}")
    print(
        f"    x extent {track.xs.max() - track.xs.min():.0f} px, "
        f"y extent {track.ys.max() - track.ys.min():.0f} px"
    )
    analysis = analyse_periodic(track, axis="x")
    print(
        f"    period: mean {analysis.mean_period_s:.3f} s "
        f"(first half {analysis.period_first_half_s:.3f}, "
        f"second half {analysis.period_second_half_s:.3f}), "
        f"{analysis.n_crossings} crossings"
    )
    err = (
        abs(analysis.mean_period_s - GROUND_TRUTH_PERIOD_S)
        / GROUND_TRUTH_PERIOD_S
        * 100
    )
    print(
        f"    ground truth {GROUND_TRUTH_PERIOD_S:.2f} s "
        f"(L = {GROUND_TRUTH_LENGTH_M} m, lesson's own figure)"
        f" -> error {err:.1f}%"
    )
    print(
        "    VERDICT: FAIL -- the 0.94 s figure is a tracker artefact, "
        "not a measurement. Adjacent-frame x jumps of ~85 px prove the "
        "blob is fragmenting between the load and string/shadow pieces. "
        "A second method was also tried: frame-to-frame difference in "
        "the same band finds NO blob >= 100 px on any of the 375 frames "
        "-- the load's grey level (~59) is ~4 levels from the board "
        "(~63), below any usable threshold. The swing IS in the video "
        "(string tilted at 122 s, vertical at 128 s; counter runs "
        "01.00 -> 10.00 in real time, so the video is not sped up), "
        "but neither the colour tracker nor this motion-difference "
        "probe can recover its period. PRODUCT GAP (recorded, not "
        "fixed tonight): dark-on-dark loads need the SAM-2 "
        "segmentation path the plan already names for hard cases."
    )


if __name__ == "__main__":
    main()
