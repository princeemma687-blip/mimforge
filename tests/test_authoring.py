"""Phase 2.4: authoring editor -- teacher approves/edits draft steps,
and the edited draft survives a save/reopen round trip.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mimforge.narration import manual_transcript  # noqa: E402
from mimforge.projects import create_project, open_project  # noqa: E402
from mimforge.structuring import AuthoringDraft, build_draft  # noqa: E402
from mimforge.templates import load_template  # noqa: E402
from mimforge.ui.authoring import AuthoringPanel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _draft():
    template = load_template("pendulum")
    entries = []
    t = 0.0
    for step in sorted(template.steps, key=lambda s: s.order):
        entries.append((t, t + 8.0, step.narration))
        t += 10.0
    return build_draft(template, manual_transcript(entries))


def test_panel_loads_draft_and_approves(app):
    panel = AuthoringPanel()
    draft = _draft()
    panel.load_draft(draft)
    assert panel.step_list.count() == 9
    assert "0/9 APPROVED" in panel.status_label.text()
    panel.step_list.setCurrentRow(0)
    assert "Set up the apparatus" in panel.step_title.text()
    panel.approve_button.click()
    assert draft.steps[0].status == "approved"
    assert "1/9 APPROVED" in panel.status_label.text()
    panel.reject_button.click()
    assert draft.steps[0].status == "rejected"
    assert "0/9 APPROVED" in panel.status_label.text()


def test_editing_approved_step_marks_it_edited(app):
    panel = AuthoringPanel()
    draft = _draft()
    panel.load_draft(draft)
    panel.step_list.setCurrentRow(1)
    panel.approve_button.click()
    assert draft.steps[1].status == "approved"
    panel.editor.setPlainText("Teacher's own wording for this step.")
    assert draft.steps[1].status == "edited"
    assert draft.steps[1].draft_text == "Teacher's own wording for this step."
    assert panel.current_draft() is draft


def test_draft_survives_project_save_reopen(app, tmp_path):
    draft = _draft()
    panel = AuthoringPanel()
    panel.load_draft(draft)
    panel.step_list.setCurrentRow(0)
    panel.approve_button.click()
    panel.step_list.setCurrentRow(2)
    panel.approve_button.click()
    panel.editor.setPlainText("Release gently, no push.")

    project = create_project(tmp_path, "demo-proj", "Demo project")
    project.put_record("authoring_draft", "main", draft.to_dict())
    project.save()

    reopened = open_project(tmp_path, "demo-proj")
    restored = AuthoringDraft.from_dict(
        reopened.get_record("authoring_draft", "main")
    )
    assert [s.step_id for s in restored.steps] == [
        s.step_id for s in draft.steps
    ]
    assert restored.steps[0].status == "approved"
    assert restored.steps[2].draft_text == "Release gently, no push."
    assert restored.steps[2].status == "edited"
