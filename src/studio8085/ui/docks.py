"""The panels that live in dock widgets: registers, flags, stack, I/O ports,
problems, listing, symbols, interrupts and the output log."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFormLayout, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QSpinBox, QTableView, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from ..core.assembler import ERROR, NOTE, AsmResult, Diagnostic
from .editor import monospace_font
from .icons import make_icon
from .themes import Theme

MONO = None


def mono(size: int = 10) -> QFont:
    return monospace_font(size=size)


def parse_hex(text: str, bits: int) -> int | None:
    t = text.strip().lower().removesuffix("h").removeprefix("0x")
    try:
        v = int(t, 16)
    except ValueError:
        return None
    return v if 0 <= v < (1 << bits) else None


def _table(columns: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(columns))
    t.setHorizontalHeaderLabels(columns)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(23)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.horizontalHeader().setStretchLastSection(True)
    t.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return t


def _item(text: str, align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, font=None, editable=False):
    it = QTableWidgetItem(text)
    it.setTextAlignment(align)
    if font:
        it.setFont(font)
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    else:
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
    return it


# ------------------------------------------------------------------ registers
class RegistersPanel(QTableWidget):
    edited = Signal()
    ROWS = [("A", "r8", 7), ("B", "r8", 0), ("C", "r8", 1), ("D", "r8", 2), ("E", "r8", 3),
            ("H", "r8", 4), ("L", "r8", 5), ("BC", "rp", 0), ("DE", "rp", 1), ("HL", "rp", 2),
            ("SP", "sp", 0), ("PC", "pc", 0)]

    def __init__(self, parent=None):
        super().__init__(len(self.ROWS), 4, parent)
        self.machine = None
        self.theme: Theme | None = None
        self._busy = False
        self._prev: dict[str, int] = {}
        self.setHorizontalHeaderLabels(["Reg", "Hex", "Dec", "Binary"])
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(22)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.horizontalHeader().setStretchLastSection(True)
        f = mono(10)
        for r, (name, *_rest) in enumerate(self.ROWS):
            self.setItem(r, 0, _item(name, font=f))
            self.setItem(r, 1, _item("", Qt.AlignmentFlag.AlignCenter, f, editable=True))
            self.setItem(r, 2, _item("", Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f))
            self.setItem(r, 3, _item("", Qt.AlignmentFlag.AlignCenter, f))
        self.setColumnWidth(0, 44)
        self.setColumnWidth(1, 64)
        self.setColumnWidth(2, 58)
        self.itemChanged.connect(self._changed)
        self.setToolTip("Double-click a Hex value to edit a register")

    def set_machine(self, m):
        self.machine = m
        self.refresh(reset_marks=True)

    def _value(self, kind, idx):
        cpu = self.machine.cpu
        if kind == "r8":
            return cpu.regs[idx], 8
        if kind == "rp":
            return cpu.get_rp(idx), 16
        if kind == "sp":
            return cpu.sp, 16
        return cpu.pc, 16

    def refresh(self, reset_marks: bool = False):
        if not self.machine or not self.theme:
            return
        self._busy = True
        dim, accent, text = self.theme.c("text_dim"), self.theme.c("warning"), self.theme.c("text")
        for r, (name, kind, idx) in enumerate(self.ROWS):
            v, bits = self._value(kind, idx)
            self.item(r, 1).setText(f"{v:0{bits // 4}X}")
            self.item(r, 2).setText(str(v))
            self.item(r, 3).setText(f"{v:08b}" if bits == 8 else "")
            changed = (not reset_marks) and name in self._prev and self._prev[name] != v
            for c in (1, 2, 3):
                self.item(r, c).setForeground(QBrush(accent if changed else text))
            self._prev[name] = v
        self._busy = False

    def set_theme(self, theme):
        self.theme = theme
        self.refresh(reset_marks=True)

    def _changed(self, item: QTableWidgetItem):
        if self._busy or item.column() != 1 or not self.machine:
            return
        name, kind, idx = self.ROWS[item.row()]
        v, bits = self._value(kind, idx)
        new = parse_hex(item.text(), bits)
        cpu = self.machine.cpu
        if new is not None:
            if kind == "r8":
                cpu.regs[idx] = new
            elif kind == "rp":
                cpu.set_rp(idx, new)
            elif kind == "sp":
                cpu.sp = new
            else:
                cpu.pc = new
            self.edited.emit()
        self.refresh(reset_marks=True)


# ----------------------------------------------------------------------- flags
class FlagsPanel(QWidget):
    edited = Signal()
    NAMES = [("S", "s"), ("Z", "z"), ("AC", "ac"), ("P", "p"), ("CY", "cy")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.machine = None
        self.clock_mhz = 3.0
        self._busy = False
        row = QHBoxLayout()
        row.setSpacing(6)
        self.buttons = {}
        for label, attr in self.NAMES:
            b = QToolButton()
            b.setObjectName("FlagButton")
            b.setText(label)
            b.setCheckable(True)
            b.setToolTip({"s": "Sign: bit 7 of the result", "z": "Zero: result was 0",
                          "ac": "Auxiliary carry: carry out of bit 3",
                          "p": "Parity: result has an even number of 1 bits",
                          "cy": "Carry / borrow"}[attr] + "\n(click to toggle)")
            b.toggled.connect(lambda on, a=attr: self._toggled(a, on))
            row.addWidget(b)
            self.buttons[attr] = b
        self.fbyte = QLabel()
        self.fbyte.setFont(mono(10))
        self.fbyte.setObjectName("Dim")

        self.state = QLabel("Not assembled")
        self.state.setObjectName("Pill")
        self.instr = QLabel("0")
        self.tstates = QLabel("0")
        self.elapsed = QLabel("0 µs")
        self.next_instr = QLabel("-")
        for w in (self.instr, self.tstates, self.elapsed, self.next_instr):
            w.setFont(mono(10))
        form = QFormLayout()
        form.setContentsMargins(0, 8, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow("State", self.state)
        form.addRow("Next", self.next_instr)
        form.addRow("Instructions", self.instr)
        self.tstates_label = QLabel("T-states")
        form.addRow(self.tstates_label, self.tstates)
        self.elapsed_label = QLabel("Time @ 3 MHz")
        form.addRow(self.elapsed_label, self.elapsed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addLayout(row)
        lay.addWidget(self.fbyte)
        lay.addLayout(form)
        lay.addStretch(1)

    def set_machine(self, m):
        self.machine = m
        self.refresh()

    def set_simple(self, simple: bool):
        """Beginner mode hides the detailed timing rows."""
        for w in (self.tstates, self.elapsed, self.elapsed_label):
            w.setVisible(not simple)
        self.tstates_label.setVisible(not simple)
        if self.layout() is not None:  # see MemoryPanel.set_simple
            self.layout().invalidate()
        self.updateGeometry()

    def set_clock(self, mhz: float):
        self.clock_mhz = mhz
        self.elapsed_label.setText(f"Time @ {mhz:g} MHz")
        self.refresh()

    def set_state(self, text: str, kind: str = "Pill"):
        self.state.setText(text)
        self.state.setObjectName(kind)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)

    def refresh(self):
        if not self.machine:
            return
        cpu = self.machine.cpu
        self._busy = True
        for _, attr in self.NAMES:
            self.buttons[attr].setChecked(bool(getattr(cpu, attr)))
        self._busy = False
        f = cpu.f
        self.fbyte.setText(f"F = {f:02X}h   {f >> 4:04b} {f & 15:04b}b")
        self.instr.setText(f"{cpu.icount:,}")
        self.tstates.setText(f"{cpu.tstates:,}")
        us = cpu.tstates / self.clock_mhz
        self.elapsed.setText(f"{us:,.1f} µs" if us < 1000 else (f"{us / 1000:,.2f} ms" if us < 1e6 else f"{us / 1e6:,.3f} s"))
        self.next_instr.setText(f"{cpu.pc:04X}h  {self.machine.next_instruction()}")

    def _toggled(self, attr, on):
        if self._busy or not self.machine:
            return
        setattr(self.machine.cpu, attr, 1 if on else 0)
        self.refresh()
        self.edited.emit()


# ----------------------------------------------------------------------- stack
class StackPanel(QWidget):
    ROWS = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.machine = None
        self.theme: Theme | None = None
        self.caption = QLabel()
        self.caption.setObjectName("Dim")
        self.table = _table(["Address", "Byte", "Word", "Points to"])
        self.table.setRowCount(self.ROWS)
        f = mono(10)
        for r in range(self.ROWS):
            for c in range(4):
                self.table.setItem(r, c, _item("", Qt.AlignmentFlag.AlignCenter if c < 3 else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f))
        self.table.setColumnWidth(0, 78)
        self.table.setColumnWidth(1, 50)
        self.table.setColumnWidth(2, 60)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.caption)
        lay.addWidget(self.table)
        self.caption.setContentsMargins(8, 6, 8, 6)

    def set_machine(self, m):
        self.machine = m
        self.reset()

    def reset(self):
        self.base = self.machine.cpu.sp if self.machine else 0xFFFF
        self._last_sp = self.base

    def set_theme(self, theme):
        self.theme = theme

    def update_base(self):
        """Track where the stack started. Cheap, and must run even while this panel is hidden
        (the memory-cell detail uses it to tell stack bytes from unused memory)."""
        if not self.machine:
            return
        sp = self.machine.cpu.sp
        # The stack base is where SP started; a big jump (LXI SP / SPHL) moves it.
        if abs(sp - self._last_sp) > 32 or sp > self.base:
            self.base = sp
        self._last_sp = sp

    def refresh(self):
        if not self.machine:
            return
        cpu = self.machine.cpu
        d = cpu.mem.data
        sp = cpu.sp
        self.update_base()
        depth = max(0, self.base - sp)
        self.caption.setText(f"SP = {sp:04X}h   -   {depth} byte(s) on the stack" if depth
                             else f"SP = {sp:04X}h   -   stack is empty")
        for r in range(self.ROWS):
            a = (sp + r) & 0xFFFF
            live = r < depth
            self.table.item(r, 0).setText(("► " if r == 0 else "") + f"{a:04X}" if (live or r == 0) else "")
            self.table.item(r, 1).setText(f"{d[a]:02X}" if live else "")
            if live and r % 2 == 0 and r + 1 < depth:
                w = d[a] | (d[(a + 1) & 0xFFFF] << 8)
                self.table.item(r, 2).setText(f"{w:04X}")
                self.table.item(r, 3).setText(self.machine.symbol_for(w) or "")
            else:
                self.table.item(r, 2).setText("")
                self.table.item(r, 3).setText("")
            if self.theme:
                self.table.item(r, 0).setForeground(QBrush(self.theme.c("warning") if r == 0 else self.theme.c("text")))


# ------------------------------------------------------------------- I/O ports
class IOModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.machine = None
        self.theme: Theme | None = None
        self.font = mono(10)
        self.written: dict[int, int] = {}

    def rowCount(self, parent=QModelIndex()):
        return 256

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ["Port", "Value (hex)", "Dec", "Binary"][section]
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return f | Qt.ItemFlag.ItemIsEditable if index.column() == 1 else f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not self.machine or not self.theme:
            return None
        port, col = index.row(), index.column()
        v = self.machine.cpu.io[port]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return [f"{port:02X}h", f"{v:02X}", str(v), f"{v:08b}"][col]
        if role == Qt.ItemDataRole.FontRole:
            return self.font
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            return QBrush(self.theme.c("text") if (v or port in self.written) else self.theme.c("text_dim"))
        if role == Qt.ItemDataRole.BackgroundRole and port in self.written:
            age = self.machine.cpu.icount - self.written[port]
            if age < 2000:
                return QBrush(QColor(self.theme.colors["heat_write"]).darker(300 if self.theme.dark else 100)
                              if self.theme.dark else QColor("#ffe7cf"))
        if role == Qt.ItemDataRole.ToolTipRole:
            return ("Edit the value to feed this port; IN reads it.\n"
                    + ("Last written by OUT" if port in self.written else "Not written by the program"))
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole and index.column() == 1 and self.machine:
            v = parse_hex(str(value), 8)
            if v is None:
                return False
            self.machine.cpu.io[index.row()] = v
            self.dataChanged.emit(index, index)
            return True
        return False


class IOPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = IOModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(23)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 56)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 56)
        self.goto = QLineEdit()
        self.goto.setPlaceholderText("Go to port (hex)")
        self.goto.setMaximumWidth(150)
        hint = QLabel("Edit a value to feed a port - IN reads it, OUT writes it.")
        hint.setObjectName("Dim")
        top = QHBoxLayout()
        top.setContentsMargins(6, 6, 6, 6)
        top.addWidget(self.goto)
        top.addWidget(hint, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.table)
        self.goto.returnPressed.connect(self._goto)

    def set_machine(self, m):
        self.model.machine = m
        self.model.layoutChanged.emit()

    def set_theme(self, theme):
        self.model.theme = theme
        self.model.layoutChanged.emit()

    def note_out(self, port: int, icount: int):
        self.model.written[port] = icount

    def refresh(self):
        self.table.viewport().update()

    def _goto(self):
        p = parse_hex(self.goto.text(), 8)
        if p is not None:
            self.table.scrollTo(self.model.index(p, 1), QAbstractItemView.ScrollHint.PositionAtCenter)
            self.table.selectRow(p)


# -------------------------------------------------------------------- problems
class ProblemsPanel(QWidget):
    goto = Signal(int, int)
    counts = Signal(int, int, int)  # errors, warnings, notes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = _table(["", "Line", "Col", "Message"])
        self.table.setColumnWidth(0, 28)
        self.table.setColumnWidth(1, 50)
        self.table.setColumnWidth(2, 44)
        self.empty = QLabel("No problems")
        self.empty.setObjectName("Dim")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.table)
        lay.addWidget(self.empty)
        self.table.cellActivated.connect(self._activated)
        self.table.cellDoubleClicked.connect(self._activated)
        self._icons: dict[str, object] = {}
        self._diags: list[Diagnostic] = []
        self.set_theme_colors("#e5484d", "#e0b341", "#4f9cff")

    def set_theme_colors(self, err: str, warn: str, info: str):
        self._icons = {ERROR: make_icon("error", err), "warning": make_icon("warning", warn),
                       NOTE: make_icon("info", info)}

    def set_theme(self, theme: Theme):
        self.set_theme_colors(theme.colors["error"], theme.colors["warning"], theme.colors["info"])
        self.set_diagnostics(self._diags)

    def set_diagnostics(self, diags: list[Diagnostic]):
        self._diags = diags
        t = self.table
        t.setRowCount(len(diags))
        for r, d in enumerate(diags):
            it = _item("")
            it.setIcon(self._icons[d.severity])
            t.setItem(r, 0, it)
            t.setItem(r, 1, _item(str(d.line), Qt.AlignmentFlag.AlignCenter))
            t.setItem(r, 2, _item(str(d.start + 1), Qt.AlignmentFlag.AlignCenter))
            t.setItem(r, 3, _item(d.message))
        self.table.setVisible(bool(diags))
        self.empty.setVisible(not diags)
        e = sum(1 for d in diags if d.severity == ERROR)
        n = sum(1 for d in diags if d.severity == NOTE)
        self.counts.emit(e, len(diags) - e - n, n)

    def _activated(self, row, _col):
        d = self._diags[row]
        self.goto.emit(d.line, d.start)


# --------------------------------------------------------------------- listing
class ListingPanel(QWidget):
    goto = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = _table(["Line", "Addr", "Bytes", "Source"])
        self.table.setColumnWidth(0, 46)
        self.table.setColumnWidth(1, 56)
        self.table.setColumnWidth(2, 110)
        self.table.cellDoubleClicked.connect(lambda r, c: self.goto.emit(r + 1))
        self.theme: Theme | None = None
        self._row_of_addr: dict[int, int] = {}
        self._hl: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)

    def set_theme(self, theme):
        self.theme = theme

    def set_result(self, res: AsmResult):
        t = self.table
        f = mono(10)
        t.setUpdatesEnabled(False)
        t.setRowCount(len(res.listing))
        for r, l in enumerate(res.listing):
            t.setItem(r, 0, _item(str(l.line), Qt.AlignmentFlag.AlignCenter, f))
            t.setItem(r, 1, _item(f"{l.addr:04X}" if l.addr is not None else "", Qt.AlignmentFlag.AlignCenter, f))
            hexs = " ".join(f"{b:02X}" for b in l.data[:4]) + (" …" if len(l.data) > 4 else "")
            t.setItem(r, 2, _item(hexs, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f))
            t.setItem(r, 3, _item(l.text.replace("\t", "    "), font=f))
        t.setUpdatesEnabled(True)
        self._hl = None

    def highlight(self, line: int | None):
        t = self.table
        if self._hl is not None and self._hl <= t.rowCount() and self.theme:
            for c in range(4):
                it = t.item(self._hl - 1, c)
                if it:
                    it.setBackground(QBrush())
        self._hl = line
        if line and self.theme and line <= t.rowCount():
            col = QBrush(self.theme.c("exec_line"))
            for c in range(4):
                it = t.item(line - 1, c)
                if it:
                    it.setBackground(col)
            t.scrollToItem(t.item(line - 1, 3), QAbstractItemView.ScrollHint.EnsureVisible)


# --------------------------------------------------------------------- symbols
class SymbolsPanel(QWidget):
    goto = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = _table(["Name", "Value", "Type", "Contents (live)"])
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 64)
        self.table.setColumnWidth(2, 54)
        self.machine = None
        self._syms = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)
        self.table.cellDoubleClicked.connect(lambda r, c: self.goto.emit(self._syms[r].line))

    def set_machine(self, m):
        self.machine = m

    def set_result(self, res: AsmResult):
        f = mono(10)
        self._syms = sorted(res.symbols.values(), key=lambda s: (s.kind == "equ", s.value, s.name.lower()))
        t = self.table
        t.setRowCount(len(self._syms))
        for r, s in enumerate(self._syms):
            t.setItem(r, 0, _item(s.name, font=f))
            t.setItem(r, 1, _item(f"{s.value & 0xFFFF:04X}h" if s.kind != "equ" else f"{s.value}",
                                  Qt.AlignmentFlag.AlignCenter, f))
            t.setItem(r, 2, _item({"label": "code", "data": "data", "equ": "const"}[s.kind]))
            t.setItem(r, 3, _item("", font=f))
        self.refresh()

    def refresh(self):
        if not self.machine:
            return
        d = self.machine.cpu.mem.data
        for r, s in enumerate(self._syms):
            if s.kind == "data":
                n = max(1, s.size)
                txt = " ".join(f"{d[(s.value + i) & 0xFFFF]:02X}" for i in range(min(n, 8)))
                if n > 8:
                    txt += f" … ({n} bytes)"
                self.table.item(r, 3).setText(txt)
            elif s.kind == "equ":
                self.table.item(r, 3).setText(f"= {s.value} = {s.value & 0xFFFF:X}h")
            else:
                self.table.item(r, 3).setText("")


# ------------------------------------------------------------------- interrupts
class InterruptPanel(QWidget):
    raised = Signal(str, int)
    edited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.machine = None
        grid = QGridLayout()
        grid.setSpacing(6)
        self.buttons = {}
        specs = [("TRAP", "TRAP", True, "Non-maskable. Vector 0024h"), ("RST 7.5", "RST7.5", False, "Vector 003Ch (edge-triggered latch)"),
                 ("RST 6.5", "RST6.5", False, "Vector 0034h"), ("RST 5.5", "RST5.5", False, "Vector 002Ch")]
        for i, (label, name, nm, tip) in enumerate(specs):
            b = QPushButton(label)
            b.setObjectName("IrqButton")
            b.setProperty("nonmaskable", nm)
            b.setToolTip(tip + "\nRaises the request; it is taken after the current instruction if unmasked.")
            b.clicked.connect(lambda _=False, n=name: self.raised.emit(n, 0))
            grid.addWidget(b, i // 2, i % 2)
            self.buttons[name] = b
        self.intr = QPushButton("INTR")
        self.intr.setObjectName("IrqButton")
        self.intr.setToolTip("External interrupt: supplies RST n. Needs IE=1 (EI).")
        self.rst_n = QSpinBox()
        self.rst_n.setRange(0, 7)
        self.rst_n.setValue(7)
        self.rst_n.setPrefix("RST ")
        self.rst_n.setToolTip("Which RST n instruction the device puts on the bus")
        self.intr.clicked.connect(lambda: self.raised.emit("INTR", self.rst_n.value()))
        grid.addWidget(self.intr, 2, 0)
        grid.addWidget(self.rst_n, 2, 1)

        self.pills = {}
        pill_row = QHBoxLayout()
        pill_row.setSpacing(5)
        for key, label in (("ie", "IE"), ("m75", "M7.5"), ("m65", "M6.5"), ("m55", "M5.5")):
            p = QLabel(label)
            p.setObjectName("Pill")
            p.setToolTip({"ie": "Interrupt enable (EI/DI)", "m75": "RST 7.5 masked", "m65": "RST 6.5 masked",
                          "m55": "RST 5.5 masked"}[key] + " - lit means ON/masked")
            pill_row.addWidget(p)
            self.pills[key] = p
        pill_row.addStretch(1)
        self.pending = QLabel("Pending: none")
        self.pending.setObjectName("Dim")
        self.sid = QCheckBox("SID input (serial in) = 1")
        self.sid.toggled.connect(self._sid)
        self.sod = QLabel("SOD (serial out) = 0")
        self.sod.setObjectName("Dim")
        note = QLabel("After reset RST 7.5/6.5/5.5 are masked. Use\nMVI A,08h / SIM to unmask, then EI.")
        note.setObjectName("Dim")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addLayout(grid)
        lay.addSpacing(6)
        lay.addLayout(pill_row)
        lay.addWidget(self.pending)
        lay.addWidget(self.sid)
        lay.addWidget(self.sod)
        lay.addWidget(note)
        lay.addStretch(1)

    def set_machine(self, m):
        self.machine = m
        self.refresh()

    def _sid(self, on):
        if self.machine:
            self.machine.cpu.sid = 1 if on else 0

    def refresh(self):
        if not self.machine:
            return
        cpu = self.machine.cpu
        for key in ("ie", "m75", "m65", "m55"):
            p = self.pills[key]
            on = bool(getattr(cpu, key))
            want = "PillOn" if on else "Pill"
            if p.objectName() != want:
                p.setObjectName(want)
                p.style().unpolish(p)
                p.style().polish(p)
        names = [n for n, bit in (("TRAP", 1), ("RST 7.5", 2), ("RST 6.5", 4), ("RST 5.5", 8), ("INTR", 16)) if cpu.pending & bit]
        self.pending.setText("Pending: " + (", ".join(names) if names else "none"))
        self.sod.setText(f"SOD (serial out) = {cpu.sod}")


# ----------------------------------------------------------------------- output
class OutputPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log = QPlainTextEdit()
        self.log.setObjectName("OutputLog")
        self.log.setReadOnly(True)
        self.log.setFont(mono(10))
        self.log.setMaximumBlockCount(5000)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.log.clear)
        top = QHBoxLayout()
        top.setContentsMargins(6, 4, 6, 4)
        top.addStretch(1)
        top.addWidget(clear)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.log)

    def add(self, text: str):
        self.log.appendPlainText(text)


# ------------------------------------------------------------------- explain
class ExplainPanel(QScrollArea):
    """Plain-language explanation of the next instruction and of what the last step changed."""

    predict_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.machine = None
        self._active = False
        self.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(4)

        def label(obj=None):
            w = QLabel()
            w.setWordWrap(True)
            w.setTextFormat(Qt.TextFormat.RichText)
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            w.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            if obj:
                w.setObjectName(obj)
            return w

        self.predict = QCheckBox("Predict first (hide the result)")
        self.predict.setToolTip("Hide what the next instruction will produce, so you can work it out yourself\n"
                                "and then step to compare. The explanation of what the instruction does stays visible.")
        self.predict.toggled.connect(self._predict_toggled)
        self.meta = label("Card")
        self.meta.hide()
        self.next_title = QLabel("NEXT INSTRUCTION")
        self.next_title.setObjectName("Section")
        self.next = label()
        self.last_title = QLabel("WHAT JUST HAPPENED")
        self.last_title.setObjectName("Section")
        self.last = label()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Item", "Before", "After"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.hide()
        self.notes = label()
        for w in (self.predict, self.meta, self.next_title, self.next, self.last_title, self.last, self.table,
                  self.notes):
            lay.addWidget(w)
        lay.addStretch(1)
        self.setWidget(body)
        self.show_hint()

    def set_machine(self, m):
        self.machine = m

    def set_predict_first(self, on: bool):
        self.predict.blockSignals(True)
        self.predict.setChecked(on)
        self.predict.blockSignals(False)
        self.refresh_next(self._active)

    def _predict_toggled(self, on: bool):
        self.refresh_next(self._active)
        self.predict_changed.emit(on)

    def set_meta(self, meta: dict[str, str]):
        from ..core.meta import describe_validation
        keys = [("title", None), ("topic", "Topic"), ("chapter", "Chapter"), ("section", "Section"),
                ("level", "Level"), ("validation", "Validation"), ("id", "Example"), ("related", "Related")]
        lines = []
        for k, label in keys:
            if k in meta:
                if k == "title":
                    lines.append(f"<b style='font-size:110%'>{_html(meta[k])}</b>")
                else:
                    extra = ""
                    if k == "validation":
                        extra = " <span style='opacity:.7'>(" + "; ".join(describe_validation(meta[k])).replace("<", "&lt;") + ")</span>"
                    lines.append(f"{label}: <b>{_html(meta[k])}</b>{extra}")
        self.meta.setText("<br>".join(lines))
        self.meta.setVisible(bool(lines))
        if "validation" in meta:
            from ..core.meta import VALIDATION_RULE
            self.meta.setToolTip("\n".join(describe_validation(meta["validation"], with_limits=True)
                                           + [VALIDATION_RULE]))
        else:
            self.meta.setToolTip("")

    def show_hint(self):
        self.next.setText("<p>Assemble the program (<b>F7</b>) or press a step button. Before each instruction runs, "
                          "this panel explains it in plain language using the actual register values, and says "
                          "whether a branch will be taken.</p>")
        self.clear_last()

    def refresh_next(self, active: bool):
        self._active = active
        if not self.machine:
            return
        if not active:
            self.next.setText("<p><i>No program is loaded.</i> Press <b>Assemble</b> (F7) or <b>Step</b> (F11).</p>")
            return
        from ..core.explain import explain_next
        self.next.setText(explain_next(self.machine.cpu).html(hide_outcome=self.predict.isChecked()))

    def clear_last(self, text: str = ""):
        self.last.setText(text or "<p><i>Nothing has run yet.</i></p>")
        self.table.hide()
        self.notes.setText("")

    def show_last(self, head: str, items, notes: list[str], extra: list[str]):
        """``items`` are (name, before, after) triples; ``notes`` explain flag changes."""
        self.last.setText(head)
        self.table.setRowCount(len(items))
        f = mono(10)
        for r, (name, a, b) in enumerate(items):
            for c, text in enumerate((name, a, b)):
                it = QTableWidgetItem(text)
                it.setFont(f)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter if c else Qt.AlignmentFlag.AlignLeft)
                self.table.setItem(r, c, it)
        self.table.setFixedHeight(min(len(items), 14) * 22 + 26)
        self.table.setVisible(bool(items))
        body = []
        for n in notes:
            body.append(f"<p style='margin:1px 0'>&bull; {_html(n)}</p>")
        for x in extra:
            body.append(f"<p style='margin:1px 0'>{_html(x)}</p>")
        self.notes.setText("".join(body))


def _html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ----------------------------------------------------------------------- trace
class TracePanel(QWidget):
    """Live trace table: one row per executed instruction (state after it ran)."""

    export_requested = Signal()
    clear_requested = Signal()
    record_toggled = Signal(bool)
    MAX_ROWS = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        from ..core.trace import COLUMNS
        self.columns = COLUMNS
        self.record = QCheckBox("Record trace")
        self.record.setToolTip("Keep one row per executed instruction (up to 100,000). Slows execution down a little.")
        self.record.toggled.connect(self.record_toggled)
        self.info = QLabel("Recording is off")
        self.info.setObjectName("Dim")
        self.export = QPushButton("Export...")
        self.export.clicked.connect(self.export_requested)
        self.clear = QPushButton("Clear")
        self.clear.clicked.connect(self.clear_requested)
        top = QHBoxLayout()
        top.setContentsMargins(8, 6, 8, 6)
        top.setSpacing(14)
        for w in (self.record, self.info):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(self.export)
        top.addWidget(self.clear)
        self.table = _table(self.columns)
        self.table.horizontalHeader().setStretchLastSection(True)
        f = mono(10)
        self._font = f
        for c, w in enumerate([48, 62, 46, 150, 34, 34, 34, 34, 34, 34, 34, 52, 52, 26, 26, 30, 26, 30, 64, 62]):
            self.table.setColumnWidth(c, w)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.table)
        self._shown = 0
        self._first = 0

    def set_recording(self, on: bool):
        self.record.blockSignals(True)
        self.record.setChecked(on)
        self.record.blockSignals(False)

    def refresh(self, machine=None):
        m = machine or getattr(self, "machine", None)
        if m is None:
            return
        self.machine = m
        rows = m.trace
        n = len(rows)
        start = max(0, n - self.MAX_ROWS)
        t = self.table
        if n < self._shown or start != self._first or (n == 0 and t.rowCount()):
            t.setRowCount(0)
            self._shown = start
            self._first = start
        if n > self._shown:
            t.setUpdatesEnabled(False)
            base = t.rowCount()
            t.setRowCount(base + n - self._shown)
            for i, row in enumerate(rows[self._shown:n]):
                for c, text in enumerate(row.cells()):
                    it = QTableWidgetItem(text)
                    it.setFont(self._font)
                    it.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if c in (3, 20) else Qt.AlignmentFlag.AlignRight))
                    t.setItem(base + i, c, it)
            t.setUpdatesEnabled(True)
            t.scrollToBottom()
            self._shown = n
        msg = "Recording is off" if not m.trace_on and n == 0 else f"{n:,} instruction(s) recorded"
        if start:
            msg += f" - showing the last {self.MAX_ROWS:,}"
        if m.trace_truncated:
            msg += " - limit reached, recording stopped"
        self.info.setText(msg)
