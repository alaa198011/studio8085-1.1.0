"""Responsive workspace: the editor keeps a usable width whatever the window size, saved layout or display scale,
and the automatic grouping of docks on a narrow window is reversible and never hides a panel."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

SIZES = [(800, 600), (1024, 600), (1280, 720), (1366, 768), (1920, 1080)]
MODES = ["beginner", "advanced"]


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    QApplication.setOrganizationName("S85test")
    QApplication.setApplicationName("S85test")
    settings_dir = str(tmp_path_factory.mktemp("settings_responsive"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings_dir)
    return QApplication.instance() or QApplication([])


def _settle(app, n=8):
    for _ in range(n):
        app.processEvents()


def _window(app, mode, size, clear=True):
    from studio8085.ui.mainwindow import MainWindow
    if clear:
        QSettings().clear()
    QSettings().setValue("mode", mode)
    w = MainWindow()
    w.resize(*size)
    w.show()
    _settle(app)
    return w


def _close(app, w):
    w.editor.document().setModified(False)
    w.close()
    _settle(app, 2)


def _show_all(app, w):
    for d in w.docks.values():
        d.show()
    _settle(app)


def _visible_keys(w):
    return {k for k, d in w.docks.items() if not d.isHidden()}


def _assert_workspace_ok(w, what):
    from studio8085.ui.mainwindow import MainWindow
    assert w.editor.width() >= MainWindow.EDITOR_MIN_WIDTH, (what, w.editor.width())
    central = w.centralWidget().geometry()
    for k, d in w.docks.items():
        if d.isFloating() or not d.isVisible():
            continue
        assert d.width() > 0 and d.height() > 0, (what, k, d.geometry())
        assert not d.geometry().intersects(central), (what, k, d.geometry(), central)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("size", SIZES)
def test_editor_keeps_its_minimum_width_with_every_dock_shown(app, mode, size):
    w = _window(app, mode, size)
    try:
        _show_all(app, w)
        shown = _visible_keys(w)
        assert len(shown) == len(w.docks)  # nothing was closed to make room
        _assert_workspace_ok(w, (mode, size))
    finally:
        _close(app, w)


@pytest.mark.parametrize("mode", MODES)
def test_default_layout_keeps_the_minimum_at_800x600_and_nothing_is_hidden(app, mode):
    w = _window(app, mode, (800, 600))
    try:
        before = set(w.BEGINNER_DOCKS) if mode == "beginner" else set(w.docks)
        assert _visible_keys(w) == before
        _assert_workspace_ok(w, mode)
    finally:
        _close(app, w)


@pytest.mark.parametrize("mode", MODES)
def test_narrow_window_groups_docks_in_one_column_and_widening_separates_them(app, mode):
    L, R = Qt.DockWidgetArea.LeftDockWidgetArea, Qt.DockWidgetArea.RightDockWidgetArea
    w = _window(app, mode, (1500, 900))
    try:
        assert w._compact is None
        assert w.dockWidgetArea(w.docks["registers"]) == L
        shown = _visible_keys(w)
        w.resize(800, 600)
        _settle(app)
        assert w._compact is not None
        assert w.dockWidgetArea(w.docks["registers"]) == R
        assert w.docks["registers"] in w.tabifiedDockWidgets(w.docks["memory"])
        assert _visible_keys(w) == shown
        w.resize(1500, 900)
        _settle(app)
        assert w._compact is None
        assert w.dockWidgetArea(w.docks["registers"]) == L
        assert _visible_keys(w) == shown
        _assert_workspace_ok(w, mode)
    finally:
        _close(app, w)


def test_user_floating_a_dock_survives_narrowing_and_widening(app):
    w = _window(app, "advanced", (1500, 900))
    try:
        w.docks["stack"].setFloating(True)
        _settle(app)
        w.resize(800, 600)
        _settle(app)
        assert w.docks["stack"].isFloating() and not w.docks["stack"].isHidden()
        w.resize(1500, 900)
        _settle(app)
        assert w.docks["stack"].isFloating()
    finally:
        _close(app, w)


def test_user_rearranging_while_narrow_is_kept_when_widening(app):
    L = Qt.DockWidgetArea.LeftDockWidgetArea
    w = _window(app, "advanced", (1500, 900))
    try:
        w.resize(800, 600)
        _settle(app)
        assert w._compact is not None
        w.docks["trace"].setFloating(True)  # the user's own change while grouped
        _settle(app)
        w.resize(1500, 900)
        _settle(app)
        assert w._compact is None
        assert w.docks["trace"].isFloating()
        assert not w.docks["registers"].isHidden()
        assert w.dockWidgetArea(w.docks["registers"]) in (L, Qt.DockWidgetArea.RightDockWidgetArea)
    finally:
        _close(app, w)


def test_a_dock_opened_while_grouped_joins_the_group_and_is_visible(app):
    R = Qt.DockWidgetArea.RightDockWidgetArea
    w = _window(app, "advanced", (1500, 900))
    try:
        w.docks["interrupts"].hide()  # a left-hand dock the user had closed
        _settle(app)
        w.resize(800, 600)
        _settle(app)
        assert w._compact is not None and w.docks["interrupts"].isHidden()
        w.docks["interrupts"].show()
        _settle(app)
        assert w.docks["interrupts"].isVisible()
        assert w.dockWidgetArea(w.docks["interrupts"]) == R
        _assert_workspace_ok(w, "opened")
    finally:
        _close(app, w)


@pytest.mark.parametrize("mode", MODES)
def test_layout_saved_on_a_big_screen_is_clamped_on_a_small_one(app, mode):
    big = _window(app, mode, (1920, 1080))
    try:
        _show_all(app, big)
        big.resize(1920, 1080)
        _settle(app)
    finally:
        _close(app, big)  # saves geometry and state like a real session
    small = _window(app, mode, (800, 600), clear=False)
    try:
        _assert_workspace_ok(small, ("restore", mode))
        assert small.editor.width() >= small.EDITOR_MIN_WIDTH
    finally:
        _close(app, small)


@pytest.mark.parametrize("mode", MODES)
def test_the_grouping_of_a_narrow_session_is_not_saved_as_the_users_layout(app, mode):
    L = Qt.DockWidgetArea.LeftDockWidgetArea
    w = _window(app, mode, (800, 600))
    try:
        assert w._compact is not None
    finally:
        _close(app, w)
    again = _window(app, mode, (1700, 950), clear=False)
    try:
        assert again.dockWidgetArea(again.docks["registers"]) == L
        _assert_workspace_ok(again, ("reopen", mode))
    finally:
        _close(app, again)


def test_mode_switch_at_a_small_size_keeps_the_editor_usable(app):
    w = _window(app, "beginner", (800, 600))
    try:
        w._set_mode("advanced")
        _settle(app)
        _assert_workspace_ok(w, "to advanced")
        w._set_mode("beginner")
        _settle(app)
        _assert_workspace_ok(w, "to beginner")
        assert w.origin_edit.isVisible()  # "Store code at" stays in both modes
        assert w.trainer.mode() == "raw" if hasattr(w.trainer, "mode") and callable(w.trainer.mode) else True
    finally:
        _close(app, w)


_PROBE = r"""
import sys, tempfile
sys.path.insert(0, sys.argv[1])
from studio8085.app import use_system_fonts_offscreen
use_system_fonts_offscreen()
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
QApplication.setOrganizationName("S85dpi"); QApplication.setApplicationName("S85dpi")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
app = QApplication([])
QSettings().setValue("mode", sys.argv[2])
from studio8085.ui.mainwindow import MainWindow
w = MainWindow(); w.resize(int(sys.argv[3]), int(sys.argv[4])); w.show()
for d in w.docks.values():
    d.show()
for _ in range(10):
    app.processEvents()
central = w.centralWidget().geometry()
bad = [k for k, d in w.docks.items() if d.isVisible() and (d.width() <= 0 or d.geometry().intersects(central))]
print("dpr", w.devicePixelRatio(), "win", w.width(), "editor", w.editor.width(), "bad", bad)
w.editor.document().setModified(False)
sys.exit(0 if w.editor.width() >= MainWindow.EDITOR_MIN_WIDTH and not bad else 1)
"""


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("scale", ["1.25", "1.5", "2.0"])
def test_editor_minimum_holds_at_display_scales(mode, scale):
    """Logical sizes are physical / scale: 1366 x 768 and 1920 x 1080 monitors at 125 %, 150 % and 200 %."""
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    for phys in ((1366, 768), (1920, 1080)):
        w, h = round(phys[0] / float(scale)), round(phys[1] / float(scale))
        r = subprocess.run([sys.executable, "-c", _PROBE, src, mode, str(w), str(h)],
                           env=env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (phys, r.stdout + r.stderr)
        assert f"dpr {float(scale)}" in r.stdout, r.stdout


# ---------------------------------------------------------------- unchecked boxes stay visible
def _lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("theme", ["Dark", "Light", "High Contrast"])
def test_checkbox_border_has_wcag_non_text_contrast(theme):
    from studio8085.ui.themes import available_themes
    c = available_themes()[theme].colors
    for bg in ("panel", "window", "base"):
        assert _ratio(c["control_border"], c[bg]) >= 3.0, (theme, bg)
    assert _ratio(c["accent"], c["panel"]) >= 3.0


@pytest.mark.parametrize("theme", ["Dark", "Light", "High Contrast"])
def test_an_unchecked_checkbox_is_drawn_with_a_visible_box(app, theme):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QCheckBox
    from studio8085.ui.themes import apply_theme, available_themes
    t = available_themes()[theme]
    apply_theme(app, t)
    cb = QCheckBox()
    cb.setFixedSize(30, 30)
    cb.setStyleSheet(f"QCheckBox {{ background: {t.colors['panel']}; }}")
    cb.show()
    _settle(app, 3)
    img = cb.grab().toImage()
    bg = t.colors["panel"]
    worst = max(_ratio(QColor(img.pixel(x, y)).name(), bg) for x in range(img.width()) for y in range(img.height()))
    cb.close()
    assert worst >= 3.0, (theme, worst)
    from studio8085.ui.themes import apply_theme as _a  # restore the default look for other tests
    _a(app, available_themes()["Dark"])
