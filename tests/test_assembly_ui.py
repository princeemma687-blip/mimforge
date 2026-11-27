"""Stage 3 UI: the BUILD IT player, the Design view switcher and
the production-document export, driven the way a teacher drives
them -- real button clicks on the real window, offscreen.

Pins:
- BUILD IT opens the assembly player on the current design at
  the Design panel's tier; the transport walks all nine steps to
  the coupled state, and every card prices against the tier;
- switching the Design tier re-prices the player's cards;
- the Design view switcher shows the generated wiring schematic
  and panel layout (fed from the host's generators);
- the production-document export obeys the Stage 0 gate order:
  unsigned -> refused with NO save dialog; signed -> the dialog
  opens and the document is written.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

from mimforge.ui.main_window import SECTIONS, MainWindow


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


def _window(tmp_path) -> MainWindow:
    return MainWindow(projects_dir=tmp_path / "projects")


def _create_via_clicks(window: MainWindow) -> None:
    panel = window.projects_panel
    panel.template_combo.setCurrentIndex(
        panel.template_combo.findData("pendulum")
    )
    panel.title_edit.setText("Coupling Test Bench")
    panel.create_button.click()
    assert window.current_project is not None


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


# ------------------------------------------------------------- the player


def test_build_it_walks_all_nine_steps_to_coupled(app, tmp_path):
    window = _window(tmp_path)
    _create_via_clicks(window)
    plan = window.show_assembly(narrate=False)
    assert window.stack.currentWidget() is window.assembly_panel
    player = window.assembly_panel
    assert len(plan.steps) == 9
    assert player.current_index == 0
    assert "STEP 01/09" in player.card_title.text()
    assert "₦69,500" in player.card.text()  # prototype build total
    # Walk the whole sequence with the transport's test driver.
    for expected in range(1, 9):
        player.advance()
        assert player.current_index == expected
    assert "COUPLED" in player.status_label.text()
    assert "STEP 09/09" in player.card_title.text()
    # Back returns to the Design section.
    player.back_button.click()
    assert window.stack.currentWidget() is window.design_panel


def test_tier_switch_reprices_the_player(app, tmp_path):
    window = _window(tmp_path)
    _create_via_clicks(window)
    combo = window.design_panel.tier_combo
    combo.setCurrentIndex(combo.findData("professional"))
    plan = window.show_assembly(narrate=False)
    assert plan.tier == "professional"
    assert plan.total_ngn == 159000
    assert "₦159,000" in window.assembly_panel.card.text()


def test_next_and_prev_buttons_move_one_step(app, tmp_path):
    window = _window(tmp_path)
    _create_via_clicks(window)
    window.show_assembly(narrate=False)
    player = window.assembly_panel
    player.next_button.click()
    assert player.current_index == 1
    player.prev_button.click()
    assert player.current_index == 0
    player.reset_button.click()
    assert player.current_index == 0


# ------------------------------------------------------- design view tabs


def test_design_view_switcher_shows_generated_drawings(app, tmp_path):
    window = _window(tmp_path)
    _create_via_clicks(window)
    panel = window.design_panel
    assert panel.current_view == "elevation"
    panel.view_buttons["wiring"].click()
    assert panel.current_view == "wiring"
    diagram = panel.wiring_view.diagram
    assert diagram is not None
    assert {node.role for node in diagram.nodes} >= {"controller", "estop"}
    panel.view_buttons["panel"].click()
    assert panel.current_view == "panel"
    layout = panel.panel_view.layout_data
    assert layout is not None
    assert any(c.kind == "estop" for c in layout.controls)
    panel.view_buttons["elevation"].click()
    assert panel.current_view == "elevation"


class _FakeEngine:
    """A stand-in voice: instant, so the button-path test does not
    render real narration (the speech layer itself is pinned by
    tests/test_speech.py and tests/test_assembly.py)."""

    id = "fake-engine"
    voice = "fake"

    def synthesize(self, text: str):
        import io
        import wave

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(b"\x40\x1f" * 2205)
        return buffer.getvalue(), 0.1


def test_build_it_button_opens_the_player(app, tmp_path, monkeypatch):
    from mimforge import speech

    monkeypatch.setattr(speech, "default_engine", lambda: _FakeEngine())
    window = _window(tmp_path)
    _create_via_clicks(window)
    window.design_panel.build_it_button.click()
    assert window.stack.currentWidget() is window.assembly_panel
    player = window.assembly_panel
    assert len(player.plan.steps) == 9
    # The narration attached through the button path too.
    assert player.plan.steps[0].audio is not None
    assert "AI VOICE" in player.voice_label.text()


# ------------------------------------------------- production document


def test_production_export_refused_before_any_dialog(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    _create_via_clicks(window)
    panel = window.deliver_panel
    recorder = _DialogRecorder(result=str(tmp_path / "production.html"))
    recorder.install(monkeypatch)
    panel.production_button.click()
    assert recorder.calls == [], (
        "the save dialog opened before the sign-off gate refused"
    )
    assert "EXPORT REFUSED" in panel.status_label.text()
    assert not (tmp_path / "production.html").exists()


def test_production_export_after_signing_writes_the_document(
    app, tmp_path, monkeypatch
):
    window = _window(tmp_path)
    _create_via_clicks(window)
    panel = window.deliver_panel
    panel.teacher_edit.setText("A Teacher")
    panel.sign_button.click()
    target = tmp_path / "production.html"
    recorder = _DialogRecorder(result=str(target))
    recorder.install(monkeypatch)
    panel.production_button.click()
    assert len(recorder.calls) == 1
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "PRODUCTION DOCUMENT" in text
    assert "HOW IT IS BUILT" in text
    assert "PRODUCTION DOCUMENT SAVED" in panel.status_label.text()
