"""Ingest + generic object tracking (plan Phase 2.1).

Everything here is practical-agnostic: a video is probed with ffprobe,
frames are read, and a caller-supplied colour prompt tracks one object
through the clip. The result is a timed 2-D track plus a coverage report
-- the product never assumes what the tracked object is, what it is
made of, or what the motion means. Meaning is attached later, by the
template that owns the practical.

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


@dataclass
class TrackResult:
    """A timed 2-D track plus how completely it was observed."""

    times: np.ndarray  # seconds, tracked frames only
    xs: np.ndarray  # centroid x in pixels
    ys: np.ndarray  # centroid y in pixels
    fps: float
    frames_total: int
    frames_tracked: int
    gaps: list[tuple[int, int]] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Fraction of the frames EXAMINED in which the object was
        found. With a stride above 1 the tracker examines every
        stride-th frame, so this is a sampled coverage -- brief
        losses between examined frames are not visible to it."""
        if self.frames_total == 0:
            return 0.0
        return self.frames_tracked / self.frames_total


def track_object(
    path: str | Path, prompt: ColourPrompt, stride: int = 1
) -> TrackResult:
    """Track one colour-prompted object through a video.

    Frames where the object is not found are recorded as gaps (a range
    of frame indices) instead of failing the run -- a teacher's real
    footage will have occlusions, and the product must report them, not
    crash on them.
    """
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - environment guard
        raise EngineUnavailable(
            "OpenCV (opencv-python-headless) is required for tracking"
        ) from exc
    info = probe_video(path)
    times, xs, ys = [], [], []
    gaps: list[tuple[int, int]] = []
    gap_start: int | None = None
    frames_total = 0
    for index, t, frame in iter_frames(path, stride=stride):
        frames_total += 1
        mask = mask_for_prompt(frame, prompt)
        moments = cv2.moments(mask)
        if moments["m00"] < prompt.min_pixels:
            if gap_start is None:
                gap_start = index
            continue
        if gap_start is not None:
            gaps.append((gap_start, index - stride))
            gap_start = None
        xs.append(moments["m10"] / moments["m00"])
        ys.append(moments["m01"] / moments["m00"])
        times.append(t)
    if gap_start is not None:
        gaps.append((gap_start, index))
    return TrackResult(
        times=np.array(times),
        xs=np.array(xs),
        ys=np.array(ys),
        fps=info.fps,
        frames_total=frames_total,
        frames_tracked=len(times),
        gaps=gaps,
    )


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
    return {
        "fps": float(track.fps),
        "frames_examined": int(track.frames_total),
        "frames_tracked": int(track.frames_tracked),
        "coverage": float(track.coverage),
        "gaps": [[int(a), int(b)] for a, b in track.gaps],
        "times_s": [round(float(track.times[i]), 3) for i in keep],
        "xs_px": [round(float(track.xs[i]), 1) for i in keep],
        "ys_px": [round(float(track.ys[i]), 1) for i in keep],
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
