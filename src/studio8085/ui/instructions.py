"""The Instructions panel: a searchable list of the 8085 instruction set. One click on an instruction
asks the main window to put it in the editor; typing code by hand keeps working as before.

Each row shows the opcode (hex), the length in bytes and the T-states, and the line under the list
explains the instruction under the mouse (what it does, its opcode in binary, its machine code).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.catalog import CATEGORIES, SCOPE_ALL, SCOPE_ESSENTIAL, Entry, Form, describe, search
from .editor import monospace_font

ROLE_FORM = Qt.ItemDataRole.UserRole + 1
ROLE_ENTRY = Qt.ItemDataRole.UserRole + 2
AUTO_EXPAND_LIMIT = 40  # while searching, open every group if this few instructions are left

INTRO = ("Click an instruction to insert it into your program (Ctrl+Z undoes it). Typing instructions yourself "
         "works too. Hover over a row to see what it does and how it is encoded.")


class _Tree(QTreeWidget):
    activated_item = Signal(object)  # QTreeWidgetItem (Enter pressed)

    _after_double_click = False

    def sizeHint(self):
        # Small on purpose: the list scrolls, and a tall hint would make Qt grow the main window to fit it.
        return QSize(280, 120)

    def minimumSizeHint(self):
        return QSize(160, 70)

    def mouseDoubleClickEvent(self, e):
        # A quick second click belongs to the same gesture. Without this a double-click would insert the
        # instruction twice (or open and shut a group): Qt reports a click for both releases.
        self._after_double_click = True
        e.accept()

    def mousePressEvent(self, e):
        self._after_double_click = False
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._after_double_click:
            self._after_double_click = False
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentItem() is not None:
            self.activated_item.emit(self.currentItem())
            return
        super().keyPressEvent(e)


class InstructionPanel(QWidget):
    insert_requested = Signal(object)  # Form
    scope_changed = Signal(str)

    def sizeHint(self):
        return QSize(320, 260)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search: mov a,b   78h   carry   rotate")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setToolTip("Type part of an instruction (mov a), an opcode in hex (78h), or what it does (carry).\n"
                                    "Enter inserts the first result; Down moves into the list.")
        self.scope = QComboBox()
        self.scope.addItem("Essential instructions", SCOPE_ESSENTIAL)
        self.scope.addItem("All instructions", SCOPE_ALL)
        for c in CATEGORIES:
            self.scope.addItem(c, c)
        self.scope.setToolTip("Essential = the instructions used by the beginner examples.")

        self.tree = _Tree()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Instruction", "Opcode", "Bytes", "T"])
        head = self.tree.headerItem()
        head.setToolTip(1, "The opcode: the first byte of the instruction in memory, in hexadecimal")
        head.setToolTip(2, "How many bytes the instruction occupies (opcode plus operand bytes)")
        head.setToolTip(3, "T-states (clock cycles). 7/10 means 7 when a condition is false, 10 when it is true")
        self.tree.setFont(monospace_font(size=10))
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setExpandsOnDoubleClick(False)  # a click already opens a group
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setMouseTracking(True)
        hh = self.tree.header()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        self.detail = QLabel(INTRO)
        self.detail.setObjectName("Dim")
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.detail.setMinimumHeight(self.detail.fontMetrics().lineSpacing() * 4 + 6)

        top = QHBoxLayout()
        top.addWidget(self.search_edit, 1)
        top.addWidget(self.scope)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.detail)

        self.search_edit.textChanged.connect(self.populate)
        self.search_edit.returnPressed.connect(self._search_enter)
        self.search_edit.installEventFilter(self)
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemExpanded.connect(self._expanded)
        self.tree.activated_item.connect(self._clicked)
        self.tree.itemEntered.connect(lambda item, _c: self._show(item))
        self.tree.currentItemChanged.connect(lambda cur, _prev: self._show(cur))
        self.populate()

    # ------------------------------------------------------------ public
    def set_scope(self, scope: str):
        i = self.scope.findData(scope)
        self.scope.blockSignals(True)
        self.scope.setCurrentIndex(max(0, i))
        self.scope.blockSignals(False)
        self.populate()

    def current_scope(self) -> str:
        return self.scope.currentData()

    def focus_search(self):
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    # ------------------------------------------------------------ list
    def populate(self, *_):
        results = search(self.search_edit.text(), self.current_scope())
        shown = sum(len(forms) for _, forms in results)
        t = self.tree
        t.setUpdatesEnabled(False)
        t.clear()
        for entry, forms in results:
            if len(forms) == 1:  # a lone instruction is a row of its own, not a one-child group
                t.addTopLevelItem(self._form_item(entry, forms[0], label=forms[0].label))
                continue
            g = QTreeWidgetItem([entry.syntax, f"{len(forms)} opcodes", str(entry.length), entry.timing])
            g.setData(0, ROLE_ENTRY, entry)
            g.setToolTip(0, describe(entry))
            for c in (1, 2, 3):
                g.setTextAlignment(c, Qt.AlignmentFlag.AlignCenter)
            for f in forms:
                g.addChild(self._form_item(entry, f))
            t.addTopLevelItem(g)
        if self.search_edit.text().strip() and shown <= AUTO_EXPAND_LIMIT:
            t.expandAll()
        t.setUpdatesEnabled(True)
        if results:
            self.detail.setText(INTRO)
        else:
            self.detail.setText("No instruction matches. Try a mnemonic (mov), an opcode (3E), or a word like carry.")

    def _form_item(self, entry: Entry, f: Form, label: str | None = None) -> QTreeWidgetItem:
        it = QTreeWidgetItem([label or f.label, f.hex + "h", str(f.length), f.timing])
        it.setData(0, ROLE_FORM, f)
        it.setData(0, ROLE_ENTRY, entry)
        it.setToolTip(0, describe(entry, f))
        for c in (1, 2, 3):
            it.setTextAlignment(c, Qt.AlignmentFlag.AlignCenter)
        return it

    # ------------------------------------------------------------ actions
    def _clicked(self, item, _col=0):
        form = item.data(0, ROLE_FORM)
        if form is not None:
            self.insert_requested.emit(form)
        else:
            item.setExpanded(not item.isExpanded())

    def _expanded(self, item):
        """Browsing (no search text): opening a group closes the others and brings it to the top, so the
        small panel never ends up as one long scrolling list."""
        if self.search_edit.text().strip():
            return
        t = self.tree
        for i in range(t.topLevelItemCount()):
            other = t.topLevelItem(i)
            if other is not item and other.isExpanded():
                other.setExpanded(False)
        t.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtTop)

    def _show(self, item):
        if item is None:
            return
        entry, form = item.data(0, ROLE_ENTRY), item.data(0, ROLE_FORM)
        if entry is not None:
            self.detail.setText(describe(entry, form))

    def _scope_changed(self, _i):
        self.populate()
        self.scope_changed.emit(self.current_scope())

    def _search_enter(self):
        top = self.tree.topLevelItem(0)
        if top is None:
            return
        form = top.data(0, ROLE_FORM)
        if form is not None:
            self.insert_requested.emit(form)
        else:  # several opcodes: let the student choose
            top.setExpanded(True)
            self.tree.setFocus()
            self.tree.setCurrentItem(top.child(0))

    def eventFilter(self, obj, e):
        if obj is self.search_edit and e.type() == e.Type.KeyPress and e.key() == Qt.Key.Key_Down:
            if self.tree.topLevelItemCount():
                self.tree.setFocus()
                if self.tree.currentItem() is None:
                    self.tree.setCurrentItem(self.tree.topLevelItem(0))
                return True
        return super().eventFilter(obj, e)
