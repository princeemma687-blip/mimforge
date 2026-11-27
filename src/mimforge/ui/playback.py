"""Lesson player panel (plan Phase 6.1; Stage 4 sample re-skin).

Plays a ``LessonPackage`` step by step in the app: the step list,
the current step's narration / expected observation / check
question / safety notes, a precomputed-replay view that draws the
stored track progressively, and play / pause / stop controls. The
player never runs a model or a simulation engine -- everything it
shows was precomputed when the lesson was built, which is what
makes playback light enough for a low-spec school PC.

State machine: IDLE (no lesson) -> LOADED -> PLAYING -> PAUSED /
STOPPED / FINISHED. ``advance()`` is a public slot so tests can
drive the whole lesson without waiting on the real timer.

Stage 4 sample (plan §9, the one panel Prince reviews first):
the panel is arranged side by side, mission-control style -- the
machine view large and primary, the step list beside it, and the
readings / fitted graph / outcome as the inspector column. The
flat replay curve stays the diagnostic strip under the machine
view (Stage 1 decision). At narrow widths the three columns stack
vertically, machine first, inside a scroll area, so nothing is
ever cut off. Transport
uses the app's own vector icon set (``ui.icons``); type follows
the §4.2 audit -- mono for every measurement, readout and code
surface, a grotesque for prose. Motion on this panel is drafting
draws (the fitted-graph sweep, the step rule) that honour the
MOTION toggle on every tick; with motion reduced the panel draws
its final state immediately and stays complete and static-correct.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..design import GantryParameters
from ..playback import (
    DEFAULT_STEP_SECONDS,
    LessonGraph,
    LessonPackage,
    LessonTable,
)
from ..tempdirs import TempDir
from ..visuals import MachineTimeline
from .icons import make_icon
from .machine_view import MachineViewWidget
from .main_window import ACCENT, MUTED, TEXT, mono_font, prose_font
from .motion import motion_enabled

#: Below this panel width the three columns stack vertically
#: (machine first), instead of sitting side by side.
_NARROW_WIDTH = 900


class _StepDrawLine(QWidget):
    """The drafting rule under the current step's title.

    A dimension-line draw: an accent line sweeps out from a square
    node, with a short end tick. When motion is reduced the line
    is drawn whole immediately -- the rule is a static mark, never
    a gate on the step text, which is always shown at once.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(8)
        self._progress = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._advance)

    @property
    def draw_progress(self) -> float:
        return self._progress

    @property
    def draw_active(self) -> bool:
        return self._timer.isActive()

    def animate(self) -> None:
        """Start the draw. Reduced motion: complete at once."""
        if not motion_enabled():
            self._timer.stop()
            self._progress = 1.0
            self.update()
            return
        self._progress = 0.0
        self._timer.start()
        self.update()

    def _advance(self) -> None:
        if not motion_enabled():
            self._timer.stop()
            self._progress = 1.0
            self.update()
            return
        self._progress = min(1.0, self._progress + 0.15)
        if self._progress >= 1.0:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window().color())
        width = max(self.width(), 1)
        end = int(width * self._progress)
        pen = QPen(QColor(ACCENT))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(0, 4, max(end, 2), 4)
        painter.setBrush(QColor(ACCENT))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 2, 5, 5)
        if self._progress >= 1.0:
            painter.setPen(pen)
            painter.drawLine(width - 1, 0, width - 1, 8)


class ReadingsGraphView(QWidget):
    """The fitted graph, drawn drafting-style, as the inspector's
    diagnostic plot: grid, axis labels, measured points as cross
    marks, the fitted line sweeping in.

    The sweep is motion, not state: with motion reduced the whole
    line is drawn at once, and a motion toggle mid-sweep completes
    it on the next tick. The points, slope and intercept readouts
    are always present either way.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._graph: LessonGraph | None = None
        self._sweep = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._advance_sweep)

    @property
    def sweep_progress(self) -> float:
        return self._sweep

    @property
    def sweep_active(self) -> bool:
        return self._timer.isActive()

    @property
    def point_count(self) -> int:
        return len(self._graph.points) if self._graph is not None else 0

    def set_graph(self, graph: LessonGraph | None) -> None:
        self._graph = graph
        if graph is None or len(graph.points) < 2:
            self._timer.stop()
            self._sweep = 1.0
            self.update()
            return
        if not motion_enabled():
            self._timer.stop()
            self._sweep = 1.0
            self.update()
            return
        self._sweep = 0.0
        self._timer.start()
        self.update()

    def _advance_sweep(self) -> None:
        if not motion_enabled():
            self._timer.stop()
            self._sweep = 1.0
            self.update()
            return
        self._sweep = min(1.0, self._sweep + 0.08)
        if self._sweep >= 1.0:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101216"))
        graph = self._graph
        if graph is None or len(graph.points) < 2:
            painter.setPen(QColor(MUTED))
            painter.setFont(mono_font(9))
            painter.drawText(
                self.rect(), Qt.AlignCenter,
                "NO FITTED GRAPH IN THIS LESSON",
            )
            return
        pad_l, pad_r, pad_t, pad_b = 34, 12, 20, 22
        w = max(self.width() - pad_l - pad_r, 1)
        h = max(self.height() - pad_t - pad_b, 1)
        xs = [p[0] for p in graph.points]
        ys = [p[1] for p in graph.points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)
        # A little headroom so the topmost point never touches the edge.
        min_y -= span_y * 0.08
        max_y += span_y * 0.08
        span_y = max_y - min_y

        def px(x: float) -> float:
            return pad_l + (x - min_x) / span_x * w

        def py(y: float) -> float:
            return pad_t + (max_y - y) / span_y * h

        # Drafting grid.
        grid = QPen(QColor("#262B31"))
        grid.setWidth(1)
        painter.setPen(grid)
        for i in range(1, 4):
            gx = pad_l + w * i / 4
            painter.drawLine(int(gx), pad_t, int(gx), pad_t + h)
            gy = pad_t + h * i / 4
            painter.drawLine(pad_l, int(gy), pad_l + w, int(gy))
        # Axes.
        axis = QPen(QColor("#6b7580"))
        axis.setWidth(1)
        painter.setPen(axis)
        painter.drawLine(pad_l, pad_t + h, pad_l + w, pad_t + h)
        painter.drawLine(pad_l, pad_t, pad_l, pad_t + h)
        # Measured points as cross marks.
        mark = QPen(QColor(TEXT))
        mark.setWidth(2)
        painter.setPen(mark)
        for x, y in graph.points:
            cx, cy = int(px(x)), int(py(y))
            painter.drawLine(cx - 4, cy, cx + 4, cy)
            painter.drawLine(cx, cy - 4, cx, cy + 4)
        # Fitted line, swept in from the left.
        x0, x1 = min_x, max_x
        y0 = graph.slope * x0 + graph.intercept
        y1 = graph.slope * x1 + graph.intercept
        end_x = x0 + (x1 - x0) * self._sweep
        end_y = graph.slope * end_x + graph.intercept
        fit = QPen(QColor(ACCENT))
        fit.setWidth(2)
        painter.setPen(fit)
        painter.drawLine(int(px(x0)), int(py(y0)), int(px(end_x)), int(py(end_y)))
        # Readouts -- mono, as every measurement surface is.
        painter.setPen(QColor(MUTED))
        painter.setFont(mono_font(8))
        painter.drawText(
            pad_l, 12,
            f"SLOPE {graph.slope:.3f}  ·  INTERCEPT {graph.intercept:.3f}",
        )
        painter.drawText(
            pad_l + w - 110, pad_t + h + 16, graph.x_label,
        )
        painter.drawText(4, pad_t + 8, graph.y_label)


class ReplayView(QWidget):
    """Draws a stored replay track progressively (0.0 -> 1.0)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self._points: list[tuple[float, float, float]] = []
        self._progress = 0.0
        self._label = ""

    def set_replay(self, points, label: str = "") -> None:
        self._points = list(points)
        self._label = label
        self._progress = 0.0
        self.update()

    def set_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    @property
    def progress(self) -> float:
        return self._progress

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window().color())
        if len(self._points) < 2:
            painter.setPen(MUTED)
            painter.setFont(mono_font(10))
            painter.drawText(
                self.rect(), Qt.AlignCenter,
                "NO REPLAY TRACK IN THIS LESSON",
            )
            return
        xs = [p[1] for p in self._points]
        ys = [p[2] for p in self._points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)
        pad = 12
        w, h = max(self.width() - 2 * pad, 1), max(self.height() - 2 * pad, 1)
        scale = min(w / span_x, h / span_y)

        def px(x: float) -> float:
            return pad + (x - min_x) * scale

        def py(y: float) -> float:
            return self.height() - pad - (y - min_y) * scale

        pen = QPen()
        pen.setColor(ACCENT)
        pen.setWidth(2)
        painter.setPen(pen)
        shown = max(2, int(len(self._points) * self._progress))
        prev = self._points[0]
        for point in self._points[1:shown]:
            painter.drawLine(
                int(px(prev[1])), int(py(prev[2])),
                int(px(point[1])), int(py(point[2])),
            )
            prev = point
        last = self._points[shown - 1]
        painter.drawEllipse(int(px(last[1])) - 4, int(py(last[2])) - 4, 8, 8)
        painter.setPen(MUTED)
        painter.setFont(mono_font(9))
        painter.drawText(
            pad, 14, f"REPLAY — {self._label} — {self._progress:.0%}"
        )


class LessonPlayer(QWidget):
    """Step-by-step lesson player following the design rule: dark
    charcoal, one electric accent, mono type, mission-control plates.

    Stage 4 sample layout (side by side): the machine view is the
    large primary surface, the step list sits beside it, and the
    readings / fitted graph / outcome form the inspector column.
    Below ``_NARROW_WIDTH`` the columns stack vertically, machine
    first, so the panel stays complete at any width.
    """

    #: Emitted when the teacher asks to export the loaded lesson;
    #: the shell owns the save dialog and the file write.
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lesson: LessonPackage | None = None
        self._index = 0
        self._playing = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.advance)
        self._narrow: bool | None = None

        root = QVBoxLayout(self)
        title = QLabel("■ LESSON PLAYBACK")
        title.setFont(mono_font(12, bold=True))
        root.addWidget(title)

        # -- the three side-by-side columns ---------------------------
        # They live in a scroll area: side by side they fill the
        # panel; stacked (narrow widths) they are taller than the
        # panel, and the area scrolls instead of cutting anything off.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._main_container = QWidget()
        self._main_row = QBoxLayout(QBoxLayout.LeftToRight)
        self._main_row.setContentsMargins(0, 0, 0, 0)
        self._main_row.setSpacing(12)
        self._main_container.setLayout(self._main_row)

        # Column 1 -- the machine, primary. The flat replay curve
        # stays under it as the diagnostic strip (Stage 1 decision),
        # with the transport bar beneath that.
        machine_col = QWidget()
        machine_col.setMinimumWidth(300)
        machine_layout = QVBoxLayout(machine_col)
        machine_layout.setContentsMargins(0, 0, 0, 0)
        machine_layout.setSpacing(8)
        self.machine_view = MachineViewWidget()
        # The machine is the primary surface: its rendered frame
        # fills the view (the renderer itself may still trade
        # resolution for rate on a weak machine -- its own adaptive
        # ladder -- but the picture never sits as a small stamp in
        # a large black frame).
        self.machine_view.image_label.setScaledContents(True)
        self._last_render_size: QSize | None = None
        machine_layout.addWidget(self.machine_view, stretch=1)
        self._machine_params = GantryParameters()
        self._step_elapsed = 0.0
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(100)
        self._sync_timer.timeout.connect(self._sync_tick)
        self.replay_view = ReplayView()
        self.replay_view.setMinimumHeight(100)
        machine_layout.addWidget(self.replay_view)
        controls = QHBoxLayout()
        self.play_button = QPushButton("PLAY")
        self.play_button.setIcon(make_icon("play", 20))
        self.pause_button = QPushButton("PAUSE")
        self.pause_button.setIcon(make_icon("pause", 20))
        self.stop_button = QPushButton("STOP")
        self.stop_button.setIcon(make_icon("stop", 20))
        self.export_button = QPushButton("EXPORT HTML")
        self.export_button.setIcon(make_icon("export", 20))
        for button in (
            self.play_button,
            self.pause_button,
            self.stop_button,
            self.export_button,
        ):
            button.setFont(mono_font(10, bold=True))
            button.setIconSize(QSize(20, 20))
            controls.addWidget(button)
        self.play_button.clicked.connect(self.play)
        self.pause_button.clicked.connect(self.pause)
        self.stop_button.clicked.connect(self.stop)
        self.export_button.clicked.connect(self._on_export)
        machine_layout.addLayout(controls)
        self._main_row.addWidget(machine_col, stretch=5)

        # Column 2 -- the steps and the current step in full.
        steps_col = QWidget()
        steps_col.setMinimumWidth(200)
        steps_layout = QVBoxLayout(steps_col)
        steps_layout.setContentsMargins(0, 0, 0, 0)
        steps_layout.setSpacing(6)
        steps_heading = QLabel("STEPS")
        steps_heading.setFont(mono_font(9, bold=True))
        steps_heading.setStyleSheet(f"color: {MUTED};")
        steps_layout.addWidget(steps_heading)
        self.steps = QListWidget()
        self.steps.setFont(mono_font(10))
        self.steps.setMinimumHeight(140)
        # Long step titles wrap onto a second line instead of
        # clipping at the column edge.
        self.steps.setWordWrap(True)
        self.steps.addItems(
            ["01  —  (no lesson loaded)", "02  —  open a project to load steps"]
        )
        self.steps.currentRowChanged.connect(self._on_step_picked)
        steps_layout.addWidget(self.steps, stretch=1)
        self.step_title = QLabel("NO LESSON LOADED")
        self.step_title.setFont(prose_font(11, bold=True))
        self.step_title.setStyleSheet(f"color: {ACCENT};")
        self.step_title.setWordWrap(True)
        steps_layout.addWidget(self.step_title)
        self._draw_line = _StepDrawLine()
        steps_layout.addWidget(self._draw_line)
        self.narration = QLabel("")
        self.narration.setFont(prose_font(10))
        self.narration.setStyleSheet(f"color: {TEXT};")
        self.narration.setWordWrap(True)
        steps_layout.addWidget(self.narration)
        # Stage 2: the step's voice, labelled in plain words (AI
        # voice vs teacher voice). Empty when the step has no audio
        # -- the lesson still plays, silently, with the text above.
        self.voice_label = QLabel("")
        self.voice_label.setFont(mono_font(9, bold=True))
        self.voice_label.setStyleSheet(f"color: {ACCENT};")
        self.voice_label.setWordWrap(True)
        steps_layout.addWidget(self.voice_label)
        self.observation = QLabel("")
        self.observation.setFont(prose_font(10))
        self.observation.setStyleSheet(f"color: {MUTED};")
        self.observation.setWordWrap(True)
        steps_layout.addWidget(self.observation)
        self.check = QLabel("")
        self.check.setFont(prose_font(10))
        self.check.setStyleSheet(f"color: {MUTED};")
        self.check.setWordWrap(True)
        steps_layout.addWidget(self.check)
        steps_layout.addStretch(1)
        self._main_row.addWidget(steps_col, stretch=2)

        # Column 3 -- the inspector: readings, fitted graph, outcome.
        inspector_col = QWidget()
        inspector_col.setMinimumWidth(220)
        inspector_layout = QVBoxLayout(inspector_col)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(6)
        readings_heading = QLabel("READINGS")
        readings_heading.setFont(mono_font(9, bold=True))
        readings_heading.setStyleSheet(f"color: {MUTED};")
        inspector_layout.addWidget(readings_heading)
        self.readings_table = QTableWidget()
        self.readings_table.setFont(mono_font(9))
        self.readings_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.readings_table.setMinimumHeight(120)
        self.readings_table.verticalHeader().setVisible(False)
        inspector_layout.addWidget(self.readings_table)
        self.readings_empty = QLabel("NO READINGS IN THIS LESSON")
        self.readings_empty.setFont(mono_font(9))
        self.readings_empty.setStyleSheet(f"color: {MUTED};")
        self.readings_empty.setWordWrap(True)
        inspector_layout.addWidget(self.readings_empty)
        graph_heading = QLabel("GRAPH — FITTED LINE")
        graph_heading.setFont(mono_font(9, bold=True))
        graph_heading.setStyleSheet(f"color: {MUTED};")
        inspector_layout.addWidget(graph_heading)
        self.graph_view = ReadingsGraphView()
        inspector_layout.addWidget(self.graph_view, stretch=1)
        outcome_heading = QLabel("OUTCOME")
        outcome_heading.setFont(mono_font(9, bold=True))
        outcome_heading.setStyleSheet(f"color: {MUTED};")
        inspector_layout.addWidget(outcome_heading)
        self.outcome_label = QLabel("NO OUTCOME RECORDED")
        self.outcome_label.setFont(mono_font(10))
        self.outcome_label.setStyleSheet(f"color: {TEXT};")
        self.outcome_label.setWordWrap(True)
        inspector_layout.addWidget(self.outcome_label)
        inspector_layout.addStretch(1)
        self._main_row.addWidget(inspector_col, stretch=2)

        self._scroll.setWidget(self._main_container)
        root.addWidget(self._scroll, stretch=1)

        # -- bottom status strip: progress and state, mono readouts --
        strip = QHBoxLayout()
        self.progress_label = QLabel("STEP —/—")
        self.progress_label.setFont(mono_font(10, bold=True))
        strip.addWidget(self.progress_label)
        strip.addStretch(1)
        self.status = QLabel("STATUS: IDLE — NO LESSON LOADED")
        self.status.setFont(mono_font(10, bold=True))
        self.status.setStyleSheet(f"color: {ACCENT};")
        strip.addWidget(self.status)
        root.addLayout(strip)

        # Narration playback. Any failure here (no audio device, no
        # backend) leaves the player fully functional and silent --
        # audio is an enhancement, never a dependency.
        self._media: QMediaPlayer | None = None
        self._audio_out: QAudioOutput | None = None
        self._audio_dir = None  # tempdirs.TempDir
        self._audio_files: dict[int, object] = {}
        self._audio_step: int | None = None
        try:
            self._audio_out = QAudioOutput(self)
            self._media = QMediaPlayer(self)
            self._media.setAudioOutput(self._audio_out)
        except Exception:
            self._media = None
            self._audio_out = None

        self._set_readings(None)
        self.graph_view.set_graph(None)
        self._update_layout_direction()

    # ------------------------------------------------------------ layout

    @property
    def is_narrow_layout(self) -> bool:
        """True when the three columns are stacked vertically."""
        return bool(self._narrow)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._update_layout_direction()
        # Re-render the machine at the new size once the layout has
        # settled (a single-shot deferral, so the label's size is
        # the laid-out one). Only when the size moved materially,
        # so a drag-resize does not re-render every pixel.
        QTimer.singleShot(0, self._refresh_machine_frame)

    def _refresh_machine_frame(self) -> None:
        label = self.machine_view.image_label
        size = label.size()
        last = self._last_render_size
        if last is not None and (
            abs(size.width() - last.width()) < 32
            and abs(size.height() - last.height()) < 32
        ):
            return
        self._last_render_size = QSize(size)
        self.machine_view.render_frame_now()

    def _update_layout_direction(self) -> None:
        """Side by side at laptop widths; stacked, machine first,
        at narrow widths. The direction follows the live width, so
        a resize (or a narrow window) reflows at once."""
        narrow = self.width() < _NARROW_WIDTH
        if narrow == self._narrow:
            return
        self._narrow = narrow
        self._main_row.setDirection(
            QBoxLayout.TopToBottom if narrow else QBoxLayout.LeftToRight
        )

    # ------------------------------------------------------------ state

    @property
    def lesson(self) -> LessonPackage | None:
        return self._lesson

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def is_playing(self) -> bool:
        return self._playing

    def set_machine_params(self, params: GantryParameters) -> None:
        """The design the machine view performs with."""
        self._machine_params = params
        self.machine_view.set_params(params)

    def load_lesson(self, lesson: LessonPackage,
                    params: GantryParameters | None = None) -> None:
        lesson.validate()
        self._stop_timer()
        self._sync_timer.stop()
        self._stop_media()
        self._step_elapsed = 0.0
        self._lesson = lesson
        self._index = 0
        self._playing = False
        self._prepare_audio(lesson)
        if params is not None:
            self.set_machine_params(params)
        self.steps.clear()
        for i, step in enumerate(lesson.steps):
            self.steps.addItem(f"{i + 1:02d}  —  {step.title}")
        if lesson.replay is not None:
            self.replay_view.set_replay(lesson.replay.points, lesson.replay.label)
        else:
            self.replay_view.set_replay([], "")
        self._set_readings(lesson.table)
        self.graph_view.set_graph(lesson.graph)
        self._set_outcome(lesson.outcome_summary)
        self._load_machine_timeline(lesson)
        self._show_step(0)
        self.status.setText(
            f"STATUS: LOADED — {lesson.step_count} STEPS — READY"
        )

    def _load_machine_timeline(self, lesson: LessonPackage) -> None:
        """Feed the machine view from the lesson's replay track.

        The replay's own axis labels say which frame its points
        are in (the retargeted demonstration track is labelled in
        millimetres of carriage travel and drop; the simulation
        track is metres relative to the pivot). Any failure leaves
        the machine at rest -- a lesson never fails to load over
        its picture."""
        params = self._machine_params
        replay = lesson.replay
        try:
            if replay is None or len(replay.points) < 2:
                timeline = MachineTimeline.rest(params)
            elif replay.x_label.lower().startswith("carriage"):
                timeline = MachineTimeline.from_retarget_points(
                    replay.points, params
                )
            else:
                timeline = MachineTimeline.from_sim_track(
                    replay.points, params
                )
            if replay is not None:
                timeline.label = replay.label
        except Exception:
            timeline = MachineTimeline.rest(params)
        self._attach_action_segments(timeline, lesson)
        self.machine_view.set_timeline(timeline)

    @staticmethod
    def _attach_action_segments(timeline, lesson: LessonPackage) -> None:
        """The robot teacher's cue sheet for this lesson.

        The machine clock is the lesson clock (each step owns an
        equal share of the track), so the cue sheet is written in
        the same shares: a step's share is split equally among
        its motion primitives, each mapped to the robot action it
        calls for; a step with no primitives leaves the robot
        standing watch while the narration covers it. Lessons
        whose steps carry no primitives at all get no cue sheet
        -- the timeline's own release then governs the robot."""
        from ..visuals import robot_action_for_primitive

        steps = lesson.steps
        if not steps or not any(s.motion_primitives for s in steps):
            return
        start = timeline.start_s
        duration = timeline.duration_s
        if duration <= 0:
            return
        segments = []
        share = duration / len(steps)
        for i, step in enumerate(steps):
            step_start = start + i * share
            primitives = step.motion_primitives or ["watch"]
            sub = share / len(primitives)
            for j, primitive in enumerate(primitives):
                segments.append(
                    (
                        step_start + j * sub,
                        step_start + (j + 1) * sub,
                        robot_action_for_primitive(primitive),
                    )
                )
        timeline.action_segments = segments

    # ------------------------------------------------- machine sync

    def _sync_tick(self) -> None:
        self._step_elapsed += 0.1
        self._sync_machine()

    def _sync_machine(self) -> None:
        """The machine's clock is the lesson's clock: the track
        plays across the whole lesson, each step owning an equal
        share, so the performance and the narration never drift."""
        if self._lesson is None or not self._lesson.steps:
            return
        n = len(self._lesson.steps)
        within = min(1.0, self._step_elapsed / self.step_seconds(self._index))
        self.machine_view.seek_fraction((self._index + within) / n)

    def step_seconds(self, index: int) -> float:
        step = self._lesson.steps[index]
        if step.duration_s is not None and step.duration_s > 0:
            return step.duration_s
        return DEFAULT_STEP_SECONDS

    def play(self) -> None:
        if self._lesson is None:
            self.status.setText("STATUS: IDLE — NO LESSON LOADED")
            return
        if self._index >= len(self._lesson.steps) - 1 and not self._playing:
            # Restart from the top after a finished run.
            self._index = 0
            self._step_elapsed = 0.0
            self._show_step(0)
        self._playing = True
        self._sync_timer.start()
        self._arm_timer()
        if (
            self._media is not None
            and self._audio_step == self._index
            and self._media.playbackState() == QMediaPlayer.PausedState
        ):
            self._media.play()  # resume the paused step narration
        else:
            self._play_step_audio(self._index)
        self.status.setText(
            f"STATUS: PLAYING — STEP {self._index + 1}/{len(self._lesson.steps)}"
        )

    def pause(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self._stop_timer()
        self._sync_timer.stop()
        if self._media is not None:
            try:
                self._media.pause()
            except Exception:
                pass
        self.status.setText(
            f"STATUS: PAUSED — STEP {self._index + 1}/{len(self._lesson.steps)}"
        )

    def stop(self) -> None:
        self._playing = False
        self._stop_timer()
        self._sync_timer.stop()
        self._stop_media()
        self._step_elapsed = 0.0
        if self._lesson is None:
            self.status.setText("STATUS: IDLE — NO LESSON LOADED")
            return
        self._index = 0
        self._show_step(0)
        self.status.setText("STATUS: STOPPED — BACK TO STEP 1")

    def advance(self) -> None:
        """Move to the next step (timer slot; also the test driver)."""
        if self._lesson is None or not self._playing:
            return
        if self._index >= len(self._lesson.steps) - 1:
            self._playing = False
            self._stop_timer()
            self._sync_timer.stop()
            self._stop_media()
            self.replay_view.set_progress(1.0)
            self.machine_view.seek_fraction(1.0)
            self.status.setText("STATUS: FINISHED — LESSON COMPLETE")
            return
        self._index += 1
        self._step_elapsed = 0.0
        self._show_step(self._index)
        self._arm_timer()
        self.status.setText(
            f"STATUS: PLAYING — STEP {self._index + 1}/{len(self._lesson.steps)}"
        )

    def _on_export(self) -> None:
        if self._lesson is None:
            self.status.setText(
                "STATUS: NO LESSON LOADED — NOTHING TO EXPORT"
            )
            return
        self.export_requested.emit()

    # ---------------------------------------------------------- helpers

    def _set_readings(self, table: LessonTable | None) -> None:
        """The inspector's readings table, from the lesson's own
        table (or the plain empty state when the lesson has none)."""
        if table is None or not table.rows:
            self.readings_table.setRowCount(0)
            self.readings_table.setColumnCount(0)
            self.readings_table.setVisible(False)
            self.readings_empty.setVisible(True)
            return
        self.readings_empty.setVisible(False)
        self.readings_table.setVisible(True)
        self.readings_table.setColumnCount(len(table.columns))
        headers = []
        for column in table.columns:
            label = column.get("label", column.get("key", ""))
            unit = column.get("unit", "")
            headers.append(f"{label} ({unit})" if unit else label)
        self.readings_table.setHorizontalHeaderLabels(headers)
        self.readings_table.setRowCount(len(table.rows))
        for row_i, row in enumerate(table.rows):
            for col_i, column in enumerate(table.columns):
                value = row.get(column["key"], "")
                if isinstance(value, float):
                    text = f"{value:g}"
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                item.setFont(mono_font(9))
                self.readings_table.setItem(row_i, col_i, item)
        header = self.readings_table.horizontalHeader()
        # Columns size to their content and the table scrolls
        # sideways when needed -- seven columns squeezed to fit
        # would clip every header to unreadable fragments.
        header.setSectionResizeMode(QHeaderView.ResizeToContents)

    def _set_outcome(self, outcome: dict | None) -> None:
        """The inspector's outcome readout, from the lesson's own
        outcome summary (or the plain empty state)."""
        if not outcome:
            self.outcome_label.setText("NO OUTCOME RECORDED")
            return
        lines = []
        for key, value in outcome.items():
            label = str(key).replace("_", " ").upper()
            lines.append(f"{label}: {value}")
        self.outcome_label.setText("\n".join(lines))

    def _arm_timer(self) -> None:
        self._timer.start(int(self.step_seconds(self._index) * 1000))

    def _stop_timer(self) -> None:
        self._timer.stop()

    def _on_step_picked(self, row: int) -> None:
        if self._lesson is None or row < 0 or row >= len(self._lesson.steps):
            return
        was_playing = self._playing
        self._stop_timer()
        if not was_playing:
            self._stop_media()
        self._step_elapsed = 0.0
        self._index = row
        self._playing = was_playing
        self._show_step(row)
        if was_playing:
            self._sync_timer.start()
            self._arm_timer()

    # ------------------------------------------------------ narration audio

    def _release_audio(self) -> None:
        """Stop the narration player and let go of its files BEFORE
        their folder is removed. On Windows a WAV the media backend
        still holds cannot be deleted (WinError 32 -- CI run
        45991918059, where the removal raised out of tempfile's
        exit-time cleanup): stop, clear the source, release the
        audio output, and only then remove the folder, through a
        cleanup that retries briefly and can never raise. The
        audio output is re-attached on the next play."""
        self._stop_media()
        if self._media is not None:
            try:
                self._media.setSource(QUrl())
            except Exception:
                pass
            try:
                self._media.setAudioOutput(None)
            except Exception:
                pass
        if self._audio_dir is not None:
            self._audio_dir.cleanup()
            self._audio_dir = None
        self._audio_files = {}
        self._audio_step = None

    def _prepare_audio(self, lesson: LessonPackage) -> None:
        """Write each step's narration WAV to a temp folder the
        media player can stream from. Steps without audio simply
        have no file -- playback stays silent for them."""
        from pathlib import Path

        self._release_audio()
        if not any(step.audio and step.audio.data_b64 for step in lesson.steps):
            return
        self._audio_dir = TempDir(prefix="mimforge-voice-")
        root = Path(self._audio_dir.name)
        for index, step in enumerate(lesson.steps):
            if step.audio and step.audio.data_b64:
                try:
                    target = root / f"step-{index + 1:02d}.wav"
                    target.write_bytes(step.audio.wav_bytes())
                    self._audio_files[index] = target
                except Exception:
                    continue

    def _play_step_audio(self, index: int) -> None:
        if self._media is None:
            return
        target = self._audio_files.get(index)
        try:
            if target is None:
                self._media.stop()
                self._audio_step = None
                return
            if (
                self._audio_out is not None
                and self._media.audioOutput() is not self._audio_out
            ):
                self._media.setAudioOutput(self._audio_out)
            self._media.setSource(QUrl.fromLocalFile(str(target)))
            self._media.play()
            self._audio_step = index
        except Exception:
            self._audio_step = None

    def _stop_media(self) -> None:
        if self._media is not None:
            try:
                self._media.stop()
            except Exception:
                pass
        self._audio_step = None

    def _show_step(self, index: int) -> None:
        step = self._lesson.steps[index]
        self.steps.setCurrentRow(index)
        self.step_title.setText(f"{index + 1:02d} — {step.title}")
        self._draw_line.animate()
        self.narration.setText(step.narration or "(no narration)")
        self.voice_label.setText(step.audio.label if step.audio else "")
        self.observation.setText(
            f"EXPECTED: {step.expected_observation or '—'}"
        )
        self.check.setText(f"CHECK: {step.check_question or '—'}")
        self.progress_label.setText(
            f"STEP {index + 1:02d}/{len(self._lesson.steps):02d}"
        )
        self.replay_view.set_progress((index + 1) / len(self._lesson.steps))
        self._sync_machine()
        if self._playing:
            self._play_step_audio(index)
