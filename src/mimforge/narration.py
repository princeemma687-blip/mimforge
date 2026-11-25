"""Narration transcription (plan Phase 2.2).

The teacher's spoken narration is transcribed locally with
faster-whisper (Whisper ``base`` in lean mode, ``small`` in full mode --
see ``config.py``). Nothing leaves the machine: no cloud speech API is
used anywhere. When the engine or its model is unavailable, the failure
is explicit (``TranscriptionError`` / ``EngineUnavailable``) and the
caller falls back to a teacher-supplied transcript -- an SRT file or
manually entered timed lines -- so structuring (Phase 2.3) never blocks
on transcription.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .perception import EngineUnavailable


class TranscriptionError(Exception):
    """Transcription could not run or produced no usable output."""


@dataclass
class TranscriptSegment:
    start_s: float
    end_s: float
    text: str


@dataclass
class Transcript:
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str = ""
    engine: str = "none"  # "faster-whisper" | "srt" | "manual"
    model: str = ""

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    @property
    def duration_s(self) -> float:
        if not self.segments:
            return 0.0
        return max(s.end_s for s in self.segments)


def extract_audio(
    video_path: str | Path, out_path: str | Path, sample_rate: int = 16000
) -> Path:
    """Extract a video's audio track to mono WAV with ffmpeg.

    Raises TranscriptionError if the file has no audio track (a silent
    demonstration is valid -- the caller then uses a manual transcript).
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise EngineUnavailable("ffmpeg not found on PATH")
    video_path, out_path = Path(video_path), Path(out_path)
    if not video_path.is_file():
        raise TranscriptionError(f"video file not found: {video_path}")
    proc = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            str(out_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        raise TranscriptionError(
            f"no usable audio in {video_path} "
            f"(ffmpeg: {proc.stderr.strip() or 'empty output'})"
        )
    return out_path


class WhisperTranscriber:
    """Local transcription via faster-whisper. The model is loaded
    lazily, used once, and released -- lean mode loads one model at a
    time (see config.py: sequential_model_loading)."""

    def __init__(
        self,
        model: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model = model
        self.device = device
        self.compute_type = compute_type

    @staticmethod
    def available() -> bool:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    def transcribe(self, audio_path: str | Path) -> Transcript:
        if not self.available():
            raise EngineUnavailable(
                "faster-whisper is not installed; "
                "use a manual/SRT transcript instead"
            )
        from faster_whisper import WhisperModel

        audio_path = Path(audio_path)
        if not audio_path.is_file():
            raise TranscriptionError(f"audio file not found: {audio_path}")
        model = WhisperModel(
            self.model, device=self.device, compute_type=self.compute_type
        )
        try:
            segments, info = model.transcribe(str(audio_path), beam_size=5)
            return Transcript(
                segments=[
                    TranscriptSegment(
                        start_s=float(s.start),
                        end_s=float(s.end),
                        text=s.text.strip(),
                    )
                    for s in segments
                ],
                language=info.language or "",
                engine="faster-whisper",
                model=self.model,
            )
        finally:
            del model  # release the model immediately (lean mode)


# ------------------------------------------------- teacher-supplied input


_SRT_BLOCK = re.compile(
    r"(\d+)\s*\n"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*\n"
    r"(.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)


def _srt_time(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(text: str) -> Transcript:
    """Parse an SRT subtitle file into a Transcript."""
    segments = []
    for match in _SRT_BLOCK.finditer(text.strip()):
        start = _srt_time(*match.groups()[1:5])
        end = _srt_time(*match.groups()[5:9])
        body = " ".join(
            line.strip() for line in match.group(10).strip().splitlines()
        )
        if body:
            segments.append(
                TranscriptSegment(start_s=start, end_s=end, text=body)
            )
    if not segments:
        raise TranscriptionError("no subtitle blocks found in SRT input")
    return Transcript(segments=segments, engine="srt")


def manual_transcript(
    entries: list[tuple[float, float, str]],
) -> Transcript:
    """Build a Transcript from teacher-typed (start, end, text) lines."""
    segments = [
        TranscriptSegment(start_s=s, end_s=e, text=t.strip())
        for s, e, t in entries
        if t.strip() and e > s
    ]
    if not segments:
        raise TranscriptionError("manual transcript has no usable lines")
    return Transcript(segments=segments, engine="manual")
