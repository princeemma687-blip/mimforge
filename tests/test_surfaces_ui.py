"""Surfacing pass (2026-11-26): the seven features that existed only
as engine code get real click-paths, driven through the real widgets
offscreen -- the Deliver section (risk sign-off gate, checked code
generation, signed package export), the Design CAD exports, the
Author demonstration import (tracking + transcription -> draft), and
the Projects sync toggle.

Stubs, and only these: the OS file dialogs (they cannot open
offscreen -- the same seam the earlier audit tests use), the
transcription engine for the success path (the real engine is
covered by the Phase 2 tests; here a prepared transcript proves the
wiring), the code generator for the allow-list failure path (the
checker and the refusal stay real), and the sync backend at the
sync layer's own documented seam (an in-memory backend).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from mimforge import signing  # noqa: E402
from mimforge.design import read_step_dimensions  # noqa: E402
from mimforge.narration import Transcript, TranscriptSegment  # noqa: E402
from mimforge.sync import MemoryBackend  # noqa: E402
from mimforge.ui.main_window import SECTIONS, MainWindow  # noqa: E402

VIDEOS = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "pendulum_proof"
    / "output"
    / "videos"
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path, **kwargs) -> MainWindow:
    return MainWindow(projects_dir=tmp_path / "projects", **kwargs)


def _create_via_clicks(window: MainWindow, title: str = "Pendulum Class"):
    panel = window.projects_panel
    panel.title_edit.setText(title)
    panel.create_button.click()
    assert window.current_project is not None
    return window.current_project


def _goto(window: MainWindow, section: str) -> None:
    window.nav.setCurrentRow(SECTIONS.index(section))


def _save_dialog(monkeypatch, target: Path) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "")),
    )


def _open_dialog(monkeypatch, target: Path) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(target), "")),
    )


# ---------------------------------------------------------------- deliver


def test_deliver_no_project_states_are_plain(app, tmp_path):
    window = _window(tmp_path)
    panel = window.deliver_panel
    panel.sign_button.click()
    assert "OPEN A PROJECT FIRST" in panel.status_label.text()
    panel.export_button.click()
    assert "OPEN A PROJECT FIRST" in panel.status_label.text()
    panel.generate_button.click()
    assert "OPEN A PROJECT FIRST" in panel.status_label.text()


def test_deliver_export_refused_before_signoff(app, tmp_path, monkeypatch):
    window = _window(tmp_path)
    _create_via_clicks(window)
    _goto(window, "Deliver")
    panel = window.deliver_panel
    assert "NOT SIGNED" in panel.signoff_label.text()
    assert "HAZARDS" in panel.assessment_view.toPlainText()
    target = tmp_path / "pkg.tmachine"
    _save_dialog(monkeypatch, target)
    panel.export_button.click()
    assert "EXPORT REFUSED" in panel.status_label.text()
    assert "SIGN" in panel.status_label.text()
    assert not target.exists()


def test_deliver_sign_then_export_produces_a_verifiable_package(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    project = _create_via_clicks(window)
    _goto(window, "Deliver")
    panel = window.deliver_panel

    # A blank name cannot sign.
    panel.sign_button.click()
    assert "TYPE THE TEACHER'S NAME" in panel.status_label.text()

    panel.teacher_edit.setText("Mrs A. Teacher")
    panel.sign_button.click()
    assert "SIGNED BY Mrs A. Teacher" in panel.signoff_label.text()

    target = tmp_path / "lesson.tmachine"
    _save_dialog(monkeypatch, target)
    panel.export_button.click()
    assert "PACKAGE SAVED" in panel.status_label.text()
    assert target.is_file()
    public_pem = Path(str(target) + ".pubkey.pem").read_bytes()
    manifest = signing.verify_package(target, public_pem)
    for name in (
        "project.json",
        "template.json",
        "risk_assessment.json",
        "controller.py",
        "control_panel.py",
        "draft.json",
    ):
        assert name in manifest["files"]

    # The sign-off is stored on the project: reopen and it still holds.
    window.open_project(project.project_id)
    _goto(window, "Deliver")
    assert "SIGNED BY Mrs A. Teacher" in panel.signoff_label.text()


def test_deliver_generate_code_saves_checked_files(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    _create_via_clicks(window)
    _goto(window, "Deliver")
    panel = window.deliver_panel
    out_dir = tmp_path / "code"
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *a, **k: str(out_dir)),
    )
    panel.generate_button.click()
    assert "CODE SAVED" in panel.status_label.text()
    assert "PASSED" in panel.code_view.toPlainText()
    controller = (out_dir / "controller.py").read_text(encoding="utf-8")
    panel_source = (out_dir / "control_panel.py").read_text(
        encoding="utf-8"
    )
    from mimforge.allowlist import check_source

    assert check_source(controller, "controller").passed
    assert check_source(panel_source, "panel").passed


def test_deliver_generate_code_blocked_when_the_check_fails(
    app, tmp_path, monkeypatch
):
    """The generator is stubbed to emit code that addresses the
    operating system directly; the real allow-list checker must
    block it and nothing may be saved."""
    import mimforge.delivery as delivery_module

    monkeypatch.setattr(
        delivery_module,
        "generate_controller",
        lambda template, params=None: "import os\nos.system('x')\n",
    )
    window = _window(tmp_path)
    _create_via_clicks(window)
    _goto(window, "Deliver")
    panel = window.deliver_panel
    out_dir = tmp_path / "code"
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *a, **k: str(out_dir)),
    )
    panel.generate_button.click()
    assert "CODE BLOCKED" in panel.status_label.text()
    assert "FAILED" in panel.code_view.toPlainText()
    assert not (out_dir / "controller.py").exists()


# -------------------------------------------------------------------- CAD


def test_design_exports_step_and_stl(app, tmp_path, monkeypatch):
    window = _window(tmp_path)
    _create_via_clicks(window)
    _goto(window, "Design")
    panel = window.design_panel

    step_path = tmp_path / "machine.step"
    _save_dialog(monkeypatch, step_path)
    panel.export_step_button.click()
    assert "SAVED" in panel.status_label.text()
    assert step_path.is_file() and step_path.stat().st_size > 0
    measured = read_step_dimensions(step_path)
    assert measured.overall_span_mm == pytest.approx(600.0, abs=1.0)
    assert measured.overall_height_mm == pytest.approx(1140.0, abs=1.0)

    stl_path = tmp_path / "machine.stl"
    _save_dialog(monkeypatch, stl_path)
    panel.export_stl_button.click()
    assert "SAVED" in panel.status_label.text()
    assert stl_path.is_file() and stl_path.stat().st_size > 0


# ----------------------------------------------------------------- import


class _StubTranscriber:
    """A prepared transcript at the transcription seam: the wiring
    is what is under test here (the real speech engine has its own
    Phase 2 tests)."""

    def transcribe(self, audio_path):
        return Transcript(
            segments=[
                TranscriptSegment(
                    0.0,
                    4.0,
                    "Set up the stand, clamp the thread and measure "
                    "the length from the pivot to the centre.",
                ),
                TranscriptSegment(
                    4.0,
                    8.0,
                    "Displace it through a small angle and release "
                    "without a push, then time twenty oscillations.",
                ),
            ],
            language="en",
            engine="stub",
            model="stub",
        )


def test_import_non_video_file_is_refused_plainly(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    _create_via_clicks(window)
    draft_before = window.author_panel.current_draft()
    note = tmp_path / "notes.txt"
    note.write_text("not a video", encoding="utf-8")
    _open_dialog(monkeypatch, note)
    window.author_panel.import_button.click()
    status = window.author_panel.import_status_label.text()
    assert "NOT A READABLE VIDEO" in status
    assert window.author_panel.current_draft() is draft_before


def test_import_missing_file_is_refused_plainly(app, tmp_path, monkeypatch):
    window = _window(tmp_path)
    _create_via_clicks(window)
    _open_dialog(monkeypatch, tmp_path / "no-such-clip.mp4")
    window.author_panel.import_button.click()
    status = window.author_panel.import_status_label.text()
    assert "WAS NOT FOUND" in status


def test_import_silent_video_reports_no_speech(app, tmp_path, monkeypatch):
    """The reference clip has no audio track: the real extraction
    path must report plainly that no speech could be read, and the
    existing draft must survive untouched."""
    window = _window(tmp_path)
    _create_via_clicks(window)
    draft_before = window.author_panel.current_draft()
    _open_dialog(monkeypatch, VIDEOS / "demo_L090cm.mp4")
    window.author_panel.import_button.click()
    status = window.author_panel.import_status_label.text()
    assert "NO SPEECH COULD BE READ" in status
    assert "TRACKING" in status  # the tracking outcome rides along
    assert window.author_panel.current_draft() is draft_before


def _clip_with_audio(tmp_path) -> Path:
    """The reference clip with an audio track muxed in (silent tone):
    the import's success path needs a video whose audio can be
    extracted -- the reference clips are silent by design."""
    import subprocess

    target = tmp_path / "demo_with_audio.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-i", str(VIDEOS / "demo_L090cm.mp4"),
            "-f", "lavfi", "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest", "-c:v", "copy", "-c:a", "aac",
            str(target),
        ],
        check=True,
        timeout=120,
    )
    return target


def test_import_builds_a_draft_from_the_recording(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    project = _create_via_clicks(window)
    window.transcriber = _StubTranscriber()
    _open_dialog(monkeypatch, _clip_with_audio(tmp_path))
    window.author_panel.import_button.click()
    status = window.author_panel.import_status_label.text()
    assert "DEMONSTRATION IMPORTED" in status
    assert "FOUND IN" in status  # the tracked object was found
    draft = window.author_panel.current_draft()
    assert draft is not None
    assert draft.transcript_engine == "stub"
    assert len(draft.steps) == 9
    report = window.last_import_report
    assert report is not None
    assert report["coverage"] > 0.9
    # The imported draft is the project's stored draft now.
    window.open_project(project.project_id)
    reopened = window.author_panel.current_draft()
    assert reopened is not None
    assert reopened.transcript_engine == "stub"


def test_import_without_a_project_is_a_plain_status(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    _open_dialog(monkeypatch, VIDEOS / "demo_L090cm.mp4")
    window.author_panel.import_button.click()
    status = window.author_panel.import_status_label.text()
    assert "OPEN A PROJECT" in status


# ------------------------------------------------------------------- sync


def test_sync_toggle_without_settings_says_not_set_up(
    app, tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "MIMFORGE_ENV_FILE", str(tmp_path / "absent.env")
    )
    window = _window(tmp_path)
    panel = window.projects_panel
    panel.sync_button.click()
    assert not window.sync_on
    assert "NOT SET UP" in panel.sync_status_label.text()
    assert panel.sync_button.text() == "SYNC: OFF"


def _write_fake_env(tmp_path) -> Path:
    env_file = tmp_path / "sync.env"
    env_file.write_text(
        "FIREBASE_API_KEY=test-key\nFIREBASE_PROJECT_ID=demo-project\n",
        encoding="utf-8",
    )
    return env_file


def test_sync_toggle_sends_project_details_via_the_backend(
    app, tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "MIMFORGE_ENV_FILE", str(_write_fake_env(tmp_path))
    )
    backend = MemoryBackend()
    window = _window(
        tmp_path, sync_backend_factory=lambda cfg: backend
    )
    project = _create_via_clicks(window)
    panel = window.projects_panel
    panel.sync_button.click()
    assert window.sync_on
    assert panel.sync_button.text() == "SYNC: ON"
    assert "PROJECT DETAILS SENT" in panel.sync_status_label.text()
    sent = backend.store.get(f"projects/{project.project_id}")
    assert sent is not None
    assert sent["title"] == "Pendulum Class"
    panel.sync_button.click()
    assert not window.sync_on
    assert "SYNC: OFF" in panel.sync_status_label.text()


class _FailingBackend:
    def push(self, collection, doc_id, payload):
        raise RuntimeError("service unavailable")

    def pull(self, collection, doc_id):
        raise RuntimeError("service unavailable")


def test_sync_failure_is_a_plain_status_not_a_crash(
    app, tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "MIMFORGE_ENV_FILE", str(_write_fake_env(tmp_path))
    )
    window = _window(
        tmp_path, sync_backend_factory=lambda cfg: _FailingBackend()
    )
    _create_via_clicks(window)
    panel = window.projects_panel
    panel.sync_button.click()
    assert window.sync_on
    assert "LAST SEND FAILED" in panel.sync_status_label.text()
