"""Full feature audit (2026-11-26): every remaining click-path and
edge path exercised through the real widgets, the way a user hits
them -- empty states, rejection and editing in Author, a tampered
project refused in plain words, the bounded auto-adjust (clean and
seeded-error), playback driven to the end, and the HTML export
(written, cancelled, and refused with no lesson).

Nothing here reaches into panel internals beyond reading what the
user would see; the only stub is the OS save dialog, which cannot
open offscreen.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from mimforge.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path) -> MainWindow:
    return MainWindow(projects_dir=tmp_path / "projects")


def _create_via_clicks(win: MainWindow, title: str = "Pendulum Class") -> None:
    panel = win.projects_panel
    panel.template_combo.setCurrentIndex(
        panel.template_combo.findData("pendulum")
    )
    panel.title_edit.setText(title)
    panel.create_button.click()


def _approve_all(win: MainWindow) -> None:
    panel = win.author_panel
    for row in range(panel.step_list.count()):
        panel.step_list.setCurrentRow(row)
        panel.approve_button.click()


def _journey_to_lesson(win: MainWindow) -> None:
    _create_via_clicks(win)
    _approve_all(win)
    win.author_panel.build_lesson_button.click()
    assert win.playback_panel.lesson is not None


# ------------------------------------------------------------ empty states


def test_open_with_nothing_selected_is_a_plain_status(app, tmp_path):
    win = _window(tmp_path)
    win.projects_panel.open_button.click()
    assert "CHOOSE A SAVED PROJECT" in win.projects_panel.status_label.text()
    assert win.current_project is None


def test_actions_without_a_project_fail_in_plain_words(app, tmp_path):
    win = _window(tmp_path)
    win.simulate_panel.run_button.click()
    assert "NO PROJECT OPEN" in win.simulate_panel.results.toPlainText()
    win.author_panel.build_lesson_button.click()
    assert "NO DRAFT" in win.author_panel.status_label.text()
    win.simulate_panel.adjust_button.click()
    assert "NO PROJECT OPEN" in win.simulate_panel.results.toPlainText()


def test_create_without_a_title_is_a_plain_status(app, tmp_path):
    win = _window(tmp_path)
    win.projects_panel.template_combo.setCurrentIndex(
        win.projects_panel.template_combo.findData("pendulum")
    )
    win.projects_panel.title_edit.setText("   ")
    win.projects_panel.create_button.click()
    assert "GIVE THE PROJECT A TITLE" in (
        win.projects_panel.status_label.text()
    )
    assert win.current_project is None


# ------------------------------------------------------------- author paths


def test_author_reject_and_edit_through_clicks(app, tmp_path):
    win = _window(tmp_path)
    _create_via_clicks(win)
    panel = win.author_panel
    draft = panel.current_draft()
    assert draft is not None and len(draft.steps) == 9

    panel.step_list.setCurrentRow(0)
    panel.reject_button.click()
    assert draft.steps[0].status == "rejected"
    assert "REJECTED" in panel.step_list.item(0).text()

    panel.step_list.setCurrentRow(1)
    panel.approve_button.click()
    assert draft.approved_count == 1

    # Editing approved wording withdraws the approval -- the teacher
    # must look again before this step can enter a lesson.
    panel.editor.setPlainText("Measure the length to the centre of the bob.")
    assert draft.steps[1].status == "edited"
    assert draft.approved_count == 0


# ------------------------------------------------------- tampered project


def test_tampered_project_is_refused_in_plain_words(app, tmp_path):
    win = _window(tmp_path)
    _create_via_clicks(win)
    project_id = win.current_project.project_id

    # Break the seal: the manifest no longer matches the contents.
    manifest_path = tmp_path / "projects" / project_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["content_hash"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    fresh = _window(tmp_path)
    fresh.projects_panel.refresh_projects()
    assert fresh.projects_panel.project_list.count() == 1
    fresh.projects_panel.project_list.setCurrentRow(0)
    fresh.projects_panel.open_button.click()
    status = fresh.projects_panel.status_label.text()
    assert "COULD NOT BE OPENED" in status
    assert "SEAL" in status
    assert fresh.current_project is None


# ------------------------------------------------------------- auto-adjust


def test_auto_adjust_on_a_clean_run_reports_within_tolerance(app, tmp_path):
    win = _window(tmp_path)
    _create_via_clicks(win)
    win.simulate_panel.run_button.click()
    win.simulate_panel.adjust_button.click()
    results = win.simulate_panel.results.toPlainText()
    assert "AUTO-ADJUST" in results
    assert "ADJUSTED — WITHIN TOLERANCE" in (
        win.simulate_panel.status_label.text()
    )
    assert win.current_length_scale() == pytest.approx(1.0)


def test_auto_adjust_fixes_a_seeded_length_error(app, tmp_path):
    win = _window(tmp_path)
    _create_via_clicks(win)
    # Seed a miscalibrated machine: lengths set 10% long.
    win.current_project.put_record(
        "calibration", "current", {"length_scale": 1.10}
    )
    win.current_project.save()

    fresh = _window(tmp_path)
    fresh.projects_panel.project_list.setCurrentRow(0)
    fresh.projects_panel.open_button.click()
    assert fresh.current_length_scale() == pytest.approx(1.10)

    fresh.simulate_panel.run_button.click()
    assert "OUTSIDE TOLERANCE" in fresh.simulate_panel.results.toPlainText()

    fresh.simulate_panel.adjust_button.click()
    assert "ADJUSTED — WITHIN TOLERANCE" in (
        fresh.simulate_panel.status_label.text()
    )
    # The corrected scale is stored, near the true 1.0, and the
    # re-run shown in the panel is back inside the band.
    assert fresh.current_length_scale() == pytest.approx(1.0, abs=0.02)
    assert "WITHIN TOLERANCE" in fresh.simulate_panel.results.toPlainText()


# ---------------------------------------------------------------- playback


def test_playback_controls_drive_the_lesson_to_the_end(app, tmp_path):
    win = _window(tmp_path)
    _journey_to_lesson(win)
    player = win.playback_panel

    player.play_button.click()
    assert player.is_playing
    player.pause_button.click()
    assert not player.is_playing
    assert "PAUSED" in player.status.text()
    player.play_button.click()
    for _ in range(12):
        player.advance()
        if "FINISHED" in player.status.text():
            break
    assert "FINISHED" in player.status.text()
    assert player.replay_view.progress == pytest.approx(1.0)

    player.stop_button.click()
    assert "STOPPED" in player.status.text()
    assert player.current_index == 0


def test_export_with_no_lesson_is_a_plain_status(app, tmp_path):
    win = _window(tmp_path)
    win.playback_panel.export_button.click()
    assert "NOTHING TO EXPORT" in win.playback_panel.status.text()


def test_export_writes_a_valid_html_file(app, tmp_path, monkeypatch):
    win = _window(tmp_path)
    _journey_to_lesson(win)
    target = tmp_path / "lesson.html"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "HTML files (*.html)")),
    )
    win.playback_panel.export_button.click()
    assert "LESSON SAVED" in win.playback_panel.status.text()
    html = target.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    for step in win.playback_panel.lesson.steps:
        assert step.title in html
    # One self-contained file: no external resources to fetch.
    assert "http://" not in html and "https://" not in html


def test_export_cancelled_is_a_plain_status(app, tmp_path, monkeypatch):
    win = _window(tmp_path)
    _journey_to_lesson(win)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )
    win.playback_panel.export_button.click()
    assert "EXPORT CANCELLED" in win.playback_panel.status.text()
