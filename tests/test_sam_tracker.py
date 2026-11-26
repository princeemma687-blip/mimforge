"""Click tracker (SAM 2.1, ONNX) — unit contract tests.

Weights custody, the decoder's mask choice, and the tracking loop
are exercised with fakes at the documented seams (a downloader, a
session factory, a segmenter) so the wire and tensor contracts are
proven without the 130 MB model files. The proving test at the end
runs the REAL model on the real hard clip -- the classroom footage
whose dark moving mass the colour tracker cannot separate from the
board behind it -- and is skipped unless both the clip and verified
weights are on this machine.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from mimforge import sam_tracker
from mimforge.perception import TrackResult
from mimforge.sam_tracker import (
    SamError,
    SamSegmenter,
    ensure_weights,
    track_with_click,
    weights_present,
)

ASSETS = Path.home() / "workspace" / "mimforge-assets"
HARD_CLIP = ASSETS / "commons_pendelgesetz_swing_trim.mp4"


# --------------------------------------------------------------- weights


def _tiny_spec(monkeypatch, payload: bytes = b"tiny-model-bytes"):
    spec = {
        "encoder.onnx": (
            "https://example.invalid/encoder.onnx",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        ),
        "decoder.onnx": (
            "https://example.invalid/decoder.onnx",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        ),
    }
    monkeypatch.setattr(sam_tracker, "_WEIGHT_FILES", spec)
    monkeypatch.setattr(
        sam_tracker, "_TOTAL_WEIGHT_BYTES", 2 * len(payload)
    )
    return payload


def test_ensure_weights_downloads_verifies_and_caches(tmp_path, monkeypatch):
    payload = _tiny_spec(monkeypatch)
    calls = []

    def fake_download(url, dest, progress, base_done):
        calls.append(url)
        dest.write_bytes(payload)

    folder = tmp_path / "models"
    assert not weights_present(folder)
    result = ensure_weights(folder, downloader=fake_download)
    assert result == folder
    assert weights_present(folder)
    assert len(calls) == 2
    # Second run: everything verifies, nothing downloads again.
    ensure_weights(folder, downloader=fake_download)
    assert len(calls) == 2


def test_ensure_weights_rejects_a_corrupt_download(tmp_path, monkeypatch):
    _tiny_spec(monkeypatch)

    def corrupt_download(url, dest, progress, base_done):
        dest.write_bytes(b"not the model at all")

    folder = tmp_path / "models"
    with pytest.raises(SamError) as caught:
        ensure_weights(folder, downloader=corrupt_download)
    assert "did not check out" in str(caught.value)
    assert not weights_present(folder)
    assert not list(folder.glob("*.onnx"))  # nothing unverified is kept


def test_ensure_weights_network_failure_is_plain(tmp_path, monkeypatch):
    _tiny_spec(monkeypatch)

    def dead_download(url, dest, progress, base_done):
        raise OSError("no route to host")

    with pytest.raises(SamError) as caught:
        ensure_weights(tmp_path / "models", downloader=dead_download)
    assert "could not be downloaded" in str(caught.value)


def test_segmenter_without_weights_is_plain(tmp_path):
    segmenter = SamSegmenter(tmp_path / "empty")
    frame = np.zeros((40, 60, 3), dtype=np.uint8)
    with pytest.raises(SamError) as caught:
        segmenter.segment(frame, (10.0, 10.0))
    assert "not on this computer" in str(caught.value)


# ------------------------------------------------------------- segmenter


class _FakeEncoder:
    def __init__(self):
        self.seen_shapes = []

    def run(self, _outputs, feeds):
        image = feeds["image"]
        self.seen_shapes.append(image.shape)
        assert image.dtype == np.float32
        return [
            np.zeros((1, 256, 64, 64), dtype=np.float32),
            np.zeros((1, 32, 256, 256), dtype=np.float32),
            np.zeros((1, 64, 128, 128), dtype=np.float32),
        ]


class _FakeDecoder:
    """Mask channel 2 (the best-scoring alternative) carries a
    bright square at the frame's centre; the rest are empty."""

    def __init__(self):
        self.seen_points = []

    def run(self, _outputs, feeds):
        self.seen_points.append(feeds["point_coords"].copy())
        logits = np.full((1, 4, 256, 256), -5.0, dtype=np.float32)
        logits[0, 2, 108:148, 108:148] = 5.0
        scores = np.array([[0.1, 0.5, 0.9, 0.2]], dtype=np.float32)
        return [logits, scores]


def _segmenter_with_fakes(tmp_path, monkeypatch):
    payload = _tiny_spec(monkeypatch)
    folder = tmp_path / "models"
    folder.mkdir()
    (folder / "encoder.onnx").write_bytes(payload)
    (folder / "decoder.onnx").write_bytes(payload)
    encoder, decoder = _FakeEncoder(), _FakeDecoder()
    segmenter = SamSegmenter(
        folder, session_factory=lambda e, d: (encoder, decoder)
    )
    return segmenter, encoder, decoder


def test_segmenter_prepares_prompts_and_picks_the_best_mask(
    tmp_path, monkeypatch
):
    segmenter, encoder, decoder = _segmenter_with_fakes(tmp_path, monkeypatch)
    frame = np.zeros((100, 200, 3), dtype=np.uint8)  # H=100, W=200
    mask = segmenter.segment(frame, (50.0, 25.0))
    assert mask.shape == (100, 200)
    assert encoder.seen_shapes == [(1, 3, 1024, 1024)]
    # The point is scaled into the 1024 frame: x*1024/200, y*1024/100.
    point = decoder.seen_points[0]
    assert point.shape == (1, 1, 2)
    assert point[0, 0, 0] == pytest.approx(50.0 * 1024 / 200)
    assert point[0, 0, 1] == pytest.approx(25.0 * 1024 / 100)
    # Channel 2's centred square wins (best alternative score).
    assert mask[50, 100] == 1
    assert mask[2, 2] == 0
    assert mask.sum() > 100


class _WholeVsPartDecoder:
    """Channel 1 is the whole frame with the best predicted score;
    channel 3 is a small square on the click. A click names one
    object: the tightest mask containing the click must win."""

    def run(self, _outputs, feeds):
        logits = np.full((1, 4, 256, 256), -5.0, dtype=np.float32)
        logits[0, 1, :, :] = 5.0  # everything
        logits[0, 3, 60:80, 20:40] = 5.0  # a small part at the click
        scores = np.array([[0.2, 0.99, 0.1, 0.1]], dtype=np.float32)
        return [logits, scores]


def test_segmenter_prefers_the_tightest_mask_on_the_click(
    tmp_path, monkeypatch
):
    payload = _tiny_spec(monkeypatch)
    folder = tmp_path / "models"
    folder.mkdir()
    (folder / "encoder.onnx").write_bytes(payload)
    (folder / "decoder.onnx").write_bytes(payload)
    segmenter = SamSegmenter(
        folder,
        session_factory=lambda e, d: (_FakeEncoder(), _WholeVsPartDecoder()),
    )
    frame = np.zeros((256, 256, 3), dtype=np.uint8)
    # The frame is 256x256, the same size as the logit grid, so
    # coordinates carry straight over: the small square occupies
    # x 20-40, y 60-80, and the click lands inside it.
    mask = segmenter.segment(frame, (30.0, 70.0))
    assert 0 < mask.sum() < 2000  # the part, not the whole frame
    assert mask[70, 30] == 1


# ------------------------------------------------------------ track loop


def _write_moving_square_video(path: Path, frames: int = 30) -> None:
    import cv2

    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (160, 120)
    )
    assert writer.isOpened()
    for i in range(frames):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        cx = 30 + i * 3  # the square walks right, 3 px per frame
        cv2.rectangle(frame, (cx - 8, 52), (cx + 8, 68), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()


class _ThresholdSegmenter:
    """Stands in for SAM at the segmenter seam: finds the bright
    square. What is under test is the loop -- chaining, gaps, and
    the TrackResult contract -- not the model."""

    def __init__(self, blank_frames=()):
        self.blank_frames = set(blank_frames)
        self.calls = 0
        self.prompts = []

    def segment(self, frame, point_xy):
        index = self.calls
        self.calls += 1
        self.prompts.append(point_xy)
        if index in self.blank_frames:
            return np.zeros(frame.shape[:2], dtype=np.uint8)
        grey = frame[:, :, 0]
        return (grey > 200).astype(np.uint8)


def test_track_loop_chains_prompts_and_reports_gaps(tmp_path):
    video = tmp_path / "moving.mp4"
    _write_moving_square_video(video)
    segmenter = _ThresholdSegmenter(blank_frames={3, 4})
    track = track_with_click(
        video, (30.0, 60.0), stride=1, segmenter=segmenter
    )
    assert isinstance(track, TrackResult)
    assert track.frames_total == 30
    assert track.frames_tracked == 28  # two blank frames are gaps
    assert track.gaps == [(3, 4)]
    assert track.coverage == pytest.approx(28 / 30)
    # The prompt chains: the second prompt is the first found centre.
    assert segmenter.prompts[1][0] == pytest.approx(30.0, abs=1.5)
    # ...and the track follows the square's walk to the right.
    assert track.xs[-1] > track.xs[0] + 50


def test_track_loop_never_found_is_all_gap(tmp_path):
    video = tmp_path / "moving.mp4"
    _write_moving_square_video(video, frames=6)
    segmenter = _ThresholdSegmenter(blank_frames=set(range(6)))
    track = track_with_click(
        video, (30.0, 60.0), stride=1, segmenter=segmenter
    )
    assert track.frames_tracked == 0
    assert track.coverage == 0.0
    assert track.gaps == [(0, 5)]


# ---------------------------------------------------------------- proof


@pytest.mark.slow
@pytest.mark.skipif(
    not HARD_CLIP.is_file() or not weights_present(),
    reason="the hard clip or the verified SAM weights are not on "
    "this machine",
)
def test_sam_tracks_the_clip_colour_cannot():
    """The proving test: the real model, the real classroom clip.

    The clip is the lesson's swing segment (122-132 s of the
    source): the small dark mass at the string's end, clicked at
    its true first-frame position (545, 575) -- the position a
    teacher clicking the object in the picker would choose.

    What is proven (measured 2026-11-26 on this machine): the
    colour tracker cannot run on this footage at all (the mass
    and the board share a colour band), while the click tracker
    returns a mask in 100% of the 50 examined frames -- coverage
    is the win, and it is what this test asserts.

    What is NOT proven, stated plainly: the track is not yet
    measurement-grade on this clip. Across four measured runs the
    chained prompt migrated off the small mass -- up the string
    it hangs from, and in one run onto the teacher -- so no
    period is recovered from the SAM track here (the lesson's
    true period is ~1.42 s; the colour/motion path remains the
    measurement route where a colour band exists). The audit
    trail with the numbers is in the project progress log.
    """
    track = track_with_click(HARD_CLIP, (545.0, 575.0), stride=5)
    assert track.coverage >= 0.85
