"""Help dialogs: searchable instruction reference and assembler syntax guide."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHeaderView, QLineEdit, QTableWidget, QTableWidgetItem,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..core.opcodes import BY_MNEMONIC, DIRECTIVE_INFO, INFO
from .docks import mono

SYNTAX_HTML = """
<h3>Source format</h3>
<pre>[label:]  mnemonic  [operand[, operand]]   ; comment</pre>
<p>Labels end with <b>:</b> (the colon is optional only in front of <b>EQU</b>, <b>DB</b>, <b>DW</b>, <b>DS</b>).
Instructions, registers and labels are not case-sensitive.</p>

<h3>Numbers</h3>
<table cellpadding="3">
<tr><td><code>255</code> or <code>255d</code></td><td>decimal</td></tr>
<tr><td><code>0FFh</code> or <code>0xFF</code></td><td>hexadecimal (an <code>h</code> number must start with a digit: <code>0ABh</code>, not <code>ABh</code>)</td></tr>
<tr><td><code>11111111b</code></td><td>binary</td></tr>
<tr><td><code>377o</code> or <code>377q</code></td><td>octal</td></tr>
<tr><td><code>'A'</code></td><td>character code</td></tr>
<tr><td><code>$</code></td><td>address of the current instruction/data</td></tr>
</table>

<h3>Expressions</h3>
<p>Anywhere a number is expected you can write an expression using labels, constants and
<code>+ - * / % &amp; | ^ ~ &lt;&lt; &gt;&gt;</code>, parentheses, and the word operators
<code>AND OR XOR NOT SHL SHR MOD HIGH LOW</code>.
Example: <code>LXI H, table + 2*count</code> or <code>MVI A, HIGH(buffer)</code>.</p>

<h3>Directives</h3>
<table cellpadding="3">
<tr><td><code>ORG addr</code></td><td>continue assembling at <i>addr</i></td></tr>
<tr><td><code>DB v1, v2, "text"</code></td><td>define bytes and strings</td></tr>
<tr><td><code>DW v1, v2</code></td><td>define 16-bit words (low byte first)</td></tr>
<tr><td><code>DS n[, fill]</code></td><td>reserve <i>n</i> bytes</td></tr>
<tr><td><code>name: EQU value</code></td><td>named constant</td></tr>
<tr><td><code>END [label]</code></td><td>stop assembling; optional entry point</td></tr>
</table>

<h3>Debugging</h3>
<ul>
<li>Click the gutter (or press <b>F9</b>) to toggle a breakpoint. A comment line containing only <code>;@</code> sets a breakpoint on the next line when the file is opened.</li>
<li><b>F11</b> step into, <b>F10</b> step over (runs a whole CALL/RST), <b>Shift+F11</b> step out (runs until the current routine returns).</li>
<li>Edit registers, flags, memory bytes and input ports directly in their panels.</li>
<li>The heatmap shows every memory byte: blue = read, orange = written, green = executed code.</li>
</ul>

<h3>Interrupts</h3>
<p>After reset RST 7.5/6.5/5.5 are masked. Unmask them with <code>MVI A,08h</code> / <code>SIM</code>
(bit 3 enables the mask change, bits 0-2 mask 5.5/6.5/7.5), then <code>EI</code>.
Raise requests from the Interrupts panel. <b>TRAP</b> ignores masks and EI.</p>
"""


class ReferenceDialog(QDialog):
    def __init__(self, parent=None, start_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("8085 Reference")
        self.resize(980, 620)
        tabs = QTabWidget()

        page = QWidget()
        lay = QVBoxLayout(page)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter: type a mnemonic or any word from the description...")
        self.search.setClearButtonEnabled(True)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Syntax", "Opcode", "Bytes", "T-states", "Flags", "Description"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.search)
        lay.addWidget(self.table)
        self._fill()
        self.search.textChanged.connect(self._filter)
        tabs.addTab(page, "Instruction set")

        guide = QTextBrowser()
        guide.setHtml(SYNTAX_HTML)
        guide.setOpenExternalLinks(True)
        tabs.addTab(guide, "Assembler syntax")
        tabs.setCurrentIndex(start_tab)

        outer = QVBoxLayout(self)
        outer.addWidget(tabs)

    def _fill(self):
        f = mono(10)
        rows = []
        for mn in sorted(INFO):
            syntax, desc, flags = INFO[mn]
            forms = BY_MNEMONIC[mn]
            ops = sorted(i.opcode for i in forms)
            op = ", ".join(f"{o:02X}" for o in ops) if len(ops) <= 3 else f"{ops[0]:02X}-{ops[-1]:02X}"
            ts = sorted({i.tstates for i in forms} | {i.tstates + i.taken_extra for i in forms})
            size = sorted({i.length for i in forms})
            rows.append((syntax, op, "/".join(map(str, size)), "/".join(map(str, ts)), flags, desc))
        for syn, (s, d) in DIRECTIVE_INFO.items():
            rows.append((s, "-", "-", "-", "-", d + "  (directive)"))
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                it = QTableWidgetItem(text)
                if c < 5:
                    it.setFont(f)
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

    def _filter(self, text: str):
        t = text.lower().strip()
        for r in range(self.table.rowCount()):
            hay = " ".join(self.table.item(r, c).text().lower() for c in range(6))
            self.table.setRowHidden(r, bool(t) and t not in hay)
