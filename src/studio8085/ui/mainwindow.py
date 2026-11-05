"""The main window: wires the editor, debugger and dock panels together."""

from __future__ import annotations

import time
from importlib import resources
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QMarginsF, QSize, Qt, QTimer
from PySide6.QtGui import (QAction, QActionGroup, QFont, QKeySequence, QPageLayout, QPageSize, QPdfWriter,
                           QShortcut, QTextDocument)
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QCheckBox, QComboBox, QDockWidget,
                               QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPushButton, QScrollArea, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, IDEA_AFFILIATION, IDEA_AUTHOR, __version__
from .. import APP_NAME as _APP
from ..core import diff as statediff
from ..core.assembler import AsmResult, assemble
from ..core.catalog import FORM_OF
from ..core.explain import flag_notes
from ..core.machine import Machine, Stop
from ..core.opcodes import TABLE
from ..core.peripherals import PeripheralConfigError, PortMap, TrainerKit
from ..core.trace import to_csv, to_html, to_markdown
from .docks import (ExplainPanel, FlagsPanel, InterruptPanel, IOPanel, ListingPanel, OutputPanel,
                    ProblemsPanel, RegistersPanel, StackPanel, SymbolsPanel, TracePanel, parse_hex)
from .editor import CodeEditor, monospace_font
from .fontscale import scale_monospace
from .help import ReferenceDialog
from .icons import app_icon, make_icon
from .instructions import InstructionPanel
from .memory import MemoryPanel
from .settings import Prefs, PreferencesDialog
from .themes import Theme, apply_theme, available_themes
from .trainer import TITLE as TRAINER_TITLE
from .trainer import PortMapDialog, TrainerPanel

SPEEDS = [("Max speed", 0), ("100,000 instr/s", 100_000), ("10,000 instr/s", 10_000),
          ("1,000 instr/s", 1_000), ("100 instr/s", 100), ("10 instr/s", 10), ("1 instr/s", 1)]
SOURCE_FILTER = "Assembly (*.asm *.s *.a85 *.8085);;All files (*)"


class FindBar(QFrame):
    def __init__(self, editor: CodeEditor):
        super().__init__()
        self.setObjectName("FindBar")
        self.editor = editor
        self.text = QLineEdit()
        self.text.setPlaceholderText("Find")
        self.case = QCheckBox("Aa")
        self.case.setToolTip("Match case")
        prev, nxt, close = QToolButton(), QToolButton(), QToolButton()
        prev.setText("▲")
        nxt.setText("▼")
        close.setText("✕")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        for w in (self.text, self.case, prev, nxt, close):
            lay.addWidget(w)
        self.text.textChanged.connect(self._changed)
        self.text.returnPressed.connect(lambda: self.find(False))
        prev.clicked.connect(lambda: self.find(True))
        nxt.clicked.connect(lambda: self.find(False))
        close.clicked.connect(self.close_bar)
        self.case.toggled.connect(self._changed)
        self.hide()

    def open(self):
        self.show()
        sel = self.editor.textCursor().selectedText()
        if sel and " " not in sel:
            self.text.setText(sel)
        self.text.setFocus()
        self.text.selectAll()
        self._changed()

    def close_bar(self):
        self.hide()
        self.editor.highlight_matches("")
        self.editor.setFocus()

    def find(self, backwards: bool):
        self.editor.find_text(self.text.text(), backwards, self.case.isChecked())

    def _changed(self, *_):
        self.editor.highlight_matches(self.text.text(), self.case.isChecked())


class DockScroll(QScrollArea):
    """Holds a dock panel so the dock can be made smaller than the panel's minimum size.

    Several panels have a rigid minimum (the heatmap, the flag buttons, the interrupt pins...). Inside a
    dock, those minimums add up and forced the main window to about 820 x 900 px in Advanced mode, more
    than a 1280 x 720 or 1366 x 768 screen offers. In this scroll area the panel still fills the dock and
    looks exactly as before whenever the dock is at least as big as the panel's minimum; only when the
    window is smaller do scroll bars appear instead of the window growing past the screen.
    """

    def __init__(self, panel: QWidget):
        super().__init__()
        self.setObjectName("DockScroll")
        # Not widgetResizable: for a panel with word-wrapped labels (height-for-width) QScrollArea would
        # keep it at its *preferred* height and scroll, instead of letting its tables shrink first.
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keyboard focus and tab order stay on the panel
        self.setAutoFillBackground(False)
        self.viewport().setAutoFillBackground(False)
        self.setWidget(panel)
        panel.installEventFilter(self)

    def _panel_minimum(self) -> QSize:
        p = self.widget()
        return p.minimumSize().expandedTo(p.minimumSizeHint())

    def _fit_panel(self):
        """The panel fills the viewport, but never gets smaller than its minimum (then it scrolls)."""
        p = self.widget()
        if p is None:
            return
        size = self.viewport().size().expandedTo(self._panel_minimum())
        if p.size() != size:
            p.resize(size)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_panel()

    def eventFilter(self, obj, e):
        if obj is self.widget() and e.type() == QEvent.Type.LayoutRequest:  # minimum may have changed
            QTimer.singleShot(0, self._fit_panel)
        return super().eventFilter(obj, e)

    def sizeHint(self):  # lay the docks out at the panel's natural size, as without the scroll area
        return self.widget().sizeHint() if self.widget() is not None else super().sizeHint()


class MainWindow(QMainWindow):
    def __init__(self, prefs: Prefs | None = None):
        super().__init__()
        self.prefs = prefs or Prefs()
        self.themes = available_themes()
        self.theme: Theme = self.themes.get(self.prefs.get("theme"), self.themes["Dark"])
        self.machine = Machine(self.prefs.get("ac_borrow"))
        self.path: Path | None = None
        self.state = "idle"  # idle | ready | running | paused | halted
        self.live: AsmResult | None = None
        self.loaded_text: str | None = None
        self.loaded_origin: int | None = None  # the "Store code at" address the loaded program was built for
        self._mode = "run"
        self._temp_bp: int | None = None
        self._out_seen = 0
        self._credit = 0.0
        self._budget = 2000
        self._last_tick = self._last_ui = 0.0
        self._icon_specs: list[tuple[QAction, str, str]] = []
        self._layout_restored = False
        self._before = None
        self._before_ins = None
        self._base_font = QApplication.font()
        self._hidden_for_focus: list[str] | None = None
        self.mode = "beginner"
        self._lab_active = False  # a Lab menu program or Experiment 1 is in use: Beginner mode keeps the kit visible
        self._loading_lab = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)
        self.setDockNestingEnabled(True)

        self._build_panels()
        self._build_central()
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        self._apply_prefs()
        self._apply_theme(self.theme.name, save=False)
        self._restore_layout()
        self._set_mode(self.prefs.get("mode"), save=False, first=True)
        self.editor.font_size_changed.connect(lambda n: self.prefs.set("font_size", n))
        self.editor.content_changed.connect(self._live_check)
        self.editor.breakpoints_changed.connect(self._sync_breakpoints)
        self.editor.document().modificationChanged.connect(self.setWindowModified)
        self.editor.caret_moved.connect(lambda l, c: self.pos_label.setText(f"Ln {l}, Col {c}"))
        self.editor.caret_moved.connect(lambda l, c: self._update_code_label())
        self._load_example("beginner/01_first_program.asm" if self.prefs.get("mode") == "beginner"
                           else "02_sum_array.asm")

    # ============================================================== build
    def _build_panels(self):
        self.editor = CodeEditor()
        self.registers = RegistersPanel()
        self.flags = FlagsPanel()
        self.stack = StackPanel()
        self.io = IOPanel()
        self.memory = MemoryPanel()
        self.problems = ProblemsPanel()
        self.listing = ListingPanel()
        self.symbols = SymbolsPanel()
        self.interrupts = InterruptPanel()
        self.output = OutputPanel()
        self.explain = ExplainPanel()
        self.instructions = InstructionPanel()
        self.trace = TracePanel()
        self.kit = self._make_kit()
        self.trainer = TrainerPanel(self.kit)
        self.trainer.set_machine(self.machine)
        self.trainer.changed.connect(self._trainer_changed)
        self.trainer.enabled_changed.connect(self._trainer_enabled)
        self.trainer.mode_changed.connect(lambda m: self.prefs.set("trainer_seg_mode", m))
        self.trainer.ports_requested.connect(self.trainer_ports)
        self.trainer.reset_requested.connect(self.trainer_reset)
        self.trainer.guide.ended.connect(self._end_lab)
        self.trainer.guide.load_requested.connect(self.start_experiment_program)
        self.trainer.concealed_changed.connect(self._apply_conceal)
        self.io.model.dataChanged.connect(self._io_edited)
        for p in (self.registers, self.flags, self.stack, self.io, self.memory, self.symbols, self.interrupts,
                  self.explain):
            p.set_machine(self.machine)
        self.trace.machine = self.machine
        self.explain.set_predict_first(self.prefs.get("predict_first"))
        self.explain.predict_changed.connect(lambda on: self.prefs.set("predict_first", on))
        self.registers.edited.connect(self._after_manual_edit)
        self.flags.edited.connect(self._after_manual_edit)
        self.memory.memory_edited.connect(self._after_manual_edit)
        self.memory.stack_range = lambda: ((self.machine.cpu.sp, self.stack.base)
                                           if self.stack.base > self.machine.cpu.sp else None)
        self.problems.goto.connect(self.editor.goto)
        self.problems.counts.connect(self._problem_counts)
        self.listing.goto.connect(lambda l: self.editor.goto(l))
        self.symbols.goto.connect(lambda l: self.editor.goto(l))
        self.interrupts.raised.connect(self._raise_irq)
        self.trace.record_toggled.connect(self._set_trace)
        self.trace.export_requested.connect(self.export_trace)
        self.trace.clear_requested.connect(self.clear_trace)
        self.instructions.set_scope(self.prefs.get("palette_scope"))
        self.instructions.insert_requested.connect(self._insert_instruction)
        self.instructions.scope_changed.connect(lambda s: self.prefs.set("palette_scope", s))

    def _build_central(self):
        self.findbar = FindBar(self.editor)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.editor, 1)
        lay.addWidget(self.findbar)
        self.setCentralWidget(w)

    def _build_docks(self):
        self.docks: dict[str, QDockWidget] = {}
        spec = [("registers", "Registers", self.registers), ("flags", "Flags / Status", self.flags),
                ("interrupts", "Interrupts", self.interrupts), ("memory", "Memory Map", self.memory),
                ("stack", "Stack", self.stack), ("io", "I/O Ports", self.io),
                ("symbols", "Symbols", self.symbols), ("problems", "Problems", self.problems),
                ("listing", "Listing", self.listing), ("output", "Output", self.output),
                ("explain", "Explain", self.explain), ("instructions", "Instructions", self.instructions),
                ("trace", "Trace", self.trace), ("trainer", TRAINER_TITLE, self.trainer)]
        for key, title, widget in spec:
            d = QDockWidget(title, self)
            d.setObjectName(key)
            # panels that scroll by themselves (tables) go in directly; the others get a scroll area
            d.setWidget(widget if isinstance(widget, QAbstractScrollArea) else DockScroll(widget))
            d.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                          | QDockWidget.DockWidgetFeature.DockWidgetClosable)
            self.docks[key] = d
            d.visibilityChanged.connect(lambda vis, w=widget: vis and self._refresh_widget(w))
        self.registers.setMinimumWidth(250)
        self.memory.setMinimumWidth(470)
        self._default_layout()

    def _tab(self, first: QDockWidget, second: QDockWidget):
        """Tabify two docks reliably. Qt silently ignores ``tabifyDockWidget`` for a dock that has not been
        shown yet; the layout then keeps them stacked, and the window grows to fit the taller stack."""
        first.show()
        second.show()
        self.tabifyDockWidget(first, second)

    def _reset_docks(self):
        for d in self.docks.values():
            d.setFloating(False)
            self.removeDockWidget(d)

    def _default_layout(self):
        """Advanced mode: every panel."""
        L, R, B = (Qt.DockWidgetArea.LeftDockWidgetArea, Qt.DockWidgetArea.RightDockWidgetArea,
                   Qt.DockWidgetArea.BottomDockWidgetArea)
        self._reset_docks()
        D = self.docks
        for k in ("registers", "flags", "explain", "interrupts", "instructions"):
            self.addDockWidget(L, D[k])
        self.splitDockWidget(D["registers"], D["flags"], Qt.Orientation.Vertical)
        self.tabifyDockWidget(D["flags"], D["explain"])
        self.tabifyDockWidget(D["explain"], D["interrupts"])
        self.tabifyDockWidget(D["interrupts"], D["instructions"])  # plain tabify keeps Flags / Status in front
        for k in ("memory", "stack", "io", "symbols"):
            self.addDockWidget(R, D[k])
        self.splitDockWidget(D["memory"], D["stack"], Qt.Orientation.Vertical)
        self.tabifyDockWidget(D["stack"], D["io"])
        self.tabifyDockWidget(D["io"], D["symbols"])
        self.addDockWidget(R, D["trainer"])
        self.tabifyDockWidget(D["symbols"], D["trainer"])  # Phase 1: a tab next to I/O Ports; Stack stays in front
        for k in ("problems", "listing", "output", "trace"):
            self.addDockWidget(B, D[k])
        self.tabifyDockWidget(D["problems"], D["listing"])
        self.tabifyDockWidget(D["listing"], D["output"])
        self.tabifyDockWidget(D["output"], D["trace"])
        for d in D.values():
            d.show()
        D["flags"].raise_()
        D["stack"].raise_()
        D["problems"].raise_()
        QTimer.singleShot(0, self._apply_default_sizes)

    BEGINNER_DOCKS = ("registers", "flags", "explain", "instructions", "memory", "problems", "output")

    def _enforce_beginner_docks(self):
        """Beginner mode shows exactly the Beginner panels (plus the Trainer Kit while a lab is active), whatever
        layout was restored. Qt's ``restoreState`` does not hide the docks that the default layout had shown, so
        a session saved in Beginner mode used to come back with every panel."""
        keep = set(self.BEGINNER_DOCKS) | ({"trainer"} if self._lab_active else set())
        for k, d in self.docks.items():
            d.setVisible(k in keep)

    def _beginner_layout(self):
        """Beginner mode: editor, registers, flags, memory, explanation, problems and output."""
        L, R, B = (Qt.DockWidgetArea.LeftDockWidgetArea, Qt.DockWidgetArea.RightDockWidgetArea,
                   Qt.DockWidgetArea.BottomDockWidgetArea)
        self._reset_docks()
        D = self.docks
        self.addDockWidget(L, D["registers"])
        self.addDockWidget(L, D["flags"])
        self.splitDockWidget(D["registers"], D["flags"], Qt.Orientation.Vertical)
        self.addDockWidget(R, D["explain"])
        self.addDockWidget(R, D["memory"])
        self.splitDockWidget(D["explain"], D["memory"], Qt.Orientation.Vertical)
        self.addDockWidget(R, D["instructions"])
        self._tab(D["explain"], D["instructions"])  # the "write" and "run" guides share one pane
        self.addDockWidget(R, D["trainer"])
        self._tab(D["instructions"], D["trainer"])  # hidden below; View or Lab menu brings it back as a tab here
        self.addDockWidget(B, D["problems"])
        self.addDockWidget(B, D["output"])
        self.tabifyDockWidget(D["problems"], D["output"])
        keep = set(self.BEGINNER_DOCKS) | ({"trainer"} if self._lab_active else set())
        for k, d in D.items():
            d.setVisible(k in keep)
        (D["trainer"] if self._lab_active else D["explain"]).raise_()
        D["problems"].raise_()
        QTimer.singleShot(0, self._apply_beginner_sizes)
        if self._lab_active:
            QTimer.singleShot(0, self._size_trainer_dock)

    def _side_scale(self, widths: list[int]) -> float:
        """<= 1: shrink the side columns on a narrow window so the editor keeps about 35 % of the width."""
        return max(0.3, min(1.0, 0.65 * self.width() / sum(widths)))

    def _resize_docks(self, docks: list[QDockWidget], sizes: list[int], orientation: Qt.Orientation,
                      floor: bool = True):
        """``resizeDocks`` that asks for at least each panel's natural minimum when there is room.

        Panels in a ``DockScroll`` no longer force the window to grow, so a plain resizeDocks could give
        them less than they need and show scroll bars even on a screen where everything fits (the hex
        table lost its last column and the detail line). Asking for the natural minimum keeps the old
        look whenever the window is big enough; Qt still shrinks the docks to fit a small window.
        """
        out = []
        for d, size in zip(docks, sizes):
            holder = d.widget()
            if floor and isinstance(holder, DockScroll) and holder.widget() is not None:
                need = holder._panel_minimum()
                if orientation == Qt.Orientation.Vertical:
                    chrome = max(0, d.height() - holder.height()) or 30
                    size = max(size, need.height() + chrome)
                else:
                    chrome = max(0, d.width() - holder.width())
                    size = max(size, need.width() + chrome)
            out.append(size)
        self.resizeDocks(docks, out, orientation)

    def _apply_beginner_sizes(self):
        if self.mode != "beginner":
            return
        D = self.docks
        H, V = Qt.Orientation.Horizontal, Qt.Orientation.Vertical
        # The sizes below are designed for a window about 900 px tall. On a shorter window (a 768 px laptop)
        # scale them down; asking for more than fits would make Qt grow the window past the screen.
        k = max(0.6, min(1.0, (self.height() - 290) / 660))
        kx = self._side_scale([290, 520])
        self._resize_docks([D["registers"], D["explain"]], [round(290 * kx), round(520 * kx)], H, floor=kx >= 1)
        self._resize_docks([D["registers"], D["flags"]], [round(372 * k), round(200 * k)], V)
        self._resize_docks([D["explain"], D["memory"]], [round(400 * k), round(260 * k)], V)
        self._resize_docks([D["problems"]], [round(130 * min(1.0, k + 0.2))], V)

    def _compact_layout(self):
        """One tabbed column on the right and a short strip at the bottom (small screens)."""
        R, B = Qt.DockWidgetArea.RightDockWidgetArea, Qt.DockWidgetArea.BottomDockWidgetArea
        self._reset_docks()
        D = self.docks
        order = ["registers", "flags", "explain", "instructions", "memory", "stack", "io", "symbols", "interrupts",
                 "trainer"]
        for k in order:
            self.addDockWidget(R, D[k])
        for a, b in zip(order, order[1:]):
            self.tabifyDockWidget(D[a], D[b])
        for k in ("problems", "listing", "output", "trace"):
            self.addDockWidget(B, D[k])
        for a, b in (("problems", "listing"), ("listing", "output"), ("output", "trace")):
            self.tabifyDockWidget(D[a], D[b])
        for d in D.values():
            d.show()
        D["registers"].raise_()
        D["problems"].raise_()
        QTimer.singleShot(0, lambda: self.resizeDocks([D["problems"]], [110], Qt.Orientation.Vertical))

    def _reset_layout(self):
        self._layout_restored = False
        if self.mode == "beginner":
            self._beginner_layout()
        else:
            self._default_layout()
            QTimer.singleShot(0, lambda: self._apply_default_sizes(force=True))

    def _apply_default_sizes(self, force: bool = False):
        if self.mode != "advanced" or (self._layout_restored and not force):
            return
        D = self.docks
        H, V = Qt.Orientation.Horizontal, Qt.Orientation.Vertical
        # Designed for a window about 950 px tall; scale the heights down on shorter windows (720/768 px
        # screens) so the editor keeps its share instead of the bottom panels taking it.
        k = max(0.5, min(1.0, (self.height() - 290) / 660))
        kx = self._side_scale([290, 600])
        self._resize_docks([D["registers"], D["memory"]], [round(290 * kx), round(600 * kx)], H, floor=kx >= 1)
        self._resize_docks([D["registers"], D["flags"]], [round(352 * k), round(308 * k)], V)
        self._resize_docks([D["memory"], D["stack"]], [round(480 * k), round(200 * k)], V)
        self._resize_docks([D["problems"]], [round(200 * k)], V)

    def _act(self, text, slot, shortcut=None, icon=None, color="text", tip=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if tip:
            a.setToolTip(f"{tip}  ({a.shortcut().toString()})" if shortcut else tip)
            a.setStatusTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        if icon:
            self._icon_specs.append((a, icon, color))
        return a

    def _build_actions(self):
        A = self._act
        K = QKeySequence.StandardKey
        self.a_new = A("&New", self.new_file, K.New, "new", tip="New file")
        self.a_open = A("&Open...", lambda: self.open_dialog(), K.Open, "open", tip="Open a file")
        self.a_save = A("&Save", lambda: self.save(), K.Save, "save", tip="Save")
        self.a_saveas = A("Save &As...", lambda: self.save_as(), "Ctrl+Shift+S")
        self.a_prefs = A("&Preferences...", self.preferences, "Ctrl+,")
        self.a_quit = A("&Quit", self.close, "Ctrl+Q")
        self.a_undo = A("&Undo", lambda: self.editor.undo(), K.Undo)
        self.a_redo = A("&Redo", lambda: self.editor.redo(), K.Redo)
        self.a_cut = A("Cu&t", lambda: self.editor.cut(), K.Cut)
        self.a_copy = A("&Copy", lambda: self.editor.copy(), K.Copy)
        self.a_paste = A("&Paste", lambda: self.editor.paste(), K.Paste)
        self.a_selall = A("Select &All", lambda: self.editor.selectAll(), K.SelectAll)
        self.a_find = A("&Find...", self.findbar.open, K.Find, "find", tip="Find in the source")
        self.a_findnext = A("Find &Next", lambda: self.findbar.find(False), "F3")
        self.a_findprev = A("Find &Previous", lambda: self.findbar.find(True), "Shift+F3")
        self.a_goto = A("&Go to Line...", self.goto_line, "Ctrl+G")
        self.a_comment = A("Toggle &Comment", lambda: self.editor.toggle_comment(), "Ctrl+/")
        self.a_instr = A("&Instructions", self.show_instructions, "Ctrl+I", "instructions", "text",
                         "Instruction list: click one to insert it (opcodes shown)")
        self.a_zoom_in = A("Zoom &In", lambda: self.editor.zoom(1), "Ctrl+=")
        self.a_zoom_out = A("Zoom &Out", lambda: self.editor.zoom(-1), "Ctrl+-")

        self.a_assemble = A("&Assemble", self.cmd_assemble, "F7", "assemble", "text", "Assemble and load the program")
        self.a_run = A("&Run / Continue", self.cmd_run, "F5", "run", "ok", "Run (or continue) the program")
        self.a_pause = A("&Pause", self.cmd_pause, "F6", "pause", "warning", "Pause execution")
        self.a_stop = A("&Stop", self.cmd_stop, "Shift+F5", "stop", "error", "Stop and return to editing")
        self.a_restart = A("Re&start", self.cmd_restart, "Ctrl+Shift+F5", "restart", "text", "Reassemble and restart at the first instruction")
        self.a_into = A("Step &Into", lambda: self.cmd_step("into"), "F11", "step_in", "info", "Execute one instruction")
        self.a_over = A("Step &Over", lambda: self.cmd_step("over"), "F10", "step_over", "info", "Execute one instruction, running whole CALL/RST routines")
        self.a_out = A("Step Ou&t", lambda: self.cmd_step("out"), "Shift+F11", "step_out", "info", "Run until the current routine returns")
        self.a_cursor = A("Run to &Cursor", self.cmd_run_to_cursor, "Ctrl+F10", "run_cursor", "info", "Run until the line with the cursor")
        self.a_bp = A("Toggle &Breakpoint", lambda: self.editor.toggle_breakpoint(), "F9", "breakpoint", "bp", "Toggle a breakpoint on the current line")
        self.a_clearbp = A("&Remove All Breakpoints", lambda: self.editor.clear_breakpoints(), None, "clear_bp", "text", "Remove all breakpoints")
        self.a_clearmem = A("Clear &Memory and Heat", self.cmd_clear_memory)
        self.a_theme = A("Toggle &Dark/Light Theme", self.toggle_theme, "Ctrl+T", "theme", "text", "Switch between dark and light theme")
        self.a_ref = A("8085 &Reference", lambda: self.show_reference(0), "F1", "help", "text", "Instruction set reference")
        self.a_syntax = A("Assembler &Syntax", lambda: self.show_reference(1))
        self.a_about = A("&About", self.about)
        self.a_layout = A("&Reset Window Layout", self._reset_layout)
        self.a_compact = A("&Compact Layout (small screens)", self._compact_layout)
        self.a_focus = A("&Focus Editor (hide all panels)", self.toggle_focus_mode, "F12", checkable=True,
                         tip="Hide every panel to give the editor the whole window")
        self.a_goto_editor = A("Go to &Editor", lambda: self.editor.setFocus(), "Ctrl+E")
        self.a_trace = A("Record Execution &Trace", lambda: self._set_trace(self.a_trace.isChecked()),
                         checkable=True, tip="Keep one row per executed instruction for the Trace panel and export")
        self.a_trace_export = A("E&xport Trace...", self.export_trace, tip="Save the trace as CSV, Markdown, HTML or PDF")
        self.a_trace_clear = A("Clear Tra&ce", self.clear_trace)
        self.mode_group = QActionGroup(self)
        self.a_mode = {}
        for key, text in (("beginner", "&Beginner (simple layout)"), ("advanced", "&Advanced (all panels)")):
            a = QAction(text, self, checkable=True)
            a.triggered.connect(lambda _=False, k=key: self._set_mode(k))
            self.mode_group.addAction(a)
            self.a_mode[key] = a
        self.compat_group = QActionGroup(self)
        self.a_compat = {}
        for key, text in (("off", "Studio8085 syntax (no checks)"), ("note", "Note where GNUSim8085 would differ"),
                          ("strict", "GNUSim8085-compatible (differences are errors)")):
            a = QAction(text, self, checkable=True)
            a.triggered.connect(lambda _=False, k=key: self._set_compat(k))
            self.compat_group.addAction(a)
            self.a_compat[key] = a
        for act, short in ((self.a_new, "New"), (self.a_open, "Open"), (self.a_save, "Save"),
                           (self.a_assemble, "Assemble"), (self.a_run, "Run"), (self.a_pause, "Pause"),
                           (self.a_stop, "Stop"), (self.a_restart, "Restart"), (self.a_into, "Step"),
                           (self.a_over, "Over"), (self.a_out, "Out"), (self.a_cursor, "To cursor"),
                           (self.a_bp, "Breakpoint"), (self.a_clearbp, "Clear all"), (self.a_find, "Find"),
                           (self.a_theme, "Theme"), (self.a_ref, "Help")):
            act.setIconText(short)
        self.a_theme.setText("Switch &Theme")
        self.a_theme.setToolTip("Switch theme (Ctrl+T): Dark, Light, High Contrast")

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.a_new, self.a_open):
            m.addAction(a)
        self.recent_menu = m.addMenu("Open &Recent")
        self.examples_menu = m.addMenu("&Examples")
        m.addSeparator()
        for a in (self.a_save, self.a_saveas):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_prefs)
        m.addAction(self.a_quit)
        self._fill_examples()
        self._fill_recent()

        m = mb.addMenu("&Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_cut, self.a_copy, self.a_paste, self.a_selall, None,
                  self.a_find, self.a_findnext, self.a_findprev, self.a_goto, self.a_comment, None, self.a_instr):
            m.addSeparator() if a is None else m.addAction(a)

        m = mb.addMenu("&Debug")
        for a in (self.a_assemble, self.a_run, self.a_pause, self.a_stop, self.a_restart, None, self.a_into,
                  self.a_over, self.a_out, self.a_cursor, None, self.a_bp, self.a_clearbp, None, self.a_clearmem, None, self.a_trace, self.a_trace_export, self.a_trace_clear):
            m.addSeparator() if a is None else m.addAction(a)
        m.addSeparator()
        self.compat_menu = m.addMenu("Assembler s&yntax")
        for a in self.a_compat.values():
            self.compat_menu.addAction(a)

        m = mb.addMenu("&View")
        for key in ("registers", "flags", "explain", "instructions", "interrupts", "memory", "stack", "io", "symbols", "problems", "listing", "output", "trace", "trainer"):
            m.addAction(self.docks[key].toggleViewAction())
        m.addSeparator()
        self.theme_menu = m.addMenu("&Theme")
        self.theme_group = QActionGroup(self)
        for name in self.themes:
            a = QAction(name, self, checkable=True)
            a.setChecked(name == self.theme.name)
            a.triggered.connect(lambda _=False, n=name: self._apply_theme(n))
            self.theme_group.addAction(a)
            self.theme_menu.addAction(a)
        m.addAction(self.a_theme)
        m.addSeparator()
        m.addAction(self.a_zoom_in)
        m.addAction(self.a_zoom_out)
        m.addSeparator()
        self.mode_menu = m.addMenu("Interface &mode")
        for a in self.a_mode.values():
            self.mode_menu.addAction(a)
        m.addAction(self.a_focus)
        m.addAction(self.a_compact)
        m.addAction(self.a_goto_editor)
        m.addAction(self.a_layout)

        m = mb.addMenu("&Lab")
        self.lab_menu = m
        self.a_trainer_show = m.addAction("Show the &Virtual 8085 Trainer Kit", self.show_trainer)
        self.a_experiment1 = m.addAction("&Experiment 1: Read Switches and Control LEDs", self.start_experiment)
        m.addSeparator()
        for name, label in self.TRAINER_EXAMPLES:
            m.addAction(label, lambda n=name: self._open_trainer_example(n))
        m.addSeparator()
        m.addAction("Trainer Kit &Port Mapping...", self.trainer_ports)
        m.addAction("&Reset Trainer Hardware", self.trainer_reset)

        m = mb.addMenu("&Help")
        m.addAction(self.a_ref)
        m.addAction(self.a_syntax)
        m.addSeparator()
        m.addAction(self.a_about)
        QShortcut(QKeySequence("Escape"), self.findbar, activated=self.findbar.close_bar)

    def _build_toolbar(self):
        def make(name):
            tb = QToolBar(name)
            tb.setObjectName("tb_" + name.lower())
            tb.setMovable(False)
            tb.setIconSize(QSize(22, 22))
            self.addToolBar(tb)
            return tb

        self._advanced_actions: list[QAction] = []
        self.tb_file = make("File")
        for a in (self.a_new, self.a_open, self.a_save):
            self.tb_file.addAction(a)
        self.tb_run = make("Run")
        for a in (self.a_assemble, self.a_run, self.a_pause, self.a_stop, self.a_restart):
            self.tb_run.addAction(a)
        self.tb_run.addSeparator()
        for a in (self.a_into, self.a_over, self.a_out):
            self.tb_run.addAction(a)
        self.tb_extra = tb = make("Tools")
        self.toolbar = self.tb_run

        def adv(widget_or_action):
            act = widget_or_action if isinstance(widget_or_action, QAction) else tb.addWidget(widget_or_action)
            self._advanced_actions.append(act)
            return act

        lbl = QLabel(" Store code at ")  # shown in both modes: where in memory the program is saved
        lbl.setObjectName("Dim")
        tb.addWidget(lbl)
        self.origin_edit = QLineEdit()
        self.origin_edit.setFixedWidth(64)
        self.origin_edit.setMaxLength(5)
        self.origin_edit.setToolTip("Memory address (hex) where the program's first byte is stored; execution starts there.\n"
                                    "An ORG line in the source overrides it. Press Enter, then Assemble or Run.")
        self.origin_edit.editingFinished.connect(self._origin_changed)
        tb.addWidget(self.origin_edit)
        tb.addAction(self.a_bp)
        for a in (self.a_cursor, self.a_clearbp):
            tb.addAction(a)
            self._advanced_actions.append(a)
        tb.addSeparator()
        lbl = QLabel(" Speed ")
        lbl.setObjectName("Dim")
        self._compact_labels = [(adv(lbl), lbl, True)]  # (action, label, advanced only)
        self.speed = QComboBox()
        self.speed.setAccessibleName("Speed")
        for label, rate in SPEEDS:
            self.speed.addItem(label, rate)
        self.speed.setCurrentIndex(self.prefs.get("speed"))
        self.speed.setToolTip("How fast Run executes. Slow speeds let you watch registers and the heatmap change.")
        self.speed.currentIndexChanged.connect(lambda i: self.prefs.set("speed", i))
        adv(self.speed)
        tb.addSeparator()
        for a in (self.a_instr, self.a_find, self.a_theme, self.a_ref):
            tb.addAction(a)
        lbl = QLabel(" Mode ")
        lbl.setObjectName("Dim")
        self._compact_labels.append((tb.addWidget(lbl), lbl, False))
        self.mode_combo = QComboBox()
        self.mode_combo.setAccessibleName("Mode")
        self.mode_combo.addItem("Beginner", "beginner")
        self.mode_combo.addItem("Advanced", "advanced")
        self.mode_combo.setToolTip("Beginner shows only what you need to learn; Advanced shows every panel.")
        self.mode_combo.currentIndexChanged.connect(lambda i: self._set_mode(self.mode_combo.itemData(i)))
        tb.addWidget(self.mode_combo)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.msg = QLabel("")
        self.pos_label = QLabel("Ln 1, Col 1")
        self.pc_label = QLabel("PC 0000h")
        self.pc_label.setFont(monospace_font(size=10))
        self.code_label = QLabel("")
        self.code_label.setFont(monospace_font(size=10))
        self.code_label.setToolTip("The machine code of the instruction on the cursor line: its opcode first, then its operand bytes")
        sb.addWidget(self.msg, 1)
        sb.addPermanentWidget(self.code_label)
        sb.addPermanentWidget(self.pc_label)
        sb.addPermanentWidget(self.pos_label)

    # ============================================================== theme
    def _apply_theme(self, name: str, save: bool = True):
        self.theme = self.themes.get(name, self.themes["Dark"])
        font = QApplication.font()
        apply_theme(QApplication.instance(), self.theme, font)
        t = self.theme
        self.editor.set_theme(t, self.prefs.syntax_overrides(t.dark))
        for p in (self.memory, self.registers, self.stack, self.io, self.problems, self.listing, self.trainer):
            p.set_theme(t)
        self._refresh_icons()
        for a in self.theme_group.actions():
            a.setChecked(a.text() == t.name)
        if save:
            self.prefs.set("theme", t.name)
        self._apply_fonts()  # setStyleSheet resets widget fonts in Qt, so set them again
        self.refresh_all()

    def _refresh_icons(self):
        t = self.theme
        for action, name, key in self._icon_specs:
            action.setIcon(make_icon(name, t.colors[key], t.colors["text_dim"]))

    def toggle_theme(self):
        names = list(self.themes)
        self._apply_theme(names[(names.index(self.theme.name) + 1) % len(names)])

    def _apply_prefs(self):
        p = self.prefs
        self.editor.apply_font(p.get("font_family"), p.get("font_size"))
        self.editor.set_tab_width(p.get("tab_width"))
        self.origin_edit.setText(f"{p.get('origin'):04X}")
        self.machine.max_instructions = p.get("max_instr")
        self.machine.stop_on_idle_loop = p.get("stop_idle")
        self.machine.cpu.ac_borrow_style = p.get("ac_borrow")
        self.a_restart.setToolTip(
            "Restart (Ctrl+Shift+F5): re-assemble the source and reload it. "
            + ("Memory is kept (Preferences > Simulation); " if p.get("keep_memory") else "Memory is cleared; ")
            + "the registers, flags, PC, SP, interrupt state and statistics are reset. I/O port values you entered are kept.")
        self.flags.set_clock(p.get("clock_mhz"))
        self.compat = p.get("compat")
        for k, a in self.a_compat.items():
            a.setChecked(k == self.compat)
        f = QFont(self._base_font)
        if p.get("ui_font_size"):
            f.setPointSize(p.get("ui_font_size"))
        QApplication.setFont(f)
        self._apply_fonts()

    def _panel_font_delta(self) -> int:
        ui = self.prefs.get("ui_font_size")
        return (ui - self._base_font.pointSize()) if ui else 0

    def _rescale(self, *widgets):
        """Scale panels that just created new table items (listing, symbols, trace, explain)."""
        delta = self._panel_font_delta()
        if delta:
            for w in widgets:
                scale_monospace(w, delta, False)

    def _apply_fonts(self, geometry: bool = True):
        """Editor font + the monospace dock panels (they follow the interface font size)."""
        self.editor.reapply_font()
        delta = self._panel_font_delta()
        for d in self.docks.values():
            if d.widget() is not None:
                scale_monospace(d.widget(), delta, geometry)
        self.pc_label.setFont(monospace_font(size=10 + delta))
        self._schedule_fit_toolbars()  # bigger interface text makes the toolbars wider

    def preferences(self):
        dlg = PreferencesDialog(self.prefs, self.themes, self)
        if dlg.exec():
            dlg.save()
            self._apply_prefs()
            self._apply_theme(self.prefs.get("theme"))
            self._live_check()

    # ============================================================== files
    def _fill_examples(self):
        from ..core.meta import parse_metadata
        self.examples_menu.clear()
        folder = resources.files("studio8085").joinpath("examples")
        beginner = folder.joinpath("beginner")
        if beginner.is_dir():
            sub = self.examples_menu.addMenu("Beginner: the essential instructions")
            for f in sorted(beginner.iterdir(), key=lambda x: x.name):
                if f.name.endswith(".asm"):
                    meta = parse_metadata(f.read_text(encoding="utf-8").splitlines())
                    num = f.name.split("_", 1)[0]
                    a = sub.addAction(f"{num}  {meta.get('title', f.name[:-4])}")
                    a.setStatusTip(meta.get("topic", ""))
                    a.triggered.connect(lambda _=False, n="beginner/" + f.name: self._open_example(n))
            self.examples_menu.addSeparator()
        for f in sorted(folder.iterdir(), key=lambda x: x.name):
            if f.name.endswith(".asm"):
                title = f.name[:-4].split("_", 1)
                label = f"{title[0]}  {title[1].replace('_', ' ').title()}" if len(title) == 2 else f.name
                a = self.examples_menu.addAction(label)
                a.triggered.connect(lambda _=False, n=f.name: self._open_example(n))

    def _fill_recent(self):
        self.recent_menu.clear()
        files = [f for f in self.prefs.get("recent") if Path(f).exists()]
        for f in files:
            a = self.recent_menu.addAction(Path(f).name)
            a.setToolTip(f)
            a.triggered.connect(lambda _=False, p=f: self.open_file(Path(p)))
        self.recent_menu.setEnabled(bool(files))

    def _remember(self, path: Path):
        files = [str(path)] + [f for f in self.prefs.get("recent") if f != str(path)]
        self.prefs.set("recent", files[:8])
        self._fill_recent()

    def _maybe_save(self) -> bool:
        if not self.editor.document().isModified():
            return True
        name = self.path.name if self.path else "this file"
        r = QMessageBox.question(self, APP_NAME, f"Save changes to {name}?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                 | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def _set_source(self, text: str, path: Path | None, title: str | None = None):
        self.timer.stop()
        if not self._loading_lab:
            self._end_lab()  # the student opened or started something else: the lab is over
        self.editor.setReadOnly(False)
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        self.editor.apply_auto_breakpoints()
        self.path = path
        self._title = title or (path.name if path else "Untitled")
        self.setWindowTitle(f"{self._title}[*] - {APP_NAME}")
        self.setWindowModified(False)
        self._drop_session()
        self._live_check()

    def _drop_session(self):
        self.timer.stop()
        self.machine.unload(keep_memory=self.prefs.get("keep_memory"))
        self.kit.reset_outputs()  # a new program starts with dark LEDs; the switches stay where they are
        self.stack.reset()
        self._before = None
        self.explain.show_hint()
        self.trace.refresh(self.machine)
        self.loaded_text = None
        self.loaded_origin = None
        self._out_seen = 0
        self.output.log.clear()
        self._set_state("idle")
        self.refresh_all()

    def new_file(self):
        if self._maybe_save():
            self._set_source("; New program\n\n\t\thlt\n", None, "Untitled")

    def open_dialog(self):
        if not self._maybe_save():
            return
        start = str(self.path.parent) if self.path else str(Path.home())
        f, _ = QFileDialog.getOpenFileName(self, "Open assembly file", start, SOURCE_FILTER)
        if f:
            self.open_file(Path(f), checked=True)

    def open_file(self, path: Path, checked: bool = False):
        if not checked and not self._maybe_save():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Cannot open {path}:\n{e}")
            return
        self._set_source(text, path)
        self._remember(path)
        self.say(f"Opened {path}")

    def _open_example(self, name: str):
        if self._maybe_save():
            self._load_example(name)

    def _load_example(self, name: str):
        """``name`` is a file in the examples folder, or ``beginner/<file>`` for the beginner set."""
        parts = name.split("/")
        text = resources.files("studio8085").joinpath("examples", *parts).read_text(encoding="utf-8")
        self._set_source(text, None, parts[-1])
        self.say(f"Example: {parts[-1]}  (File > Save As to keep your changes)")

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        start = str(self.path) if self.path else str(Path.home() / (getattr(self, "_title", "program") if getattr(self, "_title", "").endswith(".asm") else "program.asm"))
        f, _ = QFileDialog.getSaveFileName(self, "Save assembly file", start, SOURCE_FILTER)
        if not f:
            return False
        if not Path(f).suffix:
            f += ".asm"
        return self._write(Path(f))

    def _write(self, path: Path) -> bool:
        try:
            path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Cannot save {path}:\n{e}")
            return False
        self.path = path
        self._title = path.name
        self.setWindowTitle(f"{path.name}[*] - {APP_NAME}")
        self.editor.document().setModified(False)
        self._remember(path)
        self.say(f"Saved {path}")
        return True

    def goto_line(self):
        n, ok = QInputDialog.getInt(self, "Go to line", "Line number:", self.editor.textCursor().blockNumber() + 1,
                                    1, max(1, self.editor.blockCount()))
        if ok:
            self.editor.goto(n)

    # drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self.open_file(Path(url.toLocalFile()))
                break

    # ======================================================== diagnostics
    def _origin(self) -> int:
        v = parse_hex(self.origin_edit.text(), 16)
        return self.prefs.get("origin") if v is None else v

    def _origin_changed(self):
        v = parse_hex(self.origin_edit.text(), 16)
        if v is None:
            self.origin_edit.setText(f"{self.prefs.get('origin'):04X}")
        else:
            changed = v != self.prefs.get("origin")
            self.prefs.set("origin", v)
            self.origin_edit.setText(f"{v:04X}")
            self._live_check()
            if changed:
                self.say(f"The code will be stored at {v:04X}h the next time you assemble or run "
                         "(an ORG line in the source overrides this).")

    def _live_check(self):
        if not self.prefs.get("live_diag") and self.live is not None:
            return
        self._show_result(assemble(self.editor.toPlainText(), self._origin(), compat=self.compat))

    def _show_result(self, res: AsmResult):
        self.live = res
        self.editor.set_diagnostics(res.diagnostics)
        self.problems.set_diagnostics(res.diagnostics)
        names = {s.name: s for s in res.symbols.values()}
        self.editor.highlighter.set_symbols(names)
        self.editor.symbol_info = lambda up, r=res: self._symbol_tip(r, up)
        self.editor.valid_lines = set(res.line_to_addr)
        if res.ok:
            self.listing.set_result(res)
            self.symbols.set_result(res)
            self._rescale(self.listing, self.symbols)
        self.editor.gutter.update()
        self.explain.set_meta(res.metadata)
        self._update_status_hint()
        self._update_code_label()

    @staticmethod
    def _symbol_tip(res: AsmResult, up: str):
        s = res.symbols.get(up)
        if not s:
            return None
        if s.kind == "equ":
            return f"<b>{s.name}</b> = {s.value} ({s.value & 0xFFFF:X}h)  <i>constant, line {s.line}</i>"
        kind = "data" if s.kind == "data" else "code label"
        extra = f", {s.size} byte(s)" if s.size else ""
        return f"<b>{s.name}</b> = {s.value:04X}h  <i>{kind}{extra}, line {s.line}</i>"

    def _problem_counts(self, errors: int, warnings: int, notes: int = 0):
        d = self.docks["problems"]
        parts = []
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings:
            parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
        if notes:
            parts.append(f"{notes} note{'s' if notes != 1 else ''}")
        d.setWindowTitle("Problems" + (f"  ({', '.join(parts)})" if parts else ""))

    def _update_code_label(self):
        """Status bar: the opcode and operand bytes of the instruction on the cursor line."""
        text = ""
        live = self.live
        if live is not None:
            line = self.editor.textCursor().blockNumber() + 1
            addr = live.line_to_addr.get(line)
            form = FORM_OF.get(live.image.get(addr)) if addr is not None else None
            if form is not None:
                data = " ".join(f"{live.image.get((addr + i) & 0xFFFF, 0):02X}" for i in range(form.length))
                text = f"Machine code: {data}"
        self.code_label.setText(text)

    def show_instructions(self):
        """Open the Instructions panel (even from Focus-editor mode) and put the cursor in its search box."""
        if self.a_focus.isChecked():
            self.a_focus.setChecked(False)
            self.toggle_focus_mode()
        d = self.docks["instructions"]
        d.show()
        d.raise_()
        self.instructions.focus_search()

    def _insert_instruction(self, form):
        if not self.editor.insert_instruction(form.insert, form.select):
            self.say("The program is running - press Pause or Stop to edit it.", "warn")
            return
        n = f"{form.length} byte{'s' if form.length != 1 else ''}"
        self.say(f"Inserted {form.label}: opcode {form.hex}h, {n}. Ctrl+Z undoes it.", "ok")

    def _update_status_hint(self):
        if self.state == "idle" and self.live is not None:
            e, w = len(self.live.errors), len(self.live.warnings)
            if e:
                self.flags.set_state(f"{e} error{'s' if e != 1 else ''}", "PillBad")
            elif w:
                self.flags.set_state("Not assembled", "Pill")
            else:
                self.flags.set_state("Not assembled", "Pill")

    # ============================================================== state
    def _is_stale(self) -> bool:
        return self.machine.program is not None and (self.loaded_text != self.editor.toPlainText()
                                                     or self.loaded_origin != self._origin())

    def _set_state(self, state: str):
        self.state = state
        running = state == "running"
        loaded = state in ("ready", "running", "paused", "halted")
        self.editor.set_read_only_running(running)
        self.a_assemble.setEnabled(not running)
        self.a_run.setEnabled(not running)
        self.a_pause.setEnabled(running)
        self.a_stop.setEnabled(loaded)
        self.a_restart.setEnabled(loaded)
        for a in (self.a_into, self.a_over, self.a_out, self.a_cursor):
            a.setEnabled(not running)
        pill = {"idle": ("Not assembled", "Pill"), "ready": ("Ready", "PillOn"), "running": ("Running", "PillOk"),
                "paused": ("Paused", "PillWarn"), "halted": ("Halted", "PillOn")}[state]
        self.flags.set_state(*pill)
        if state == "idle":
            self._update_status_hint()

    def say(self, text: str, kind: str = "info"):
        color = {"error": self.theme.colors["error"], "warn": self.theme.colors["warning"],
                 "ok": self.theme.colors["ok"]}.get(kind)
        self.msg.setStyleSheet(f"color:{color}" if color else "")
        self.msg.setText(text)

    # ======================================================== run control
    def _needs_assemble(self) -> bool:
        return self.machine.program is None or self.state == "idle" or self._is_stale()

    def cmd_assemble(self):
        if self._assemble_and_load():
            prog = self.machine.program
            self.say(f"Assembled {prog.size} byte(s), stored at {prog.origin:04X}h; entry {prog.entry:04X}h", "ok")
            self.memory.scroll_to(prog.origin)  # show where the code was saved

    def _assemble_and_load(self) -> bool:
        self.timer.stop()
        text = self.editor.toPlainText()
        res = assemble(text, self._origin(), compat=self.compat)
        self._show_result(res)
        if not res.ok:
            self.docks["problems"].show()
            self.docks["problems"].raise_()
            self.say(f"{len(res.errors)} error(s) - fix them to run (see Problems)", "error")
            self._set_state("idle")
            self.editor.set_exec_line(None)
            return False
        self.machine.load(res, keep_memory=self.prefs.get("keep_memory"))
        self.kit.reset_outputs()  # assemble / restart / reload: LEDs and display blank, switches kept
        self.stack.reset()
        self._before = None
        self.explain.clear_last("<p><i>Nothing has run yet - the first instruction is highlighted in the editor.</i></p>")
        self.loaded_text = text
        self.loaded_origin = self._origin()
        self._temp_bp = None
        self._out_seen = 0
        self._sync_breakpoints()
        self.output.add(f"--- assembled {res.size} byte(s) stored at {res.origin:04X}h, entry {res.entry:04X}h ---")
        for w in res.warnings:
            self.output.add(f"warning line {w.line}: {w.message}")
        self._set_state("ready")
        if self.trainer.guide.isVisible():
            self.trainer.guide.program_loaded()
        self.refresh_all()
        return True

    def _sync_breakpoints(self):
        prog = self.machine.program
        if not prog:
            return
        bps = {prog.line_to_addr[l] for l in self.editor.breakpoint_lines() if l in prog.line_to_addr}
        if self._temp_bp is not None:
            bps.add(self._temp_bp)
        self.machine.breakpoints = bps

    def _can_wake(self) -> bool:
        cpu = self.machine.cpu
        return bool(cpu.pending) and self._acceptable(cpu)

    @staticmethod
    def _acceptable(cpu) -> bool:
        p = cpu.pending
        return bool(p & 1 or (cpu.ie and ((p & 2 and not cpu.m75) or (p & 4 and not cpu.m65)
                                          or (p & 8 and not cpu.m55) or p & 16)))

    def cmd_run(self):
        if self.state == "running":
            return
        if self._needs_assemble() or (self.state == "halted" and not self._can_wake()):
            if not self._assemble_and_load():
                return
        self._begin("run")

    def cmd_step(self, mode: str):
        if self.state == "running":
            return
        if self._needs_assemble() or (self.state == "halted" and not self._can_wake()):
            if self._assemble_and_load():
                self.say("Ready - the highlighted line runs on the next step", "ok")
            return
        self._begin(mode)

    def cmd_run_to_cursor(self):
        if self.state == "running":
            return
        if self._needs_assemble() and not self._assemble_and_load():
            return
        line = self.editor.textCursor().blockNumber() + 1
        addr = self.machine.program.line_to_addr.get(line)
        if addr is None:
            self.say(f"Line {line} has no instruction to run to", "warn")
            return
        self._begin("run", temp_bp=addr)

    def cmd_pause(self):
        if self.state != "running":
            return
        self.timer.stop()
        self._set_state("paused")
        self.refresh_all()
        self._update_last("run")
        self.say(f"Paused at {self.machine.cpu.pc:04X}h", "warn")

    def cmd_stop(self):
        self.timer.stop()
        if self._temp_bp is not None:
            self._temp_bp = None
            self._sync_breakpoints()
        self._set_state("idle")
        self.editor.set_exec_line(None)
        self.listing.highlight(None)
        self.say("Stopped. Edit the source, or press Run to start again.")

    def cmd_restart(self):
        if self._assemble_and_load():
            memory = ("memory kept (Preferences > Simulation)" if self.prefs.get("keep_memory")
                      else "memory cleared")
            self.say(f"Restarted: source re-assembled and reloaded, {memory}, registers/flags/PC/SP reset. "
                     "I/O port values you entered were kept.", "ok")

    def cmd_clear_memory(self):
        self.machine.cpu.mem.clear()
        if self.machine.program:
            self.machine.reload_program_bytes()
        self.machine.cpu.exec_count = [0] * 65536
        self.refresh_all()

    def _begin(self, mode: str, temp_bp: int | None = None):
        if temp_bp is not None:
            self._temp_bp = temp_bp
            self._sync_breakpoints()
        if self.trainer.concealed:
            # Experiment 1: running now would show A and the LEDs before the student has predicted
            self.say("Experiment 1: lock in your prediction first (or press Help me), then step through the program.",
                     "warn")
            return
        self._mode = mode
        cpu = self.machine.cpu
        self._before = statediff.take(self.machine)
        ins = TABLE[cpu.mem.data[cpu.pc]]
        self._before_ins = (ins.mnemonic if ins else None, mode, self.machine.next_instruction())
        self.machine.start(mode)
        self._set_state("running")
        self._credit = 0.0
        self._last_tick = time.perf_counter()
        self._last_ui = 0.0
        if mode in ("into", "over", "out"):
            self._tick()
        if self.state == "running":
            self.timer.start(0 if self._rate() == 0 or self._mode != "run" else 4)

    def _rate(self) -> int:
        return int(self.speed.currentData() or 0)

    def _tick(self):
        now = time.perf_counter()
        rate = self._rate() if self._mode == "run" else 0
        if rate == 0:
            budget = self._budget
        else:
            self._credit += rate * (now - self._last_tick)
            budget = int(self._credit)
            if budget < 1:
                self._last_tick = now
                return
            self._credit -= budget
            budget = min(budget, 100_000)
        self._last_tick = now
        t0 = time.perf_counter()
        why = self.machine.run_chunk(budget)
        elapsed = time.perf_counter() - t0
        if rate == 0 and elapsed > 0:
            self._budget = max(200, min(400_000, int(self._budget * 0.012 / elapsed)))
        if why is not None:
            self._finish(why)
            return
        interval = 0.016 if rate and rate <= 1000 else 0.08
        if now - self._last_ui >= interval:
            self._last_ui = now
            self.refresh_all()

    def _finish(self, why: Stop):
        self.timer.stop()
        cpu = self.machine.cpu
        if self._temp_bp is not None:
            self._temp_bp = None
            self._sync_breakpoints()
        if why is Stop.HALT:
            self._set_state("halted")
            us = cpu.tstates / self.prefs.get("clock_mhz")
            msg = (f"Halted after {cpu.icount:,} instructions, {cpu.tstates:,} T-states "
                   f"({us:,.1f} µs at {self.prefs.get('clock_mhz'):g} MHz)")
            self.say(msg, "ok")
            self.output.add(msg)
        elif why is Stop.STEP:
            self._set_state("paused")
            self.say("")
        elif why is Stop.BREAKPOINT:
            self._set_state("paused")
            line = self.machine.current_line()
            self.say(f"Breakpoint at line {line}" if line else f"Breakpoint at {cpu.pc:04X}h", "warn")
        else:
            self._set_state("paused")
            text = self.machine.stop_reason_text(why)
            self.say(text, "error")
            self.output.add(f"!!! {text}")
        self.refresh_all()
        self._update_last(self._mode)

    def _raise_irq(self, name: str, rst: int):
        if self.machine.program is None:
            self.say("Assemble the program first (F7), then raise interrupts while it runs", "warn")
            return
        cpu = self.machine.cpu
        cpu.raise_interrupt(name, rst)
        self.interrupts.refresh()
        self.output.add(f"{name} raised" + (f" (RST {rst})" if name == "INTR" else ""))
        if self.state == "halted":
            if self._acceptable(cpu):
                self._begin("run")
            else:
                self.say(f"{name} is pending but masked or interrupts are disabled (IE=0) - see the Interrupts panel", "warn")
        elif self.state in ("paused", "ready"):
            self.say(f"{name} pending - it is taken before the next instruction")

    def _after_manual_edit(self):
        self.refresh_all()

    # ============================================== Virtual 8085 Trainer Kit
    TRAINER_EXAMPLES = [("E1_read_switches_control_leds.asm", "Lab program: Read switches, control LEDs (E1)"),
                        ("E1b_seven_segment_raw.asm", "Lab program: Seven-segment raw bits"),
                        ("E1c_seven_segment_hex.asm", "Lab program: Seven-segment hex decode")]

    def _make_kit(self) -> TrainerKit:
        p = self.prefs
        ports = PortMap(p.get("trainer_switch_port"), p.get("trainer_led_port"), p.get("trainer_seg_port"))
        try:
            ports.validate()
        except PeripheralConfigError:
            ports = PortMap()  # a damaged setting: fall back to the documented defaults
        kit = TrainerKit(self.machine.cpu, ports, enabled=p.get("trainer_enabled"))
        try:
            kit.display.set_mode(p.get("trainer_seg_mode"))
        except PeripheralConfigError:
            pass
        return kit

    def _trainer_changed(self):
        """The user flipped a switch: the I/O Ports row of the switch port mirrors it."""
        if self.io.isVisible():
            self.io.refresh()
        if self.state in ("ready", "paused", "halted"):
            self.explain.refresh_next(self.machine.program is not None)  # "IN 00h will read ..." stays true

    def _apply_conceal(self, on: bool):
        """Experiment 1, before the student has predicted: show the kit's ports as ``??`` in the I/O Ports table,
        the Output log, the Explain panel and the Trace table. Display only - ``cpu.io``, the switches and the
        CPU are never touched, and everything is shown again as soon as the student predicts, asks for help or
        ends the experiment."""
        p = self.kit.ports
        ports = {p.switches_in, p.leds_out, p.seven_segment_out} if on else ()
        self.io.set_concealed(ports)
        self.output.set_concealed(ports)
        self.trace.set_concealed(on)
        self.explain.concealed = on
        if on:
            self.explain.clear_last()
        self.explain.refresh_next(self.explain._active)
        self.refresh_all()

    def _trainer_enabled(self, on: bool):
        self.prefs.set("trainer_enabled", on)
        self.say("Trainer kit connected: IN/OUT on its ports drive the switches, LEDs and display." if on else
                 "Trainer kit disconnected: IN/OUT use only the I/O Ports table, exactly as before.")
        self.refresh_all()

    def _io_edited(self, top, bottom, _roles=None):
        """An edit in the I/O Ports table on the switch port sets the switches (the switches own that port)."""
        k = self.kit
        if not k.enabled:
            return
        port = k.switches.port
        if top.row() <= port <= bottom.row() and self.machine.cpu.io[port] != k.switches.value:
            k.set_switches(self.machine.cpu.io[port])
            self.trainer.refresh()

    def show_trainer(self):
        if self.a_focus.isChecked():
            self.a_focus.setChecked(False)
            self.toggle_focus_mode()
        d = self.docks["trainer"]
        d.show()
        d.raise_()
        QTimer.singleShot(0, self._size_trainer_dock)

    def _size_trainer_dock(self):
        """Ask for the panel's natural height when it is docked in a short tab group (never more than about
        60 % of the window, so the editor and the other column keep their space; the panel scrolls)."""
        d = self.docks["trainer"]
        if d.isFloating() or not d.isVisible():
            return
        holder = d.widget()
        need = holder.widget().sizeHint().height() + max(0, d.height() - holder.height())
        want = min(need, round(self.height() * 0.6))
        if d.height() < want:
            self.resizeDocks([d], [want], Qt.Orientation.Vertical)

    def trainer_ports(self):
        dlg = PortMapDialog(self.kit.ports, self)
        if not dlg.exec():
            return
        ports = dlg.ports()
        try:
            self.kit.set_ports(ports)
        except PeripheralConfigError as e:  # the dialog validates first; keep a clear message anyway
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        self.prefs.set("trainer_switch_port", ports.switches_in)
        self.prefs.set("trainer_led_port", ports.leds_out)
        self.prefs.set("trainer_seg_port", ports.seven_segment_out)
        self.trainer.sync_from_kit()
        if self.trainer.concealed:
            self._apply_conceal(True)  # the masked ports moved with the mapping
        self.say(f"Trainer kit ports: switches IN {ports.switches_in:02X}H, LEDs OUT {ports.leds_out:02X}H, "
                 f"seven-segment OUT {ports.seven_segment_out:02X}H", "ok")
        self.refresh_all()

    def trainer_reset(self):
        self.kit.reset_hardware()
        self.trainer.sync_from_kit()
        self.say("Trainer kit reset: switches down, LEDs and display blank. The CPU was not touched.")
        self.refresh_all()

    def _open_trainer_example(self, name: str):
        if self._maybe_save():
            self._loading_lab = True
            try:
                self._load_example("trainer/" + name)
            finally:
                self._loading_lab = False
            self._begin_lab()
            self._apply_display_hint()

    def _begin_lab(self):
        """A lab is running: the kit must be visible, and stays visible in Beginner mode until the lab ends."""
        self._lab_active = True
        self.show_trainer()

    def _end_lab(self):
        if not self._lab_active:
            return
        self._lab_active = False
        if self.trainer.guide.isVisible():
            self.trainer.hide_guide()  # leaving the experiment shows everything again

    def _apply_display_hint(self):
        """A lab program may say ``; @display: hex`` (or raw): switch the display mode for it. Display only."""
        mode = (self.live.metadata.get("display", "") if self.live else "").strip().lower()
        if mode in ("raw", "hex") and mode != self.kit.display.mode:
            self.kit.display.set_mode(mode)
            self.prefs.set("trainer_seg_mode", mode)
            self.trainer.sync_from_kit()
            self.say(f"This lab uses the seven-segment display in {'Hex decode' if mode == 'hex' else 'Raw segment bits'} "
                     "mode (Trainer Kit panel). Changing the mode never touches the CPU.", "ok")

    def start_experiment(self):
        """Lab > Experiment 1: show the kit with the guided flow (the program is loaded at its 'Assemble' step)."""
        self._begin_lab()
        self.trainer.show_guide()
        self.trainer.refresh()
        self.say("Experiment 1: follow the steps in the Trainer Kit panel.", "ok")

    def start_experiment_program(self):
        if not self._maybe_save():
            return
        self._loading_lab = True
        try:
            self._load_example("trainer/" + self.TRAINER_EXAMPLES[0][0])
        finally:
            self._loading_lab = False
        if self._assemble_and_load():
            self.say("Experiment 1 program assembled. Press Step Into (F11) to execute IN.", "ok")

    # ============================================================= refresh
    def _pull_out_log(self):
        m = self.machine
        new = m.out_count - self._out_seen
        if new > 0:
            for icount, port, value in m.out_log[-min(new, len(m.out_log)):][-200:]:
                self.output.add(f"[{icount:>9,}]  OUT {port:02X}h <- {value:02X}h  ({value})", port,
                                f"[{icount:>9,}]  OUT {port:02X}h <- ??h  (hidden until you predict)")
                self.io.note_out(port, icount)
            self._out_seen = m.out_count
        elif new < 0:
            self._out_seen = m.out_count

    def _update_exec_line(self):
        line = None
        if self.machine.program is not None and self.state != "idle":
            pc = self.machine.cpu.pc
            addr_line = self.machine.program.addr_to_line
            line = addr_line.get((pc - 1) & 0xFFFF) if self.state == "halted" and self.machine.cpu.halted else addr_line.get(pc)
        self.editor.set_exec_line(line, reveal=self.state != "running")
        self.listing.highlight(line)

    def _refresh_widget(self, w):
        if hasattr(w, "refresh"):
            w.refresh()

    def refresh_all(self):
        cpu = self.machine.cpu
        self.stack.update_base()  # keep the stack extent right even when the Stack panel is hidden
        self.registers.refresh(reset_marks=self.state in ("idle", "ready"))
        self.flags.refresh()
        for w in (self.stack, self.io, self.symbols, self.interrupts, self.memory, self.trainer):
            if w.isVisible():
                w.refresh()
        self._pull_out_log()
        self._update_exec_line()
        if self.state != "running":
            self.explain.refresh_next(self.machine.program is not None and self.state != "idle")
            if self.docks["trace"].isVisible():
                self.trace.refresh(self.machine)
                self._rescale(self.trace)
        self.pc_label.setText(f"PC {cpu.pc:04X}h   SP {cpu.sp:04X}h")


    # ====================================================== modes & layout
    def _set_mode(self, mode: str, save: bool = True, first: bool = False):
        mode = mode if mode in ("beginner", "advanced") else "beginner"
        if not first and self.mode == "advanced" and mode != "advanced":
            self.prefs.q.setValue("window/state_advanced", self.saveState())
        changed = mode != self.mode or first
        self.mode = mode
        beginner = mode == "beginner"
        self.memory.set_simple(beginner)
        self.flags.set_simple(beginner)
        for act in self._advanced_actions:
            act.setVisible(not beginner)
        self.tb_run.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if beginner
                                       else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.a_mode[mode].setChecked(True)
        btn = self.tb_extra.widgetForAction(self.a_instr)
        if btn is not None:
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if beginner
                                   else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(mode))
        self.mode_combo.blockSignals(False)
        if save:
            self.prefs.set("mode", mode)
        if changed and not (first and self._layout_restored):
            if beginner:
                self._beginner_layout()
            else:
                state = self.prefs.q.value("window/state_advanced")
                if isinstance(state, QByteArray) and not state.isEmpty() and not first:
                    self.restoreState(state)
                    self._layout_restored = True
                    self._place_docks_missing_from(state, "advanced")
                elif not first:
                    self._default_layout()
        self._schedule_fit_toolbars()
        if not first:
            self.say("Beginner mode: the essentials only. Switch to Advanced (toolbar or View menu) for every panel."
                     if beginner else "Advanced mode: all panels.")
        self.refresh_all()

    def toggle_focus_mode(self, _checked=None):
        if self.a_focus.isChecked():
            self._hidden_for_focus = [k for k, d in self.docks.items() if d.isVisible()]
            for d in self.docks.values():
                d.hide()
        else:
            for k in self._hidden_for_focus or []:
                self.docks[k].show()
            self._hidden_for_focus = None

    def _set_compat(self, mode: str):
        self.compat = mode
        self.prefs.set("compat", mode)
        for k, a in self.a_compat.items():
            a.setChecked(k == mode)
        self._show_result(assemble(self.editor.toPlainText(), self._origin(), compat=mode))
        if self.machine.program is not None:
            self.loaded_text = None  # the loaded program was built under other rules: re-assemble on next run
        self.say({"off": "Syntax checks off.", "note": "Blue notes mark syntax GNUSim8085 would not accept.",
                  "strict": "GNUSim8085-compatible mode: syntax it would reject is an error."}[mode])

    # ===================================================== trace + explain
    def _set_trace(self, on: bool):
        self.machine.set_trace(on)
        self.a_trace.setChecked(on)
        self.trace.set_recording(on)
        if on:
            self.docks["trace"].show()
            self.docks["trace"].raise_()
            self.say("Recording a trace: every executed instruction becomes a row (Debug > Export Trace...).", "ok")
        else:
            self.say("Trace recording stopped (the recorded rows are kept until you clear them).")
        self.trace.refresh(self.machine)

    def clear_trace(self):
        self.machine.clear_trace()
        self.trace.refresh(self.machine)

    def export_trace(self):
        rows = self.machine.trace
        if not rows:
            self.say("No trace recorded yet: turn on Debug > Record Execution Trace, then run or step.", "warn")
            return
        base = Path(getattr(self, "_title", "program")).stem + "-trace"
        start = str((self.path.parent if self.path else Path.home()) / base)
        f, flt = QFileDialog.getSaveFileName(
            self, "Export trace", start, "CSV (*.csv);;Markdown (*.md);;HTML (*.html);;PDF (*.pdf)")
        if not f:
            return
        ext = {"CSV": ".csv", "Markdown": ".md", "HTML": ".html", "PDF": ".pdf"}[flt.split(" ")[0]]
        path = Path(f)
        if path.suffix.lower() not in (".csv", ".md", ".html", ".pdf"):
            path = path.with_suffix(ext)
        try:
            self.write_trace(path)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Cannot save {path}:\n{e}")
            return
        self.say(f"Saved a trace of {len(rows):,} instruction(s) to {path}", "ok")

    def write_trace(self, path: Path):
        """Write the recorded trace; the format follows the file extension."""
        rows = self.machine.trace
        title = f"Execution trace - {getattr(self, '_title', 'program')}"
        note = f"{len(rows):,} instruction(s)" + (" (recording stopped at the row limit)" if self.machine.trace_truncated else "")
        suffix = path.suffix.lower()
        if suffix == ".csv":
            path.write_text(to_csv(rows), encoding="utf-8")
        elif suffix == ".md":
            path.write_text(to_markdown(rows, title, note), encoding="utf-8")
        elif suffix == ".pdf":
            doc = QTextDocument()
            doc.setHtml(to_html(rows, title, note, font_pt=6))
            w = QPdfWriter(str(path))
            w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            w.setPageOrientation(QPageLayout.Orientation.Landscape)
            w.setPageMargins(QMarginsF(8, 8, 8, 8), QPageLayout.Unit.Millimeter)
            doc.print_(w)
        else:
            path.write_text(to_html(rows, title, note), encoding="utf-8")

    def _update_last(self, mode: str):
        """Fill 'What just happened' from the snapshot taken when the run began."""
        if self._before is None:
            return
        cpu = self.machine.cpu
        after = statediff.take(self.machine)
        d = statediff.compare(self._before, after)
        mn, _, text = self._before_ins or (None, mode, "")
        verb = {"into": "Step Into", "over": "Step Over", "out": "Step Out", "run": "Run"}.get(mode, "Run")
        if d.instructions == 0:
            head = "<p><i>No instruction executed.</i></p>"
        elif d.instructions == 1:
            head = f"<p>Executed <b>{text}</b> &mdash; {d.tstates} T-states.</p>"
        else:
            head = f"<p><b>{verb}</b>: {d.instructions:,} instructions, {d.tstates:,} T-states.</p>"
        notes = []
        if d.instructions == 1 and mn:
            notes = flag_notes(mn, self._before.flags, after.flags, ac_borrow_style=cpu.ac_borrow_style)
        extra = []
        if d.mem:
            shown = ", ".join(f"[{a:04X}h] {o:02X}h -> {n:02X}h" for a, o, n in d.mem[:8])
            extra.append("Memory changed: " + shown + (" ..." if len(d.mem) > 8 else ""))
        if d.io:
            extra.append("I/O ports changed: " + ", ".join(f"{p:02X}h {o:02X}h -> {n:02X}h" for p, o, n in d.io[:8]))
        self.explain.show_last(head, d.items, notes, extra)
        self._rescale(self.explain)

    # =============================================================== misc
    def show_reference(self, tab: int = 0):
        ReferenceDialog(self, tab).exec()

    @staticmethod
    def about_html() -> str:
        return (f"<h3>{APP_NAME} {__version__}</h3>"
                "<p>An assembler, simulator and debugger for the Intel 8085 microprocessor.</p>"
                f"<p><b>Designed by {IDEA_AUTHOR}</b><br>{IDEA_AFFILIATION}</p>"
                "<p>Written in Python with Qt (PySide6). Instruction-level T-state accounting, interrupts, "
                "SIM/RIM, flags per the Intel manual and a live memory heatmap.</p>"
                "<p>See docs/ACCURACY.md for exactly what is and is not modelled.</p>")

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}", self.about_html())

    def _restore_layout(self):
        q = self.prefs.q
        geo = q.value("window/geometry")
        state = q.value("window/state")
        if isinstance(geo, QByteArray) and not geo.isEmpty():
            self.restoreGeometry(geo)
            self._fit_to_screen()  # saved on a bigger screen (or a projector): keep it on this one
        else:
            screen = self.screen().availableGeometry()
            self.resize(min(1500, screen.width() - 40), min(900, screen.height() - 60))
        if isinstance(state, QByteArray) and not state.isEmpty():
            self.restoreState(state)
            self._layout_restored = True
            self._place_docks_missing_from(state, self.prefs.get("mode"))
            if self.prefs.get("mode") == "beginner":
                self._enforce_beginner_docks()

    def _place_docks_missing_from(self, state: QByteArray, mode: str):
        """A layout saved before a dock existed (e.g. by 8085 Studio 1.1.0, before the Trainer Kit) does not
        mention it, and Qt then leaves it wherever the default layout put it. Give it the default place of the
        mode instead: hidden in Beginner mode, a tab next to I/O Ports in Advanced mode."""
        raw = bytes(state.data())
        d = self.docks["trainer"]
        if "trainer".encode("utf-16-be") in raw:
            return
        if mode == "beginner":
            d.hide()
            return
        # isHidden, not isVisible: at start-up the window itself is not shown yet
        mate = next((self.docks[k] for k in ("symbols", "io", "stack", "memory") if not self.docks[k].isHidden()), None)
        if mate is None:
            d.hide()  # the user had closed that whole column; do not add one
            return
        d.show()
        self.tabifyDockWidget(mate, d)
        mate.raise_()

    def _fit_to_screen(self):
        """Shrink/move the (non-maximised) window so it lies inside the available screen area."""
        if self.isMaximized() or self.isFullScreen() or self.screen() is None:
            return
        avail = self.screen().availableGeometry()
        frame = self.frameGeometry()
        extra_w, extra_h = frame.width() - self.width(), frame.height() - self.height()
        w = min(self.width(), avail.width() - extra_w)
        h = min(self.height(), avail.height() - extra_h)
        if (w, h) != (self.width(), self.height()):
            self.resize(max(w, self.minimumSizeHint().width()), max(h, self.minimumSizeHint().height()))
        frame = self.frameGeometry()
        x = min(max(frame.x(), avail.left()), max(avail.left(), avail.right() - frame.width() + 1))
        y = min(max(frame.y(), avail.top()), max(avail.top(), avail.bottom() - frame.height() + 1))
        if (x, y) != (frame.x(), frame.y()):
            self.move(x, y)

    # ------------------------------------------------------------ toolbar fit
    def _toolbars_in_row(self) -> list[QToolBar]:
        return [tb for tb in (self.tb_file, self.tb_run, self.tb_extra)
                if not tb.isHidden() and self.toolBarArea(tb) == Qt.ToolBarArea.TopToolBarArea]

    def _fit_toolbars(self):
        """Move the Tools toolbar to a second row when the three toolbars do not fit in one.

        Qt hides whatever does not fit behind the toolbar's overflow chevron. In Beginner mode the
        Run toolbar shows text beside its icons and is wide, so on a narrow window (or at a high
        display scale) the "Store code at" box - which must be visible in both modes - ended up
        behind the chevron. A second row gives the Tools toolbar the full window width; "Store code
        at" is its first item, so it stays visible. One row is used again when everything fits.
        """
        if not hasattr(self, "tb_extra"):  # called while the window is still being built
            return
        if self.tb_extra.isHidden() or self.toolBarArea(self.tb_extra) != Qt.ToolBarArea.TopToolBarArea:
            return
        # widths as if the "Speed" / "Mode" captions were shown (they may be hidden by compact mode)
        beginner = getattr(self, "mode", "beginner") == "beginner"
        labels = [(act, lbl) for act, lbl, adv_only in self._compact_labels if not (adv_only and beginner)]
        hidden = sum(lbl.sizeHint().width() for act, lbl in labels if not act.isVisible())
        need = sum(tb.sizeHint().width() for tb in self._toolbars_in_row()) + hidden
        wrap = need > self.width()
        if wrap != self.toolBarBreak(self.tb_extra):
            if wrap:
                self.insertToolBarBreak(self.tb_extra)
            else:
                self.removeToolBarBreak(self.tb_extra)
        # Very narrow (or a high display scale with wide fonts): even a row of its own is too short for
        # the Tools toolbar, and the Mode box would go behind the chevron. Drop the two captions then;
        # the boxes keep their tooltips and accessible names.
        full = self.tb_extra.sizeHint().width() + hidden
        compact = wrap and full > self.width()
        for act, lbl in labels:
            if act.isVisible() == compact:
                act.setVisible(not compact)
        # Never narrower than the compact Tools row, so its last item (the Mode box) cannot be pushed
        # behind the chevron. This is far below 800 px; the docks scroll instead.
        narrowest = full - sum(lbl.sizeHint().width() for act, lbl in labels)
        if self.minimumWidth() != narrowest:
            self.setMinimumWidth(narrowest)

    def _schedule_fit_toolbars(self):
        self._fit_toolbars()
        QTimer.singleShot(0, self._fit_toolbars)  # again once the toolbars have re-laid out

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_toolbars()

    def showEvent(self, e):
        super().showEvent(e)
        self._schedule_fit_toolbars()

    def closeEvent(self, e):
        if not self._maybe_save():
            e.ignore()
            return
        self.timer.stop()
        q = self.prefs.q
        q.setValue("window/geometry", self.saveGeometry())
        q.setValue("window/state", self.saveState())
        if self.mode == "advanced":
            q.setValue("window/state_advanced", self.saveState())
        e.accept()
