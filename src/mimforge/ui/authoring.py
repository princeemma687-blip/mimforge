"""Authoring editor panel (plan Phase 2.4).

The teacher reviews the auto-drafted steps one by one: reads the draft
wording, edits it in place, checks the apparatus and safety notes, and
approves or rejects each step. Nothing is final until approved -- every
auto-generated artefact stays visibly a *draft* until the teacher
approves it. The panel works on an in-memory ``AuthoringDraft``; the
caller persists it (e.g. as a project record) via ``current_draft()``.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..structuring import AuthoringDraft
from .icons import make_icon
from .main_window import (
    ACCENT,
    MONO_FAMILY,
    MUTED,
    PANEL_BG,
    TEXT,
    mono_font,
    prose_font,
)


class AuthoringPanel(QWidget):
    """Step-by-step authoring editor following the design rule: dark
    charcoal, one electric accent, mono type, mission-control plates."""

    #: Emitted when the teacher asks to build the lesson package
    #: from the approved draft. The shell owns the assembly.
    build_lesson_requested = Signal()

    #: Emitted when the teacher asks to import a demonstration
    #: recording. The shell owns the file dialog and the pipeline.
    import_requested = Signal()

    #: Emitted when the teacher asks to draft from a transcript
    #: file instead (the fallback when a recording's speech cannot
    #: be read on this computer). The shell owns the pipeline.
    transcript_requested = Signal()

    #: Emitted whenever the teacher changes the draft (approve,
    #: reject, edit) so the shell can persist it immediately --
    #: approvals must survive the window being closed at any
    #: moment, not only the next project switch.
    draft_changed = Signal()

    #: Teacher voice (Stage 2): the shell owns the file dialog,
    #: the microphone recorder and the audio conversion; the panel
    #: only asks. The recording replaces the app's synthetic voice
    #: for the selected step and is labelled as the teacher's.
    voice_attach_requested = Signal()
    voice_record_requested = Signal()
    voice_remove_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._draft: AuthoringDraft | None = None
        self._current: int | None = None

        layout = QVBoxLayout(self)
        title = QLabel("■ AUTHOR — DEMONSTRATION STEPS")
        title.setFont(mono_font(12, bold=True))
        layout.addWidget(title)

        self.hint = QLabel(
            "DRAFT — every step needs teacher approval before it is used."
        )
        self.hint.setFont(mono_font(10, bold=True))
        self.hint.setStyleSheet(f"color: {ACCENT};")
        layout.addWidget(self.hint)

        import_row = QHBoxLayout()
        self.tracker_combo = QComboBox()
        self.tracker_combo.setFont(mono_font(10))
        self.tracker_combo.addItem("TRACKER: COLOUR", "colour")
        self.tracker_combo.addItem("TRACKER: CLICK (SAM 2.1)", "sam")
        import_row.addWidget(self.tracker_combo)
        self.import_button = QPushButton("⇓  IMPORT DEMONSTRATION VIDEO")
        self.import_button.setFont(mono_font(10, bold=True))
        self.import_button.setIcon(make_icon("import", 18))
        self.import_button.setIconSize(QSize(18, 18))
        self.import_button.clicked.connect(self.import_requested.emit)
        import_row.addWidget(self.import_button)
        self.transcript_button = QPushButton("⇓  USE A TRANSCRIPT FILE")
        self.transcript_button.setFont(mono_font(10, bold=True))
        self.transcript_button.setIcon(make_icon("file", 18))
        self.transcript_button.setIconSize(QSize(18, 18))
        self.transcript_button.clicked.connect(
            self.transcript_requested.emit
        )
        import_row.addWidget(self.transcript_button)
        self.import_status_label = QLabel("")
        self.import_status_label.setFont(mono_font(9, bold=True))
        self.import_status_label.setStyleSheet(f"color: {ACCENT};")
        self.import_status_label.setWordWrap(True)
        import_row.addWidget(self.import_status_label, stretch=1)
        layout.addLayout(import_row)

        body = QHBoxLayout()
        self.step_list = QListWidget()
        self.step_list.setFont(mono_font(10))
        self.step_list.setFixedWidth(340)
        self.step_list.currentRowChanged.connect(self._on_select)
        body.addWidget(self.step_list)

        right = QVBoxLayout()
        self.step_title = QLabel("No step selected.")
        self.step_title.setFont(prose_font(11, bold=True))
        right.addWidget(self.step_title)

        self.meta_label = QLabel("")
        self.meta_label.setFont(mono_font(9))
        self.meta_label.setStyleSheet(f"color: {MUTED};")
        right.addWidget(self.meta_label)

        self.editor = QPlainTextEdit()
        # The draft wording is prose -- the words the lesson will
        # speak -- so it reads in the grotesque, per the type
        # audit; the readouts around it stay mono.
        self.editor.setFont(prose_font(10))
        self.editor.setPlaceholderText("Draft wording — edit freely.")
        self.editor.textChanged.connect(self._on_text_changed)
        right.addWidget(self.editor, stretch=1)

        self.check_label = QLabel("")
        self.check_label.setFont(prose_font(9))
        self.check_label.setStyleSheet(f"color: {MUTED};")
        self.check_label.setWordWrap(True)
        right.addWidget(self.check_label)

        self.voice_label = QLabel("VOICE: —")
        self.voice_label.setFont(mono_font(9, bold=True))
        self.voice_label.setStyleSheet(f"color: {ACCENT};")
        self.voice_label.setWordWrap(True)
        right.addWidget(self.voice_label)

        voice_row = QHBoxLayout()
        self.voice_attach_button = QPushButton("⇓  ATTACH MY VOICE FILE")
        self.voice_attach_button.setFont(mono_font(10, bold=True))
        self.voice_attach_button.setIcon(make_icon("attach", 18))
        self.voice_attach_button.setIconSize(QSize(18, 18))
        self.voice_attach_button.clicked.connect(
            self.voice_attach_requested.emit
        )
        self.voice_record_button = QPushButton("●  RECORD MY VOICE")
        self.voice_record_button.setFont(mono_font(10, bold=True))
        self.voice_record_button.setIcon(make_icon("record", 18))
        self.voice_record_button.setIconSize(QSize(18, 18))
        self.voice_record_button.clicked.connect(
            self.voice_record_requested.emit
        )
        self.voice_remove_button = QPushButton("✕  REMOVE MY VOICE")
        self.voice_remove_button.setFont(mono_font(10, bold=True))
        self.voice_remove_button.setIcon(make_icon("cross", 18))
        self.voice_remove_button.setIconSize(QSize(18, 18))
        self.voice_remove_button.clicked.connect(
            self.voice_remove_requested.emit
        )
        voice_row.addWidget(self.voice_attach_button)
        voice_row.addWidget(self.voice_record_button)
        voice_row.addWidget(self.voice_remove_button)
        right.addLayout(voice_row)

        buttons = QHBoxLayout()
        self.approve_button = QPushButton("✓  APPROVE STEP")
        self.approve_button.setFont(mono_font(10, bold=True))
        self.approve_button.setIcon(make_icon("check", 18))
        self.approve_button.setIconSize(QSize(18, 18))
        self.approve_button.clicked.connect(self._approve)
        self.reject_button = QPushButton("✕  REJECT STEP")
        self.reject_button.setFont(mono_font(10, bold=True))
        self.reject_button.setIcon(make_icon("cross", 18))
        self.reject_button.setIconSize(QSize(18, 18))
        self.reject_button.clicked.connect(self._reject)
        self.build_lesson_button = QPushButton("▣  BUILD LESSON")
        self.build_lesson_button.setFont(mono_font(10, bold=True))
        self.build_lesson_button.setIcon(make_icon("build", 18))
        self.build_lesson_button.setIconSize(QSize(18, 18))
        self.build_lesson_button.clicked.connect(
            self.build_lesson_requested.emit
        )
        buttons.addWidget(self.approve_button)
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.build_lesson_button)
        right.addLayout(buttons)
        body.addLayout(right, stretch=1)
        layout.addLayout(body, stretch=1)

        self.status_label = QLabel("STATUS: NO DRAFT LOADED")
        self.status_label.setFont(mono_font(10, bold=True))
        self.status_label.setStyleSheet(f"color: {ACCENT};")
        layout.addWidget(self.status_label)

    # ---------------------------------------------------------------- API

    def load_draft(self, draft: AuthoringDraft) -> None:
        self._draft = draft
        self._current = None
        self.step_list.clear()
        for step in draft.steps:
            item = QListWidgetItem(
                f"{step.order:02d}  [{step.status.upper():^8}]  {step.title}"
            )
            self.step_list.addItem(item)
        self._refresh_status()
        if draft.steps:
            self.step_list.setCurrentRow(0)

    def current_draft(self) -> AuthoringDraft | None:
        return self._draft

    def current_step_index(self) -> int | None:
        return self._current

    def refresh_voice_label(self) -> None:
        """Show the selected step's voice state in plain words."""
        draft = self._draft
        if draft is None or self._current is None:
            self.voice_label.setText("VOICE: —")
            return
        step = draft.steps[self._current]
        if step.voice_audio:
            duration = float(step.voice_audio.get("duration_s", 0.0))
            self.voice_label.setText(
                "VOICE: TEACHER VOICE — RECORDED BY THE TEACHER "
                f"({duration:.1f} s) — PLAYS INSTEAD OF THE APP VOICE"
            )
        else:
            self.voice_label.setText(
                "VOICE: NONE — THE APP'S AI VOICE WILL READ THIS STEP "
                "WHEN THE LESSON IS BUILT"
            )

    def set_recording(self, active: bool) -> None:
        self.voice_record_button.setText(
            "■  STOP RECORDING" if active else "●  RECORD MY VOICE"
        )
        self.voice_record_button.setIcon(
            make_icon("stop" if active else "record", 18)
        )

    def show_import_status(self, text: str) -> None:
        self.import_status_label.setText(text)

    def tracker_choice(self) -> str:
        """Which tracker the import should use: ``colour`` (the
        template's colour band) or ``sam`` (the teacher clicks the
        object and the segmentation model follows it)."""
        return str(self.tracker_combo.currentData() or "colour")

    # ------------------------------------------------------------ internals

    def _refresh_status(self) -> None:
        draft = self._draft
        if draft is None:
            self.status_label.setText("STATUS: NO DRAFT LOADED")
            return
        self.status_label.setText(
            f"STATUS: {draft.approved_count}/{len(draft.steps)} APPROVED  ·  "
            f"MEAN CONFIDENCE {draft.mean_confidence:.2f}  ·  "
            f"{len(draft.warnings)} WARNING(S)"
        )

    def _refresh_row(self, index: int) -> None:
        draft = self._draft
        if draft is None:
            return
        step = draft.steps[index]
        self.step_list.item(index).setText(
            f"{step.order:02d}  [{step.status.upper():^8}]  {step.title}"
        )

    def _on_select(self, row: int) -> None:
        draft = self._draft
        if draft is None or row < 0 or row >= len(draft.steps):
            return
        self._current = row
        step = draft.steps[row]
        self.step_title.setText(f"{step.order:02d} — {step.title}")
        spans = ", ".join(
            f"{s:.1f}–{e:.1f}s" for s, e in step.source_spans
        ) or "no narration matched"
        self.meta_label.setText(
            f"CONFIDENCE {step.confidence:.2f}  ·  ADVISOR {step.advisor_used}  ·  "
            f"SOURCE {spans}"
        )
        apparatus = ", ".join(step.apparatus_refs) or "—"
        safety = "; ".join(step.safety_notes) or "—"
        self.check_label.setText(
            f"APPARATUS: {apparatus}\n"
            f"SAFETY: {safety}\n"
            f"CHECK: {step.check_question or '—'}"
        )
        self.editor.blockSignals(True)
        self.editor.setPlainText(step.draft_text)
        self.editor.blockSignals(False)
        self.refresh_voice_label()

    def _on_text_changed(self) -> None:
        draft = self._draft
        if draft is None or self._current is None:
            return
        step = draft.steps[self._current]
        step.draft_text = self.editor.toPlainText()
        if step.status == "approved":
            step.status = "edited"  # approval no longer covers new wording
            self._refresh_row(self._current)
            self._refresh_status()
        self.draft_changed.emit()

    def _approve(self) -> None:
        draft = self._draft
        if draft is None or self._current is None:
            return
        draft.steps[self._current].status = "approved"
        self._refresh_row(self._current)
        self._refresh_status()
        self.draft_changed.emit()

    def _reject(self) -> None:
        draft = self._draft
        if draft is None or self._current is None:
            return
        draft.steps[self._current].status = "rejected"
        self._refresh_row(self._current)
        self._refresh_status()
        self.draft_changed.emit()
