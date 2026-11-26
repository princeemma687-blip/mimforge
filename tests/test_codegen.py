"""Phase 4.1: template codegen -- the generated controller runs the
approved steps through the safety kernel only, the generated control
panel builds from the template's control list, and both pass the
allow-list checker.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mimforge.allowlist import check_source  # noqa: E402
from mimforge.codegen import generate_control_panel, generate_controller  # noqa: E402
from mimforge.design import GantryParameters  # noqa: E402
from mimforge.safety import CommandOutcome, SafetyKernel  # noqa: E402
from mimforge.templates import load_template_data  # noqa: E402


@pytest.fixture(scope="module")
def template():
    return load_template_data("pendulum")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _design_params():
    params = GantryParameters()
    return {
        "span_mm": params.span_mm,
        "height_mm": params.height_mm,
        "section_mm": params.section_mm,
        "suspension_range_mm": list(params.suspension_range_mm),
    }


def test_generated_controller_passes_the_allow_list(template):
    source = generate_controller(template, _design_params())
    report = check_source(source, "controller")
    assert report.passed, report.violations
    assert "from mimforge.safety import MotionCommand" in source
    assert "import os" not in source
    assert "socket" not in source


def test_generated_controller_runs_only_through_the_kernel(template):
    source = generate_controller(template, _design_params())
    namespace: dict = {"__name__": "generated_controller"}
    exec(compile(source, "<generated-controller>", "exec"), namespace)
    kernel = SafetyKernel()
    namespace["run"](kernel)
    audit = kernel.audit_log()
    assert audit, "the controller issued no commands at all"
    assert all(
        entry.outcome in (CommandOutcome.ACCEPTED, CommandOutcome.CLAMPED)
        for entry in audit
    ), [(e.outcome, e.detail) for e in audit]
    assert not kernel.stopped
    # Every motion command the generator emitted is inside the cap.
    assert all("clamped" not in e.detail for e in audit)


def test_generated_controller_covers_every_step(template):
    source = generate_controller(template, _design_params())
    for step in template["steps"]:
        assert f"Step {step['order']}:" in source
    # Observation steps are marked, never executed as motion: the
    # template's six READ primitives each produce one such comment.
    assert source.count("Observation step") == 6


def test_tool_steps_are_comments_not_guessed_code():
    template = {
        "practical": {"title": "Synthetic tool practical"},
        "steps": [
            {
                "order": 1,
                "title": "Cut the sample",
                "motion_primitives": [{"type": "cut"}],
            },
            {
                "order": 2,
                "title": "Heat the sample",
                "motion_primitives": [{"type": "heat"}],
            },
        ],
    }
    source = generate_controller(template, {})
    assert "teacher-approved tool binding" in source
    assert source.count("kernel.execute") == 0  # no motion invented
    report = check_source(source, "controller")
    assert report.passed, report.violations
    namespace: dict = {"__name__": "generated_controller"}
    exec(compile(source, "<generated-controller>", "exec"), namespace)
    kernel = SafetyKernel()
    namespace["run"](kernel)
    assert kernel.audit_log() == []  # no motion invented for tool steps


def test_generated_panel_passes_the_allow_list(template):
    source = generate_control_panel(template)
    report = check_source(source, "panel")
    assert report.passed, report.violations


def test_generated_panel_builds_with_the_template_controls(app, template):
    source = generate_control_panel(template)
    namespace: dict = {"__name__": "generated_panel"}
    exec(compile(source, "<generated-panel>", "exec"), namespace)
    kernel = SafetyKernel()
    panel = namespace["ControlPanel"](kernel)
    # Length selector carries the template's five settings.
    assert panel.length_selector.count() == 5
    assert panel.length_selector.itemText(0) == "90.0"
    assert panel.length_selector.itemText(4) == "50.0"
    # Readings table has one column per observation column.
    assert panel.readings_table.columnCount() == 7
    # Release goes through the kernel; Stop latches it.
    panel.on_release()
    assert not kernel.stopped
    assert panel.status.text() == "Released."
    panel.on_stop()
    assert kernel.stopped
    assert panel.status.text() == "Stopped."
    panel.close()


def test_generated_panel_without_kernel_only_updates_status(app, template):
    """Without a kernel, Release/Stop must say so honestly -- the
    old text claimed "Released."/"Stopped." when nothing had
    happened at all (full spec audit, 2026-11-26)."""
    source = generate_control_panel(template)
    namespace: dict = {"__name__": "generated_panel"}
    exec(compile(source, "<generated-panel>", "exec"), namespace)
    panel = namespace["ControlPanel"]()
    panel.on_release()
    assert "nothing was released" in panel.status.text()
    panel.on_stop()
    assert "nothing was stopped" in panel.status.text()
    panel.close()


def test_generated_panel_always_has_a_stop_button(app):
    """A template whose control list forgets the stop entry still
    gets a Stop button: an operator surface without one is not
    finished."""
    template = {
        "practical": {"title": "No stop listed"},
        "control_panel": ["release", "readings table"],
        "observation_spec": {"columns": [], "rows": []},
    }
    source = generate_control_panel(template)
    namespace: dict = {"__name__": "generated_panel_nostop"}
    exec(compile(source, "<generated-panel>", "exec"), namespace)
    panel = namespace["ControlPanel"]()
    assert hasattr(panel, "stop_button")
    panel.close()
