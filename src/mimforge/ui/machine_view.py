"""MachineView widget (next-stage plan, Stage 1): the living machine.

Presents the designed machine performing, as the primary visual of
the Playback and Simulate surfaces. The preferred renderer is the
MuJoCo render model from ``mimforge.visuals`` -- real geometry
from the same parameters as the CAD, posed kinematically by the
performance timeline (simulation track, or the retargeted
demonstration track, labelled as what it is).

If rendering is unavailable on the machine (driver, headless box,
frozen bundle), the widget falls back automatically to a 2.5D
canvas performance view with a plain status line -- never a crash,
never a blank panel. An INTERNALS view shows the design's parts
separated and labelled (drawn from the CAD part set's placements),
in both modes.

Transport is explicit (play / pause / stop / seek) so the owning
panels drive it; nothing auto-plays here except when the owner
asks. Frame pacing is adaptive: render resolution steps down if
measured frame times say the machine cannot hold the rate, and
the measured cost is shown in the footer -- reported, not hidden.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..design import GantryParameters
from ..visuals import (
    MachineRenderer,
    MachineState,
    MachineTimeline,
    part_layout,
    renderer_available,
)
from .main_window import ACCENT, MUTED, TEXT, mono_font

_PAGE_RENDER, _PAGE_CANVAS, _PAGE_INTERNALS = 0, 1, 2
_SCALE_STEPS = (1.0, 0.8, 0.66, 0.5)
_MAX_W, _MAX_H = 960, 720


# ------------------------------------------------------------------ canvas


class _ProjectionView(QWidget):
    """The 2.5D canvas performance view (the fallback renderer).

    Draws the machine from one state's geometry in a chosen
    projection: front (span x height), side (depth x height --
    the swing runs across the page in front view; here the load's
    height is exact and its swing is foreshortened, which the
    caption says), or top (span x depth, the load tracing its
    line on the bench plan)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._state: MachineState | None = None
        self._params = GantryParameters()
        self._projection = "front"
        self._caption = ""

    def set_scene(self, state: MachineState, params: GantryParameters,
                  projection: str, caption: str = "") -> None:
        self._state = state
        self._params = params
        self._projection = projection
        self._caption = caption
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101216"))
        p = self._params
        state = self._state
        if state is None:
            painter.setPen(QColor(MUTED))
            painter.setFont(mono_font(10))
            painter.drawText(self.rect(), Qt.AlignCenter, "NO MACHINE LOADED")
            return
        pad = 26
        w = max(self.width() - 2 * pad, 1)
        h = max(self.height() - 2 * pad - 14, 1)
        # World extents per projection, metres: (horizontal, vertical).
        if self._projection == "top":
            ext_x = (p.span_mm / 1000.0) * 1.25
            ext_y = (p.base_depth_mm / 1000.0) * 2.2
        else:
            ext_x = (p.span_mm / 1000.0) * 1.25
            ext_y = (p.height_mm / 1000.0) * 1.18
        scale = min(w / ext_x, h / ext_y)
        ox = pad + (w - ext_x * scale) / 2
        oy = pad + (h - ext_y * scale) / 2

        def px(x_m: float) -> float:
            return ox + (x_m + ext_x / 2) * scale

        def py(v_m: float) -> float:
            # front/side: v is height (z), 0 at the bench.
            # top: v is depth (y), running down the page.
            if self._projection == "top":
                return oy + (v_m + ext_y / 2) * scale
            return oy + (ext_y - v_m) * scale

        steel = QPen(QColor("#6b7580"))
        steel.setWidth(3)
        accent = QPen(QColor(ACCENT))
        accent.setWidth(2)
        thin = QPen(QColor("#9aa3ab"))
        thin.setWidth(1)
        s = p.section_mm / 1000.0
        half_span = p.span_mm / 2000.0
        ux = half_span - s / 2
        height = p.height_mm / 1000.0

        if self._projection == "top":
            painter.setPen(steel)
            painter.drawRect(int(px(-half_span)), int(py(-p.base_depth_mm / 2000.0)),
                             int(p.span_mm / 1000.0 * scale), int(p.base_depth_mm / 1000.0 * scale))
            painter.setPen(accent)
            painter.drawEllipse(int(px(state.mass_x_m)) - 5, int(py(0.0)) - 5, 10, 10)
            painter.setPen(thin)
            painter.drawLine(int(px(state.carriage_x_m)), int(py(-0.05)),
                             int(px(state.carriage_x_m)), int(py(0.05)))
        else:
            # Bench line.
            painter.setPen(steel)
            painter.drawLine(int(px(-ext_x / 2 + 0.05)), int(py(0.0)),
                             int(px(ext_x / 2 - 0.05)), int(py(0.0)))
            # Uprights + beam (side view: the two uprights coincide).
            xs = (-ux, ux) if self._projection == "front" else (0.0,)
            for x in xs:
                painter.drawRect(int(px(x - s / 2)), int(py(height)),
                                 max(int(s * scale), 2), int(height * scale))
            painter.drawRect(int(px(-half_span)), int(py(height + s)),
                             int(p.span_mm / 1000.0 * scale), max(int(s * scale), 2))
            # Carriage + gate.
            cw = p.carriage_width_mm / 1000.0
            ch = p.carriage_height_mm / 1000.0
            cx = state.carriage_x_m if self._projection == "front" else 0.0
            painter.setPen(QPen(QColor("#0094a8")))
            painter.drawRect(int(px(cx - cw / 2)), int(py(height)),
                             int(cw * scale), int(ch * scale))
            gate_x = cx + 0.045 * state.gate_open
            painter.setPen(QPen(QColor("#d94d33")))
            painter.drawRect(int(px(gate_x - 0.015)), int(py(height - ch - 0.045)),
                             max(int(0.03 * scale), 2), max(int(0.02 * scale), 2))
            # Suspension line + load.
            painter.setPen(thin)
            painter.drawLine(int(px(cx)), int(py(height)),
                             int(px(state.mass_x_m)), int(py(state.mass_z_m)))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(ACCENT))
            painter.drawEllipse(int(px(state.mass_x_m)) - 6,
                                int(py(state.mass_z_m)) - 6, 12, 12)
        painter.setPen(QColor(MUTED))
        painter.setFont(mono_font(8))
        caption = self._caption or {
            "front": "FRONT — SPAN × HEIGHT",
            "side": "SIDE — DEPTH × HEIGHT (SWING FORESHORTENED)",
            "top": "TOP — SPAN × DEPTH",
        }[self._projection]
        painter.drawText(8, self.height() - 4, caption)


class InternalsView(QWidget):
    """The machine taken apart: every designed part separated and
    labelled, drawn from the CAD part set's placements."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._params = GantryParameters()

    def set_params(self, params: GantryParameters) -> None:
        self._params = params
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101216"))
        parts = part_layout(self._params)
        pad = 20
        label_w = 190
        w = max(self.width() - 2 * pad - label_w, 1)
        h = max(self.height() - 2 * pad, 1)
        xs = [pl.exploded_center_mm[0] for pl in parts]
        zs = [pl.exploded_center_mm[2] for pl in parts]
        sx = [pl.size_mm[0] for pl in parts]
        sz = [pl.size_mm[2] for pl in parts]
        min_x = min(x - s / 2 for x, s in zip(xs, sx)) - 40
        max_x = max(x + s / 2 for x, s in zip(xs, sx)) + 40
        min_z = min(z - s / 2 for z, s in zip(zs, sz)) - 40
        max_z = max(z + s / 2 for z, s in zip(zs, sz)) + 40
        scale = min(w / (max_x - min_x), h / (max_z - min_z))

        def px(x: float) -> float:
            return pad + (x - min_x) * scale

        def py(z: float) -> float:
            return self.height() - pad - (z - min_z) * scale

        colours = ["#6b7580", "#7d8791", "#0094a8", "#8a929a", "#8a929a",
                   "#00b3c8", "#bf993f", "#d94d33", "#9aa3ab"]
        painter.setFont(mono_font(8))
        for i, pl in enumerate(parts):
            cx, _cy, cz = pl.exploded_center_mm
            sw, _sd, sh = pl.size_mm
            x0, y0 = px(cx - sw / 2), py(cz + sh / 2)
            painter.setPen(QPen(QColor(colours[i % len(colours)])))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(int(x0), int(y0),
                             max(int(sw * scale), 2), max(int(sh * scale), 2))
            painter.setPen(QColor(TEXT))
            painter.drawText(int(px(max_x)) + 8, int(py(cz)) + 3,
                             f"{i + 1:02d} {pl.name.upper()}")
        painter.setPen(QColor(MUTED))
        painter.drawText(8, 14, "INTERNALS — PARTS SEPARATED, AS DESIGNED")


# ------------------------------------------------------------------ widget


class MachineViewWidget(QWidget):
    """The living-machine surface: renderer first, canvas fallback,
    internals always available. See the module docstring."""

    time_changed = Signal(float)
    finished = Signal()

    def __init__(self, parent: QWidget | None = None, *,
                 force_fallback: bool = False) -> None:
        super().__init__(parent)
        self._params = GantryParameters()
        self._timeline: MachineTimeline = MachineTimeline.rest(self._params)
        self._time = self._timeline.start_s
        self._playing = False
        self._view = "front"
        self._force_fallback = force_fallback
        self._renderer: MachineRenderer | None = None
        self._renderer_failed = False
        self._scale_index = 0
        self._frame_ema_ms: float | None = None
        self._good_ticks = 0
        self._clock = QTimer(self)
        self._clock.setInterval(33)
        self._clock.timeout.connect(self._tick)
        self._last_tick_at: float | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("■ MACHINE — LIVE VIEW")
        title.setFont(mono_font(11, bold=True))
        header.addWidget(title)
        self.mode_label = QLabel("")
        self.mode_label.setFont(mono_font(9, bold=True))
        self.mode_label.setStyleSheet(f"color: {ACCENT};")
        header.addWidget(self.mode_label)
        header.addStretch(1)
        layout.addLayout(header)

        views = QHBoxLayout()
        self.view_buttons: dict[str, QPushButton] = {}
        for key, text in (("front", "FRONT"), ("side", "SIDE"),
                          ("top", "TOP"), ("internals", "INTERNALS")):
            button = QPushButton(text)
            button.setFont(mono_font(9, bold=True))
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self.set_view(k))
            self.view_buttons[key] = button
            views.addWidget(button)
        views.addStretch(1)
        layout.addLayout(views)
        self.view_buttons["front"].setChecked(True)

        self.pages = QStackedLayout()
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(220)
        self.image_label.setStyleSheet("background: #101216;")
        self.canvas = _ProjectionView()
        self.internals = InternalsView()
        self.pages.addWidget(self.image_label)
        self.pages.addWidget(self.canvas)
        self.pages.addWidget(self.internals)
        layout.addLayout(self.pages, stretch=1)

        footer = QHBoxLayout()
        self.track_label = QLabel("")
        self.track_label.setFont(mono_font(9))
        self.track_label.setStyleSheet(f"color: {TEXT};")
        footer.addWidget(self.track_label)
        footer.addStretch(1)
        self.time_label = QLabel("T 0.0 / 0.0 S")
        self.time_label.setFont(mono_font(9, bold=True))
        footer.addWidget(self.time_label)
        layout.addLayout(footer)
        self._refresh_mode_label()
        self.render_frame_now()

    # ------------------------------------------------------------ state

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def current_time(self) -> float:
        return self._time

    @property
    def current_view(self) -> str:
        return self._view

    @property
    def using_fallback(self) -> bool:
        return self._force_fallback or self._renderer_failed \
            or not renderer_available()

    @property
    def timeline(self) -> MachineTimeline:
        return self._timeline

    @property
    def render_scale(self) -> float:
        return _SCALE_STEPS[self._scale_index]

    @property
    def last_frame_ms(self) -> float | None:
        return self._frame_ema_ms

    # ------------------------------------------------------------ input

    def set_params(self, params: GantryParameters) -> None:
        self._params = params
        self._renderer = None  # rebuilt for the new design on demand
        self.internals.set_params(params)
        if self._timeline.label.startswith("AT REST"):
            self._timeline = MachineTimeline.rest(params)
            self._time = self._timeline.start_s
        self.render_frame_now()

    def set_timeline(self, timeline: MachineTimeline, label: str = "") -> None:
        self._timeline = timeline
        if label:
            self._timeline.label = label
        self._time = timeline.start_s
        self._playing = False
        self._clock.stop()
        self.track_label.setText(self._timeline.label)
        self.render_frame_now()

    def set_view(self, view: str) -> None:
        if view not in ("front", "side", "top", "internals"):
            raise ValueError(f"unknown machine view {view!r}")
        self._view = view
        for key, button in self.view_buttons.items():
            button.setChecked(key == view)
        self.render_frame_now()

    # ---------------------------------------------------------- transport

    def play(self) -> None:
        if self._time >= self._timeline.start_s + self._timeline.duration_s:
            self._time = self._timeline.start_s
        self._playing = True
        self._last_tick_at = None
        self._clock.start()
        self.render_frame_now()

    def pause(self) -> None:
        self._playing = False
        self._clock.stop()
        self.render_frame_now()

    def stop(self) -> None:
        self._playing = False
        self._clock.stop()
        self._time = self._timeline.start_s
        self.render_frame_now()

    def seek_time(self, t_s: float) -> None:
        start = self._timeline.start_s
        self._time = min(max(float(t_s), start), start + self._timeline.duration_s)
        self.render_frame_now()

    def seek_fraction(self, fraction: float) -> None:
        frac = min(1.0, max(0.0, float(fraction)))
        self.seek_time(self._timeline.start_s + frac * self._timeline.duration_s)

    def advance_time(self, dt_s: float) -> None:
        """Move the performance clock by hand (the test driver;
        the timer calls the same path with real elapsed time)."""
        if not self._playing:
            return
        self._time += max(0.0, float(dt_s))
        end = self._timeline.start_s + self._timeline.duration_s
        if self._time >= end:
            self._time = end
            self._playing = False
            self._clock.stop()
            self.render_frame_now()
            self.finished.emit()
            return
        self.time_changed.emit(self._time)
        self.render_frame_now()

    def _tick(self) -> None:
        now = time.monotonic()
        if self._last_tick_at is None:
            self._last_tick_at = now
            return
        dt = now - self._last_tick_at
        self._last_tick_at = now
        self.advance_time(min(dt, 0.25))

    # ----------------------------------------------------------- render

    def _refresh_mode_label(self) -> None:
        if self.using_fallback:
            self.mode_label.setText("2D FALLBACK — 3D NOT AVAILABLE HERE")
        else:
            self.mode_label.setText("3D — RENDERED FROM THE DESIGN")

    def _ensure_renderer(self) -> MachineRenderer | None:
        if self.using_fallback:
            return None
        if self._renderer is None:
            try:
                w, h = self._render_size()
                self._renderer = MachineRenderer(
                    self._params, width=w, height=h
                )
            except Exception:
                self._renderer_failed = True
                self._refresh_mode_label()
                return None
        return self._renderer

    def _render_size(self) -> tuple[int, int]:
        w = max(self.image_label.width(), 320)
        h = max(self.image_label.height(), 240)
        scale = _SCALE_STEPS[self._scale_index]
        w = int(min(_MAX_W, w) * scale)
        h = int(min(_MAX_H, h) * scale)
        return max(w // 32 * 32, 160), max(h // 32 * 32, 120)

    def render_frame_now(self) -> None:
        """Draw the current state once, in the current view/mode."""
        state = self._timeline.state_at(self._time)
        self.time_label.setText(
            f"T {self._time - self._timeline.start_s:.1f} / "
            f"{self._timeline.duration_s:.1f} S"
        )
        self.track_label.setText(self._timeline.label)
        if self._view == "internals":
            self.internals.set_params(self._params)
            self.pages.setCurrentIndex(_PAGE_INTERNALS)
            return
        renderer = self._ensure_renderer()
        if renderer is None:
            self.canvas.set_scene(state, self._params, self._view)
            self.pages.setCurrentIndex(_PAGE_CANVAS)
            return
        try:
            want = self._render_size()
            if (renderer.width, renderer.height) != want:
                self._renderer = MachineRenderer(
                    self._params, width=want[0], height=want[1]
                )
                renderer = self._renderer
            frame = renderer.render(state, self._view)
        except Exception:
            self._renderer_failed = True
            self._renderer = None
            self._refresh_mode_label()
            self.canvas.set_scene(state, self._params, self._view)
            self.pages.setCurrentIndex(_PAGE_CANVAS)
            return
        self._adapt_scale(renderer.last_frame_ms)
        image = QImage(
            frame.data, frame.shape[1], frame.shape[0],
            3 * frame.shape[1], QImage.Format_RGB888,
        ).copy()
        self.image_label.setPixmap(QPixmap.fromImage(image))
        self.pages.setCurrentIndex(_PAGE_RENDER)

    def _adapt_scale(self, frame_ms: float) -> None:
        """Adaptive pacing: step the render resolution down when
        measured frames cannot hold the rate; step back up only
        after a sustained run of cheap frames."""
        if self._frame_ema_ms is None:
            self._frame_ema_ms = frame_ms
        else:
            self._frame_ema_ms = 0.8 * self._frame_ema_ms + 0.2 * frame_ms
        if self._frame_ema_ms > 30.0 and self._scale_index < len(_SCALE_STEPS) - 1:
            self._scale_index += 1
            self._renderer = None
            self._good_ticks = 0
        elif self._frame_ema_ms < 10.0 and self._scale_index > 0:
            self._good_ticks += 1
            if self._good_ticks >= 60:
                self._scale_index -= 1
                self._renderer = None
                self._good_ticks = 0
        else:
            self._good_ticks = 0
