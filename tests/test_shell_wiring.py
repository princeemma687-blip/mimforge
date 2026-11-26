"""Shell wiring (install-test gap, 2026-11-26): the click-path Prince
found missing on the real laptop -- create a project from a template,
author it, run verification, build the lesson, play it back -- plus
the Safety panel's latching E-stop wired to the real kernel, and the
Design panel's machine + BOM readouts. All driven through the real
widgets, offscreen."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mimforge.projects import list_projects, open_project  # noqa: E402
from mimforge.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _create_via_clicks(window: MainWindow, title: str = "My first lesson"):
    panel = window.projects_panel
    assert panel.template_combo.count() >= 1
    panel.title_edit.setText(title)
    panel.create_button.click()
    return window.current_project


def _approve_all_steps(window: MainWindow) -> None:
    panel = window.author_panel
    draft = panel.current_draft()
    assert draft is not None
    for row in range(len(draft.steps)):
        panel.step_list.setCurrentRow(row)
        panel.approve_button.click()
    assert panel.current_draft().approved_count == len(draft.steps)


# ------------------------------------------------------------- safety


def test_safety_panel_estop_latches_and_reset_rearms(app, tmp_path):
    """Item 0: the E-stop must latch the real kernel stop, show it,
    and re-arm only through the deliberate reset. This test fails on
    the pre-wiring build, where the buttons were connected to
    nothing and the label was a fixed string."""
    window = MainWindow(projects_dir=tmp_path / "projects")
    panel = window.safety_panel
    assert not panel.kernel.stopped
    assert "ARMED" in panel.state_label.text()
    assert not panel.reset_button.isEnabled()

    panel.estop_button.click()
    assert panel.kernel.stopped
    assert "STOPPED" in panel.state_label.text()
    assert "LATCHED" in panel.state_label.text()
    assert panel.kernel.audit_log()[-1].outcome.value == "stopped"
    assert panel.reset_button.isEnabled()

    panel.reset_button.click()
    assert not panel.kernel.stopped
    assert "ARMED" in panel.state_label.text()
    assert "reset" in panel.kernel.audit_log()[-1].detail


# ----------------------------------------------------------- projects


def test_create_project_loads_draft_into_author(app, tmp_path):
    store = tmp_path / "projects"
    window = MainWindow(projects_dir=store)
    project = _create_via_clicks(window)
    assert project is not None
    assert window.current_section() == "Author"
    draft = window.author_panel.current_draft()
    assert draft is not None
    assert len(draft.steps) == 9
    assert draft.template_id == window.current_template.id
    # Stored on disk, self-contained: template + draft records.
    assert list_projects(store) == [project.project_id]
    reopened = open_project(store, project.project_id)
    assert reopened.get_record("template", "current") is not None
    assert reopened.get_record("draft", "current") is not None


def test_project_reopens_in_a_fresh_window(app, tmp_path):
    store = tmp_path / "projects"
    first = MainWindow(projects_dir=store)
    project = _create_via_clicks(first, "Reopen me")
    second = MainWindow(projects_dir=store)
    panel = second.projects_panel
    assert panel.project_list.count() == 1
    panel.project_list.setCurrentRow(0)
    panel.open_button.click()
    assert second.current_project is not None
    assert second.current_project.project_id == project.project_id
    draft = second.author_panel.current_draft()
    assert draft is not None and len(draft.steps) == 9


# ------------------------------------------------------------- design


def test_design_panel_shows_machine_and_bom_totals(app, tmp_path):
    window = MainWindow(projects_dir=tmp_path / "projects")
    _create_via_clicks(window)
    text = window.design_panel.readout.toPlainText()
    assert "HEIGHT" in text and "1100" in text
    assert "SUSPENSION RANGE" in text
    assert "PROTOTYPE" in text and "69,500" in text
    assert "PROFESSIONAL" in text and "159,000" in text
    assert "INDUSTRIAL" in text and "359,500" in text
    assert "My first lesson" in window.design_panel.project_label.text()


# ------------------------------------------------- simulate + lesson


def test_click_path_simulate_then_build_lesson(app, tmp_path):
    """The full path: create -> approve every step -> RUN
    VERIFICATION (recovered constant on display) -> BUILD LESSON ->
    the lesson is loaded in Playback."""
    window = MainWindow(projects_dir=tmp_path / "projects")
    _create_via_clicks(window)
    _approve_all_steps(window)

    window.nav.setCurrentRow(3)  # Simulate
    assert window.current_section() == "Simulate"
    window.simulate_panel.run_button.click()
    outcome = window.last_verification
    assert outcome is not None
    assert outcome.sim_fit["recovered_value"] == pytest.approx(9.796, abs=0.05)
    results = window.simulate_panel.results.toPlainText()
    assert "9.796" in results
    assert "4.030" in results
    assert "WITHIN TOLERANCE" in results

    window.author_panel.build_lesson_button.click()
    lesson = window.playback_panel.lesson
    assert lesson is not None
    assert lesson.step_count == 9
    assert window.current_section() == "Playback"
    assert lesson.steps[0].narration  # approved draft wording carried in
    recovered = float(lesson.outcome_summary["outcome_result"].split()[-1])
    assert recovered == pytest.approx(9.796, abs=0.05)
    assert lesson.graph.slope == pytest.approx(4.02, abs=0.05)
    assert len(lesson.table.rows) == 5
    assert len(lesson.replay.points) == 600


def test_build_lesson_blocked_until_every_step_approved(app, tmp_path):
    window = MainWindow(projects_dir=tmp_path / "projects")
    _create_via_clicks(window)
    window.author_panel.build_lesson_button.click()
    assert window.playback_panel.lesson is None
    assert "APPROVE" in window.author_panel.status_label.text()
