"""The "Interactive CPU Architecture" dock (Phase 2): a vector block diagram of the 8085 programmer's model.

Layering: this module only DRAWS. It receives immutable ``CpuState`` / ``StepRecord`` / ``KitView`` objects from
``core/visual.py`` and never touches the CPU, the Machine or the debugger. Animation is a UI timer that replays a
stored record; the real execution has already finished before the first frame is drawn.

Everything is QPainter vector graphics inside a QGraphicsView, so it stays sharp at any zoom or display scale.
The diagram is a conceptual teaching model of the 8085 programmer's view (Intel 8085 terminology). It is not a
bus-cycle or cycle-accurate model, and the Instruction Register / Decoder box and the data paths are conceptual.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from html import escape

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGraphicsEllipseItem, QGraphicsItem, QGraphicsObject,
                               QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSplitter, QTabWidget, QTextBrowser, QVBoxLayout,
                               QWidget)

from ..core.visual import (CONCEPTUAL, FLAG_ORDER, PAIRS, REG_ORDER, CpuState, Flow, KitView, StepRecord)
from .cpulabs import LabGuidePanel
from .docks import mono
from .themes import DARK, Theme

TITLE = "Interactive CPU Architecture"
SCENE_W, SCENE_H = 1030, 710

# ------------------------------------------------------------------ geometry
_REG_W, _REG_H = 100, 85
GEOM: dict[str, tuple[float, float, float, float]] = {
    "IR": (34, 20, 240, 100), "A": (290, 20, 160, 100), "ALU": (500, 20, 160, 100), "FLAGS": (710, 20, 290, 100),
    "B": (40, 215, _REG_W, _REG_H), "C": (144, 215, _REG_W, _REG_H),
    "D": (276, 215, _REG_W, _REG_H), "E": (380, 215, _REG_W, _REG_H),
    "H": (512, 215, _REG_W, _REG_H), "L": (616, 215, _REG_W, _REG_H),
    "BC": (34, 205, 216, 125), "DE": (270, 205, 216, 125), "HL": (506, 205, 216, 125),
    "PC": (746, 205, 120, 125), "SP": (880, 205, 120, 125),
    "MEMIF": (34, 430, 260, 90), "IOIF": (480, 430, 300, 90),
    "MEM": (34, 570, 410, 80), "PORT_IN": (480, 570, 150, 80), "PORT_OUT": (640, 570, 160, 80),
}
DATA_Y, ADDR_Y = 170.0, 380.0
RISER_L, RISER_R, ADDR_RISER = 10.0, 1015.0, 22.0


def _cx(node: str) -> float:
    x, _, w, _ = GEOM[node]
    return x + w / 2


def _bottom(node: str) -> float:
    return GEOM[node][1] + GEOM[node][3]


def _top(node: str) -> float:
    return GEOM[node][1]


def _data_tap(node: str) -> list[QPointF] | None:
    """Points from the node to the 8-bit internal data path, ending ON the bus line."""
    P = QPointF
    if node in ("IR", "A", "ALU", "FLAGS"):
        return [P(_cx(node), _bottom(node)), P(_cx(node), DATA_Y)]
    if node in REG_ORDER[1:]:
        return [P(_cx(node), _top(node)), P(_cx(node), DATA_Y)]
    if node in PAIRS:
        return [P(_cx(node), _top(node)), P(_cx(node), DATA_Y)]
    if node == "MEM":
        return [P(100, _top("MEM")), P(100, 545), P(RISER_L, 545), P(RISER_L, DATA_Y)]
    if node in ("PORT_IN", "PORT_OUT"):
        return [P(_cx(node), _top(node)), P(_cx(node), 545), P(RISER_R, 545), P(RISER_R, DATA_Y)]
    return None


def _addr_tap(node: str) -> list[QPointF] | None:
    """Points from the node to the 16-bit address path, ending ON that bus line."""
    P = QPointF
    if node in ("PC", "SP") or node in PAIRS:
        return [P(_cx(node), _bottom(node)), P(_cx(node), ADDR_Y)]
    if node == "IR":
        x, y, _, h = GEOM["IR"]
        return [P(x, y + h / 2), P(ADDR_RISER, y + h / 2), P(ADDR_RISER, ADDR_Y)]
    if node == "MEM":
        return [P(340, _top("MEM")), P(340, ADDR_Y)]
    return None


_DIRECT = {  # (src, dst): (start, end) for the short arrows between neighbouring blocks
    ("A", "ALU"): ((450, 45), (500, 45)), ("ALU", "A"): ((500, 80), (450, 80)),
    ("ALU", "FLAGS"): ((660, 45), (710, 45)), ("FLAGS", "ALU"): ((710, 80), (660, 80)),
}
_ADDR_NODES = {"PC", "SP", "BC", "DE", "HL", "IR", "MEM"}


def route(flow: Flow) -> QPainterPath:
    """The drawn path of a flow: along the data path or the address path, or a short direct arrow."""
    src, dst = flow.src, flow.dst
    path = QPainterPath()
    if (src, dst) in _DIRECT:
        a, b = _DIRECT[(src, dst)]
        path.moveTo(*a)
        path.lineTo(*b)
        return path
    use_addr = flow.kind in ("addr16", "data16") and src in _ADDR_NODES and dst in _ADDR_NODES
    tap = _addr_tap if use_addr else _data_tap
    y = ADDR_Y if use_addr else DATA_Y
    if src == dst:
        x, ya, w, _ = GEOM[src]
        path.moveTo(x + w * 0.35, ya)
        path.cubicTo(x + w * 0.35, ya - 26, x + w * 0.65, ya - 26, x + w * 0.65, ya)
        return path
    a, b = tap(src), tap(dst)
    if a is None or b is None:
        a, b = _data_tap(src), _data_tap(dst)
        y = DATA_Y
    if a is None or b is None:
        return path
    pts = list(a) + list(reversed(b))
    # drop the duplicate where the two taps meet on the bus line
    path.moveTo(pts[0])
    for p in pts[1:]:
        if p != path.currentPosition():
            path.lineTo(p)
    return path


# ------------------------------------------------------------------- helpers
def os_prefers_reduced_motion() -> bool:
    """Windows: 'Show animations in Windows' off; any platform: S85_REDUCE_MOTION=1."""
    if os.environ.get("S85_REDUCE_MOTION", "") not in ("", "0"):
        return True
    if sys.platform == "win32":
        try:
            flag = ctypes.c_int(1)
            ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)  # SPI_GETCLIENTAREAANIMATION
            return bool(ok) and flag.value == 0
        except Exception:
            return False
    return False


def hexs(v: int, bits_: int) -> str:
    return f"{v:0{bits_ // 4}X}h"


def bins(v: int, bits_: int) -> str:
    s = f"{v:0{bits_}b}"
    return " ".join(s[i:i + 4] for i in range(0, bits_, 4))


NODE_INFO: dict[str, tuple[str, str]] = {
    "A": ("Accumulator A", "The 8-bit accumulator. Most arithmetic and logic results go here; IN loads it and OUT sends it."),
    "B": ("Register B", "8-bit general purpose register; B and C form the pair BC."),
    "C": ("Register C", "8-bit general purpose register; B and C form the pair BC."),
    "D": ("Register D", "8-bit general purpose register; D and E form the pair DE."),
    "E": ("Register E", "8-bit general purpose register; D and E form the pair DE."),
    "H": ("Register H", "High byte of HL. HL is the memory pointer used by the M operand."),
    "L": ("Register L", "Low byte of HL. HL is the memory pointer used by the M operand."),
    "BC": ("Register pair BC", "B (high byte) and C (low byte) used together as one 16-bit value."),
    "DE": ("Register pair DE", "D (high byte) and E (low byte) used together as one 16-bit value."),
    "HL": ("Register pair HL", "H (high byte) and L (low byte). HL addresses memory for the M operand."),
    "PC": ("Program Counter PC", "16-bit address of the next instruction."),
    "SP": ("Stack Pointer SP", "16-bit address of the top of the stack in memory. PUSH/CALL decrease it, POP/RET increase it."),
    "FLAGS": ("Flags S Z AC P CY", "Sign, Zero, Auxiliary Carry, Parity and Carry flags set by the ALU."),
    "ALU": ("Arithmetic Logic Unit", "Performs the arithmetic and logic operations and sets the flags."),
    "IR": ("Instruction Register / Decoder (conceptual)", "Holds the opcode being executed. Conceptual: this simulator "
           "is instruction-level and does not model the decoder."),
    "MEMIF": ("Memory interface", "Where the CPU reads and writes memory. Conceptual block (bus signals are not simulated)."),
    "IOIF": ("I/O interface", "Where IN and OUT reach the 256 input/output ports. Conceptual block."),
    "MEM": ("Memory (64K x 8)", "The simulated 64K memory."),
    "PORT_IN": ("Input port", "The port read by IN. With the Trainer Kit connected this is the 8 switches."),
    "PORT_OUT": ("Output port", "The port written by OUT. With the Trainer Kit connected this is the 8 LEDs."),
}
_CONCEPTUAL_NODES = {"IR", "MEMIF", "IOIF"}
_ROLE_TAG = {"src": "SRC", "dst": "DST", "both": "SRC+DST"}
_KIND_STYLE = {"data8": "info", "data16": "info", "addr16": "accent", "addr8": "accent", "ctl": "warning"}


class Palette:
    """Theme colours used by the diagram (every key falls back to the Dark theme)."""

    def __init__(self, theme: Theme | None):
        self.theme = theme
        self.hc = theme is not None and theme.name == "High Contrast"

    def c(self, key: str) -> QColor:
        t = self.theme
        if t is not None and key in t.colors:
            return QColor(t.colors[key])
        return QColor(DARK[key])


# --------------------------------------------------------------------- items
class NodeItem(QGraphicsObject):
    """One block of the diagram. Focusable (Tab / arrow keys), has a tooltip, and shows state as text + outline."""

    focused = Signal(str)

    def __init__(self, nid: str, pal: Palette, panel: "CpuArchitecturePanel"):
        super().__init__()
        self.nid = nid
        self.pal = pal
        self.panel = panel
        x, y, w, h = GEOM[nid]
        self.rect = QRectF(0, 0, w, h)
        self.setPos(x, y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setAcceptHoverEvents(True)
        self.role = ""
        self.changed = False
        self.dim = False
        self.value: tuple[int, int] | None = None  # (value, bits) currently shown
        self.old: int | None = None
        self.extra: list[str] = []
        self.flags_vals: tuple[int, ...] | None = None
        self.flags_changed: frozenset[str] = frozenset()
        self.tag = ""
        self.masked = False
        self.leds: int | None = None  # 8-bit pattern drawn as dots (output port node)
        self.decimal = False
        title, desc = NODE_INFO.get(nid, (nid, ""))
        self.title = title
        self.setToolTip(f"{title}\n{desc}")
        self.setZValue(2)

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-4, -4, 4, 4)

    # state --------------------------------------------------------------
    def describe(self) -> str:
        parts = [self.title]
        if self.masked:
            parts.append("value hidden until you predict")
        elif self.value is not None:
            v, b = self.value
            parts.append(f"value {hexs(v, b)}, binary {bins(v, b)}")
        if self.nid == "FLAGS" and self.flags_vals is not None and not self.masked:
            parts.append(", ".join(f"{n}={v}" for n, v in zip(FLAG_ORDER, self.flags_vals)))
        if self.role:
            parts.append({"src": "source of a data movement", "dst": "destination of a data movement",
                          "both": "source and destination"}[self.role])
        if self.changed:
            parts.append("changed by the last step" + (f", was {hexs(self.old, self.value[1])}"
                                                          if self.old is not None and self.value else ""))
        if self.tag:
            parts.append(self.tag)
        parts.extend(self.extra)
        if self.nid in _CONCEPTUAL_NODES:
            parts.append("conceptual block")
        return ". ".join(parts)

    def set_state(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.setToolTip(self.describe() + "\n" + NODE_INFO.get(self.nid, ("", ""))[1])
        self.update()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focused.emit(self.describe())
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.panel.focus_step(self, 1)
        elif e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.panel.focus_step(self, -1)
        else:
            super().keyPressEvent(e)

    # painting -----------------------------------------------------------
    def paint(self, p: QPainter, _opt, _w=None):
        pal = self.pal
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        active = bool(self.role) or self.changed
        base = pal.c("panel")
        text = pal.c("text") if (active or not self.dim) else pal.c("text_dim")
        border = pal.c("border")
        width = 1.0
        if self.role == "src":
            border, width = pal.c("info"), 3.0
        elif self.role == "dst":
            border, width = pal.c("ok"), 3.0
        elif self.role == "both":
            border, width = pal.c("accent"), 3.0
        if self.changed:
            width = max(width, 3.0)
            if not self.role:
                border = pal.c("exec_arrow")
        if pal.hc:
            width += 1
        pen = QPen(border, width)
        if self.nid in _CONCEPTUAL_NODES:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        fill = QColor(base)
        if self.changed:
            fill = QColor(pal.c("ok"))
            fill.setAlpha(46)
            fill = _over(base, fill)
        p.setBrush(QBrush(fill))
        r = self.rect
        p.drawRoundedRect(r, 7, 7)
        if self.hasFocus():
            fp = QPen(pal.c("accent"), 2, Qt.PenStyle.DotLine)
            p.setPen(fp)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), 9, 9)
        p.setPen(text)
        tf = QFont(p.font())
        tf.setBold(True)
        tf.setPointSizeF(10)
        p.setFont(tf)
        short = {"A": "Accumulator A", "ALU": "ALU", "IR": "Instruction Register / Decoder",
                 "MEMIF": "Memory interface", "IOIF": "I/O interface", "MEM": "Memory (64K x 8)",
                 "PC": "PC", "SP": "SP", "FLAGS": "Flags"}.get(self.nid, self.nid)
        if self.nid in ("PORT_IN", "PORT_OUT"):
            short = self.title
        p.drawText(QRectF(8, 4, r.width() - (12 if len(short) > 6 and self.nid not in ("PORT_IN", "PORT_OUT") else 54), 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, short)
        # role / change badges: text, so the meaning never depends on colour
        badge = []
        if self.role:
            badge.append(_ROLE_TAG[self.role])
        if self.changed:
            badge.append("Δ")
        if badge:
            bf = QFont(p.font())
            bf.setPointSizeF(8)
            p.setFont(bf)
            long_title = len(short) > 6 and self.nid not in ("PORT_IN", "PORT_OUT")
            by = r.height() - 20 if long_title else 4
            p.drawText(QRectF(r.width() - 78, by, 72, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       " ".join(badge))
        mf = mono(10)
        mf.setBold(True)
        small = mono(8)
        y = 26.0
        p.setFont(mf)
        if self.nid == "IR":
            p.setFont(small)
            p.drawText(QRectF(8, 24, r.width() - 16, 18), Qt.AlignmentFlag.AlignLeft, "conceptual - not a simulated circuit")
            p.setFont(mf)
            p.drawText(QRectF(8, 44, r.width() - 16, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self.extra[0] if self.extra else "")
            p.setFont(small)
            for i, line in enumerate(self.extra[1:3]):
                p.drawText(QRectF(8, 66 + 14 * i, r.width() - 16, 14), Qt.AlignmentFlag.AlignLeft, line)
            return
        if self.nid == "FLAGS":
            self._paint_flags(p, mf, small, text)
            return
        if self.nid in ("MEMIF", "IOIF", "ALU"):
            p.setFont(small)
            for i, line in enumerate(self.extra[:4] or ([""] if self.nid != "ALU" else ["arithmetic + logic"])):
                p.drawText(QRectF(8, 28 + 15 * i, r.width() - 16, 15), Qt.AlignmentFlag.AlignLeft, line)
            if self.nid in ("MEMIF", "IOIF"):
                p.drawText(QRectF(8, r.height() - 20, r.width() - 16, 16), Qt.AlignmentFlag.AlignLeft,
                           "conceptual block")
            elif self.tag:
                p.setFont(mf)
                p.drawText(QRectF(8, 50, r.width() - 16, 20), Qt.AlignmentFlag.AlignLeft, self.tag)
            return
        if self.nid in ("MEM", "PORT_IN", "PORT_OUT"):
            self._paint_endpoint(p, mf, small)
            return
        # registers / pairs / PC / SP
        if self.masked:
            p.drawText(QRectF(8, y, r.width() - 16, 20), Qt.AlignmentFlag.AlignLeft, "??")
            p.setFont(small)
            p.drawText(QRectF(8, y + 22, r.width() - 16, 14), Qt.AlignmentFlag.AlignLeft, "hidden until you predict")
            return
        if self.value is not None:
            v, b = self.value
            p.drawText(QRectF(8, y, r.width() - 16, 20), Qt.AlignmentFlag.AlignLeft, hexs(v, b))
            p.setFont(small)
            if b == 8:
                p.drawText(QRectF(8, y + 22, r.width() - 12, 14), Qt.AlignmentFlag.AlignLeft, bins(v, b))
                yy = y + 38
            else:
                p.drawText(QRectF(8, y + 22, r.width() - 12, 14), Qt.AlignmentFlag.AlignLeft, bins(v >> 8, 8))
                p.drawText(QRectF(8, y + 36, r.width() - 12, 14), Qt.AlignmentFlag.AlignLeft, bins(v & 255, 8))
                yy = y + 52
            if self.decimal:
                p.drawText(QRectF(8, yy, r.width() - 12, 14), Qt.AlignmentFlag.AlignLeft, f"= {v}")
                yy += 14
            if self.changed and self.old is not None and r.height() - yy >= 12:
                p.drawText(QRectF(8, yy, r.width() - 12, 14), Qt.AlignmentFlag.AlignLeft, f"was {hexs(self.old, b)}")
            if self.tag and r.height() - yy >= 12 and not (self.changed and self.old is not None):
                p.drawText(QRectF(8, yy, r.width() - 12, 14), Qt.AlignmentFlag.AlignLeft, self.tag)

    def _paint_flags(self, p: QPainter, mf: QFont, small: QFont, text: QColor):
        pal = self.pal
        r = self.rect
        n = len(FLAG_ORDER)
        cw = (r.width() - 16) / n
        for i, name in enumerate(FLAG_ORDER):
            x = 8 + i * cw
            box = QRectF(x + 3, 30, cw - 6, 62)
            chg = name in self.flags_changed
            p.setPen(QPen(pal.c("exec_arrow") if chg else pal.c("border"), 3 if chg else 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 5, 5)
            p.setPen(text)
            p.setFont(small)
            p.drawText(QRectF(box.x(), box.y() + 3, box.width(), 14), Qt.AlignmentFlag.AlignHCenter,
                       name + (" Δ" if chg else ""))
            p.setFont(mf)
            val = "?" if self.masked or self.flags_vals is None else str(self.flags_vals[i])
            p.drawText(QRectF(box.x(), box.y() + 20, box.width(), 22), Qt.AlignmentFlag.AlignHCenter, val)
            p.setFont(small)
            on = self.flags_vals is not None and not self.masked and self.flags_vals[i]
            p.drawText(QRectF(box.x(), box.y() + 44, box.width(), 14), Qt.AlignmentFlag.AlignHCenter,
                       "set" if on else "clear" if not self.masked else "")

    def _paint_endpoint(self, p: QPainter, mf: QFont, small: QFont):
        r = self.rect
        p.setFont(small)
        lines = self.extra[:3]
        if self.masked:
            lines = ["value hidden until you predict"]
        for i, line in enumerate(lines):
            p.drawText(QRectF(8, 26 + 14 * i, r.width() - 12, 14), Qt.AlignmentFlag.AlignLeft, line)
        if self.leds is not None and not self.masked:  # eight LED dots: filled = lit (shape, not just colour)
            on, off = self.pal.c("led_on"), self.pal.c("led_off")
            for i, bit in enumerate(range(7, -1, -1)):
                lit = self.leds >> bit & 1
                p.setPen(QPen(self.pal.c("text"), 1))
                p.setBrush(QBrush(on if lit else off))
                p.drawEllipse(QRectF(8 + i * 17, 62, 12, 12))
                if not lit:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QRectF(8 + i * 17 + 4, 66, 4, 4))


def _over(base: QColor, top: QColor) -> QColor:
    a = top.alphaF()
    return QColor(int(base.red() * (1 - a) + top.red() * a), int(base.green() * (1 - a) + top.green() * a),
                  int(base.blue() * (1 - a) + top.blue() * a))


class PairFrame(QGraphicsObject):
    """The frame around B+C / D+E / H+L with the 16-bit pair value in its bottom strip."""

    def __init__(self, nid: str, pal: Palette):
        super().__init__()
        self.nid, self.pal = nid, pal
        x, y, w, h = GEOM[nid]
        self.rect = QRectF(0, 0, w, h)
        self.setPos(x, y)
        self.setZValue(1)
        self.role = ""
        self.changed = False
        self.value: int | None = None
        self.masked = False
        self.decimal = False
        self.setToolTip(f"{NODE_INFO[nid][0]}\n{NODE_INFO[nid][1]}")

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-3, -3, 3, 3)

    def set_state(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.update()

    def paint(self, p: QPainter, _o, _w=None):
        pal = self.pal
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        col, width = pal.c("border"), 1.0
        if self.role:
            col, width = {"src": pal.c("info"), "dst": pal.c("ok"), "both": pal.c("accent")}[self.role], 3.0
        if pal.hc:
            width += 1
        p.setPen(QPen(col, width))
        p.setBrush(QBrush(pal.c("alt_base")))
        p.drawRoundedRect(self.rect, 9, 9)
        p.setPen(pal.c("text"))
        f = mono(10)
        f.setBold(True)
        p.setFont(f)
        val = "????h" if self.masked or self.value is None else hexs(self.value, 16)
        label = f"{self.nid} = {val}" + (f"  ({self.value})" if self.decimal and self.value is not None and not self.masked else "")
        tag = (" " + _ROLE_TAG[self.role]) if self.role else ""
        tag += " Δ" if self.changed else ""
        p.drawText(QRectF(8, self.rect.height() - 25, self.rect.width() - 16, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label + tag)


class FlowItem(QGraphicsPathItem):
    """An arrow for one conceptual data movement. Solid = confirmed by the state diff; dashed = conceptual only."""

    def __init__(self, flow: Flow, pal: Palette):
        super().__init__()
        self.flow = flow
        self.pal = pal
        self.setZValue(3)
        path = route(flow)
        self.setPath(path)
        self.setToolTip(f"{flow.label}\n({'observed in the state change' if flow.observed else CONCEPTUAL})")
        self.head = QGraphicsPathItem(self)
        self.dot = QGraphicsEllipseItem(-5, -5, 10, 10, self)
        self.dot.setVisible(False)
        self.restyle(pal)
        self._arrow()

    def _arrow(self):
        path = self.path()
        n = path.elementCount()
        if n < 2:
            return
        tip = path.elementAt(n - 1)
        prev = path.elementAt(n - 2)
        tip_p, prev_p = QPointF(tip.x, tip.y), QPointF(prev.x, prev.y)
        d = tip_p - prev_p
        ln = (d.x() ** 2 + d.y() ** 2) ** 0.5 or 1.0
        ux, uy = d.x() / ln, d.y() / ln
        left = QPointF(tip_p.x() - 11 * ux + 6 * uy, tip_p.y() - 11 * uy - 6 * ux)
        right = QPointF(tip_p.x() - 11 * ux - 6 * uy, tip_p.y() - 11 * uy + 6 * ux)
        poly = QPainterPath()
        poly.addPolygon(QPolygonF([tip_p, left, right, tip_p]))
        self.head.setPath(poly)

    def restyle(self, pal: Palette):
        self.pal = pal
        col = pal.c(_KIND_STYLE.get(self.flow.kind, "info"))
        pen = QPen(col, 4.0 if self.flow.observed else 3.0)
        if not self.flow.observed:
            pen.setStyle(Qt.PenStyle.DashLine)
        if self.flow.kind == "ctl":
            pen.setStyle(Qt.PenStyle.DashDotLine)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setPen(pen)
        self.head.setPen(QPen(col, 1))
        self.head.setBrush(QBrush(col))
        self.dot.setBrush(QBrush(pal.c("text")))
        self.dot.setPen(QPen(col, 2))

    def place_dot(self, frac: float):
        self.dot.setPos(self.path().pointAtPercent(max(0.0, min(1.0, frac))))
        self.dot.setVisible(True)


class DiagramView(QGraphicsView):
    zoom_requested = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("CPU architecture diagram")
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_requested.emit(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)
            e.accept()
        else:
            super().wheelEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_requested.emit(1.15)
        elif k in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.zoom_requested.emit(1 / 1.15)
        elif k == Qt.Key.Key_0:
            self.zoom_requested.emit(0.0)  # 0.0 = fit
        else:
            super().keyPressEvent(e)


# ---------------------------------------------------------------- the panel
SPEEDS = [("0.5x (slow)", 0.5), ("1x", 1.0), ("2x", 2.0), ("4x (fast)", 4.0)]
PHASE_MS = 650
MIN_FIT_SCALE = 0.55
LIVE_INTERVAL = 0.10  # seconds: coalesce live refreshes while a program runs


class CpuArchitecturePanel(QWidget):
    """The dock contents. Pure view: feed it with ``show_live``, ``show_record`` and ``set_kit``."""

    explain_changed = Signal(bool)
    settings_changed = Signal()
    visible_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme: Theme | None = None
        self.pal = Palette(None)
        self.explain_mode = True
        self.animate = True
        self.reduce_motion = os_prefers_reduced_motion()
        self.decimal = False
        self.speed = 1.0
        self._fit = True
        self._scale = 1.0
        self._concealed = False
        self._conceal_ports: tuple[int, ...] = ()
        self._rec: StepRecord | None = None
        self._state: CpuState | None = None
        self._kit = KitView()
        self._anim: dict | None = None
        self._paused = False
        self._last_live = 0.0
        self._pending_live: CpuState | None = None
        self.redraws = 0
        self.setMinimumSize(520, 420)

        self.scene = QGraphicsScene(0, 0, SCENE_W, SCENE_H, self)
        self.view = DiagramView(self.scene)
        self.view.setMinimumHeight(260)
        self.view.zoom_requested.connect(self.zoom_by)
        self.nodes: dict[str, NodeItem] = {}
        self.frames: dict[str, PairFrame] = {}
        self.flow_items: list[FlowItem] = []
        self._build_scene()

        # controls ---------------------------------------------------------
        self.explain_cb = QCheckBox("Explain Execution")
        self.explain_cb.setChecked(True)
        self.explain_cb.setToolTip("On: Step shows the data flow, before/after values and an explanation.\n"
                                   "Off: the diagram only shows the live register, flag and PC/SP values.")
        self.explain_cb.toggled.connect(self._explain_toggled)
        self.anim_cb = QCheckBox("Animate")
        self.anim_cb.setChecked(True)
        self.anim_cb.setToolTip("Animate the data movement. Off: the finished step is shown at once.")
        self.anim_cb.toggled.connect(self._anim_toggled)
        self.reduce_cb = QCheckBox("Reduce motion")
        self.reduce_cb.setChecked(self.reduce_motion)
        self.reduce_cb.setToolTip("No moving dots: the finished step is shown at once.\n"
                                  "Starts on if the operating system asks for reduced animation.")
        self.reduce_cb.toggled.connect(self._reduce_toggled)
        self.dec_cb = QCheckBox("Decimal")
        self.dec_cb.setToolTip("Also show decimal values (hex and binary are always shown).")
        self.dec_cb.toggled.connect(self._dec_toggled)
        self.speed_combo = QComboBox()
        for label, v in SPEEDS:
            self.speed_combo.addItem(label, v)
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.setAccessibleName("Animation speed")
        self.speed_combo.setToolTip("Animation speed")
        self.speed_combo.currentIndexChanged.connect(self._speed_changed)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setToolTip("Pause / resume the animation (the CPU is never affected)")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setToolTip("Jump to the end of the animation")
        self.skip_btn.clicked.connect(self.skip)
        self.replay_btn = QPushButton("Replay")
        self.replay_btn.setToolTip("Replay the last captured step. The CPU is not executed again.")
        self.replay_btn.clicked.connect(self.replay)
        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.setAccessibleName("Zoom out")
        self.zoom_out_btn.setToolTip("Zoom out (also - key or Ctrl+wheel)")
        self.zoom_out_btn.clicked.connect(lambda: self.zoom_by(1 / 1.15))
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setAccessibleName("Zoom in")
        self.zoom_in_btn.setToolTip("Zoom in (also + key or Ctrl+wheel)")
        self.zoom_in_btn.clicked.connect(lambda: self.zoom_by(1.15))
        self.fit_btn = QPushButton("Fit")
        self.fit_btn.setToolTip("Fit the diagram to the panel (also 0 key)")
        self.fit_btn.clicked.connect(lambda: self.zoom_by(0.0))
        for b in (self.zoom_out_btn, self.zoom_in_btn):
            b.setFixedWidth(34)
        row1 = QHBoxLayout()
        for w in (self.explain_cb, self.anim_cb, self.reduce_cb, self.dec_cb):
            row1.addWidget(w)
        row1.addStretch(1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Speed:"))
        row2.addWidget(self.speed_combo)
        for w in (self.pause_btn, self.skip_btn, self.replay_btn):
            row2.addWidget(w)
        row2.addStretch(1)
        row2.addWidget(self.zoom_out_btn)
        row2.addWidget(self.zoom_in_btn)
        row2.addWidget(self.fit_btn)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Selected block")
        self.status.setObjectName("Dim")
        self.text = QTextBrowser()
        self.text.setAccessibleName("Step explanation")
        self.text.setOpenLinks(False)
        self.text.setMinimumHeight(70)
        self.labs = LabGuidePanel()
        self.tabs = QTabWidget()
        self.tabs.addTab(self.text, "Step explanation")
        self.tabs.addTab(self.labs, "Labs")
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.addWidget(self.view)
        self.split.addWidget(self.tabs)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        self.split.setChildrenCollapsible(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(row1)
        lay.addLayout(row2)
        lay.addWidget(self.split, 1)
        lay.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._flush_live)
        self.setTabOrder(self.explain_cb, self.anim_cb)
        self.set_theme(None)
        self._update_buttons()
        self._show_idle()

    # -------------------------------------------------------------- scene
    def _build_scene(self):
        self.bg = []
        self._static_items: list = []
        self.nodes.clear()
        self.frames.clear()
        for nid in ("BC", "DE", "HL"):
            f = PairFrame(nid, self.pal)
            self.scene.addItem(f)
            self.frames[nid] = f
        order = ["IR", "A", "ALU", "FLAGS", "B", "C", "D", "E", "H", "L", "PC", "SP", "MEMIF", "IOIF", "MEM",
                 "PORT_IN", "PORT_OUT"]
        for nid in order:
            n = NodeItem(nid, self.pal, self)
            n.focused.connect(self._node_focused)
            self.scene.addItem(n)
            self.nodes[nid] = n
        self.caption = QGraphicsSimpleTextItem("")
        self.caption.setPos(34, 662)
        self.caption.setZValue(5)
        self.scene.addItem(self.caption)
        self._draw_background()

    def _draw_background(self):
        for it in self._static_items:
            self.scene.removeItem(it)
        self._static_items.clear()
        pal = self.pal
        P = QPointF
        pen = QPen(pal.c("text_dim"), 2)
        thin = QPen(pal.c("border"), 1.5)

        def line(pts, pn):
            path = QPainterPath(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            it = QGraphicsPathItem(path)
            it.setPen(pn)
            it.setZValue(0)
            self.scene.addItem(it)
            self._static_items.append(it)

        line([P(RISER_L, DATA_Y), P(RISER_R, DATA_Y)], pen)  # 8-bit data path
        line([P(ADDR_RISER, ADDR_Y), P(1000, ADDR_Y)], pen)  # 16-bit address path
        for nid in ("IR", "A", "ALU", "FLAGS", "B", "C", "D", "E", "H", "L", "MEM", "PORT_IN", "PORT_OUT"):
            line(_data_tap(nid), thin)
        for nid in ("PC", "SP", "BC", "DE", "HL", "MEM", "IR"):
            line(_addr_tap(nid), thin)
        line([P(RISER_L, 545), P(RISER_L, 475), P(34, 475)], thin)  # data to the memory interface
        line([P(160, 430), P(160, ADDR_Y)], thin)
        line([P(780, 475), P(RISER_R, 475)], thin)
        line([P(RISER_R, DATA_Y), P(RISER_R, 545)], thin)
        line([P(630, 430), P(630, ADDR_Y)], thin)
        line([P(555, 520), P(555, 570)], thin)
        line([P(720, 520), P(720, 570)], thin)
        line([P(100, 520), P(100, 570)], thin)
        for text, x, y in (("8-bit internal data path (conceptual)", 735, 174),
                           ("16-bit address path (conceptual)", 650, 384)):
            t = QGraphicsSimpleTextItem(text)
            f = QFont(t.font())
            f.setPointSizeF(9)
            f.setItalic(True)
            t.setFont(f)
            t.setBrush(QBrush(pal.c("text_dim")))
            t.setPos(x, y)
            t.setZValue(0)
            self.scene.addItem(t)
            self._static_items.append(t)

    # ------------------------------------------------------------- theme
    def set_theme(self, theme: Theme | None):
        self.theme = theme
        self.pal = Palette(theme)
        for n in self.nodes.values():
            n.pal = self.pal
        for f in self.frames.values():
            f.pal = self.pal
        self._draw_background()
        for fi in self.flow_items:
            fi.restyle(self.pal)
        self.caption.setBrush(QBrush(self.pal.c("text")))
        cf = QFont(self.caption.font())
        cf.setPointSizeF(10)
        cf.setBold(True)
        self.caption.setFont(cf)
        self.scene.setBackgroundBrush(QBrush(self.pal.c("base")))
        self.scene.update()

    # --------------------------------------------------------- settings
    def settings(self) -> dict:
        return {"explain": self.explain_mode, "animate": self.animate, "reduce_motion": self.reduce_motion,
                "decimal": self.decimal, "speed": self.speed}

    def apply_settings(self, explain=True, animate=True, reduce_motion=None, decimal=False, speed=1.0):
        for cb, v in ((self.explain_cb, explain), (self.anim_cb, animate), (self.dec_cb, decimal)):
            cb.blockSignals(True)
            cb.setChecked(bool(v))
            cb.blockSignals(False)
        if reduce_motion is not None:
            self.reduce_cb.blockSignals(True)
            self.reduce_cb.setChecked(bool(reduce_motion))
            self.reduce_cb.blockSignals(False)
            self.reduce_motion = bool(reduce_motion)
        self.explain_mode, self.animate, self.decimal = bool(explain), bool(animate), bool(decimal)
        i = self.speed_combo.findData(float(speed))
        self.speed_combo.blockSignals(True)
        self.speed_combo.setCurrentIndex(i if i >= 0 else 1)
        self.speed_combo.blockSignals(False)
        self.speed = float(self.speed_combo.currentData())
        self._redraw()

    def _explain_toggled(self, on):
        self.explain_mode = on
        self.explain_changed.emit(on)
        self.settings_changed.emit()
        self._redraw()
        self._update_buttons()

    def _anim_toggled(self, on):
        self.animate = on
        if not on:
            self.skip()
        self.settings_changed.emit()
        self._update_buttons()

    def _reduce_toggled(self, on):
        self.reduce_motion = on
        if on:
            self.skip()
        self.settings_changed.emit()
        self._update_buttons()

    def _dec_toggled(self, on):
        self.decimal = on
        self.settings_changed.emit()
        self._redraw()
        self._render_text()

    def _speed_changed(self, _i):
        self.speed = float(self.speed_combo.currentData())
        self.settings_changed.emit()

    @property
    def motion_allowed(self) -> bool:
        return self.animate and not self.reduce_motion

    def _update_buttons(self):
        running = self._anim is not None
        self.pause_btn.setEnabled(running)
        self.skip_btn.setEnabled(running)
        self.pause_btn.setText("Resume" if self._paused else "Pause")
        self.replay_btn.setEnabled(self._rec is not None and self._rec.detailed and not self._concealed)
        self.speed_combo.setEnabled(self.motion_allowed)

    # --------------------------------------------------- conceal (Phase 1)
    def set_concealed(self, on: bool, ports: tuple[int, ...] = ()):
        """Experiment 1 before the prediction: hide A, the kit ports and the last step. Display only."""
        self._concealed = on
        self._conceal_ports = tuple(ports)
        if on:
            self._stop_anim()
            self._rec = None
            self._pending_live = None
            self.text.clear()
        self._redraw()
        self._update_buttons()

    @property
    def concealed(self) -> bool:
        return self._concealed

    # -------------------------------------------------------------- feeds
    def set_kit(self, kit: KitView):
        self._kit = kit
        self._redraw()

    def show_live(self, state: CpuState, immediate: bool = False):
        """Current CPU state. While a program runs the calls are coalesced to ~10 per second."""
        now = time.perf_counter()
        if immediate or now - self._last_live >= LIVE_INTERVAL:
            self._last_live = now
            self._pending_live = None
            self._apply_live(state)
        else:
            self._pending_live = state
            if not self._live_timer.isActive():
                self._live_timer.start(int(LIVE_INTERVAL * 1000))

    def _flush_live(self):
        if self._pending_live is not None:
            s, self._pending_live = self._pending_live, None
            self._last_live = time.perf_counter()
            self._apply_live(s)

    def _apply_live(self, state: CpuState):
        self._state = state
        if self._anim is None:
            if self._rec is not None and (state.icount != self._rec.post.icount or state != self._rec.post):
                self._rec = None  # the CPU moved on (Run, edit, restart): the old step no longer describes it
                self.text.clear()
            self._redraw()
            self._update_buttons()

    def show_record(self, rec: StepRecord | None, animate: bool | None = None):
        """A finished step. Safe to call at any time; it never executes anything."""
        if self._concealed or rec is None:
            return
        self._stop_anim()
        self._rec = rec
        self._state = rec.post
        want = self.motion_allowed if animate is None else animate
        if self.explain_mode and want and rec.kind == "instr" and rec.flows:
            self._start_anim(rec)
        else:
            self._redraw()
        self._render_text()
        self.tabs.setCurrentWidget(self.text)
        self._update_buttons()

    def reset(self):
        """Program reloaded / restarted: forget the last step."""
        self._stop_anim()
        self._rec = None
        self._state = None
        self.text.clear()
        self._show_idle()
        self._redraw()
        self._update_buttons()

    # ------------------------------------------------------- animation
    def _phases(self, rec: StepRecord) -> list[int]:
        return sorted({f.phase for f in rec.flows})

    def _start_anim(self, rec: StepRecord):
        self._anim = {"rec": rec, "phases": self._phases(rec), "idx": 0, "t": 0.0, "last": time.perf_counter()}
        self._paused = False
        self.timer.start()
        self._redraw()

    def _stop_anim(self):
        self.timer.stop()
        self._anim = None
        self._paused = False
        for fi in self.flow_items:
            fi.dot.setVisible(False)

    def toggle_pause(self):
        if self._anim is None:
            return
        self._paused = not self._paused
        self._anim["last"] = time.perf_counter()
        self._update_buttons()

    def skip(self):
        if self._anim is not None:
            self._stop_anim()
            self._redraw()
            self._update_buttons()

    def replay(self):
        if self._rec is not None and not self._concealed:
            was = self.reduce_motion
            self.show_record(self._rec, animate=self.animate and not was)

    def _tick(self):
        a = self._anim
        if a is None:
            self.timer.stop()
            return
        now = time.perf_counter()
        if not self._paused:
            a["t"] += (now - a["last"]) * 1000.0 * self.speed / PHASE_MS
        a["last"] = now
        while a["t"] >= 1.0:
            a["t"] -= 1.0
            a["idx"] += 1
            if a["idx"] >= len(a["phases"]):
                self._stop_anim()
                self._redraw()
                self._update_buttons()
                return
        self._redraw()

    # --------------------------------------------------------- drawing
    def _clear_flows(self):
        for fi in self.flow_items:
            self.scene.removeItem(fi)
        self.flow_items.clear()

    def _redraw(self):
        """Bring every item in line with the current state/record. Cheap: ~20 items, no per-instruction calls."""
        self.redraws += 1
        rec = self._rec if (self.explain_mode and not self._concealed) else None
        live = self._state
        shown = live
        a = self._anim
        phase_now = None
        frac = 0.0
        if a is not None and rec is not None:
            phase_now = a["phases"][a["idx"]]
            frac = a["t"]
            shown = rec.pre
        # flows ------------------------------------------------------
        want = [] if rec is None else list(rec.flows)
        if [f.flow for f in self.flow_items] != want:
            self._clear_flows()
            for fl in want:
                fi = FlowItem(fl, self.pal)
                self.scene.addItem(fi)
                self.flow_items.append(fi)
        done_dst: set[str] = set()
        cap = ""
        for fi in self.flow_items:
            fl = fi.flow
            if phase_now is None:
                fi.setVisible(True)
                fi.dot.setVisible(False)
                done_dst.add(fl.dst)
            elif fl.phase < phase_now:
                fi.setVisible(True)
                fi.dot.setVisible(False)
                done_dst.add(fl.dst)
            elif fl.phase == phase_now:
                fi.setVisible(True)
                fi.place_dot(frac)
                cap = cap or fl.label
            else:
                fi.setVisible(False)
        if a is None and rec is not None and rec.kind == "instr":
            cap = f"{rec.text}: {rec.summary}" if rec.summary else rec.text
            cap = cap if len(cap) <= 118 else cap[:115] + "..."
        # node state ---------------------------------------------------
        roles = rec.role_map if rec is not None else {}
        tags = rec.tag_map if rec is not None else {}
        changed = rec.changed_nodes if rec is not None else frozenset()
        active = bool(roles) or bool(changed)
        sub_phase = a is not None
        for pid, (hi, lo) in PAIRS.items():
            if pid in done_dst:
                done_dst.update((hi, lo))
        chg_regs = {n: o for n, o, _ in rec.reg_changes} if rec is not None else {}
        for nid, node in self.nodes.items():
            if nid in ("IR", "ALU", "FLAGS", "MEMIF", "IOIF", "MEM", "PORT_IN", "PORT_OUT"):
                continue
            use_post = rec is not None and sub_phase and nid in done_dst
            st = rec.post if use_post else shown
            masked = self._concealed and nid == "A"
            is_changed = rec is not None and nid in changed and (not sub_phase or use_post)
            old = chg_regs.get(nid)
            if rec is not None and nid == "PC" and rec.pc_change:
                old = rec.pc_change[0]
            if rec is not None and nid == "SP" and rec.sp_change:
                old = rec.sp_change[0]
            role = roles.get(nid, "")
            node.set_state(role=role, changed=is_changed, dim=active and not role and not is_changed,
                           value=st.node_value(nid) if st is not None else None, old=old if is_changed else None,
                           tag=tags.get(nid, ""), masked=masked, decimal=self.decimal)
        # flags
        fl_node = self.nodes["FLAGS"]
        fst = shown if not (sub_phase and "FLAGS" in done_dst and rec is not None) else rec.post
        fl_node.set_state(flags_vals=fst.flags if fst is not None else None,
                          flags_changed=frozenset(n for n, _, _ in rec.flag_changes) if rec is not None
                          and (not sub_phase or "FLAGS" in done_dst) else frozenset(),
                          masked=False)
        # pairs
        for pid, fr in self.frames.items():
            st = shown
            if sub_phase and rec is not None and (pid in done_dst or set(PAIRS[pid]) & done_dst):
                st = rec.post
            fr.set_state(role=roles.get(pid, ""), changed=pid in changed and not sub_phase,
                         value=st.pair(pid) if st is not None else None, masked=False, decimal=self.decimal)
        # IR / interfaces / memory / ports -----------------------------
        self._update_blocks(rec, shown, sub_phase)
        self.caption.setText(("" if self._concealed else (cap if cap else "")))
        self.scene.update()
        sm = self.status
        if not sm.text():
            sm.setText("Tab / arrow keys move between blocks; + - 0 zoom; Ctrl+wheel zooms.")

    def _update_blocks(self, rec: StepRecord | None, shown: CpuState | None, sub_phase: bool):
        ir = self.nodes["IR"]
        kit = self._kit
        if rec is not None and rec.kind == "instr":
            ir.set_state(extra=[rec.text, f"opcode {rec.raw[0]:02X}h, {rec.length} byte(s)", rec.family],
                         role=rec.role_map.get("IR", ""), tag=rec.tag_map.get("IR", ""))
        else:
            ir.set_state(extra=["(no step captured)" if rec is None else rec.text, "", ""], role="", tag="")
        mem_lines: list[str] = []
        io_lines: list[str] = []
        pin, pout = self.nodes["PORT_IN"], self.nodes["PORT_OUT"]
        sw_port, led_port = kit.switch_port, kit.led_port
        kit_in = kit.enabled
        pin.set_state(title="Input port", extra=[f"port {sw_port:02X}H" + (" - kit switches" if kit_in else ""),
                                                  f"switches {hexs(kit.switches, 8)}" if kit_in else "value from the I/O table",
                                                  bins(kit.switches, 8) + "b" if kit_in else ""], leds=None)
        pout.set_state(title="Output port", extra=[f"port {led_port:02X}H" + (" - kit LEDs" if kit_in else ""),
                                                    "", ""], leds=None)
        if rec is not None and rec.kind == "instr":
            for ev in rec.port_events:
                node = pin if ev.direction == "IN" else pout
                inkit = kit.enabled and ev.port == (sw_port if ev.direction == "IN" else led_port)
                node.set_state(title=("Input port" if ev.direction == "IN" else "Output port"),
                               extra=[f"port {ev.port:02X}H" + (" - kit" if inkit else ""),
                                      f"{ev.direction} value {hexs(ev.value, 8)}", bins(ev.value, 8) + "b"])
            for a in rec.mem_accesses[:3]:
                mem_lines.append(f"{'read' if a.kind == 'R' else 'write'} {a.addr:04X}h = {a.value:02X}h"
                                 + ("" if a.observed else " (expected)"))
        if kit.enabled and kit.leds_written:
            pout.set_state(leds=kit.leds)
        self.nodes["MEM"].set_state(extra=mem_lines or ["no memory access in this step" if rec is not None and
                                                         rec.kind == "instr" else "64K bytes, 0000h-FFFFh"],
                                    role=(rec.role_map.get("MEM", "") if rec is not None else ""))
        mif = rec.role_map.get("MEM", "") if rec is not None else ""
        self.nodes["MEMIF"].set_state(extra=["address 16 bits, data 8 bits"] if mif else ["address 16 bits / data 8 bits"],
                                      role="")
        ports_used = rec is not None and any(f.src.startswith("PORT") or f.dst.startswith("PORT") for f in rec.flows)
        self.nodes["IOIF"].set_state(extra=["port number 8 bits / data 8 bits"], role="both" if ports_used else "")
        rm = rec.role_map if rec is not None else {}
        self.nodes["ALU"].set_state(role=rm.get("ALU", ""), tag=rec.tag_map.get("ALU", "") if rec is not None else "")
        for nid in ("PORT_IN", "PORT_OUT", "FLAGS"):
            self.nodes[nid].set_state(role=rm.get(nid, ""), changed=nid == "FLAGS" and rec is not None
                                      and bool(rec.flag_changes) and not sub_phase)
        # masks for Experiment 1
        for nid in ("PORT_IN", "PORT_OUT"):
            self.nodes[nid].set_state(masked=self._concealed)
        if self._concealed:
            for nid in ("PORT_IN", "PORT_OUT"):
                self.nodes[nid].set_state(extra=[], leds=None)
            self.status.clear()

    # ------------------------------------------------------------- text
    def _show_idle(self):
        self.text.setHtml("<p><b>Interactive CPU Architecture</b></p><p>Press <b>Step Into</b> (F11). The diagram "
                          "shows where the data logically moves for the instruction that ran, and the exact "
                          "before/after values read from the simulator.</p>"
                          f"<p><i>Data paths and the Instruction Register / Decoder are a {CONCEPTUAL}: this "
                          "simulator is instruction-level, not cycle-accurate.</i></p>")

    def _render_text(self):
        rec = self._rec
        if rec is None or self._concealed:
            return
        h = [f"<p><b>Step {rec.seq}: {escape(rec.text)}</b>"]
        if rec.kind == "instr":
            h.append(f" &nbsp;<span>opcode {rec.raw[0]:02X}h, {rec.length} byte(s) &middot; {escape(rec.family)}</span>")
        h.append("</p>")
        if rec.summary:
            h.append(f"<p>{escape(rec.summary)}</p>")
        if rec.kind == "multi":
            h.append(f"<p>{rec.n_instr:,} instructions executed ({escape(rec.mode)}); "
                     "no per-instruction animation is shown for this action.</p>")
        elif rec.kind == "interrupt":
            h.append("<p>An interrupt was accepted instead of the next instruction.</p>")
        elif rec.kind == "instr" and not rec.detailed:
            h.append("<p><i>This instruction has no detailed animation in Phase 2. The exact state change below is "
                     "read from the simulator.</i></p>")
        h.append("<p><b>Result (read from the CPU)</b></p><ul>")
        for n, o, nw in rec.reg_changes:
            h.append(f"<li>{n}: {o:02X}h &rarr; {nw:02X}h &nbsp;<tt>{o:08b} &rarr; {nw:08b}</tt>"
                     + (f" &nbsp;({o} &rarr; {nw})" if self.decimal else "") + "</li>")
        for n, o, nw in rec.flag_changes:
            h.append(f"<li>flag {n}: {o} &rarr; {nw}</li>")
        if rec.sp_change:
            h.append(f"<li>SP: {rec.sp_change[0]:04X}h &rarr; {rec.sp_change[1]:04X}h</li>")
        if rec.pc_change:
            h.append(f"<li>PC: {rec.pc_change[0]:04X}h &rarr; {rec.pc_change[1]:04X}h</li>")
        for a in rec.mem_accesses:
            h.append(f"<li>memory {'read' if a.kind == 'R' else 'write'} at {a.addr:04X}h = {a.value:02X}h "
                     + ("(observed by the simulator's access counters)" if a.observed else "(expected, not verified)")
                     + "</li>")
        for ev in rec.port_events:
            h.append(f"<li>port {ev.direction} {ev.port:02X}h = {ev.value:02X}h "
                     + ("(observed)" if ev.observed else "(expected)") + "</li>")
        for addr, o, nw in rec.mem_diff[:8]:
            if not any(a.addr == addr for a in rec.mem_accesses):
                h.append(f"<li>memory {addr:04X}h: {o:02X}h &rarr; {nw:02X}h</li>")
        if not (rec.reg_changes or rec.flag_changes or rec.sp_change or rec.pc_change or rec.mem_accesses
                or rec.port_events or rec.mem_diff):
            h.append("<li>no visible state change</li>")
        h.append("</ul>")
        if rec.why:
            h.append("<p><b>Why it happened</b></p><ul>" + "".join(f"<li>{escape(w)}</li>" for w in rec.why) + "</ul>")
        if rec.details:
            h.append("<p>Inputs: " + escape(" ".join(rec.details)) + "</p>")
        if rec.flag_why:
            h.append("<p><b>Flags</b></p><ul>" + "".join(f"<li>{escape(w)}</li>" for w in rec.flag_why) + "</ul>")
        if rec.conceptual_steps:
            h.append(f"<p><b>Data flow</b> <i>({CONCEPTUAL})</i></p><ol>"
                     + "".join(f"<li>{escape(s)}</li>" for s in rec.conceptual_steps) + "</ol>")
            h.append("<p><i>Solid arrows: the state change confirms this movement. Dashed arrows: conceptual only "
                     "(the simulator is instruction-level; bus signals and cycles are not modelled).</i></p>")
        self.text.setHtml("".join(h))

    # ------------------------------------------------------------- zoom
    def zoom_by(self, factor: float):
        if factor == 0.0:
            self._fit = True
            self._apply_fit()
            return
        self._fit = False
        self._scale = max(0.3, min(3.0, self._scale * factor))
        self.view.resetTransform()
        self.view.scale(self._scale, self._scale)

    def _apply_fit(self):
        vw, vh = self.view.viewport().width(), self.view.viewport().height()
        if vw < 50:
            return
        s = min(vw / SCENE_W, vh / SCENE_H)
        s = max(MIN_FIT_SCALE, s)  # below this the labels would stop being readable: scroll instead
        self._scale = s
        self.view.resetTransform()
        self.view.scale(s, s)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit:
            self._apply_fit()

    def showEvent(self, e):
        super().showEvent(e)
        if self._fit:
            QTimer.singleShot(0, self._apply_fit)
        self.visible_changed.emit(True)

    def hideEvent(self, e):
        super().hideEvent(e)
        self._stop_anim()
        self.visible_changed.emit(False)

    @property
    def scale_factor(self) -> float:
        return self._scale

    # ------------------------------------------------------- keyboard
    def focus_step(self, node: NodeItem, delta: int):
        items = list(self.nodes.values())
        i = items.index(node)
        nxt = items[(i + delta) % len(items)]
        nxt.setFocus()
        self.view.ensureVisible(nxt)

    def _node_focused(self, text: str):
        self.status.setText(text)
        self.view.setAccessibleDescription(text)

    # ------------------------------------------------------ for tests
    def node_texts(self) -> list[str]:
        out = [n.describe() + " " + n.toolTip() for n in self.nodes.values()]
        out += [f.toolTip() for f in self.flow_items]
        out += [self.caption.text(), self.text.toPlainText(), self.status.text()]
        for fr in self.frames.values():
            out.append(f"{fr.nid} {fr.value} {fr.masked}")
        return out
