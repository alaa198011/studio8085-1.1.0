"""Phase 2 final UX correction: responsive CPU panel dock, un-clipped caption, visible check boxes, masking
while the panel is tabbed / floated / restored."""

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontMetricsF  # noqa: E402

from test_gui import _settle, app, set_src  # noqa: E402,F401
from test_responsive_layout import _assert_workspace_ok, _ratio, _window  # noqa: E402,F401
from test_trainer_phase1_fixes import SW, _leaks, close, new_window  # noqa: E402
from test_visual_gui import IO_PROG, load, open_panel, panel_texts, step  # noqa: E402

R = Qt.DockWidgetArea.RightDockWidgetArea
L = Qt.DockWidgetArea.LeftDockWidgetArea
SIZES = [(800, 600), (1024, 600), (1280, 720), (1366, 768), (1920, 1080)]


def _dock_cpu(w, app):
    w.show_cpu_view()
    _settle(app)
    w.cpu_dock.setFloating(False)
    _settle(app)


# ----------------------------------------------------------------- caption
def test_stack_push_caption_is_complete_and_not_elided(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, "START: LXI H,1234H\n       DAD H\n       PUSH H\n       HLT\n")
        step(w, app, 3)
        cap = p.caption.text()
        assert cap.startswith("PUSH H:") and "..." not in cap and cap.endswith("low byte at SP).")
        assert "high byte at SP+1" in cap
    finally:
        close(w, app)


def test_every_instruction_caption_fits_the_scene_without_elision(app):
    """Longest explanation of every opcode, wrapped at the caption width, stays within three lines inside the
    scene and below every block of the diagram."""
    from studio8085.core.explain import explain_instruction
    from studio8085.core.opcodes import TABLE
    from studio8085.ui import cpuview
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        cap = p.caption
        longest = ""
        for ins in TABLE:
            if ins is None:
                continue
            e = explain_instruction(ins, bytes([0x12, 0x34, 0x56][: ins.length]) if ins.length > 1 else b"\x00")
            text = f"{ins.mnemonic} A,B: {e.summary}"
            if len(text) > len(longest):
                longest = text
        cap.setText(longest)
        _settle(app, 2)
        assert cap.toPlainText() == longest
        lines = cap.document().size().height() / QFontMetricsF(cap.font()).lineSpacing()
        assert lines <= 3.6, (lines, longest)
        r = cap.sceneBoundingRect()
        assert p.scene.sceneRect().contains(r), r
        nodes_bottom = max(n.sceneBoundingRect().bottom() for n in p.nodes.values())
        assert r.top() >= nodes_bottom - 1, (r.top(), nodes_bottom)
        assert cap.pos().x() == cpuview.CAPTION_X
        assert cap.textWidth() == cpuview.CAPTION_W
    finally:
        close(w, app)


# ------------------------------------------------------------- check boxes
@pytest.mark.parametrize("theme", ["Dark", "Light", "High Contrast"])
def test_cpu_panel_unchecked_boxes_are_visible(app, theme):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        w._apply_theme(theme)
        _settle(app, 4)
        bg = w.theme.colors["panel"]
        for cb in (p.anim_cb, p.reduce_cb, p.dec_cb):
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
            _settle(app, 2)
            img = cb.grab().toImage()
            bgc = QColor(img.pixel(0, 0)).name()
            worst = max(_ratio(QColor(img.pixel(x, y)).name(), bgc)
                        for x in range(min(24, img.width())) for y in range(img.height()))
            assert worst >= 3.0, (theme, cb.text(), worst, bg)
    finally:
        w._apply_theme("Dark")
        close(w, app)


# ------------------------------------------------- responsive CPU panel dock
@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("mode", ["beginner", "advanced"])
def test_docked_cpu_panel_keeps_the_editor_minimum(app, mode, size):
    w = _window(app, mode, size)
    try:
        _dock_cpu(w, app)
        for d in w.docks.values():
            d.show()
        _settle(app)
        assert not w.cpu_dock.isFloating() and w.cpu_dock.isVisible() or w.cpu_dock in [
            t for d in w.docks.values() for t in w.tabifiedDockWidgets(d)]
        _assert_workspace_ok(w, (mode, size))
        cd = w.cpu_dock
        assert cd.width() > 0 or not cd.isVisible()
        if size[0] < w.COMPACT_BELOW:
            assert w.dockWidgetArea(cd) == R
            assert any(t.objectName() == "memory" for t in w.tabifiedDockWidgets(cd))  # same tab group
    finally:
        close(w, app)


def test_cpu_panel_floats_and_redocks_correctly_when_narrow_and_wide(app):
    w = _window(app, "advanced", (800, 600))
    try:
        _dock_cpu(w, app)
        _assert_workspace_ok(w, "docked narrow")
        assert not w.cpu_dock.isHidden()
        w.cpu_dock.setFloating(True)
        _settle(app)
        assert w.cpu_dock.isFloating() and w.cpu_dock.isVisible()
        _assert_workspace_ok(w, "floating narrow")
        w.cpu_dock.setFloating(False)
        _settle(app)
        assert not w.cpu_dock.isFloating()
        w.resize(1700, 950)
        _settle(app)
        assert not w.cpu_dock.isHidden()
        _assert_workspace_ok(w, "docked wide")
        w.resize(800, 600)
        _settle(app)
        _assert_workspace_ok(w, "narrow again")
    finally:
        close(w, app)


def test_narrow_session_with_a_docked_cpu_panel_is_not_saved_as_the_users_layout(app):
    w = _window(app, "advanced", (800, 600))
    try:
        _dock_cpu(w, app)
        assert w._compact is not None
    finally:
        close(w, app)
    again = _window(app, "advanced", (1700, 950), clear=False)
    try:
        assert again.dockWidgetArea(again.docks["registers"]) == L
        _assert_workspace_ok(again, "reopen")
    finally:
        close(again, app)


def test_floating_cpu_panel_does_not_cover_the_editor_when_opened_small(app):
    """The floating panel is placed beside the window, not over the code, as far as the screen allows."""
    w = _window(app, "advanced", (1100, 700))
    try:
        w.show_cpu_view()
        _settle(app)
        assert w.cpu_dock.isFloating()
        assert w.cpu_dock.width() <= 1000 and w.cpu_dock.height() <= 760
    finally:
        close(w, app)


# ------------------------------------------------------ Experiment 1 masking
def _assert_masked(w, p):
    assert w.trainer.concealed and p.concealed
    assert [t for t in panel_texts(p) if _leaks(t, SW)] == []
    a = p.nodes["A"]
    assert a.masked


@pytest.mark.parametrize("narrow", [True, False])
def test_masking_survives_tabifying_floating_and_restoring_the_cpu_panel(app, narrow):
    w = _window(app, "advanced", (1500, 900))
    try:
        p = open_panel(w, app)
        w.kit.set_switches(SW)
        w.start_experiment()
        _settle(app)
        _assert_masked(w, p)
        w.cpu_dock.setFloating(False)
        _settle(app)
        _assert_masked(w, p)
        w.resize(800, 600)  # the dock is tabified with the others
        _settle(app)
        assert w._compact is not None
        _assert_masked(w, p)
        w.cpu_dock.raise_()
        _settle(app)
        _assert_masked(w, p)
        w.cpu_dock.setFloating(True)
        _settle(app)
        _assert_masked(w, p)
        w.cpu_dock.setFloating(False)
        w.resize(1500, 900)  # restored to the wide layout
        _settle(app)
        _assert_masked(w, p)
        if narrow:
            w.resize(800, 600)
            _settle(app)
        w.cpu_dock.hide()
        w.show_cpu_view()
        _settle(app)
        _assert_masked(w, p)
        w.cmd_step("into")  # stepping is still refused before the prediction
        _settle(app)
        _assert_masked(w, p)
        assert p._rec is None
        w.trainer.guide.predict_edit.setText(f"{SW:08b}")
        w.trainer.guide.lock_prediction()
        _settle(app)
        assert not p.concealed
    finally:
        close(w, app)


def test_cpu_panel_opened_floating_then_docked_on_a_narrow_window_joins_the_group(app):
    """Regression (screenshots): docked after the window had been made narrow, the panel stayed in a separate
    stacked group (and the layout was treated as rearranged by the user)."""
    w = _window(app, "advanced", (1366, 768))
    try:
        w.show_cpu_view()
        _settle(app)
        w.resize(800, 600)
        _settle(app)
        assert w._compact is not None
        w.cpu_dock.setFloating(False)
        _settle(app)
        w.cpu_dock.raise_()
        _settle(app)
        assert w._compact is not None and not w._user_narrow
        mates = {t.objectName() for t in w.tabifiedDockWidgets(w.cpu_dock)}
        assert {"registers", "memory", "trainer"} <= mates
        assert w.cpu_dock.isVisible()
        _assert_workspace_ok(w, "late docking")
    finally:
        close(w, app)


@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
def test_cpu_panel_docked_on_a_wide_window_is_tabbed_with_the_right_hand_docks(app, size):
    w = _window(app, "advanced", size)
    try:
        _dock_cpu(w, app)
        mates = {t.objectName() for t in w.tabifiedDockWidgets(w.cpu_dock)}
        assert "memory" in mates or "stack" in mates
        assert w.cpu_dock.isVisible() and w.dockWidgetArea(w.cpu_dock) == R
        _assert_workspace_ok(w, size)
    finally:
        close(w, app)
