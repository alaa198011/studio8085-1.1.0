"""Regression tests: font handling must not depend on which fonts the platform happens to resolve.

The Windows CI run failed three GUI tests (panel font scaling x2, the "Store code at" box hidden in
Beginner mode) that passed on Linux. Cause: Qt's offscreen platform on Windows had an empty font
database, so nothing resolved as fixed pitch and every glyph was drawn ~2x wide by a fallback engine.
"""

import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from studio8085.app import use_system_fonts_offscreen


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_panel_fonts_are_recognised_as_monospace_without_font_resolution(qapp):
    from studio8085.ui.fontscale import _monospace
    from studio8085.ui.editor import monospace_font
    missing = QFont("No Such Font 8085")  # never resolves to a fixed-pitch font
    missing.setStyleHint(QFont.StyleHint.Monospace)
    assert _monospace(missing)
    assert _monospace(monospace_font(size=10))
    proportional = QFont("No Such Font 8085")
    proportional.setStyleHint(QFont.StyleHint.SansSerif)
    assert not _monospace(proportional)


def test_scale_monospace_uses_the_style_hint(qapp):
    from PySide6.QtWidgets import QLabel, QWidget
    from studio8085.ui.fontscale import scale_monospace
    root = QWidget()
    mono, plain = QLabel("A", root), QLabel("B", root)
    f = QFont("No Such Font 8085", 10)
    f.setStyleHint(QFont.StyleHint.Monospace)
    mono.setFont(f)
    p = QFont("No Such Font 8085", 10)
    p.setStyleHint(QFont.StyleHint.SansSerif)
    plain.setFont(p)
    scale_monospace(root, 4)
    assert mono.font().pointSize() == 14 and plain.font().pointSize() == 10
    scale_monospace(root, 0)
    assert mono.font().pointSize() == 10


@pytest.mark.parametrize("platform, expect", [("offscreen", True), ("minimal", True),
                                              ("offscreen:fontengine=freetype", True),
                                              ("windows", False), ("", False)])
def test_offscreen_fonts_on_windows(monkeypatch, tmp_path, platform, expect):
    (tmp_path / "Fonts").mkdir()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("WINDIR", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", platform)
    monkeypatch.delenv("QT_QPA_FONTDIR", raising=False)
    use_system_fonts_offscreen()
    import os
    assert (os.environ.get("QT_QPA_FONTDIR") == str(tmp_path / "Fonts")) is expect


def test_offscreen_fonts_never_override_an_explicit_dir_or_touch_linux(monkeypatch, tmp_path):
    import os
    (tmp_path / "Fonts").mkdir()
    monkeypatch.setenv("WINDIR", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("QT_QPA_FONTDIR", "/custom")
    use_system_fonts_offscreen()
    assert os.environ["QT_QPA_FONTDIR"] == "/custom"
    monkeypatch.delenv("QT_QPA_FONTDIR")
    monkeypatch.setattr(sys, "platform", "linux")  # fontconfig already finds the fonts
    use_system_fonts_offscreen()
    assert "QT_QPA_FONTDIR" not in os.environ


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only font database behaviour")
def test_the_offscreen_test_session_has_real_fonts(qapp):
    from PySide6.QtGui import QFontDatabase, QFontInfo
    from studio8085.ui.editor import monospace_font
    assert QFontDatabase.families(), "empty font database: offscreen layout would not match the real app"
    assert QFontInfo(monospace_font(size=10)).fixedPitch()
