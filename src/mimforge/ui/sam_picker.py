"""The click prompt for the segmentation tracker.

When the teacher chooses the click tracker for a demonstration
import, the shell shows the recording's first frame here and the
teacher clicks the object to follow. The dialog owns only the
geometry: painting the frame fitted into the view and translating
a click back into frame pixels. Cancelling (or closing without a
click) returns no point, and the import reports that plainly.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .main_window import ACCENT, MUTED, TEXT, mono_font

_VIEW_W = 880
_VIEW_H = 520


def _to_pixmap(frame_bgr: np.ndarray) -> QPixmap:
    """A BGR frame as a pixmap (a copied image -- the frame buffer
    is reused by the video reader)."""
    import cv2

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    image = QImage(
        rgb.data, width, height, int(rgb.strides[0]), QImage.Format_RGB888
    )
    return QPixmap.fromImage(image.copy())


class _FrameView(QWidget):
    """Paints one frame fitted into the view and records where the
    teacher clicked, in frame pixels."""

    def __init__(self, frame_bgr: np.ndarray, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(_VIEW_W, _VIEW_H)
        self._pixmap = _to_pixmap(frame_bgr)
        self._frame_w = int(frame_bgr.shape[1])
        self._frame_h = int(frame_bgr.shape[0])
        self.point: tuple[float, float] | None = None
        self.on_click = None  # optional callback, set by the dialog

    def _draw_rect(self) -> QRectF:
        scale = min(
            _VIEW_W / max(self._frame_w, 1), _VIEW_H / max(self._frame_h, 1)
        )
        w = self._frame_w * scale
        h = self._frame_h * scale
        return QRectF((_VIEW_W - w) / 2, (_VIEW_H - h) / 2, w, h)

    def frame_point(self, view_x: float, view_y: float):
        """Translate a view position to frame pixels, or None when
        the position falls outside the drawn frame."""
        rect = self._draw_rect()
        if not rect.contains(QPointF(view_x, view_y)):
            return None
        fx = (view_x - rect.x()) / rect.width() * self._frame_w
        fy = (view_y - rect.y()) / rect.height() * self._frame_h
        return (float(fx), float(fy))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        pos = event.position()
        point = self.frame_point(pos.x(), pos.y())
        if point is not None:
            self.point = point
            self.update()
            if self.on_click is not None:
                self.on_click(point)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        rect = self._draw_rect()
        painter.drawPixmap(rect.toRect(), self._pixmap)
        if self.point is not None:
            scale = rect.width() / max(self._frame_w, 1)
            cx = rect.x() + self.point[0] * scale
            cy = rect.y() + self.point[1] * (
                rect.height() / max(self._frame_h, 1)
            )
            pen = QPen(QColor(ACCENT))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawEllipse(
                int(cx) - 10, int(cy) - 10, 20, 20
            )
            painter.drawLine(int(cx) - 16, int(cy), int(cx) + 16, int(cy))
            painter.drawLine(int(cx), int(cy) - 16, int(cx), int(cy) + 16)


class SamPointDialog(QDialog):
    """First frame + one click: the segmentation tracker's prompt."""

    def __init__(self, frame_bgr: np.ndarray, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CLICK THE OBJECT TO TRACK")
        layout = QVBoxLayout(self)
        caption = QLabel(
            "CLICK THE OBJECT TO FOLLOW THROUGH THE RECORDING"
        )
        caption.setFont(mono_font(10, bold=True))
        caption.setStyleSheet(f"color: {TEXT};")
        layout.addWidget(caption)
        self.view = _FrameView(frame_bgr, self)
        layout.addWidget(self.view)
        row = QHBoxLayout()
        self.hint_label = QLabel("NO CLICK YET")
        self.hint_label.setFont(mono_font(9, bold=True))
        self.hint_label.setStyleSheet(f"color: {MUTED};")
        row.addWidget(self.hint_label, stretch=1)
        self.track_button = QPushButton("TRACK THIS OBJECT")
        self.track_button.setFont(mono_font(10, bold=True))
        self.track_button.setEnabled(False)
        self.track_button.clicked.connect(self.accept)
        row.addWidget(self.track_button)
        cancel = QPushButton("CANCEL")
        cancel.setFont(mono_font(10, bold=True))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        layout.addLayout(row)
        self.view.on_click = self._clicked

    def _clicked(self, point: tuple[float, float]) -> None:
        self.track_button.setEnabled(True)
        self.hint_label.setText(
            f"CLICKED AT {point[0]:.0f}, {point[1]:.0f} — "
            "TRACK THIS OBJECT WHEN READY"
        )

    @property
    def point(self) -> tuple[float, float] | None:
        """The clicked point in frame pixels, or None."""
        return self.view.point
