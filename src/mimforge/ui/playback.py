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

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..design import GantryParameters
from ..playback import DEFAULT_STEP_SECONDS, LessonPackage
from ..visuals import MachineTimeline
from .machine_view import MachineViewWidget
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

        # Stage 2: the step's voice, labelled in plain words (AI
        # voice vs teacher voice). Empty when the step has no audio
        # -- the lesson still plays, silently, with the text above.
        self.voice_label = QLabel("")
        self.voice_label.setFont(mono_font(9, bold=True))
        self.voice_label.setStyleSheet(f"color: {ACCENT};")
        self.voice_label.setWordWrap(True)
        layout.addWidget(self.voice_label)

        # Narration playback. Any failure here (no audio device, no
        # backend) leaves the player fully functional and silent --
        # audio is an enhancement, never a dependency.
        self._media: QMediaPlayer | None = None
        self._audio_out: QAudioOutput | None = None
        self._audio_dir = None  # tempfile.TemporaryDirectory
        self._audio_files: dict[int, object] = {}
        self._audio_step: int | None = None
        try:
            self._audio_out = QAudioOutput(self)
            self._media = QMediaPlayer(self)
            self._media.setAudioOutput(self._audio_out)
        except Exception:
            self._media = None
            self._audio_out = None

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

        # Stage 1: the machine itself is the primary visual; the
        # flat track view stays as the diagnostic readout under it.
        self.machine_view = MachineViewWidget()
        layout.addWidget(self.machine_view, stretch=1)
        self._machine_params = GantryParameters()
        self._step_elapsed = 0.0
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(100)
        self._sync_timer.timeout.connect(self._sync_tick)

        self.replay_view = ReplayView()
        self.replay_view.setMinimumHeight(100)
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
        self.machine_view.set_timeline(timeline)

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

    def _prepare_audio(self, lesson: LessonPackage) -> None:
        """Write each step's narration WAV to a temp folder the
        media player can stream from. Steps without audio simply
        have no file -- playback stays silent for them."""
        import tempfile
        from pathlib import Path

        if self._audio_dir is not None:
            try:
                self._audio_dir.cleanup()
            except Exception:
                pass
            self._audio_dir = None
        self._audio_files = {}
        self._audio_step = None
        if not any(step.audio and step.audio.data_b64 for step in lesson.steps):
            return
        self._audio_dir = tempfile.TemporaryDirectory(prefix="mimforge-voice-")
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
