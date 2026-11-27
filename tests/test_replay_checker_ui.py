"""Trajectory replay + Muse double-checker in the shell.

Driven offscreen through the real widgets. The demonstration is
placed on the project as a record directly -- the record is the
seam the replay consumes (the import path that produces it has
its own tests). The checker is substituted at the window's
documented service attribute with a fake client, the seam the
shell offers; the client and service contracts have their own
tests.
"""

from __future__ import annotations

import io
import json
import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mimforge.checker import CheckerClient, CheckerService  # noqa: E402
from mimforge.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _window(tmp_path) -> MainWindow:
    window = MainWindow(projects_dir=tmp_path / "projects")
    panel = window.projects_panel
    panel.template_combo.setCurrentIndex(
        panel.template_combo.findData("pendulum")
    )
    panel.title_edit.setText("Replay Class")
    panel.create_button.click()
    assert window.current_project is not None
    return window


def _arc_track(seconds=4.0, n=41):
    times, xs, ys = [], [], []
    for i in range(n):
        angle = math.pi * i / (n - 1)
        times.append(round(seconds * i / (n - 1), 3))
        xs.append(round(320.0 + 150.0 * math.cos(angle), 1))
        ys.append(round(240.0 - 150.0 * math.sin(angle), 1))
    return {
        "fps": 25.0,
        "frames_examined": n,
        "frames_tracked": n,
        "coverage": 1.0,
        "gaps": [],
        "times_s": times,
        "xs_px": xs,
        "ys_px": ys,
    }


def _give_demonstration(window: MainWindow) -> None:
    window.current_project.put_record(
        "demonstration",
        "current",
        {
            "source_name": "demo.mp4",
            "tracker": "colour",
            "width": 640,
            "height": 480,
            "track": _arc_track(),
        },
    )
    window.current_project.save()
    window._refresh_replay_button()


def _approve_all_steps(window: MainWindow) -> None:
    panel = window.author_panel
    draft = panel.current_draft()
    for row in range(len(draft.steps)):
        panel.step_list.setCurrentRow(row)
        panel.approve_button.click()
    assert panel.current_draft().approved_count == len(draft.steps)


# -------------------------------------------------------------- replay


def test_replay_button_disabled_without_a_demonstration(app, tmp_path):
    window = _window(tmp_path)
    assert not window.simulate_panel.replay_button.isEnabled()
    result = window.run_trajectory_replay()
    assert result is None
    text = window.simulate_panel.results.toPlainText()
    assert "NO RECORDED DEMONSTRATION" in text


def test_trajectory_replay_runs_and_reports_fidelity(app, tmp_path):
    window = _window(tmp_path)
    _give_demonstration(window)
    assert window.simulate_panel.replay_button.isEnabled()
    window.simulate_panel.replay_button.click()
    result = window.last_trajectory
    assert result is not None
    assert result.feasible_percent == 100.0
    text = window.simulate_panel.results.toPlainText()
    assert "TRAJECTORY REPLAY" in text
    assert "PATH AND TIMING EXACT" in text
    assert len(window.simulate_panel.trajectory_view._points) == 41
    # The result is stored on the project for the lesson builder.
    stored = window.current_project.get_record("trajectory", "current")
    assert stored is not None
    assert stored["total_points"] == 41


def test_lesson_replay_follows_the_demonstration(app, tmp_path):
    window = _window(tmp_path)
    _give_demonstration(window)
    _approve_all_steps(window)
    window.simulate_panel.run_button.click()
    assert window.last_verification is not None
    window.author_panel.build_lesson_button.click()
    lesson = window.playback_panel.lesson
    assert lesson is not None
    assert "RECORDED DEMONSTRATION" in lesson.replay.label
    assert "PATH AND TIMING EXACT" in lesson.replay.label


def test_lesson_without_demonstration_keeps_the_simulation_track(
    app, tmp_path
):
    window = _window(tmp_path)
    _approve_all_steps(window)
    window.simulate_panel.run_button.click()
    window.author_panel.build_lesson_button.click()
    lesson = window.playback_panel.lesson
    assert lesson is not None
    assert "RECORDED DEMONSTRATION" not in lesson.replay.label


# -------------------------------------------------------------- checker


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _fake_service(tmp_path, payload, name="state.json"):
    calls: list = []

    def opener(request, timeout=None):
        calls.append(request)
        return _Response(json.dumps(payload).encode("utf-8"))

    client = CheckerClient("https://worker.example", opener=opener)
    service = CheckerService(tmp_path / name, client=client)
    return service, calls


def test_checker_agree_is_noted_and_counted(app, tmp_path):
    window = _window(tmp_path)
    service, calls = _fake_service(tmp_path, {"verdict": "agree"})
    window.checker_service = service
    window._refresh_checker_ui()
    assert window.checker_button.text() == "MUSE CHECK: ON"
    window.simulate_panel.run_button.click()
    assert window.last_verification is not None  # local result stands
    assert len(calls) == 1
    record = window.current_project.get_record("checks", "current")
    assert record["entries"][0]["step"] == "verification"
    assert record["entries"][0]["verdict"] == "agree"
    assert "CHECKS TODAY: 1 OF 50" in window.checker_status_label.text()


def test_checker_flag_is_shown_and_stored(app, tmp_path):
    window = _window(tmp_path)
    service, _calls = _fake_service(
        tmp_path,
        {"verdict": "flag", "concerns": ["The fit rests on two points."]},
    )
    window.checker_service = service
    window._refresh_checker_ui()
    window.simulate_panel.run_button.click()
    assert window.last_verification is not None  # still the official result
    message = window.statusBar().currentMessage()
    assert "FLAGGED" in message
    assert "two points" in message
    record = window.current_project.get_record("checks", "current")
    assert record["entries"][0]["verdict"] == "flag"
    assert record["entries"][0]["concerns"] == [
        "The fit rests on two points."
    ]


def test_checker_off_makes_no_calls_and_changes_nothing(app, tmp_path):
    window = _window(tmp_path)
    service, calls = _fake_service(tmp_path, {"verdict": "agree"})
    service.set_enabled(False)
    window.checker_service = service
    window._refresh_checker_ui()
    assert window.checker_button.text() == "MUSE CHECK: OFF"
    window.simulate_panel.run_button.click()
    assert window.last_verification is not None
    assert calls == []
    assert window.current_project.get_record("checks", "current") is None


def test_checker_toggle_flips_and_persists(app, tmp_path):
    window = _window(tmp_path)
    service, _calls = _fake_service(tmp_path, {"verdict": "agree"})
    window.checker_service = service
    window._refresh_checker_ui()
    window.checker_button.click()
    assert not service.enabled
    assert window.checker_button.text() == "MUSE CHECK: OFF"
    window.checker_button.click()
    assert service.enabled
    assert window.checker_button.text() == "MUSE CHECK: ON"


def test_checker_not_set_up_by_default_and_steps_still_work(
    app, tmp_path, monkeypatch
):
    monkeypatch.delenv("MIMFORGE_WORKER_URL", raising=False)
    window = _window(tmp_path)
    assert not window.checker_service.configured
    assert window.checker_button.text() == "MUSE CHECK: NOT SET UP"
    window.simulate_panel.run_button.click()
    assert window.last_verification is not None
    assert window.current_project.get_record("checks", "current") is None
