"""Ingest + generic object tracking (plan Phase 2.1).

Everything here is practical-agnostic: a video is probed with ffprobe,
frames are read, and a caller-supplied colour prompt tracks one object
through the clip. The result is a timed 2-D track plus a coverage report
-- the product never assumes what the tracked object is, what it is
made of, or what the motion means. Meaning is attached later, by the
template that owns the practical.

The tracker (improved 2026-11-26, Prince's order) follows the object
by CONTINUITY, not by whole-frame colour mass: candidate blobs are
scored against a constant-velocity prediction, the colour window is
sampled from a patch on the object itself and adapts as the light
shifts, and a brief loss is BRIDGED by interpolation -- with every
bridged point marked as bridged in the data, never presented as
measured. A loss too long to bridge is a FAILED span in the coverage
report, with a plain reason. No part of a demonstration is ever
silently dropped: every examined frame is accounted for as tracked,
bridged, or failed.

Periodic-motion analysis (equilibrium crossings -> mean period) is also
generic: it works on any roughly sinusoidal 1-D track. The experiment
proof under ``experiments/`` reuses these exact functions.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np

from . import resources


class IngestError(Exception):
    """The video file could not be read or probed."""


class EngineUnavailable(Exception):
    """A required external tool (ffprobe / OpenCV) is missing."""


# ---------------------------------------------------------------- probe


@dataclass
class VideoInfo:
    path: str
    duration_s: float
    fps: float
    width: int
    height: int
    codec: str
    has_audio: bool
    frame_count: int


def probe_video(path: str | Path) -> VideoInfo:
    """Read container metadata with ffprobe (no decode)."""
    path = Path(path)
    if not path.is_file():
        raise IngestError(f"video file not found: {path}")
    resolved = resources.ffprobe_path()
    if resolved is None:
        raise EngineUnavailable("ffprobe not available (no bundled copy found)")
    ffprobe = str(resolved)
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height,r_frame_rate,nb_frames",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise IngestError(f"ffprobe timed out on {path}") from None
    if proc.returncode != 0:
        raise IngestError(f"ffprobe failed on {path}: {proc.stderr.strip()}")
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise IngestError(
            f"ffprobe returned unreadable output for {path}"
        ) from None
    streams = data.get("streams", [])
    if not streams:
        raise IngestError(f"no video stream in {path}")
    stream = streams[0]
    try:
        num, den = str(stream.get("r_frame_rate", "30/1")).split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    except (ValueError, ZeroDivisionError):
        fps = 30.0  # an odd rate string must not kill the ingest
    # Audio presence: a second probe is cheap and keeps the first call simple.
    try:
        audio = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        has_audio = bool(audio.stdout.strip())
    except subprocess.TimeoutExpired:
        has_audio = False
    try:
        duration_s = float(data.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        duration_s = 0.0
    try:
        frame_count = int(stream.get("nb_frames") or 0)
    except (TypeError, ValueError):
        frame_count = 0  # ffprobe reports "N/A" for some containers
    return VideoInfo(
        path=str(path),
        duration_s=duration_s,
        fps=fps,
        width=int(stream.get("width", 0)),
        height=int(stream.get("height", 0)),
        codec=str(stream.get("codec_name", "")),
        has_audio=has_audio,
        frame_count=frame_count,
    )


# ------------------------------------------------------------ frame read


def iter_frames(
    path: str | Path, stride: int = 1
) -> Iterator[tuple[int, float, np.ndarray]]:
    """Yield (frame_index, time_s, BGR frame) every ``stride`` frames."""
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - environment guard
        raise EngineUnavailable(
            "OpenCV (opencv-python-headless) is required for frame ingest"
        ) from exc
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IngestError(f"could not open video {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
    index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if index % stride == 0:
                yield index, index / fps, frame
            index += 1
    finally:
        cap.release()


# ------------------------------------------------------------ tracking


@dataclass(frozen=True)
class ColourPrompt:
    """A caller-supplied colour definition for one tracked object.

    BGR channel ranges, inclusive. The prompt is *data supplied by the
    teacher/template* -- the tracker itself knows nothing about what the
    colour belongs to.
    """

    name: str
    bgr_low: tuple[int, int, int]
    bgr_high: tuple[int, int, int]
    min_pixels: int = 20


def mask_for_prompt(frame: np.ndarray, prompt: ColourPrompt) -> np.ndarray:
    """Binary mask (uint8 0/1) of pixels inside the prompt's BGR ranges."""
    channels = [frame[:, :, c].astype(np.int16) for c in range(3)]
    mask = np.ones(frame.shape[:2], dtype=bool)
    for c in range(3):
        mask &= (channels[c] >= prompt.bgr_low[c]) & (
            channels[c] <= prompt.bgr_high[c]
        )
    return mask.astype(np.uint8)


@dataclass(frozen=True)
class TrackSpan:
    """One run of examined frames with a single tracking outcome.

    ``kind`` is ``"tracked"`` (the object was measured in these
    frames), ``"bridged"`` (positions were interpolated across a
    brief loss and are marked as such in the track), or ``"failed"``
    (the object could not be followed here; ``reason`` says why, in
    plain words). Spans partition the examined frames: every frame
    the tracker looked at belongs to exactly one span.
    """

    kind: str
    start_frame: int
    end_frame: int  # inclusive
    start_s: float
    end_s: float
    reason: str = ""


@dataclass
class TrackResult:
    """A timed 2-D track plus how completely it was observed."""

    times: np.ndarray  # seconds, one entry per returned point
    xs: np.ndarray  # centroid x in pixels
    ys: np.ndarray  # centroid y in pixels
    fps: float
    frames_total: int
    frames_tracked: int  # returned points (measured + bridged)
    gaps: list[tuple[int, int]] = field(default_factory=list)
    # Per-point flag parallel to times/xs/ys: True where the point was
    # interpolated across a brief loss instead of measured. None means
    # the producing tracker does not bridge (all points measured).
    bridged: np.ndarray | None = None
    spans: list[TrackSpan] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Fraction of the frames EXAMINED for which the track has a
        position (measured or bridged). With a stride above 1 the
        tracker examines every stride-th frame, so this is a sampled
        coverage -- brief losses between examined frames are not
        visible to it."""
        if self.frames_total == 0:
            return 0.0
        return self.frames_tracked / self.frames_total

    @property
    def frames_measured(self) -> int:
        """Points that were actually observed (not interpolated)."""
        if self.bridged is None:
            return self.frames_tracked
        return self.frames_tracked - int(np.count_nonzero(self.bridged))

    @property
    def measured_coverage(self) -> float:
        """Fraction of examined frames in which the object was truly
        measured -- the honest headline number (bridged frames do not
        count toward it)."""
        if self.frames_total == 0:
            return 0.0
        return self.frames_measured / self.frames_total


# ------------------------------------------- colour tracker (improved)
#
# Failure modes closed here (Prince, 2026-11-26): a hand crossing the
# object, a lighting shift mid-recording, fast motion with blur, and a
# same-colour distractor elsewhere in frame. The engine: connected
# components propose candidate blobs; a constant-velocity prediction
# chooses among them by continuity; the HSV colour window is seeded
# from the caller's prompt band, then sampled from a PATCH on the
# accepted object each frame and adapted gradually (with clamped
# drift, so it can follow the light but never wander onto another
# object); a component covering most of the frame is background, not
# an object -- a prompt that matches the wall must report "not
# found", never track the wall's centroid and call it success.

_BG_AREA_FRACTION = 0.40  # a blob bigger than this is the background
_BRIDGE_SECONDS = 1.5  # longest loss interpolated across, in seconds
_LOCK_SCORE = 3000.0  # chain score that locks acquisition immediately
_PATIENT_BUFFER = 120  # examined frames after which weaker evidence locks
_BAND_EMA = 0.12  # colour-offset learning rate per accepted frame
# Max per-channel learned offset from the (gain-scaled) seed band:
# the scene-gain scaling does the heavy lifting for lighting shifts,
# so the learned part only ever needs to correct a little -- and a
# tight clamp means it can never wander onto another object.
_BAND_DRIFT = 40.0

_MISS_TEXT = {
    "not_visible": (
        "the object could not be seen — it may have been hidden, "
        "out of frame, or too dark"
    ),
    "background": "only the background matched the object's colour here",
    "out_of_reach": "the object moved too far between frames to follow safely",
}


def _band_mask(
    frame: np.ndarray, low: np.ndarray, high: np.ndarray
) -> np.ndarray:
    """Binary mask (uint8 0/1) of pixels inside a BGR band."""
    mask = np.ones(frame.shape[:2], dtype=bool)
    for c in range(3):
        channel = frame[:, :, c].astype(np.float32)
        mask &= (channel >= low[c]) & (channel <= high[c])
    return mask.astype(np.uint8)


def _blob_candidates(
    cv2, mask: np.ndarray, min_pixels: int, frame_area: int
) -> tuple[list[tuple[float, float, float]], bool]:
    """Connected components of the mask as (cx, cy, area) candidates.

    Components smaller than ``min_pixels`` are noise; a component
    covering more than ``_BG_AREA_FRACTION`` of the frame is the
    background (returned separately as a flag so the caller can say
    so), never an object candidate.
    """
    _n, _labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    out: list[tuple[float, float, float]] = []
    background_only = False
    for i in range(1, stats.shape[0]):
        area = float(stats[i, cv2.CC_STAT_AREA])
        if area < min_pixels:
            continue
        if frame_area and area > _BG_AREA_FRACTION * frame_area:
            background_only = True
            continue
        out.append(
            (float(centroids[i][0]), float(centroids[i][1]), area)
        )
    return out, background_only


def _scene_gain(frame: np.ndarray, ref_median: np.ndarray) -> np.ndarray:
    """Per-channel gain of this frame's scene relative to the
    reference frame (median colour of a subsample -- the scene is
    mostly background in a demonstration, so the median tracks the
    illumination, not the object). A lighting shift scales every
    colour in the scene by roughly this gain; a stable scene gives
    ~1.0 whatever the object does."""
    sample = frame[::8, ::8].reshape(-1, 3).astype(np.float64)
    cur = np.median(sample, axis=0)
    gain = cur / np.maximum(ref_median, 1.0)
    return np.clip(gain, 0.4, 2.5)


def _update_band_offset(
    frame: np.ndarray,
    cx: float,
    cy: float,
    area: float,
    low: np.ndarray,
    high: np.ndarray,
    seed_centre: np.ndarray,
    gain: np.ndarray,
    offset: np.ndarray,
) -> None:
    """Learn a small correction to the gain-scaled seed band from
    the object's own colours, sampled from a patch on its CORE
    around the accepted centroid (never a single pixel; edge pixels
    are anti-aliased mixtures that would drag the band). The offset
    is clamped tight -- the gain scaling handles lighting, so this
    only corrects the difference between the prompt's nominal colour
    and this object's actual colour, and it cannot wander onto a
    different object."""
    radius = int(min(48, max(3, round(0.35 * np.sqrt(area / np.pi)))))
    y0, y1 = max(0, int(cy) - radius), min(frame.shape[0], int(cy) + radius + 1)
    x0, x1 = max(0, int(cx) - radius), min(frame.shape[1], int(cx) + radius + 1)
    patch = frame[y0:y1, x0:x1].reshape(-1, 3).astype(np.float64)
    if patch.shape[0] == 0:
        return
    in_band = np.ones(patch.shape[0], dtype=bool)
    for c in range(3):
        in_band &= (patch[:, c] >= low[c]) & (patch[:, c] <= high[c])
    inliers = patch[in_band]
    if inliers.shape[0] < 8:
        return
    target_offset = np.median(inliers, axis=0) - seed_centre * gain
    offset[:] = offset + _BAND_EMA * (target_offset - offset)
    offset[:] = np.clip(offset, -_BAND_DRIFT, _BAND_DRIFT)


def _best_moving_chain(
    cands_seq: list[list[tuple[float, float, float]]],
    min_pixels: int,
) -> tuple[dict[int, tuple[float, float, float]], float] | None:
    """Chain candidate blobs across the buffered opening frames and
    return the chain that behaves like a demonstrated object: present
    in most frames and actually MOVING. Static scenery of the right
    colour (a banner, a board) chains perfectly but never moves, so
    it can never win -- acquisition by motion, not by size.

    Returns ({buffer position: candidate}, score) or None.

    The evidence bar is deliberately strict, because three impostors
    are common in real footage: a huge scenery blob whose centroid
    jitters as the blob fragments and merges (tens of pixels of fake
    "motion" on a blob hundreds of pixels wide); a tiny fragment of
    the real object (a fingertip, a highlight) whose travel measured
    in its own radii looks enormous; and the object itself held
    still in a hand at the start. So a chain must have at least 8
    points, a median area at least 6x the prompt's noise floor (the
    demonstrated object is a substantial thing, not a speck), and
    travel at least ~1.2 of its own radii; it is scored by
    persistence x travel x root-area, which a real object wins by
    orders of magnitude. A held object simply locks a little later,
    once it moves."""
    all_chains: list[list[tuple[int, tuple[float, float, float]]]] = []
    active: list[tuple[list, tuple[float, float], int]] = []
    for fi, cands in enumerate(cands_seq):
        used: set[int] = set()
        still_active = []
        for chain, last, missed in active:
            best_i, best_d = None, float("inf")
            for ci, c in enumerate(cands):
                if ci in used:
                    continue
                d = float(np.hypot(c[0] - last[0], c[1] - last[1]))
                if d < best_d:
                    best_d, best_i = d, ci
            if best_i is not None and best_d <= 60.0:
                used.add(best_i)
                chain.append((fi, cands[best_i]))
                still_active.append(
                    (chain, (cands[best_i][0], cands[best_i][1]), 0)
                )
            elif missed < 2:
                still_active.append((chain, last, missed + 1))
        for ci, c in enumerate(cands):
            if ci not in used:
                chain = [(fi, c)]
                all_chains.append(chain)
                still_active.append((chain, (c[0], c[1]), 0))
        active = still_active
    best: list | None = None
    best_score = -1.0
    for chain in all_chains:
        if len(chain) < 8:
            continue
        xs = [c[0] for _fi, c in chain]
        ys = [c[1] for _fi, c in chain]
        areas = [c[2] for _fi, c in chain]
        median_area = float(np.median(areas))
        if median_area < 6.0 * min_pixels:
            continue  # a speck or a fragment, not the demonstrated object
        extent = max(max(xs) - min(xs), max(ys) - min(ys))
        radius = float(np.sqrt(median_area / np.pi))
        if extent < max(12.0, 1.2 * radius):
            continue  # scenery or a held object: not yet a demonstration
        score = len(chain) * extent * float(np.sqrt(median_area))
        if score > best_score:
            best, best_score = chain, score
    if best is None:
        return None
    return {fi: c for fi, c in best}, best_score


def _extend_chain_backward(
    cands_seq: list[list[tuple[float, float, float]]],
    chain: dict[int, tuple[float, float, float]],
    max_gap: int,
) -> dict[int, tuple[float, float, float]]:
    """Extend a winning chain BACKWARD through the buffered
    candidates. The object was usually already moving before its
    chain scored high enough to lock -- it was just fragmented or
    merged with a hand -- so walking back from the chain's first
    point, always taking the candidate nearest the backward
    prediction, recovers those frames as the measurements they are
    instead of writing them off as a failed span. The walk stops
    after ``max_gap`` consecutive frames with no plausible candidate
    (the replay bridges shorter gaps between recovered points)."""
    if not chain:
        return chain
    extended = dict(chain)
    start = min(chain)
    pos = np.array(chain[start][:2], dtype=np.float64)
    following = [p for p in sorted(chain) if p > start]
    if following:
        nxt = following[0]
        velocity = (
            np.array(chain[nxt][:2], dtype=np.float64) - pos
        ) / (nxt - start)
    else:
        velocity = np.zeros(2)
    gap = 0
    for bp in range(start - 1, -1, -1):
        if gap > max_gap:
            break
        predicted = pos - velocity * (gap + 1)
        cands = cands_seq[bp]
        if not cands:
            gap += 1
            continue
        best = min(
            cands,
            key=lambda c: float(
                np.hypot(c[0] - predicted[0], c[1] - predicted[1])
            ),
        )
        dist = float(np.hypot(best[0] - predicted[0], best[1] - predicted[1]))
        gate = min(
            max(48.0, 3.0 * float(np.hypot(*velocity))) * (1.0 + 0.4 * gap),
            160.0,
        )
        if dist > gate:
            gap += 1
            continue
        implied = (pos - np.array(best[:2], dtype=np.float64)) / (gap + 1)
        velocity = 0.5 * velocity + 0.5 * implied
        pos = np.array(best[:2], dtype=np.float64)
        extended[bp] = best
        gap = 0
    return extended


def _cluster_around(
    candidates: list[tuple[float, float, float]],
    core: tuple[float, float, float],
    radius: float,
) -> tuple[float, float, float]:
    """Merge the fragments of one object: candidates whose centroids
    lie within ``radius`` of the core candidate are really one object
    split by shadow or shading, so their area-weighted centroid and
    summed area describe the object better than any single fragment.
    Candidates farther away (a hand, a distractor) stay out."""
    cx, cy, area = core
    total = area
    sx, sy = cx * area, cy * area
    for ox, oy, oa in candidates:
        if (ox, oy, oa) == core:
            continue
        if float(np.hypot(ox - cx, oy - cy)) <= radius:
            sx += ox * oa
            sy += oy * oa
            total += oa
    return sx / total, sy / total, total


def track_object(
    path: str | Path, prompt: ColourPrompt, stride: int = 1
) -> TrackResult:
    """Track one colour-prompted object through a video.

    Acquisition is by MOTION: the opening frames are buffered and
    the tracker locks onto the colour candidate that actually moves
    (a demonstration is of a moving object; the biggest blob of the
    right colour is usually scenery). From there the object is
    followed by continuity: a constant-velocity prediction picks the
    plausible blob among the candidates, the colour window adapts to
    the light, brief losses (up to ~1.5 s) are bridged by
    interpolation and the bridged points are MARKED, and longer
    losses become failed spans in the coverage report. Nothing is
    dropped silently -- see :func:`coverage_report`.
    """
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - environment guard
        raise EngineUnavailable(
            "OpenCV (opencv-python-headless) is required for tracking"
        ) from exc
    info = probe_video(path)
    fps = info.fps or 30.0
    max_bridge = max(2, int(round(_BRIDGE_SECONDS * fps / max(1, stride))))

    # The colour band starts as the caller's prompt band. Each frame
    # it is re-derived: scaled by the scene's gain (lighting shifts
    # move every colour in the scene together) plus a small learned
    # offset from patches on the accepted object.
    seed_low = np.array(prompt.bgr_low, dtype=np.float64)
    seed_high = np.array(prompt.bgr_high, dtype=np.float64)
    seed_centre = 0.5 * (seed_low + seed_high)
    seed_half = 0.5 * (seed_high - seed_low)
    band_low = seed_low.copy()
    band_high = seed_high.copy()
    band_offset = np.zeros(3)
    gain_cell = np.ones(3)
    ref_median: np.ndarray | None = None

    frame_area = info.width * info.height
    state: dict = {
        "last_pos": None,
        "velocity": np.zeros(2),
        "speed_ref": 0.0,  # decaying max of recent step speeds (gate scale)
        "have_velocity": False,
        "last_area": 0.0,
        "misses": 0,
        "pending": [],  # (frame index, time) since the last accept
        "miss_reasons": [],
        "measured": {},
        "bridged": {},
        "failed": [],  # (start index, end index, reason code)
    }
    examined: list[int] = []

    def _miss(index: int, t: float, code: str) -> None:
        state["misses"] += 1
        state["pending"].append((index, t))
        state["miss_reasons"].append(code)

    def _accept(index: int, t: float, chosen, update_model=None) -> None:
        cx, cy, area = chosen
        pending = state["pending"]
        last_pos = state["last_pos"]
        if pending:
            if last_pos is not None and len(pending) <= max_bridge:
                steps = len(pending) + 1
                for k, (pi, pt) in enumerate(pending, start=1):
                    frac = k / steps
                    state["bridged"][pi] = (
                        pt,
                        float(last_pos[0] + (cx - last_pos[0]) * frac),
                        float(last_pos[1] + (cy - last_pos[1]) * frac),
                    )
            else:
                code = (
                    "start"
                    if last_pos is None
                    else (
                        state["miss_reasons"][-1]
                        if state["miss_reasons"]
                        else "not_visible"
                    )
                )
                state["failed"].append((pending[0][0], pending[-1][0], code))
        if last_pos is not None and len(pending) <= max_bridge:
            steps = len(pending) + 1
            inst = np.array(
                [(cx - last_pos[0]) / steps, (cy - last_pos[1]) / steps]
            )
            state["velocity"] = (
                inst
                if not state["have_velocity"]
                else 0.5 * state["velocity"] + 0.5 * inst
            )
            state["have_velocity"] = True
            # The gate is scaled by how fast the object has recently
            # been seen to move (decaying slowly), not by the current
            # velocity vector alone: at a swing's turning point the
            # vector reverses and shrinks, but the object is about to
            # come back at full speed -- a gate keyed to the vector
            # loses it there, exactly where real footage needs it.
            inst_speed = float(np.hypot(inst[0], inst[1]))
            state["speed_ref"] = max(
                inst_speed, state["speed_ref"] * 0.95
            )
        else:
            state["velocity"] = np.zeros(2)
            state["have_velocity"] = False
            state["speed_ref"] = 0.0
        state["measured"][index] = (t, cx, cy)
        state["last_pos"] = np.array([cx, cy])
        state["last_area"] = (
            area
            if not state["last_area"]
            else 0.7 * state["last_area"] + 0.3 * area
        )
        if update_model is not None:
            _update_band_offset(
                update_model,
                cx,
                cy,
                area,
                band_low,
                band_high,
                seed_centre,
                gain_cell,
                band_offset,
            )
        state["misses"] = 0
        state["pending"] = []
        state["miss_reasons"] = []

    # ---- phase A: buffer the opening, lock onto what moves.
    buffer: list[tuple[int, float, list, bool]] = []
    reacq: list[tuple[int, float, list, bool]] = []
    locked = False
    frames_iter = iter_frames(path, stride=stride)
    for index, t, frame in frames_iter:
        examined.append(index)
        if not frame_area:
            frame_area = frame.shape[0] * frame.shape[1]
        # This frame's effective colour band: the seed band scaled
        # by the scene gain, plus the learned offset.
        if ref_median is None:
            ref_median = np.median(
                frame[::8, ::8].reshape(-1, 3).astype(np.float64), axis=0
            )
            gain_cell[:] = 1.0
        else:
            gain_cell[:] = _scene_gain(frame, ref_median)
        centre_now = seed_centre * gain_cell + band_offset
        half_now = np.maximum(seed_half * gain_cell, 6.0)
        band_low[:] = np.clip(centre_now - half_now, 0.0, 255.0)
        band_high[:] = np.clip(centre_now + half_now, 0.0, 255.0)
        if not locked:
            mask = _band_mask(frame, band_low, band_high)
            candidates, background_only = _blob_candidates(
                cv2, mask, prompt.min_pixels, frame_area
            )
            buffer.append((index, t, candidates, background_only))
            chain = None
            if len(buffer) >= 8 and (
                len(buffer) <= 120 or len(buffer) % 15 == 0
            ):
                found = _best_moving_chain(
                    [b[2] for b in buffer], prompt.min_pixels
                )
                if found is not None:
                    mapping, score = found
                    # Overwhelming evidence locks at once; weaker
                    # evidence must first survive a patient buffer,
                    # so an early impostor chain cannot win a race
                    # against the real object appearing later.
                    if score >= _LOCK_SCORE or len(buffer) >= _PATIENT_BUFFER:
                        chain = mapping
            if chain is None and len(buffer) > 900:
                # Bound the buffer: the oldest frames age out as
                # misses (they become a failed span at the start).
                for bi, bt, bc, bbg in buffer[:300]:
                    _miss(bi, bt, "background" if (bbg and not bc) else "not_visible")
                buffer = buffer[300:]
                continue
            if chain is None:
                continue
            chain = _extend_chain_backward(
                [b[2] for b in buffer], chain, max_bridge
            )
            # Replay the buffer through the accept/miss bookkeeping:
            # chain frames are measurements, the rest are misses.
            for pos, (bi, bt, bc, bbg) in enumerate(buffer):
                if pos in chain:
                    _accept(bi, bt, chain[pos])
                else:
                    _miss(
                        bi,
                        bt,
                        "background" if (bbg and not bc) else "not_visible",
                    )
            buffer = []
            locked = True
            continue

        # ---- phase B: follow by continuity. Candidate blobs come
        # from the (adapting) colour band; the constant-velocity
        # prediction picks the plausible one and its nearby fragments
        # are clustered back into the whole object.
        mask = _band_mask(frame, band_low, band_high)
        candidates, background_only = _blob_candidates(
            cv2, mask, prompt.min_pixels, frame_area
        )
        last_pos = state["last_pos"]
        misses = state["misses"]
        radius = (
            np.sqrt(state["last_area"] / np.pi) if state["last_area"] else 12.0
        )
        if misses > max_bridge:
            # Re-acquisition after a failed span is by MOTION, like
            # the initial acquisition: buffer the candidates and
            # lock onto a chain that moves. A static colour-matched
            # fragment (a rail, a mark on the board) can never
            # re-acquire the track -- only the object can.
            reacq.append((index, t, candidates, background_only))
            found = None
            if len(reacq) >= 8:
                found = _best_moving_chain(
                    [r[2] for r in reacq], prompt.min_pixels
                )
            if found is not None:
                mapping, _score = found
                mapping = _extend_chain_backward(
                    [r[2] for r in reacq], mapping, max_bridge
                )
                for pos, (ri, rt, rc, rbg) in enumerate(reacq):
                    if pos in mapping:
                        _accept(ri, rt, mapping[pos])
                    else:
                        _miss(
                            ri,
                            rt,
                            "background"
                            if (rbg and not rc)
                            else "not_visible",
                        )
                reacq = []
            elif len(reacq) > 45:
                ri, rt, rc, rbg = reacq.pop(0)
                _miss(
                    ri, rt, "background" if (rbg and not rc) else "not_visible"
                )
            continue
        if not candidates:
            _miss(
                index,
                t,
                "background" if background_only else "not_visible",
            )
            continue
        speed = max(
            float(np.hypot(*state["velocity"])), state["speed_ref"]
        )
        gate = max(28.0, 2.4 * speed + 0.6 * radius) * (1.0 + 0.6 * misses)
        gate = min(
            gate, 0.30 * float(np.hypot(frame.shape[1], frame.shape[0]))
        )
        predicted = last_pos + state["velocity"] * (misses + 1)
        core = min(
            candidates,
            key=lambda c: float(
                np.hypot(c[0] - predicted[0], c[1] - predicted[1])
            ),
        )
        clustered = _cluster_around(
            candidates, core, max(2.2 * radius, 30.0)
        )
        dist = float(
            np.hypot(clustered[0] - predicted[0], clustered[1] - predicted[1])
        )
        if dist <= gate:
            chosen = clustered
        elif float(
            np.hypot(core[0] - predicted[0], core[1] - predicted[1])
        ) <= gate:
            chosen = core
        else:
            _miss(index, t, "out_of_reach")
            continue
        _accept(index, t, chosen, update_model=frame)

    if not locked:
        # Nothing in the whole recording moved like an object of
        # this colour: every buffered frame is a miss, and the
        # coverage report says so plainly.
        for bi, bt, bc, bbg in buffer:
            _miss(bi, bt, "background" if (bbg and not bc) else "not_visible")
    # Frames still held in the re-acquisition buffer when the
    # recording ends are misses too -- nothing is left unaccounted.
    for ri, rt, rc, rbg in reacq:
        _miss(ri, rt, "background" if (rbg and not rc) else "not_visible")
    if state["pending"]:
        code = (
            "start"
            if state["last_pos"] is None
            else (
                state["miss_reasons"][-1]
                if state["miss_reasons"]
                else "not_visible"
            )
        )
        state["failed"].append(
            (state["pending"][0][0], state["pending"][-1][0], code)
        )

    measured = state["measured"]
    bridged_pts = state["bridged"]

    # ---- assemble the point series (measured + bridged, in order).
    order = sorted(set(measured) | set(bridged_pts))
    if order:
        times = np.array([measured.get(i, bridged_pts.get(i))[0] for i in order])
        xs = np.array([measured.get(i, bridged_pts.get(i))[1] for i in order])
        ys = np.array([measured.get(i, bridged_pts.get(i))[2] for i in order])
    else:
        times = xs = ys = np.empty(0)
    bridged_flags = np.array([i in bridged_pts for i in order], dtype=bool)

    # ---- classify every examined frame and merge runs into spans.
    failed_map = {}
    for start, end, code in state["failed"]:
        for i in examined:
            if start <= i <= end:
                failed_map[i] = code
    spans: list[TrackSpan] = []
    gaps: list[tuple[int, int]] = []
    run: dict = {"kind": None, "start": 0, "code": ""}

    def _close_run(end_index: int) -> None:
        if run["kind"] is None:
            return
        reason = ""
        if run["kind"] == "failed":
            if not measured or run["start"] < min(measured):
                reason = (
                    "the object could not be picked out at the start "
                    "of the recording"
                )
            elif run["start"] > max(measured):
                reason = (
                    "the recording ends before the object is seen again — "
                    + _MISS_TEXT.get(run["code"], _MISS_TEXT["not_visible"])
                )
            else:
                reason = _MISS_TEXT.get(run["code"], _MISS_TEXT["not_visible"])
        spans.append(
            TrackSpan(
                kind=run["kind"],
                start_frame=run["start"],
                end_frame=end_index,
                start_s=run["start"] / fps,
                end_s=end_index / fps,
                reason=reason,
            )
        )
        if run["kind"] in ("bridged", "failed"):
            gaps.append((run["start"], end_index))

    prev_index = examined[-1] if examined else 0
    for i in examined:
        if i in measured:
            kind, code = "tracked", ""
        elif i in bridged_pts:
            kind, code = "bridged", ""
        else:
            kind, code = "failed", failed_map.get(i, "not_visible")
        if kind != run["kind"] or (kind == "failed" and code != run["code"]):
            _close_run(prev_index)
            run["kind"], run["start"], run["code"] = kind, i, code
        prev_index = i
    _close_run(prev_index)

    return TrackResult(
        times=times,
        xs=xs,
        ys=ys,
        fps=fps,
        frames_total=len(examined),
        frames_tracked=len(order),
        gaps=gaps,
        bridged=bridged_flags,
        spans=spans,
    )

def _mmss(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def coverage_report(track: TrackResult) -> dict:
    """The honesty layer as data: how much of the recording was truly
    measured, how much was bridged, and which spans failed and why.
    JSON-safe; stored with every saved track."""
    measured = track.frames_measured
    bridged_n = track.frames_tracked - measured
    return {
        "frames_examined": int(track.frames_total),
        "frames_measured": int(measured),
        "frames_bridged": int(bridged_n),
        "measured_pct": float(track.measured_coverage),
        "with_bridged_pct": float(track.coverage),
        "spans": [
            {
                "kind": s.kind,
                "start_frame": int(s.start_frame),
                "end_frame": int(s.end_frame),
                "start_s": round(float(s.start_s), 3),
                "end_s": round(float(s.end_s), 3),
                "reason": s.reason,
            }
            for s in track.spans
        ],
        "summary": coverage_summary(track),
    }


def coverage_summary(track: TrackResult) -> str:
    """The coverage report in plain words, for status lines and
    records. Bridged and failed parts are always named -- a part of
    the demonstration is never silently missing."""
    if track.frames_total == 0:
        return "No frames could be examined in this recording."
    pct = track.measured_coverage
    bridged_spans = [s for s in track.spans if s.kind == "bridged"]
    failed_spans = [s for s in track.spans if s.kind == "failed"]
    if pct >= 1.0 and not bridged_spans and not failed_spans:
        return "The object was followed directly for the whole recording."
    parts = [f"The object was followed directly in {pct:.0%} of the recording."]
    if bridged_spans:
        ranges = ", ".join(
            f"{_mmss(s.start_s)}–{_mmss(s.end_s)}" for s in bridged_spans[:3]
        )
        extra = (
            f" and {len(bridged_spans) - 3} more"
            if len(bridged_spans) > 3
            else ""
        )
        parts.append(
            f"{len(bridged_spans)} short part{'s' if len(bridged_spans) > 1 else ''} "
            f"({ranges}{extra}) lost the object briefly and "
            f"{'were' if len(bridged_spans) > 1 else 'was'} bridged from the "
            "motion either side — those points are marked as bridged, "
            "not measured."
        )
    if failed_spans:
        ranges = ", ".join(
            f"{_mmss(s.start_s)}–{_mmss(s.end_s)}" for s in failed_spans[:3]
        )
        extra = (
            f" and {len(failed_spans) - 3} more"
            if len(failed_spans) > 3
            else ""
        )
        parts.append(
            f"{len(failed_spans)} part{'s' if len(failed_spans) > 1 else ''} "
            f"({ranges}{extra}) could not be followed — those moments "
            "are missing from the motion record."
        )
    return " ".join(parts)


def serialise_track(track: TrackResult, max_points: int = 600) -> dict:
    """JSON-safe form of a track for a project's Demonstration
    record: the coverage report plus the timed points, evenly
    downsampled to at most ``max_points`` so a long recording stays
    a small record. The full-resolution track is a working value;
    the record keeps enough to re-plot and re-analyse the motion."""
    n = int(track.times.size)
    if n > max_points:
        keep = np.linspace(0, n - 1, max_points).astype(int)
    else:
        keep = np.arange(n)
    if track.bridged is not None:
        bridged_flags = [bool(track.bridged[i]) for i in keep]
    else:
        bridged_flags = [False] * len(keep)
    return {
        "fps": float(track.fps),
        "frames_examined": int(track.frames_total),
        "frames_tracked": int(track.frames_tracked),
        "coverage": float(track.coverage),
        "coverage_measured": float(track.measured_coverage),
        "gaps": [[int(a), int(b)] for a, b in track.gaps],
        "times_s": [round(float(track.times[i]), 3) for i in keep],
        "xs_px": [round(float(track.xs[i]), 1) for i in keep],
        "ys_px": [round(float(track.ys[i]), 1) for i in keep],
        # Bridged points stay marked in the record, and the full
        # coverage report (spans + plain-words summary) travels with
        # the track so no part of the demonstration is silently lost.
        "bridged": bridged_flags,
        "coverage_report": coverage_report(track),
    }


# ------------------------------------------------- periodic-motion analysis


def upward_crossing_times(t: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Times at which y crosses zero going upward, linearly interpolated
    between samples so the estimate is not quantised to the sample grid."""
    idx = np.where((y[:-1] < 0.0) & (y[1:] >= 0.0))[0]
    if idx.size == 0:
        return np.empty(0)
    frac = -y[idx] / (y[idx + 1] - y[idx])
    return t[idx] + frac * (t[idx + 1] - t[idx])


def period_from_crossings(crossings: np.ndarray) -> tuple[float, np.ndarray]:
    """Mean period and the individual intervals between upward crossings."""
    intervals = np.diff(crossings)
    if intervals.size == 0:
        raise ValueError("fewer than two upward crossings: no period")
    return float(intervals.mean()), intervals


def split_period_estimates(intervals: np.ndarray) -> tuple[float, float]:
    """Two period estimates from the first and second halves of the
    crossing intervals -- the analogue of timing the same run twice."""
    if intervals.size == 0:
        raise ValueError("no crossing intervals: no period estimates")
    if intervals.size < 2:
        only = float(intervals.mean())
        return only, only
    half = intervals.size // 2
    return float(intervals[:half].mean()), float(intervals[half:].mean())


@dataclass
class PeriodicAnalysis:
    mean_period_s: float
    period_first_half_s: float
    period_second_half_s: float
    n_crossings: int
    extent_px: float
    equilibrium_px: float


def analyse_periodic(track: TrackResult, axis: str = "x") -> PeriodicAnalysis:
    """Period of a roughly periodic 1-D track about its equilibrium
    (midpoint of the track's extremes)."""
    values = track.xs if axis == "x" else track.ys
    if values.size < 4:
        raise ValueError("track too short for periodic analysis")
    equilibrium = 0.5 * (float(values.max()) + float(values.min()))
    crossings = upward_crossing_times(track.times, values - equilibrium)
    period, intervals = period_from_crossings(crossings)
    first_half, second_half = split_period_estimates(intervals)
    return PeriodicAnalysis(
        mean_period_s=period,
        period_first_half_s=first_half,
        period_second_half_s=second_half,
        n_crossings=int(crossings.size),
        extent_px=float(values.max() - values.min()),
        equilibrium_px=equilibrium,
    )
