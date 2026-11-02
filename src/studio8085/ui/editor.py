"""Source editor: line numbers, breakpoint gutter, syntax highlighting,
squiggly diagnostics, execution-line marker, tooltips and small conveniences."""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QKeySequence, QPainter, QPolygonF,
                           QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat,
                           QTextBlockUserData, QTextDocument)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QToolTip, QWidget

from ..core.assembler import ERROR, NOTE, WARNING, Diagnostic, find_comment
from ..core.expr import WORD_OPS
from ..core.opcodes import (BY_MNEMONIC, DIRECTIVE_INFO, DIRECTIVES, INFO, MNEMONICS,
                            RESERVED_REGISTERS)
from .themes import SYNTAX_TOKENS, Theme

_STRING_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
_LABEL_RE = re.compile(r"^\s*([A-Za-z_?@.][A-Za-z0-9_?@.]*)\s*:")
_TOKEN_RE = re.compile(r"(?P<num>0[xX][0-9A-Fa-f]+|\b[0-9][0-9A-Fa-f]*[hHbBoOqQdD]?\b)"
                       r"|(?P<word>[A-Za-z_?@.][A-Za-z0-9_?@.]*)")
_WORD_AT = re.compile(r"[A-Za-z_?@.][A-Za-z0-9_?@.]*")


def first_word_start(text: str) -> int:
    """Column where the instruction/directive starts (after an optional label)."""
    m = _LABEL_RE.match(text)
    pos = m.end() if m else 0
    return pos + len(text[pos:]) - len(text[pos:].lstrip())


def monospace_font(family: str = "", size: int = 11) -> QFont:
    if family:
        f = QFont(family)
    else:
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for cand in ("JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo",
                     "Ubuntu Mono", "Liberation Mono"):
            if cand in QFontDatabase.families():
                f = QFont(cand)
                break
    f.setPointSize(size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


class AsmHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self.formats: dict[str, QTextCharFormat] = {}
        self.symbols: set[str] = set()

    def set_theme(self, theme: Theme, overrides: dict[str, str] | None = None):
        for tok in SYNTAX_TOKENS:
            color, bold, italic = theme.syntax_format(tok, overrides)
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            if italic:
                fmt.setFontItalic(True)
            self.formats[tok] = fmt
        self.rehighlight()

    def set_symbols(self, names):
        new = {n.upper() for n in names}
        if new != self.symbols:
            self.symbols = new
            self.rehighlight()

    def highlightBlock(self, text: str):
        if not self.formats:
            return
        f = self.formats
        cstart = find_comment(text)
        if cstart < len(text):
            self.setFormat(cstart, len(text) - cstart,
                           f["marker"] if text[cstart:cstart + 2] == ";@" else f["comment"])
        code = text[:cstart]
        strings = []
        for m in _STRING_RE.finditer(code):
            strings.append((m.start(), m.end()))
            self.setFormat(m.start(), m.end() - m.start(), f["string"])
        pos = 0
        m = _LABEL_RE.match(code)
        if m:
            self.setFormat(m.start(1), m.end(1) - m.start(1), f["label"])
            pos = m.end()
        first = True
        for m in _TOKEN_RE.finditer(code, pos):
            if any(a <= m.start() < b for a, b in strings):
                continue
            start, length = m.start(), m.end() - m.start()
            if m.group("num"):
                self.setFormat(start, length, f["number"])
                first = False
                continue
            word = m.group("word").upper()
            if first:
                first = False
                if word in MNEMONICS:
                    self.setFormat(start, length, f["mnemonic"])
                elif word in DIRECTIVES:
                    self.setFormat(start, length, f["directive"])
                else:
                    rest = code[m.end():]
                    nxt = _WORD_AT.match(rest.lstrip())
                    if nxt and nxt.group(0).upper() in ("EQU", "DB", "DW", "DS"):
                        self.setFormat(start, length, f["label"])
                continue
            if word in RESERVED_REGISTERS:
                self.setFormat(start, length, f["register"])
            elif word in WORD_OPS or word in DIRECTIVES:
                self.setFormat(start, length, f["directive"])
            elif word in self.symbols:
                self.setFormat(start, length, f["symbol"])


class BlockData(QTextBlockUserData):
    def __init__(self):
        super().__init__()
        self.bp = False


class _Gutter(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor
        self.setMouseTracking(True)

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, e):
        self.editor.paint_gutter(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.editor.gutter_clicked(e.position().toPoint().y())


class CodeEditor(QPlainTextEdit):
    breakpoints_changed = Signal()
    content_changed = Signal()  # debounced
    caret_moved = Signal(int, int)  # line, column (1-based)
    font_size_changed = Signal(int)  # after zoom, so the new size can be remembered

    BP_W, DIAG_W = 20, 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme: Theme | None = None
        self.diagnostics: list[Diagnostic] = []
        self.exec_line: int | None = None
        self.valid_lines: set[int] | None = None  # lines that hold code (None = unknown)
        self.symbol_info = lambda name: None  # name -> description string or None
        self.find_matches: list[QTextCursor] = []
        self._font_size = 11
        self._family = ""

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(monospace_font())
        self.setCursorWidth(2)
        self.setMouseTracking(True)
        self.gutter = _Gutter(self)
        self.highlighter = AsmHighlighter(self.document())

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._on_cursor)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(280)
        self._debounce.timeout.connect(self.content_changed)
        self.textChanged.connect(self._debounce.start)
        self._update_gutter_width()
        self.set_tab_width(8)

    # ------------------------------------------------------------ theme
    def set_theme(self, theme: Theme, overrides: dict[str, str] | None = None):
        self.theme = theme
        self.highlighter.set_theme(theme, overrides)
        self._refresh_selections()
        self.gutter.update()

    def apply_font(self, family: str, size: int):
        self._family, self._font_size = family, size
        self.reapply_font()

    def reapply_font(self):
        """(Re)set the editor font from the remembered family and size.

        Qt restores a widget's original font whenever the application stylesheet is set again
        (theme change), so this must be called after every ``setStyleSheet``."""
        self.setFont(monospace_font(self._family, self._font_size))
        self.set_tab_width(self._tab_chars)
        self._update_gutter_width()
        self.gutter.update()

    def set_tab_width(self, chars: int):
        self._tab_chars = chars
        self.setTabStopDistance(chars * self.fontMetrics().horizontalAdvance(" "))

    def zoom(self, delta: int):
        new = max(6, min(72, self._font_size + delta))
        if new == self._font_size:
            return
        self._font_size = new
        self.reapply_font()
        self.font_size_changed.emit(new)

    # ----------------------------------------------------------- gutter
    def gutter_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return self.BP_W + self.DIAG_W + self.fontMetrics().horizontalAdvance("9") * digits + 10

    def _update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        if not self.theme:
            return
        t = self.theme
        p = QPainter(self.gutter)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(event.rect(), t.c("gutter_bg"))
        p.setPen(t.c("border"))
        p.drawLine(self.gutter.width() - 1, event.rect().top(), self.gutter.width() - 1, event.rect().bottom())
        fm = self.fontMetrics()
        cur_line = self.textCursor().blockNumber() + 1
        rank = {ERROR: 3, WARNING: 2, NOTE: 1}
        diag_by_line: dict[int, str] = {}
        for d in self.diagnostics:
            if rank[d.severity] > rank.get(diag_by_line.get(d.line), 0):
                diag_by_line[d.line] = d.severity
        block = self.firstVisibleBlock()
        n = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        w = self.gutter.width()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line = n + 1
                h = bottom - top
                cy = top + h / 2
                p.setPen(t.c("text") if line == cur_line else t.c("gutter_text"))
                p.drawText(QRect(self.BP_W + self.DIAG_W, top, w - self.BP_W - self.DIAG_W - 8, h),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(line))
                data = block.userData()
                if data is not None and getattr(data, "bp", False):
                    verified = self.valid_lines is None or line in self.valid_lines
                    r = min(6.0, h / 2 - 2)
                    if verified:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(t.c("bp"))
                    else:
                        p.setPen(t.c("bp"))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QPointF(self.BP_W / 2, cy), r, r)
                if line == self.exec_line:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(t.c("exec_arrow"))
                    x = self.BP_W / 2
                    p.drawPolygon(QPolygonF([QPointF(x - 5, cy - 5.5), QPointF(x + 6, cy), QPointF(x - 5, cy + 5.5)]))
                sev = diag_by_line.get(line)
                if sev:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(t.c({ERROR: "error", WARNING: "warning", NOTE: "info"}[sev]))
                    p.drawEllipse(QPointF(self.BP_W + self.DIAG_W / 2 - 1, cy), 3.2, 3.2)
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            n += 1

    def gutter_clicked(self, y: int):
        cur = self.cursorForPosition(QPointF(0, y).toPoint())
        self.toggle_breakpoint(cur.blockNumber() + 1)

    # -------------------------------------------------------- breakpoints
    def toggle_breakpoint(self, line: int | None = None):
        if line is None:
            line = self.textCursor().blockNumber() + 1
        block = self.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return
        data = block.userData()
        if data is None:
            data = BlockData()
            block.setUserData(data)
        data.bp = not data.bp
        self.gutter.update()
        self.breakpoints_changed.emit()

    def breakpoint_lines(self) -> list[int]:
        out = []
        b = self.document().begin()
        while b.isValid():
            d = b.userData()
            if d is not None and getattr(d, "bp", False):
                out.append(b.blockNumber() + 1)
            b = b.next()
        return out

    def clear_breakpoints(self):
        b = self.document().begin()
        while b.isValid():
            d = b.userData()
            if d is not None:
                d.bp = False
            b = b.next()
        self.gutter.update()
        self.breakpoints_changed.emit()

    def apply_auto_breakpoints(self):
        """';@' on its own line sets a breakpoint on the following line."""
        self.clear_breakpoints()
        b = self.document().begin()
        while b.isValid():
            if b.text().lstrip().startswith(";@") and b.next().isValid():
                nb = b.next()
                d = nb.userData() or BlockData()
                d.bp = True
                nb.setUserData(d)
            b = b.next()
        self.gutter.update()
        self.breakpoints_changed.emit()

    # ------------------------------------------------------ diagnostics
    def set_diagnostics(self, diags: list[Diagnostic]):
        self.diagnostics = diags
        self._refresh_selections()
        self.gutter.update()

    def set_exec_line(self, line: int | None, reveal: bool = True):
        self.exec_line = line
        self._refresh_selections()
        self.gutter.update()
        if line and reveal:
            self.reveal_line(line)

    def reveal_line(self, line: int):
        block = self.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return
        geo = self.blockBoundingGeometry(block).translated(self.contentOffset())
        margin = geo.height() * 2
        if geo.top() < margin or geo.bottom() > self.viewport().height() - margin:
            old = self.textCursor()
            c = QTextCursor(block)
            self.setTextCursor(c)
            self.centerCursor()
            self.setTextCursor(old)

    def goto(self, line: int, col: int = 0):
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        c = QTextCursor(block)
        c.setPosition(block.position() + min(col, block.length() - 1))
        self.setTextCursor(c)
        self.centerCursor()
        self.setFocus()

    def _cursor_for(self, line: int, start: int, end: int) -> QTextCursor | None:
        block = self.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return None
        n = block.length() - 1
        c = QTextCursor(block)
        c.setPosition(block.position() + min(start, n))
        c.setPosition(block.position() + min(max(end, start + 1), max(n, 0)), QTextCursor.MoveMode.KeepAnchor)
        return c

    def _refresh_selections(self):
        if not self.theme:
            return
        t = self.theme
        sels = []

        def full_line(cursor, color):
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(color)
            s.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            s.cursor = cursor
            s.cursor.clearSelection()
            return s

        if not self.isReadOnly():
            sels.append(full_line(self.textCursor(), t.c("current_line")))
        if self.exec_line:
            block = self.document().findBlockByNumber(self.exec_line - 1)
            if block.isValid():
                sels.append(full_line(QTextCursor(block), t.c("exec_line")))
        for d in self.diagnostics:
            c = self._cursor_for(d.line, d.start, d.end)
            if c is None:
                continue
            s = QTextEdit.ExtraSelection()
            s.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DotLine if d.severity == NOTE
                                       else QTextCharFormat.UnderlineStyle.WaveUnderline)
            s.format.setUnderlineColor(t.c({ERROR: "error", WARNING: "warning", NOTE: "info"}[d.severity]))
            s.cursor = c
            sels.append(s)
        for c in self.find_matches:
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(QColor(t.colors["warning"]).darker(220 if t.dark else 100))
            s.format.setBackground(QColor(t.colors["selection"]))
            s.cursor = c
            sels.append(s)
        self.setExtraSelections(sels)

    def _on_cursor(self):
        self._refresh_selections()
        self.gutter.update()
        c = self.textCursor()
        self.caret_moved.emit(c.blockNumber() + 1, c.positionInBlock() + 1)

    # ----------------------------------------------------------- tooltip
    def viewportEvent(self, e):
        if e.type() == QEvent.Type.ToolTip:
            text = self._tooltip_at(e.pos())
            if text:
                QToolTip.showText(e.globalPos(), text, self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().viewportEvent(e)

    def _tooltip_at(self, pos) -> str | None:
        cur = self.cursorForPosition(pos)
        block = cur.block()
        line, col = block.blockNumber() + 1, cur.positionInBlock()
        parts = []
        for d in self.diagnostics:
            if d.line == line and d.start <= col <= d.end:
                color = {ERROR: "#e5484d", WARNING: "#e0b341", NOTE: "#4f9cff"}[d.severity]
                label = "Note" if d.severity == NOTE else d.severity.title()
                parts.append(f"<span style='color:{color}'><b>{label}:</b></span> {_esc(d.message)}")
        text = block.text()
        code = text[:find_comment(text)]
        head = first_word_start(code)
        for m in _WORD_AT.finditer(code):
            if m.start() <= col <= m.end():
                parts.append(self._word_help(m.group(0), m.start() == head))
                break
        parts = [p for p in parts if p]
        return "<br><br>".join(parts) if parts else None

    def _word_help(self, word: str, is_first: bool) -> str | None:
        up = word.upper()
        if is_first and up in INFO:
            syntax, desc, flags = INFO[up]
            forms = BY_MNEMONIC[up]
            ts = sorted({i.tstates for i in forms} | {i.tstates + i.taken_extra for i in forms})
            size = sorted({i.length for i in forms})
            return (f"<b>{_esc(syntax)}</b><br>{_esc(desc)}<br>"
                    f"<span style='color:gray'>Flags: {flags} &nbsp;|&nbsp; "
                    f"{'/'.join(map(str, size))} byte(s) &nbsp;|&nbsp; "
                    f"{'/'.join(map(str, ts))} T-states</span>")
        if is_first and up in DIRECTIVE_INFO:
            syntax, desc = DIRECTIVE_INFO[up]
            return f"<b>{_esc(syntax)}</b><br>{_esc(desc)}"
        if up in RESERVED_REGISTERS:
            names = {"M": "memory byte addressed by HL", "SP": "stack pointer", "PSW": "accumulator + flags",
                     "A": "accumulator", "B": "register B (BC pair)", "C": "register C (BC pair)",
                     "D": "register D (DE pair)", "E": "register E (DE pair)",
                     "H": "register H (HL pair)", "L": "register L (HL pair)"}
            return f"<b>{up}</b> - {names[up]}"
        return self.symbol_info(up)

    # ------------------------------------------------------------ editing
    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            text = self.textCursor().block().text()
            indent = text[:len(text) - len(text.lstrip())]
            if not indent and re.match(r"^\s*[A-Za-z_?@.][\w?@.]*\s*:\s*(;.*)?$", text):
                indent = "\t"
            super().keyPressEvent(e)
            self.insertPlainText(indent)
            return
        if e.key() == Qt.Key.Key_Backtab or (e.key() == Qt.Key.Key_Tab and self.textCursor().hasSelection()):
            self._indent(e.key() == Qt.Key.Key_Backtab)
            return
        if e.matches(QKeySequence.StandardKey.ZoomIn):
            self.zoom(1)
            return
        if e.matches(QKeySequence.StandardKey.ZoomOut):
            self.zoom(-1)
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    def _selected_blocks(self):
        c = self.textCursor()
        start, end = sorted((c.selectionStart(), c.selectionEnd()))
        doc = self.document()
        first = doc.findBlock(start)
        last = doc.findBlock(max(start, end - 1 if end > start else end))
        return first, last

    def _indent(self, back: bool):
        first, last = self._selected_blocks()
        c = self.textCursor()
        c.beginEditBlock()
        b = first
        while b.isValid():
            cc = QTextCursor(b)
            if back:
                t = b.text()
                if t.startswith("\t"):
                    cc.deleteChar()
                elif t.startswith(" "):
                    for _ in range(min(self._tab_chars, len(t) - len(t.lstrip(" ")))):
                        cc.deleteChar()
            else:
                cc.insertText("\t")
            if b == last:
                break
            b = b.next()
        c.endEditBlock()

    def toggle_comment(self):
        first, last = self._selected_blocks()
        blocks = []
        b = first
        while b.isValid():
            blocks.append(b)
            if b == last:
                break
            b = b.next()
        nonempty = [b for b in blocks if b.text().strip()]
        uncomment = bool(nonempty) and all(b.text().lstrip().startswith(";") for b in nonempty)
        c = self.textCursor()
        c.beginEditBlock()
        for b in blocks:
            if not b.text().strip():
                continue
            cc = QTextCursor(b)
            if uncomment:
                idx = b.text().index(";")
                cc.setPosition(b.position() + idx)
                n = 2 if b.text()[idx:idx + 2] == "; " else 1
                cc.setPosition(b.position() + idx + n, QTextCursor.MoveMode.KeepAnchor)
                cc.removeSelectedText()
            else:
                cc.insertText("; ")
        c.endEditBlock()

    def _indent_for_insert(self, block) -> str:
        """Indentation for a new instruction line: the line's own, else the nearest code line above, else a tab."""
        text = block.text()
        if text.strip():
            return text[:len(text) - len(text.lstrip())] or "\t"
        if text:  # a blank line that already holds the whitespace the user (or auto-indent) left there
            return text
        b = block.previous()
        while b.isValid():
            t = b.text()
            if t.strip() and not t.lstrip().startswith(";"):
                return t[:len(t) - len(t.lstrip())] or "\t"
            b = b.previous()
        return "\t"

    def insert_instruction(self, text: str, select: tuple[int, int] | None = None) -> bool:
        """Put an instruction on its own line: on the current line if that is blank, otherwise on a new
        line below it. ``select`` = (start, length) inside ``text`` is left selected so typing replaces
        the placeholder operand. One undo step. Returns False when the editor is locked (program running)."""
        if self.isReadOnly():
            return False
        cur = self.textCursor()
        block = cur.block()
        indent = self._indent_for_insert(block)
        cur.beginEditBlock()
        if block.text().strip():
            cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            cur.insertBlock()
        else:
            cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cur.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(indent + text)
        line_start = cur.block().position()
        cur.endEditBlock()
        if select:
            cur.setPosition(line_start + len(indent) + select[0])
            cur.setPosition(line_start + len(indent) + select[0] + select[1], QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cur)
        self.ensureCursorVisible()
        self.setFocus()
        return True

    # --------------------------------------------------------------- find
    def find_text(self, text: str, backwards: bool = False, case: bool = False) -> bool:
        flags = QTextDocument.FindFlag(0)
        if backwards:
            flags |= QTextDocument.FindFlag.FindBackward
        if case:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.find(text, flags):
            return True
        c = self.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End if backwards else QTextCursor.MoveOperation.Start)
        self.setTextCursor(c)
        return self.find(text, flags)

    def highlight_matches(self, text: str, case: bool = False):
        self.find_matches = []
        if text:
            flags = QTextDocument.FindFlag.FindCaseSensitively if case else QTextDocument.FindFlag(0)
            c = self.document().find(text, 0, flags)
            while not c.isNull() and len(self.find_matches) < 500:
                self.find_matches.append(c)
                c = self.document().find(text, c, flags)
        self._refresh_selections()

    def set_read_only_running(self, running: bool):
        """Lock editing while the program runs (like a debugger)."""
        self.setReadOnly(running)
        self._refresh_selections()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
