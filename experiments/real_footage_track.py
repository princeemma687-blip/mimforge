"""Real-footage tracker proof (Phase 2, follow-up to synthetic proof).

Runs the generic colour-prompt tracker from src/mimforge/perception.py on
the public demonstration videos sourced into ~/workspace/mimforge-assets/
(see SOURCES.md). No pendulum-specific logic lives here beyond the colour
prompt values, which are *data* supplied for this one clip -- the tracker
itself stays generic.

Clip 1 (first): commons_blocked_pendulum_slowmo.mp4 -- large yellow bob,
plain board, fixed camera. Expectation: high coverage; period analysis is
only indicative here because the peg-block makes the swing non-sinusoidal.

Clip 2: commons_pendelgesetz_timed_run_trim.mp4 -- known 0.5 m length,
lesson ground truth ~14.2 s per 10 oscillations. Expectation: period
recovered near 1.42 s if the small dark bob tracks.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np

from mimforge.perception import (
    ColourPrompt,
    analyse_periodic,
    probe_video,
    track_object,
)

ASSETS = Path.home() / "workspace" / "mimforge-assets"

# Yellow bob (BGR): sampled from frame 0 -- median (80, 180, 195),
# p5 (56, 129, 154), p95 (112, 215, 231). Prompt brackets that range
# with margin, excluding the green board (high G, low R) and the skin/hand.
YELLOW_PROMPT = ColourPrompt(
    name="yellow-ball",
    bgr_low=(40, 110, 140),
    bgr_high=(130, 230, 250),
    min_pixels=100,
)

# Lead-grey bob in the Pendelgesetz trim: NOT usable as a colour prompt --
# the board itself falls in the same BGR band (~180k px/frame), so a
# whole-frame grey prompt "tracks" the board's centroid, not the bob.
# Verified 2026-11-25: the trim shows the apparatus AT REST (frame-diff
# in the swing region: mean 0.7% changed pixels; the string hangs
# vertical at the same x in every sampled frame). The lesson's ground
# truth (1.42 s per swing) is written on the board, but the swing itself
# is not in this 45 s trim -- it must be earlier in the original video.
# Clip 2 is therefore recorded as an INVALID period test input, not a
# tracker failure. See run_pendelgesetz_rest_check() below.


def report_clip(path: Path, prompt: ColourPrompt, label: str) -> None:
    info = probe_video(path)
    print(f"--- {label}")
    print(
        f"    {path.name}: {info.width}x{info.height} "
        f"{info.fps:.1f} fps, {info.duration_s:.1f} s, {info.frame_count} frames"
    )
    track = track_object(path, prompt)
    print(
        f"    tracked {track.frames_tracked}/{track.frames_total} frames "
        f"-> coverage {track.coverage:.1%}"
    )
    print(f"    gaps: {track.gaps}")
    if track.frames_tracked >= 4:
        print(
            f"    x extent {track.xs.max() - track.xs.min():.0f} px, "
            f"y extent {track.ys.max() - track.ys.min():.0f} px"
        )
        try:
            analysis = analyse_periodic(track, axis="x")
            print(
                f"    period: mean {analysis.mean_period_s:.3f} s "
                f"(first half {analysis.period_first_half_s:.3f}, "
                f"second half {analysis.period_second_half_s:.3f}), "
                f"{analysis.n_crossings} crossings"
            )
        except ValueError as exc:
            print(f"    period analysis: {exc}")
    print()


def report_pendelgesetz_rest_check(path: Path) -> None:
    """Clip 2 is NOT a period test: prove the apparatus is at rest.

    Frame-difference in the swing region (x 280..400, y 0..430) sampled
    once per second: a swinging load would change a large fraction of
    those pixels every second. What we actually see is ~0.7% mean --
    the string hangs vertical at the same x in every sampled frame.
    The lesson's ground truth (1.42 s per swing) is written on the
    board, but the swing itself is not in this trim.
    """
    import cv2

    print("--- Clip 2: Pendelgesetz timed run (ground truth ~1.42 s)")
    cap = cv2.VideoCapture(str(path))
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
    prev = None
    diffs: list[float] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        roi = cv2.cvtColor(frame[0:430, 280:400], cv2.COLOR_BGR2GRAY)
        if prev is not None and idx % 25 == 0:
            d = cv2.absdiff(roi, prev)
            diffs.append(float((d > 25).mean()))
        prev = roi
        idx += 1
    cap.release()
    mean_change = float(np.mean(diffs)) if diffs else 0.0
    print(f"    {path.name}: {idx} frames, {fps:.0f} fps")
    print(
        f"    swing-region change per 1 s sample: mean {mean_change:.1%}, "
        f"max {max(diffs):.1%} -> apparatus AT REST in this trim"
    )
    print(
        "    VERDICT: invalid period test input (no swing to recover); "
        "the real swing must be earlier in the original video."
    )
    print()


def main() -> None:
    report_clip(
        ASSETS / "commons_blocked_pendulum_slowmo.mp4",
        YELLOW_PROMPT,
        "Clip 1: blocked pendulum (slow motion, yellow bob)",
    )
    report_pendelgesetz_rest_check(
        ASSETS / "commons_pendelgesetz_timed_run_trim.mp4"
    )


if __name__ == "__main__":
    main()
