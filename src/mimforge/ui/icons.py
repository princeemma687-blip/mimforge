"""The app's vector icon set (next-stage plan, Stage 4.2; the
Stage 4 full pass carries it to every panel).

One icon set, drawn as vector paths in the app's own drafting
style -- no emoji, no stock glyphs, no raster art. Every icon is a
``QPainterPath`` in a 24 x 24 drafting grid, stroked with one
consistent weight, and rendered to a pixmap at whatever size the
caller asks for, so the same path stays crisp at 16, 32 and 64 px.

The set began with the Playback transport (play, pause, stop,
export) and now covers every panel's actions -- import, attach,
record, approve, build, sign, generate, navigate -- drawn once
here and used everywhere: buttons take their icons from
:func:`make_icon`, never from a text glyph.

Generic-only: the icons are action marks, not practical marks;
nothing here names or pictures any demonstration.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .main_window import ACCENT

# The drafting grid every icon is drawn on. Paths use these
# coordinates; rendering scales the grid to the requested size, so
# the stroke weight scales with the icon and stays consistent.
_GRID = 24.0

# Stroke weight in grid units -- one weight for the whole set.
_STROKE = 2.0

ICON_NAMES = (
    "play", "pause", "stop", "export",
    "import", "file", "attach", "record", "check", "cross",
    "build", "sign", "gear", "back", "prev", "next", "reset", "doc",
)


def _move(path: QPainterPath, x: float, y: float) -> None:
    path.moveTo(x, y)


def _line(path: QPainterPath, x: float, y: float) -> None:
    path.lineTo(x, y)


def _path_play() -> QPainterPath:
    """A right-pointing triangle, outline only -- the drafting
    mark for "start the performance"."""
    path = QPainterPath()
    _move(path, 7.0, 4.5)
    _line(path, 7.0, 19.5)
    _line(path, 19.5, 12.0)
    path.closeSubpath()
    return path


def _path_pause() -> QPainterPath:
    """Two upright bars -- the drafting mark for "hold"."""
    path = QPainterPath()
    _move(path, 8.0, 5.0)
    _line(path, 8.0, 19.0)
    _move(path, 16.0, 5.0)
    _line(path, 16.0, 19.0)
    return path


def _path_stop() -> QPainterPath:
    """A square, outline only -- the drafting mark for "end and
    return to the start"."""
    path = QPainterPath()
    path.addRect(6.0, 6.0, 12.0, 12.0)
    return path


def _path_export() -> QPainterPath:
    """An up arrow leaving an open tray -- the drafting mark for
    "take this lesson out of the app"."""
    path = QPainterPath()
    # Tray: open at the top, closed at the bottom.
    _move(path, 4.5, 10.5)
    _line(path, 4.5, 19.5)
    _line(path, 19.5, 19.5)
    _line(path, 19.5, 10.5)
    # Arrow shaft, rising out of the tray.
    _move(path, 12.0, 17.0)
    _line(path, 12.0, 4.5)
    # Arrow head.
    _move(path, 7.5, 9.0)
    _line(path, 12.0, 4.5)
    _line(path, 16.5, 9.0)
    return path


def _path_import() -> QPainterPath:
    """A down arrow entering an open tray -- the drafting mark
    for "bring a file into the app" (the export mark, reversed)."""
    path = QPainterPath()
    _move(path, 4.5, 10.5)
    _line(path, 4.5, 19.5)
    _line(path, 19.5, 19.5)
    _line(path, 19.5, 10.5)
    _move(path, 12.0, 4.5)
    _line(path, 12.0, 16.5)
    _move(path, 7.5, 12.0)
    _line(path, 12.0, 16.5)
    _line(path, 16.5, 12.0)
    return path


def _path_file() -> QPainterPath:
    """A page with a folded corner -- the mark for a document
    the teacher supplies (a transcript, a file of their own)."""
    path = QPainterPath()
    _move(path, 6.0, 3.5)
    _line(path, 14.5, 3.5)
    _line(path, 18.0, 7.0)
    _line(path, 18.0, 20.5)
    _line(path, 6.0, 20.5)
    path.closeSubpath()
    _move(path, 14.5, 3.5)
    _line(path, 14.5, 7.0)
    _line(path, 18.0, 7.0)
    return path


def _path_doc() -> QPainterPath:
    """A page carrying ruled lines -- the mark for a document
    the app produces (the production document)."""
    path = _path_file()
    for y in (11.5, 14.5, 17.5):
        _move(path, 9.0, y)
        _line(path, 15.0, y)
    return path


def _path_attach() -> QPainterPath:
    """Two chain links, overlapping -- the mark for attaching
    one thing (the teacher's voice file) to another (the step)."""
    path = QPainterPath()
    path.addRoundedRect(3.0, 9.0, 9.5, 6.5, 3.0, 3.0)
    path.addRoundedRect(11.5, 8.5, 9.5, 6.5, 3.0, 3.0)
    return path


def _path_record() -> QPainterPath:
    """A ring with a centre dot -- the mark for recording."""
    path = QPainterPath()
    path.addEllipse(4.5, 4.5, 15.0, 15.0)
    path.addEllipse(10.4, 10.4, 3.2, 3.2)
    return path


def _path_check() -> QPainterPath:
    """A tick -- the mark for approval."""
    path = QPainterPath()
    _move(path, 5.0, 12.5)
    _line(path, 10.0, 17.5)
    _line(path, 19.0, 6.5)
    return path


def _path_cross() -> QPainterPath:
    """A cross -- the mark for rejection or removal."""
    path = QPainterPath()
    _move(path, 6.5, 6.5)
    _line(path, 17.5, 17.5)
    _move(path, 17.5, 6.5)
    _line(path, 6.5, 17.5)
    return path


def _path_build() -> QPainterPath:
    """Four blocks in a grid -- the mark for building: coupling
    parts together, or building the lesson from its steps."""
    path = QPainterPath()
    for x in (4.5, 13.0):
        for y in (4.5, 13.0):
            path.addRect(x, y, 6.5, 6.5)
    return path


def _path_sign() -> QPainterPath:
    """A pen nib over a ruled line -- the mark for signing."""
    path = QPainterPath()
    _move(path, 6.0, 15.5)
    _line(path, 15.5, 6.0)
    _line(path, 18.0, 8.5)
    _line(path, 8.5, 18.0)
    _line(path, 5.0, 19.0)
    path.closeSubpath()
    _move(path, 4.0, 21.0)
    _line(path, 20.0, 21.0)
    return path


def _path_gear() -> QPainterPath:
    """A hub with eight spokes -- the mark for generation: the
    app working a mechanism (code, adjustment) on request."""
    import math

    path = QPainterPath()
    path.addEllipse(8.8, 8.8, 6.4, 6.4)
    for i in range(8):
        angle = math.radians(i * 45.0)
        x1 = 12.0 + 4.6 * math.cos(angle)
        y1 = 12.0 + 4.6 * math.sin(angle)
        x2 = 12.0 + 8.2 * math.cos(angle)
        y2 = 12.0 + 8.2 * math.sin(angle)
        _move(path, x1, y1)
        _line(path, x2, y2)
    return path


def _path_back() -> QPainterPath:
    """A left arrow on a shaft -- the mark for going back."""
    path = QPainterPath()
    _move(path, 20.0, 12.0)
    _line(path, 5.0, 12.0)
    _move(path, 10.5, 6.5)
    _line(path, 5.0, 12.0)
    _line(path, 10.5, 17.5)
    return path


def _path_prev() -> QPainterPath:
    """A left chevron -- the mark for the previous step."""
    path = QPainterPath()
    _move(path, 15.0, 5.0)
    _line(path, 8.0, 12.0)
    _line(path, 15.0, 19.0)
    return path


def _path_next() -> QPainterPath:
    """A right chevron -- the mark for the next step."""
    path = QPainterPath()
    _move(path, 9.0, 5.0)
    _line(path, 16.0, 12.0)
    _line(path, 9.0, 19.0)
    return path


def _path_reset() -> QPainterPath:
    """A circular arrow, nearly closed -- the mark for returning
    to the start. Traced as chords so the arc is exact at every
    size, with the head at the top where the circle closes."""
    import math

    path = QPainterPath()
    steps = 9
    for i in range(steps + 1):
        angle = math.radians(-90.0 + i * (300.0 / steps))
        x = 12.0 + 7.5 * math.cos(angle)
        y = 12.0 + 7.5 * math.sin(angle)
        if i == 0:
            _move(path, x, y)
        else:
            _line(path, x, y)
    # Arrow head at the final point, tangent to the circle.
    angle = math.radians(-90.0 + 300.0)
    x = 12.0 + 7.5 * math.cos(angle)
    y = 12.0 + 7.5 * math.sin(angle)
    tx, ty = -math.sin(angle), math.cos(angle)  # tangent (direction of travel)
    nx, ny = math.cos(angle), math.sin(angle)  # radial
    _move(path, x - 3.4 * tx + 1.8 * nx, y - 3.4 * ty + 1.8 * ny)
    _line(path, x, y)
    _line(path, x - 3.4 * tx - 1.8 * nx, y - 3.4 * ty - 1.8 * ny)
    return path


_PATH_BUILDERS = {
    "play": _path_play,
    "pause": _path_pause,
    "stop": _path_stop,
    "export": _path_export,
    "import": _path_import,
    "file": _path_file,
    "attach": _path_attach,
    "record": _path_record,
    "check": _path_check,
    "cross": _path_cross,
    "build": _path_build,
    "sign": _path_sign,
    "gear": _path_gear,
    "back": _path_back,
    "prev": _path_prev,
    "next": _path_next,
    "reset": _path_reset,
    "doc": _path_doc,
}


def icon_path(name: str) -> QPainterPath:
    """The vector path for ``name`` on the 24 x 24 drafting grid.

    Raises ``ValueError`` for an unknown name -- an icon that does
    not exist must fail loudly at build time, never render blank.
    """
    try:
        builder = _PATH_BUILDERS[name]
    except KeyError:
        raise ValueError(
            f"unknown icon {name!r}; known icons: {', '.join(ICON_NAMES)}"
        ) from None
    return builder()


def icon_pixmap(name: str, size: int, color: str = ACCENT) -> QPixmap:
    """Render ``name`` to a square pixmap of ``size`` px.

    The path is drawn once, scaled from the drafting grid, with
    antialiasing and a stroke weight that scales with the size, so
    the mark is crisp at 16, 32 and 64 px alike. ``size`` must be
    positive; anything smaller than 8 px cannot carry the stroke
    and is refused.
    """
    if size < 8:
        raise ValueError(f"icon size {size} px is too small to draw")
    path = icon_path(name)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    scale = size / _GRID
    painter.scale(scale, scale)
    pen = QPen(QColor(color))
    pen.setWidthF(_STROKE)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.end()
    return pixmap


def make_icon(name: str, size: int = 24, color: str = ACCENT) -> QIcon:
    """The icon as a ``QIcon`` at ``size`` px, for a button."""
    return QIcon(icon_pixmap(name, size, color))
