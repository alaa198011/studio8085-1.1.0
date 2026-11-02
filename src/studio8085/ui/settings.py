"""User preferences (stored with QSettings) and the Preferences dialog."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFontComboBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from .themes import SYNTAX_TOKENS, Theme

DEFAULTS = {
    "theme": "Dark", "font_family": "", "font_size": 11, "tab_width": 8,
    "origin": 0, "ac_borrow": False, "clock_mhz": 3.0, "max_instr": 0,
    "stop_idle": True, "live_diag": True, "speed": 0, "recent": [],
    "mode": "beginner", "compat": "off", "ui_font_size": 0, "predict_first": False,
    "palette_scope": "Essential", "keep_memory": True,
}


class Prefs:
    def __init__(self):
        self.q = QSettings()

    def get(self, key):
        d = DEFAULTS[key]
        v = self.q.value(key, d)
        if isinstance(d, bool):
            return v if isinstance(v, bool) else str(v).lower() in ("true", "1")
        if isinstance(d, int):
            try:
                return int(v)
            except (TypeError, ValueError):
                return d
        if isinstance(d, float):
            try:
                return float(v)
            except (TypeError, ValueError):
                return d
        if isinstance(d, list):
            if v is None:
                return []
            return list(v) if isinstance(v, (list, tuple)) else [v]
        return str(v) if v is not None else d

    def set(self, key, value):
        self.q.setValue(key, value)

    def syntax_overrides(self, dark: bool) -> dict[str, str]:
        group = f"syntax/{'dark' if dark else 'light'}"
        out = {}
        for tok in SYNTAX_TOKENS:
            v = self.q.value(f"{group}/{tok}")
            if v:
                out[tok] = str(v)
        return out

    def set_syntax_override(self, dark: bool, token: str, spec: str | None):
        key = f"syntax/{'dark' if dark else 'light'}/{token}"
        if spec:
            self.q.setValue(key, spec)
        else:
            self.q.remove(key)


class _ColorRow:
    def __init__(self, token: str, theme: Theme, override: str | None):
        self.token = token
        spec = override or theme.syntax[token]
        parts = spec.split("|")
        self.color = QColor(parts[0])
        self.default = theme.syntax[token]
        self.button = QPushButton()
        self.button.setFixedWidth(70)
        self.bold = QCheckBox("Bold")
        self.italic = QCheckBox("Italic")
        self.bold.setChecked("b" in parts[1:])
        self.italic.setChecked("i" in parts[1:])
        self.button.clicked.connect(self.pick)
        self._paint()

    def _paint(self):
        self.button.setText(self.color.name())
        fg = "#000" if self.color.lightness() > 140 else "#fff"
        self.button.setStyleSheet(f"background:{self.color.name()};color:{fg};border-radius:5px;")

    def pick(self):
        c = QColorDialog.getColor(self.color, self.button, "Choose colour")
        if c.isValid():
            self.color = c
            self._paint()

    def reset(self):
        parts = self.default.split("|")
        self.color = QColor(parts[0])
        self.bold.setChecked("b" in parts[1:])
        self.italic.setChecked("i" in parts[1:])
        self._paint()

    def spec(self) -> str:
        return self.color.name() + ("|b" if self.bold.isChecked() else "") + ("|i" if self.italic.isChecked() else "")


class PreferencesDialog(QDialog):
    def __init__(self, prefs: Prefs, themes: dict[str, Theme], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.prefs = prefs
        self.themes = themes
        self.setMinimumWidth(470)
        tabs = QTabWidget()

        # --- appearance
        ap = QWidget()
        f = QFormLayout(ap)
        self.theme = QComboBox()
        self.theme.addItems(list(themes))
        self.theme.setCurrentText(prefs.get("theme"))
        self.font = QFontComboBox()
        self.font.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        fam = prefs.get("font_family")
        if fam:
            self.font.setCurrentFont(QFontDatabase.font(fam, "", 11))
        self.use_default_font = QCheckBox("Use the system monospace font")
        self.use_default_font.setChecked(not fam)
        self.font.setEnabled(bool(fam))
        self.use_default_font.toggled.connect(lambda on: self.font.setEnabled(not on))
        self.size = QSpinBox()
        self.size.setRange(6, 72)
        self.size.setValue(prefs.get("font_size"))
        self.tab = QSpinBox()
        self.tab.setRange(1, 16)
        self.tab.setValue(prefs.get("tab_width"))
        f.addRow("Theme", self.theme)
        f.addRow("Editor font", self.font)
        f.addRow("", self.use_default_font)
        f.addRow("Font size", self.size)
        f.addRow("Tab width", self.tab)
        self.ui_size = QSpinBox()
        self.ui_size.setRange(0, 24)
        self.ui_size.setSpecialValueText("system default")
        self.ui_size.setSuffix(" pt")
        self.ui_size.setValue(prefs.get("ui_font_size"))
        self.ui_size.setToolTip("Size of menus, panels and tables (the editor has its own size above)")
        f.addRow("Interface font size", self.ui_size)
        tabs.addTab(ap, "Appearance")

        # --- syntax colours
        sx = QWidget()
        v = QVBoxLayout(sx)
        self.syntax_theme = themes.get(prefs.get("theme"), next(iter(themes.values())))
        v.addWidget(QLabel(f"Colours for the <b>{self.syntax_theme.name}</b> theme:"))
        self.rows: list[_ColorRow] = []
        over = prefs.syntax_overrides(self.syntax_theme.dark)
        for tok, label in SYNTAX_TOKENS.items():
            row = _ColorRow(tok, self.syntax_theme, over.get(tok))
            self.rows.append(row)
            h = QHBoxLayout()
            h.addWidget(QLabel(label), 1)
            h.addWidget(row.button)
            h.addWidget(row.bold)
            h.addWidget(row.italic)
            v.addLayout(h)
        reset = QPushButton("Reset to theme defaults")
        reset.clicked.connect(lambda: [r.reset() for r in self.rows])
        v.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        v.addStretch(1)
        tabs.addTab(sx, "Syntax colours")

        # --- simulation
        sm = QWidget()
        f2 = QFormLayout(sm)
        self.origin = QLineEdit(f"{prefs.get('origin'):04X}")
        self.origin.setMaximumWidth(80)
        self.clock = QDoubleSpinBox()
        self.clock.setRange(0.1, 6.25)
        self.clock.setDecimals(2)
        self.clock.setSuffix(" MHz")
        self.clock.setValue(prefs.get("clock_mhz"))
        self.max_instr = QSpinBox()
        self.max_instr.setRange(0, 2_000_000_000)
        self.max_instr.setSpecialValueText("unlimited")
        self.max_instr.setValue(prefs.get("max_instr"))
        self.idle = QCheckBox("Stop when a program jumps to itself with interrupts disabled")
        self.idle.setChecked(prefs.get("stop_idle"))
        self.borrow = QCheckBox("Textbook AC for subtraction (borrow) instead of 8085 hardware (carry)")
        self.borrow.setChecked(prefs.get("ac_borrow"))
        self.borrow.setToolTip("The 8085 ALU subtracts by adding the complement, so AC is the carry out of bit 3.\n"
                               "Many textbooks describe AC after SUB as a borrow, which is the opposite.")
        self.keep = QCheckBox("Keep memory contents when assembling, running and restarting")
        self.keep.setChecked(prefs.get("keep_memory"))
        self.keep.setToolTip("On: values you type into memory, and results an earlier run left there, survive. Assembling writes only the\n"
                             "program's own code and initialised data (DB, DW, DS with a fill value); space reserved with a plain\n"
                             "DS is left as it is, and the previous version's code is removed.\n"
                             "Off: every assemble wipes all of memory first, so every run starts from the same clean state.\n"
                             "Debug > Clear Memory and Heat wipes memory whenever you want.")
        self.live = QCheckBox("Check the source while typing")
        self.live.setChecked(prefs.get("live_diag"))
        self.compat = QComboBox()
        self.compat.addItem("Studio8085 syntax (no compatibility checks)", "off")
        self.compat.addItem("Studio8085 syntax + notes where GNUSim8085 would differ", "note")
        self.compat.addItem("GNUSim8085-compatible: differences are errors", "strict")
        self.compat.setCurrentIndex(max(0, self.compat.findData(prefs.get("compat"))))
        self.compat.setToolTip("For authors who want programs that run in both tools. See docs/COMPATIBILITY.md.")
        f2.addRow("Assembler syntax", self.compat)
        f2.addRow("Default load address (hex)", self.origin)
        f2.addRow("CPU clock", self.clock)
        f2.addRow("Instruction limit", self.max_instr)
        f2.addRow("", self.idle)
        f2.addRow("", self.borrow)
        f2.addRow("", self.keep)
        f2.addRow("", self.live)
        tabs.addTab(sm, "Simulation")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    def save(self):
        p = self.prefs
        p.set("theme", self.theme.currentText())
        p.set("font_family", "" if self.use_default_font.isChecked() else self.font.currentFont().family())
        p.set("font_size", self.size.value())
        p.set("tab_width", self.tab.value())
        try:
            p.set("origin", int(self.origin.text().strip().lower().removesuffix("h"), 16) & 0xFFFF)
        except ValueError:
            pass
        p.set("ui_font_size", self.ui_size.value())
        p.set("compat", self.compat.currentData())
        p.set("clock_mhz", self.clock.value())
        p.set("max_instr", self.max_instr.value())
        p.set("stop_idle", self.idle.isChecked())
        p.set("ac_borrow", self.borrow.isChecked())
        p.set("keep_memory", self.keep.isChecked())
        p.set("live_diag", self.live.isChecked())
        for r in self.rows:
            spec = r.spec()
            p.set_syntax_override(self.syntax_theme.dark, r.token, None if spec == r.default else spec)
