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
lesson ground truth ~14.2 s per 10 oscillations. CORRECTED 2026-11-25:
the swing IS in this trim (121-134 s absolute; string tilted at 122 s,
vertical at 128 s) -- the earlier "at rest" verdict was an averaging
artefact. But the small dark lead bob is untrackable by the current
tracker family (colour prompt fails: bob BGR ~ board BGR; motion
probe in pendelgesetz_motion.py returns only a noisy 0.94 s artefact
vs 1.42 s ground truth). Documented tracker gap; SAM-2 is the named fix.
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
# CORRECTION 2026-11-25 (evening): the earlier "apparatus AT REST"
# verdict was WRONG. A full-video scan found sustained ~1.85%/s change
# at 121-134 s absolute time (11-24 s into the trim) -- the real timed
# run. The earlier rest-check averaged the whole 45 s trim (most of it
# genuinely at rest), which masked the 14 s of swing, and a single frame
# at the equilibrium crossing looks identical to rest. Frames prove it:
# string tilted at 122 s, vertical at 128 s; the on-screen counter runs
# 01.00 -> 10.00 in real time, so the video is not sped up. The swing
# IS in the trim -- but the bob is untrackable by the current tracker
# family: colour prompt fails (bob BGR ~ board BGR), and the
# motion-difference probe in experiments/pendelgesetz_motion.py recovers
# only a noisy track (period artefact 0.94 s vs 1.42 s ground truth;
# frame-to-frame diff finds nothing -- bob grey ~59 vs board ~63).
# PRODUCT GAP: dark-on-dark loads need the SAM-2 segmentation path the
# plan already names for hard cases. See run_pendelgesetz_rest_check()
# below, which now reports the corrected finding.


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
    """Clip 2, CORRECTED 2026-11-25 (evening).

    The 2026-11-25 afternoon verdict ("apparatus AT REST in this trim")
    was wrong: it averaged the whole 45 s trim, most of which IS at rest,
    and so masked the 14 s of real swing at 121-134 s absolute time
    (11-24 s into the trim). A full-video scan of the original shows
    sustained ~1.85%/s change across 121-134 s, and frames at 122 s
    (string tilted) vs 128 s (string vertical) prove the swing visually.
    The swing is therefore IN this trim -- but the bob is untrackable by
    the current tracker family (see experiments/pendelgesetz_motion.py):
    colour prompt fails (bob BGR ~ board BGR) and the motion-difference
    probe returns only a noisy artefact (0.94 s vs 1.42 s ground truth).
    The clip stays a documented tracker gap, not a period test pass.
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
        f"max {max(diffs):.1%} (mean over the whole trim -- mostly rest, "
        "so it hides the 14 s of swing at 121-134 s absolute time)"
    )
    print(
        "    CORRECTED VERDICT: the swing IS in this trim (121-134 s; "
        "string tilted at 122 s, vertical at 128 s; counter 01.00->"
        "10.00 in real time). The earlier 'at rest' verdict averaged "
        "it away. The bob is still untrackable by the current tracker "
        "family -- see experiments/pendelgesetz_motion.py (motion "
        "probe: 0.94 s artefact vs 1.42 s ground truth). Documented "
        "tracker gap; SAM-2 path is the named fix."
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
