"""Motion layer (2026-11-26): the boot intro appears only with
motion on and is skippable; the rail toggle flips the mode; the
design elevation and fit graph render; and the full click-path
still lands on the same end states with motion forced off -- motion
is a layer, never a load-bearing wall.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mimforge.design import GantryParameters  # noqa: E402
from mimforge.ui.main_window import BootIntro, MainWindow  # noqa: E402
from mimforge.ui.motion import motion_enabled, set_motion_enabled  # noqa: E402
from mimforge.ui.panels import FitGraphView, GantryElevationView  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore_motion():
    yield
    set_motion_enabled(True)


def test_no_intro_when_motion_is_reduced(app, tmp_path):
    set_motion_enabled(False)
    win = MainWindow(projects_dir=tmp_path / "projects")
    win.show()
    app.processEvents()
    assert win.findChild(BootIntro) is None
    win.close()


def test_intro_appears_with_motion_on_and_a_click_skips_it(app, tmp_path):
    set_motion_enabled(True)
    win = MainWindow(projects_dir=tmp_path / "projects")
    win.show()
    app.processEvents()
    intro = win.findChild(BootIntro)
    assert intro is not None
    assert intro.isVisible()
    QTest.mouseClick(intro, Qt.LeftButton)
    app.processEvents()
    # Skipped: the overlay lifts at once (its deferred deletion
    # completes on the real event loop, not inside processEvents).
    assert intro.isHidden()
    win.close()


def test_motion_toggle_flips_mode_and_label(app, tmp_path):
    set_motion_enabled(True)
    win = MainWindow(projects_dir=tmp_path / "projects")
    assert "FULL" in win.motion_button.text()
    win.motion_button.click()
    assert motion_enabled() is False
    assert "REDUCED" in win.motion_button.text()
    win.motion_button.click()
    assert motion_enabled() is True
    assert "FULL" in win.motion_button.text()


def test_design_elevation_renders_from_parameters(app):
    view = GantryElevationView()
    view.resize(640, 260)
    view.set_params(GantryParameters())
    assert view.params.span_mm == 600
    assert view.params.height_mm == 1100
    pixmap = view.grab()
    assert not pixmap.isNull()
    assert pixmap.width() == 640


def test_fit_graph_renders_points_and_sweeps(app):
    view = FitGraphView()
    view.resize(520, 220)
    view.set_data(
        [(0.5, 2.02), (0.6, 2.42), (0.7, 2.82), (0.8, 3.22), (0.9, 3.63)],
        slope=4.03,
        intercept=0.0,
    )
    assert view.point_count == 5
    view.set_progress(0.5)
    assert view.progress == pytest.approx(0.5)
    assert not view.grab().isNull()


def test_click_path_end_states_with_motion_forced_off(app, tmp_path):
    """The shell-wiring journey, with animations disabled: every
    end state is identical to the motion-on path."""
    set_motion_enabled(False)
    win = MainWindow(projects_dir=tmp_path / "projects")
    panel = win.projects_panel
    panel.title_edit.setText("Pendulum Class")
    panel.create_button.click()
    assert win.current_section() == "Author"
    author = win.author_panel
    for row in range(author.step_list.count()):
        author.step_list.setCurrentRow(row)
        author.approve_button.click()
    win.simulate_panel.run_button.click()
    assert "9.796" in win.simulate_panel.results.toPlainText()
    author.build_lesson_button.click()
    assert win.playback_panel.lesson is not None
    assert win.current_section() == "Playback"
