"""Vector icons drawn with QPainter, so they are crisp at any DPI, follow the
theme colours and need no image files."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF)

_S = 24.0  # design grid


def _pen(color, w=2.0):
    p = QPen(QColor(color), w)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return p


def _poly(pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _draw(name: str, p: QPainter, c: QColor):
    stroke = _pen(c)
    p.setPen(stroke)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if name == "new":
        path = QPainterPath()
        path.moveTo(6, 3); path.lineTo(14, 3); path.lineTo(19, 8); path.lineTo(19, 21)
        path.lineTo(6, 21); path.closeSubpath()
        p.drawPath(path)
        p.drawPolyline(_poly([(14, 3), (14, 8), (19, 8)]))
    elif name == "open":
        path = QPainterPath()
        path.moveTo(3, 19); path.lineTo(3, 6); path.lineTo(9, 6); path.lineTo(11, 8)
        path.lineTo(19, 8); path.lineTo(19, 11)
        p.drawPath(path)
        p.drawPolyline(_poly([(3, 19), (6, 11), (22, 11), (19, 19), (3, 19)]))
    elif name == "save":
        p.drawRoundedRect(QRectF(4, 4, 16, 16), 2, 2)
        p.drawRect(QRectF(8, 4, 7, 5))
        p.drawRect(QRectF(7, 13, 10, 7))
    elif name == "assemble":  # gear
        p.drawEllipse(QPointF(12, 12), 4, 4)
        p.drawEllipse(QPointF(12, 12), 7.5, 7.5)
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(QPointF(12 + 7.5 * math.cos(a), 12 + 7.5 * math.sin(a)),
                       QPointF(12 + 10 * math.cos(a), 12 + 10 * math.sin(a)))
    elif name == "run":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawPolygon(_poly([(7, 4), (20, 12), (7, 20)]))
    elif name == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(6, 5, 4.5, 14), 1.2, 1.2)
        p.drawRoundedRect(QRectF(13.5, 5, 4.5, 14), 1.2, 1.2)
    elif name == "stop":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(5.5, 5.5, 13, 13), 2, 2)
    elif name == "restart":
        p.drawArc(QRectF(4, 4, 16, 16), 40 * 16, 280 * 16)
        p.setBrush(c)
        p.drawPolygon(_poly([(20, 3), (20.5, 10), (13.5, 7.5)]))
    elif name in ("step_in", "step_out", "step_over"):
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        if name == "step_over":
            p.drawEllipse(QPointF(12, 19), 2.2, 2.2)
            p.setPen(stroke); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(3.5, 5, 17, 13), 20 * 16, 140 * 16)
            p.setBrush(c)
            p.drawPolygon(_poly([(21, 4), (21.5, 11), (15, 9)]))
            p.setPen(Qt.PenStyle.NoPen)
        else:
            p.drawEllipse(QPointF(12, 19.5), 2.2, 2.2)
            p.setPen(stroke); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(12, 3), QPointF(12, 13))
            p.setBrush(c)
            if name == "step_in":
                p.drawPolygon(_poly([(7.5, 10), (16.5, 10), (12, 15.5)]))
            else:
                p.drawPolygon(_poly([(7.5, 8), (16.5, 8), (12, 2.5)]))
                p.setPen(Qt.PenStyle.NoPen)
    elif name == "run_cursor":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawPolygon(_poly([(5, 4), (15, 11), (5, 18)]))
        p.drawRoundedRect(QRectF(16, 5, 3, 13), 1, 1)
    elif name == "breakpoint":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(12, 12), 6.5, 6.5)
    elif name == "clear_bp":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(11, 11), 6, 6)
        p.drawLine(QPointF(15, 15), QPointF(21, 21))
    elif name == "theme":
        p.drawEllipse(QPointF(12, 12), 8, 8)
        path = QPainterPath()
        path.moveTo(12, 4); path.arcTo(QRectF(4, 4, 16, 16), 90, -180); path.closeSubpath()
        p.setBrush(c)
        p.drawPath(path)
    elif name == "find":
        p.drawEllipse(QPointF(10.5, 10.5), 6, 6)
        p.drawLine(QPointF(15, 15), QPointF(21, 21))
    elif name == "help":
        p.drawEllipse(QPointF(12, 12), 9, 9)
        f = QFont(); f.setBold(True); f.setPixelSize(15)
        p.setFont(f)
        p.drawText(QRectF(0, 0, 24, 24), Qt.AlignmentFlag.AlignCenter, "?")
    elif name == "bolt":
        p.setBrush(c)
        p.drawPolygon(_poly([(13.5, 2.5), (5.5, 13), (11, 13), (9.5, 21.5), (18.5, 10.5), (12.5, 10.5)]))
    elif name in ("error", "warning", "info"):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        if name == "warning":
            p.drawPolygon(_poly([(12, 3), (22, 20), (2, 20)]))
        else:
            p.drawEllipse(QPointF(12, 12), 9.5, 9.5)
        p.setPen(QPen(QColor("#ffffff"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if name == "error":
            p.drawLine(QPointF(8.5, 8.5), QPointF(15.5, 15.5)); p.drawLine(QPointF(15.5, 8.5), QPointF(8.5, 15.5))
        elif name == "warning":
            p.drawLine(QPointF(12, 9), QPointF(12, 14.5)); p.drawPoint(QPointF(12, 17.3))
        else:
            p.drawLine(QPointF(12, 11), QPointF(12, 16.5)); p.drawPoint(QPointF(12, 7.6))
    elif name == "instructions":  # a list with a plus: pick an instruction to insert
        p.drawRoundedRect(QRectF(3.5, 4, 17, 16), 2, 2)
        p.drawLine(QPointF(7, 9), QPointF(12, 9)); p.drawLine(QPointF(7, 13), QPointF(10.5, 13))
        p.drawLine(QPointF(7, 17), QPointF(12, 17))
        p.drawLine(QPointF(16, 11), QPointF(16, 17)); p.drawLine(QPointF(13.3, 14), QPointF(18.7, 14))
    elif name == "folder_examples":
        p.drawRoundedRect(QRectF(4, 4, 16, 16), 2, 2)
        p.drawLine(QPointF(8, 9), QPointF(16, 9)); p.drawLine(QPointF(8, 13), QPointF(16, 13))
        p.drawLine(QPointF(8, 17), QPointF(13, 17))
    else:  # unknown -> dot
        p.setBrush(c)
        p.drawEllipse(QPointF(12, 12), 3, 3)


def _render(name: str, color: QColor, px: int) -> QPixmap:
    dpr = 2
    img = QImage(px * dpr, px * dpr, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    p.scale(px * dpr / _S, px * dpr / _S)
    _draw(name, p, color)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def make_icon(name: str, color: str | QColor, disabled: str | QColor = "#808080", px: int = 22) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_render(name, QColor(color), px), QIcon.Mode.Normal)
    icon.addPixmap(_render(name, QColor(disabled), px), QIcon.Mode.Disabled)
    return icon


def app_icon() -> QIcon:
    """The application icon: a dark chip with a green '85'."""
    icon = QIcon()
    for px in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(px))
    return icon


def app_pixmap(px: int) -> QPixmap:
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    s = px / 64.0
    p.scale(s, s)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1b2230"))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 12, 12)
    # chip pins
    p.setBrush(QColor("#4f9cff"))
    for i in range(5):
        x = 13 + i * 9.5
        p.drawRoundedRect(QRectF(x, 5, 4, 7), 1, 1)
        p.drawRoundedRect(QRectF(x, 52, 4, 7), 1, 1)
    p.setBrush(QColor("#232d3f"))
    p.drawRoundedRect(QRectF(9, 12, 46, 40), 6, 6)
    f = QFont("DejaVu Sans Mono")
    f.setBold(True)
    f.setPixelSize(22)
    p.setFont(f)
    p.setPen(QColor("#3fe08d"))
    p.drawText(QRectF(9, 12, 46, 40), Qt.AlignmentFlag.AlignCenter, "85")
    p.end()
    return QPixmap.fromImage(img)
