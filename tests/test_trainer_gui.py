"""Phase 1 GUI tests: the "Virtual 8085 Trainer Kit" dock, its synchronisation with the debugger, the
Experiment 1 guide, layouts (small screens, saved layouts, both modes, high DPI) and the three themes."""

import base64
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QByteArray, QPoint, QRect, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QRegion  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QMenu, QWidget  # noqa: E402

from test_gui import _on_screen, _settle, app, make_window, set_src, wait_until  # noqa: E402,F401

HERE = Path(__file__).resolve().parent
EXPERIMENT_1 = "START: IN 00H\n       OUT 01H\n       HLT\n"


@pytest.fixture
def win(app):
    w = make_window(app, "advanced")
    w.resize(1400, 900)
    w.show()
    _settle(app, 3)
    yield w
    w.editor.document().setModified(False)
    w.close()
    _settle(app, 2)


def run_program(win, app, src):
    set_src(win, src)
    assert win._assemble_and_load()
    win.cmd_run()
    wait_until(app, lambda: win.state in ("halted", "paused"))


def leds_shown(win):
    return sum(1 << lamp.bit for lamp in win.trainer.leds if lamp.on)


# ------------------------------------------------------------------ the dock
def test_dock_is_titled_and_reachable_from_the_view_and_lab_menus(win, app):
    from studio8085.ui.mainwindow import DockScroll
    d = win.docks["trainer"]
    assert d.windowTitle() == "Virtual 8085 Trainer Kit"
    assert isinstance(d.widget(), DockScroll) and d.widget().widget() is win.trainer
    menus = {m.title(): m for m in win.menuBar().findChildren(QMenu)}
    assert d.toggleViewAction() in menus["&View"].actions()
    lab = [a.text() for a in menus["&Lab"].actions()]
    assert any("Experiment 1" in t for t in lab) and any("Trainer Kit" in t for t in lab)
    assert d.isVisible() and win.dockWidgetArea(d) == Qt.DockWidgetArea.RightDockWidgetArea
    assert d in win.tabifiedDockWidgets(win.docks["io"])  # a tab next to I/O Ports
    assert not win.docks["stack"].visibleRegion().isEmpty()  # Stack is still the front tab


def test_beginner_mode_hides_it_until_asked_and_then_docks_it(app):
    w = make_window(app, "beginner")
    try:
        w.resize(1280, 720)
        w.show()
        _settle(app)
        assert not w.docks["trainer"].isVisible()
        w.a_trainer_show.trigger()
        _settle(app)
        d = w.docks["trainer"]
        assert d.isVisible() and not d.isFloating() and _on_screen(w, d)
        assert d in w.tabifiedDockWidgets(w.docks["explain"])
        assert (w.width(), w.height()) == (1280, 720)
    finally:
        w.editor.document().setModified(False)
        w.close()
        _settle(app, 2)


# ---------------------------------------------------------------- switches
def test_switches_toggle_with_the_mouse_and_mirror_into_the_io_table(win, app):
    sw7, sw0 = win.trainer.switches[0], win.trainer.switches[7]
    assert (sw7.bit, sw0.bit) == (7, 0)  # MSB on the left
    win.show_trainer()
    _settle(app)
    win.docks["trainer"].widget().ensureWidgetVisible(sw7)
    QTest.mouseClick(sw7, Qt.MouseButton.LeftButton)
    QTest.mouseClick(sw0, Qt.MouseButton.LeftButton)
    assert win.kit.switches.value == 0x81 and win.machine.cpu.io[0] == 0x81
    assert "1000 0001b = 81h" in win.trainer.sw_value.text()
    QTest.mouseClick(sw7, Qt.MouseButton.LeftButton)
    assert win.kit.switches.value == 0x01


def test_switches_work_from_the_keyboard_and_are_accessible(win, app):
    win.show_trainer()
    _settle(app)
    s = win.trainer.switches
    s[0].setFocus()
    _settle(app)
    assert s[0].hasFocus()
    QTest.keyClick(s[0], Qt.Key.Key_Space)
    assert win.kit.switches.value == 0x80
    QTest.keyClick(s[0], Qt.Key.Key_Right)
    assert s[1].hasFocus()
    QTest.keyClick(s[1], Qt.Key.Key_Return)
    assert win.kit.switches.value == 0xC0
    QTest.keyClick(s[1], Qt.Key.Key_Left)
    assert s[0].hasFocus()
    # Tab walks SW7 -> SW0 in order
    order = [s[0]]
    for _ in range(7):
        order[-1].focusNextChild()
        _settle(app, 1)
        order.append(QApplication_focus())
    assert order == s
    for sw in s:
        assert sw.accessibleName() == f"SW{sw.bit}" and sw.focusPolicy() == Qt.FocusPolicy.StrongFocus
        assert sw.isCheckable() and f"bit {sw.bit}" in sw.toolTip() and "IN 00H" in sw.toolTip()
    assert "on, 1" in s[0].accessibleDescription() and "off, 0" in s[2].accessibleDescription()
    for lamp in win.trainer.leds:
        assert lamp.accessibleName() == f"LED{lamp.bit}" and "OUT 01H" in lamp.toolTip()


def QApplication_focus():
    from PySide6.QtWidgets import QApplication
    return QApplication.focusWidget()


def test_switch_positions_survive_cpu_reset_reload_and_mode_switch(win, app):
    win.kit.set_switches(0x3C)
    win.trainer.refresh()
    set_src(win, EXPERIMENT_1)
    assert win._assemble_and_load()
    win.cmd_restart()
    win._set_mode("beginner")
    win._set_mode("advanced")
    _settle(app)
    assert win.kit.switches.value == 0x3C
    assert [s.isChecked() for s in win.trainer.switches] == [False, False, True, True, True, True, False, False]
    win.trainer_reset()  # only an explicit hardware reset moves them
    assert win.kit.switches.value == 0 and not any(s.isChecked() for s in win.trainer.switches)


# -------------------------------------------------- LEDs / display sync
def test_leds_follow_out_when_stepping_and_never_touch_registers(win, app):
    win.show_trainer()
    win.kit.set_switches(0xA5)
    set_src(win, EXPERIMENT_1)
    win.cmd_step("into")  # assembles
    assert win.state == "ready" and leds_shown(win) == 0 and not win.kit.leds.written
    win.cmd_step("into")  # IN 00H
    assert win.machine.cpu.a == 0xA5 and leds_shown(win) == 0
    flags = win.machine.cpu.f
    win.cmd_step("into")  # OUT 01H
    assert leds_shown(win) == 0xA5 == win.kit.leds.value
    assert "1010 0101b = A5h" in win.trainer.led_value.text()
    assert win.machine.cpu.f == flags and win.machine.cpu.a == 0xA5


def test_leds_update_while_running_without_per_instruction_repaints(win, app):
    win.show_trainer()
    win.speed.setCurrentIndex(0)  # max speed
    set_src(win, "loop: in 00h\n out 01h\n jmp loop\n")
    calls = []
    orig = win.trainer.refresh
    win.trainer.refresh = lambda: (calls.append(win.machine.cpu.icount), orig())[1]
    try:
        win.kit.set_switches(0x0F)
        win.cmd_run()
        wait_until(app, lambda: leds_shown(win) == 0x0F and win.state == "running")
        win.kit.set_switches(0xF0)  # flip the switches while it runs, as on a real kit
        wait_until(app, lambda: leds_shown(win) == 0xF0 and win.state == "running")
        t0 = time.time()
        wait_until(app, lambda: time.time() - t0 > 0.5)
        win.cmd_pause()
        assert win.state == "paused" and leds_shown(win) == 0xF0
        icount = win.machine.cpu.icount
        assert len(calls) < icount / 100  # refreshed per batch, not per instruction
        win.kit.set_switches(0x55)
        win.cmd_run()  # resume
        wait_until(app, lambda: leds_shown(win) == 0x55)
        win.cmd_stop()
        assert win.state == "idle"
        assert leds_shown(win) == 0x55  # stop keeps the last latched value until the next load
    finally:
        win.trainer.refresh = orig


def test_breakpoint_stop_shows_a_before_out_and_leds_after(win, app):
    win.show_trainer()
    win.kit.set_switches(0x96)
    set_src(win, EXPERIMENT_1)
    win.editor.toggle_breakpoint(2)  # on OUT 01H
    assert win._assemble_and_load()
    win.cmd_run()
    wait_until(app, lambda: win.state == "paused")
    assert "Breakpoint" in win.msg.text() and win.machine.cpu.a == 0x96 and leds_shown(win) == 0
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    assert leds_shown(win) == 0x96


def test_repeated_runs_leave_no_stale_state(win, app):
    win.show_trainer()
    for value in (0xFF, 0x00, 0x5A, 0x5A):
        win.kit.set_switches(value)
        run_program(win, app, EXPERIMENT_1)
        assert win.state == "halted" and win.kit.leds.value == value == leds_shown(win)
        assert win.kit.leds.writes == 1  # the latch was cleared by the reload, not accumulated
        win.cmd_restart()
        assert not win.kit.leds.written and leds_shown(win) == 0 and "no OUT yet" in win.trainer.led_value.text()


def test_seven_segment_raw_and_hex_modes(win, app):
    win.show_trainer()
    run_program(win, app, "mvi a,0F6h\nout 02h\nhlt")
    assert win.trainer.digit.lit == set("bcefgp")  # H.
    before = (tuple(win.machine.cpu.regs), win.machine.cpu.f, bytes(win.machine.cpu.io), win.machine.cpu.icount)
    win.trainer.mode.setCurrentIndex(win.trainer.mode.findData("hex"))
    assert win.kit.display.mode == "hex" and win.prefs.get("trainer_seg_mode") == "hex"
    assert win.trainer.digit.lit == set("acdefg") and "shows: 6" in win.trainer.seg_value.text()
    assert (tuple(win.machine.cpu.regs), win.machine.cpu.f, bytes(win.machine.cpu.io), win.machine.cpu.icount) == before
    win.trainer.mode.setCurrentIndex(0)
    assert win.kit.display.mode == "raw"


def test_lab_programs_load_and_run(win, app):
    names = [n for n, _ in win.TRAINER_EXAMPLES]
    win.kit.set_switches(0x2A)
    win._open_trainer_example(names[0])
    assert win.live.ok and win.kit.display.mode == "raw"
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    assert win.kit.leds.value == 0x2A == win.machine.cpu.a
    win._open_trainer_example(names[1])
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    assert win.kit.display.value == 0xF6 and win.kit.leds.value == 0xF6 and win.trainer.digit.lit == set("bcefgp")
    win._open_trainer_example(names[2])  # says "@display: hex"
    assert win.kit.display.mode == "hex"
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    assert win.kit.display.glyph() == "A" and win.trainer.digit.lit == set("abcefg")


# ---------------------------------------------------- I/O table interplay
def test_io_table_edit_on_the_switch_port_moves_the_switches(win, app):
    m = win.io.model
    m.setData(m.index(0x00, 1), "C3")
    assert win.kit.switches.value == 0xC3 and win.trainer.switches[0].isChecked()
    m.setData(m.index(0x10, 1), "AB")  # any other port: as before
    assert win.machine.cpu.io[0x10] == 0xAB and win.kit.switches.value == 0xC3


def test_existing_io_behaviour_is_unchanged_on_other_ports(win, app):
    run_program(win, app, "mvi a,5\nout 05h\nin 07h\nhlt")
    log = win.output.log.toPlainText()
    assert "OUT 05h <- 05h" in log and win.machine.cpu.io[5] == 5 and not win.kit.leds.written


def test_disconnecting_restores_the_plain_io_ports(win, app):
    win.show_trainer()
    record = win.kit.bus._prev_out
    win.trainer.connected.setChecked(False)
    assert not win.kit.enabled and win.prefs.get("trainer_enabled") is False
    assert win.machine.cpu.on_out == record and win.machine.cpu.on_in is None
    assert not win.trainer.led_box.isEnabled()
    win.kit.switches.set_value(0x11)
    win.machine.cpu.io[0] = 0x44  # typed in the I/O Ports table
    run_program(win, app, EXPERIMENT_1)
    assert win.machine.cpu.a == 0x44 and win.machine.cpu.io[1] == 0x44 and not win.kit.leds.written
    win.io.model.setData(win.io.model.index(0, 1), "22")
    assert win.kit.switches.value == 0x11  # not connected: the table does not move the switches
    win.trainer.connected.setChecked(True)
    assert win.kit.enabled and win.machine.cpu.io[0] == 0x11


# ---------------------------------------------------------- port mapping
def test_port_mapping_dialog_validates_and_remaps(win, app):
    from studio8085.core.peripherals import PortMap
    from studio8085.ui.trainer import PortMapDialog
    dlg = PortMapDialog(win.kit.ports, win)
    ok = dlg.buttons.button(dlg.buttons.StandardButton.Ok)
    assert ok.isEnabled() and dlg.error.isHidden()
    dlg.edits["leds_out"].setText("02")
    assert not ok.isEnabled() and "Port conflict" in dlg.error.text() and "OUT 02H" in dlg.error.text()
    dlg.edits["leds_out"].setText("1G")
    assert not ok.isEnabled() and "not a port" in dlg.error.text()
    dlg.edits["leds_out"].setText("100")
    assert not ok.isEnabled()
    dlg.edits["leds_out"].setText("01")  # an IN and an OUT may share a number
    dlg.edits["switches_in"].setText("01")
    assert ok.isEnabled()
    dlg.close()
    win.kit.set_ports(PortMap(0x10, 0x20, 0x30))
    win.trainer.sync_from_kit()
    assert win.trainer.sw_box.title() == "Switches - IN 10H" and "OUT 20H" in win.trainer.leds[0].toolTip()
    win.kit.set_switches(0x77)
    run_program(win, app, "in 10h\nout 20h\nout 30h\nhlt")
    assert win.kit.leds.value == 0x77 == win.kit.display.value


def test_saved_port_settings_are_used_and_bad_ones_fall_back(app):
    QSettings().clear()
    QSettings().setValue("trainer_switch_port", 0x40)
    QSettings().setValue("trainer_led_port", 0x41)
    QSettings().setValue("trainer_seg_port", 0x41)  # conflict: fall back to the defaults
    from studio8085.ui.mainwindow import MainWindow
    w = MainWindow()
    try:
        assert w.kit.ports.leds_out == 0x01 and w.kit.ports.switches_in == 0x00
    finally:
        w.editor.document().setModified(False)
        w.close()
    QSettings().setValue("trainer_seg_port", 0x42)
    w = MainWindow()
    try:
        assert (w.kit.ports.switches_in, w.kit.ports.leds_out, w.kit.ports.seven_segment_out) == (0x40, 0x41, 0x42)
    finally:
        w.editor.document().setModified(False)
        w.close()
        QSettings().clear()


# ------------------------------------------------------------- Experiment 1
def test_experiment_1_hides_the_answer_until_a_prediction(win, app):
    g = win.trainer.guide
    win.kit.set_switches(0b1100_0011)
    win.start_experiment()
    _settle(app)
    assert g.isVisible() and g.stage == 0
    secret = ("1100 0011", "C3h")
    texts = lambda: g.text.text() + win.trainer.sw_value.text()  # noqa: E731
    assert not any(s in texts() for s in secret)
    g.next_btn.click()
    assert g.stage == 1 and not g.load_btn.isVisible() and not g.next_btn.isEnabled()
    g.next_stage()  # cannot skip the prediction
    assert g.stage == 1 and not any(s in texts() for s in secret)
    g.predict_edit.setText("12345678")
    g.lock_btn.click()
    assert g.prediction is None and g.stage == 1
    g.predict_edit.setText("11000010")  # a wrong prediction (bit 0 missed)
    g.lock_btn.click()
    assert g.prediction == 0xC2 and g.stage == 2 and "1100 0011b = C3h" in win.trainer.sw_value.text()
    g.load_btn.click()
    assert win.state == "ready" and g.stage == 3 and "E1_read_switches" in win.windowTitle()
    win.cmd_step("into")
    assert g.stage == 4 and g.observed_a == win.machine.cpu.a == 0xC3
    win.cmd_step("into")
    assert g.stage == 7 and g.observed_leds == win.kit.leds.value == 0xC3
    assert "Not quite" in g.text.text() and "LED0 differ" in g.text.text()


def test_experiment_1_compares_with_the_real_cpu_not_a_constant(win, app):
    g = win.trainer.guide
    win.start_experiment()
    win.kit.set_switches(0x24)
    g.next_stage()
    g.predict_edit.setText("24h")
    g.lock_prediction()
    g.load_btn.click()
    win.machine.cpu.mem.data[win.machine.cpu.pc + 1] = 0x07  # patch IN 00H into IN 07H...
    win.machine.cpu.io[7] = 0x99  # ...which no device owns
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    assert g.observed_leds == 0x99 and "Not quite" in g.text.text()  # the CPU said 99h, so the guide does too


def test_experiment_1_help_reveals_on_request_and_start_over(win, app):
    g = win.trainer.guide
    win.kit.set_switches(0x81)
    win.start_experiment()
    g.next_stage()
    g.help_btn.click()
    assert g.helped and g.stage == 2 and "1000 0001b (81h)" in g.text.text()
    g.load_btn.click()
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    assert g.stage == 7 and "you asked for help" in g.text.text()
    g.restart_btn.click()
    assert g.stage == 0 and g.prediction is None and "????" in win.trainer.sw_value.text()
    assert win.kit.switches.value == 0x81  # starting over does not touch the hardware
    win.trainer.hide_guide()
    assert "81h" in win.trainer.sw_value.text()


def test_prediction_parser():
    from studio8085.ui.trainer import ExperimentGuide
    p = ExperimentGuide.parse_prediction
    assert p("10100101") == p("1010 0101") == p("1010_0101b") == p("A5h") == p("0xA5") == 0xA5
    assert p("") is None and p("A5") is None and p("1010") is None and p("2G h") is None


# --------------------------------------------------------- themes & painting
def _contrast(a, b):
    from PySide6.QtGui import QColor

    def lum(c):
        c = QColor(c)
        ch = []
        for v in (c.redF(), c.greenF(), c.blueF()):
            ch.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("theme", ["Dark", "Light", "High Contrast"])
def test_each_theme_paints_lit_and_dark_parts_with_enough_contrast(win, app, theme):
    from PySide6.QtGui import QColor
    win._apply_theme(theme)
    win.show_trainer()
    run_program(win, app, "mvi a,81h\nout 01h\nmvi a,08h\nout 02h\nhlt")  # LED7, LED0 and segment d
    _settle(app)
    c = win.theme.colors
    assert _contrast(c["led_on"], c["panel"]) >= 3.0 and _contrast(c["led_on"], c["led_off"]) >= 3.0
    assert _contrast(c["seg_on"], c["seg_bg"]) >= 4.5 and _contrast(c["seg_on"], c["seg_off"]) >= 3.0
    for lamp, lit in ((win.trainer.leds[0], True), (win.trainer.leds[1], False)):
        img = lamp.grab().toImage()
        px = QColor(img.pixel(img.width() // 2, img.height() // 2))
        want = QColor(c["led_on"] if lit else c["led_off"])
        assert max(abs(px.red() - want.red()), abs(px.green() - want.green()), abs(px.blue() - want.blue())) < 40, \
            (theme, lit, px.name(), want.name())
    assert win.trainer.digit.lit == {"d"} and not win.trainer.grab().isNull()
    for sw in win.trainer.switches:
        assert sw.theme is win.theme


# --------------------------------------------------- geometry & layouts
def _geometry_problems(w, app):
    """Overlapping or clipped labels, and controls that cannot be scrolled fully into view."""
    holder = w.docks["trainer"].widget()
    panel = w.trainer
    bad = []
    leaves = [c for c in panel.findChildren(QWidget) if c.isVisible() and isinstance(c, (QLabel, QAbstractButton,
                                                                                          QComboBox, QLineEdit))]
    for c in leaves:
        if isinstance(c, QLabel) and c.wordWrap() and c.heightForWidth(c.width()) > c.height() + 1:
            bad.append(("wrapped text cut off", c.text()[:40], c.height(), c.heightForWidth(c.width())))
        if isinstance(c, QLabel) and not c.wordWrap():
            for line in c.text().split("\n"):
                if c.fontMetrics().horizontalAdvance(line) > c.contentsRect().width() + 1:
                    bad.append(("clipped", c.text()[:30], c.width()))
        if isinstance(c, QAbstractButton) and c.width() < c.minimumSizeHint().width() - 1:
            bad.append(("squeezed", c.text(), c.width(), c.minimumSizeHint().width()))
    rects = [(c, QRect(c.mapTo(panel, QPoint(0, 0)), c.size())) for c in leaves]
    for i, (a, ra) in enumerate(rects):
        for b, rb in rects[i + 1:]:
            if a.isAncestorOf(b) or b.isAncestorOf(a):
                continue
            if ra.intersected(rb).width() > 1 and ra.intersected(rb).height() > 1:
                bad.append(("overlap", a.objectName() or a.text()[:20] if hasattr(a, "text") else a, b.text()[:20]
                            if hasattr(b, "text") else b))
    for c in leaves:
        if isinstance(c, QLabel):
            continue
        holder.ensureWidgetVisible(c, 0, 0)
        _settle(app, 2)
        r = QRect(QPoint(0, 0), c.size())
        if (c.visibleRegion() & QRegion(r)) != QRegion(r):
            bad.append(("unreachable", c.accessibleName() or getattr(c, "text", lambda: "")()))
    if panel.width() > holder.viewport().width() and not holder.horizontalScrollBar().isVisible():
        bad.append(("cut off horizontally without a scroll bar",))
    if panel.height() > holder.viewport().height() and not holder.verticalScrollBar().isVisible():
        bad.append(("cut off vertically without a scroll bar",))
    return bad


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
@pytest.mark.parametrize("size", [(800, 600), (1024, 600), (1280, 720), (1366, 768), (1920, 1080)])
def test_panel_fits_small_screens_without_clipping_or_overlap(app, mode, size):
    w = make_window(app, mode)
    try:
        w.resize(*size)
        w.show()
        _settle(app)
        w.start_experiment()  # the tallest content: kit + guide
        _settle(app)
        assert (w.width(), w.height()) == size  # the window did not grow past the screen
        d = w.docks["trainer"]
        assert d.isVisible() and not d.isFloating() and w.rect().contains(d.geometry())
        assert w.centralWidget().width() >= 0.22 * w.width()  # the editor keeps usable space
        assert _geometry_problems(w, app) == [], (mode, size)
        w.trainer.hide_guide()
        _settle(app)
        assert _geometry_problems(w, app) == [], (mode, size)
        assert _on_screen(w, w.origin_edit) and _on_screen(w, w.mode_combo)
    finally:
        w.editor.document().setModified(False)
        w.close()
        _settle(app, 2)


def test_dock_resize_scrolls_instead_of_clipping(win, app):
    win.show_trainer()
    _settle(app)
    d = win.docks["trainer"]
    holder = d.widget()
    win.resizeDocks([d], [120], Qt.Orientation.Vertical)
    _settle(app)
    assert holder.verticalScrollBar().isVisible() and _geometry_problems(win, app) == []
    d.setFloating(True)
    d.resize(900, 900)
    _settle(app)
    assert not holder.verticalScrollBar().isVisible() and not holder.horizontalScrollBar().isVisible()
    assert _geometry_problems(win, app) == []
    d.setFloating(False)


def test_large_interface_font_still_fits(win, app):
    from test_gui import _set_ui_font
    win.resize(1280, 720)
    _set_ui_font(win, 14)
    try:
        win.start_experiment()
        _settle(app)
        assert win.trainer.switches[0].font().pointSize() > 10  # the panel follows the interface font size
        assert _geometry_problems(win, app) == []
    finally:
        _set_ui_font(win, 0)


def _baseline_states():
    return json.loads((HERE / "data" / "baseline_1.1.0_layouts.json").read_text(encoding="utf-8"))["states"]


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
def test_a_layout_saved_by_1_1_0_is_restored(app, mode):
    """``tests/data/baseline_1.1.0_layouts.json`` holds window states saved by the code before Phase 1
    (commit 7222094). They do not know the trainer dock; every old panel must come back as saved."""
    saved = _baseline_states()[mode]
    QSettings().clear()
    QSettings().setValue("mode", mode)
    QSettings().setValue("window/state", QByteArray(base64.b64decode(saved["state"])))
    QSettings().setValue("window/geometry", QByteArray(base64.b64decode(saved["geometry"])))
    if mode == "advanced":
        QSettings().setValue("window/state_advanced", QByteArray(base64.b64decode(saved["state"])))
    from studio8085.ui.mainwindow import MainWindow
    w = MainWindow()
    try:
        w.show()
        _settle(app)
        assert w._layout_restored and w.mode == mode
        shown = sorted(k for k, d in w.docks.items() if d.isVisible() and k != "trainer")
        if mode == "beginner":
            # 1.1.0 brought back all 13 panels for a Beginner session (the restore bug fixed in Phase 1,
            # recorded in restored_by_baseline); now the restore shows exactly the Beginner set.
            assert shown == saved["visible"] and shown != saved["restored_by_baseline"]
        else:
            assert shown == saved["restored_by_baseline"]  # exactly what 1.1.0 itself shows for that state
        d = w.docks["trainer"]
        assert not d.isFloating()
        if mode == "beginner":
            assert not d.isVisible()
        else:
            assert d.isVisible() and d in w.tabifiedDockWidgets(w.docks["symbols"])
        assert _on_screen(w, w.origin_edit) and _on_screen(w, w.mode_combo)
        w._set_mode("beginner" if mode == "advanced" else "advanced")
        _settle(app)
        w._set_mode(mode)
        _settle(app)
        assert sorted(k for k, d in w.docks.items() if d.isVisible() and k != "trainer") == saved["visible"]
        w.show_trainer()
        _settle(app)
        assert d.isVisible() and not d.isFloating() and _on_screen(w, d)
    finally:
        w.editor.document().setModified(False)
        w.close()
        _settle(app, 2)
        QSettings().clear()


def test_a_layout_with_the_trainer_dock_is_restored_as_saved(app):
    w = make_window(app, "advanced")
    try:
        w.resize(1366, 768)
        w.show()
        _settle(app)
        w.docks["trainer"].setFloating(True)
        _settle(app)
    finally:
        w.editor.document().setModified(False)
        w.close()  # saves window/state
        _settle(app, 2)
    from studio8085.ui.mainwindow import MainWindow
    w = MainWindow()
    try:
        w.show()
        _settle(app)
        assert w.docks["trainer"].isFloating()  # the user's choice is respected, not re-docked
    finally:
        w.docks["trainer"].setFloating(False)
        w.editor.document().setModified(False)
        w.close()
        _settle(app, 2)
        QSettings().clear()


def test_mode_switching_keeps_the_kit_and_its_dock(win, app):
    win.show_trainer()
    win.kit.set_switches(0x42)
    for mode in ("beginner", "advanced", "beginner", "advanced"):
        win._set_mode(mode)
        _settle(app)
        assert win.kit.switches.value == 0x42 and win.kit.enabled
        assert win.docks["trainer"].isVisible() == (mode == "advanced")
    win._set_mode("beginner")
    win.show_trainer()
    _settle(app)
    assert win.docks["trainer"].isVisible() and not win.docks["trainer"].isFloating()


_HIDPI_TRAINER_PROBE = r"""
import sys, tempfile
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[5])
from studio8085.app import use_system_fonts_offscreen
use_system_fonts_offscreen()
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
QApplication.setOrganizationName("S85hidpitk"); QApplication.setApplicationName("S85hidpitk")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
app = QApplication([])
QSettings().setValue("mode", sys.argv[2])
from studio8085.ui.mainwindow import MainWindow
import test_trainer_gui as T
w = MainWindow(); w.resize(int(sys.argv[3]), int(sys.argv[4])); w.show()
for _ in range(5):
    app.processEvents()
w.start_experiment()
for _ in range(5):
    app.processEvents()
bad = T._geometry_problems(w, app)
size_ok = (w.width(), w.height()) == (int(sys.argv[3]), int(sys.argv[4]))
print("dpr", w.devicePixelRatio(), "mode", w.mode, "size_ok", size_ok, "problems", bad)
w.editor.document().setModified(False)
sys.exit(0 if not bad and size_ok and w.docks["trainer"].isVisible() else 1)
"""


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
@pytest.mark.parametrize("scale", ["1.5", "2"])
def test_panel_fits_at_150_and_200_percent(mode, scale):
    import os
    import subprocess
    import sys
    src = str(HERE.parents[0] / "src")
    env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    w, h = round(1920 / float(scale)), round(1080 / float(scale))  # a 1920 x 1080 screen at 150 % / 200 %
    r = subprocess.run([sys.executable, "-c", _HIDPI_TRAINER_PROBE, src, mode, str(w), str(h), str(HERE)],
                       env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"dpr {float(scale)}" in r.stdout, r.stdout
