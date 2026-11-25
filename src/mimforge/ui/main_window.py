"""Main window: mission-control shell for the Mimforge desktop app.

Layout: a left navigation rail (section plates), a central drafting
canvas with a blueprint grid and dimension-line header, and a bottom
status strip with mono readouts. Panels are swapped per section; the
lesson player is a stub panel in this phase (playback engine lands in
Phase 6) and the safety panel hosts the monitored-stop control.

Runs headless under ``QT_QPA_PLATFORM=offscreen`` for tests.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

# -- design tokens (single electric accent on dark charcoal) -------------
ACCENT = "#00E5FF"  # electric cyan -- the one accent
BG = "#17191D"  # dark charcoal
PANEL_BG = "#20242A"
PANEL_BORDER = "#343A42"
TEXT = "#D7DDE3"
MUTED = "#7A838D"
GRID_LINE = "#262B31"
STOP_RED = "#E5484D"  # safety-signal exception: the E-stop only
MONO_FAMILY = "Consolas, 'JetBrains Mono', 'DejaVu Sans Mono', monospace"

SECTIONS = ["Projects", "Author", "Design", "Simulate", "Safety", "Playback"]


def mono_font(point_size: int = 10, bold: bool = False) -> QFont:
    font = QFont()
    font.setFamilies([f.strip().strip("'") for f in MONO_FAMILY.split(",")])
    font.setPointSize(point_size)
    font.setBold(bold)
    return font


class DraftingCanvas(QWidget):
    """Central canvas: drafting grid + dimension-line header strip.

    The grid is drawn, not a background image, so it scales with the
    window and stays crisp at any size.
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QLabel(f"  ┌─ {title} ────────────────────────────  SCALE 1:1  ─┐")
        header.setFont(mono_font(10, bold=True))
        header.setStyleSheet(f"color: {ACCENT}; padding: 6px 0;")
        layout.addWidget(header)
        self.body = QVBoxLayout()
        layout.addLayout(self.body, stretch=1)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window().color())
        pen = QPen()
        pen.setColor(GRID_LINE)
        painter.setPen(pen)
        step = 24
        for x in range(0, self.width(), step):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), step):
            painter.drawLine(0, y, self.width(), y)


def _panel(title: str, lines: list[str]) -> QWidget:
    """A placeholder control panel: title plate + mono status lines."""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    plate = QLabel(f"■ {title}")
    plate.setFont(mono_font(12, bold=True))
    plate.setStyleSheet(f"color: {TEXT};")
    layout.addWidget(plate)
    for line in lines:
        label = QLabel(line)
        label.setFont(mono_font(10))
        label.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(label)
    layout.addStretch(1)
    return widget


class PlaybackPanel(QWidget):
    """Lesson player stub (Phase 6 wires the real playback engine)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("■ LESSON PLAYBACK — STUB")
        title.setFont(mono_font(12, bold=True))
        layout.addWidget(title)
        self.steps = QListWidget()
        self.steps.addItems(
            ["01  —  (no lesson loaded)", "02  —  open a project to load steps"]
        )
        self.steps.setFont(mono_font(10))
        layout.addWidget(self.steps)
        controls = QHBoxLayout()
        self.play_button = QPushButton("▶  PLAY")
        self.pause_button = QPushButton("❚❚  PAUSE")
        self.stop_button = QPushButton("■  STOP")
        for button in (self.play_button, self.pause_button, self.stop_button):
            button.setFont(mono_font(10, bold=True))
            controls.addWidget(button)
        layout.addLayout(controls)
        self.status = QLabel("STATUS: IDLE — NO LESSON LOADED")
        self.status.setFont(mono_font(10, bold=True))
        self.status.setStyleSheet(f"color: {ACCENT};")
        layout.addWidget(self.status)
        layout.addStretch(1)


class SafetyPanel(QWidget):
    """Safety panel: monitored-stop control + audit readout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("■ SAFETY KERNEL — MONITORED STOP")
        title.setFont(mono_font(12, bold=True))
        layout.addWidget(title)
        self.estop_button = QPushButton("⬤  EMERGENCY STOP")
        self.estop_button.setFont(mono_font(12, bold=True))
        self.estop_button.setStyleSheet(
            f"color: {STOP_RED}; border: 2px solid {STOP_RED}; padding: 12px;"
        )
        layout.addWidget(self.estop_button)
        self.reset_button = QPushButton("RESET — DELIBERATE TEACHER ACTION")
        self.reset_button.setFont(mono_font(10, bold=True))
        layout.addWidget(self.reset_button)
        self.state_label = QLabel("STATE: ARMED — CAP 250 mm/s — NO FAULTS")
        self.state_label.setFont(mono_font(10, bold=True))
        self.state_label.setStyleSheet(f"color: {ACCENT};")
        layout.addWidget(self.state_label)
        layout.addStretch(1)


class MainWindow(QMainWindow):
    """The Mimforge shell: nav rail + drafting canvas + status strip."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MIMFORGE — TEACHING MACHINE STUDIO  ·  v0.0.1")
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(
            f"QMainWindow {{ background: {BG}; color: {TEXT}; }}"
            f"QWidget {{ background: {BG}; color: {TEXT}; }}"
            f"QPushButton {{ background: {PANEL_BG}; color: {TEXT}; "
            f"border: 1px solid {PANEL_BORDER}; padding: 8px 14px; }}"
            f"QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}"
            f"QListWidget {{ background: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; }}"
            f"QFrame {{ border: 1px solid {PANEL_BORDER}; }}"
        )

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left navigation rail.
        rail = QFrame()
        rail.setFixedWidth(180)
        rail_layout = QVBoxLayout(rail)
        brand = QLabel("MIMFORGE")
        brand.setFont(mono_font(16, bold=True))
        brand.setStyleSheet(f"color: {ACCENT}; padding: 12px 8px 2px;")
        rail_layout.addWidget(brand)
        sub = QLabel("TEACHING MACHINE\nSTUDIO")
        sub.setFont(mono_font(9))
        sub.setStyleSheet(f"color: {MUTED}; padding: 0 8px 12px;")
        rail_layout.addWidget(sub)
        self.nav = QListWidget()
        self.nav.addItems([f"▸ {section.upper()}" for section in SECTIONS])
        self.nav.setFont(mono_font(11, bold=True))
        self.nav.setCurrentRow(0)
        rail_layout.addWidget(self.nav, stretch=1)
        root.addWidget(rail)

        # Central drafting canvas with stacked section panels.
        self.canvas = DraftingCanvas("ELEVATION — WORKSPACE")
        self.stack = QStackedWidget()
        self.playback_panel = PlaybackPanel()
        self.safety_panel = SafetyPanel()
        panels: dict[str, QWidget] = {
            "Projects": _panel(
                "PROJECTS",
                ["No project open.", "Create or open a project to begin."],
            ),
            "Author": _panel(
                "AUTHOR — DEMONSTRATION STEPS",
                ["Import a demonstration video to draft steps.", "Teacher approves every step."],
            ),
            "Design": _panel(
                "DESIGN — MACHINE + BOM",
                ["Platform: bench gantry (parameterised).", "BOM tiers: Prototype / Professional / Industrial."],
            ),
            "Simulate": _panel(
                "SIMULATE — VERIFICATION",
                ["Simulation vs demonstration discrepancy report.", "No run yet."],
            ),
            "Safety": self.safety_panel,
            "Playback": self.playback_panel,
        }
        for section in SECTIONS:
            self.stack.addWidget(panels[section])
        self.canvas.body.addWidget(self.stack)
        root.addWidget(self.canvas, stretch=1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        self.setCentralWidget(central)

        status = QStatusBar()
        status.setFont(mono_font(9))
        status.showMessage("READY  ·  OFFLINE-FIRST  ·  LEAN PROFILE  ·  CAP 250 mm/s")
        status.setStyleSheet(f"color: {MUTED}; background: {PANEL_BG};")
        self.setStatusBar(status)

    def current_section(self) -> str:
        return SECTIONS[self.stack.currentIndex()]


def run() -> int:
    """Launch the desktop shell (entry point for the packaged app)."""
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
