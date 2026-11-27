"""Colour-tracker robustness (Prince's improvement order, 2026-11-26).

The tracker must not silently ignore parts of a demonstration in
other practicals: brief losses are bridged AND marked, long losses
are failed spans with a plain reason, the colour band adapts to a
lighting shift, prediction holds through fast blurred motion, and a
same-colour distractor cannot steal the track. Every case also
asserts the accounting invariant: the spans partition the examined
frames, so no frame is ever unaccounted for.

Clips are synthetic and generated in-test (a yellow disc on a dark
field, ground truth known exactly) -- the real-footage numbers live
in the progress log, from experiments/real_footage_track.py.
"""

import json

import cv2
import numpy as np
import pytest

from mimforge.perception import (
    ColourPrompt,
    coverage_report,
    serialise_track,
    track_object,
)

W, H, FPS = 320, 240, 30
BG = (24, 20, 16)
DISC = (60, 190, 215)  # yellow in BGR
PROMPT = ColourPrompt(
    name="yellow-disc",
    bgr_low=(30, 150, 170),
    bgr_high=(110, 230, 255),
    min_pixels=50,
)


def _path(i, n):
    """Ground-truth disc centre on frame i of n: left to right with
    a sinusoidal vertical swing."""
    cx = 40.0 + 240.0 * (i / max(1, n - 1))
    cy = 120.0 + 45.0 * np.sin(2 * np.pi * i / 30.0)
    return cx, cy


def _write_clip(path, n, draw):
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H)
    )
    assert writer.isOpened()
    for i in range(n):
        frame = np.full((H, W, 3), BG, np.uint8)
        draw(frame, i, n)
        writer.write(frame)
    writer.release()
    return path


def _draw_disc(frame, i, n, radius=14):
    cx, cy = _path(i, n)
    cv2.circle(frame, (int(cx), int(cy)), radius, DISC, -1)


def _assert_accounting(track):
    """Spans partition the examined frames exactly; point flags
    agree with the spans; nothing is silently unaccounted."""
    total = sum(s.end_frame - s.start_frame + 1 for s in track.spans)
    assert total == track.frames_total
    for a, b in zip(track.spans, track.spans[1:]):
        assert b.start_frame == a.end_frame + 1
    assert track.spans[0].start_frame == 0
    assert track.spans[-1].end_frame == track.frames_total - 1
    bridged_points = int(np.count_nonzero(track.bridged))
    bridged_span_frames = sum(
        s.end_frame - s.start_frame + 1
        for s in track.spans
        if s.kind == "bridged"
    )
    assert bridged_points == bridged_span_frames


def _points_by_frame(track):
    return {
        int(round(t * track.fps)): (x, y, bool(b))
        for t, x, y, b in zip(track.times, track.xs, track.ys, track.bridged)
    }


def test_occlusion_is_bridged_and_marked(tmp_path):
    """(a) A hand-sized occluder hides the disc for ~0.5 s: the gap
    is bridged, the bridged points are marked, the track completes."""
    n = 90

    def draw(frame, i, total):
        _draw_disc(frame, i, total)
        if 40 <= i <= 54:  # grey "hand" passes over the disc
            cx, cy = _path(i, total)
            cv2.rectangle(
                frame,
                (int(cx) - 26, int(cy) - 26),
                (int(cx) + 26, int(cy) + 26),
                (110, 110, 110),
                -1,
            )

    track = track_object(_write_clip(tmp_path / "occ.mp4", n, draw), PROMPT)
    _assert_accounting(track)
    assert track.coverage >= 0.99  # measured + bridged: nothing lost
    assert track.measured_coverage < 1.0  # but not all of it measured
    bridged_spans = [s for s in track.spans if s.kind == "bridged"]
    assert bridged_spans, "the occlusion must produce a bridged span"
    assert any(
        s.start_frame <= 47 <= s.end_frame for s in bridged_spans
    ), f"bridged spans {bridged_spans} do not cover the occlusion"
    points = _points_by_frame(track)
    assert points[47][2] is True  # mid-occlusion point is marked bridged
    assert not any(s.kind == "failed" for s in track.spans)


def test_lighting_ramp_adaptive_band_holds(tmp_path):
    """(b) The light dims steadily to 45%: the band adapts and the
    disc is measured (not bridged) for almost the whole clip. The
    static prompt band alone no longer matches at the dark end."""
    n = 90

    def draw(frame, i, total):
        _draw_disc(frame, i, total)
        factor = 1.0 - 0.55 * (i / max(1, total - 1))
        frame[:] = np.clip(frame.astype(np.float32) * factor, 0, 255).astype(
            np.uint8
        )

    track = track_object(_write_clip(tmp_path / "dim.mp4", n, draw), PROMPT)
    _assert_accounting(track)
    assert track.measured_coverage >= 0.95, (
        f"measured coverage {track.measured_coverage:.2f} under a "
        "lighting ramp -- the band did not adapt"
    )


def test_fast_blurred_motion_is_held_or_reported(tmp_path):
    """(c) Fast motion (20 px/frame) with heavy blur: prediction
    holds the track, or any loss is a reported span -- never a
    silent one."""
    n = 90

    def fast_path(i):
        # triangle wave across the frame at 20 px/frame
        span, half = 260.0, 30.0
        pos = (i * 20.0) % (2 * span)
        cx = half + (pos if pos <= span else 2 * span - pos)
        return cx, 120.0

    def draw(frame, i, total):
        cx, cy = fast_path(i)
        cv2.circle(frame, (int(cx), int(cy)), 14, DISC, -1)
        frame[:] = cv2.blur(frame, (13, 13))

    track = track_object(_write_clip(tmp_path / "fast.mp4", n, draw), PROMPT)
    _assert_accounting(track)  # every frame tracked, bridged, or failed
    assert track.coverage >= 0.90


def test_same_colour_distractor_cannot_steal_the_track(tmp_path):
    """(d) A static same-colour disc sits away from the path: the
    track stays on the moving disc, frame after frame."""
    n = 90
    # Clear of the path (nearest approach ~38 px > disc r16 +
    # distractor r12): two same-colour discs that actually touch
    # merge into one blob, which no colour tracker can separate.
    distractor = (280.0, 40.0)

    def draw(frame, i, total):
        cv2.circle(
            frame,
            (int(distractor[0]), int(distractor[1])),
            12,
            DISC,
            -1,
        )
        _draw_disc(frame, i, total, radius=16)

    track = track_object(_write_clip(tmp_path / "dist.mp4", n, draw), PROMPT)
    _assert_accounting(track)
    points = _points_by_frame(track)
    assert len(points) >= 85
    for i, (x, y, bridged) in points.items():
        if bridged:
            continue
        gx, gy = _path(i, n)
        assert np.hypot(x - gx, y - gy) < 10.0, (
            f"frame {i}: track at ({x:.0f},{y:.0f}), disc at "
            f"({gx:.0f},{gy:.0f}) -- the distractor stole the track"
        )
        assert np.hypot(x - distractor[0], y - distractor[1]) > 15.0


def test_long_loss_is_a_failed_span_not_a_bridge(tmp_path):
    """A 3 s disappearance is far beyond the bridge limit: it must
    surface as a failed span with a reason, the motion must NOT be
    invented across it, and tracking must resume afterwards."""
    n = 150

    def draw(frame, i, total):
        if 30 <= i <= 119:
            return  # the object is gone for 3 s
        _draw_disc(frame, i, total)

    track = track_object(_write_clip(tmp_path / "gone.mp4", n, draw), PROMPT)
    _assert_accounting(track)
    failed = [s for s in track.spans if s.kind == "failed"]
    assert failed, "the 3 s loss must be a failed span"
    assert any(
        s.start_frame <= 35 and s.end_frame >= 114 for s in failed
    ), f"failed spans {failed} do not cover the disappearance"
    assert all(s.reason for s in failed)
    points = _points_by_frame(track)
    assert not any(31 <= i <= 118 for i in points), (
        "points were invented across a failed span"
    )
    assert any(i >= 125 for i in points), "tracking never resumed"
    report = coverage_report(track)
    assert "could not be followed" in report["summary"]
    assert report["frames_measured"] < report["frames_examined"]


def test_failed_spans_reach_the_draft_warnings():
    """Downstream honesty: build_draft receives the coverage report
    and names the missing part in its warnings -- steps from that
    moment are known to rest on the narration alone."""
    from mimforge.narration import Transcript
    from mimforge.structuring import build_draft
    from mimforge.templates import load_template

    template = load_template("pendulum")
    report = {
        "spans": [
            {"kind": "tracked", "start_s": 0.0, "end_s": 11.0, "reason": ""},
            {
                "kind": "failed",
                "start_s": 11.0,
                "end_s": 14.0,
                "reason": "the object could not be seen",
            },
            {"kind": "bridged", "start_s": 20.0, "end_s": 20.5, "reason": ""},
        ]
    }
    draft = build_draft(
        template, Transcript(engine="test"), track_report=report
    )
    joined = " ".join(draft.warnings)
    assert "could not be tracked (0:11-0:14)" in joined
    assert "rest on the narration alone" in joined
    assert "bridged" in joined


def test_serialised_record_carries_the_marks(tmp_path):
    """The saved record keeps the bridged flags, the spans and the
    plain-words coverage report -- the honesty layer is stored, not
    just shown once."""
    n = 90

    def draw(frame, i, total):
        _draw_disc(frame, i, total)
        if 40 <= i <= 54:
            cx, cy = _path(i, total)
            cv2.rectangle(
                frame,
                (int(cx) - 26, int(cy) - 26),
                (int(cx) + 26, int(cy) + 26),
                (110, 110, 110),
                -1,
            )

    track = track_object(_write_clip(tmp_path / "rec.mp4", n, draw), PROMPT)
    record = serialise_track(track)
    json.dumps(record)  # the whole record must be JSON-safe
    assert len(record["bridged"]) == len(record["times_s"])
    assert any(record["bridged"])
    report = record["coverage_report"]
    assert report["frames_bridged"] > 0
    assert any(s["kind"] == "bridged" for s in report["spans"])
    assert "bridged" in report["summary"]
    assert record["coverage_measured"] == pytest.approx(
        track.measured_coverage
    )
