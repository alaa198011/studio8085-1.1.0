"""Scale the monospace fonts of the dock panels with the "Interface font size" setting.

Most panels (registers, stack, memory, listing...) use their own 10 pt monospace font, so the
application-wide font size does not reach them. ``scale_monospace`` shifts those fonts by ``delta``
points and grows row heights and column widths with them.

It is *idempotent*: the first time a widget/item is seen its original size is remembered, so calling
it again (for example after the stylesheet was re-applied, which resets widget fonts in Qt) always
gives ``original + delta`` rather than accumulating.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QWidget

_BASE_PT = "_fs_base_pt"
_BASE_ROW = "_fs_base_row"
_BASE_COLS = "_fs_base_cols"
ITEM_BASE_ROLE = Qt.ItemDataRole.UserRole + 77
REFERENCE_PT = 10  # the size the panels were designed for


_MONO_HINTS = (QFont.StyleHint.Monospace, QFont.StyleHint.TypeWriter)


def _monospace(font: QFont) -> bool:
    # ``monospace_font()`` tags every panel font with the Monospace style hint. Check that request
    # first: ``QFontInfo.fixedPitch()`` describes whatever font Qt *resolved*, which depends on the
    # fonts installed (with an empty font database - e.g. the offscreen platform on Windows - nothing
    # resolves as fixed pitch and the panels silently stopped scaling).
    return font.styleHint() in _MONO_HINTS or QFontInfo(font).fixedPitch()


def _scaled(font: QFont, base: int, delta: int) -> QFont:
    f = QFont(font)
    f.setPointSize(max(6, base + delta))
    return f


def scale_monospace(root: QWidget, delta: int, geometry: bool = True):
    """Set every monospace font under ``root`` to its original size + ``delta`` points."""
    factor = max(0.6, (REFERENCE_PT + delta) / REFERENCE_PT)
    for w in [root, *root.findChildren(QWidget)]:
        f = w.font()
        if _monospace(f):
            base = w.property(_BASE_PT)
            if base is None:
                base = f.pointSize()
                w.setProperty(_BASE_PT, base)
            if f.pointSize() != max(6, base + delta):
                w.setFont(_scaled(f, base, delta))
        if isinstance(w, QTableWidget):
            _scale_items(w, delta)
        if isinstance(w, QAbstractItemView) and hasattr(w, "verticalHeader"):
            _scale_geometry(w, factor, geometry)
    for m in root.findChildren(QAbstractTableModel):
        font = getattr(m, "font", None)
        if isinstance(font, QFont):
            base = m.property(_BASE_PT)
            if base is None:
                base = font.pointSize()
                m.setProperty(_BASE_PT, base)
            if font.pointSize() != max(6, base + delta):
                m.font = _scaled(font, base, delta)
                m.layoutChanged.emit()


def _scale_items(table: QTableWidget, delta: int):
    for r in range(table.rowCount()):
        for c in range(table.columnCount()):
            it = table.item(r, c)
            if it is None:
                continue
            f = it.font()
            if not _monospace(f):
                continue
            base = it.data(ITEM_BASE_ROLE)
            if base is None:
                base = f.pointSize()
                it.setData(ITEM_BASE_ROLE, base)
            if f.pointSize() != max(6, base + delta):
                it.setFont(_scaled(f, base, delta))


def _scale_geometry(view: QAbstractItemView, factor: float, apply: bool):
    vh = view.verticalHeader()
    if vh is None:
        return
    if view.property(_BASE_ROW) is None:
        view.setProperty(_BASE_ROW, vh.defaultSectionSize())
        hh = view.horizontalHeader()
        view.setProperty(_BASE_COLS, [hh.sectionSize(i) for i in range(hh.count())] if hh else [])
    if not apply:
        return
    vh.setDefaultSectionSize(max(18, round(view.property(_BASE_ROW) * factor)))
    hh = view.horizontalHeader()
    cols = view.property(_BASE_COLS) or []
    if hh and cols:
        for i, w in enumerate(cols[:-1]):  # the last column stretches
            if i < hh.count() and w:
                hh.resizeSection(i, round(w * factor))
