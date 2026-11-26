"""Main window: mission-control shell for the Mimforge desktop app.

Layout: a left navigation rail (section plates), a central drafting
canvas with a blueprint grid and dimension-line header, and a bottom
status strip with mono readouts. Panels are swapped per section; the
lesson player is the Phase 6 playback engine and the safety panel
hosts the monitored-stop control.

Runs headless under ``QT_QPA_PLATFORM=offscreen`` for tests.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
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

from ..safety import SafetyKernel
from .motion import motion_enabled, set_motion_enabled

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


def _icon_png_path() -> Path:
    """Locate the bundled app icon (logo C, "Machine Frame").

    Frozen (PyInstaller): mimforge.spec ships
    ``assets/branding/icon_256.png`` under the bundle root
    (``sys._MEIPASS``). Dev: the same path relative to the repository
    root -- this file lives at ``src/mimforge/ui/main_window.py``.
    """
    rel = Path("assets") / "branding" / "icon_256.png"
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root is not None:
        return Path(bundle_root) / rel
    return Path(__file__).resolve().parents[3] / rel


def app_icon() -> QIcon:
    """The application icon; an empty icon if the file is missing."""
    path = _icon_png_path()
    return QIcon(str(path)) if path.is_file() else QIcon()


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
        # Living workspace: a soft scan line travels the drafting
        # grid while the window is shown and motion is on.
        self._scan_phase = 0.0
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(50)
        self._scan_timer.timeout.connect(self._advance_scan)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._scan_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._scan_timer.stop()
        super().hideEvent(event)

    def _advance_scan(self) -> None:
        if not motion_enabled():
            return
        self._scan_phase = (self._scan_phase + 0.004) % 1.0
        self.update()

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
        if motion_enabled() and self.width() > 0:
            scan_x = int(self._scan_phase * self.width())
            scan_color = QColor(ACCENT)
            scan_color.setAlpha(46)
            pen.setColor(scan_color)
            pen.setWidth(9)
            painter.setPen(pen)
            painter.drawLine(scan_x, 0, scan_x, self.height())
            scan_color.setAlpha(120)
            pen.setColor(scan_color)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(scan_x, 0, scan_x, self.height())


class BootIntro(QWidget):
    """Launch overlay: the Machine Frame mark fades in while a
    dimension line sweeps beneath it, then the overlay lifts.
    Brief (about 1.5 s), decorative only, and dismissed at once by
    any click or keypress -- it never blocks the shell."""

    DURATION_MS = 1500

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._step)
        icon_path = _icon_png_path()
        self._pixmap = (
            QPixmap(str(icon_path)) if icon_path.is_file() else QPixmap()
        )
        self.setFocusPolicy(Qt.StrongFocus)

    def start(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._timer.start()

    def finish(self) -> None:
        self._timer.stop()
        self.hide()
        self.deleteLater()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.finish()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.finish()

    def _step(self) -> None:
        self._phase += self._timer.interval() / self.DURATION_MS
        if self._phase >= 1.0:
            self.finish()
            return
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(BG))
        # Fade in fast, hold, fade out at the end.
        if self._phase < 0.25:
            opacity = self._phase / 0.25
        elif self._phase > 0.8:
            opacity = max(0.0, (1.0 - self._phase) / 0.2)
        else:
            opacity = 1.0
        painter.setOpacity(opacity)
        cx, cy = self.width() // 2, self.height() // 2
        if not self._pixmap.isNull():
            size = 132
            painter.drawPixmap(
                cx - size // 2, cy - size - 8, size, size, self._pixmap
            )
        painter.setFont(mono_font(18, bold=True))
        painter.setPen(QColor(ACCENT))
        painter.drawText(
            cx - 200, cy + 24, 400, 30, Qt.AlignCenter, "MIMFORGE"
        )
        # Dimension line sweeping out from the centre.
        half = int(190 * min(1.0, self._phase / 0.6))
        y = cy + 62
        pen = QPen(QColor(ACCENT))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(cx - half, y, cx + half, y)
        painter.drawLine(cx - half, y - 6, cx - half, y + 6)
        painter.drawLine(cx + half, y - 6, cx + half, y + 6)


def _default_projects_dir() -> Path:
    """Where the app keeps its projects: ``MIMFORGE_PROJECTS_DIR``
    when set, else a ``Mimforge/projects`` folder in the user's
    home directory."""
    override = os.environ.get("MIMFORGE_PROJECTS_DIR")
    if override:
        return Path(override)
    return Path.home() / "Mimforge" / "projects"


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "project"


class SafetyPanel(QWidget):
    """Safety panel: monitored-stop control + audit readout.

    Wired to the real safety kernel: the on-screen EMERGENCY STOP
    latches the kernel's monitored stop, and RESET re-arms only
    through the kernel's deliberate operator reset. The state plate
    always shows the kernel's actual state, never a fixed string.
    """

    def __init__(
        self,
        kernel: SafetyKernel | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kernel = kernel or SafetyKernel()
        layout = QVBoxLayout(self)
        title = QLabel("■ SAFETY KERNEL — MONITORED STOP")
        title.setFont(mono_font(12, bold=True))
        layout.addWidget(title)
        self.estop_button = QPushButton("⬤  EMERGENCY STOP")
        self.estop_button.setFont(mono_font(12, bold=True))
        self.estop_button.clicked.connect(self._on_estop)
        layout.addWidget(self.estop_button)
        # While armed the stop carries a slow red pulse; once
        # latched it goes solid and stays that way until reset.
        self._pulse_on = False
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(650)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self.reset_button = QPushButton("RESET — DELIBERATE TEACHER ACTION")
        self.reset_button.setFont(mono_font(10, bold=True))
        self.reset_button.clicked.connect(self._on_reset)
        layout.addWidget(self.reset_button)
        self.state_label = QLabel("")
        self.state_label.setFont(mono_font(10, bold=True))
        layout.addWidget(self.state_label)
        self.audit_label = QLabel("LOG: —")
        self.audit_label.setFont(mono_font(9))
        self.audit_label.setStyleSheet(f"color: {MUTED};")
        self.audit_label.setWordWrap(True)
        layout.addWidget(self.audit_label)
        layout.addStretch(1)
        self._refresh()

    # -------------------------------------------------------------- slots

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._pulse_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._pulse_timer.stop()
        super().hideEvent(event)

    def _pulse_tick(self) -> None:
        if self.kernel.stopped or not motion_enabled():
            return
        self._pulse_on = not self._pulse_on
        self._style_estop()

    def _style_estop(self) -> None:
        if self.kernel.stopped:
            # Latched: solid red, no pulse, until a deliberate reset.
            self.estop_button.setStyleSheet(
                f"background: {STOP_RED}; color: #FFFFFF; "
                f"border: 2px solid {STOP_RED}; padding: 12px;"
            )
        elif self._pulse_on:
            self.estop_button.setStyleSheet(
                f"color: {STOP_RED}; border: 2px solid {STOP_RED}; "
                f"background: rgba(229, 72, 77, 0.18); padding: 12px;"
            )
        else:
            self.estop_button.setStyleSheet(
                f"color: {STOP_RED}; border: 2px solid {STOP_RED}; "
                f"padding: 12px;"
            )

    def _on_estop(self) -> None:
        self.kernel.trigger_stop("on-screen emergency stop")
        self._refresh()

    def _on_reset(self) -> None:
        self.kernel.reset(operator="teacher")
        self._refresh()

    def _refresh(self) -> None:
        cap = self.kernel.limits.max_tool_speed_mm_s
        if self.kernel.stopped:
            self.state_label.setText(
                f"STATE: STOPPED — LATCHED — CAP {cap:g} mm/s"
            )
            self.state_label.setStyleSheet(f"color: {STOP_RED};")
            self.reset_button.setEnabled(True)
        else:
            self.state_label.setText(
                f"STATE: ARMED — CAP {cap:g} mm/s — NO FAULTS"
            )
            self.state_label.setStyleSheet(f"color: {ACCENT};")
            self.reset_button.setEnabled(False)
        self._style_estop()
        entries = self.kernel.audit_log()
        if entries:
            self.audit_label.setText(f"LOG: {entries[-1].detail}")


class MainWindow(QMainWindow):
    """The Mimforge shell: nav rail + drafting canvas + status strip.

    The window is also the shell's controller: it owns the project
    store location, the current project / template / draft, and the
    last verification outcome, and the workspace panels delegate
    every action here.
    """

    def __init__(
        self,
        projects_dir: str | Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.projects_dir = (
            Path(projects_dir)
            if projects_dir is not None
            else _default_projects_dir()
        )
        self.current_project = None
        self.current_template = None
        self.current_template_data: dict | None = None
        self.current_template_name = ""
        self.last_verification = None
        self.setWindowTitle("MIMFORGE — TEACHING MACHINE STUDIO  ·  v0.0.1")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(
            f"QMainWindow {{ background: {BG}; color: {TEXT}; }}"
            f"QWidget {{ background: {BG}; color: {TEXT}; }}"
            f"QPushButton {{ background: {PANEL_BG}; color: {TEXT}; "
            f"border: 1px solid {PANEL_BORDER}; padding: 8px 14px; }}"
            f"QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}"
            f"QListWidget {{ background: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; }}"
            f"QListWidget::item:hover {{ color: {ACCENT}; }}"
            f"QListWidget::item:selected {{ background: #2A2F36; color: {ACCENT}; }}"
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
        self.motion_button = QPushButton()
        self.motion_button.setFont(mono_font(9, bold=True))
        self.motion_button.clicked.connect(self._toggle_motion)
        rail_layout.addWidget(self.motion_button)
        self._refresh_motion_button()
        root.addWidget(rail)

        # Central drafting canvas with stacked section panels.
        self.canvas = DraftingCanvas("ELEVATION — WORKSPACE")
        self.stack = QStackedWidget()
        # Local imports: ui panels import the design tokens from here.
        from .panels import DesignPanel, ProjectsPanel, SimulatePanel
        from .playback import LessonPlayer

        self.playback_panel = LessonPlayer()
        self.playback_panel.export_requested.connect(
            lambda: self.export_lesson_html()
        )
        self.safety_panel = SafetyPanel()
        from .authoring import AuthoringPanel

        self.author_panel = AuthoringPanel()
        self.author_panel.build_lesson_requested.connect(
            self.build_current_lesson
        )
        self.projects_panel = ProjectsPanel(self)
        self.design_panel = DesignPanel()
        self.simulate_panel = SimulatePanel(self)
        panels: dict[str, QWidget] = {
            "Projects": self.projects_panel,
            "Author": self.author_panel,
            "Design": self.design_panel,
            "Simulate": self.simulate_panel,
            "Safety": self.safety_panel,
            "Playback": self.playback_panel,
        }
        for section in SECTIONS:
            self.stack.addWidget(panels[section])
        self.canvas.body.addWidget(self.stack)
        root.addWidget(self.canvas, stretch=1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.currentRowChanged.connect(self._fade_stack)
        self._fade_effect = QGraphicsOpacityEffect(self.stack)
        self._fade_anim = QPropertyAnimation(
            self._fade_effect, b"opacity", self
        )
        self._fade_anim.setDuration(220)

        self.setCentralWidget(central)

        status = QStatusBar()
        status.setFont(mono_font(9))
        status.showMessage("READY  ·  OFFLINE-FIRST  ·  LEAN PROFILE  ·  CAP 250 mm/s")
        status.setStyleSheet(f"color: {MUTED}; background: {PANEL_BG};")
        self.setStatusBar(status)

        # The Design panel shows the default machine until a project
        # is opened; the Projects panel lists the store as found.
        self.design_panel.show_design(
            None, self.current_params(), self.bom_totals()
        )

    # -------------------------------------------------------------- motion

    def _refresh_motion_button(self) -> None:
        self.motion_button.setText(
            "MOTION: FULL" if motion_enabled() else "MOTION: REDUCED"
        )

    def _toggle_motion(self) -> None:
        set_motion_enabled(not motion_enabled())
        self._refresh_motion_button()

    def _fade_stack(self, _index: int) -> None:
        """Section changes fade in instead of swapping instantly.
        Skipped entirely when the window is not shown (tests) or
        motion is reduced -- the end state is identical either way."""
        if not self.isVisible() or not motion_enabled():
            return
        self.stack.setGraphicsEffect(self._fade_effect)
        self._fade_anim.stop()
        self._fade_anim.setStartValue(0.25)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        if getattr(self, "_intro_shown", False):
            return
        self._intro_shown = True
        if motion_enabled():
            BootIntro(self.centralWidget()).start()

    def current_section(self) -> str:
        return SECTIONS[self.stack.currentIndex()]

    def load_lesson(self, lesson) -> None:
        """Load a lesson package into the Playback panel and show it."""
        self.playback_panel.load_lesson(lesson)
        self.nav.setCurrentRow(SECTIONS.index("Playback"))

    # ---------------------------------------------------- project store

    def available_templates(self) -> list[dict]:
        from ..templates import list_templates

        return list_templates()

    def saved_projects(self) -> list[tuple[str, str]]:
        """(project_id, title) for every project in the store."""
        from ..projects import MANIFEST_NAME, list_projects

        saved = []
        for project_id in list_projects(self.projects_dir):
            title = project_id
            manifest_path = self.projects_dir / project_id / MANIFEST_NAME
            try:
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                title = manifest.get("title") or project_id
            except (OSError, ValueError):
                pass
            saved.append((project_id, title))
        return saved

    def create_project(self, template_name: str, title: str):
        """Create a project from a bundled template, build its draft
        from the template's own text (no recording yet), make it
        current and show the draft in the Author panel."""
        from ..narration import Transcript
        from ..projects import create_project as _create
        from ..structuring import build_draft
        from ..templates import load_template_data, template_from_data

        self._persist_current_draft()
        data = load_template_data(template_name)
        template = template_from_data(data)
        base = _slugify(title)
        project_id, n = base, 2
        while (self.projects_dir / project_id).exists():
            project_id = f"{base}-{n}"
            n += 1
        project = _create(self.projects_dir, project_id, title)
        project.put_record(
            "template",
            "current",
            {
                "name": template_name,
                "template_id": template.id,
                "data": data,
            },
        )
        draft = build_draft(template, Transcript())
        project.put_record("draft", "current", draft.to_dict())
        project.save()
        self._set_current(project, template, data, template_name)
        self.author_panel.load_draft(draft)
        self.projects_panel.refresh_projects()
        self.projects_panel.show_current(title)
        self.nav.setCurrentRow(SECTIONS.index("Author"))
        self.statusBar().showMessage(f"PROJECT CREATED — {title}")
        return project

    def open_project(self, project_id: str):
        """Open a saved project and load its draft into Author. A
        project whose saved contents no longer match its seal is
        refused in plain words -- never opened, never a crash."""
        from ..projects import IntegrityError, ProjectError
        from ..projects import open_project as _open
        from ..structuring import AuthoringDraft, build_draft
        from ..narration import Transcript
        from ..templates import template_from_data

        self._persist_current_draft()
        try:
            project = _open(self.projects_dir, project_id)
        except IntegrityError:
            self.projects_panel.status_label.setText(
                "STATUS: THAT PROJECT COULD NOT BE OPENED — ITS SAVED "
                "CONTENTS DO NOT MATCH ITS SEAL"
            )
            return None
        except (ProjectError, OSError, ValueError):
            self.projects_panel.status_label.setText(
                "STATUS: THAT PROJECT COULD NOT BE OPENED"
            )
            return None
        record = project.get_record("template", "current")
        if record is None:
            self.projects_panel.status_label.setText(
                "STATUS: THAT PROJECT CARRIES NO TEMPLATE"
            )
            return None
        data = record["data"]
        template = template_from_data(data)
        draft_record = project.get_record("draft", "current")
        if draft_record is not None:
            draft = AuthoringDraft.from_dict(draft_record)
        else:
            draft = build_draft(template, Transcript())
        self._set_current(project, template, data, record.get("name", ""))
        self.author_panel.load_draft(draft)
        self.projects_panel.show_current(project.title)
        self.nav.setCurrentRow(SECTIONS.index("Author"))
        self.statusBar().showMessage(f"PROJECT OPEN — {project.title}")
        return project

    def _set_current(self, project, template, data, template_name: str) -> None:
        self.current_project = project
        self.current_template = template
        self.current_template_data = data
        self.current_template_name = template_name
        self.last_verification = None
        self.design_panel.show_design(
            project.title, self.current_params(), self.bom_totals()
        )
        self.simulate_panel.show_project(project.title)

    def _persist_current_draft(self) -> None:
        if self.current_project is None:
            return
        draft = self.author_panel.current_draft()
        if draft is not None:
            self.current_project.put_record("draft", "current", draft.to_dict())
            self.current_project.save()

    # ------------------------------------------------------------ design

    def current_params(self):
        """The current project's machine parameters (defaults until
        a project stores its own design record)."""
        from ..design import GantryParameters

        if self.current_project is not None:
            record = self.current_project.get_record("design", "current")
            if record:
                try:
                    return GantryParameters(**record)
                except (TypeError, ValueError):
                    pass
        return GantryParameters()

    def bom_totals(self) -> list[tuple[str, float]]:
        from ..bom import TIERS, PartsDB, generate_bom
        from ..design import build_gantry

        part_ids = build_gantry(self.current_params()).part_ids
        db = PartsDB()
        return [
            (tier, generate_bom(db, tier, part_ids).total_ngn)
            for tier in TIERS
        ]

    # -------------------------------------------------------- verification

    def run_verification(self):
        """Run the Phase 4 pipeline for the current project and show
        the outcome in the Simulate panel."""
        from ..verification import run_verification as _run

        if self.current_template is None:
            self.simulate_panel.show_message(
                "NO PROJECT OPEN — CREATE OR OPEN A PROJECT FIRST"
            )
            return None
        try:
            outcome = _run(
                self.current_template,
                self.current_template_data,
                params=self.current_params(),
                length_scale=self.current_length_scale(),
            )
        except Exception as exc:  # plain-words failure, never a crash
            self.simulate_panel.show_message(
                f"VERIFICATION COULD NOT RUN — {exc}"
            )
            return None
        self.last_verification = outcome
        self.simulate_panel.show_outcome(outcome)
        return outcome

    # ------------------------------------------------------- calibration

    def current_length_scale(self) -> float:
        """The current project's stored length calibration (1.0
        until an auto-adjust run corrects it)."""
        if self.current_project is not None:
            record = self.current_project.get_record("calibration", "current")
            if record:
                try:
                    scale = float(record.get("length_scale", 1.0))
                except (TypeError, ValueError):
                    return 1.0
                if scale > 0:
                    return scale
        return 1.0

    def run_auto_adjust(self):
        """Bounded auto-adjust: correct the machine's length scale
        until the simulated outcome lands on the demonstrated one
        inside the template's tolerance band. The corrected scale
        is stored on the project and the verification re-runs so
        the panel shows the corrected outcome. Unfixable cases are
        reported for teacher review, never silently passed."""
        from ..adjust import auto_adjust
        from ..verification import simulated_recovered

        if self.current_template is None:
            self.simulate_panel.show_message(
                "NO PROJECT OPEN — CREATE OR OPEN A PROJECT FIRST"
            )
            return None
        outcome = self.last_verification or self.run_verification()
        if outcome is None:
            return None
        target = float(outcome.teacher_fit["recovered_value"])
        params = self.current_params()
        template = self.current_template
        data = self.current_template_data

        def evaluate(parameters):
            return simulated_recovered(
                template,
                data,
                params=params,
                length_scale=parameters["length_scale"],
            )

        def rule(parameters, value, goal):
            # The recovered value scales inversely with the set
            # lengths, so the scale moves by value/goal.
            return {"length_scale": parameters["length_scale"] * value / goal}

        result = auto_adjust(
            {"length_scale": self.current_length_scale()},
            evaluate=evaluate,
            adjust=rule,
            target=target,
            band_percent=float(outcome.band_percent),
        )
        if result.fixed:
            scale = float(result.final_parameters["length_scale"])
            if self.current_project is not None:
                self.current_project.put_record(
                    "calibration", "current", {"length_scale": scale}
                )
                self.current_project.save()
            self.last_verification = None
            self.run_verification()
            self.simulate_panel.show_adjust(result, scale)
            return result
        self.simulate_panel.show_adjust(
            result, self.current_length_scale()
        )
        return result

    # ------------------------------------------------------------ export

    def export_lesson_html(self, path=None):
        """Write the loaded lesson as one self-contained HTML file
        (the Phase 6 export). With no path, a save dialog asks;
        cancelling is a plain status, never a dead end."""
        from ..playback import export_html_lesson

        lesson = self.playback_panel.lesson
        if lesson is None:
            self.playback_panel.status.setText(
                "STATUS: NO LESSON LOADED — NOTHING TO EXPORT"
            )
            return None
        if path is None:
            chosen, _selected = QFileDialog.getSaveFileName(
                self,
                "Export lesson",
                f"{lesson.title}.html",
                "HTML files (*.html)",
            )
            if not chosen:
                self.playback_panel.status.setText(
                    "STATUS: EXPORT CANCELLED"
                )
                return None
            path = chosen
        target = export_html_lesson(lesson, path)
        self.playback_panel.status.setText(
            f"STATUS: LESSON SAVED — {Path(target).name}"
        )
        return target

    # ------------------------------------------------------------- lesson

    def build_current_lesson(self):
        """Assemble the lesson package from the approved draft plus
        the verification outputs, exactly as the Phase 6 code does,
        and load it into Playback. Nothing is built until every
        draft step carries the teacher's approval."""
        from ..playback import build_lesson

        draft = self.author_panel.current_draft()
        if self.current_template is None or draft is None:
            self.author_panel.status_label.setText(
                "STATUS: NO DRAFT — OPEN A PROJECT FIRST"
            )
            return None
        if draft.approved_count < len(draft.steps):
            self.author_panel.status_label.setText(
                f"STATUS: APPROVE EVERY STEP BEFORE BUILDING THE LESSON"
                f" — {draft.approved_count}/{len(draft.steps)} APPROVED"
            )
            return None
        outcome = self.last_verification or self.run_verification()
        if outcome is None:
            self.author_panel.status_label.setText(
                "STATUS: LESSON NOT BUILT — VERIFICATION NEEDED"
            )
            return None
        lesson = build_lesson(
            self.current_template,
            table=outcome.table,
            graph=outcome.graph,
            replay=outcome.replay,
            verification_run=outcome.run,
        )
        # The teacher's approved wording is the lesson's wording.
        by_order = {step.order: step for step in draft.steps}
        for step in lesson.steps:
            approved = by_order.get(step.order)
            if approved is None:
                continue
            step.title = approved.title or step.title
            step.narration = approved.draft_text
            step.check_question = approved.check_question or step.check_question
            if approved.safety_notes:
                step.safety_notes = list(approved.safety_notes)
        lesson.validate()
        self._persist_current_draft()
        self.load_lesson(lesson)
        self.statusBar().showMessage(
            f"LESSON BUILT — {lesson.step_count} STEPS — PLAYBACK READY"
        )
        return lesson


def run() -> int:
    """Launch the desktop shell (entry point for the packaged app)."""
    app = QApplication([])
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
