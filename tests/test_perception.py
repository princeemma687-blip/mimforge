"""Phase 2.1: ingest + generic object tracking.

Test T2.1 runs on the synthetic reference clip (the experiment's
rendered video): the tracked object must be present in >= 98% of
frames and the period recovered from the track must match the clip's
known period. Periodic analysis is also checked on a synthetic sine
track with a known period.
"""

from pathlib import Path

import numpy as np
import pytest

from mimforge.perception import (
    ColourPrompt,
    IngestError,
    analyse_periodic,
    period_from_crossings,
    probe_video,
    track_object,
    upward_crossing_times,
)

VIDEOS = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "pendulum_proof"
    / "output"
    / "videos"
)

# The reference clip's object is strongly red; the prompt is supplied as
# data, exactly as a template/teacher would supply it.
RED_PROMPT = ColourPrompt(
    name="red-object", bgr_low=(0, 0, 150), bgr_high=(110, 110, 255)
)


def test_probe_reads_reference_clip():
    info = probe_video(VIDEOS / "demo_L090cm.mp4")
    assert info.duration_s == pytest.approx(21.87, abs=0.1)
    assert info.frame_count == 656
    assert info.fps == pytest.approx(30.0)
    assert info.width > 0 and info.height > 0
    assert info.has_audio is False


def test_probe_missing_file_raises_cleanly():
    with pytest.raises(IngestError):
        probe_video(VIDEOS / "no-such-clip.mp4")


def test_track_object_coverage_and_period():
    """T2.1: track present in >= 98% of frames; period recovered."""
    track = track_object(VIDEOS / "demo_L090cm.mp4", RED_PROMPT)
    assert track.coverage >= 0.98, f"coverage {track.coverage:.3f} < 0.98"
    assert track.gaps == []
    analysis = analyse_periodic(track, axis="x")
    # Clip was rendered with L = 0.90 m; small-angle period ~1.90 s.
    assert analysis.mean_period_s == pytest.approx(1.90, abs=0.05)
    assert analysis.n_crossings >= 10
    # The two half-run estimates agree (stable tracking, no drift).
    assert abs(
        analysis.period_first_half_s - analysis.period_second_half_s
    ) < 0.05


def test_track_object_all_five_lengths():
    """Same tracker, same prompt, five clips: period shortens with length."""
    periods = []
    for length in ("090", "080", "070", "060", "050"):
        track = track_object(VIDEOS / f"demo_L{length}cm.mp4", RED_PROMPT)
        assert track.coverage >= 0.98
        periods.append(analyse_periodic(track, axis="x").mean_period_s)
    assert periods == sorted(periods, reverse=True)
    assert periods[0] == pytest.approx(1.90, abs=0.05)
    assert periods[-1] == pytest.approx(1.42, abs=0.05)


def test_periodic_analysis_on_synthetic_sine():
    t = np.linspace(0, 20, 2001)
    y = np.sin(2 * np.pi * t / 2.5)  # known period 2.5 s
    crossings = upward_crossing_times(t, y)
    period, _ = period_from_crossings(crossings)
    assert period == pytest.approx(2.5, abs=0.01)


def test_periodic_analysis_rejects_flat_track():
    t = np.linspace(0, 10, 101)
    y = np.zeros_like(t)
    with pytest.raises(ValueError):
        period_from_crossings(upward_crossing_times(t, y))
