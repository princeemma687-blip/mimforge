"""Stage 2 -- talking lessons (narration layer).

Covers the phonemizer (bundled lexicon, numbers, fallbacks), the
Piper engine against the staged bundled voice, the attach flow
(render-at-build, teacher override, labels, silent-safe), the
lesson audio round-trip, the HTML export's embedded audio +
labels, and the in-app player's voice label + silent-safe state
machine. Engine tests skip cleanly when the bundled voice has not
been staged in this checkout (packaging fetches it).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mimforge import resources, speech  # noqa: E402
from mimforge.playback import (  # noqa: E402
    LessonPackage,
    LessonStep,
    export_html_lesson,
)
from mimforge.speech import (  # noqa: E402
    AI_VOICE_LABEL,
    TEACHER_VOICE_LABEL,
    LexiconPhonemizer,
    StepAudio,
)

VOICE_DIR = resources.piper_voice_dir()
needs_voice = pytest.mark.skipif(
    VOICE_DIR is None, reason="bundled Piper voice not staged here"
)


def _tiny_wav(seconds: float = 0.5, rate: int = 22050) -> bytes:
    import numpy as np

    samples = (np.sin(np.linspace(0, 440 * 2 * 3.14159 * seconds, int(rate * seconds))) * 0.3)
    return speech._samples_to_wav(samples.astype("float32"), rate)


class _FakeEngine:
    """Deterministic stand-in engine: renders a short tone."""

    id = "fake:test"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str):
        self.calls.append(text)
        wav = _tiny_wav(0.5)
        return wav, speech.wav_duration_s(wav)


def _lesson(*narrations: str) -> LessonPackage:
    return LessonPackage(
        title="T",
        subject="S",
        template_id="t",
        steps=[
            LessonStep(order=i + 1, title=f"Step {i + 1}", narration=text)
            for i, text in enumerate(narrations)
        ],
    )


# ------------------------------------------------------------- phonemizer


@needs_voice
def test_phonemizer_covers_lesson_vocabulary():
    phonemizer = LexiconPhonemizer.from_voice_dir(VOICE_DIR)
    sentences = phonemizer.sentences(
        "Measure the length carefully. Time twenty oscillations, "
        "twice, and record the mean value."
    )
    assert len(sentences) == 2
    flat = [ph for sentence in sentences for ph in sentence]
    assert " " in flat  # word separators present
    assert len(flat) > 30  # real phoneme content, not stubs


@needs_voice
def test_phonemizer_verbalises_numbers_and_units():
    phonemizer = LexiconPhonemizer.from_voice_dir(VOICE_DIR)
    # 90.5 must become words (ninety point five): the phoneme count
    # for the numeric sentence must rival the spelled-out form.
    numeric = phonemizer.sentences("Set the length to 90.5 centimetres.")
    spelled = phonemizer.sentences("Set the length to ninety point five centimetres.")
    assert abs(len(numeric[0]) - len(spelled[0])) <= 2
    percent = phonemizer.sentences("Repeat until 50% is reached.")
    percent_words = phonemizer.sentences("Repeat until fifty percent is reached.")
    assert abs(len(percent[0]) - len(percent_words[0])) <= 2


@needs_voice
def test_phonemizer_unknown_words_fall_back_without_crashing():
    phonemizer = LexiconPhonemizer.from_voice_dir(VOICE_DIR)
    config_ids = set(
        __import__("json").loads(
            (VOICE_DIR / "model.onnx.json").read_text(encoding="utf-8")
        )["phoneme_id_map"]
    )
    sentences = phonemizer.sentences("The xylophone quivered near Blorpleton.")
    flat = [ph for sentence in sentences for ph in sentence]
    assert flat  # something was produced for every word position
    assert all(ph in config_ids for ph in flat)


@needs_voice
def test_fallback_tables_only_emit_voice_phonemes():
    """Every phoneme in the grapheme rules and the letter-name
    table must be a single phoneme the bundled voice knows --
    diphthongs and stress are sequences, never fused tokens."""
    config_ids = set(
        __import__("json").loads(
            (VOICE_DIR / "model.onnx.json").read_text(encoding="utf-8")
        )["phoneme_id_map"]
    )
    for _pattern, phonemes in speech._G2P_RULES:
        assert all(ph in config_ids for ph in phonemes), phonemes
    for letter, phonemes in speech._LETTER_PHONEMES.items():
        assert all(ph in config_ids for ph in phonemes), (letter, phonemes)


def test_number_words():
    assert speech._number_to_words("20") == "twenty"
    assert speech._number_to_words("90.5") == "ninety point five"
    assert speech._number_to_words("100") == "one hundred"
    assert speech._number_to_words("2026") == "two thousand twenty six"
    assert speech._ordinal_to_words("1") == "first"
    assert speech._ordinal_to_words("3") == "third"
    assert speech._ordinal_to_words("20") == "twentieth"


# ---------------------------------------------------------------- engines


@needs_voice
def test_piper_engine_synthesizes_non_silent_audio():
    engine = speech.piper_engine()
    assert engine is not None
    wav, duration = engine.synthesize(
        "The machine is ready. Watch the moving part."
    )
    assert duration > 0.8
    assert speech.wav_rms(wav) > 0.005
    assert engine.id == f"piper:{resources.PIPER_VOICE}"


def test_kokoro_engine_reports_unavailable_without_files(tmp_path):
    engine = speech.KokoroEngine(tmp_path / "absent")
    assert not engine.available()
    with pytest.raises(speech.SpeechUnavailable):
        engine.synthesize("Anything.")


# ------------------------------------------------------------- attach flow


def test_attach_renders_ai_voice_with_label(tmp_path):
    lesson = _lesson("First step words.", "Second step words.")
    engine = _FakeEngine()
    report = speech.attach_narration(
        lesson, engine=engine, cache_dir=tmp_path / "cache"
    )
    assert report.ai_steps == 2 and report.teacher_steps == 0
    for step in lesson.steps:
        assert step.audio is not None
        assert step.audio.source == "ai"
        assert step.audio.label == AI_VOICE_LABEL
        assert step.audio.engine == "fake:test"
        # Step timing grows to fit the voice.
        assert step.duration_s is not None and step.duration_s >= 1.3
    assert lesson.provenance["narration"]["ai_steps"] == 2


def test_attach_uses_cache_on_rebuild(tmp_path):
    lesson = _lesson("Cached step words.")
    engine = _FakeEngine()
    speech.attach_narration(lesson, engine=engine, cache_dir=tmp_path / "c")
    assert len(engine.calls) == 1
    lesson2 = _lesson("Cached step words.")
    speech.attach_narration(lesson2, engine=engine, cache_dir=tmp_path / "c")
    assert len(engine.calls) == 1  # second build served from cache
    assert lesson2.steps[0].audio is not None


def test_teacher_audio_overrides_ai(tmp_path):
    teacher = StepAudio.teacher(_tiny_wav(0.7)).to_dict()
    lesson = _lesson("App voice step.", "Teacher voice step.")
    engine = _FakeEngine()
    report = speech.attach_narration(
        lesson,
        teacher_audio={2: teacher},
        engine=engine,
        cache_dir=tmp_path / "cache",
    )
    assert report.teacher_steps == 1 and report.ai_steps == 1
    assert lesson.steps[0].audio.source == "ai"
    assert lesson.steps[1].audio.source == "teacher"
    assert lesson.steps[1].audio.label == TEACHER_VOICE_LABEL
    assert engine.calls == ["App voice step."]  # teacher step not synthesized


def test_attach_with_unavailable_engine_stays_silent_safe(tmp_path):
    lesson = _lesson("No voice available.")
    report = speech.attach_narration(
        lesson,
        engine=_UnavailableEngine(),
        cache_dir=tmp_path / "cache",
    )
    assert report.ai_steps == 0 and report.silent_steps == 1
    assert lesson.steps[0].audio is None
    # The lesson itself is untouched and still valid/playable.
    lesson.validate()


class _UnavailableEngine:
    id = "unavailable:test"

    def synthesize(self, text: str):
        raise speech.SpeechUnavailable("no voice here")


def test_step_audio_round_trip():
    audio = StepAudio.ai(_tiny_wav(0.4), "piper:test")
    clone = StepAudio.from_dict(audio.to_dict())
    assert clone == audio
    assert clone.label == AI_VOICE_LABEL
    step = LessonStep(order=1, title="S", narration="Words.", audio=audio)
    step2 = LessonStep.from_dict(step.to_dict())
    assert step2.audio == audio
    bare = LessonStep.from_dict(LessonStep(order=1, title="S").to_dict())
    assert bare.audio is None


# -------------------------------------------------------------- HTML export


def test_html_export_embeds_audio_and_labels(tmp_path):
    lesson = _lesson("Voiced step.")
    lesson.steps[0].audio = StepAudio.ai(_tiny_wav(0.4), "piper:test")
    out = export_html_lesson(lesson, tmp_path / "lesson.html")
    doc = out.read_text(encoding="utf-8")
    assert "data_b64" in doc  # audio travels inside the payload
    assert AI_VOICE_LABEL in doc  # the label is in the export
    assert 'id="step-audio"' in doc  # the player has an audio element
    assert "http://" not in doc and "https://" not in doc  # offline


def test_html_export_without_audio_has_no_voice_note(tmp_path):
    lesson = _lesson("Silent step.")
    out = export_html_lesson(lesson, tmp_path / "lesson.html")
    doc = out.read_text(encoding="utf-8")
    assert "VOICE:" not in doc


# ------------------------------------------------------------------- player


def test_player_shows_voice_label_and_plays_silently_safe():
    from PySide6.QtWidgets import QApplication

    from mimforge.ui.playback import LessonPlayer

    _app = QApplication.instance() or QApplication([])
    player = LessonPlayer()
    lesson = _lesson("One.", "Two.")
    lesson.steps[0].audio = StepAudio.ai(_tiny_wav(0.4), "piper:test")
    lesson.steps[1].audio = StepAudio.teacher(_tiny_wav(0.4))
    player.load_lesson(lesson)
    assert player.voice_label.text() == AI_VOICE_LABEL
    assert 0 in player._audio_files and 1 in player._audio_files
    player.play()
    assert player.is_playing
    player.advance()
    assert player.current_index == 1
    assert player.voice_label.text() == TEACHER_VOICE_LABEL
    player.pause()
    player.play()  # resume path must not raise
    player.stop()
    assert player.current_index == 0
    # A lesson with no audio at all still plays start to finish.
    bare = _lesson("Silent.")
    player.load_lesson(bare)
    assert player.voice_label.text() == ""
    assert player._audio_files == {}
    player.play()
    player.advance()
    assert "FINISHED" in player.status.text()
    player.close()
