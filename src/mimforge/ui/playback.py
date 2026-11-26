"""Lesson player panel (plan Phase 6.1).

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
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..playback import DEFAULT_STEP_SECONDS, LessonPackage
from .main_window import ACCENT, MONO_FAMILY, MUTED, TEXT, mono_font


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
    charcoal, one electric accent, mono type, mission-control plates."""

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

        layout = QVBoxLayout(self)
        title = QLabel("■ LESSON PLAYBACK")
        title.setFont(mono_font(12, bold=True))
        layout.addWidget(title)

        self.steps = QListWidget()
        self.steps.setFont(mono_font(10))
        self.steps.addItems(
            ["01  —  (no lesson loaded)", "02  —  open a project to load steps"]
        )
        self.steps.currentRowChanged.connect(self._on_step_picked)
        layout.addWidget(self.steps)

        self.step_title = QLabel("NO LESSON LOADED")
        self.step_title.setFont(mono_font(11, bold=True))
        self.step_title.setStyleSheet(f"color: {ACCENT};")
        self.step_title.setWordWrap(True)
        layout.addWidget(self.step_title)

        self.narration = QLabel("")
        self.narration.setFont(mono_font(10))
        self.narration.setStyleSheet(f"color: {TEXT};")
        self.narration.setWordWrap(True)
        layout.addWidget(self.narration)

        self.observation = QLabel("")
        self.observation.setFont(mono_font(10))
        self.observation.setStyleSheet(f"color: {MUTED};")
        self.observation.setWordWrap(True)
        layout.addWidget(self.observation)

        self.check = QLabel("")
        self.check.setFont(mono_font(10))
        self.check.setStyleSheet(f"color: {MUTED};")
        self.check.setWordWrap(True)
        layout.addWidget(self.check)

        self.replay_view = ReplayView()
        layout.addWidget(self.replay_view)

        controls = QHBoxLayout()
        self.play_button = QPushButton("▶  PLAY")
        self.pause_button = QPushButton("❚❚  PAUSE")
        self.stop_button = QPushButton("■  STOP")
        self.export_button = QPushButton("⇩  EXPORT HTML")
        for button in (
            self.play_button,
            self.pause_button,
            self.stop_button,
            self.export_button,
        ):
            button.setFont(mono_font(10, bold=True))
            controls.addWidget(button)
        self.play_button.clicked.connect(self.play)
        self.pause_button.clicked.connect(self.pause)
        self.stop_button.clicked.connect(self.stop)
        self.export_button.clicked.connect(self._on_export)
        layout.addLayout(controls)

        self.progress_label = QLabel("STEP —/—")
        self.progress_label.setFont(mono_font(10, bold=True))
        layout.addWidget(self.progress_label)

        self.status = QLabel("STATUS: IDLE — NO LESSON LOADED")
        self.status.setFont(mono_font(10, bold=True))
        self.status.setStyleSheet(f"color: {ACCENT};")
        layout.addWidget(self.status)
        layout.addStretch(1)

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

    def load_lesson(self, lesson: LessonPackage) -> None:
        lesson.validate()
        self._stop_timer()
        self._lesson = lesson
        self._index = 0
        self._playing = False
        self.steps.clear()
        for i, step in enumerate(lesson.steps):
            self.steps.addItem(f"{i + 1:02d}  —  {step.title}")
        if lesson.replay is not None:
            self.replay_view.set_replay(lesson.replay.points, lesson.replay.label)
        else:
            self.replay_view.set_replay([], "")
        self._show_step(0)
        self.status.setText(
            f"STATUS: LOADED — {lesson.step_count} STEPS — READY"
        )

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
            self._show_step(0)
        self._playing = True
        self._arm_timer()
        self.status.setText(
            f"STATUS: PLAYING — STEP {self._index + 1}/{len(self._lesson.steps)}"
        )

    def pause(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self._stop_timer()
        self.status.setText(
            f"STATUS: PAUSED — STEP {self._index + 1}/{len(self._lesson.steps)}"
        )

    def stop(self) -> None:
        self._playing = False
        self._stop_timer()
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
            self.replay_view.set_progress(1.0)
            self.status.setText("STATUS: FINISHED — LESSON COMPLETE")
            return
        self._index += 1
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

    def _arm_timer(self) -> None:
        self._timer.start(int(self.step_seconds(self._index) * 1000))

    def _stop_timer(self) -> None:
        self._timer.stop()

    def _on_step_picked(self, row: int) -> None:
        if self._lesson is None or row < 0 or row >= len(self._lesson.steps):
            return
        was_playing = self._playing
        self._playing = False
        self._stop_timer()
        self._index = row
        self._show_step(row)
        if was_playing:
            self._playing = True
            self._arm_timer()

    def _show_step(self, index: int) -> None:
        step = self._lesson.steps[index]
        self.steps.setCurrentRow(index)
        self.step_title.setText(f"{index + 1:02d} — {step.title}")
        self.narration.setText(step.narration or "(no narration)")
        self.observation.setText(
            f"EXPECTED: {step.expected_observation or '—'}"
        )
        self.check.setText(f"CHECK: {step.check_question or '—'}")
        self.progress_label.setText(
            f"STEP {index + 1:02d}/{len(self._lesson.steps):02d}"
        )
        self.replay_view.set_progress((index + 1) / len(self._lesson.steps))
