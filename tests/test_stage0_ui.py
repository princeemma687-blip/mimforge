"""Stage 0 UI regressions (2026-11-26 walk findings #1, #2, #3).

#2 -- the Deliver export gate must refuse BEFORE any save dialog
opens (run #7 opened the dialog first; the refusal arrived only
after a file was picked, which read as the gate waving the user
through). The test drives the REAL export button click with
QFileDialog monkeypatched to RECORD every opening: unsigned =>
the dialog never opens and the status is the plain refusal;
signed => the dialog opens and the package is written.

#3 -- save dialogs default to the user's Documents folder, not
the install folder.

#1 -- the Design elevation's bob geometry: it swings on an arc
around its pivot (constant radius, easing profile), displaced
even at rest -- it never slides vertically along the line.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from mimforge.ui import panels as panels_module  # noqa: E402
from mimforge.ui.main_window import SECTIONS, MainWindow, _documents_dir  # noqa: E402
from mimforge.ui.panels import (  # noqa: E402
    SWING_REST_PHASE,
    GantryElevationView,
    swing_arc_points,
    swing_mass_position,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path) -> MainWindow:
    return MainWindow(projects_dir=tmp_path / "projects")


def _create_via_clicks(window: MainWindow):
    panel = window.projects_panel
    panel.title_edit.setText("Pendulum Class")
    panel.create_button.click()
    assert window.current_project is not None


def _goto(window: MainWindow, section: str) -> None:
    window.nav.setCurrentRow(SECTIONS.index(section))


class _DialogRecorder:
    """A QFileDialog stand-in that records every opening."""

    def __init__(self, result: str = "") -> None:
        self.calls: list[tuple] = []
        self.result = result

    def get_save(self, *args, **kwargs):
        self.calls.append(args)
        return (self.result, "")

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", staticmethod(self.get_save)
        )


# ---------------------------------------------------------- finding #2


def test_export_gate_refuses_before_any_dialog(app, tmp_path, monkeypatch):
    window = _window(tmp_path)
    _create_via_clicks(window)
    _goto(window, "Deliver")
    panel = window.deliver_panel
    assert "NOT SIGNED" in panel.signoff_label.text()
    recorder = _DialogRecorder(result=str(tmp_path / "pkg.tmachine"))
    recorder.install(monkeypatch)
    panel.export_button.click()
    assert recorder.calls == [], (
        "the save dialog opened before the sign-off gate refused -- "
        "that is walk finding #2"
    )
    assert "EXPORT REFUSED" in panel.status_label.text()
    assert "SIGN" in panel.status_label.text()
    assert not (tmp_path / "pkg.tmachine").exists()


def test_export_after_signing_opens_dialog_in_documents(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    _create_via_clicks(window)
    _goto(window, "Deliver")
    panel = window.deliver_panel
    panel.teacher_edit.setText("A Teacher")
    panel.sign_button.click()
    assert "SIGNED" in panel.signoff_label.text()
    target = tmp_path / "pkg.tmachine"
    recorder = _DialogRecorder(result=str(target))
    recorder.install(monkeypatch)
    panel.export_button.click()
    assert len(recorder.calls) == 1, "signed export must open the dialog"
    # Finding #3: the dialog's start path lives in Documents.
    start = str(recorder.calls[0][2])
    assert start.startswith(str(_documents_dir())), start
    assert target.exists()
    assert "PACKAGE SAVED" in panel.status_label.text()


# ---------------------------------------------------------- finding #3


def test_cad_export_dialog_defaults_to_documents(app, tmp_path, monkeypatch):
    window = _window(tmp_path)
    _create_via_clicks(window)
    _goto(window, "Deliver")
    panel = window.deliver_panel
    panel.teacher_edit.setText("A Teacher")
    panel.sign_button.click()
    recorder = _DialogRecorder(result=str(tmp_path / "machine.step"))
    recorder.install(monkeypatch)
    _goto(window, "Design")
    window.design_panel.export_step_button.click()
    assert len(recorder.calls) == 1
    start = str(recorder.calls[0][2])
    assert start.startswith(str(_documents_dir())), start


def test_html_export_dialog_defaults_to_documents(app, tmp_path, monkeypatch):
    from mimforge.playback import build_lesson

    window = _window(tmp_path)
    _create_via_clicks(window)
    outcome = window.run_verification()
    assert outcome is not None
    lesson = build_lesson(
        window.current_template,
        table=outcome.table,
        graph=outcome.graph,
        replay=outcome.replay,
        verification_run=outcome.run,
    )
    window.playback_panel.load_lesson(lesson)
    recorder = _DialogRecorder(result=str(tmp_path / "lesson.html"))
    recorder.install(monkeypatch)
    window.export_lesson_html()
    assert len(recorder.calls) == 1
    start = str(recorder.calls[0][2])
    assert start.startswith(str(_documents_dir())), start
    assert (tmp_path / "lesson.html").exists()


# ---------------------------------------------------------- finding #1


def test_swing_mass_stays_on_its_arc():
    pivot = (200.0, 50.0)
    length = 150.0
    for step in range(20):
        phase = step / 20
        x, y = swing_mass_position(*pivot, length, phase)
        radius = math.hypot(x - pivot[0], y - pivot[1])
        assert radius == pytest.approx(length), (
            "the bob must stay exactly one line-length from the "
            "pivot -- it swings, it does not slide"
        )
        assert y >= pivot[1]


def test_swing_mass_actually_swings_sideways():
    pivot = (200.0, 50.0)
    xs = [swing_mass_position(*pivot, 150.0, step / 40)[0] for step in range(40)]
    assert max(xs) - min(xs) > 60, "the bob's x must sweep a wide arc"
    # Centre at phase 0 / 0.5; extremes at 0.25 / 0.75 (the angle
    # follows max * sin(2*pi*phase)).
    assert swing_mass_position(*pivot, 150.0, 0.0)[0] == pytest.approx(pivot[0])
    assert swing_mass_position(*pivot, 150.0, 0.25)[0] > pivot[0] + 40
    assert swing_mass_position(*pivot, 150.0, 0.5)[0] == pytest.approx(pivot[0])
    assert swing_mass_position(*pivot, 150.0, 0.75)[0] < pivot[0] - 40


def test_swing_arc_is_symmetric_with_bottom_at_rest():
    points = swing_arc_points(200.0, 50.0, 150.0, steps=24)
    assert points[0][0] < 200.0 < points[-1][0]
    assert points[0][1] == pytest.approx(points[-1][1])
    middle = points[len(points) // 2]
    assert middle[0] == pytest.approx(200.0)
    assert middle[1] == pytest.approx(200.0)  # pivot_y + length


def test_elevation_rest_phase_is_displaced(app):
    """With motion reduced the still image must still read as a
    pendulum: the resting phase puts the bob off-centre."""
    view = GantryElevationView()
    assert view._phase == SWING_REST_PHASE
    x, _y = swing_mass_position(0.0, 0.0, 100.0, view._phase)
    assert x > 20, "resting bob must be visibly displaced"


def test_panels_module_exports_swing_helpers():
    assert hasattr(panels_module, "swing_mass_position")
    assert hasattr(panels_module, "swing_arc_points")
