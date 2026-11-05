"""Phase 1 follow-up tests: Experiment 1 must not show the answer before the student predicts (Fix 1), a
session saved in Beginner mode must come back as the Beginner layout (Fix 2), and the Trainer Kit must stay
visible and usable in Beginner mode for the whole of a lab (Requirement 3)."""

import re

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QLabel, QLineEdit, QMenu, QPlainTextEdit,  # noqa: E402
                               QTableWidget, QWidget)

from studio8085.core.peripherals import PortMap  # noqa: E402
from test_gui import _on_screen, _settle, app, make_window, set_src  # noqa: E402,F401
from test_trainer_gui import EXPERIMENT_1, _geometry_problems  # noqa: E402

SW = 0x93  # the secret: 1001 0011b. No other number on screen should look like it.
BEGINNER_SET = ["explain", "flags", "instructions", "memory", "output", "problems", "registers"]
ALL_PANELS = ["explain", "flags", "instructions", "interrupts", "io", "listing", "memory", "output", "problems",
              "registers", "stack", "symbols", "trace"]


def visible(w, trainer=False):
    return sorted(k for k, d in w.docks.items() if d.isVisible() and (trainer or k != "trainer"))


def close(w, app):
    w.editor.document().setModified(False)
    w.close()
    _settle(app, 2)


def new_window(app, mode, size=(1366, 768)):
    w = make_window(app, mode)
    w.resize(*size)
    w.show()
    _settle(app)
    return w


# ------------------------------------------------------------------ Fix 1
def _leaks(text: str, sw: int = SW) -> bool:
    """Does this text contain the switch byte in hex (as a number of its own) or in binary?"""
    hx = f"{sw:02X}"
    if re.search(rf"(?<![0-9A-Fa-f]){hx}(?![0-9A-Fa-f])", text, re.I):
        return True
    return f"{sw:08b}" in text or f"{sw >> 4:04b} {sw & 15:04b}" in text


def visible_texts(w, sw: int = SW) -> list[str]:
    """Every string the trainer panel, the I/O Ports table, the event/log views, the Explain panel and the status
    bar can show (text, tooltips and accessible descriptions). The port number column is the address, not a value."""
    out = []
    for root in (w.trainer, w.io, w.output, w.trace, w.explain, w.msg, w.pc_label):
        widgets = [root] + root.findChildren(QWidget)
        for c in widgets:
            out += [c.toolTip(), c.accessibleName(), c.accessibleDescription(), c.statusTip()]
            if isinstance(c, (QLabel, QAbstractButton)):
                out.append(c.text())
            if isinstance(c, QLineEdit):
                out += [c.text(), c.placeholderText()]
            if isinstance(c, QPlainTextEdit):
                out.append(c.toPlainText())
            if isinstance(c, QComboBox):
                out += [c.itemText(i) for i in range(c.count())]
            if isinstance(c, QTableWidget):
                out += [c.item(r, k).text() for r in range(c.rowCount()) for k in range(c.columnCount())
                        if c.item(r, k) is not None]
    m = w.io.model
    for port in range(256):  # the value columns (hex, dec, binary) of every row, shown and edited
        for col in (1, 2, 3):
            ix = m.index(port, col)
            for role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ToolTipRole):
                v = m.data(ix, role)
                if v is not None:
                    out.append(str(v))
    return [t for t in out if t]


def assert_hidden(w, sw: int = SW):
    bad = [t for t in visible_texts(w) if _leaks(t, sw) or str(sw) in re.findall(r"\d+", t)]
    assert bad == [], bad[:3]


def prepare(app, mode, ports=None, size=(1366, 768)):
    """A window with the switches at SW, Experiment 1 already run once (so stale results exist), trace on."""
    w = new_window(app, mode, size)
    if ports is not None:
        w.kit.set_ports(ports)
        w.trainer.sync_from_kit()
    w.kit.set_switches(SW)
    w._set_trace(True)
    sw, led = w.kit.ports.switches_in, w.kit.ports.leds_out
    set_src(w, f"START: IN {sw:02X}H\n       OUT {led:02X}H\n       HLT\n")
    assert w._assemble_and_load()
    w.cmd_run()
    for _ in range(200):
        _settle(app, 1)
        if w.state == "halted":
            break
    assert w.state == "halted" and w.machine.cpu.a == SW
    return w


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
def test_nothing_shows_the_answer_before_the_student_predicts(app, mode):
    w = prepare(app, mode)
    try:
        # sanity: without the experiment the secret IS on screen (so the check above has teeth)
        assert any(_leaks(t) for t in visible_texts(w))
        w.start_experiment()
        _settle(app)
        assert w.trainer.concealed
        assert_hidden(w)
        assert w.io.model.data(w.io.model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "??"
        assert w.io.model.data(w.io.model.index(1, 1), Qt.ItemDataRole.DisplayRole) == "??"
        assert w.io.model.data(w.io.model.index(2, 1), Qt.ItemDataRole.DisplayRole) == "??"
        assert w.io.model.data(w.io.model.index(3, 1), Qt.ItemDataRole.DisplayRole) == "00"  # other ports unaffected
        assert not any(lamp.on for lamp in w.trainer.leds)  # no lit LEDs shown either
        # the student predicts: now everything is shown
        w.trainer.guide.predict_edit.setText(f"{SW:08b}")
        w.trainer.guide.lock_prediction()
        _settle(app)
        assert not w.trainer.concealed
        assert w.io.model.data(w.io.model.index(0, 1), Qt.ItemDataRole.DisplayRole) == f"{SW:02X}"
        assert w.io.model.data(w.io.model.index(0, 3), Qt.ItemDataRole.DisplayRole) == f"{SW:08b}"
        assert w.io.model.data(w.io.model.index(1, 1), Qt.ItemDataRole.DisplayRole) == f"{SW:02X}"
        assert f"OUT 01h <- {SW:02X}h" in w.output.log.toPlainText()
        assert f"{SW:02X}h" in w.trainer.sw_value.text() and f"{SW:08b}"[:4] in w.trainer.led_value.text()
        assert w.trace.table.rowCount() > 0
        assert any(lamp.on for lamp in w.trainer.leds)
        assert any(_leaks(t) for t in visible_texts(w))
    finally:
        close(w, app)


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
def test_help_and_ending_the_experiment_also_unmask(app, mode):
    w = prepare(app, mode)
    try:
        w.start_experiment()
        assert_hidden(w)
        w.trainer.guide.help_btn.click()
        _settle(app)
        assert not w.trainer.concealed and any(_leaks(t) for t in visible_texts(w))
        w.trainer.guide.start_over()  # hidden again, and the LED/display readouts are cleared as well
        _settle(app)
        assert w.trainer.concealed
        assert_hidden(w)
        assert "????" in w.trainer.led_value.text() and "??" in w.trainer.seg_value.text()
        w.trainer.guide.end_btn.click()  # ending the experiment shows everything again
        _settle(app)
        assert not w.trainer.concealed and not w._lab_active
        assert any(_leaks(t) for t in visible_texts(w))
        assert w.io.model.concealed == frozenset()
        w.start_experiment()
        assert w.trainer.concealed
        w.editor.document().setModified(False)
        w.new_file()  # leaving the experiment by opening something else
        _settle(app)
        assert not w.trainer.concealed and not w.trainer.guide.isVisible()
    finally:
        close(w, app)


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
def test_masking_follows_the_configured_ports_not_00_and_01(app, mode):
    w = prepare(app, mode, ports=PortMap(0x10, 0x11, 0x12))
    try:
        w.start_experiment()
        _settle(app)
        assert_hidden(w)
        d = lambda p: w.io.model.data(w.io.model.index(p, 1), Qt.ItemDataRole.DisplayRole)  # noqa: E731
        assert (d(0x10), d(0x11), d(0x12)) == ("??", "??", "??")
        assert d(0x00) == "00" and d(0x01) == "00"  # the old default ports are ordinary ports now
        w.trainer.guide.help_btn.click()
        assert d(0x10) == f"{SW:02X}" and d(0x11) == f"{SW:02X}"
    finally:
        close(w, app)


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
def test_stepping_waits_for_the_prediction(app, mode):
    """Run and Step are refused while the answer is hidden, so A and the LEDs cannot be read early."""
    w = new_window(app, mode)
    try:
        w.kit.set_switches(SW)
        w.start_experiment()
        set_src(w, EXPERIMENT_1)
        assert w._assemble_and_load()
        w.cmd_step("into")
        w.cmd_run()
        _settle(app)
        assert w.state == "ready" and w.machine.cpu.a == 0 and w.machine.cpu.icount == 0
        assert "prediction" in w.msg.text()
        assert_hidden(w)
        w.trainer.guide.predict_edit.setText("10010011")
        w.trainer.guide.lock_prediction()
        w.cmd_step("into")
        _settle(app)
        assert w.machine.cpu.a == SW and w.machine.cpu.icount == 1  # the register panel shows A now
    finally:
        close(w, app)


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
def test_cpu_io_results_are_identical_with_and_without_masking(app, mode):
    def result(w):
        cpu = w.machine.cpu
        return (cpu.a, bytes(cpu.io), list(w.machine.out_log), w.kit.leds.value, w.kit.switches.value,
                cpu.icount, cpu.tstates, cpu.halted, w.kit.bus.last_in, w.kit.bus.last_out)

    def execute(w):  # drive the machine directly: the UI gate is a separate thing from the masking
        w.machine.start("run")
        w.machine.run_chunk(1000)

    plain = new_window(app, mode)
    try:
        plain.kit.set_switches(SW)
        set_src(plain, EXPERIMENT_1)
        assert plain._assemble_and_load()
        execute(plain)
        expected = result(plain)
    finally:
        close(plain, app)
    masked = new_window(app, mode)
    try:
        masked.kit.set_switches(SW)
        masked.start_experiment()
        set_src(masked, EXPERIMENT_1)
        assert masked._assemble_and_load()
        before = (bytes(masked.machine.cpu.io), masked.kit.switches.value)
        assert masked.trainer.concealed
        execute(masked)
        assert masked.trainer.concealed  # still masked while the CPU ran
        assert result(masked) == expected
        assert before[1] == SW and masked.machine.cpu.io[0] == SW  # cpu.io itself holds the real value
        masked.trainer.guide.help_btn.click()
        assert result(masked) == expected
    finally:
        close(masked, app)


# ------------------------------------------------------------------ Fix 2
def test_a_session_saved_in_beginner_mode_restores_the_beginner_panels(app):
    """Regression: the restored state brought back all 13 panels (Qt's restoreState does not hide the docks
    the default layout showed, and nothing enforced the Beginner set afterwards)."""
    from studio8085.ui.mainwindow import MainWindow
    w = new_window(app, "beginner")
    try:
        assert visible(w) == BEGINNER_SET
    finally:
        close(w, app)
    w2 = MainWindow()  # the same settings: a new session
    try:
        w2.show()
        _settle(app)
        assert w2._layout_restored and w2.mode == "beginner"
        assert visible(w2, trainer=True) == BEGINNER_SET  # exactly the Beginner set, no kit, no Stack/I/O/...
        w2._set_mode("advanced")
        _settle(app)
        assert visible(w2) == ALL_PANELS
        w2._set_mode("beginner")
        _settle(app)
        assert visible(w2, trainer=True) == BEGINNER_SET
    finally:
        close(w2, app)
        QSettings().clear()


def test_advanced_keeps_its_own_saved_layout_and_modes_still_switch_after_a_restore(app):
    from studio8085.ui.mainwindow import MainWindow
    w = new_window(app, "advanced")
    try:
        w.docks["trace"].hide()
        w.docks["symbols"].hide()
        _settle(app)
    finally:
        close(w, app)
    w2 = MainWindow()
    try:
        w2.show()
        _settle(app)
        assert w2.mode == "advanced" and w2._layout_restored
        assert "trace" not in visible(w2) and "symbols" not in visible(w2) and "io" in visible(w2)
        w2._set_mode("beginner")
        _settle(app)
        assert visible(w2, trainer=True) == BEGINNER_SET
        w2._set_mode("advanced")  # its own layout comes back (saved when leaving Advanced)
        _settle(app)
        assert "trace" not in visible(w2) and "symbols" not in visible(w2) and "io" in visible(w2)
    finally:
        close(w2, app)
        QSettings().clear()


def test_a_new_session_does_not_inherit_a_running_lab(app):
    from studio8085.ui.mainwindow import MainWindow
    w = new_window(app, "beginner")
    try:
        w.start_experiment()
        _settle(app)
        assert w.docks["trainer"].isVisible()
    finally:
        close(w, app)
    w2 = MainWindow()
    try:
        w2.show()
        _settle(app)
        assert visible(w2, trainer=True) == BEGINNER_SET and not w2._lab_active
    finally:
        close(w2, app)
        QSettings().clear()


# ------------------------------------------------------------ Requirement 3
def _menu_action(w, title_part):
    menus = {m.title(): m for m in w.menuBar().findChildren(QMenu)}
    return next(a for a in menus["&Lab"].actions() if title_part in a.text())


def test_default_beginner_layout_without_a_lab_is_unchanged(app):
    w = new_window(app, "beginner")
    try:
        assert visible(w, trainer=True) == BEGINNER_SET and not w._lab_active
        view = {m.title(): m for m in w.menuBar().findChildren(QMenu)}["&View"]
        assert w.docks["trainer"].toggleViewAction() in view.actions()  # reachable
    finally:
        close(w, app)


@pytest.mark.parametrize("start", ["experiment", "lab_program_menu_action", "seven_segment_lab"])
def test_a_lab_shows_the_kit_in_beginner_mode_and_keeps_it_through_mode_switches(app, start):
    w = new_window(app, "beginner")
    try:
        d = w.docks["trainer"]
        assert not d.isVisible()
        if start == "experiment":
            _menu_action(w, "Experiment 1").trigger()
        elif start == "lab_program_menu_action":
            _menu_action(w, "Read switches, control LEDs").trigger()
        else:
            _menu_action(w, "hex decode").trigger()
        _settle(app)
        assert w._lab_active and d.isVisible() and not d.isFloating() and _on_screen(w, d)
        assert visible(w) == BEGINNER_SET
        for mode in ("advanced", "beginner", "advanced", "beginner"):
            w._set_mode(mode)
            _settle(app)
            assert d.isVisible() and not d.isFloating(), mode
            if mode == "beginner":
                assert visible(w) == BEGINNER_SET and _on_screen(w, d)
        w._reset_layout()  # View > Reset layout
        _settle(app)
        assert d.isVisible() and visible(w) == BEGINNER_SET
        w.kit.set_switches(0x55)  # usable: the kit still works
        w.trainer.refresh()
        assert w.trainer.switches[7].isChecked()
        w.trainer.switches[7].click()
        assert w.kit.switches.value == 0x54
        # the View menu still toggles it (reachable), and a lab started again brings it back
        d.toggleViewAction().trigger()
        _settle(app)
        assert not d.isVisible()
        _menu_action(w, "Show the").trigger()
        assert d.isVisible()
        # the lab ends when the student moves on: the default (hidden) comes back on the next layout
        w.new_file()
        assert not w._lab_active
        w._set_mode("advanced")
        w._set_mode("beginner")
        _settle(app)
        assert visible(w, trainer=True) == BEGINNER_SET
    finally:
        close(w, app)


@pytest.mark.parametrize("size", [(800, 600), (1024, 600), (1280, 720), (1366, 768)])
def test_the_kit_fits_beginner_mode_during_a_lab(app, size):
    w = new_window(app, "beginner", size)
    try:
        for how in ("experiment", "program", "mode switch"):
            if how == "experiment":
                w.start_experiment()
            elif how == "program":
                w._open_trainer_example("E1_read_switches_control_leds.asm")
            else:
                w._set_mode("advanced")
                w._set_mode("beginner")
            _settle(app, 8)
            d = w.docks["trainer"]
            assert (w.width(), w.height()) == size, how  # the window did not grow past the screen
            assert d.isVisible() and not d.isFloating() and w.rect().contains(d.geometry()), how
            assert w.centralWidget().width() >= 0.22 * w.width(), (how, w.centralWidget().width())
            assert w.editor.width() >= 0.2 * w.width() and w.editor.height() >= 150, (how, w.editor.size())
            assert _geometry_problems(w, app) == [], (size, how)
            assert _on_screen(w, w.origin_edit) and _on_screen(w, w.mode_combo)
    finally:
        close(w, app)
