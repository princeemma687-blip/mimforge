"""Click tracker in the shell (2026-11-26), driven offscreen.

The tracker choice, the click dialog's geometry, and the import
flow's refusal paths are the real widgets and the real window code.
Stubs, and only these: the SAM run itself at the window's documented
seam (the real model has its own proving test), the transcription
engine (a prepared transcript, as in the other import tests), the
weights download (made to fail in plain words), and the OS file
dialogs.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from mimforge import sam_tracker  # noqa: E402
from mimforge.narration import Transcript, TranscriptSegment  # noqa: E402
from mimforge.perception import TrackResult  # noqa: E402
from mimforge.ui.main_window import MainWindow  # noqa: E402
from mimforge.ui.sam_picker import SamPointDialog  # noqa: E402

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


class _StubTranscriber:
    def transcribe(self, audio_path):
        return Transcript(
            segments=[
                TranscriptSegment(
                    0.0,
                    4.0,
                    "Set up the stand and measure the length from "
                    "the pivot to the centre of the mass.",
                )
            ],
            language="en",
            engine="stub",
            model="stub",
        )


def _clip_with_audio(tmp_path) -> Path:
    """The generated demo clips are silent; the import reads speech,
    so mux a silent audio track in (the same move the other import
    tests make) -- the stub transcriber supplies the words."""
    import subprocess

    target = tmp_path / "clip_with_audio.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
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


def _window(tmp_path) -> MainWindow:
    window = MainWindow(projects_dir=tmp_path / "projects")
    panel = window.projects_panel
    panel.template_combo.setCurrentIndex(
        panel.template_combo.findData("pendulum")
    )
    panel.title_edit.setText("Click Class")
    panel.create_button.click()
    assert window.current_project is not None
    window.transcriber = _StubTranscriber()
    return window


def _fake_track() -> TrackResult:
    times = np.linspace(0.0, 4.0, 9)
    return TrackResult(
        times=times,
        xs=np.linspace(100.0, 140.0, 9),
        ys=np.full(9, 60.0),
        fps=25.0,
        frames_total=10,
        frames_tracked=9,
        gaps=[(3, 3)],
    )


# ------------------------------------------------------------- the dialog


def test_picker_maps_a_click_back_to_frame_pixels(app):
    frame = np.zeros((100, 200, 3), dtype=np.uint8)  # H=100, W=200
    dialog = SamPointDialog(frame)
    dialog.show()
    app.processEvents()
    view = dialog.view
    # The frame is drawn fitted and centred; its centre in the
    # view must map to the frame's centre pixel.
    rect = view._draw_rect()
    centre = QPoint(int(rect.center().x()), int(rect.center().y()))
    QTest.mouseClick(view, Qt.LeftButton, pos=centre)
    assert dialog.point is not None
    assert dialog.point[0] == pytest.approx(100.0, abs=3.0)
    assert dialog.point[1] == pytest.approx(50.0, abs=3.0)
    assert dialog.track_button.isEnabled()


def test_picker_click_outside_the_frame_is_ignored(app):
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    dialog = SamPointDialog(frame)
    dialog.show()
    app.processEvents()
    QTest.mouseClick(dialog.view, Qt.LeftButton, pos=QPoint(2, 2))
    assert dialog.point is None
    assert not dialog.track_button.isEnabled()


# ------------------------------------------------------------ import flow


def test_tracker_choice_defaults_to_colour(app, tmp_path):
    window = _window(tmp_path)
    assert window.author_panel.tracker_choice() == "colour"
    combo = window.author_panel.tracker_combo
    combo.setCurrentIndex(combo.findData("sam"))
    assert window.author_panel.tracker_choice() == "sam"


def test_sam_import_uses_the_clicked_point_and_drafts(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    seen = {}

    def fake_sam_run(path, point, progress):
        seen["point"] = point
        progress(1.0, "CLICK TRACKING — DONE")
        return _fake_track()

    draft = window.import_demonstration(
        _clip_with_audio(tmp_path),
        tracker="sam",
        sam_point=(120.0, 60.0),
        sam_tracker_fn=fake_sam_run,
    )
    assert draft is not None
    assert seen["point"] == (120.0, 60.0)
    status = window.author_panel.import_status_label.text()
    assert "CLICK MODEL" in status
    assert "90%" in status  # 9 of 10 frames, from the track itself
    assert window.last_import_report["tracker"] == "sam"
    record = window.current_project.get_record("demonstration", "current")
    assert record["tracker"] == "sam"
    assert record["track"]["coverage"] == pytest.approx(0.9)


def test_sam_import_cancelled_click_imports_nothing(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)

    class _CancelledDialog:
        Accepted = QDialog.Accepted

        def __init__(self, frame, parent=None):
            self.point = None

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(
        "mimforge.ui.sam_picker.SamPointDialog", _CancelledDialog
    )
    # Weights are "present" so the flow reaches the click dialog.
    monkeypatch.setattr(sam_tracker, "weights_present", lambda folder=None: True)
    monkeypatch.setattr(
        MainWindow, "_sam_model_dir", lambda self: tmp_path / "models"
    )
    draft_before = window.author_panel.current_draft()
    draft = window.import_demonstration(
        VIDEOS / "demo_L090cm.mp4", tracker="sam"
    )
    assert draft is None
    status = window.author_panel.import_status_label.text()
    assert "NO OBJECT WAS CLICKED" in status
    # The pre-existing template draft is untouched; nothing imported.
    assert window.author_panel.current_draft() == draft_before
    assert window.last_import_report is None


def test_sam_import_failed_model_download_is_plain(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    monkeypatch.setattr(
        MainWindow, "_sam_model_dir", lambda self: tmp_path / "models"
    )
    monkeypatch.setattr(
        sam_tracker, "weights_present", lambda folder=None: False
    )

    def dead_ensure(folder, progress=None):
        raise sam_tracker.SamError(
            "The click-tracking model could not be downloaded — "
            "check the network connection and try again."
        )

    monkeypatch.setattr(sam_tracker, "ensure_weights", dead_ensure)
    draft_before = window.author_panel.current_draft()
    draft = window.import_demonstration(
        VIDEOS / "demo_L090cm.mp4", tracker="sam", sam_point=(10.0, 10.0)
    )
    assert draft is None
    status = window.author_panel.import_status_label.text()
    assert "COULD NOT BE DOWNLOADED" in status
    assert "NOTHING WAS IMPORTED" in status
    assert window.author_panel.current_draft() == draft_before
    assert window.last_import_report is None
