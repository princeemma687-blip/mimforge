"""Vector icon set for the Playback panel (next-stage plan, Stage 4.2).

One icon set, drawn as vector paths in the app's own drafting
style -- no emoji, no stock glyphs, no raster art. Every icon is a
``QPainterPath`` in a 24 x 24 drafting grid, stroked with one
consistent weight, and rendered to a pixmap at whatever size the
caller asks for, so the same path stays crisp at 16, 32 and 64 px.

The set covers the transport the Playback panel uses: play, pause,
stop, export. Drawn once here, used everywhere on the panel -- the
transport buttons take their icons from :func:`make_icon`, never
from a text glyph.

Generic-only: the icons are transport marks, not practical marks;
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

ICON_NAMES = ("play", "pause", "stop", "export")


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


_PATH_BUILDERS = {
    "play": _path_play,
    "pause": _path_pause,
    "stop": _path_stop,
    "export": _path_export,
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
