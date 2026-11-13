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

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPainterPath, QPen, QPolygonF,
                           QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QGraphicsEllipseItem, QGraphicsItem, QGraphicsObject,
                               QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsTextItem, QGraphicsView,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSplitter, QTabWidget, QTextBrowser, QVBoxLayout,
                               QWidget)

from ..core.visual import (CONCEPTUAL, FLAG_ORDER, PAIRS, REG_ORDER, CpuState, Flow, KitView, MemView, StepRecord)
from .cpulabs import LabGuidePanel
from .docks import mono
from .icons import make_icon
from .themes import DARK, Theme

TITLE = "Interactive CPU Architecture"
SCENE_W, SCENE_H = 1200, 722

# Text sizes in scene points (the diagram is drawn at 100% zoom in scene units and scaled to fit the panel; the
# fit never goes below MIN_FIT_SCALE, so at the smallest fit values are >= 12.8 pt and labels >= 10 pt).
FONT_VALUE = 16.0  # register / PC / SP / flag values
FONT_LABEL = 12.5  # box titles
FONT_DETAIL = 11.5  # binary, "was", tags, port lines, memory rows
FONT_MIN = FONT_DETAIL  # nothing inside a box is drawn smaller than this

# The one-line explanation under the diagram wraps over up to three lines instead of being cut with "...".
CAPTION_X, CAPTION_Y, CAPTION_W = 26, 676, SCENE_W - 2 * 26


class CaptionItem(QGraphicsTextItem):
    """Word-wrapped caption (never elided). Same small API as the text item it replaces."""

    def __init__(self):
        super().__init__("")
        self.document().setDocumentMargin(2)
        self.setTextWidth(CAPTION_W)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)  # never takes clicks away from the diagram

    def setBrush(self, brush: QBrush):
        self.setDefaultTextColor(brush.color())

    def setText(self, text: str):
        self.setPlainText(text)
        self.setToolTip("")

    def text(self) -> str:
        return self.toPlainText()


# ------------------------------------------------------------------ geometry
_REG_W, _REG_H = 104, 118
_REG_Y = 198
GEOM: dict[str, tuple[float, float, float, float]] = {
    "IR": (26, 10, 290, 122), "A": (328, 10, 160, 122), "ALU": (504, 10, 160, 122), "FLAGS": (680, 10, 506, 122),
    "B": (34, _REG_Y, _REG_W, _REG_H), "C": (146, _REG_Y, _REG_W, _REG_H),
    "D": (278, _REG_Y, _REG_W, _REG_H), "E": (390, _REG_Y, _REG_W, _REG_H),
    "H": (522, _REG_Y, _REG_W, _REG_H), "L": (634, _REG_Y, _REG_W, _REG_H),
    "BC": (26, 172, 232, 184), "DE": (270, 172, 232, 184), "HL": (514, 172, 232, 184),
    "PC": (758, 172, 130, 184), "SP": (900, 172, 286, 184),
    "MEMIF": (26, 410, 748, 48), "IOIF": (790, 410, 396, 48),
    "MEM": (26, 498, 748, 172), "PORT_IN": (790, 498, 194, 172), "PORT_OUT": (992, 498, 194, 172),
}
DATA_Y, ADDR_Y, MIDY = 146.0, 386.0, 478.0
RISER_L, RISER_R, ADDR_RISER = 8.0, 1194.0, 17.0


def _cx(node: str) -> float:
    x, _, w, _ = GEOM[node]
    return x + w / 2


def _bottom(node: str) -> float:
    return GEOM[node][1] + GEOM[node][3]


def _top(node: str) -> float:
    return GEOM[node][1]


PAIR_TITLE_X = 28.0  # the pair's title starts this far inside its frame, to the right of the first register's tap
_FIRST_REGS, _SECOND_REGS = ("B", "D", "H"), ("C", "E", "L")
_PAIR_OF_REG = {r: pair for pair, regs in PAIRS.items() for r in regs}
_LOOP_W = 22.0  # width of a self-loop in a pair's right-hand corner
# The title may be as wide as the gap between PAIR_TITLE_X and the right-hand corner loop / tap of the second register
# (less a margin): a wider font shrinks the title (fit_font), it never pushes it onto the arrows.
PAIR_TITLE_AVAIL = (GEOM["C"][0] + GEOM["C"][2] - 8 - _LOOP_W) - GEOM["BC"][0] - 6 - PAIR_TITLE_X


def pair_title_font(nid: str) -> QFont:
    """The font a pair title is really drawn with (the platform font, shrunk to fit PAIR_TITLE_AVAIL)."""
    return fit_font(fnt(FONT_DETAIL, bold=True), NODE_INFO[nid][0], PAIR_TITLE_AVAIL)


def pair_title_rect(nid: str) -> QRectF:
    """Scene rectangle of a register pair's title, from the metrics of the font in use: arrows and taps are routed
    around it, so this holds for any font (DejaVu on Linux is much wider than Segoe UI on Windows)."""
    gx, gy, _, _ = GEOM[nid]
    f = pair_title_font(nid)
    fm = QFontMetricsF(f)
    return QRectF(gx + PAIR_TITLE_X, gy + 4, fm.horizontalAdvance(NODE_INFO[nid][0]), 22 - 6)


def _clear_of_title(reg: str, x0: float, x1: float, margin: float = 6.0) -> bool:
    """Is the vertical band x0..x1 (scene coordinates) beside the title of the pair that holds ``reg``?"""
    pair = _PAIR_OF_REG.get(reg)
    if pair is None:
        return True
    t = pair_title_rect(pair)
    return x1 + margin <= t.left() or x0 - margin >= t.right()


def _reg_tap_x(node: str) -> float:
    """x where a register's line to the data path leaves its box. The first register of a pair (B, D, H) leaves near
    its left corner, before the pair title. The second (C, E, L) leaves from its middle when that is clear of the
    title as drawn in the current font, otherwise from its right-hand corner, after the title."""
    x, _, w, _ = GEOM[node]
    if node in _FIRST_REGS:
        return x + 8
    if node in _SECOND_REGS and not _clear_of_title(node, x + w / 2, x + w / 2):
        return x + w - 8
    return x + w / 2


def _data_tap(node: str) -> list[QPointF] | None:
    """Points from the node to the 8-bit internal data path, ending ON the bus line."""
    P = QPointF
    if node in ("IR", "A", "ALU", "FLAGS"):
        return [P(_cx(node), _bottom(node)), P(_cx(node), DATA_Y)]
    if node in REG_ORDER[1:]:
        return [P(_reg_tap_x(node), _top(node)), P(_reg_tap_x(node), DATA_Y)]
    if node in PAIRS:
        return [P(_cx(node), _top(node)), P(_cx(node), DATA_Y)]
    if node == "MEM":
        return [P(100, _top("MEM")), P(100, MIDY), P(RISER_L, MIDY), P(RISER_L, DATA_Y)]
    if node in ("PORT_IN", "PORT_OUT"):
        return [P(_cx(node), _top(node)), P(_cx(node), MIDY), P(RISER_R, MIDY), P(RISER_R, DATA_Y)]
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
    ("A", "ALU"): ((488, 45), (504, 45)), ("ALU", "A"): ((504, 80), (488, 80)),
    ("ALU", "FLAGS"): ((664, 45), (680, 45)), ("FLAGS", "ALU"): ((680, 80), (664, 80)),
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
        if src in _FIRST_REGS:  # keep this small loop in the corner, beside the pair title instead of across it
            path.moveTo(x + 13, ya)
            path.cubicTo(x + 13, ya - 26, x + 1, ya - 26, x + 1, ya)
            return path
        x0, x1 = x + w * 0.35, x + w * 0.65
        if src in _SECOND_REGS and not _clear_of_title(src, x0, x1):  # the title (in this font) reaches the middle
            x0, x1 = x + w - 8 - _LOOP_W, x + w - 8  # use the right-hand corner, after the title
        path.moveTo(x0, ya)
        path.cubicTo(x0, ya - 22, x1, ya - 22, x1, ya)
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
FONT_MEM = 12.0  # memory rows / stack words (mono)
_AL = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_AC = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
_AR = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class TextRec:
    """One piece of text drawn inside a box (recorded only while ``panel.audit`` is a list: tests check these)."""

    __slots__ = ("nid", "text", "rect", "font")

    def __init__(self, nid: str, text: str, rect: QRectF, font: QFont):
        self.nid, self.text, self.rect, self.font = nid, text, rect, QFont(font)

    def fits(self) -> bool:
        fm = QFontMetricsF(self.font)
        return fm.horizontalAdvance(self.text) <= self.rect.width() + 0.5 and fm.height() <= self.rect.height() + 0.5


def fnt(size: float, mono_font: bool = False, bold: bool = False, italic: bool = False) -> QFont:
    f = mono(10) if mono_font else QFont(QApplication.font())
    f.setPointSizeF(size)
    f.setBold(bold)
    f.setItalic(italic)
    return f


def fit_font(font: QFont, text: str, width: float) -> QFont:
    """The font itself when the text fits; otherwise shrunk a quarter point at a time, but never below 10.5 pt
    (13 pt for the big values). So a wider system font shrinks a title slightly instead of clipping it."""
    floor = 13.0 if font.pointSizeF() >= 14 else 10.5
    f = QFont(font)
    fm = QFontMetricsF(f)
    while fm.horizontalAdvance(text) > width and f.pointSizeF() > floor + 0.01:
        f.setPointSizeF(max(floor, f.pointSizeF() - 0.25))
        fm = QFontMetricsF(f)
    return f


def _marks(uses) -> dict[int, str]:
    out: dict[int, set] = {}
    for a in uses:
        out.setdefault(a.addr, set()).add(a.kind)
    return {k: ("RW" if len(v) == 2 else next(iter(v))) for k, v in out.items()}


def access_text(a) -> str:
    """The one-line text of a memory access (used by the diagram, tooltips and tests)."""
    if a.kind == "W":
        old = "??" if a.old is None else f"{a.old:02X}"
        return f"WRITE {a.addr:04X}h  {old}h -> {a.value:02X}h"
    return f"READ  {a.addr:04X}h = {a.value:02X}h"


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
        self.hide_contents = False  # Experiment 1 before the prediction: no memory / stack values at all
        self.leds: int | None = None  # 8-bit pattern drawn as dots (output port node)
        self.decimal = False
        self.uses: tuple = ()  # this step's memory accesses (MEM node)
        self.mv: MemView | None = None  # memory / stack snapshot (MEM and SP nodes)
        self.mem_note = ""
        title, desc = NODE_INFO.get(nid, (nid, ""))
        self.title = title
        self.setToolTip(f"{title}\n{desc}")
        self.setZValue(2)

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-4, -4, 4, 4)

    # ------------------------------------------------- memory / stack model
    def mem_lines(self) -> list[str]:
        """Rows of the Memory area for this step, as text. Single source for drawing, tooltip and tests."""
        if self.hide_contents:
            return ["hidden until you predict"]
        rows = [access_text(a) for a in self.uses[:4]]
        if len(self.uses) > 4:
            rows[-1] = f"+{len(self.uses) - 3} more accesses"
        return rows or [self.mem_note or "64K bytes, 0000h-FFFFh"]

    def recent_text(self) -> str:
        mv = self.mv
        if self.hide_contents or mv is None or not mv.recent:
            return ""
        return " ".join(f"{a.kind}{a.addr:04X}" for a in mv.recent[:4])

    def strips(self) -> list[tuple[str, list[tuple[int, int, str]]]]:
        """[(caption, [(addr, value, mark)])]: the cells around HL (M) and around the last accessed address."""
        mv = self.mv
        if self.hide_contents or mv is None:
            return []
        marks = _marks(self.uses)
        out = [(f"around HL (M) = {mv.hl:04X}h", [(a, v, marks.get(a, "")) for a, v in mv.hl_cells])]
        if mv.last is not None:
            out.append((f"around last access = {mv.last:04X}h", [(a, v, marks.get(a, "")) for a, v in mv.last_cells]))
        return out

    def sp_lines(self) -> tuple[list[str], list[str]]:
        """(left column rows, stack rows) of the SP box: [SP], [SP+1], the word, and the top words."""
        if self.hide_contents:
            return ["contents hidden", "until you predict"], []
        mv, val = self.mv, self.value
        if mv is None or val is None or val[0] != mv.sp:
            return ["[SP]   = ??", "[SP+1] = ??", "word   = ????"], []
        left = [f"[SP]   = {mv.sp_lo:02X}h", f"[SP+1] = {mv.sp_hi:02X}h", f"word   = {mv.sp_word:04X}h"]
        stack = [f"{'>' if i == 0 else ' '} {a:04X} {w:04X}h" for i, (a, w) in enumerate(mv.stack)] or ["(stack empty)"]
        return left, stack

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
        if self.nid == "MEM":
            parts.extend(self.mem_lines())
            rt = self.recent_text()
            if rt:
                parts.append("recent " + rt)
            for cap, cells in self.strips():
                parts.append(cap + ": " + ", ".join(f"{a:04X}h={v:02X}h{(' ' + m) if m else ''}" for a, v, m in cells))
        if self.nid == "SP":
            left, stack = self.sp_lines()
            parts.extend(left + [t.strip() for t in stack])
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
    def _t(self, p: QPainter, x: float, y: float, w: float, h: float, s: str, font: QFont, align=_AL):
        """Draw one line of text in a rectangle (never elided) and record it for the tests."""
        if not s:
            return
        r = QRectF(x, y, w, h)
        font = fit_font(font, s, w)
        p.setFont(font)
        p.drawText(r, align, s)
        audit = self.panel.audit
        if audit is not None:
            audit.append(TextRec(self.nid, s, r, font))

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
        W = r.width()
        lf = fnt(FONT_LABEL, bold=True)
        df = fnt(FONT_DETAIL)
        dm = fnt(FONT_DETAIL, True)
        vf = fnt(FONT_VALUE, True, True)
        short = {"A": "Accumulator A", "ALU": "ALU", "IR": "Instruction Register / Decoder",
                 "MEMIF": "Memory interface (conceptual)", "IOIF": "I/O interface (conceptual)",
                 "MEM": "Memory (64K x 8)", "PC": "PC", "SP": "SP  Stack Pointer",
                 "FLAGS": "Flags"}.get(self.nid, self.nid)
        if self.nid in ("PORT_IN", "PORT_OUT"):
            short = self.title
        # role / change badges are text, so the meaning never depends on colour; on top if the title leaves room
        badge = " ".join(([_ROLE_TAG[self.role]] if self.role else []) + (["Δ"] if self.changed else []))
        bf = fnt(FONT_DETAIL, bold=True)
        tw = QFontMetricsF(lf).horizontalAdvance(short)
        bw = QFontMetricsF(bf).horizontalAdvance(badge) if badge else 0
        top_badge = tw + bw + 24 <= W
        self._t(p, 8, 4, W - 16 - (bw + 8 if badge and top_badge else 0), 22, short, lf)
        if badge:
            self._t(p, W - bw - 10, 4 if top_badge else r.height() - 24, bw + 4, 20, badge, bf, _AR)
        if self.nid == "IR":
            self._t(p, 8, 28, W - 16, 20, "conceptual - not a simulated circuit", df)
            first = self.extra[0] if self.extra else ""
            self._t(p, 8, 48, W - 16, 26, first, fnt(13.5, True, True))
            for i, line in enumerate(self.extra[1:3]):
                self._t(p, 8, 76 + 20 * i, W - 16, 20, line, dm)
            return
        if self.nid == "FLAGS":
            self._paint_flags(p, text)
            return
        if self.nid in ("MEMIF", "IOIF", "ALU"):
            for line in self.extra[:1] or ([""] if self.nid != "ALU" else ["arithmetic + logic"]):
                self._t(p, 8, 26, W - 16, 20, line, df)
            if self.nid == "ALU" and self.tag:
                self._t(p, 8, 54, W - 16, 28, self.tag, vf)
            return
        if self.nid == "MEM":
            self._paint_memory(p, df, dm)
            return
        if self.nid in ("PORT_IN", "PORT_OUT"):
            self._paint_endpoint(p, dm)
            return
        if self.nid == "SP":
            self._paint_sp(p, df, dm, vf)
            return
        # registers / pairs / PC
        y = 28.0
        if self.masked:
            self._t(p, 8, y, W - 16, 28, "??", vf)
            self._t(p, 8, y + 30, W - 12, 20, "hidden until", df)
            self._t(p, 8, y + 50, W - 12, 20, "you predict", df)
            return
        if self.value is not None:
            v, b = self.value
            self._t(p, 8, y, W - 16, 28, hexs(v, b), vf)
            if b == 8:
                self._t(p, 8, y + 28, W - 12, 20, bins(v, b), dm)
                yy = y + 48
            else:
                self._t(p, 8, y + 28, W - 12, 20, bins(v >> 8, 8), dm)
                self._t(p, 8, y + 48, W - 12, 20, bins(v & 255, 8), dm)
                yy = y + 68
            if self.decimal:
                self._t(p, 8, yy, W - 12, 20, f"= {v}", dm)
                yy += 20
            if self.changed and self.old is not None and r.height() - yy >= 20:
                self._t(p, 8, yy, W - 12, 20, f"was {hexs(self.old, b)}", dm)
                yy += 20
            elif self.tag and r.height() - yy >= 20:
                self._t(p, 8, yy, W - 12, 20, self.tag, dm)

    def _paint_sp(self, p: QPainter, df: QFont, dm: QFont, vf: QFont):
        r = self.rect
        W = r.width()
        if self.value is None:
            return
        v, _b = self.value
        self._t(p, 8, 28, 140, 28, hexs(v, 16), vf)
        if self.changed and self.old is not None:
            self._t(p, 8, 56, 140, 20, f"was {hexs(self.old, 16)}", dm)
        elif self.tag:
            self._t(p, 8, 56, 140, 20, self.tag, dm)
        left, stack = self.sp_lines()
        mf = fnt(FONT_MEM, True)
        for i, line in enumerate(left):
            self._t(p, 8, 78 + 20 * i, 146, 20, line, mf)
        if stack:
            self._t(p, 160, 28, W - 168, 20, "stack, top is >", df)
            for i, line in enumerate(stack[:4]):
                self._t(p, 160, 48 + 20 * i, W - 168, 20, line, fnt(FONT_DETAIL, True, i == 0))
        if not self.hide_contents:
            self._t(p, 8, r.height() - 28, W - 16, 22, "low byte at SP, high byte at SP+1", df)

    def _paint_memory(self, p: QPainter, df: QFont, dm: QFont):
        pal = self.pal
        mf = fnt(FONT_MEM, True, True)
        self._t(p, 8, 28, 300, 20, "" if self.hide_contents else "this step:", fnt(FONT_DETAIL, bold=True))
        for i, line in enumerate(self.mem_lines()):
            access = line.startswith(("WRITE", "READ"))
            self._t(p, 8, 48 + 20 * i, 300, 20, line, mf if access else df)
        rt = self.recent_text()
        if rt:
            self._t(p, 8, 130, 300, 20, "recently used (R read, W write):", df)
            self._t(p, 8, 150, 300, 20, rt, dm)
        x0, cw = 322.0, 84.0
        y = 28.0
        for cap, cells in self.strips():
            self._t(p, x0, y, 420, 20, cap, df)
            for i, (a, v, mark) in enumerate(cells):
                box = QRectF(x0 + i * cw, y + 20, cw - 4, 44)
                key = "heat_write" if "W" in mark else "heat_read"
                p.setPen(QPen(pal.c(key) if mark else pal.c("border"), 3 if mark else 1))
                if mark:
                    fill = QColor(pal.c(key))
                    fill.setAlpha(60)
                    p.setBrush(QBrush(_over(pal.c("panel"), fill)))
                else:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(box, 4, 4)
                p.setPen(pal.c("text"))
                hl = " HL" if self.mv is not None and a == self.mv.hl else ""
                self._t(p, box.x() + 4, box.y() + 2, box.width() - 8, 18, f"{a:04X}{hl}", dm)
                self._t(p, box.x() + 4, box.y() + 20, box.width() - 8, 22, f"{mark} {v:02X}h".lstrip(), mf)
            y += 74

    def _paint_flags(self, p: QPainter, text: QColor):
        pal = self.pal
        r = self.rect
        n = len(FLAG_ORDER)
        cw = (r.width() - 16) / n
        for i, name in enumerate(FLAG_ORDER):
            x = 8 + i * cw
            box = QRectF(x + 3, 30, cw - 6, 86)
            chg = name in self.flags_changed
            p.setPen(QPen(pal.c("exec_arrow") if chg else pal.c("border"), 3 if chg else 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 5, 5)
            p.setPen(text)
            self._t(p, box.x(), box.y() + 3, box.width(), 22, name + (" Δ" if chg else ""), fnt(FONT_LABEL, bold=True), _AC)
            val = "?" if self.masked or self.flags_vals is None else str(self.flags_vals[i])
            self._t(p, box.x(), box.y() + 26, box.width(), 28, val, fnt(FONT_VALUE, True, True), _AC)
            on = self.flags_vals is not None and not self.masked and self.flags_vals[i]
            self._t(p, box.x(), box.y() + 58, box.width(), 22, "set" if on else "clear" if not self.masked else "",
                    fnt(FONT_DETAIL), _AC)

    def _paint_endpoint(self, p: QPainter, dm: QFont):
        r = self.rect
        lines = self.extra[:2] if self.leds is not None else self.extra[:3]
        if self.masked:
            lines = ["hidden until", "you predict"]
        for i, line in enumerate(lines):
            self._t(p, 8, 28 + 20 * i, r.width() - 12, 20, line, dm)
        if self.leds is not None and not self.masked:  # eight LED dots: filled = lit (shape, not just colour)
            on, off = self.pal.c("led_on"), self.pal.c("led_off")
            for i, bit in enumerate(range(7, -1, -1)):
                lit = self.leds >> bit & 1
                p.setPen(QPen(self.pal.c("text"), 1))
                p.setBrush(QBrush(on if lit else off))
                p.drawEllipse(QRectF(8 + i * 22, 100, 16, 16))
                if not lit:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QRectF(8 + i * 22 + 5, 105, 6, 6))


def _over(base: QColor, top: QColor) -> QColor:
    a = top.alphaF()
    return QColor(int(base.red() * (1 - a) + top.red() * a), int(base.green() * (1 - a) + top.green() * a),
                  int(base.blue() * (1 - a) + top.blue() * a))


class PairFrame(QGraphicsObject):
    """The frame around B+C / D+E / H+L with the 16-bit pair value in its bottom strip."""

    def __init__(self, nid: str, pal: Palette, panel: "CpuArchitecturePanel"):
        super().__init__()
        self.nid, self.pal, self.panel = nid, pal, panel
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

    def _t(self, p, x, y, w, h, s, font, align=_AL):
        r = QRectF(x, y, w, h)
        font = fit_font(font, s, w)
        p.setFont(font)
        p.drawText(r, align, s)
        if self.panel.audit is not None:
            self.panel.audit.append(TextRec(self.nid, s, r, font))

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
        val = "????h" if self.masked or self.value is None else hexs(self.value, 16)
        label = f"{self.nid} = {val}" + (f"  ({self.value})" if self.decimal and self.value is not None and not self.masked else "")
        tag = " ".join(([_ROLE_TAG[self.role]] if self.role else []) + (["Δ"] if self.changed else []))
        bf = fnt(FONT_DETAIL, bold=True)
        self._t(p, PAIR_TITLE_X, 4, PAIR_TITLE_AVAIL, 22, NODE_INFO[self.nid][0], bf)
        if tag:
            bw = QFontMetricsF(bf).horizontalAdvance(tag)
            self._t(p, self.rect.width() - bw - 10, 4, bw + 4, 22, tag, bf, _AR)
        self._t(p, 8, self.rect.height() - 34, self.rect.width() - 16, 28, label, fnt(13.5, True, True))


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


class EnlargedWindow(QWidget):
    """A plain top-level window that hosts the CPU panel while it is enlarged. Closing it (title-bar button or Esc)
    asks the owner to hand the panel back to its dock."""

    closed = Signal()

    def __init__(self, panel: QWidget, title: str):
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle(title)
        self.setObjectName("cpuview_enlarged")
        self._panel = panel
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(panel)
        self._released = False
        self._actions: list = []

    def set_actions(self, actions):
        """Lend the main window's run/step actions to this separate top-level window, so F5/F10/F11... still work."""
        for a in actions:
            self.addAction(a)
        self._actions = list(actions)

    def release(self):
        """Give the panel up (the caller re-parents it) without emitting ``closed``."""
        self._released = True
        for a in self._actions:
            self.removeAction(a)
        self._actions = []
        self.layout().removeWidget(self._panel)
        self._panel.setParent(None)
        self.hide()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.closed.emit()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        if not self._released:
            e.ignore()  # the owner restores the layout, then drops this window
            self.closed.emit()
        else:
            super().closeEvent(e)


# ---------------------------------------------------------------- the panel
ZOOM_CHOICES = [("Fit", 0.0), ("100%", 1.0), ("125%", 1.25), ("150%", 1.5), ("200%", 2.0)]
SPEEDS = [("0.5x (slow)", 0.5), ("1x", 1.0), ("2x", 2.0), ("4x (fast)", 4.0)]
PHASE_MS = 650
MIN_FIT_SCALE = 0.8  # below this the labels would stop being readable: the diagram scrolls instead
LIVE_INTERVAL = 0.10  # seconds: coalesce live refreshes while a program runs


class CpuArchitecturePanel(QWidget):
    """The dock contents. Pure view: feed it with ``show_live``, ``show_record`` and ``set_kit``."""

    explain_changed = Signal(bool)
    settings_changed = Signal()
    visible_changed = Signal(bool)
    enlarge_requested = Signal(bool)  # True: show this panel in a maximized window; False: restore the layout

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
        self.audit: list | None = None  # tests: a list collects every text drawn in a box (see TextRec)
        self._mv: MemView | None = None
        self._zoom_pref = 0.0  # 0 = fit the panel (persisted "diagram size")
        self.enlarged = False
        self.setMinimumSize(300, 420)  # the header controls wrap onto more rows when the panel is narrow

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
        self.zoom_out_btn = QPushButton()
        self.zoom_out_btn.setAccessibleName("Zoom out")
        self.zoom_out_btn.setToolTip("Zoom out (Ctrl+- while this panel has the focus, also the - key or Ctrl+wheel)")
        self.zoom_out_btn.clicked.connect(lambda: self.zoom_by(1 / 1.15))
        self.zoom_in_btn = QPushButton()
        self.zoom_in_btn.setAccessibleName("Zoom in")
        self.zoom_in_btn.setToolTip("Zoom in (Ctrl+= while this panel has the focus, also the + key or Ctrl+wheel)")
        self.zoom_in_btn.clicked.connect(lambda: self.zoom_by(1.15))
        self.fit_btn = QPushButton()
        self.fit_btn.setAccessibleName("Fit the diagram to the panel")
        self.fit_btn.setToolTip("Fit the diagram to the panel (Ctrl+0, also the 0 key)")
        self.fit_btn.clicked.connect(lambda: self.zoom_by(0.0))
        self.max_btn = QPushButton()
        self.max_btn.setAccessibleName("Enlarge the CPU Architecture view and labs")
        self.max_btn.setToolTip("Enlarge the CPU Architecture view and the labs to a full window (Ctrl+Shift+F). "
                                "Press Esc or the same button to go back.")
        self.max_btn.clicked.connect(self.toggle_enlarged)
        self.size_combo = QComboBox()
        self.size_combo.setAccessibleName("Diagram size")
        self.size_combo.setToolTip("Diagram size: Fit shrinks or grows the diagram to the panel; a percentage keeps "
                                   "the text at that size (the diagram scrolls). Remembered between sessions.")
        for label, v in ZOOM_CHOICES:
            self.size_combo.addItem(label, v)
        self.size_combo.currentIndexChanged.connect(self._size_chosen)
        for b in (self.zoom_out_btn, self.zoom_in_btn, self.fit_btn, self.max_btn):
            b.setFixedSize(36, 30)
            b.setIconSize(QSize(22, 22))
        # keyboard shortcuts work anywhere inside the panel (also when it floats or is enlarged)
        self._shortcuts = []
        self._zoom_shortcuts = []
        for keys, fn in (("Ctrl+Shift+F", self.toggle_enlarged), ("Ctrl+=", lambda: self.zoom_by(1.15)),
                         ("Ctrl++", lambda: self.zoom_by(1.15)), ("Ctrl+-", lambda: self.zoom_by(1 / 1.15)),
                         ("Ctrl+0", lambda: self.zoom_by(0.0)), ("Esc", self._escape)):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            self._shortcuts.append(sc)
            if keys in ("Ctrl+=", "Ctrl++", "Ctrl+-"):
                self._zoom_shortcuts.append(sc)
            if keys == "Esc":
                self._esc_shortcut = sc
                sc.setEnabled(False)  # Esc only means "back" while enlarged; otherwise it stays free (Find bar)
        # The header is two groups of controls: (left items | right items). It is laid out by _reflow_header():
        # at a normal width that is exactly two rows; in a narrow dock the items wrap onto more rows instead of
        # being cut off, so every control stays reachable.
        self._size_lbl, self._speed_lbl = QLabel("Size:"), QLabel("Speed:")
        self._header_groups = [
            ([self.explain_cb, self.anim_cb, self.reduce_cb, self.dec_cb], [self._size_lbl, self.size_combo]),
            ([self._speed_lbl, self.speed_combo, self.pause_btn, self.skip_btn, self.replay_btn],
             [self.zoom_out_btn, self.zoom_in_btn, self.fit_btn, self.max_btn])]
        self.header = QVBoxLayout()
        self.header.setSpacing(4)
        self._header_sig = None

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
        self.split.setStretchFactor(0, 5)
        self.split.setStretchFactor(1, 2)
        self.split.setSizes([640, 150])
        self.split.setChildrenCollapsible(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(self.header)
        lay.addWidget(self.split, 1)
        lay.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._flush_live)
        self.setTabOrder(self.explain_cb, self.anim_cb)
        self._reflow_header()
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
            f = PairFrame(nid, self.pal, self)
            self.scene.addItem(f)
            self.frames[nid] = f
        order = ["IR", "A", "ALU", "FLAGS", "B", "C", "D", "E", "H", "L", "PC", "SP", "MEMIF", "IOIF", "MEM",
                 "PORT_IN", "PORT_OUT"]
        for nid in order:
            n = NodeItem(nid, self.pal, self)
            n.focused.connect(self._node_focused)
            self.scene.addItem(n)
            self.nodes[nid] = n
        self.caption = CaptionItem()
        self.caption.setPos(CAPTION_X, CAPTION_Y)
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
        line([P(ADDR_RISER, ADDR_Y), P(1180, ADDR_Y)], pen)  # 16-bit address path
        for nid in ("IR", "A", "ALU", "FLAGS", "B", "C", "D", "E", "H", "L", "MEM", "PORT_IN", "PORT_OUT"):
            line(_data_tap(nid), thin)
        for nid in ("PC", "SP", "BC", "DE", "HL", "MEM", "IR"):
            line(_addr_tap(nid), thin)
        mif_y = GEOM["MEMIF"][1] + GEOM["MEMIF"][3] / 2
        line([P(RISER_L, MIDY), P(RISER_L, mif_y), P(GEOM["MEMIF"][0], mif_y)], thin)  # data to the memory interface
        line([P(160, GEOM["MEMIF"][1]), P(160, ADDR_Y)], thin)
        line([P(GEOM["IOIF"][0] + GEOM["IOIF"][2], mif_y), P(RISER_R, mif_y)], thin)
        line([P(RISER_R, DATA_Y), P(RISER_R, MIDY)], thin)
        line([P(990, GEOM["IOIF"][1]), P(990, ADDR_Y)], thin)
        for nid in ("PORT_IN", "PORT_OUT"):
            line([P(_cx(nid), GEOM["IOIF"][1] + GEOM["IOIF"][3]), P(_cx(nid), _top(nid))], thin)
        line([P(100, GEOM["MEMIF"][1] + GEOM["MEMIF"][3]), P(100, _top("MEM"))], thin)
        for text, x, y in (("8-bit internal data path (conceptual)", 820, DATA_Y + 3),
                           ("16-bit address path (conceptual)", 820, ADDR_Y + 3)):
            t = QGraphicsSimpleTextItem(text)
            f = QFont(t.font())
            f.setPointSizeF(FONT_MIN - 1.0)
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
        cf.setPointSizeF(FONT_DETAIL)
        cf.setBold(True)
        self.caption.setFont(cf)
        self.scene.setBackgroundBrush(QBrush(self.pal.c("base")))
        self._icons()
        self.scene.update()

    def _icons(self):
        c, d = self.pal.c("text"), self.pal.c("text_dim")
        for btn, name in ((self.zoom_out_btn, "zoom_out"), (self.zoom_in_btn, "zoom_in"), (self.fit_btn, "fit"),
                          (self.max_btn, "restore" if self.enlarged else "expand")):
            btn.setIcon(make_icon(name, c, d, 22))

    # --------------------------------------------------------- settings
    def settings(self) -> dict:
        return {"explain": self.explain_mode, "animate": self.animate, "reduce_motion": self.reduce_motion,
                "decimal": self.decimal, "speed": self.speed, "zoom": self._zoom_pref}

    def apply_settings(self, explain=True, animate=True, reduce_motion=None, decimal=False, speed=1.0, zoom=0.0):
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
        self._set_zoom_pref(float(zoom), save=False)
        self._redraw()

    def _set_zoom_pref(self, z: float, save: bool = True):
        i = self.size_combo.findData(z)
        if i < 0:
            i = 0 if z <= 0 else min(range(len(ZOOM_CHOICES)), key=lambda k: abs(ZOOM_CHOICES[k][1] - z))
        self.size_combo.blockSignals(True)
        self.size_combo.setCurrentIndex(i)
        self.size_combo.blockSignals(False)
        self._zoom_pref = float(self.size_combo.currentData())
        if self._zoom_pref <= 0:
            self._fit = True
            self._apply_fit()
        else:
            self._fit = False
            self._scale = self._zoom_pref
            self.view.resetTransform()
            self.view.scale(self._scale, self._scale)
        if save:
            self.settings_changed.emit()

    def _size_chosen(self, _i):
        self._set_zoom_pref(float(self.size_combo.currentData()))

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
            self._mv = None
            self._pending_live = None
            self.text.clear()
        elif self._rec is None:
            self._show_idle()
        self._redraw()
        self._update_buttons()

    @property
    def concealed(self) -> bool:
        return self._concealed

    # -------------------------------------------------------------- feeds
    def set_kit(self, kit: KitView):
        if kit == self._kit:  # nothing changed: no redraw (this is called on every refresh while a program runs)
            return
        self._kit = kit
        self._redraw()

    def set_memview(self, mv: MemView | None):
        """Memory / stack snapshot read from the simulator. Ignored while Experiment 1 hides the answer: the cells
        could hold A or a port value, so nothing from memory is stored, let alone drawn."""
        self._mv = None if self._concealed else mv

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
        self._reveal(rec)

    def _reveal(self, rec: StepRecord):
        """When the diagram is taller than the panel (it scrolls rather than shrinking the text), scroll so the
        parts this step used - the Memory area and the stack pointer - are in view."""
        rect = None
        for nid, used in (("MEM", bool(rec.mem_accesses)), ("SP", rec.sp_change is not None)):
            if used:
                r = self.nodes[nid].sceneBoundingRect()
                rect = r if rect is None else rect.united(r)
        if rect is not None:
            self.view.ensureVisible(rect, 12, 12)

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
                fi.setVisible(fl.phase > 0)  # the conceptual fetch is part of the animation, not of the final picture
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
            masked = self._concealed and nid in REG_ORDER  # A and B..L: a stale copy of the answer may sit in any
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
                          masked=self._concealed)
        # pairs
        for pid, fr in self.frames.items():
            st = shown
            if sub_phase and rec is not None and (pid in done_dst or set(PAIRS[pid]) & done_dst):
                st = rec.post
            fr.set_state(role=roles.get(pid, ""), changed=pid in changed and not sub_phase,
                         value=st.pair(pid) if st is not None else None, masked=self._concealed,
                         decimal=self.decimal)
        # IR / interfaces / memory / ports -----------------------------
        hide = self._concealed
        mv = None if hide else self._mv
        self.nodes["SP"].set_state(mv=mv, hide_contents=hide)
        self._update_blocks(rec, shown, sub_phase)
        self.nodes["MEM"].set_state(mv=mv, hide_contents=hide,
                                    uses=tuple(rec.mem_accesses) if rec is not None and not hide else ())
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
            ir.set_state(extra=["(no step captured)" if rec is None else
                                ("(nothing executed)" if rec.kind == "none" else rec.text), "", ""], role="", tag="")
        mem_lines: list[str] = []
        io_lines: list[str] = []
        pin, pout = self.nodes["PORT_IN"], self.nodes["PORT_OUT"]
        sw_port, led_port = kit.switch_port, kit.led_port
        kit_in = kit.enabled
        pin.set_state(title="Input port", extra=[f"port {sw_port:02X}H" + (" (kit)" if kit_in else ""),
                                                  f"switches {hexs(kit.switches, 8)}" if kit_in else "from I/O table",
                                                  bins(kit.switches, 8) + "b" if kit_in else ""], leds=None)
        pout.set_state(title="Output port", extra=[f"port {led_port:02X}H" + (" (kit)" if kit_in else ""),
                                                    "", ""], leds=None)
        if rec is not None and rec.kind == "instr":
            for ev in rec.port_events:
                node = pin if ev.direction == "IN" else pout
                inkit = kit.enabled and ev.port == (sw_port if ev.direction == "IN" else led_port)
                node.set_state(title=("Input port" if ev.direction == "IN" else "Output port"),
                               extra=[f"port {ev.port:02X}H" + (" (kit)" if inkit else ""),
                                      f"{ev.direction} value {hexs(ev.value, 8)}", bins(ev.value, 8) + "b"])
        if kit.enabled and kit.leds_written:
            pout.set_state(leds=kit.leds)
        note = "64K bytes, 0000h-FFFFh"
        if rec is not None:
            note = {"instr": "no memory access in this step", "none": "nothing executed",
                    "interrupt": "interrupt entry: see the stack"}.get(rec.kind, "many instructions ran: see recent use")
        self.nodes["MEM"].set_state(mem_note=note, role=(rec.role_map.get("MEM", "") if rec is not None else ""))
        mif = rec.role_map.get("MEM", "") if rec is not None else ""
        self.nodes["MEMIF"].set_state(extra=["address 16 bits / data 8 bits"], role="")
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
            self._set_zoom_pref(0.0)
            return
        self._fit = False
        self._scale = max(0.3, min(3.0, self._scale * factor))
        self.view.resetTransform()
        self.view.scale(self._scale, self._scale)

    def view_state(self) -> dict:
        """The diagram's zoom and scroll position (kept across Enlarge / Restore)."""
        return {"fit": self._fit, "pref": self._zoom_pref, "scale": self._scale,
                "h": self.view.horizontalScrollBar().value(), "v": self.view.verticalScrollBar().value()}

    def restore_view_state(self, st: dict):
        """Put a ``view_state`` back. The scroll ranges only settle after the panel has been re-laid out, so it is
        applied now and again once the event loop has run."""
        def apply():
            if not st["fit"]:
                self._fit = False
                self._scale = st["scale"]
                self.view.resetTransform()
                self.view.scale(self._scale, self._scale)
                self.view.horizontalScrollBar().setValue(st["h"])
                self.view.verticalScrollBar().setValue(st["v"])
        apply()
        if not st["fit"]:
            QTimer.singleShot(0, apply)
            QTimer.singleShot(80, apply)

    def _apply_fit(self):
        vw, vh = self.view.viewport().width(), self.view.viewport().height()
        if vw < 50:
            return
        s = min(vw / SCENE_W, vh / SCENE_H)
        s = max(MIN_FIT_SCALE, s)  # below this the labels would stop being readable: scroll instead
        self._scale = s
        self.view.resetTransform()
        self.view.scale(s, s)
        self.view.verticalScrollBar().setValue(0)  # a diagram taller than the panel starts at its top
        self.view.horizontalScrollBar().setValue(0)

    def pinned_height(self) -> int:
        """Height the header (all its wrapped rows) needs, plus a strip of the diagram below it. A dock hosting this
        panel must not be shorter, or the controls would be clipped or scrolled away (see DockScroll)."""
        m = self.layout().contentsMargins() if self.layout() is not None else None
        top = m.top() if m is not None else 0
        return top + self.header.sizeHint().height() + self.header.spacing() + 40

    def _reflow_header(self):
        """Wrap the header controls to the panel width (greedy, in reading order). Same widgets, new rows."""
        avail = max(120, self.width() - 12)
        sp = 6
        rows: list[tuple[list, list]] = []
        for left, right in self._header_groups:
            cur, w = [], 0
            for it in left:
                iw = it.sizeHint().width()
                if cur and w + sp + iw > avail:
                    rows.append((cur, []))
                    cur, w = [], 0
                cur.append(it)
                w += iw + (sp if len(cur) > 1 else 0)
            rw = sum(it.sizeHint().width() for it in right) + sp * (len(right) - 1)
            if w + sp + rw <= avail:
                rows.append((cur, right))
            else:
                rows.append((cur, []))
                rows.append(([], right))
        sig = tuple((tuple(id(x) for x in a), tuple(id(x) for x in b)) for a, b in rows)
        if sig == self._header_sig:
            return
        self._header_sig = sig
        while self.header.count():  # drop the old rows; the widgets stay children of the panel
            item = self.header.takeAt(0)
            lay = item.layout()
            if lay is not None:
                while lay.count():
                    lay.takeAt(0)
                lay.setParent(None)
                lay.deleteLater()
        for a, b in rows:
            r = QHBoxLayout()
            for it in a:
                r.addWidget(it)
            r.addStretch(1)
            for it in b:
                r.addWidget(it)
            self.header.addLayout(r)
        self.header.invalidate()
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None:  # the scroll area / dock that hosts us re-reads pinned_height()
            parent.updateGeometry()
            if parent.parentWidget() is not None:
                parent.parentWidget().updateGeometry()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reflow_header()
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

    # --------------------------------------------------------- enlarge
    def set_zoom_keys(self, on: bool):
        """Ctrl+= / Ctrl++ / Ctrl+- inside the panel. A host that already owns those keys (the main window, which
        dispatches them by focus) switches them off so the key is not ambiguous; the enlarged window switches them on."""
        for sc in self._zoom_shortcuts:
            sc.setEnabled(bool(on))

    def toggle_enlarged(self):
        self.set_enlarged(not self.enlarged)

    def set_enlarged(self, on: bool):
        """Ask the main window to show this panel (diagram + labs) in a maximized window, or to put it back.
        The window owner calls ``mark_enlarged`` once it has done so; the panel itself never moves."""
        if bool(on) != self.enlarged:
            self.enlarge_requested.emit(bool(on))

    def mark_enlarged(self, on: bool):
        self.enlarged = bool(on)
        self._esc_shortcut.setEnabled(self.enlarged)
        self.max_btn.setToolTip(("Back to the normal layout (Esc or Ctrl+Shift+F)" if on else
                                 "Enlarge the CPU Architecture view and the labs to a full window (Ctrl+Shift+F). "
                                 "Press Esc or the same button to go back."))
        self.max_btn.setAccessibleName("Restore the normal layout" if on else
                                       "Enlarge the CPU Architecture view and labs")
        self._icons()
        if self._fit:
            QTimer.singleShot(0, self._apply_fit)

    def _escape(self):
        if self.enlarged:
            self.set_enlarged(False)

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
    def audit_paint(self) -> list:
        """Render the whole scene once and return every text drawn inside a box (``TextRec``)."""
        from PySide6.QtGui import QImage
        self.audit = []
        try:
            img = QImage(int(SCENE_W), int(SCENE_H), QImage.Format.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            self.scene.render(p)
            p.end()
            return list(self.audit)
        finally:
            self.audit = None

    def node_texts(self) -> list[str]:
        out = [n.describe() + " " + n.toolTip() for n in self.nodes.values()]
        out += [f.toolTip() for f in self.flow_items]
        out += [self.caption.text(), self.text.toPlainText(), self.status.text()]
        for fr in self.frames.values():
            out.append(f"{fr.nid} {fr.value} {fr.masked}")
        return out
