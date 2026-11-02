"""Colour themes. Each theme is a palette dict that is poured into the QSS
template (``styles/theme.qss``). Extra themes can be dropped into the user's
config folder as ``*.json`` files (same keys as below; missing keys fall back to
the Dark theme)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

SYNTAX_TOKENS = {
    "mnemonic": "Instructions (MOV, ADD...)",
    "directive": "Directives (ORG, DB...)",
    "register": "Registers (A, B, HL, SP...)",
    "number": "Numbers",
    "label": "Label definitions",
    "symbol": "Label references",
    "string": "Strings and characters",
    "comment": "Comments",
    "marker": "Auto-breakpoint (;@)",
}

DARK = {
    "name": "Dark",
    "dark": True,
    "window": "#1b1f27", "panel": "#232833", "base": "#1a1d23", "alt_base": "#1f232b",
    "text": "#d7dce5", "text_dim": "#8a93a6", "border": "#323946", "accent": "#4f9cff",
    "accent_text": "#08111f", "hover": "#2c3340", "selection": "#264f78",
    "gutter_bg": "#171a20", "gutter_text": "#7c869a", "current_line": "#212733",
    "exec_line": "#4a4212", "exec_arrow": "#ffd34d", "bp": "#e5484d",
    "error": "#f0616d", "warning": "#e0b341", "ok": "#3fb97c", "info": "#4f9cff",
    "heat_read": "#3b82f6", "heat_write": "#f97316", "heat_exec": "#22c55e",
    "syntax": {
        "mnemonic": "#82aaff|b", "directive": "#c792ea|b", "register": "#f78c6c",
        "number": "#ffcb6b", "label": "#c3e88d|b", "symbol": "#89ddff",
        "string": "#ecc48d", "comment": "#748c8c|i", "marker": "#ff5370|b",
    },
}

LIGHT = {
    "name": "Light",
    "dark": False,
    "window": "#f3f4f6", "panel": "#ffffff", "base": "#ffffff", "alt_base": "#f7f8fa",
    "text": "#1f2430", "text_dim": "#666d7a", "border": "#d5d9e0", "accent": "#2563eb",
    "accent_text": "#ffffff", "hover": "#e8ecf3", "selection": "#cfe2ff",
    "gutter_bg": "#f1f3f6", "gutter_text": "#606c82", "current_line": "#f2f6ff",
    "exec_line": "#fff3b0", "exec_arrow": "#ae7b00", "bp": "#d92d3a",
    "error": "#d92d3a", "warning": "#9d681b", "ok": "#167c4f", "info": "#2563eb",
    "heat_read": "#2563eb", "heat_write": "#ea580c", "heat_exec": "#16a34a",
    "syntax": {
        "mnemonic": "#1d4ed8|b", "directive": "#7c3aed|b", "register": "#c2410c",
        "number": "#b45309", "label": "#15803d|b", "symbol": "#0e7490",
        "string": "#a16207", "comment": "#6b7280|i", "marker": "#be123c|b",
    },
}


HIGH_CONTRAST = {
    "name": "High Contrast",
    "dark": True,
    "window": "#000000", "panel": "#0b0b0b", "base": "#000000", "alt_base": "#111111",
    "text": "#ffffff", "text_dim": "#cfcfcf", "border": "#8c8c8c", "accent": "#ffd400",
    "accent_text": "#000000", "hover": "#262626", "selection": "#1a44c2",
    "gutter_bg": "#000000", "gutter_text": "#bdbdbd", "current_line": "#1c1c1c",
    "exec_line": "#5c4a00", "exec_arrow": "#ffd400", "bp": "#ff5c5c",
    "error": "#ff7b7b", "warning": "#ffd400", "ok": "#5cff9d", "info": "#7cc4ff",
    "heat_read": "#4da3ff", "heat_write": "#ff9f1c", "heat_exec": "#5cff9d",
    "syntax": {
        "mnemonic": "#8cc8ff|b", "directive": "#ff9dff|b", "register": "#ffb870",
        "number": "#ffff7a", "label": "#a0ff9f|b", "symbol": "#7cffff",
        "string": "#ffd2a8", "comment": "#c8c8c8|i", "marker": "#ff7b7b|b",
    },
}


@dataclass
class Theme:
    name: str
    dark: bool
    colors: dict[str, str]
    syntax: dict[str, str] = field(default_factory=dict)

    def c(self, key: str) -> QColor:
        return QColor(self.colors[key])

    def syntax_format(self, token: str, overrides: dict[str, str] | None = None):
        spec = (overrides or {}).get(token) or self.syntax[token]
        parts = spec.split("|")
        return QColor(parts[0]), "b" in parts[1:], "i" in parts[1:]


def _theme_from_dict(d: dict, base: dict = DARK) -> Theme:
    colors = {k: v for k, v in base.items() if k not in ("name", "dark", "syntax")}
    colors.update({k: v for k, v in d.items() if k not in ("name", "dark", "syntax")})
    syntax = dict(base["syntax"])
    syntax.update(d.get("syntax", {}))
    return Theme(d.get("name", "Custom"), bool(d.get("dark", base is DARK)), colors, syntax)


def user_theme_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(base) / "themes"


def available_themes() -> dict[str, Theme]:
    themes = {"Dark": _theme_from_dict(DARK), "Light": _theme_from_dict(LIGHT, LIGHT),
              "High Contrast": _theme_from_dict(HIGH_CONTRAST)}
    folder = user_theme_dir()
    if folder.is_dir():
        for f in sorted(folder.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                d.setdefault("name", f.stem)
                themes[d["name"]] = _theme_from_dict(d, DARK if d.get("dark", True) else LIGHT)
            except (OSError, ValueError, KeyError):
                continue
    return themes


def _qss_template() -> str:
    return resources.files("studio8085.ui").joinpath("styles/theme.qss").read_text(encoding="utf-8")


def stylesheet(theme: Theme) -> str:
    qss = _qss_template()
    for key, value in theme.colors.items():
        qss = qss.replace(f"@{key}@", value)
    return qss


def apply_theme(app: QApplication, theme: Theme, font: QFont | None = None):
    app.setStyle("Fusion")
    pal = QPalette()
    c = theme.c
    for role, key in [
        (QPalette.ColorRole.Window, "window"), (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Base, "base"), (QPalette.ColorRole.AlternateBase, "alt_base"),
        (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "panel"),
        (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "selection"),
        (QPalette.ColorRole.HighlightedText, "text"), (QPalette.ColorRole.ToolTipBase, "panel"),
        (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.Link, "accent"),
        (QPalette.ColorRole.PlaceholderText, "text_dim"),
    ]:
        pal.setColor(role, c(key))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, c("text_dim"))
    app.setPalette(pal)
    if font is not None:
        app.setFont(font)
    app.setStyleSheet(stylesheet(theme))


def overrides_from_settings(raw: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in raw.items() if k in SYNTAX_TOKENS and v}
