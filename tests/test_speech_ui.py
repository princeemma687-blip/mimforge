"""Stage 2 -- teacher voice in the shell: attach / record-state /
remove in the Author panel, draft persistence of the recording,
and the end-to-end lesson build that carries the teacher's voice
into the lesson (labelled) while the app voice reads the rest.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from mimforge import speech  # noqa: E402
from mimforge.speech import AI_VOICE_LABEL, TEACHER_VOICE_LABEL, StepAudio  # noqa: E402
from mimforge.structuring import AuthoringDraft, DraftStep  # noqa: E402
from mimforge.templates import load_template  # noqa: E402
from mimforge.ui.main_window import MainWindow  # noqa: E402
from mimforge.verification import VerificationOutcome  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _tiny_wav(seconds: float = 0.5, rate: int = 22050) -> bytes:
    import numpy as np

    t = np.linspace(0, seconds, int(rate * seconds))
    samples = (np.sin(2 * 3.14159 * 330 * t) * 0.3).astype("float32")
    return speech._samples_to_wav(samples, rate)


def _draft(orders=(1, 2)) -> AuthoringDraft:
    return AuthoringDraft(
        template_id="t",
        practical_title="T",
        steps=[
            DraftStep(
                step_id=f"s{order}",
                order=order,
                title=f"Step {order}",
                draft_text=f"Words for step {order}.",
                status="approved",
            )
            for order in orders
        ],
    )


def test_draft_step_voice_round_trip():
    step = DraftStep(
        step_id="s1", order=1, title="S", draft_text="Words."
    )
    assert step.voice_audio is None
    step.voice_audio = StepAudio.teacher(_tiny_wav()).to_dict()
    clone = DraftStep.from_dict(step.to_dict())
    assert clone.voice_audio == step.voice_audio
    assert clone.voice_audio["label"] == TEACHER_VOICE_LABEL


def test_author_panel_voice_label_states(app):
    from mimforge.ui.authoring import AuthoringPanel

    panel = AuthoringPanel()
    draft = _draft()
    panel.load_draft(draft)
    assert "AI VOICE WILL READ THIS STEP" in panel.voice_label.text()
    draft.steps[0].voice_audio = StepAudio.teacher(_tiny_wav(0.9)).to_dict()
    panel.refresh_voice_label()
    assert "TEACHER VOICE" in panel.voice_label.text()
    assert "0.9" in panel.voice_label.text()
    panel.set_recording(True)
    assert "STOP RECORDING" in panel.voice_record_button.text()
    panel.set_recording(False)
    assert "RECORD MY VOICE" in panel.voice_record_button.text()
    panel.close()


def test_attach_and_remove_teacher_voice(app, tmp_path, monkeypatch):
    window = MainWindow(projects_dir=tmp_path / "projects")
    draft = _draft()
    window.author_panel.load_draft(draft)
    recording = tmp_path / "my-voice.wav"
    recording.write_bytes(_tiny_wav(0.6))
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(recording), "")),
    )
    window.attach_teacher_voice()
    step = draft.steps[0]
    assert step.voice_audio is not None
    assert step.voice_audio["source"] == "teacher"
    assert step.voice_audio["label"] == TEACHER_VOICE_LABEL
    assert "TEACHER VOICE ATTACHED" in window.author_panel.status_label.text()
    window.remove_teacher_voice()
    assert step.voice_audio is None
    window.close()


class _FakeEngine:
    id = "fake:test"

    def synthesize(self, text: str):
        wav = _tiny_wav(0.5)
        return wav, speech.wav_duration_s(wav)


def test_build_lesson_carries_teacher_and_ai_voices(app, tmp_path, monkeypatch):
    window = MainWindow(projects_dir=tmp_path / "projects")
    template = load_template()
    window.current_template = template
    draft = _draft(orders=(1, 2))
    draft.steps[0].voice_audio = StepAudio.teacher(_tiny_wav(0.8)).to_dict()
    window.author_panel.load_draft(draft)
    window.last_verification = VerificationOutcome(
        template_id=template.id,
        practical_id=template.practical.id,
        x_key="length_m",
        y_key="period_sq_s2",
        band_percent=5.0,
        expected_value=9.81,
    )
    monkeypatch.setattr(speech, "default_engine", lambda: _FakeEngine())
    monkeypatch.setattr(
        speech, "default_cache_dir", lambda: tmp_path / "cache"
    )
    lesson = window.build_current_lesson()
    assert lesson is not None
    by_order = {step.order: step for step in lesson.steps}
    assert by_order[1].audio is not None
    assert by_order[1].audio.source == "teacher"
    assert by_order[1].audio.label == TEACHER_VOICE_LABEL
    assert by_order[2].audio is not None
    assert by_order[2].audio.source == "ai"
    assert by_order[2].audio.label == AI_VOICE_LABEL
    message = window.statusBar().currentMessage()
    assert "TEACHER VOICE ON 1 STEP(S)" in message
    assert "AI VOICE" in message
    window.close()
