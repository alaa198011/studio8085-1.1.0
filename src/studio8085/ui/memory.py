"""Memory views: a 64K heatmap (256 x 256 bytes) and an editable hex table."""

from __future__ import annotations

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QPointF, QRectF, QSize, Qt, Signal)
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QImage, QPainter, QPalette, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QSplitter, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
                               QTableView, QVBoxLayout, QWidget)

from .editor import monospace_font
from .themes import Theme

# palette index layout for the heatmap image
IDX_READ, IDX_WRITE, IDX_EXEC = 32, 64, 96
CONTENT_TABLE = bytes(0 if v == 0 else 1 + (v * 30) // 255 for v in range(256))


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


class HeatmapWidget(QWidget):
    """64 x 64 cells. Overview: each cell is 16 bytes (all 64 KB).
    Zoom: each cell is one byte of a 4 KB page."""

    address_clicked = Signal(int)
    address_hovered = Signal(int)
    zoom_requested = Signal(int)

    MODES = [("Recent activity", "recent"), ("Access frequency", "freq"),
             ("Execution count", "exec"), ("Contents", "data")]
    LEFT, TOP, GRID = 36, 6, 64

    def __init__(self, parent=None):
        super().__init__(parent)
        self.machine = None
        self.theme: Theme | None = None
        self.mode = "recent"
        self.recent_window = 400  # instructions a touched byte stays "hot"
        self.zoom = False
        self.focus: int | None = None  # address whose 4 KB page is shown when zoomed
        self.selected: int | None = None
        self.hover: int | None = None
        self._img: QImage | None = None
        self._buf = b""
        self._table: list[int] = []
        self._base = 0
        self.setMouseTracking(True)
        # Small enough for 3 px squares (the smallest _rect() draws): the Memory Map then still fits a
        # 768 px tall screen in Advanced mode. It grows to 4+ px squares as soon as there is room.
        self.setMinimumSize(240, 220)

    def _small_font(self) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(max(6.5, f.pointSizeF() - 2))
        return f

    def _left(self) -> int:
        """Left margin for the address labels: wide enough for 'F000' in the current font size."""
        return max(self.LEFT, QFontMetrics(self._small_font()).horizontalAdvance("F000") + 10)

    @property
    def per(self) -> int:
        return 1 if self.zoom else 16

    # -------------------------------------------------------------- setup
    def set_theme(self, theme: Theme):
        self.theme = theme
        base, dim = theme.c("base"), theme.c("text_dim")
        t = [base.rgb()] * 256
        for i in range(1, 32):
            t[i] = mix(base, dim, 0.12 + 0.60 * i / 31).rgb()
        for start, key in ((IDX_READ, "heat_read"), (IDX_WRITE, "heat_write"), (IDX_EXEC, "heat_exec")):
            hot = theme.c(key)
            for i in range(32):
                t[start + i] = mix(base, hot, 0.30 + 0.70 * i / 31).rgb()
        self._table = t
        self.rebuild()

    def set_machine(self, machine):
        self.machine = machine
        self.rebuild()

    def set_mode(self, mode: str):
        self.mode = mode
        self.rebuild()

    def set_zoom(self, on: bool, focus: int | None = None):
        self.zoom = on
        if focus is not None:
            self.focus = focus
        self.rebuild()

    # -------------------------------------------------------------- image
    def rebuild(self):
        if not self.machine or not self._table:
            return
        cpu = self.machine.cpu
        mem = cpu.mem
        data = mem.data
        per = self.per
        n = self.GRID * self.GRID
        if self.zoom:
            focus = self.focus if self.focus is not None else cpu.pc
            base = focus & 0xF000
            buf = bytearray(data[base:base + n].translate(CONTENT_TABLE))
        else:
            base = 0
            buf = bytearray(n)
            for i in range(n):
                nz = 16 - data.count(0, i * 16, i * 16 + 16)
                if nz:
                    buf[i] = 1 + (nz * 30) // 16
        self._base = base
        best: dict[int, int] = {}

        def put(a, idx, ranked):
            c = (a - base) // per
            if 0 <= c < n and (c not in best or ranked > best[c][0]):
                best[c] = (ranked, idx)

        mode = self.mode
        if mode == "recent":
            clock, win, last, kind = cpu.icount, self.recent_window, mem.last, mem.kind
            for a in mem.hot:
                age = clock - last[a]
                if age <= win:
                    level = 31 - (age * 31) // win
                    put(a, (IDX_READ if kind[a] == 1 else IDX_WRITE) + level, level)
        elif mode == "freq":
            rd, wr = mem.rd, mem.wr
            for a in mem.hot:
                cnt = rd[a] + wr[a]
                level = min(31, (cnt.bit_length() * 31) // 18)
                put(a, (IDX_WRITE if wr[a] >= rd[a] else IDX_READ) + level, level)
        elif mode == "exec" and self.machine.program:
            ec = cpu.exec_count
            for a in self.machine.program.addr_to_line:
                cnt = ec[a]
                if cnt:
                    level = min(31, (cnt.bit_length() * 31) // 18)
                    put(a, IDX_EXEC + level, level)
        for c, (_, idx) in best.items():
            buf[c] = idx
        self._buf = bytes(buf)
        img = QImage(self._buf, self.GRID, self.GRID, self.GRID, QImage.Format.Format_Indexed8)
        img.setColorTable(self._table)
        self._img = img
        self.update()

    # ----------------------------------------------------------- geometry
    def _rect(self) -> QRectF:
        w, h = self.width() - self._left() - 6, self.height() - self.TOP - 22
        cell = max(3, int(min(w, h)) // self.GRID)
        side = cell * self.GRID
        x0 = max(self._left(), (self.width() - side) / 2)
        return QRectF(x0, self.TOP, side, side)

    def _addr_at(self, pos: QPointF) -> int | None:
        r = self._rect()
        if not r.contains(pos):
            return None
        col = int((pos.x() - r.left()) / r.width() * self.GRID)
        row = int((pos.y() - r.top()) / r.height() * self.GRID)
        return max(0, min(0xFFFF, self._base + (row * self.GRID + col) * self.per))

    def _cell_rect(self, addr: int) -> QRectF | None:
        c = (addr - self._base) // self.per
        if not 0 <= c < self.GRID * self.GRID:
            return None
        r = self._rect()
        s = r.width() / self.GRID
        return QRectF(r.left() + (c % self.GRID) * s, r.top() + (c // self.GRID) * s, s, s)

    # -------------------------------------------------------------- paint
    def paintEvent(self, e):
        if not self.theme or self._img is None:
            return
        t = self.theme
        p = QPainter(self)
        p.fillRect(self.rect(), t.c("panel"))
        r = self._rect()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(r, self._img)
        s = r.width() / self.GRID
        grid = QColor(t.c("panel"))
        grid.setAlpha(150)
        p.setPen(QPen(grid, 1))
        for k in range(1, self.GRID):
            p.drawLine(QPointF(r.left() + k * s, r.top()), QPointF(r.left() + k * s, r.bottom()))
            p.drawLine(QPointF(r.left(), r.top() + k * s), QPointF(r.right(), r.top() + k * s))
        band = QPen(t.c("border"))
        p.setFont(self._small_font())
        rows_per_label = 4
        for k in range(0, self.GRID // rows_per_label):
            y = r.top() + k * rows_per_label * s
            if k:
                p.setPen(band)
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            addr = self._base + k * rows_per_label * self.GRID * self.per
            p.setPen(t.c("text_dim"))
            p.drawText(QRectF(r.left() - self._left(), y, self._left() - 5, QFontMetrics(self._small_font()).height() + 2),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, f"{addr:04X}")
        p.setPen(band)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        if self.machine:
            cpu = self.machine.cpu
            for addr, key in ((cpu.pc, "ok"), (cpu.sp, "warning")):
                cr = self._cell_rect(addr)
                if cr:
                    p.setPen(QPen(t.c(key), 2))
                    p.drawRect(cr.adjusted(-1, -1, 1, 1))
        for addr, key in ((self.selected, "accent"), (self.hover, "text")):
            cr = self._cell_rect(addr) if addr is not None else None
            if cr:
                p.setPen(QPen(t.c(key), 1.5))
                p.drawRect(cr.adjusted(-1, -1, 1, 1))
        if self.zoom:
            p.setPen(t.c("text_dim"))
            p.drawText(QRectF(r.left(), r.bottom() + 1, r.width(), 14), Qt.AlignmentFlag.AlignRight,
                       f"page {self._base:04X}h-{self._base + 0xFFF:04X}h, one square per byte")

    # -------------------------------------------------------------- mouse
    def mouseMoveEvent(self, e):
        a = self._addr_at(e.position())
        if a != self.hover:
            self.hover = a
            self.update()
            if a is not None:
                self.address_hovered.emit(a)
                self.setToolTip(self._describe(a))
            else:
                self.setToolTip("")

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        a = self._addr_at(e.position())
        if a is not None and e.button() == Qt.MouseButton.LeftButton:
            self.selected = a
            self.address_clicked.emit(a)
            self.update()

    def mouseDoubleClickEvent(self, e):
        a = self._addr_at(e.position())
        if a is not None and e.button() == Qt.MouseButton.LeftButton:
            self.zoom_requested.emit(a)

    def _describe(self, a: int) -> str:
        if not self.machine:
            return ""
        mem = self.machine.cpu.mem
        per = self.per
        lo, hi = a, a + per - 1
        rd, wr = sum(mem.rd[lo:hi + 1]), sum(mem.wr[lo:hi + 1])
        sym = self.machine.symbol_for(lo)
        head = f"{lo:04X}h" if per == 1 else f"{lo:04X}h - {hi:04X}h"
        body = (f"value {mem.data[lo]:02X}h = {mem.data[lo]}" if per == 1
                else f"{16 - mem.data.count(0, lo, hi + 1)} of 16 bytes non-zero")
        tail = "" if per == 16 else "\n(double-click the overview to zoom into a 4 KB page)"
        return head + (f"  ({sym})" if sym else "") + f"\n{body}\nreads {rd}, writes {wr}" + tail


MARK_ROLE = Qt.ItemDataRole.UserRole + 5


class MarkDelegate(QStyledItemDelegate):
    """Draws the normal cell, then a small R / W letter in the corner of the cells the last step used, so the
    read / write distinction never depends on colour."""

    def paint(self, painter, option, index):
        mk = index.data(MARK_ROLE)
        if not mk:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        value, opt.text = opt.text, ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        painter.setPen(fg.color() if isinstance(fg, QBrush) else option.palette.color(QPalette.ColorRole.Text))
        f = QFont(option.font)
        f.setBold(True)
        painter.setFont(f)
        r = option.rect.adjusted(2, 0, -2, 0)
        painter.drawText(r, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)
        f.setPointSizeF(max(6.5, f.pointSizeF() * 0.65))
        painter.setFont(f)
        painter.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, mk)  # R / W: not colour only
        painter.restore()


class HexModel(QAbstractTableModel):
    edited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.machine = None
        self.theme: Theme | None = None
        self.window = 400
        self.font = monospace_font(size=10)
        self.edit_hook = None
        self.marks: dict[int, str] = {}  # cells used by the last step: "R", "W" or "RW" (read from the recorder)

    def set_theme(self, theme):
        self.theme = theme
        self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()):
        return 4096

    def columnCount(self, parent=QModelIndex()):
        return 17

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return f"{section:X}" if section < 16 else "ASCII"
            return f"{section * 16:04X}"
        if role == Qt.ItemDataRole.FontRole:
            return self.font
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Vertical:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() < 16:
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not self.machine or not self.theme:
            return None
        mem = self.machine.cpu.mem
        row, col = index.row(), index.column()
        if col == 16:
            if role == Qt.ItemDataRole.DisplayRole:
                chunk = mem.data[row * 16:row * 16 + 16]
                return "".join(chr(b) if 32 <= b < 127 else "·" for b in chunk)
            if role == Qt.ItemDataRole.FontRole:
                return self.font
            if role == Qt.ItemDataRole.ForegroundRole:
                return QBrush(self.theme.c("text_dim"))
            return None
        addr = row * 16 + col
        v = mem.data[addr]
        t = self.theme
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return f"{v:02X}"
        if role == Qt.ItemDataRole.FontRole:
            return self.font
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            return QBrush(t.c("text") if v else t.c("text_dim"))
        if role == MARK_ROLE:
            return self.marks.get(addr, "")
        if role == Qt.ItemDataRole.BackgroundRole:
            cpu = self.machine.cpu
            mk = self.marks.get(addr)
            if mk:
                return QBrush(mix(t.c("base"), t.c("heat_write" if "W" in mk else "heat_read"), 0.8))
            if addr == cpu.pc:
                return QBrush(mix(t.c("base"), t.c("ok"), 0.55))
            if addr == cpu.sp:
                return QBrush(mix(t.c("base"), t.c("warning"), 0.55))
            if addr in mem.hot:
                age = cpu.icount - mem.last[addr]
                if age <= self.window:
                    key = "heat_read" if mem.kind[addr] == 1 else "heat_write"
                    return QBrush(mix(t.c("base"), t.c(key), 0.25 + 0.6 * (1 - age / self.window)))
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            sym = self.machine.symbol_for(addr)
            mk = self.marks.get(addr)
            used = {"R": "READ by the last step\n", "W": "WRITTEN by the last step\n",
                    "RW": "READ and WRITTEN by the last step\n"}.get(mk or "", "")
            return (used + f"{addr:04X}h" + (f"  ({sym})" if sym else "") + f"\n{v:02X}h = {v} = {v:08b}b\n"
                    f"reads {mem.rd[addr]}, writes {mem.wr[addr]}")
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not self.machine or index.column() >= 16:
            return False
        text = str(value).strip().lower().removesuffix("h").removeprefix("0x")
        try:
            v = int(text, 16)
        except ValueError:
            return False
        if not 0 <= v <= 255:
            return False
        self.machine.cpu.mem.data[index.row() * 16 + index.column()] = v
        self.dataChanged.emit(index, index)
        self.edited.emit()
        return True


class HexTable(QTableView):
    """The hex editor table. Its minimum height always leaves room for the column header, two rows and
    the horizontal scroll bar, so a squeezed Memory Map shows real bytes (or scrolls as a whole)
    instead of a header with no visible row."""

    def minimumSizeHint(self):
        m = super().minimumSizeHint()
        hh = self.horizontalHeader()
        h = ((0 if hh.isHidden() else hh.sizeHint().height())
             + 2 * self.verticalHeader().defaultSectionSize()
             + self.horizontalScrollBar().sizeHint().height() + 2 * self.frameWidth())
        return m.expandedTo(QSize(m.width(), h))


class MemoryPanel(QWidget):
    """Heatmap on top, hex editor below, with a go-to box and mode selector."""

    memory_edited = Signal()
    hover_text = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.machine = None
        self.heat = HeatmapWidget()
        self.model = HexModel(self)
        self.table = HexTable()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setMinimumSectionSize(20)
        self.table.verticalHeader().setDefaultSectionSize(21)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for c in range(16):
            self.table.setColumnWidth(c, 29)
        self.table.setColumnWidth(16, 136)
        self.table.setStyleSheet("QTableView::item { padding: 0px; }")
        self.table.setItemDelegate(MarkDelegate(self.table))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        self.goto = QLineEdit()
        self.goto.setPlaceholderText("Go to address (hex)")
        self.goto.setMaximumWidth(170)
        self.mode = QComboBox()
        for label, key in HeatmapWidget.MODES:
            self.mode.addItem(label, key)
        self.zoom = QComboBox()
        self.zoom.addItem("64 KB overview", False)
        self.zoom.addItem("4 KB zoom", True)
        self.zoom.setToolTip("Overview: each square is 16 bytes. Zoom: each square is one byte of a 4 KB page "
                             "(double-click the overview, or use Go to, to choose the page).")
        self.clear_btn = QPushButton("Clear heat")
        self.legend = QLabel()
        self.legend.setObjectName("Dim")
        self.legend.setWordWrap(True)
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.step_label = QLabel()
        self.step_label.setObjectName("Dim")
        self.step_label.setWordWrap(True)
        self.step_label.setVisible(False)
        self.step_label.setAccessibleName("Memory cells used by the last step")
        self.detail = QLabel("Click a square or a byte to see what it is.")
        self.detail.setObjectName("Card")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        self.detail.setMargin(0)
        self.stack_range = lambda: None  # set by the main window: -> (low, high) of the live stack or None

        top = QHBoxLayout()
        top.setContentsMargins(6, 6, 6, 4)
        top.addWidget(self.goto)
        top.addWidget(self.mode)
        top.addWidget(self.zoom)
        top.addWidget(self.clear_btn)
        top.addStretch(1)

        self.split = split = QSplitter(Qt.Orientation.Vertical)
        self.heat_box = heat_box = QWidget()
        hl = QVBoxLayout(heat_box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hl.addWidget(self.heat, 1)
        hl.addWidget(self.legend)
        split.addWidget(heat_box)
        split.addWidget(self.table)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([320, 220])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.step_label)
        lay.addWidget(split, 1)
        lay.addWidget(self.detail)
        self.table.selectionModel().currentChanged.connect(self._on_current)

        self.goto.returnPressed.connect(self._goto)
        self.mode.currentIndexChanged.connect(lambda: self.heat.set_mode(self.mode.currentData()))
        self.heat.address_clicked.connect(self.scroll_to)
        self.heat.zoom_requested.connect(self._zoom_to)
        self.zoom.currentIndexChanged.connect(lambda: self.heat.set_zoom(self.zoom.currentData()))
        self.heat.address_hovered.connect(lambda a: self.hover_text.emit(self.heat._describe(a).replace("\n", "   ")))
        self.model.edited.connect(self._edited)
        self.clear_btn.clicked.connect(self._clear_heat)

    def set_machine(self, machine):
        self.machine = machine
        self.model.machine = machine
        self.heat.set_machine(machine)
        self.model.layoutChanged.emit()

    def set_theme(self, theme: Theme):
        self.model.set_theme(theme)
        self.heat.set_theme(theme)
        sq = "&#9632;"
        c = theme.colors
        self.legend.setText(
            f" <span style='color:{c['heat_read']}'>{sq}</span> data read &nbsp; "
            f"<span style='color:{c['heat_write']}'>{sq}</span> data written &nbsp; "
            f"<span style='color:{c['heat_exec']}'>{sq}</span> code executed &nbsp; "
            f"<span style='color:{c['ok']}'>&#9645;</span> PC &nbsp; "
            f"<span style='color:{c['warning']}'>&#9645;</span> SP")
        self.legend.setToolTip(
            "Blue: a byte was READ as data (LDA, MOV A,M, POP, ...).\n"
            "Orange: a byte was WRITTEN (STA, MOV M,A, PUSH, ...).\n"
            "Green: an instruction at that address was EXECUTED. Fetching an opcode counts as 'executed', "
            "not as a read.\nGreen outline: program counter.  Yellow outline: stack pointer.\n"
            "Hover a square for details, click it to select, double-click to zoom into its 4 KB page.")

    def set_simple(self, simple: bool):
        """Beginner mode: only the hex table, without heatmap controls."""
        self.heat_box.setVisible(not simple)
        for w in (self.mode, self.zoom, self.clear_btn):
            w.setVisible(not simple)
        # Hiding widgets of a window that is not shown yet does not always refresh the splitter's cached
        # minimum size, which then still counts the hidden heatmap (about 300 px) and makes the main window
        # grow too tall on its first show.
        self.split.refresh()
        self.layout().invalidate()
        self.updateGeometry()

    def refresh(self):
        if not self.isVisible():
            return
        if self.heat_box.isVisible():
            self.heat.rebuild()
        self.table.viewport().update()
        if self._detail_addr is not None:
            self.detail.setText(self.describe_cell(self._detail_addr))

    def _zoom_to(self, addr: int):
        self.zoom.blockSignals(True)
        self.zoom.setCurrentIndex(1)
        self.zoom.blockSignals(False)
        self.heat.set_zoom(True, addr)
        self.scroll_to(addr)

    _detail_addr: int | None = None

    def _on_current(self, cur, _prev=None):
        if cur.isValid():
            addr = cur.row() * 16 + (cur.column() if cur.column() < 16 else 0)
            self._detail_addr = addr
            self.detail.setText(self.describe_cell(addr))

    def describe_cell(self, addr: int) -> str:
        m = self.machine
        if not m:
            return ""
        cpu, mem = m.cpu, m.cpu.mem
        v = mem.data[addr]
        sym = m.symbol_for(addr)
        ch = chr(v) if 32 <= v < 127 else "&middot;"
        head = (f"<b>{addr:04X}h</b>" + (f" ({sym})" if sym else "")
                + f" &nbsp; value <b>{v:02X}h</b> = {v} = {v:08b}b = '{ch}'")
        kind = "unused - no program byte or data was assigned here"
        region = m.program.region_at(addr) if m.program else None
        if region:
            if region.kind == "code":
                first = "first byte" if addr == region.start else "operand byte"
                kind = f"program code - {first} of the instruction on source line {region.line}"
            elif region.kind == "data":
                kind = f"data defined by DB/DW on source line {region.line}"
            else:
                kind = f"reserved storage (DS) on source line {region.line}"
        st = self.stack_range()
        if st and st[0] <= addr < st[1]:
            kind = "stack - " + (f"also {kind}" if region else "pushed data (the stack grows downward)")
        if addr == cpu.pc:
            kind += " | the program counter points here"
        if addr == cpu.sp:
            kind += " | the stack pointer points here"
        acc = "never read or written by the program"
        if mem.kind[addr]:
            age = cpu.icount - mem.last[addr]
            acc = f"last {'read' if mem.kind[addr] == 1 else 'written'} {age:,} instruction(s) ago"
        ex = f" | executed {cpu.exec_count[addr]:,} time(s)" if cpu.exec_count[addr] else ""
        return (f"{head}<br>Type: {kind}<br>reads {mem.rd[addr]:,} | writes {mem.wr[addr]:,} | {acc}{ex}")

    def scroll_to(self, addr: int):
        if self.heat.zoom and (addr & 0xF000) != (self.heat._base):
            self.heat.focus = addr
            self.heat.rebuild()
        idx = self.model.index(addr // 16, addr % 16)
        self.table.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.table.setCurrentIndex(idx)
        self.heat.selected = addr
        self.heat.update()

    def _goto(self):
        text = self.goto.text().strip().lower().removesuffix("h").removeprefix("0x")
        try:
            a = int(text, 16)
        except ValueError:
            self.goto.setStyleSheet("border-color: #e5484d")
            return
        self.goto.setStyleSheet("")
        self.scroll_to(a & 0xFFFF)

    def set_step_accesses(self, accesses):
        """Mark the cells the last step read or wrote (from the step recorder): a coloured cell with an R / W
        letter, a one-line summary above the table, and the first cell scrolled into view. ``()`` clears."""
        marks: dict[int, str] = {}
        for a in accesses:
            marks[a.addr] = "RW" if marks.get(a.addr, a.kind) != a.kind else a.kind
        changed = marks != self.model.marks
        self.model.marks = marks
        if not marks:
            self.step_label.setVisible(False)
            self.step_label.setText("")
        else:
            parts = []
            for a in accesses[:6]:
                parts.append(f"WRITE {a.addr:04X}h {a.old:02X}h -> {a.value:02X}h" if a.kind == "W" and a.old is not None
                             else f"{'WRITE' if a.kind == 'W' else 'READ'} {a.addr:04X}h = {a.value:02X}h")
            self.step_label.setText("Last step used: " + "; ".join(parts))
            self.step_label.setVisible(True)
            first = accesses[0].addr
            idx = self.model.index(first // 16, first % 16)
            if not self.table.viewport().rect().contains(self.table.visualRect(idx)):
                self.table.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        if changed:
            self.table.viewport().update()
            self.heat.update()

    def _edited(self):
        self.heat.rebuild()
        self.memory_edited.emit()

    def _clear_heat(self):
        if self.machine:
            self.machine.cpu.mem.clear_stats()
            self.machine.cpu.exec_count = [0] * 65536
            self.refresh()
