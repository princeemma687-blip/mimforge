"""Phase 1, UI shell: the window builds offscreen and carries the
architectural design tokens (dark charcoal, one electric accent, mono
type, drafting grid, mission-control panels)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mimforge.ui.main_window import ACCENT, BG, MainWindow, SECTIONS  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


def test_window_builds_with_all_sections(app):
    window = MainWindow()
    assert "MIMFORGE" in window.windowTitle()
    assert window.nav.count() == len(SECTIONS) == 6
    assert window.stack.count() == 6
    assert window.current_section() == "Projects"
    window.nav.setCurrentRow(4)
    assert window.current_section() == "Safety"
    assert window.safety_panel.estop_button.isEnabled()
    window.nav.setCurrentRow(5)
    assert window.current_section() == "Playback"
    assert window.playback_panel.play_button.isEnabled()


def test_design_tokens_are_architectural_not_default(app):
    assert BG == "#17191D"  # dark charcoal
    assert ACCENT == "#00E5FF"  # the one electric accent
    assert ACCENT != BG
    window = MainWindow()
    stylesheet = window.styleSheet()
    assert ACCENT in stylesheet  # accent actually applied to the live window
    assert BG in stylesheet
