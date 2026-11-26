"""Trajectory retargeting — the machine follows the human's path.

Synthetic tracks with known geometry prove the contract: the path
shape survives the mapping exactly (a similarity transform), a
fast human motion is time-warped to the safety cap with the path
untouched, points outside the design's reach are clamped and
counted, and a path that mostly lies outside the reach refuses in
plain words.
"""

from __future__ import annotations

import math

import pytest

from mimforge.design import GantryParameters
from mimforge.models import SafetyLimits
from mimforge.retarget import RetargetError, retarget_track

FRAME_W, FRAME_H = 640.0, 480.0
PARAMS = GantryParameters()  # travel 400 mm, drop 500 mm
SCALE = 500.0 / FRAME_H  # the vertical-anchored scale


def _arc_track(radius_px=150.0, seconds=4.0, n=41, cx=320.0, cy=240.0):
    """A semicircle of known radius, centred in the frame."""
    times, xs, ys = [], [], []
    for i in range(n):
        angle = math.pi * i / (n - 1)  # 0..pi
        times.append(seconds * i / (n - 1))
        xs.append(cx + radius_px * math.cos(angle))
        ys.append(cy - radius_px * math.sin(angle))
    return {"times_s": times, "xs_px": xs, "ys_px": ys}


def _expected(x_px, y_px):
    """The documented transform, recomputed independently."""
    travel, drop = 400.0, 500.0
    return (
        (x_px - FRAME_W / 2) * SCALE + travel / 2,
        (y_px - FRAME_H / 2) * SCALE + drop / 2,
    )


def test_exact_path_and_timing_when_the_human_is_gentle():
    track = _arc_track()
    result = retarget_track(track, FRAME_W, FRAME_H, PARAMS)
    assert result.total_points == 41
    assert result.clamped_points == 0
    assert result.feasible_percent == 100.0
    assert result.deviation_max_mm == 0.0
    assert not result.timing_adjusted
    assert result.warp_factor == 1.0
    # Path exactness: every machine point is the transform of the
    # human point, to float tolerance.
    for (t, x, y), px, py in zip(
        result.points, track["xs_px"], track["ys_px"]
    ):
        ex, ey = _expected(px, py)
        assert x == pytest.approx(ex, abs=1e-9)
        assert y == pytest.approx(ey, abs=1e-9)
    # And the shape survived: the machine path is still a semicircle
    # of radius 150 px * scale.
    cx, cy = _expected(320.0, 240.0)
    for _t, x, y in result.points:
        assert math.hypot(x - cx, y - cy) == pytest.approx(
            150.0 * SCALE, abs=1e-6
        )


def test_fast_human_motion_is_time_warped_not_path_warped():
    gentle = retarget_track(_arc_track(seconds=4.0), FRAME_W, FRAME_H, PARAMS)
    fast_track = _arc_track(seconds=0.4)  # ten times faster
    fast = retarget_track(fast_track, FRAME_W, FRAME_H, PARAMS)
    assert fast.timing_adjusted
    assert fast.warp_factor > 2.0
    # The path is untouched: same positions as the gentle run.
    for (_t1, x1, y1), (_t2, x2, y2) in zip(fast.points, gentle.points):
        assert x1 == pytest.approx(x2, abs=1e-9)
        assert y1 == pytest.approx(y2, abs=1e-9)
    # After the warp, no segment exceeds the kernel's cap.
    assert fast.peak_speed_mm_s <= 250.0 + 1e-6
    assert fast.cap_mm_s == 250.0
    # Duration stretched by the warp factor.
    assert fast.points[-1][0] == pytest.approx(0.4 * fast.warp_factor)


def test_a_lower_cap_forces_a_bigger_warp():
    limits = SafetyLimits(max_tool_speed_mm_s=100.0)
    result = retarget_track(
        _arc_track(seconds=1.0), FRAME_W, FRAME_H, PARAMS, limits
    )
    assert result.timing_adjusted
    assert result.peak_speed_mm_s <= 100.0 + 1e-6
    assert result.cap_mm_s == 100.0


def test_partly_out_of_reach_is_clamped_and_counted():
    # An arc wider than the carriage travel: radius 200 px maps to
    # ~208 mm each side of centre; travel allows only 200 mm, so
    # the arc's ends (about 18% of its points) clamp to the edge.
    track = _arc_track(radius_px=200.0)
    result = retarget_track(track, FRAME_W, FRAME_H, PARAMS)
    assert 0 < result.clamped_points <= result.total_points // 4
    assert result.feasible_percent < 100.0
    assert result.deviation_max_mm > 0.0
    assert result.deviation_mean_mm > 0.0
    # Every delivered point is inside the envelope.
    for _t, x, y in result.points:
        assert 0.0 <= x <= 400.0
        assert 0.0 <= y <= 500.0


def test_mostly_out_of_reach_refuses_in_plain_words():
    # A path hugging the frame's left and right edges: most of it
    # maps outside a 400 mm travel.
    times = [i * 0.1 for i in range(21)]
    xs = [10.0 if i % 2 == 0 else 630.0 for i in range(21)]
    ys = [240.0] * 21
    track = {"times_s": times, "xs_px": xs, "ys_px": ys}
    with pytest.raises(RetargetError) as caught:
        retarget_track(track, FRAME_W, FRAME_H, PARAMS)
    assert "outside this machine's reach" in str(caught.value)


def test_no_track_and_no_motion_refuse_plainly():
    with pytest.raises(RetargetError):
        retarget_track(
            {"times_s": [], "xs_px": [], "ys_px": []},
            FRAME_W, FRAME_H, PARAMS,
        )
    still = {
        "times_s": [0.0, 1.0, 2.0],
        "xs_px": [100.0, 100.0, 100.0],
        "ys_px": [100.0, 100.0, 100.0],
    }
    with pytest.raises(RetargetError) as caught:
        retarget_track(still, FRAME_W, FRAME_H, PARAMS)
    assert "does not move" in str(caught.value)


def test_result_round_trips_through_a_dict():
    result = retarget_track(_arc_track(), FRAME_W, FRAME_H, PARAMS)
    back = type(result).from_dict(result.to_dict())
    assert back.points == result.points
    assert back.timing_adjusted == result.timing_adjusted
    assert back.feasible_percent == result.feasible_percent
