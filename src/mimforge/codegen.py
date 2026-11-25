"""Template code generation (plan Phase 4.1).

Two artefacts are generated from a PracticalTemplate + a machine
design, both as source text:

1. **Controller** -- a step-sequenced module that runs the approved
   steps in order. It may ONLY call the safety kernel's primitive API
   (``SafetyKernel.execute`` with ``MotionCommand``); it never
   addresses hardware, imports anything else, or invents a motion the
   template did not ask for. Tool steps the template cannot express
   as a kernel primitive (cutting, heating) are emitted as comments
   that require a teacher-approved binding -- never as guessed code.
2. **Control panel** -- a PySide6 operator panel built from the
   template's ``control_panel`` list, styled to the project's
   architectural/techy/premium rule (dark charcoal, one electric
   accent, mono type). Its Release and Stop buttons talk to the same
   safety kernel the controller uses.

Both artefacts are checked with ``mimforge.allowlist`` before they
are written anywhere; generation never executes the code it emits.
"""

from __future__ import annotations

from .models import MotionPrimitiveType

__all__ = ["generate_control_panel", "generate_controller"]

# Speeds (mm/s) the generator assigns per primitive. All sit far
# below the kernel's 250 mm/s cap; observation steps do not move.
_PRIMITIVE_SPEEDS: dict[MotionPrimitiveType, float] = {
    MotionPrimitiveType.REACH: 60.0,
    MotionPrimitiveType.GRASP: 20.0,
    MotionPrimitiveType.RELEASE: 0.0,
    MotionPrimitiveType.POUR: 30.0,
    MotionPrimitiveType.ROTATE: 30.0,
    MotionPrimitiveType.TRANSLATE: 60.0,
    MotionPrimitiveType.HOLD: 0.0,
    MotionPrimitiveType.OSCILLATE: 40.0,
    MotionPrimitiveType.READ: 0.0,
    MotionPrimitiveType.CUT: 0.0,
    MotionPrimitiveType.HEAT: 0.0,
    MotionPrimitiveType.MIX: 30.0,
}

# Primitives the generator turns into kernel motion commands.
_MOTION_PRIMITIVES = {
    MotionPrimitiveType.REACH,
    MotionPrimitiveType.GRASP,
    MotionPrimitiveType.RELEASE,
    MotionPrimitiveType.POUR,
    MotionPrimitiveType.ROTATE,
    MotionPrimitiveType.TRANSLATE,
    MotionPrimitiveType.HOLD,
    MotionPrimitiveType.OSCILLATE,
    MotionPrimitiveType.MIX,
}

# Primitives that are observations, not motions.
_OBSERVATION_PRIMITIVES = {MotionPrimitiveType.READ}

# Primitives that need a teacher-approved tool binding first.
_TOOL_PRIMITIVES = {MotionPrimitiveType.CUT, MotionPrimitiveType.HEAT}

_CONTROLLER_HEADER = '''"""Generated controller -- do not edit by hand.

Runs the approved steps of one practical in order. Every motion goes
through the safety kernel (``SafetyKernel.execute``), which enforces
the speed/force caps and the monitored stop. This module never
addresses hardware directly and imports nothing beyond the kernel
and the generic models.
"""

from mimforge.models import MotionPrimitiveType
from mimforge.safety import MotionCommand

'''


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def generate_controller(template: dict, design_parameters: dict | None = None) -> str:
    """Generate the step-sequenced controller source for a template.

    ``template`` is a PracticalTemplate as plain data (the JSON form
    under ``mimforge.templates``); ``design_parameters`` are the
    machine design's numeric parameters, emitted as a literal dict.
    """
    practical = template.get("practical", {})
    title = practical.get("title", "Untitled practical")
    steps = sorted(template.get("steps", []), key=lambda s: s.get("order", 0))
    params = design_parameters or {}

    lines = [_CONTROLLER_HEADER]
    lines.append(f'TITLE = "{_escape(title)}"\n')
    lines.append("PARAMETERS = {")
    for key in sorted(params):
        value = params[key]
        if isinstance(value, (int, float, str, bool)) or value is None:
            lines.append(f"    {key!r}: {value!r},")
    lines.append("}\n\n")
    lines.append("def run(kernel):")
    lines.append('    """Execute the approved steps in order."""')
    if not steps:
        lines.append("    # No steps in this template: nothing to run.")
        lines.append("    return")
    for step in steps:
        step_title = step.get("title", "")
        lines.append(f"    # Step {step.get('order', '?')}: {step_title}")
        duration = step.get("duration_hint_s")
        duration_arg = f", duration_s={float(duration)}" if duration else ""
        emitted = False
        for prim in step.get("motion_primitives", []):
            ptype = MotionPrimitiveType(prim.get("type", ""))
            if ptype in _MOTION_PRIMITIVES:
                speed = _PRIMITIVE_SPEEDS[ptype]
                lines.append(
                    "    kernel.execute(MotionCommand("
                    f"primitive=MotionPrimitiveType.{ptype.name}, "
                    f"speed_mm_s={speed}{duration_arg}))"
                )
                emitted = True
            elif ptype in _OBSERVATION_PRIMITIVES:
                lines.append("    # Observation step: record, do not move.")
                emitted = True
            elif ptype in _TOOL_PRIMITIVES:
                lines.append(
                    f"    # Tool step ({ptype.name.lower()}): needs a "
                    "teacher-approved tool binding before it can run."
                )
                emitted = True
        if not emitted:
            lines.append("    # No motion primitives in this step.")
    lines.append("")
    lines.append("if __name__ == \"__main__\":")
    lines.append("    from mimforge.safety import SafetyKernel")
    lines.append("    run(SafetyKernel())")
    return "\n".join(lines)


_PANEL_HEADER = '''"""Generated control panel -- do not edit by hand.

Operator surface for one practical, built from the template's
control_panel list. Release and Stop act only through the safety
kernel passed to the panel; without a kernel the buttons only update
the status line. Styled to the project design rule: dark charcoal,
one electric accent, mono type for measurements.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from mimforge.models import MotionPrimitiveType
from mimforge.safety import MotionCommand

ACCENT = "#00E5FF"
BACKGROUND = "#17191D"
SURFACE = "#22252B"
TEXT = "#E8EAED"
MUTED = "#9AA0A6"

'''


def _panel_widget_snippet(
    name: str, selector_options: list[str], columns: list[str]
) -> list[str]:
    """One control from the template's control_panel list."""
    key = name.lower()
    if "selector" in key:
        items = ", ".join(f'"{_escape(o)}"' for o in selector_options) or '"—"'
        return [
            '        self.length_selector = QComboBox()',
            f'        self.length_selector.addItems([{items}])',
            '        self.length_selector.setCurrentIndex(0)',
            '        self.layout.addWidget(QLabel("Setting:"))',
            '        self.layout.addWidget(self.length_selector)',
        ]
    if "release" in key:
        return [
            '        self.release_button = QPushButton("Release")',
            '        self.release_button.clicked.connect(self.on_release)',
            '        self.layout.addWidget(self.release_button)',
        ]
    if "stop" in key:
        return [
            '        self.stop_button = QPushButton("Stop")',
            '        self.stop_button.setStyleSheet('
            '"background-color: #5C1A1A; color: #FFFFFF;")',
            '        self.stop_button.clicked.connect(self.on_stop)',
            '        self.layout.addWidget(self.stop_button)',
        ]
    if "count" in key or "time" in key or "live" in key:
        return [
            '        self.live_label = QLabel("Count: 0   Time: 0.0 s")',
            '        self.live_label.setFont(QFont("monospace", 14))',
            '        self.layout.addWidget(self.live_label)',
        ]
    if "table" in key:
        headers = ", ".join(f'"{_escape(c)}"' for c in columns) or '"Value"'
        return [
            '        self.readings_table = QTableWidget(0, '
            f'{max(len(columns), 1)})',
            f'        self.readings_table.setHorizontalHeaderLabels([{headers}])',
            '        self.layout.addWidget(self.readings_table)',
        ]
    if "graph" in key:
        return [
            '        self.graph_label = QLabel("Graph canvas: plot appears here")',
            '        self.graph_label.setAlignment(Qt.AlignCenter)',
            '        self.layout.addWidget(self.graph_label)',
        ]
    return [
        f'        self.layout.addWidget(QLabel("{_escape(name)}"))',
    ]


def generate_control_panel(template: dict) -> str:
    """Generate the PySide6 control-panel source for a template."""
    practical = template.get("practical", {})
    title = practical.get("title", "Untitled practical")
    controls = template.get("control_panel", []) or []
    if not controls:
        # The first template carries the panel list inside its
        # machine-design hint; either location is accepted.
        controls = template.get("machine_design_hint", {}).get("control_panel", []) or []
    obs = template.get("observation_spec", {}) or {}
    columns = [c.get("label", c.get("key", "")) for c in obs.get("columns", [])]
    # Selector options: the values of the first observation column
    # across the template's example rows (whatever that column is).
    selector_options: list[str] = []
    rows = obs.get("rows", []) or []
    col_keys = [c.get("key", "") for c in obs.get("columns", [])]
    if rows and col_keys:
        first_key = col_keys[0]
        seen: list[str] = []
        for row in rows:
            if isinstance(row, dict) and first_key in row:
                value = str(row[first_key])
                if value not in seen:
                    seen.append(value)
        selector_options = seen

    lines = [_PANEL_HEADER]
    lines.append("class ControlPanel(QMainWindow):")
    lines.append('    """Operator panel for one practical."""')
    lines.append("")
    lines.append("    def __init__(self, kernel=None):")
    lines.append("        super().__init__()")
    lines.append("        self.kernel = kernel")
    lines.append(f'        self.setWindowTitle("{_escape(title)}")')
    lines.append('        self.setStyleSheet(')
    lines.append('            "QMainWindow { background-color: " + BACKGROUND + "; } "')
    lines.append('            "QWidget { background-color: " + SURFACE + "; color: "')
    lines.append('            + TEXT + "; } "')
    lines.append('            "QPushButton { background-color: " + ACCENT + "; "')
    lines.append('            "color: #101214; padding: 8px; }"')
    lines.append("        )")
    lines.append("        central = QWidget()")
    lines.append("        self.setCentralWidget(central)")
    lines.append("        self.layout = QVBoxLayout(central)")
    lines.append('        self.status = QLabel("Ready.")')
    lines.append('        self.status.setFont(QFont("monospace", 12))')
    lines.append("        self.layout.addWidget(self.status)")
    for control in controls:
        lines.extend(_panel_widget_snippet(str(control), selector_options, columns))
    lines.append("")
    lines.append("    def on_release(self):")
    lines.append('        """Release through the safety kernel, if one is set."""')
    lines.append("        if self.kernel is not None:")
    lines.append("            self.kernel.execute(MotionCommand(")
    lines.append("                primitive=MotionPrimitiveType.RELEASE,")
    lines.append("                speed_mm_s=0.0))")
    lines.append('        self.status.setText("Released.")')
    lines.append("")
    lines.append("    def on_stop(self):")
    lines.append('        """Latch the monitored stop through the kernel."""')
    lines.append("        if self.kernel is not None:")
    lines.append('            self.kernel.trigger_stop("operator stop")')
    lines.append('        self.status.setText("Stopped.")')
    lines.append("")
    lines.append("")
    lines.append("def main():")
    lines.append("    app = QApplication([])")
    lines.append("    panel = ControlPanel()")
    lines.append("    panel.show()")
    lines.append("    app.exec()")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    main()")
    return "\n".join(lines)
