"""Generated design drawings as Qt views (Stage 3): the wiring
schematic and the control-panel face, painted from the same
generated data (``mimforge.wiring``) the production dossier
embeds as SVG -- one set of numbers, two renderings, so the app
and the exported document can never show two different machines.

Drafting style, like every surface: dark field, faint grid, one
electric accent, mono labels, dimension lines on the panel face.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..wiring import PanelLayout, WiringDiagram
from .main_window import ACCENT, MUTED, TEXT, mono_font

_FIELD = "#101216"
_BOX = "#1B1E24"
_EDGE = "#4A5158"
_RUN_COLOURS = {
    "power": "#E5484D",
    "safety": "#FFB020",
    "signal": ACCENT,
    "mechanical": MUTED,
}


def _pen(colour: str, width: int = 1, dash: bool = False) -> QPen:
    pen = QPen(QColor(colour))
    pen.setWidth(width)
    if dash:
        pen.setStyle(Qt.DashLine)
    return pen


class WiringView(QWidget):
    """The machine's wiring schematic, painted from the generated
    diagram: boxes for the electrical roles, orthogonal runs for
    the connections, coloured by kind (power / safety / signal /
    mechanical)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(300)
        self._diagram: WiringDiagram | None = None

    def set_diagram(self, diagram: WiringDiagram | None) -> None:
        self._diagram = diagram
        self.update()

    @property
    def diagram(self) -> WiringDiagram | None:
        return self._diagram

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(_FIELD))
        diagram = self._diagram
        if diagram is None:
            painter.setPen(QColor(MUTED))
            painter.setFont(mono_font(10))
            painter.drawText(self.rect(), Qt.AlignCenter, "NO DESIGN YET")
            return
        pad = 14
        scale = min(
            (self.width() - 2 * pad) / 100.0,
            (self.height() - 2 * pad - 16) / 70.0,
        )

        def px(v: float) -> float:
            return pad + v * scale

        def py(v: float) -> float:
            return pad + v * scale

        by_role = {node.role: node for node in diagram.nodes}
        # Runs under the boxes.
        for run in diagram.runs:
            a, b = by_role[run.from_role], by_role[run.to_role]
            if run.kind == "mechanical":
                start = QPointF(px(a.x + a.w / 2), py(a.y + a.h))
                end = QPointF(px(b.x + b.w / 2), py(b.y))
            else:
                start = QPointF(px(a.x + a.w), py(a.y + a.h / 2))
                end = QPointF(px(b.x), py(b.y + b.h / 2))
            mid_x = (start.x() + end.x()) / 2
            path = QPainterPath(start)
            path.lineTo(mid_x, start.y())
            path.lineTo(mid_x, end.y())
            path.lineTo(end)
            painter.setPen(
                _pen(_RUN_COLOURS[run.kind], 2, dash=run.kind == "mechanical")
            )
            painter.drawPath(path)
        # Boxes + labels.
        for node in diagram.nodes:
            x, y = px(node.x), py(node.y)
            w, h = node.w * scale, node.h * scale
            painter.setPen(
                _pen(ACCENT if node.role in ("controller", "estop") else _EDGE, 1)
            )
            painter.setBrush(QColor(_BOX))
            painter.drawRect(int(x), int(y), int(w), int(h))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor(TEXT))
            painter.setFont(mono_font(8, bold=True))
            painter.drawText(
                int(x) + 5, int(y) + 12, int(w) - 8, 12,
                Qt.AlignLeft, node.label,
            )
            painter.setPen(QColor(MUTED))
            painter.setFont(mono_font(7))
            painter.drawText(
                int(x) + 5, int(y) + 24, int(w) - 8, int(h) - 26,
                Qt.AlignLeft | Qt.TextWordWrap, node.detail,
            )
        painter.setPen(QColor(MUTED))
        painter.setFont(mono_font(8))
        painter.drawText(
            pad, self.height() - 4,
            "RED POWER · AMBER SAFETY CHAIN · CYAN SIGNAL · GREY DASHED MECHANICAL",
        )


class PanelLayoutView(QWidget):
    """The control-panel face, dimensioned: every control the
    generated panel builds, placed where the builder puts it --
    the latching stop round and red at the top right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(240)
        self._layout: PanelLayout | None = None

    def set_layout(self, layout: PanelLayout | None) -> None:
        self._layout = layout
        self.update()

    @property
    def layout_data(self) -> PanelLayout | None:
        return self._layout

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(_FIELD))
        layout = self._layout
        if layout is None:
            painter.setPen(QColor(MUTED))
            painter.setFont(mono_font(10))
            painter.drawText(self.rect(), Qt.AlignCenter, "NO DESIGN YET")
            return
        pad_l, pad_t, pad_r, pad_b = 14, 12, 44, 30
        scale = min(
            (self.width() - pad_l - pad_r) / layout.width_mm,
            (self.height() - pad_t - pad_b) / layout.height_mm,
        )

        def px(v: float) -> float:
            return pad_l + v * scale

        def py(v: float) -> float:
            return pad_t + v * scale

        painter.setPen(_pen(ACCENT, 2))
        painter.setBrush(QColor(_BOX))
        painter.drawRect(
            int(px(0)), int(py(0)),
            int(layout.width_mm * scale), int(layout.height_mm * scale),
        )
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QColor(ACCENT))
        painter.setFont(mono_font(9, bold=True))
        painter.drawText(
            int(px(12)), int(py(20)),
            f"CONTROL PANEL — {layout.title.upper()}",
        )
        for control in layout.controls:
            x, y = px(control.x), py(control.y)
            w, h = control.w * scale, control.h * scale
            if control.shape == "round":
                painter.setPen(_pen("#E5484D", 2))
                painter.setBrush(QColor("#5C1A1A"))
                painter.drawEllipse(int(x), int(y), int(w), int(h))
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QColor(TEXT))
                painter.setFont(mono_font(7, bold=True))
                painter.drawText(
                    int(x) - 10, int(y + h) + 4, int(w) + 20, 10,
                    Qt.AlignCenter, control.label,
                )
                continue
            painter.setPen(
                _pen(ACCENT if control.kind in ("button", "selector") else _EDGE, 1)
            )
            painter.setBrush(QColor("#22252B"))
            painter.drawRect(int(x), int(y), int(w), int(h))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor(TEXT))
            painter.setFont(mono_font(7))
            painter.drawText(
                int(x) + 4, int(y) + 11, int(w) - 6, 10,
                Qt.AlignLeft, control.label,
            )
        # Dimension lines: width under the face, height at right.
        painter.setPen(_pen(MUTED, 1))
        painter.setFont(mono_font(8))
        dim_y = py(layout.height_mm) + 16
        painter.drawLine(int(px(0)), int(dim_y), int(px(layout.width_mm)), int(dim_y))
        painter.drawText(
            int(px(0)), int(dim_y) + 2, int(layout.width_mm * scale), 12,
            Qt.AlignCenter, f"{layout.width_mm:.0f} mm",
        )
        dim_x = px(layout.width_mm) + 16
        painter.drawLine(int(dim_x), int(py(0)), int(dim_x), int(py(layout.height_mm)))
        painter.save()
        painter.translate(dim_x + 10, py(layout.height_mm / 2))
        painter.rotate(-90)
        painter.drawText(-30, 0, 60, 12, Qt.AlignCenter, f"{layout.height_mm:.0f} mm")
        painter.restore()
