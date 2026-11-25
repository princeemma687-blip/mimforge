"""Phase 2.2: narration transcription.

The real-engine test transcribes a 13.7 s public speech sample with
the lean ``tiny`` model (fast; the product default is ``base``) and
checks it returns timed English segments. The fallback paths -- SRT
import and teacher-typed lines -- are tested without any model, and a
silent video is shown to fail cleanly instead of crashing.
"""

from pathlib import Path

import pytest

from mimforge.narration import (
    TranscriptionError,
    WhisperTranscriber,
    extract_audio,
    manual_transcript,
    parse_srt,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VIDEOS = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "pendulum_proof"
    / "output"
    / "videos"
)

SAMPLE_SRT = """1
00:00:01,000 --> 00:00:04,500
Set up the stand and clamp the thread.

2
00:00:05,000 --> 00:00:09,000
Measure the length from the pivot to the centre.
"""


def test_parse_srt():
    transcript = parse_srt(SAMPLE_SRT)
    assert transcript.engine == "srt"
    assert len(transcript.segments) == 2
    assert transcript.segments[0].start_s == pytest.approx(1.0)
    assert transcript.segments[0].end_s == pytest.approx(4.5)
    assert "stand" in transcript.segments[0].text
    assert transcript.duration_s == pytest.approx(9.0)


def test_parse_srt_rejects_garbage():
    with pytest.raises(TranscriptionError):
        parse_srt("no subtitles here at all")


def test_manual_transcript():
    transcript = manual_transcript(
        [(0.0, 3.0, "First line."), (3.0, 6.0, "Second line.")]
    )
    assert transcript.engine == "manual"
    assert len(transcript.segments) == 2
    assert transcript.full_text == "First line. Second line."


def test_manual_transcript_rejects_empty():
    with pytest.raises(TranscriptionError):
        manual_transcript([(0.0, 1.0, "   ")])


def test_extract_audio_fails_cleanly_on_silent_video(tmp_path):
    out = tmp_path / "audio.wav"
    with pytest.raises(TranscriptionError):
        extract_audio(VIDEOS / "demo_L090cm.mp4", out)


SAMPLE_URL = (
    "https://cdn-media.huggingface.co/speech_samples/sample1.flac"
)


def _speech_sample(tmp_path: Path) -> Path:
    """The checked-in fixture, or a fresh download of the same public
    sample when the fixture is absent (the repo's snapshot push cannot
    carry binary files, so a clean checkout re-fetches it)."""
    local = FIXTURES / "speech_sample.flac"
    if local.is_file():
        return local
    import urllib.request

    downloaded = tmp_path / "speech_sample.flac"
    urllib.request.urlretrieve(SAMPLE_URL, downloaded)
    return downloaded


@pytest.mark.slow
def test_whisper_transcribes_real_speech(tmp_path):
    pytest.importorskip("faster_whisper", reason="faster-whisper not installed")
    transcriber = WhisperTranscriber(model="tiny")
    transcript = transcriber.transcribe(_speech_sample(tmp_path))
    assert transcript.engine == "faster-whisper"
    assert transcript.language == "en"
    assert len(transcript.segments) >= 1
    assert len(transcript.full_text) > 20
    assert transcript.duration_s == pytest.approx(13.7, abs=1.0)
    # Segments are timed and ordered.
    starts = [s.start_s for s in transcript.segments]
    assert starts == sorted(starts)
    assert all(s.end_s > s.start_s for s in transcript.segments)
