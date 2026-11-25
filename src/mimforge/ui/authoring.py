"""Authoring editor panel (plan Phase 2.4).

The teacher reviews the auto-drafted steps one by one: reads the draft
wording, edits it in place, checks the apparatus and safety notes, and
approves or rejects each step. Nothing is final until approved -- every
auto-generated artefact stays visibly a *draft* until the teacher
approves it. The panel works on an in-memory ``AuthoringDraft``; the
caller persists it (e.g. as a project record) via ``current_draft()``.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
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
from .main_window import ACCENT, MONO_FAMILY, MUTED, PANEL_BG, TEXT, mono_font


class AuthoringPanel(QWidget):
    """Step-by-step authoring editor following the design rule: dark
    charcoal, one electric accent, mono type, mission-control plates."""

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

        body = QHBoxLayout()
        self.step_list = QListWidget()
        self.step_list.setFont(mono_font(10))
        self.step_list.setFixedWidth(340)
        self.step_list.currentRowChanged.connect(self._on_select)
        body.addWidget(self.step_list)

        right = QVBoxLayout()
        self.step_title = QLabel("No step selected.")
        self.step_title.setFont(mono_font(11, bold=True))
        right.addWidget(self.step_title)

        self.meta_label = QLabel("")
        self.meta_label.setFont(mono_font(9))
        self.meta_label.setStyleSheet(f"color: {MUTED};")
        right.addWidget(self.meta_label)

        self.editor = QPlainTextEdit()
        self.editor.setFont(mono_font(10))
        self.editor.setPlaceholderText("Draft wording — edit freely.")
        self.editor.textChanged.connect(self._on_text_changed)
        right.addWidget(self.editor, stretch=1)

        self.check_label = QLabel("")
        self.check_label.setFont(mono_font(9))
        self.check_label.setStyleSheet(f"color: {MUTED};")
        self.check_label.setWordWrap(True)
        right.addWidget(self.check_label)

        buttons = QHBoxLayout()
        self.approve_button = QPushButton("✓  APPROVE STEP")
        self.approve_button.setFont(mono_font(10, bold=True))
        self.approve_button.clicked.connect(self._approve)
        self.reject_button = QPushButton("✕  REJECT STEP")
        self.reject_button.setFont(mono_font(10, bold=True))
        self.reject_button.clicked.connect(self._reject)
        buttons.addWidget(self.approve_button)
        buttons.addWidget(self.reject_button)
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

    def _approve(self) -> None:
        draft = self._draft
        if draft is None or self._current is None:
            return
        draft.steps[self._current].status = "approved"
        self._refresh_row(self._current)
        self._refresh_status()

    def _reject(self) -> None:
        draft = self._draft
        if draft is None or self._current is None:
            return
        draft.steps[self._current].status = "rejected"
        self._refresh_row(self._current)
        self._refresh_status()
