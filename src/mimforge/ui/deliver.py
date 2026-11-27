"""Deliver panel: risk sign-off, checked code, signed package export.

This is the surface for the delivery path that previously existed
only as engine code: the risk assessment a named teacher must sign
before anything is exported, the controller code that is handed
over only when its safety check passes, and the signed machine
package itself. The panel holds no engine logic -- every action
delegates to the host window, which owns the project, the gate and
the dialogs.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .main_window import ACCENT, MUTED, TEXT, mono_font


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


class DeliverPanel(QWidget):
    """Sign-off + code generation + package export for one project."""

    def __init__(self, host, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        layout = QVBoxLayout(self)
        layout.addWidget(_plate("DELIVER — SIGN-OFF + EXPORT"))
        self.project_label = _status("PROJECT: —")
        layout.addWidget(self.project_label)

        layout.addWidget(
            _caption(
                "RISK ASSESSMENT — A TEACHER SIGNS BEFORE ANY EXPORT"
            )
        )
        self.assessment_view = QPlainTextEdit()
        self.assessment_view.setFont(mono_font(10))
        self.assessment_view.setReadOnly(True)
        self.assessment_view.setPlainText("No project open.")
        layout.addWidget(self.assessment_view, stretch=1)
        self.signoff_label = _status("SIGN-OFF: NOT SIGNED")
        layout.addWidget(self.signoff_label)
        sign_row = QHBoxLayout()
        self.teacher_edit = QLineEdit()
        self.teacher_edit.setFont(mono_font(10))
        self.teacher_edit.setPlaceholderText("Teacher's full name")
        sign_row.addWidget(self.teacher_edit, stretch=1)
        self.sign_button = QPushButton("✎  SIGN THE ASSESSMENT")
        self.sign_button.setFont(mono_font(10, bold=True))
        self.sign_button.clicked.connect(self._on_sign)
        sign_row.addWidget(self.sign_button)
        layout.addLayout(sign_row)
        self.export_button = QPushButton("⬆  EXPORT SIGNED PACKAGE")
        self.export_button.setFont(mono_font(11, bold=True))
        self.export_button.clicked.connect(
            lambda: self.host.export_package()
        )
        layout.addWidget(self.export_button)
        self.production_button = QPushButton(
            "⬆  EXPORT PRODUCTION DOCUMENT"
        )
        self.production_button.setFont(mono_font(11, bold=True))
        self.production_button.clicked.connect(
            lambda: self.host.export_production_document()
        )
        layout.addWidget(self.production_button)

        layout.addWidget(
            _caption("CONTROLLER CODE — CHECKED BEFORE IT IS SAVED")
        )
        self.generate_button = QPushButton("⚙  GENERATE CONTROLLER CODE")
        self.generate_button.setFont(mono_font(10, bold=True))
        self.generate_button.clicked.connect(
            lambda: self.host.generate_code()
        )
        layout.addWidget(self.generate_button)
        self.code_view = QPlainTextEdit()
        self.code_view.setFont(mono_font(9))
        self.code_view.setReadOnly(True)
        self.code_view.setPlainText("No code generated yet.")
        layout.addWidget(self.code_view, stretch=1)

        self.status_label = _status("STATUS: READY")
        layout.addWidget(self.status_label)

    # ------------------------------------------------------------- display

    def show_project(self, title: str | None, assessment) -> None:
        self.project_label.setText(f"PROJECT: {title or '—'}")
        self.show_assessment(assessment)

    def show_assessment(self, assessment) -> None:
        if assessment is None:
            self.assessment_view.setPlainText("No project open.")
            self.signoff_label.setText("SIGN-OFF: NOT SIGNED")
            return
        lines = [
            f"HAZARDS — {len(assessment.hazards)} RECORDED",
            "",
        ]
        for hazard in assessment.hazards:
            lines.append(
                f"• [{hazard.severity} / {hazard.likelihood}] "
                f"{hazard.description}"
            )
            lines.append(f"  Control: {hazard.mitigation}")
        self.assessment_view.setPlainText("\n".join(lines))
        if assessment.signed:
            self.signoff_label.setText(
                f"SIGN-OFF: SIGNED BY {assessment.signed_by} — EXPORT OPEN"
            )
        else:
            self.signoff_label.setText(
                "SIGN-OFF: NOT SIGNED — EXPORT STAYS CLOSED"
            )

    def show_code(self, bundle) -> None:
        lines = [
            "SAFETY CHECK — CONTROLLER: PASSED",
            "SAFETY CHECK — CONTROL PANEL: PASSED",
            "",
            bundle.controller,
        ]
        self.code_view.setPlainText("\n".join(lines))

    def show_code_failure(self, message: str) -> None:
        self.code_view.setPlainText(
            "SAFETY CHECK — FAILED\n\n" + message
        )

    def set_status(self, text: str) -> None:
        self.status_label.setText(f"STATUS: {text}")

    # --------------------------------------------------------------- slots

    def _on_sign(self) -> None:
        self.host.sign_assessment(self.teacher_edit.text())
