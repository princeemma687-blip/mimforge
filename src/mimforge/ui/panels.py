"""Workspace panels for the shell: Projects, Design, Simulate.

These panels are the click-path Prince found missing in the first
install test: create a project from a bundled template, open an
existing one, see the machine design and its bill of materials, and
run the verification. The panels hold no engine logic -- every
action delegates to the host window (``MainWindow``), which owns the
project store, the current template and the pipeline. Widgets are
named so tests can drive the real click-path offscreen.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .main_window import (
    ACCENT,
    MUTED,
    PANEL_BG,
    PANEL_BORDER,
    TEXT,
    mono_font,
)
from .motion import motion_enabled


def _plate(text: str) -> QLabel:
    label = QLabel(f"■ {text}")
    label.setFont(mono_font(12, bold=True))
    label.setStyleSheet(f"color: {TEXT};")
    return label


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(mono_font(9, bold=True))
    label.setStyleSheet(f"color: {MUTED};")
    return label


def _status(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(mono_font(10, bold=True))
    label.setStyleSheet(f"color: {ACCENT};")
    label.setWordWrap(True)
    return label


class ProjectsPanel(QWidget):
    """Project store front-end: registry-driven creation + open."""

    def __init__(self, host, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        layout = QVBoxLayout(self)
        layout.addWidget(_plate("PROJECTS"))

        layout.addWidget(_caption("NEW PROJECT — FROM A TEMPLATE"))
        self.template_combo = QComboBox()
        self.template_combo.setFont(mono_font(10))
        self.template_combo.currentIndexChanged.connect(
            self._on_template_changed
        )
        layout.addWidget(self.template_combo)
        self.title_edit = QLineEdit()
        self.title_edit.setFont(mono_font(10))
        self.title_edit.setPlaceholderText("Project title")
        layout.addWidget(self.title_edit)
        self.create_button = QPushButton("＋  CREATE PROJECT")
        self.create_button.setFont(mono_font(10, bold=True))
        self.create_button.clicked.connect(self._on_create)
        layout.addWidget(self.create_button)

        layout.addWidget(_caption("SAVED PROJECTS"))
        self.project_list = QListWidget()
        self.project_list.setFont(mono_font(10))
        self.project_list.itemDoubleClicked.connect(
            lambda _item: self._on_open()
        )
        layout.addWidget(self.project_list, stretch=1)
        self.open_button = QPushButton("OPEN PROJECT")
        self.open_button.setFont(mono_font(10, bold=True))
        self.open_button.clicked.connect(self._on_open)
        layout.addWidget(self.open_button)

        self.status_label = _status("STATUS: NO PROJECT OPEN")
        layout.addWidget(self.status_label)

        layout.addWidget(_caption("METADATA SYNC — OPTIONAL, OFF BY DEFAULT"))
        self.sync_button = QPushButton("SYNC: OFF")
        self.sync_button.setFont(mono_font(10, bold=True))
        self.sync_button.clicked.connect(lambda: self.host.toggle_sync())
        layout.addWidget(self.sync_button)
        self.sync_status_label = _status("SYNC: OFF")
        layout.addWidget(self.sync_status_label)
        self.refresh()

    # ------------------------------------------------------------ refresh

    def refresh(self) -> None:
        self.refresh_templates()
        self.refresh_projects()

    def refresh_templates(self) -> None:
        current = self.template_combo.currentData()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for entry in self.host.available_templates():
            label = entry["title"]
            if entry["subject"]:
                label += f"  —  {entry['subject']}"
            self.template_combo.addItem(label, entry["name"])
        self.template_combo.blockSignals(False)
        if current is not None:
            index = self.template_combo.findData(current)
            if index >= 0:
                self.template_combo.setCurrentIndex(index)
        self._on_template_changed()

    def refresh_projects(self) -> None:
        self.project_list.clear()
        for project_id, title in self.host.saved_projects():
            self.project_list.addItem(f"{title}   ·   {project_id}")

    def show_current(self, title: str) -> None:
        self.status_label.setText(f"STATUS: CURRENT PROJECT — {title}")

    def show_sync(self, on: bool, text: str) -> None:
        self.sync_button.setText("SYNC: ON" if on else "SYNC: OFF")
        self.sync_status_label.setText(text)

    # -------------------------------------------------------------- slots

    def _on_template_changed(self) -> None:
        name = self.template_combo.currentData()
        for entry in self.host.available_templates():
            if entry["name"] == name:
                self.title_edit.setText(entry["title"])
                return

    def _on_create(self) -> None:
        name = self.template_combo.currentData()
        if name is None:
            self.status_label.setText("STATUS: NO TEMPLATE AVAILABLE")
            return
        title = self.title_edit.text().strip()
        if not title:
            self.status_label.setText("STATUS: GIVE THE PROJECT A TITLE")
            return
        self.host.create_project(name, title)

    def _on_open(self) -> None:
        row = self.project_list.currentRow()
        saved = self.host.saved_projects()
        if row < 0 or row >= len(saved):
            self.status_label.setText("STATUS: CHOOSE A SAVED PROJECT")
            return
        self.host.open_project(saved[row][0])


class GantryElevationView(QWidget):
    """The machine drawn as an elevation from its parameters:
    uprights, top beam, carriage, and the Logo C motif -- a dotted
    suspension path with a glowing dot that travels it. Vector
    lines only, drawn fresh from the parameters on every paint."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(190)
        self._params = None
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)

    def set_params(self, params) -> None:
        self._params = params
        self.update()

    @property
    def params(self):
        return self._params

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        if not motion_enabled():
            return
        self._phase = (self._phase + 0.01) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window().color())
        params = self._params
        if params is None:
            painter.setPen(QColor(MUTED))
            painter.setFont(mono_font(10))
            painter.drawText(self.rect(), Qt.AlignCenter, "NO DESIGN YET")
            return
        span = float(params.span_mm)
        height = float(params.height_mm)
        margin_l, margin_r, margin_t, margin_b = 34, 52, 16, 30
        avail_w = max(self.width() - margin_l - margin_r, 10)
        avail_h = max(self.height() - margin_t - margin_b, 10)
        scale = min(avail_w / span, avail_h / height)
        x0, y_base = margin_l, margin_t + height * scale
        x1 = x0 + span * scale
        y_top = margin_t

        def pen(color: str, width: int = 2, style=Qt.SolidLine) -> QPen:
            p = QPen(QColor(color))
            p.setWidth(width)
            p.setStyle(style)
            return p

        # Ground line + uprights + top beam.
        painter.setPen(pen(PANEL_BORDER, 2))
        painter.drawLine(6, int(y_base) + 8, self.width() - 6, int(y_base) + 8)
        painter.setPen(pen(TEXT, 3))
        painter.drawLine(int(x0), int(y_base), int(x0), int(y_top))
        painter.drawLine(int(x1), int(y_base), int(x1), int(y_top))
        painter.drawLine(int(x0), int(y_top), int(x1), int(y_top))
        # Carriage block riding the beam.
        car_w = max(14, int(float(params.carriage_width_mm) * scale))
        car_h = max(8, int(float(params.carriage_height_mm) * scale))
        cx = (x0 + x1) / 2
        painter.fillRect(
            int(cx - car_w / 2), int(y_top - car_h / 2),
            car_w, car_h, QColor(ACCENT),
        )
        # Dotted suspension path (the Logo C motif) + travelling dot.
        path_bottom = y_base - 6
        painter.setPen(pen(ACCENT, 2, Qt.DotLine))
        painter.drawLine(int(cx), int(y_top), int(cx), int(path_bottom))
        travel = (math.sin(self._phase * 2 * math.pi) + 1) / 2
        dot_y = y_top + travel * (path_bottom - y_top)
        glow = QColor(ACCENT)
        glow.setAlpha(70)
        painter.setBrush(glow)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(cx) - 9, int(dot_y) - 9, 18, 18)
        painter.setBrush(QColor(ACCENT))
        painter.drawEllipse(int(cx) - 4, int(dot_y) - 4, 8, 8)
        # Dimension lines: span along the bottom, height at the right.
        painter.setPen(pen(MUTED, 1))
        dim_y = int(y_base) + 22
        painter.drawLine(int(x0), dim_y, int(x1), dim_y)
        painter.drawLine(int(x0), dim_y - 4, int(x0), dim_y + 4)
        painter.drawLine(int(x1), dim_y - 4, int(x1), dim_y + 4)
        dim_x = int(x1) + 26
        painter.drawLine(dim_x, int(y_top), dim_x, int(y_base))
        painter.drawLine(dim_x - 4, int(y_top), dim_x + 4, int(y_top))
        painter.drawLine(dim_x - 4, int(y_base), dim_x + 4, int(y_base))
        painter.setFont(mono_font(8))
        painter.setPen(QColor(MUTED))
        painter.drawText(
            int(x0), dim_y + 14, int(span * scale), 12,
            Qt.AlignCenter, f"{span:.0f}",
        )
        painter.save()
        painter.translate(dim_x + 12, int((y_top + y_base) / 2))
        painter.rotate(-90)
        painter.drawText(-30, 0, 60, 12, Qt.AlignCenter, f"{height:.0f}")
        painter.restore()


def _money(value: float) -> str:
    return f"₦{value:,.0f}"


class DesignPanel(QWidget):
    """The current machine design + bill of materials, with the
    CAD files (STEP / STL) exportable for manufacture. The
    materials table lists every line of the selected tier's BOM --
    the platform spec's "tell the user the necessary materials",
    in full, not just the tier totals."""

    def __init__(self, host=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._tier_boms: dict = {}
        layout = QVBoxLayout(self)
        layout.addWidget(_plate("DESIGN — MACHINE + BOM"))
        self.project_label = _status("PROJECT: —")
        layout.addWidget(self.project_label)
        self.elevation = GantryElevationView()
        layout.addWidget(self.elevation)
        self.readout = QPlainTextEdit()
        self.readout.setFont(mono_font(10))
        self.readout.setReadOnly(True)
        layout.addWidget(self.readout, stretch=1)
        layout.addWidget(
            _caption("MATERIALS — EVERYTHING THE MACHINE IS BUILT FROM")
        )
        self.tier_combo = QComboBox()
        self.tier_combo.setFont(mono_font(10))
        self.tier_combo.currentIndexChanged.connect(
            lambda _index: self._render_materials()
        )
        layout.addWidget(self.tier_combo)
        self.materials_table = QTableWidget(0, 4)
        self.materials_table.setHorizontalHeaderLabels(
            ["MATERIAL", "QTY", "UNIT PRICE", "LINE TOTAL"]
        )
        self.materials_table.setFont(mono_font(10))
        self.materials_table.horizontalHeader().setFont(
            mono_font(9, bold=True)
        )
        self.materials_table.verticalHeader().setVisible(False)
        self.materials_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.materials_table.setSelectionMode(
            QAbstractItemView.NoSelection
        )
        self.materials_table.setFocusPolicy(Qt.NoFocus)
        header = self.materials_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )
        self.materials_table.setStyleSheet(
            f"QTableWidget {{ background: {PANEL_BG}; color: {TEXT}; "
            f"gridline-color: {PANEL_BORDER}; "
            f"border: 1px solid {PANEL_BORDER}; }}"
            f"QHeaderView::section {{ background: {PANEL_BG}; "
            f"color: {MUTED}; border: none; "
            f"border-bottom: 1px solid {PANEL_BORDER}; padding: 4px; }}"
        )
        layout.addWidget(self.materials_table, stretch=1)
        export_row = QHBoxLayout()
        self.export_step_button = QPushButton("⬆  EXPORT STEP")
        self.export_step_button.setFont(mono_font(10, bold=True))
        self.export_step_button.clicked.connect(
            lambda: self.host.export_cad("step")
            if self.host is not None
            else None
        )
        export_row.addWidget(self.export_step_button)
        self.export_stl_button = QPushButton("⬆  EXPORT STL")
        self.export_stl_button.setFont(mono_font(10, bold=True))
        self.export_stl_button.clicked.connect(
            lambda: self.host.export_cad("stl")
            if self.host is not None
            else None
        )
        export_row.addWidget(self.export_stl_button)
        layout.addLayout(export_row)
        self.status_label = _status("STATUS: READY")
        layout.addWidget(self.status_label)

    def set_status(self, text: str) -> None:
        self.status_label.setText(f"STATUS: {text}")

    def show_design(self, project_title: str | None, params, tier_boms) -> None:
        """Show one machine: its parameters, the tier totals, and
        the full itemised materials of the selected tier.
        ``tier_boms`` is a list of (tier, Bom) pairs in tier
        order, exactly as the host's BOM tables provide them."""
        self.project_label.setText(
            f"PROJECT: {project_title or '—'}"
        )
        self.elevation.set_params(params)
        lines = [
            "PLATFORM — PARAMETERISED BENCH FRAME",
            "",
            f"SPAN .............. {params.span_mm:.0f} mm",
            f"HEIGHT ............ {params.height_mm:.0f} mm",
            f"SECTION ........... {params.section_mm:.0f} mm",
            f"BASE DEPTH ........ {params.base_depth_mm:.0f} mm",
            f"FOOT HEIGHT ....... {params.foot_height_mm:.0f} mm",
            f"CARRIAGE .......... {params.carriage_width_mm:.0f} x "
            f"{params.carriage_height_mm:.0f} mm",
            f"SPOOL ............. r {params.spool_radius_mm:.0f} x "
            f"{params.spool_length_mm:.0f} mm",
            "SUSPENSION RANGE .. "
            f"{params.suspension_range_mm[0]:.0f} – "
            f"{params.suspension_range_mm[1]:.0f} mm",
            "",
            "BILL OF MATERIALS — ESTIMATED TOTALS",
        ]
        for tier, bom in tier_boms:
            lines.append(f"{tier.upper():<18} {_money(bom.total_ngn)}")
        lines += [
            "",
            "Every material is itemised in the table below; "
            "prices are estimates.",
        ]
        self.readout.setPlainText("\n".join(lines))
        self._tier_boms = dict(tier_boms)
        current = self.tier_combo.currentData()
        self.tier_combo.blockSignals(True)
        self.tier_combo.clear()
        for tier, _bom in tier_boms:
            self.tier_combo.addItem(tier.upper(), tier)
        self.tier_combo.blockSignals(False)
        if current is not None:
            index = self.tier_combo.findData(current)
            if index >= 0:
                self.tier_combo.setCurrentIndex(index)
        self._render_materials()

    def _render_materials(self) -> None:
        """Fill the materials table with the selected tier's BOM
        lines, footed by that tier's total."""
        tier = self.tier_combo.currentData()
        bom = self._tier_boms.get(tier) if tier else None
        table = self.materials_table
        table.setRowCount(0)
        if bom is None:
            return
        right = Qt.AlignRight | Qt.AlignVCenter
        for line in bom.lines:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(line.name))
            qty = QTableWidgetItem(str(line.quantity))
            qty.setTextAlignment(right)
            table.setItem(row, 1, qty)
            unit = QTableWidgetItem(_money(line.unit_price_ngn))
            unit.setTextAlignment(right)
            table.setItem(row, 2, unit)
            total = QTableWidgetItem(_money(line.line_total_ngn))
            total.setTextAlignment(right)
            table.setItem(row, 3, total)
        foot = table.rowCount()
        table.insertRow(foot)
        label = QTableWidgetItem(f"TIER TOTAL — {bom.tier.upper()}")
        label.setFont(mono_font(10, bold=True))
        table.setItem(foot, 0, label)
        table.setSpan(foot, 0, 1, 3)
        total = QTableWidgetItem(_money(bom.total_ngn))
        total.setFont(mono_font(10, bold=True))
        total.setTextAlignment(right)
        table.setItem(foot, 3, total)


class FitGraphView(QWidget):
    """The fitted graph: the readings as points, the line of best
    fit drawing itself in from the left when a run completes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(170)
        self._points: list[tuple[float, float]] = []
        self._slope = 0.0
        self._intercept = 0.0
        self._progress = 1.0

    def set_data(self, points, slope: float, intercept: float) -> None:
        self._points = list(points)
        self._slope = float(slope)
        self._intercept = float(intercept)
        self._progress = 1.0
        self.update()

    def clear(self) -> None:
        self._points = []
        self._progress = 1.0
        self.update()

    def set_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    @property
    def progress(self) -> float:
        return self._progress

    @property
    def point_count(self) -> int:
        return len(self._points)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window().color())
        if len(self._points) < 2:
            painter.setPen(QColor(MUTED))
            painter.setFont(mono_font(10))
            painter.drawText(
                self.rect(), Qt.AlignCenter, "NO RUN YET — NO GRAPH"
            )
            return
        xs = [p[0] for p in self._points]
        ys = [p[1] for p in self._points]
        fit_ys = [self._slope * x + self._intercept for x in xs]
        all_y = ys + fit_ys
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(all_y), max(all_y)
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)
        pad = 16
        w = max(self.width() - 2 * pad, 1)
        h = max(self.height() - 2 * pad, 1)

        def px(x: float) -> float:
            return pad + (x - min_x) / span_x * w

        def py(y: float) -> float:
            return self.height() - pad - (y - min_y) / span_y * h

        # Fit line, swept in by the progress fraction.
        x_end = min_x + span_x * self._progress
        line = QPen(QColor(ACCENT))
        line.setWidth(2)
        painter.setPen(line)
        painter.drawLine(
            int(px(min_x)), int(py(self._slope * min_x + self._intercept)),
            int(px(x_end)), int(py(self._slope * x_end + self._intercept)),
        )
        # Readings as points.
        painter.setBrush(QColor(TEXT))
        painter.setPen(Qt.NoPen)
        for x, y in self._points:
            painter.drawEllipse(int(px(x)) - 3, int(py(y)) - 3, 6, 6)
        painter.setPen(QColor(MUTED))
        painter.setFont(mono_font(8))
        painter.drawText(pad, 12, "LINE OF BEST FIT — READINGS AS POINTS")


class SimulatePanel(QWidget):
    """Verification front-end: one run button, the fitted graph,
    and one mono readout. On a shown window with motion on, the
    graph sweeps in and the headline numbers count up; everywhere
    else the final values appear at once -- the end state is the
    same."""

    def __init__(self, host, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        layout = QVBoxLayout(self)
        layout.addWidget(_plate("SIMULATE — VERIFICATION"))
        self.project_label = _status("PROJECT: —")
        layout.addWidget(self.project_label)
        self.run_button = QPushButton("▶  RUN VERIFICATION")
        self.run_button.setFont(mono_font(11, bold=True))
        self.run_button.clicked.connect(lambda: self.host.run_verification())
        layout.addWidget(self.run_button)
        self.adjust_button = QPushButton("⚙  AUTO-ADJUST")
        self.adjust_button.setFont(mono_font(10, bold=True))
        self.adjust_button.clicked.connect(
            lambda: self.host.run_auto_adjust()
        )
        layout.addWidget(self.adjust_button)
        self.graph = FitGraphView()
        layout.addWidget(self.graph)
        self.results = QPlainTextEdit()
        self.results.setFont(mono_font(10))
        self.results.setReadOnly(True)
        self.results.setPlainText("No run yet.")
        layout.addWidget(self.results, stretch=1)
        self.status_label = _status("STATUS: READY")
        layout.addWidget(self.status_label)
        self._anim_outcome = None
        self._anim_step = 0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(40)
        self._anim_timer.timeout.connect(self._anim_tick)

    def show_project(self, title: str | None) -> None:
        self.project_label.setText(f"PROJECT: {title or '—'}")
        self.graph.clear()
        self.results.setPlainText("No run yet.")
        self.status_label.setText("STATUS: READY")

    def show_message(self, text: str) -> None:
        self.graph.clear()
        self.results.setPlainText(text)
        self.status_label.setText(f"STATUS: {text}")

    def show_outcome(self, outcome) -> None:
        points = [
            (float(r[outcome.x_key]), float(r[outcome.y_key]))
            for r in outcome.teacher_rows
        ]
        self.graph.set_data(
            points,
            float(outcome.teacher_fit["slope"]),
            float(outcome.teacher_fit["intercept"]),
        )
        if motion_enabled() and self.isVisible():
            self._anim_outcome = outcome
            self._anim_step = 0
            self._anim_timer.start()
            self._render_outcome(outcome, 0.0)
        else:
            self._render_outcome(outcome, 1.0)

    def _anim_tick(self) -> None:
        self._anim_step += 1
        fraction = min(1.0, self._anim_step / 22)  # ~0.9 s sweep
        eased = 1.0 - (1.0 - fraction) ** 3
        self.graph.set_progress(eased)
        self._render_outcome(self._anim_outcome, eased)
        if fraction >= 1.0:
            self._anim_timer.stop()
            self._render_outcome(self._anim_outcome, 1.0)

    def _render_outcome(self, outcome, fraction: float) -> None:
        sim = outcome.sim_fit
        teacher = outcome.teacher_fit
        lines = [
            f"GRAPH ........ {outcome.y_key} against {outcome.x_key}"
            " — line of best fit",
            f"SLOPE ........ {sim['slope'] * fraction:.3f}",
            "",
            f"RECOVERED CONSTANT ... {sim['recovered_value'] * fraction:.3f}",
            f"FROM THE READINGS .... {teacher['recovered_value']:.3f}",
            f"EXPECTED ............. {outcome.expected_value:.3f}",
            f"DIFFERENCE ........... {outcome.offset_percent:+.2f}%"
            f"   (allowed ±{outcome.band_percent:.1f}%)",
            "",
            "VERDICT ...... "
            + ("WITHIN TOLERANCE" if outcome.passed else "OUTSIDE TOLERANCE"),
            "",
            "SHAPE CHECKS . "
            + (
                "AGAINST YOUR RECORDED DEMONSTRATION"
                if getattr(outcome, "track_basis", "simulation")
                == "demonstration"
                else "SIMULATION ONLY — IMPORT A DEMONSTRATION TO "
                "CHECK AGAINST YOUR RECORDING"
            ),
            "CHECKS",
        ]
        if getattr(outcome, "engine", "") == "rk4-ode-fallback":
            lines.append("ENGINE ....... RK4 FALLBACK (MUJOCO UNAVAILABLE)")
        findings = outcome.report.findings if outcome.report else []
        if not findings:
            lines.append("  none — all clear")
        for finding in findings:
            lines.append(f"  • {finding.check_id}: {finding.detail}")
            if finding.diagnosis:
                lines.append(f"    → {finding.diagnosis}")
        self.results.setPlainText("\n".join(lines))
        self.status_label.setText(
            "STATUS: RUN COMPLETE — "
            + ("WITHIN TOLERANCE" if outcome.passed else "OUTSIDE TOLERANCE")
        )

    def show_adjust(self, result, scale: float) -> None:
        """Append the auto-adjust outcome under the run results."""
        lines = [
            "",
            "AUTO-ADJUST",
            f"  {result.message}",
            f"  LENGTH SCALE NOW ... {scale:.4f}",
        ]
        self.results.setPlainText(
            self.results.toPlainText() + "\n" + "\n".join(lines)
        )
        self.status_label.setText(
            "STATUS: ADJUSTED — WITHIN TOLERANCE"
            if result.fixed
            else "STATUS: NOT ADJUSTED — TEACHER REVIEW NEEDED"
        )
