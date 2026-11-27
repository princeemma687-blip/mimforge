"""BUILD IT player (next-stage plan, Stage 3): the machine couples
together part by part, BILT-style, from the generated assembly
sequence (``mimforge.assembly``).

One step fits one part: parts already fitted stand solid, the
current part travels its approach path into place (ghost outline
at its destination, fasteners flashing as it lands), parts still
to come are absent. The step card carries the exact BOM lines and
prices for the selected tier -- a tier switch re-prices every
card -- and the step's narration (Stage 2 speech layer) plays as
the part lands. Transport mirrors the lesson player, so the two
modes feel like one product.

Motion rule, as everywhere: with motion reduced the current part
is simply shown in place -- the end state is identical, nothing
animated gates anything. ``advance()`` is a public driver so
tests walk the whole build without waiting on the timer.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..assembly import AssemblyPlan
from ..visuals import part_layout
from .icons import make_icon
from .main_window import ACCENT, MUTED, TEXT, mono_font
from .motion import motion_enabled

_FIELD = "#101216"
_STEEL = "#6b7580"
_GHOST = "#4A5158"

#: How far (in design millimetres) a part starts from its seat
#: when it travels in. A fixed drafting distance, scaled by the
#: view like everything else.
_TRAVEL_MM = 300.0
_ANIM_S = 1.1  # seconds for one part to travel in


def _approach_offset(approach: str, center_x: float) -> tuple[float, float]:
    """The (dx, dz) a part starts displaced by, in mm, for one
    approach key: lowered from above, risen from below, slid in
    along the beam from the left, offered in from its own side."""
    if approach == "lower":
        return (0.0, _TRAVEL_MM)
    if approach == "rise":
        return (0.0, -_TRAVEL_MM)
    if approach == "slide":
        return (-_TRAVEL_MM, 0.0)
    if approach == "side":
        return (_TRAVEL_MM if center_x >= 0 else -_TRAVEL_MM, 0.0)
    return (0.0, _TRAVEL_MM)


class AssemblyCanvas(QWidget):
    """The coupling drawing: front elevation of the design's
    parts, in their assembly states for the current step."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(260)
        self._plan: AssemblyPlan | None = None
        self._index = 0
        self._progress = 1.0

    def set_scene(
        self, plan: AssemblyPlan | None, index: int, progress: float
    ) -> None:
        self._plan = plan
        self._index = index
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    @property
    def progress(self) -> float:
        return self._progress

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(_FIELD))
        plan = self._plan
        if plan is None or not plan.steps:
            painter.setPen(QColor(MUTED))
            painter.setFont(mono_font(10))
            painter.drawText(
                self.rect(), Qt.AlignCenter, "NO ASSEMBLY LOADED"
            )
            return
        parts = {pl.part_id: pl for pl in part_layout(plan.params)}
        pad = 26
        span = plan.params.span_mm
        height = plan.params.height_mm + plan.params.section_mm
        # The world is wide enough for the robot teacher at its
        # station: it stands by the build, watching the coupling
        # it will later perform.
        from ..visuals import robot_layout, robot_state_default

        robot = robot_layout(plan.params)
        world_half_mm = max(span * 0.65, robot.station_x_m * 1000.0 + 130.0)
        scale = min(
            (self.width() - 2 * pad) / (2 * world_half_mm),
            (self.height() - 2 * pad) / (height * 1.25),
        )

        def px(x_mm: float) -> float:
            return self.width() / 2 + x_mm * scale

        def py(z_mm: float) -> float:
            return self.height() - pad - z_mm * scale

        # Bench line.
        painter.setPen(QPen(QColor(_STEEL), 2))
        painter.drawLine(pad // 2, int(py(0)), self.width() - pad // 2, int(py(0)))
        current_id = plan.steps[self._index].part_id
        eased = 1.0 - (1.0 - self._progress) ** 3
        for i, step in enumerate(plan.steps):
            pl = parts.get(step.part_id)
            if pl is None:
                continue
            cx, _cy, cz = pl.center_mm
            sw, _sd, sh = pl.size_mm
            if i < self._index:
                self._draw_part(painter, px, py, scale, cx, cz, sw, sh, _STEEL, 2)
            elif i == self._index:
                # Ghost at the destination, then the part itself
                # travelling in along its approach.
                ghost = QPen(QColor(_GHOST), 1)
                ghost.setStyle(Qt.DashLine)
                painter.setPen(ghost)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(
                    int(px(cx - sw / 2)), int(py(cz + sh / 2)),
                    max(int(sw * scale), 2), max(int(sh * scale), 2),
                )
                dx, dz = _approach_offset(step.approach, cx)
                here_x = cx + dx * (1.0 - eased)
                here_z = cz + dz * (1.0 - eased)
                self._draw_part(
                    painter, px, py, scale, here_x, here_z, sw, sh, ACCENT, 2
                )
                if self._progress >= 1.0:
                    self._draw_fasteners(painter, px, py, cx, cz, sw, sh)
            # Future parts are absent: the machine is not built yet.
        from .machine_view import draw_robot_figure

        def robot_px(v_m: float) -> float:
            return self.width() / 2 + v_m * 1000.0 * scale

        def robot_py(v_m: float) -> float:
            return self.height() - pad - v_m * 1000.0 * scale

        draw_robot_figure(
            painter, robot, robot_state_default(plan.params),
            "front", robot_px, robot_py,
        )
        painter.setPen(QColor(MUTED))
        painter.setFont(mono_font(8))
        painter.drawText(
            8, self.height() - 4,
            f"COUPLING — STEP {self._index + 1} OF {len(plan.steps)} · "
            f"{current_id.replace('_', ' ').upper()}",
        )

    @staticmethod
    def _draw_part(painter, px, py, scale, cx, cz, sw, sh, colour, width) -> None:
        painter.setPen(QPen(QColor(colour), width))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(
            int(px(cx - sw / 2)), int(py(cz + sh / 2)),
            max(int(sw * scale), 2), max(int(sh * scale), 2),
        )

    @staticmethod
    def _draw_fasteners(painter, px, py, cx, cz, sw, sh) -> None:
        """The fasten flash: small accent crosses at the part's
        corners once it has landed."""
        painter.setPen(QPen(QColor(ACCENT), 2))
        for fx in (cx - sw / 2 + 6, cx + sw / 2 - 6):
            for fz in (cz - sh / 2 + 6, cz + sh / 2 - 6):
                x, y = px(fx), py(fz)
                painter.drawLine(int(x) - 4, int(y), int(x) + 4, int(y))
                painter.drawLine(int(x), int(y) - 4, int(x), int(y) + 4)


class AssemblyPlayer(QWidget):
    """The BUILD IT surface: step list, coupling canvas, parts
    card, transport, narration. Holds no engine logic of its own
    beyond presentation -- the sequence arrives as an
    :class:`AssemblyPlan` from the host."""

    def __init__(self, host=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._plan: AssemblyPlan | None = None
        self._index = 0
        self._progress = 1.0
        self._animating = False
        self._playing = False
        self._paused = False
        self._hold_elapsed = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("■ BUILD IT — STEP-BY-STEP COUPLING")
        title.setFont(mono_font(12, bold=True))
        header.addWidget(title)
        header.addStretch(1)
        self.back_button = QPushButton("◀  BACK TO DESIGN")
        self.back_button.setFont(mono_font(10, bold=True))
        self.back_button.setIcon(make_icon("back", 18))
        self.back_button.setIconSize(QSize(18, 18))
        self.back_button.clicked.connect(self._on_back)
        header.addWidget(self.back_button)
        layout.addLayout(header)

        self.canvas = AssemblyCanvas()
        layout.addWidget(self.canvas, stretch=1)

        self.steps_list = QListWidget()
        self.steps_list.setFont(mono_font(10))
        self.steps_list.setMaximumHeight(150)
        self.steps_list.currentRowChanged.connect(self._on_step_picked)
        layout.addWidget(self.steps_list)

        self.card_title = QLabel("NO ASSEMBLY LOADED")
        self.card_title.setFont(mono_font(11, bold=True))
        self.card_title.setStyleSheet(f"color: {ACCENT};")
        self.card_title.setWordWrap(True)
        layout.addWidget(self.card_title)
        self.card = QLabel("")
        self.card.setFont(mono_font(10))
        self.card.setStyleSheet(f"color: {TEXT};")
        self.card.setWordWrap(True)
        layout.addWidget(self.card)
        self.voice_label = QLabel("")
        self.voice_label.setFont(mono_font(9, bold=True))
        self.voice_label.setStyleSheet(f"color: {ACCENT};")
        layout.addWidget(self.voice_label)

        # Narration playback, silent-safe like the lesson player:
        # no audio device or backend simply means no voice.
        self._media: QMediaPlayer | None = None
        self._audio_out: QAudioOutput | None = None
        self._audio_dir = None
        self._audio_files: dict[int, object] = {}
        try:
            self._audio_out = QAudioOutput(self)
            self._media = QMediaPlayer(self)
            self._media.setAudioOutput(self._audio_out)
        except Exception:
            self._media = None
            self._audio_out = None

        controls = QHBoxLayout()
        self.prev_button = QPushButton("◀  PREV")
        self.play_button = QPushButton("▶  PLAY")
        self.pause_button = QPushButton("❚❚  PAUSE")
        self.next_button = QPushButton("NEXT  ▶")
        self.reset_button = QPushButton("■  RESET")
        for button, icon_name in (
            (self.prev_button, "prev"),
            (self.play_button, "play"),
            (self.pause_button, "pause"),
            (self.next_button, "next"),
            (self.reset_button, "reset"),
        ):
            button.setFont(mono_font(10, bold=True))
            button.setIcon(make_icon(icon_name, 18))
            button.setIconSize(QSize(18, 18))
            controls.addWidget(button)
        self.prev_button.clicked.connect(self.prev_step)
        self.play_button.clicked.connect(self.play)
        self.pause_button.clicked.connect(self.pause)
        self.next_button.clicked.connect(self.next_step)
        self.reset_button.clicked.connect(self.stop)
        layout.addLayout(controls)

        self.status_label = QLabel("STATUS: NO ASSEMBLY LOADED")
        self.status_label.setFont(mono_font(10, bold=True))
        self.status_label.setStyleSheet(f"color: {ACCENT};")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    # ------------------------------------------------------------ state

    @property
    def plan(self) -> AssemblyPlan | None:
        return self._plan

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def is_playing(self) -> bool:
        return self._playing

    # ------------------------------------------------------------- input

    def set_plan(self, plan: AssemblyPlan) -> None:
        self._stop_media()
        self._timer.stop()
        self._plan = plan
        self._index = 0
        self._playing = False
        self._paused = False
        self._prepare_audio(plan)
        self.steps_list.blockSignals(True)
        self.steps_list.clear()
        for step in plan.steps:
            self.steps_list.addItem(
                f"{step.index:02d}  —  {step.part_name}"
            )
        self.steps_list.blockSignals(False)
        self._begin_step(0, animate=False)
        self.status_label.setText(
            f"STATUS: READY — {len(plan.steps)} STEPS — "
            f"TIER {plan.tier.upper()} — BUILD TOTAL ₦{plan.total_ngn:,.0f}"
        )

    def _begin_step(self, index: int, *, animate: bool) -> None:
        if self._plan is None:
            return
        self._index = max(0, min(index, len(self._plan.steps) - 1))
        self._hold_elapsed = 0.0
        if animate and motion_enabled():
            self._progress = 0.0
            self._animating = True
        else:
            self._progress = 1.0
            self._animating = False
        self.steps_list.blockSignals(True)
        self.steps_list.setCurrentRow(self._index)
        self.steps_list.blockSignals(False)
        self._refresh()
        self._timer.start()

    def _refresh(self) -> None:
        plan = self._plan
        if plan is None:
            return
        step = plan.steps[self._index]
        self.canvas.set_scene(plan, self._index, self._progress)
        self.card_title.setText(
            f"STEP {step.index:02d}/{step.total:02d} — {step.part_name.upper()}"
        )
        self.card.setText(
            step.text
            + f"\nMaterials this step: ₦{step.lines_total_ngn:,.0f} · "
            f"build total ({plan.tier}): ₦{plan.total_ngn:,.0f}"
        )
        self.voice_label.setText(
            step.audio.label if getattr(step, "audio", None) else ""
        )
        if (
            self._index == len(plan.steps) - 1
            and self._progress >= 1.0
            and not self._animating
        ):
            self.status_label.setText(
                "STATUS: COUPLED — THE MACHINE IS BUILT"
            )
        else:
            self.status_label.setText(
                f"STATUS: STEP {step.index} OF {step.total} — "
                f"{step.part_name.upper()}"
            )

    # ---------------------------------------------------------- transport

    def play(self) -> None:
        if self._plan is None:
            return
        if (
            self._index >= len(self._plan.steps) - 1
            and self._progress >= 1.0
            and not self._animating
        ):
            self._begin_step(0, animate=True)  # build it again
        self._playing = True
        self._paused = False
        if self._progress < 1.0:
            self._animating = True
        self._play_step_audio(self._index)
        self._timer.start()
        self._refresh()

    def pause(self) -> None:
        self._paused = True
        self._playing = False
        if self._media is not None:
            try:
                self._media.pause()
            except Exception:
                pass
        self.status_label.setText(
            f"STATUS: PAUSED — STEP {self._index + 1}"
        )

    def stop(self) -> None:
        self._playing = False
        self._paused = False
        self._stop_media()
        if self._plan is not None:
            self._begin_step(0, animate=False)

    def next_step(self) -> None:
        if self._plan is None:
            return
        if self._index < len(self._plan.steps) - 1:
            self._begin_step(self._index + 1, animate=True)
            if self._playing:
                self._play_step_audio(self._index)
        else:
            self._progress = 1.0
            self._animating = False
            self._refresh()

    def prev_step(self) -> None:
        if self._plan is None:
            return
        if self._index > 0:
            self._begin_step(self._index - 1, animate=False)
            self._progress = 1.0
            self._animating = False
            self._refresh()

    def advance(self) -> None:
        """Move the build forward by one beat (the test driver;
        the timer walks the same path with real time)."""
        if self._plan is None:
            return
        if self._animating or self._progress < 1.0:
            self._progress = 1.0
            self._animating = False
            self._refresh()
            return
        self.next_step()
        # Land the new part instantly too: advance() is the
        # deterministic driver, not a second animation path.
        self._progress = 1.0
        self._animating = False
        self._refresh()

    # -------------------------------------------------------------- timer

    def _tick(self) -> None:
        if self._plan is None or self._paused:
            return
        dt = 0.033
        if self._animating:
            if not motion_enabled():
                # Motion reduced mid-flight: the part is simply
                # in place -- the end state never waits on motion.
                self._progress = 1.0
                self._animating = False
                self._hold_elapsed = 0.0
                self._refresh()
                return
            self._progress = min(1.0, self._progress + dt / _ANIM_S)
            if self._progress >= 1.0:
                self._animating = False
                self._hold_elapsed = 0.0
            self._refresh()
            return
        if self._playing:
            self._hold_elapsed += dt
            if self._hold_elapsed >= self._hold_seconds():
                if self._index < len(self._plan.steps) - 1:
                    self._begin_step(self._index + 1, animate=True)
                    self._play_step_audio(self._index)
                else:
                    self._playing = False
                    self._refresh()

    def _hold_seconds(self) -> float:
        step = self._plan.steps[self._index] if self._plan else None
        audio = getattr(step, "audio", None) if step else None
        if audio is not None and audio.duration_s > 0:
            return max(1.4, audio.duration_s + 0.4)
        return 2.2

    # --------------------------------------------------------------- audio

    def _prepare_audio(self, plan: AssemblyPlan) -> None:
        import tempfile
        from pathlib import Path

        if self._audio_dir is not None:
            try:
                self._audio_dir.cleanup()
            except Exception:
                pass
            self._audio_dir = None
        self._audio_files = {}
        if not any(
            getattr(step, "audio", None) and step.audio.data_b64
            for step in plan.steps
        ):
            return
        self._audio_dir = tempfile.TemporaryDirectory(
            prefix="mimforge-assembly-"
        )
        root = Path(self._audio_dir.name)
        for index, step in enumerate(plan.steps):
            audio = getattr(step, "audio", None)
            if audio and audio.data_b64:
                try:
                    target = root / f"step-{index + 1:02d}.wav"
                    target.write_bytes(audio.wav_bytes())
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
                return
            self._media.setSource(QUrl.fromLocalFile(str(target)))
            self._media.play()
        except Exception:
            pass

    def _stop_media(self) -> None:
        if self._media is not None:
            try:
                self._media.stop()
            except Exception:
                pass

    # --------------------------------------------------------------- slots

    def _on_step_picked(self, row: int) -> None:
        if self._plan is None or row < 0 or row >= len(self._plan.steps):
            return
        if row == self._index:
            return
        self._begin_step(row, animate=False)
        self._progress = 1.0
        self._animating = False
        self._refresh()

    def _on_back(self) -> None:
        show = getattr(self.host, "show_design_section", None)
        if callable(show):
            show()
