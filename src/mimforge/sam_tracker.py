"""Click-prompted segmentation tracking (plan Phase 2, hard cases).

The colour tracker (``perception.track_object``) finds an object by
its colour band. Some real footage defeats that completely: an
object whose colour matches the background behind it is invisible
to any colour band, however carefully tuned. This module is the
second tracker for exactly those cases. The teacher clicks the
object once, on the first frame; SAM 2.1 (Meta's Segment Anything
Model 2.1, hiera-tiny) segments it, and the mask is followed from
frame to frame, each new frame prompted with points sampled
inside the previous frame's mask. The output is the same
``TrackResult`` the colour tracker returns, so everything
downstream -- periodic analysis, the demonstration record,
verification -- is unchanged.

Runtime, honestly stated:

- Inference is ONNX Runtime on the CPU (no torch): an image
  encoder run once per examined frame plus a small prompt/mask
  decoder per prompt. The ONNX export used is the ``cstr``
  conversion of Meta's checkpoint -- a format conversion only, no
  weights retrained -- redistributed under the same Apache-2.0
  licence as the original model (see docs/SBOM.md).
- The two model files (~130 MB together) are NOT bundled with the
  app. They download once, on first use, into the app's data
  folder, are verified against the publisher's SHA-256 hashes,
  and work offline from then on. A file that fails verification
  is deleted and reported in plain words, never used.
- This is the image model applied per examined frame with prompt
  chaining, not SAM 2's video-memory predictor; on slow hardware
  the frame stride is what keeps a long clip practical.
- Measured limit (2026-11-26, proving clip in the test suite):
  the model returns a mask in every examined frame of footage
  the colour tracker cannot run on at all, but the chained
  prompt does not hold a small object that hangs from a long
  thin structure for a whole clip -- it migrates onto the
  structure. Treat this tracker's output as a found-object
  track, not a measurement, until a stronger propagation
  (the video-memory predictor) replaces the chaining.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .perception import EngineUnavailable, TrackResult, iter_frames, probe_video

__all__ = [
    "SamError",
    "SamSegmenter",
    "ensure_weights",
    "track_with_click",
    "weights_dir",
    "weights_present",
]

MODEL_FOLDER = "sam2.1-hiera-tiny"

# The publisher's file table (cstr/sam2.1-hiera-tiny-ONNX on
# Hugging Face, Apache-2.0): name -> (download URL, size, SHA-256).
# A downloaded file is trusted only when both checks pass.
_WEIGHT_FILES = {
    "encoder.onnx": (
        "https://huggingface.co/cstr/sam2.1-hiera-tiny-ONNX"
        "/resolve/main/encoder.onnx",
        109_473_919,
        "4fda6e68561e27808cedffa8689749a622bba5f11ba66f4ca4e3a8a9f6360db5",
    ),
    "decoder.onnx": (
        "https://huggingface.co/cstr/sam2.1-hiera-tiny-ONNX"
        "/resolve/main/decoder.onnx",
        20_655_795,
        "0ae944e08e55814c19afa4d143ef07b1a3dbad2decd77c15ec3ab220b9f57247",
    ),
}

_TOTAL_WEIGHT_BYTES = sum(spec[1] for spec in _WEIGHT_FILES.values())

# SAM 2's image normalisation (the export's documented contract).
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_INPUT_SIZE = 1024

ProgressFn = Callable[[float, str], None]


class SamError(Exception):
    """A click-tracker failure, in plain words safe to show."""


# ------------------------------------------------------------- weights


def weights_dir(base: str | Path | None = None) -> Path:
    """Where the model files live: ``MIMFORGE_SAM_DIR`` when set,
    else a ``models`` folder beside the app's projects folder."""
    override = os.environ.get("MIMFORGE_SAM_DIR")
    if override:
        return Path(override)
    if base is not None:
        return Path(base) / "models" / MODEL_FOLDER
    return Path.home() / "Mimforge" / "models" / MODEL_FOLDER


def _file_ok(path: Path, size: int, sha256: str) -> bool:
    try:
        if path.stat().st_size != size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest() == sha256
    except OSError:
        return False


def weights_present(folder: str | Path | None = None) -> bool:
    """True only when both model files are present AND verify."""
    folder = Path(folder) if folder is not None else weights_dir()
    return all(
        _file_ok(folder / name, size, sha256)
        for name, (_url, size, sha256) in _WEIGHT_FILES.items()
    )


def _download(url: str, dest: Path, progress: ProgressFn | None, base_done: int) -> None:
    """Stream one file to ``dest``, reporting overall progress."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "mimforge-sam-tracker"}
    )
    done = base_done
    with urllib.request.urlopen(request, timeout=60) as response:
        with dest.open("wb") as out:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(
                        min(1.0, done / _TOTAL_WEIGHT_BYTES),
                        "DOWNLOADING THE CLICK-TRACKING MODEL — "
                        f"{done / 1e6:.0f} OF {_TOTAL_WEIGHT_BYTES / 1e6:.0f} MB",
                    )


def ensure_weights(
    folder: str | Path | None = None,
    progress: ProgressFn | None = None,
    downloader: Callable[[str, Path, ProgressFn | None, int], None] | None = None,
) -> Path:
    """Make sure verified model files exist, downloading the
    missing ones once. Returns the folder. Any failure is a
    ``SamError`` in plain words; an unverified file is removed,
    never kept."""
    folder = Path(folder) if folder is not None else weights_dir()
    fetch = downloader or _download
    done = 0
    for name, (url, size, sha256) in _WEIGHT_FILES.items():
        target = folder / name
        if _file_ok(target, size, sha256):
            done += size
            continue
        try:
            folder.mkdir(parents=True, exist_ok=True)
            partial = folder / (name + ".part")
            fetch(url, partial, progress, done)
            if not _file_ok(partial, size, sha256):
                partial.unlink(missing_ok=True)
                raise SamError(
                    "The downloaded model file did not check out — "
                    "it was removed. Try the download again."
                )
            partial.replace(target)
        except SamError:
            raise
        except Exception as exc:
            raise SamError(
                "The click-tracking model could not be downloaded — "
                "check the network connection and try again."
            ) from exc
        done += size
    return folder


# ------------------------------------------------------------ segmenter


class SamSegmenter:
    """One loaded SAM 2.1 (encoder + decoder ONNX sessions).

    Sessions are created lazily on first use and can be injected
    (``session_factory``) so tests exercise the pre/post-processing
    without the real model files.
    """

    def __init__(
        self,
        folder: str | Path | None = None,
        session_factory: Callable[[Path, Path], tuple] | None = None,
    ) -> None:
        self._folder = Path(folder) if folder is not None else weights_dir()
        self._session_factory = session_factory
        self._encoder = None
        self._decoder = None

    def _load(self) -> None:
        if self._encoder is not None:
            return
        if self._session_factory is not None:
            self._encoder, self._decoder = self._session_factory(
                self._folder / "encoder.onnx", self._folder / "decoder.onnx"
            )
            return
        if not weights_present(self._folder):
            raise SamError(
                "The click-tracking model is not on this computer yet."
            )
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover - environment guard
            raise EngineUnavailable(
                "ONNX Runtime is required for click tracking"
            ) from exc
        options = ort.SessionOptions()
        options.log_severity_level = 3  # keep the console clean
        try:
            self._encoder = ort.InferenceSession(
                str(self._folder / "encoder.onnx"),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self._decoder = ort.InferenceSession(
                str(self._folder / "decoder.onnx"),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:
            raise SamError(
                "The click-tracking model could not be loaded on "
                "this computer."
            ) from exc

    # ------------------------------------------------------------ frames

    @staticmethod
    def _prepare(frame_bgr: np.ndarray) -> np.ndarray:
        """BGR frame -> the encoder's input tensor: RGB stretched
        to 1024x1024, scaled to [0, 1], normalised as documented
        for this export."""
        import cv2

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(
            rgb, (_INPUT_SIZE, _INPUT_SIZE), interpolation=cv2.INTER_LINEAR
        )
        tensor = resized.astype(np.float32) / 255.0
        tensor = (tensor - _MEAN) / _STD
        return np.ascontiguousarray(tensor.transpose(2, 0, 1)[None])

    def segment(
        self, frame_bgr: np.ndarray, point_xy: tuple[float, float]
    ) -> np.ndarray:
        """Segment the object at ``point_xy`` (frame pixels) in one
        frame. Returns a uint8 0/1 mask at the frame's own size;
        an all-zero mask when the model finds nothing there."""
        return self.segment_points(frame_bgr, [point_xy])

    def segment_points(
        self,
        frame_bgr: np.ndarray,
        points: list[tuple[float, float]],
    ) -> np.ndarray:
        """Segment the object named by one or more positive points.

        Several points sampled inside the previously found mask
        name the object far more strongly than a single point can:
        with one point the model also offers the structures the
        object hangs from, and a chained single prompt can wander
        onto them."""
        self._load()
        height, width = frame_bgr.shape[:2]
        encoded = self._encoder.run(
            None, {"image": self._prepare(frame_bgr)}
        )
        feeds = {
            "image_embed": encoded[0],
            "high_res_0": encoded[1],
            "high_res_1": encoded[2],
        }
        return self.segment_encoded(feeds, points, width, height)

    def segment_encoded(
        self,
        feeds: dict,
        points: list[tuple[float, float]],
        width: int,
        height: int,
    ) -> np.ndarray:
        """Run the decoder for pre-computed encoder features (the
        split the tracking loop uses when it encodes once and the
        tests use to drive the decoder contract directly). The
        first point is the anchor for the mask choice below."""
        import cv2

        coords = np.array(
            [
                [
                    [
                        float(px) * _INPUT_SIZE / max(width, 1),
                        float(py) * _INPUT_SIZE / max(height, 1),
                    ]
                    for px, py in points
                ]
            ],
            dtype=np.float32,
        )
        outputs = self._decoder.run(
            None,
            {
                **feeds,
                "point_coords": coords,
                "point_labels": np.array(
                    [[1] * len(points)], dtype=np.int64
                ),
            },
        )
        logits = outputs[0][0]  # [4, 256, 256]
        scores = outputs[1][0]  # [4]
        masks = [
            (
                cv2.resize(
                    logits[channel],
                    (width, height),
                    interpolation=cv2.INTER_LINEAR,
                )
                > 0.0
            )
            for channel in range(logits.shape[0])
        ]
        # Mask choice: the model's candidates are part/whole
        # alternatives (the object alone, the object on the
        # structure it hangs from, the whole background), and its
        # predicted-quality scores do not separate them reliably
        # -- on the proving clip the score rule picks the hanging
        # assembly, whose centre sits on the structure, and the
        # track is lost. The teacher clicked ONE object, so the
        # rule here is: among the candidates that contain the
        # anchor point, take the tightest. If none contains it
        # (not expected -- the model is prompted there), fall back
        # to the best predicted quality among the alternatives.
        anchor = points[0]
        click_x = min(max(int(round(anchor[0])), 0), width - 1)
        click_y = min(max(int(round(anchor[1])), 0), height - 1)
        containing = [
            (int(mask.sum()), channel)
            for channel, mask in enumerate(masks)
            if mask.any() and mask[click_y, click_x]
        ]
        if containing:
            index = min(containing)[1]
        elif logits.shape[0] >= 4:
            index = 1 + int(np.argmax(scores[1:4]))
        else:
            index = 0
        return masks[index].astype(np.uint8)


# -------------------------------------------------------------- tracking


def _mask_prompt_points(mask: np.ndarray) -> list[tuple[float, float]]:
    """Sample the next prompt points from a found mask: its centre
    (the anchor) plus the inset corners of its bounding box that
    fall inside the mask. A spread of points inside the object
    names it far more strongly than the centre alone, which is
    what keeps a chained prompt from wandering onto whatever the
    object is attached to."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return []
    cx, cy = float(xs.mean()), float(ys.mean())
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(ys.min()), float(ys.max())
    dx, dy = (x1 - x0) * 0.25, (y1 - y0) * 0.25
    candidates = [
        (cx, cy),
        (x0 + dx, y0 + dy),
        (x1 - dx, y0 + dy),
        (x0 + dx, y1 - dy),
        (x1 - dx, y1 - dy),
    ]
    points: list[tuple[float, float]] = []
    for px, py in candidates:
        ix, iy = int(round(px)), int(round(py))
        if (
            0 <= iy < mask.shape[0]
            and 0 <= ix < mask.shape[1]
            and mask[iy, ix]
        ):
            points.append((float(px), float(py)))
    return points or [(cx, cy)]


def track_with_click(
    path: str | Path,
    point_xy: tuple[float, float],
    stride: int = 1,
    folder: str | Path | None = None,
    segmenter: SamSegmenter | None = None,
    progress: ProgressFn | None = None,
    min_pixels: int = 20,
) -> TrackResult:
    """Track the clicked object through a video.

    Same contract as the colour tracker: frames where the object
    is not found become gaps, not failures. The first examined
    frame is prompted with the teacher's click; every later frame
    is prompted with points sampled inside the previous found
    mask (or the click again, until the object has been found
    once).
    """
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - environment guard
        raise EngineUnavailable(
            "OpenCV (opencv-python-headless) is required for tracking"
        ) from exc
    info = probe_video(path)
    worker = segmenter or SamSegmenter(folder)
    total_hint = info.frame_count or 0
    times, xs, ys = [], [], []
    gaps: list[tuple[int, int]] = []
    gap_start: int | None = None
    frames_total = 0
    prompt_points = [(float(point_xy[0]), float(point_xy[1]))]
    segment_points = getattr(worker, "segment_points", None)
    last_index = 0
    for index, t, frame in iter_frames(path, stride=stride):
        last_index = index
        frames_total += 1
        try:
            if segment_points is not None:
                mask = segment_points(frame, prompt_points)
            else:
                mask = worker.segment(frame, prompt_points[0])
        except SamError:
            raise
        except Exception as exc:
            raise SamError(
                "The click-tracking model stopped on this video."
            ) from exc
        moments = cv2.moments(mask)
        if moments["m00"] < min_pixels:
            if gap_start is None:
                gap_start = index
        else:
            if gap_start is not None:
                gaps.append((gap_start, index - stride))
                gap_start = None
            cx = moments["m10"] / moments["m00"]
            cy = moments["m01"] / moments["m00"]
            xs.append(cx)
            ys.append(cy)
            times.append(t)
            prompt_points = _mask_prompt_points(mask) or prompt_points
        if progress is not None:
            examined = index + 1
            fraction = (
                min(1.0, examined / total_hint) if total_hint else 0.0
            )
            progress(
                fraction,
                f"CLICK TRACKING — {len(times)} FRAMES FOUND SO FAR",
            )
    if gap_start is not None:
        gaps.append((gap_start, last_index))
    return TrackResult(
        times=np.array(times),
        xs=np.array(xs),
        ys=np.array(ys),
        fps=info.fps,
        frames_total=frames_total,
        frames_tracked=len(times),
        gaps=gaps,
    )
