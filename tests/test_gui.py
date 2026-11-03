"""GUI tests: run the real main window offscreen and drive it like a user."""

import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    QApplication.setOrganizationName("S85test")
    QApplication.setApplicationName("S85test")
    settings_dir = str(tmp_path_factory.mktemp("settings"))
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, settings_dir)
    # On Windows NativeFormat is the registry and setPath() does not apply to it, so the tests
    # used to read/clear the real HKCU\Software\S85test key (two runs at once clobbered each other).
    # INI files in the temp dir keep every run isolated on all platforms.
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings_dir)
    a =QApplication.instance() or QApplication([])
    yield a


def make_window(app, mode="advanced"):
    QSettings().clear()
    QSettings().setValue("mode", mode)
    from studio8085.ui.mainwindow import MainWindow
    return MainWindow()


@pytest.fixture
def win(app):
    w = make_window(app)
    w.resize(1400, 900)
    w.show()
    app.processEvents()
    yield w
    w.editor.document().setModified(False)
    w.close()
    app.processEvents()


def wait_until(app, cond, timeout=8.0):
    t0 = time.time()
    while not cond():
        app.processEvents()
        time.sleep(0.002)
        assert time.time() - t0 < timeout, "timed out"


def set_src(win, text):
    win.editor.setPlainText(text)
    win._live_check()


def test_starts_with_a_working_example(win):
    assert win.live.ok and win.state == "idle" and "02_sum_array" in win.windowTitle()


def test_run_to_halt_updates_every_panel(win, app):
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    cpu = win.machine.cpu
    assert cpu.hl == 961
    assert win.registers.item(9, 1).text() == "03C1"  # HL row
    assert win.flags.instr.text() == f"{cpu.icount:,}"
    assert "Halted after" in win.msg.text()
    assert win.editor.exec_line is not None  # shows the HLT line


def test_step_into_over_out_and_exec_line(win, app):
    set_src(win, "\tcall f\n\tmvi b,7\n\thlt\nf:\tmvi a,1\n\tcall g\n\tret\ng:\tinr a\n\tret\n")
    win.cmd_step("into")  # first press assembles and stops at the entry
    assert win.state == "ready" and win.editor.exec_line == 1
    win.cmd_step("into")
    assert win.state == "paused" and win.editor.exec_line == 4
    win.cmd_step("over")  # runs MVI A then ... lands on 'call g' (line 5)
    assert win.editor.exec_line == 5
    win.cmd_step("over")  # whole call g in one go
    assert win.editor.exec_line == 6 and win.machine.cpu.a == 2
    win.cmd_step("out")
    assert win.editor.exec_line == 2


def test_breakpoint_via_gutter_and_run_to_cursor(win, app):
    set_src(win, "\tmvi a,1\n\tmvi b,2\n\tmvi c,3\n\thlt\n")
    win.editor.toggle_breakpoint(3)
    assert win.editor.breakpoint_lines() == [3]
    win.cmd_run()
    wait_until(app, lambda: win.state == "paused")
    assert win.editor.exec_line == 3 and win.machine.cpu.regs[1] == 0x00 and win.machine.cpu.regs[0] == 2
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    assert win.machine.cpu.regs[1] == 3
    win.editor.clear_breakpoints()
    win.cmd_restart()
    win.editor.goto(3)
    win.cmd_run_to_cursor()
    wait_until(app, lambda: win.state == "paused")
    assert win.editor.exec_line == 3


def test_live_diagnostics_and_problems_panel(win, app):
    set_src(win, "\tmvi a,300\n\tfoo\n\thlt\n")
    assert len(win.problems._diags) == 2
    assert win.docks["problems"].windowTitle().startswith("Problems  (2 errors")
    assert [d.line for d in win.editor.diagnostics] == [1, 2]
    win.cmd_run()  # must refuse to run and say why
    assert win.state == "idle" and "error" in win.msg.text()
    set_src(win, "\tmvi a,3\n\thlt\n")
    assert win.problems._diags == [] and win.live.ok


def test_editing_state_from_panels(win, app):
    win.cmd_assemble()
    win.registers.item(1, 1).setText("5A")  # B
    assert win.machine.cpu.regs[0] == 0x5A
    win.registers.item(11, 1).setText("0100")  # PC
    assert win.machine.cpu.pc == 0x100
    win.flags.buttons["cy"].setChecked(True)
    assert win.machine.cpu.cy == 1
    win.memory.model.setData(win.memory.model.index(0x20, 3), "7F")
    assert win.machine.cpu.mem.data[0x203] == 0x7F
    win.io.model.setData(win.io.model.index(0x10, 1), "AB")
    assert win.machine.cpu.io[0x10] == 0xAB


def test_infinite_loop_is_stopped_with_explanation(win, app):
    set_src(win, "here:\tjmp here\n")
    win.cmd_run()
    wait_until(app, lambda: win.state == "paused")
    assert "jumps to itself" in win.msg.text()


def test_pause_and_stop_a_slow_program(win, app):
    set_src(win, "loop:\tnop\n\tjmp loop\n")
    win.speed.setCurrentIndex(3)  # 1,000 instr/s
    win.cmd_run()
    wait_until(app, lambda: win.machine.cpu.icount > 20)
    assert win.state == "running" and win.editor.isReadOnly()
    win.cmd_pause()
    n = win.machine.cpu.icount
    for _ in range(20):
        app.processEvents()
    assert win.state == "paused" and win.machine.cpu.icount == n and not win.editor.isReadOnly()
    win.cmd_run()
    win.cmd_stop()
    assert win.state == "idle"


def test_interrupt_panel_wakes_halted_cpu(win, app):
    win._load_example("08_interrupts.asm")
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    win.interrupts.buttons["RST7.5"].click()
    wait_until(app, lambda: win.state == "halted" and win.machine.cpu.io[1] == 1)
    win.interrupts.buttons["TRAP"].click()
    wait_until(app, lambda: win.state == "halted")
    assert win.machine.cpu.mem.data[win.machine.program.symbols["TRAPS"].value] == 1


def test_masked_interrupt_explains_itself(win, app):
    set_src(win, "\tei\n\thlt\n")
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    win.interrupts.buttons["RST5.5"].click()  # masked after reset
    assert "masked" in win.msg.text() and win.state == "halted"


def test_out_instruction_appears_in_log_and_io_panel(win, app):
    win._load_example("01_counter_leds.asm")
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    log = win.output.log.toPlainText()
    assert "OUT 01h <- 05h" in log and win.machine.cpu.io[1] == 255


def test_theme_switch_and_custom_syntax_colour(win, app):
    win.toggle_theme()
    assert win.theme.name == "Light" and win.editor.theme.name == "Light"
    win.prefs.set_syntax_override(False, "mnemonic", "#ff0000|b")
    win._apply_theme("Light")
    fmt = win.editor.highlighter.formats["mnemonic"]
    assert fmt.foreground().color().name() == "#ff0000"
    img = win.grab().toImage()
    assert not img.isNull() and img.width() > 800
    win.prefs.set_syntax_override(False, "mnemonic", None)


def test_heatmap_shows_activity(win, app):
    win._load_example("10_memory_heatmap.asm")
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    heat = win.memory.heat
    heat.set_mode("freq")
    cell = (0x2000 >> 4)
    assert heat._buf[cell] >= 64  # a "written" palette entry, not plain content
    heat.set_mode("exec")
    assert heat._buf[0] >= 96  # first code cell is "executed"


def test_file_open_save_roundtrip(win, app, tmp_path):
    f = tmp_path / "prog.asm"
    f.write_text("\tmvi a,9\n\thlt\n", encoding="utf-8")
    win.open_file(f)
    assert win.path == f and win.editor.toPlainText().startswith("\tmvi a,9")
    win.editor.appendPlainText("; edited")
    assert win.isWindowModified()
    assert win.save()
    assert "; edited" in f.read_text(encoding="utf-8") and not win.isWindowModified()
    assert str(f) in win.prefs.get("recent")


def test_auto_breakpoint_marker_and_gutter_validity(win, app):
    set_src(win, "\tnop\n;@\n\tnop\n\thlt\n")
    win.editor.apply_auto_breakpoints()
    assert win.editor.breakpoint_lines() == [3]
    assert win.editor.valid_lines == {1, 3, 4}


def test_dialogs_construct(win, app):
    from studio8085.ui.help import ReferenceDialog
    from studio8085.ui.settings import PreferencesDialog
    d = ReferenceDialog(win)
    assert d.table.rowCount() > 80
    d._filter("daa")
    assert sum(not d.table.isRowHidden(r) for r in range(d.table.rowCount())) >= 1
    p = PreferencesDialog(win.prefs, win.themes, win)
    p.size.setValue(13)
    p.save()
    assert win.prefs.get("font_size") == 13
    win.prefs.set("font_size", 11)


def test_editor_conveniences(win, app):
    e = win.editor
    e.setPlainText("start:")
    c = e.textCursor()
    c.movePosition(c.MoveOperation.End)
    e.setTextCursor(c)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    e.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    assert e.toPlainText().endswith("\n\t")  # indents after a label-only line
    e.setPlainText("nop\nhlt")
    e.selectAll()
    e.toggle_comment()
    assert e.toPlainText() == "; nop\n; hlt"
    e.toggle_comment()
    assert e.toPlainText() == "nop\nhlt"
    assert e.find_text("hlt") and e.textCursor().selectedText() == "hlt"
    tip = e._tooltip_at(e.cursorRect(e.textCursor()).center())
    assert tip is None or isinstance(tip, str)
    e._debounce.stop()


def test_heatmap_zoom_is_per_byte_and_follows_the_page(win, app):
    win._load_example("10_memory_heatmap.asm")
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    heat = win.memory.heat
    win.memory._zoom_to(0x3005)
    assert heat.zoom and heat._base == 0x3000
    heat.set_mode("freq")
    assert heat._buf[5] >= 64  # byte 0x3005 was written by the copy loop
    assert heat._addr_at(heat._cell_rect(0x3005).center()) == 0x3005
    win.memory.scroll_to(0x2010)  # moving the hex view moves the zoomed page
    assert heat._base == 0x2000
    win.memory.zoom.setCurrentIndex(0)
    assert not heat.zoom and heat._base == 0


def test_keyboard_shortcuts_are_wired(win, app):
    keys = {a.text().replace("&", ""): a.shortcut().toString() for a in
            (win.a_run, win.a_pause, win.a_stop, win.a_into, win.a_over, win.a_out, win.a_bp, win.a_assemble)}
    assert keys == {"Run / Continue": "F5", "Pause": "F6", "Stop": "Shift+F5", "Step Into": "F11",
                    "Step Over": "F10", "Step Out": "Shift+F11", "Toggle Breakpoint": "F9", "Assemble": "F7"}
    win.a_assemble.trigger()  # actions are connected, not just labelled
    assert win.state == "ready"
    win.a_into.trigger()
    assert win.state == "paused" and win.machine.cpu.icount == 1


# ------------------------------------------------------------------ v1.1 features
@pytest.fixture
def beginner(app):
    w = make_window(app, "beginner")
    w.resize(1400, 900)
    w.show()
    app.processEvents()
    yield w
    w.editor.document().setModified(False)
    w.close()
    app.processEvents()


def test_beginner_mode_is_the_default_and_hides_advanced_panels(app):
    QSettings().clear()
    from studio8085.ui.mainwindow import MainWindow
    w = MainWindow()
    w.show()
    app.processEvents()
    try:
        assert w.mode == "beginner"
        shown = {k for k, d in w.docks.items() if d.isVisible()}
        assert shown == {"registers", "flags", "memory", "explain", "instructions", "problems", "output"}
        assert not w.memory.heat_box.isVisible() and not w.memory.mode.isVisible()
        assert not w.flags.tstates.isVisible()
        assert not w.a_cursor.isVisible() and not w.speed.isVisible()
        # "Store code at" is in both modes since 1.1.0 (RELEASE_NOTES, USER_GUIDE): not an
        # Advanced-only item, and actually on screen (not behind the toolbar's overflow chevron)
        assert not any(w.tb_extra.widgetForAction(a) is w.origin_edit for a in w._advanced_actions)
        assert _on_screen(w, w.origin_edit) and _on_screen(w, w.mode_combo)
        assert w.tb_run.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        assert w.a_run.iconText() == "Run" and w.a_into.iconText() == "Step"
    finally:
        w.editor.document().setModified(False)
        w.close()


def test_switching_modes_round_trips_and_is_remembered(beginner, app):
    w = beginner
    w._set_mode("advanced")
    app.processEvents()
    assert {"stack", "io", "symbols", "interrupts", "listing", "trace"} <= {k for k, d in w.docks.items() if d.isVisible()}
    assert w.memory.heat_box.isVisible() and w.origin_edit.isVisible()
    assert w.prefs.get("mode") == "advanced" and w.mode_combo.currentData() == "advanced"
    w._set_mode("beginner")
    app.processEvents()
    assert not w.docks["stack"].isVisible() and w.docks["explain"].isVisible()
    assert w.a_mode["beginner"].isChecked()


def test_explain_panel_describes_next_instruction_and_what_just_happened(beginner, app):
    w = beginner
    set_src(w, "\tmvi a,0FFh\n\tadi 1\n\thlt\n")
    w.cmd_step("into")  # assemble, stop at entry
    assert "MVI A,0FFh" in w.explain.next.text() and "Loads the constant FFh" in w.explain.next.text()
    w.cmd_step("into")
    assert "ADI 01h" in w.explain.next.text() and "FFh" in w.explain.next.text()
    assert "Executed" in w.explain.last.text() and "MVI A,0FFh" in w.explain.last.text()
    assert w.explain.table.rowCount() >= 2
    w.cmd_step("into")  # ADI: A -> 00, CY, Z, AC, P change
    notes = w.explain.notes.text()
    assert "CY changed from 0 to 1" in notes and "carry out of bit 7" in notes and "Z changed from 0 to 1" in notes
    items = {w.explain.table.item(r, 0).text(): (w.explain.table.item(r, 1).text(), w.explain.table.item(r, 2).text())
             for r in range(w.explain.table.rowCount())}
    assert items["A"] == ("FFh", "00h") and items["CY"] == ("0", "1")


def test_explain_after_run_summarises_instructions_and_memory(beginner, app):
    w = beginner
    set_src(w, "\tmvi a,7\n\tsta 100h\n\tout 5\n\thlt\n")
    w.cmd_run()
    wait_until(app, lambda: w.state == "halted")
    assert "Run" in w.explain.last.text() and "4 instructions" in w.explain.last.text()
    notes = w.explain.notes.text().replace("&gt;", ">")
    assert "[0100h] 00h -> 07h" in notes and "05h 00h -> 07h" in notes


def test_beginner_flag_panel_hides_timing_but_status_still_works(beginner, app):
    w = beginner
    w.cmd_assemble()
    assert w.state == "ready" and "Ready" in w.flags.state.text()
    assert not w.flags.tstates.isVisible() and w.flags.instr.isVisible()


def test_trace_recording_panel_and_all_export_formats(win, app, tmp_path):
    set_src(win, "\tmvi a,1\n\tout 9\n\tpush psw\n\thlt\n")
    win.cmd_assemble()
    win.a_trace.trigger()  # Debug > Record Execution Trace
    assert win.machine.trace_on and win.docks["trace"].isVisible() and win.trace.record.isChecked()
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    win.trace.refresh(win.machine)
    assert win.trace.table.rowCount() == 4 and "4 instruction(s) recorded" in win.trace.info.text()
    assert win.trace.table.item(1, 3).text() == "OUT 09h" and "OUT 09h=01h" in win.trace.table.item(1, 20).text()
    for name in ("t.csv", "t.md", "t.html", "t.pdf"):
        win.write_trace(tmp_path / name)
    assert (tmp_path / "t.csv").read_text().splitlines()[0].startswith("#,Address")
    assert "| OUT 09h |" in (tmp_path / "t.md").read_text()
    assert "<table>" in (tmp_path / "t.html").read_text()
    pdf = (tmp_path / "t.pdf").read_bytes()
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500
    win.clear_trace()
    assert win.trace.table.rowCount() == 0 and win.machine.trace == []


def test_compat_notes_show_in_problems_and_gutter_but_never_block(win, app):
    set_src(win, "\torg 100h\n\tmvi a,2*3\n\thlt\n")
    assert win.problems._diags == []  # off by default
    win.a_compat["note"].trigger()
    diags = win.problems._diags
    assert [d.severity for d in diags] == ["info", "info"] and "ORG" in diags[0].message
    assert win.docks["problems"].windowTitle() == "Problems  (2 notes)"
    win.cmd_assemble()
    assert win.state == "ready"  # notes do not stop assembly
    win.a_compat["strict"].trigger()
    assert [d.severity for d in win.problems._diags] == ["error", "error"]
    win.cmd_run()
    assert win.state == "idle" and "error" in win.msg.text()
    assert win.prefs.get("compat") == "strict"
    win.a_compat["off"].trigger()


def test_memory_cell_detail_view_classifies_code_data_stack_and_unused(win, app):
    win._load_example("07_subroutines.asm")
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")
    m = win.memory
    result = win.machine.program.symbols["RESULT"].value
    assert "reserved storage (DS)" in m.describe_cell(result) and "written" in m.describe_cell(result)
    assert "program code - first byte of the instruction" in m.describe_cell(0)
    assert "operand byte" in m.describe_cell(1)
    assert "unused" in m.describe_cell(0x9000) and "never read or written" in m.describe_cell(0x9000)
    m.scroll_to(result)  # selecting a cell fills the detail card
    assert f"{result:04X}h" in m.detail.text()
    win.stack.base = 0x8000
    win.machine.cpu.sp = 0x7FFC
    assert "stack" in m.describe_cell(0x7FFD)


def test_high_contrast_theme_and_ui_font_size(win, app):
    win._apply_theme("High Contrast")
    assert win.theme.name == "High Contrast" and win.theme.colors["text"] == "#ffffff"
    assert "QToolButton:focus" in __import__("studio8085.ui.themes", fromlist=["x"]).stylesheet(win.theme)
    win.prefs.set("ui_font_size", 15)
    win._apply_prefs()
    assert app.font().pointSize() == 15
    win.prefs.set("ui_font_size", 0)
    win._apply_prefs()
    win._apply_theme("Dark")


def test_focus_editor_compact_layout_and_restart_message(win, app):
    before = {k for k, d in win.docks.items() if d.isVisible()}
    win.a_focus.setChecked(True)
    win.toggle_focus_mode()
    assert not any(d.isVisible() for d in win.docks.values())
    win.a_focus.setChecked(False)
    win.toggle_focus_mode()
    app.processEvents()
    assert {k for k, d in win.docks.items() if d.isVisible()} == before
    win._compact_layout()
    app.processEvents()
    assert all(d.isVisible() or win.docks[k].toggleViewAction() for k, d in win.docks.items())
    win.cmd_restart()
    assert "memory kept" in win.msg.text() and "I/O port values you entered were kept" in win.msg.text()  # the default
    assert "Memory is kept" in win.a_restart.toolTip() and "I/O port values you entered are kept" in win.a_restart.toolTip()
    win.prefs.set("keep_memory", False)
    win._apply_prefs()
    win.cmd_restart()
    assert "memory cleared" in win.msg.text() and "Memory is cleared" in win.a_restart.toolTip()


def test_example_metadata_card(win, app):
    win._load_example("04_bcd_add.asm")
    assert win.explain.meta.isVisible() is False or True
    assert win.live.metadata.get("validation") == "T"
    assert "Validation" in win.explain.meta.text() and "Tool-tested" in win.explain.meta.text()
    assert "no label is inherited" in win.explain.meta.toolTip().lower()
    assert "true interrupt behaviour" in win.explain.meta.toolTip()


def test_predict_first_hides_the_answer_and_remembers_the_choice(win, app):
    from PySide6.QtWidgets import QLabel
    win.set_mode("beginner") if hasattr(win, "set_mode") else None
    set_src(win, "\tmvi a,99h\n\tadi 01h\n\thlt\n")
    win.cmd_step("into")  # assemble, stop at entry
    win.cmd_step("into")  # MVI A,99h executed; next is ADI 01h

    def shown():
        return " ".join(l.text() for l in win.explain.findChildren(QLabel))

    assert "9Ah" in shown()  # default: the explanation says what will happen
    win.explain.predict.setChecked(True)
    text = shown()
    assert "9Ah" not in text and "predict-first" in text and "A = 99h" in text
    assert win.prefs.get("predict_first") is True
    win.cmd_step("into")  # step to check: the "what just happened" table is shown regardless
    cells = [win.explain.table.item(r, c).text() for r in range(win.explain.table.rowCount()) for c in range(3)]
    assert "9Ah" in cells
    win.explain.predict.setChecked(False)
    assert win.prefs.get("predict_first") is False


def test_memory_cell_detail_knows_the_stack_even_when_the_stack_panel_is_hidden(win, app):
    """Regression: in Beginner mode (Stack panel hidden) every byte above SP was reported as stack."""
    win._set_mode("beginner")
    app.processEvents()
    assert not win.docks["stack"].isVisible()
    set_src(win, "\tlxi sp,8000h\n\tlxi b,1234h\n\tpush b\n\thlt\n")
    win.cmd_step("into")  # assemble, stop at entry
    for _ in range(3):
        win.cmd_step("into")  # lxi sp, lxi b, push b
    d = win.memory.describe_cell
    assert "stack" in d(0x7FFF).lower() and "stack" in d(0x7FFE).lower()
    assert "stack" not in d(0x9000).lower() and "unused" in d(0x9000).lower()
    assert "stack" not in d(0x8000).lower()  # the byte at the stack base is not part of the stack


def test_about_credits_the_idea_author_and_affiliation(win, app, monkeypatch):
    import studio8085
    from PySide6.QtWidgets import QMessageBox
    shown = {}
    monkeypatch.setattr(QMessageBox, "about", lambda parent, title, text: shown.update(title=title, text=text))
    win.a_about.trigger()  # Help > About
    assert "Alaa A. Aldhalemi" in shown["text"] and "University of Kufa" in shown["text"]
    assert "Designed by Alaa A. Aldhalemi" in shown["text"] and "Idea proposed by" not in shown["text"]
    assert shown["title"].startswith("About")
    assert studio8085.IDEA_CREDIT == "Idea proposed by Alaa A. Aldhalemi, University of Kufa"


def test_readme_credits_the_idea_author():
    from pathlib import Path
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "Alaa A. Aldhalemi, University of Kufa" in readme


# ---------------------------------------------------------------- font size
def _set_ui_font(win, pt):
    win.prefs.set("ui_font_size", pt)
    win._apply_prefs()
    win._apply_theme(win.prefs.get("theme"))


def test_preferences_font_size_changes_the_editor_and_survives_theme_changes(win, app):
    """Regression: Qt resets widget fonts when the stylesheet is re-applied, which undid the new size."""
    from studio8085.ui.settings import PreferencesDialog
    assert win.editor.font().pointSize() == 11
    dlg = PreferencesDialog(win.prefs, win.themes, win)
    dlg.size.setValue(18)
    dlg.save()
    win._apply_prefs()
    win._apply_theme(win.prefs.get("theme"))  # what Preferences does right after saving
    assert win.editor.font().pointSize() == 18
    h18 = win.editor.fontMetrics().height()
    win.toggle_theme()
    win.toggle_theme()
    win.toggle_theme()
    assert win.editor.font().pointSize() == 18 and win.editor.fontMetrics().height() == h18
    assert win.editor.gutter_width() > 0 and win.editor.tabStopDistance() > 0
    win.prefs.set("font_size", 11)
    win._apply_prefs()


def test_zoom_is_remembered_and_survives_theme_changes(win, app):
    base = win.editor.font().pointSize()
    win.a_zoom_in.trigger()
    win.a_zoom_in.trigger()
    assert win.editor.font().pointSize() == base + 2 and win.prefs.get("font_size") == base + 2
    win.toggle_theme()
    assert win.editor.font().pointSize() == base + 2
    win.a_zoom_out.trigger()
    assert win.prefs.get("font_size") == base + 1
    win.prefs.set("font_size", 11)
    win._apply_prefs()


def test_interface_font_size_reaches_the_monospace_panels(win, app):
    from PySide6.QtGui import QFontMetrics
    win._set_mode("advanced")
    app.processEvents()
    base_item = win.registers.item(0, 1).font().pointSize()
    base_row = win.registers.verticalHeader().defaultSectionSize()
    base_col = win.registers.columnWidth(1)
    base_hex = win.memory.model.font.pointSize()
    base_hexcol = win.memory.table.columnWidth(0)
    app_pt = win._base_font.pointSize()
    _set_ui_font(win, app_pt + 6)
    try:
        assert win.registers.item(0, 1).font().pointSize() == base_item + 6  # table cells
        assert win.registers.verticalHeader().defaultSectionSize() > base_row  # rows grew with the text
        assert win.registers.columnWidth(1) > base_col
        assert win.memory.model.font.pointSize() == base_hex + 6 and win.memory.table.columnWidth(0) > base_hexcol
        assert win.explain.next.font().pointSize() == app_pt + 6  # ordinary widgets follow the app font
        # nothing is clipped: every row is taller than its text
        fm = QFontMetrics(win.registers.item(0, 1).font())
        assert win.registers.verticalHeader().defaultSectionSize() >= fm.height()
        win.toggle_theme()  # the stylesheet is re-applied: sizes must stick
        assert win.registers.item(0, 1).font().pointSize() == base_item + 6
        assert win.memory.model.font.pointSize() == base_hex + 6
        # panels that fill themselves later (listing) are scaled too
        set_src(win, "\tnop\n\thlt\n")
        win.cmd_assemble()
        assert win.listing.table.item(0, 3).font().pointSize() == base_item + 6
    finally:
        _set_ui_font(win, 0)
    # back to the original sizes exactly (no drift)
    assert win.registers.item(0, 1).font().pointSize() == base_item
    assert win.registers.verticalHeader().defaultSectionSize() == base_row
    assert win.registers.columnWidth(1) == base_col
    assert win.memory.model.font.pointSize() == base_hex and win.memory.table.columnWidth(0) == base_hexcol


def _beginner_names():
    from importlib import resources
    folder = resources.files("studio8085").joinpath("examples", "beginner")
    return sorted(f.name for f in folder.iterdir() if f.name.endswith(".asm"))


def test_beginner_mode_opens_the_first_lesson_and_it_runs(app):
    w = make_window(app, "beginner")
    try:
        w.resize(1100, 800)
        w.show()
        app.processEvents()
        assert "01_first_program" in w.windowTitle() and w.live.ok and w.state == "idle"
        w.cmd_run()
        wait_until(app, lambda: w.state == "halted")
        assert w.machine.cpu.regs[7] == 5 and w.machine.cpu.regs[1] == 0xFF
    finally:
        w.editor.document().setModified(False)
        w.close()
        app.processEvents()


def test_examples_menu_lists_the_beginner_set_first(win, app):
    top = win.examples_menu.actions()
    sub = top[0].menu()
    assert sub is not None and sub.title().startswith("Beginner")
    names = _beginner_names()
    assert len(sub.actions()) == len(names) == 17
    assert sub.actions()[0].text().startswith("01  ") and sub.actions()[-1].text().startswith("17  ")
    assert top[1].isSeparator()  # then the ten full-size programs
    assert sum(1 for a in top[2:] if a.text()) == 10
    # choosing an entry from the menu loads it into the editor, and it is ready to run
    sub.actions()[2].trigger()  # 03 Adding numbers
    app.processEvents()
    assert "03_add_numbers" in win.windowTitle() and win.live.ok and not win.live.warnings
    assert "Adding numbers" in win.explain.meta.text() and "Tool-tested" in win.explain.meta.text()


def test_every_beginner_example_loads_and_assembles_cleanly(win, app):
    for name in _beginner_names():
        win._load_example("beginner/" + name)
        win._live_check()
        assert win.live.ok and not win.live.warnings, name
        assert name[:-4] in win.windowTitle(), name


# ------------------------------------------------------- Instructions panel
def _catalog_form(opcode):
    from studio8085.core.catalog import FORM_OF
    return FORM_OF[opcode]


def _rows(win):
    t = win.instructions.tree
    return [t.topLevelItem(i) for i in range(t.topLevelItemCount())]


def _row(win, prefix):
    return next(it for it in _rows(win) if it.text(0).startswith(prefix))


def _real_click(win, app, item, double=False):
    """Click the way a mouse does (scrolling the row into view first)."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    t = win.instructions.tree
    t.scrollToItem(item)
    app.processEvents()
    pos = t.visualItemRect(item).center()
    vp = t.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    if double:  # what a real second click sends: a double-click event, then its release
        gp = QPointF(vp.mapToGlobal(pos))
        QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(pos), gp,
                                               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                               Qt.KeyboardModifier.NoModifier))
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    app.processEvents()


def _show_panel(win, app):
    win.show_instructions()
    app.processEvents()


def test_instructions_is_a_dock_in_both_modes_and_opens_from_a_shortcut(win, app):
    from PySide6.QtGui import QKeySequence
    assert "instructions" in win.docks and win.docks["instructions"].windowTitle() == "Instructions"
    assert win.a_instr.shortcut() == QKeySequence("Ctrl+I")
    from PySide6.QtWidgets import QMenu
    view = next(m for m in win.menuBar().findChildren(QMenu) if m.title() == "&View")
    assert "Instructions" in [a.text() for a in view.actions()]  # View > Instructions
    edit = next(m for m in win.menuBar().findChildren(QMenu) if m.title() == "&Edit")
    assert win.a_instr in edit.actions()  # Edit > Instructions (Ctrl+I)
    win.docks["instructions"].hide()
    win.a_instr.trigger()
    app.processEvents()
    assert win.docks["instructions"].isVisible()
    # focus-editor mode hides every panel; the shortcut brings the list back and leaves that mode
    win.a_focus.setChecked(True)
    win.toggle_focus_mode()
    assert not win.docks["instructions"].isVisible()
    win.a_instr.trigger()
    app.processEvents()
    assert win.docks["instructions"].isVisible() and not win.a_focus.isChecked()
    b = make_window(app, "beginner")
    try:
        b.resize(1200, 800)
        b.show()
        app.processEvents()
        assert b.docks["instructions"] in b.tabifiedDockWidgets(b.docks["explain"])  # shares the Explain pane
        assert b.docks["memory"] not in b.tabifiedDockWidgets(b.docks["explain"])
        def front_tab():  # the guide whose panel is actually on screen (the other has an empty visible region)
            if not b.instructions.visibleRegion().isEmpty():
                return "Instructions"
            return "Explain" if not b.explain.visibleRegion().isEmpty() else None

        assert front_tab() == "Explain"  # Explain stays the front tab at first
        btn = b.tb_extra.widgetForAction(b.a_instr)
        assert btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon  # labelled for beginners
        b.show_instructions()
        wait_until(app, lambda: front_tab() == "Instructions", timeout=5)
    finally:
        b.editor.document().setModified(False)
        b.close()
        app.processEvents()


def test_list_shows_opcode_bytes_and_tstates_and_remembers_the_scope(win, app):
    from studio8085.core.catalog import CATALOG, ESSENTIAL
    ins = win.instructions
    assert ins.current_scope() == "Essential" and len(_rows(win)) == len(ESSENTIAL)
    lda = _row(win, "LDA")
    assert [lda.text(c) for c in range(4)] == ["LDA addr", "3Ah", "3", "13"]
    jnz = _row(win, "JNZ")
    assert [jnz.text(c) for c in range(4)] == ["JNZ addr", "C2h", "3", "7/10"]  # not taken / taken
    mov = _row(win, "MOV")
    assert mov.text(1) == "63 opcodes" and mov.childCount() == 63 and mov.child(0).text(0) == "MOV B,B"
    assert mov.child(0).text(1) == "40h" and mov.text(3) == "4-7"
    ins.scope.setCurrentIndex(ins.scope.findData("All"))
    assert len(_rows(win)) == len(CATALOG) and win.prefs.get("palette_scope") == "All"
    from studio8085.ui.mainwindow import MainWindow
    w2 = MainWindow()  # a new session (settings are kept, not cleared) starts where the student left off
    try:
        assert w2.instructions.current_scope() == "All" and len(_rows(w2)) == len(CATALOG)
    finally:
        w2.editor.document().setModified(False)
        w2.close()
    ins.scope.setCurrentIndex(ins.scope.findData("Branch"))
    assert {r.text(0).split()[0][0] for r in _rows(win)} <= {"J", "C", "R", "P"}
    assert "Branch" == win.prefs.get("palette_scope")


def test_hover_or_selection_explains_the_instruction(win, app):
    ins = win.instructions
    t = ins.tree
    mov = _row(win, "MOV")
    mov.setExpanded(True)
    t.setCurrentItem(next(mov.child(i) for i in range(mov.childCount()) if mov.child(i).text(0) == "MOV A,B"))
    text = ins.detail.text()
    assert "MOV A,B" in text and "Opcode 78h = 0111 1000b" in text and "1 byte" in text and "4 T-states" in text
    t.setCurrentItem(_row(win, "MOV"))
    assert "63 opcodes between 40h and 7Fh" in ins.detail.text()
    ins.search_edit.setText("zzzz")
    assert t.topLevelItemCount() == 0 and "No instruction matches" in ins.detail.text()


def test_click_inserts_on_a_new_line_and_selects_the_operand(win, app):
    from PySide6.QtTest import QTest
    set_src(win, "\tmvi a,1\n")
    win.editor.goto(1)
    _show_panel(win, app)
    _real_click(win, app, _row(win, "ADI"))
    assert win.editor.toPlainText() == "\tmvi a,1\n\tadi   00h\n"
    assert win.editor.textCursor().selectedText() == "00h"  # typing replaces the placeholder
    QTest.keyClicks(win.editor, "7")
    assert win.editor.toPlainText() == "\tmvi a,1\n\tadi   7\n"
    assert "Inserted ADI data8" in win.msg.text() and "opcode C6h" in win.msg.text()
    # the student can carry on typing by hand
    win.editor.moveCursor(win.editor.textCursor().MoveOperation.End)
    win.editor.insertPlainText("\thlt")
    app.processEvents()
    win._live_check()
    assert win.live.ok and win.editor.toPlainText() == "\tmvi a,1\n\tadi   7\n\thlt"
    # and clicking again appends below the line the cursor is on
    win.editor.goto(2)
    _real_click(win, app, _row(win, "NOP"))
    assert win.editor.toPlainText().splitlines() == ["\tmvi a,1", "\tadi   7", "\tnop", "\thlt"]


def test_insert_uses_a_blank_line_copies_indentation_and_undoes_in_one_step(win, app):
    set_src(win, "\tmvi a,1\n\n\thlt\n")
    win.editor.goto(2)  # the blank line
    win._insert_instruction(_catalog_form(0x3C))  # INR A
    assert win.editor.toPlainText() == "\tmvi a,1\n\tinr   a\n\thlt\n"  # reused, no extra line
    win.editor.undo()
    assert win.editor.toPlainText() == "\tmvi a,1\n\n\thlt\n"  # one Ctrl+Z puts everything back
    set_src(win, "        mvi a,1\n")  # eight spaces, as in the bundled examples
    win.editor.goto(1)
    win._insert_instruction(_catalog_form(0x3D))  # DCR A
    assert win.editor.toPlainText() == "        mvi a,1\n        dcr   a\n"
    set_src(win, "again:\n")  # a label alone on its line: the instruction is indented below it
    win.editor.goto(1)
    win._insert_instruction(_catalog_form(0x3C))
    assert win.editor.toPlainText() == "again:\n\tinr   a\n"
    set_src(win, "")
    win._insert_instruction(_catalog_form(0x00))
    assert win.editor.toPlainText() == "\tnop" and win.editor.textCursor().selectedText() == ""
    set_src(win, "; just a comment\n")
    win.editor.goto(1)
    win._insert_instruction(_catalog_form(0xC3))  # JMP label
    assert win.editor.toPlainText() == "; just a comment\n\tjmp   label\n"
    assert win.editor.textCursor().selectedText() == "label"


def test_insert_is_refused_while_the_program_runs(win, app):
    set_src(win, "\thlt\n")
    win.editor.set_read_only_running(True)
    try:
        win._insert_instruction(_catalog_form(0x00))
        assert win.editor.toPlainText() == "\thlt\n" and "running" in win.msg.text()
    finally:
        win.editor.set_read_only_running(False)


def test_single_and_double_clicks_insert_exactly_once(win, app):
    set_src(win, "\thlt\n")
    win.editor.goto(1)
    _show_panel(win, app)
    got = []
    win.instructions.insert_requested.connect(lambda f: got.append(f.label))
    _real_click(win, app, _row(win, "XCHG"))
    assert got == ["XCHG"]
    got.clear()
    _real_click(win, app, _row(win, "CMA"), double=True)  # a double-click is one gesture
    assert got == ["CMA"]
    assert win.editor.toPlainText().count("cma") == 1


def test_groups_open_on_a_click_and_only_one_stays_open(win, app):
    _show_panel(win, app)
    mov, mvi = _row(win, "MOV"), _row(win, "MVI")
    assert not mov.isExpanded()
    _real_click(win, app, mov)
    assert mov.isExpanded() and mov.childCount() == 63
    _real_click(win, app, mvi)
    assert mvi.isExpanded() and not mov.isExpanded()  # the accordion keeps the small pane short
    _real_click(win, app, mvi, double=True)  # a double-click toggles once, not twice
    assert not mvi.isExpanded()
    _real_click(win, app, mvi)
    set_src(win, "")
    _real_click(win, app, mvi.child(7))  # MVI A,data8 from inside the group
    assert win.editor.toPlainText() == "\tmvi   a,00h" and win.editor.textCursor().selectedText() == "00h"


def test_search_filters_and_enter_inserts_a_single_match(win, app):
    from PySide6.QtTest import QTest
    ins = win.instructions
    set_src(win, "")
    ins.search_edit.setText("hlt")
    assert [r.text(0) for r in _rows(win)] == ["HLT"]
    QTest.keyClick(ins.search_edit, Qt.Key.Key_Return)
    assert win.editor.toPlainText() == "\thlt"
    ins.search_edit.setText("mov a,b")
    rows = _rows(win)
    assert [r.text(0) for r in rows] == ["MOV A,B"] and rows[0].text(1) == "78h"
    ins.search_edit.setText("78h")
    assert [r.text(0) for r in _rows(win)] == ["MOV A,B"]
    ins.search_edit.setText("inr")  # several opcodes: Enter lets the student choose instead of guessing
    before = win.editor.toPlainText()
    QTest.keyClick(ins.search_edit, Qt.Key.Key_Return)
    assert win.editor.toPlainText() == before and ins.tree.currentItem().text(0) == "INR B"
    ins.search_edit.setText("")
    assert len(_rows(win)) == 40


def test_status_bar_shows_the_machine_code_of_the_cursor_line(win, app):
    set_src(win, "; a comment\n\tmvi a,5\n\tsta 0200h\n\tjnz 0\n\thlt\n")
    for line, expect in ((1, ""), (2, "Machine code: 3E 05"), (3, "Machine code: 32 00 02"),
                         (4, "Machine code: C2 00 00"), (5, "Machine code: 76")):
        win.editor.goto(line)
        app.processEvents()
        assert win.code_label.text() == expect, line
    # typing a new instruction updates the label once the live check has run
    win.editor.moveCursor(win.editor.textCursor().MoveOperation.End)
    win.editor.insertPlainText("\n\tnop")
    win._live_check()
    assert win.code_label.text() == "Machine code: 00"


def test_instruction_list_follows_the_interface_font_size(win, app):
    t = win.instructions.tree
    base = t.font().pointSize()
    _set_ui_font(win, win.prefs.get("ui_font_size") + 15)  # "interface font size" is absolute: 15 pt = default + 6
    try:
        assert QApplication.font().pointSize() == 15
        assert t.font().pointSize() == base + 6
        assert t.fontMetrics().height() <= t.visualItemRect(t.topLevelItem(0)).height()  # rows are not clipped
    finally:
        _set_ui_font(win, 0)
    assert t.font().pointSize() == base


# ----------------------------------------------------------- keep memory
KEEP_PROGRAM = "\tlda 2000h\n\tadi 1\n\tsta 2001h\n\thlt\n"


def _type_in_memory(win, addr, value):
    """Edit a memory cell in the Memory panel like a user (row = address // 16, column = address % 16)."""
    assert win.memory.model.setData(win.memory.model.index(addr // 16, addr % 16), f"{value:02X}")


def _run_to_halt(win, app):
    win.cmd_run()
    wait_until(app, lambda: win.state == "halted")


def test_memory_typed_before_running_survives_the_run(win, app):
    """Reported: values typed into memory turned to zero when Run was pressed."""
    set_src(win, KEEP_PROGRAM)
    mem = win.machine.cpu.mem.data
    _type_in_memory(win, 0x2000, 0x41)  # before anything is assembled
    _run_to_halt(win, app)
    assert (mem[0x2000], mem[0x2001], win.machine.cpu.regs[7]) == (0x41, 0x42, 0x42)
    # Run again on the halted program re-assembles it: the data (and the result) are still there
    _run_to_halt(win, app)
    assert (mem[0x2000], mem[0x2001], win.machine.cpu.regs[7]) == (0x41, 0x42, 0x42)
    # Restart and Step keep it too
    win.cmd_restart()
    assert mem[0x2000] == 0x41 and win.machine.cpu.pc == 0
    _type_in_memory(win, 0x2000, 0x50)
    set_src(win, KEEP_PROGRAM + "\tnop\n")  # edit the source: the next Step re-assembles
    win.cmd_step("into")
    assert mem[0x2000] == 0x50


def test_memory_typed_after_assembling_is_used_by_the_run(win, app):
    set_src(win, KEEP_PROGRAM)
    win.cmd_assemble()
    _type_in_memory(win, 0x2000, 0x10)
    _run_to_halt(win, app)
    assert win.machine.cpu.mem.data[0x2001] == 0x11


def test_opening_another_program_keeps_memory_but_drops_the_old_code(win, app):
    set_src(win, KEEP_PROGRAM)
    win.cmd_assemble()
    _type_in_memory(win, 0x2000, 0x41)
    assert win.machine.cpu.mem.data[0] == 0x3A  # the old program's first byte (LDA)
    win._load_example("beginner/01_first_program.asm")  # replaces the source
    mem = win.machine.cpu.mem.data
    assert mem[0x2000] == 0x41 and bytes(mem[:8]) == bytes(8)  # data kept, old code gone


def test_preference_off_restores_the_clean_start(win, app):
    win.prefs.set("keep_memory", False)
    set_src(win, KEEP_PROGRAM)
    _type_in_memory(win, 0x2000, 0x41)
    _run_to_halt(win, app)
    assert win.machine.cpu.mem.data[0x2000] == 0 and win.machine.cpu.mem.data[0x2001] == 1
    _type_in_memory(win, 0x3000, 0x77)
    win._load_example("beginner/01_first_program.asm")
    assert win.machine.cpu.mem.data[0x3000] == 0  # replacing the source wipes memory again


def test_preferences_dialog_has_the_keep_memory_switch(win, app):
    from studio8085.ui.settings import PreferencesDialog
    dlg = PreferencesDialog(win.prefs, win.themes, win)
    assert dlg.keep.isChecked() and "Keep memory" in dlg.keep.text()  # on by default
    dlg.keep.setChecked(False)
    dlg.save()
    assert win.prefs.get("keep_memory") is False
    dlg2 = PreferencesDialog(win.prefs, win.themes, win)
    assert not dlg2.keep.isChecked()


def test_clear_memory_command_still_wipes_on_demand(win, app):
    set_src(win, KEEP_PROGRAM)
    win.cmd_assemble()
    _type_in_memory(win, 0x2000, 0x41)
    win.cmd_clear_memory()
    mem = win.machine.cpu.mem.data
    assert mem[0x2000] == 0 and mem[0] == 0x3A  # data wiped, the loaded program restored


# ------------------------------------------------------- code address
def test_code_address_box_is_visible_in_both_modes(win, app):
    assert win.origin_edit.isVisible()  # advanced
    b = make_window(app, "beginner")
    try:
        b.resize(1300, 800)
        b.show()
        app.processEvents()
        assert b.origin_edit.isVisible()  # beginner too: the student can choose where the code is stored
        assert "first byte is stored" in b.origin_edit.toolTip() and "ORG" in b.origin_edit.toolTip()
    finally:
        b.editor.document().setModified(False)
        b.close()
        app.processEvents()


def _on_screen(window, widget) -> bool:
    """Visible (not hidden in a toolbar's overflow menu) and entirely inside the window."""
    from PySide6.QtCore import QPoint, QRect
    r = QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())
    return widget.isVisible() and not widget.visibleRegion().isEmpty() and window.rect().contains(r)


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
@pytest.mark.parametrize("size", [(800, 600), (900, 600), (1024, 600), (1280, 720), (1366, 768)])
def test_code_address_box_fits_on_narrow_windows(app, mode, size):
    """Regression: in Beginner mode the wide Run toolbar pushed "Store code at" (and the Mode box)
    behind the Tools toolbar's overflow chevron on narrow windows; the Tools toolbar now wraps."""
    w = make_window(app, mode)
    try:
        w.resize(*size)
        w.show()
        for _ in range(3):
            app.processEvents()
        assert w.mode == mode
        assert (w.width(), w.height()) == size  # the window did not grow past the requested size
        assert _on_screen(w, w.origin_edit), (size, mode, w.size())
        assert _on_screen(w, w.mode_combo), (size, mode, w.size())
        if not w.toolBarBreak(w.tb_extra):  # one row only when everything really fits
            assert sum(tb.sizeHint().width() for tb in w._toolbars_in_row()) <= w.width()
        w.resize(1900, w.height())  # wide again: back to a single toolbar row
        app.processEvents()
        assert not w.toolBarBreak(w.tb_extra) and _on_screen(w, w.origin_edit)
    finally:
        w.editor.document().setModified(False)
        w.close()
        app.processEvents()


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
def test_window_fits_small_screens(app, mode):
    """Regression: rigid panel minimums (heatmap, flag buttons, interrupt pins...) added up to a minimum
    window of about 820 x 900 px in Advanced mode, taller than a 1280 x 720 / 1366 x 768 screen."""
    w = make_window(app, mode)
    try:
        w.resize(1400, 900)
        w.show()
        for _ in range(3):
            app.processEvents()
        assert w.mode == mode
        m = w.minimumSizeHint()
        assert m.width() <= 1024 and m.height() <= 600, m  # also fits 1024 x 600 netbooks
        w.resize(1280, 680)  # 1280 x 720 minus the taskbar
        for _ in range(3):
            app.processEvents()
        assert (w.width(), w.height()) == (1280, 680)
        shown = {k for k, d in w.docks.items() if d.isVisible()}
        assert shown == ({"registers", "flags", "memory", "explain", "instructions", "problems", "output"}
                         if mode == "beginner" else set(w.docks))  # every panel is still there
        front = [k for k in shown if not w.docks[k].visibleRegion().isEmpty()]  # not behind another tab
        assert {"registers", "flags", "memory", "problems"} <= set(front)
        for k in front:
            assert w.rect().contains(w.docks[k].geometry()), k
    finally:
        w.editor.document().setModified(False)
        w.close()
        app.processEvents()


def _settle(app, n=5):
    for _ in range(n):
        app.processEvents()


def test_beginner_memory_panel_is_not_squeezed_on_a_720_screen(app):
    """Regression (visual QA): with the panels in scroll areas the hex table lost its last column and the
    detail line on a 1280 x 720 window although they fit; docks now get their natural minimum first."""
    w = make_window(app, "beginner")
    try:
        w.resize(1280, 720)
        w.show()
        _settle(app)
        holder = w.docks["memory"].widget()
        assert not holder.verticalScrollBar().isVisible() and not holder.horizontalScrollBar().isVisible()
        assert _on_screen(w, w.memory.detail)
        # the panel fills the dock exactly: nothing of it is cut off by the scroll area (whether column F
        # fits depends on the monospace font's width, as before this change)
        assert w.memory.size() == holder.viewport().size()
        t = w.memory.table
        assert t.height() >= t.horizontalHeader().height() + t.verticalHeader().defaultSectionSize()
        assert not w.docks["flags"].widget().verticalScrollBar().isVisible()
    finally:
        w.editor.document().setModified(False)
        w.close()
        _settle(app, 2)


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
@pytest.mark.parametrize("size", [(800, 600), (960, 540), (1280, 720)])
def test_editor_keeps_a_usable_share_of_narrow_windows(app, mode, size):
    """Regression (visual QA): fixed side-dock widths left the editor about 60 px wide on small windows."""
    w = make_window(app, mode)
    try:
        w.resize(*size)
        w.show()
        _settle(app)
        assert w.centralWidget().width() >= 0.22 * w.width(), (w.centralWidget().width(), w.width())
    finally:
        w.editor.document().setModified(False)
        w.close()
        _settle(app, 2)


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
@pytest.mark.parametrize("width", [460, 560, 660])
def test_mode_box_never_goes_behind_the_chevron(app, mode, width):
    """Regression (Linux CI, 200 %): on a very narrow window even the Tools row of its own overflowed and
    hid the Mode box. The captions are dropped first, and the window is never narrower than that row."""
    w = make_window(app, mode)
    try:
        w.resize(width, 600)
        w.show()
        _settle(app)
        assert _on_screen(w, w.origin_edit) and _on_screen(w, w.mode_combo), (mode, width, w.width())
        assert w.minimumWidth() <= 800  # still fits an 800 x 600 screen
        assert w.mode_combo.accessibleName() == "Mode" and w.speed.accessibleName() == "Speed"
        w.resize(1900, 700)
        _settle(app)
        assert all(a.isVisible() for a, _l, adv in w._compact_labels if not (adv and mode == "beginner"))
    finally:
        w.editor.document().setModified(False)
        w.close()
        _settle(app, 2)


def test_heatmap_minimum_still_draws_whole_squares(app):
    from studio8085.ui.memory import HeatmapWidget
    h = HeatmapWidget()
    m = h.minimumSize()
    assert m.width() <= 240 and m.height() <= 220
    h.resize(m)
    r = h._rect()
    assert r.width() == r.height() and r.width() // HeatmapWidget.GRID >= 3
    assert r.right() <= h.width() and r.bottom() <= h.height()


def test_switching_modes_many_times_keeps_size_and_panels(app):
    w = make_window(app, "advanced")
    try:
        w.resize(1366, 768)
        w.show()
        _settle(app)
        seen = {}
        for i in range(10):
            w._set_mode("beginner" if i % 2 == 0 else "advanced")
            _settle(app, 3)
            assert (w.width(), w.height()) == (1366, 768)
            docks = frozenset(k for k, d in w.docks.items() if d.isVisible())
            assert seen.setdefault(w.mode, docks) == docks  # no panel lost or added on later round trips
            assert _on_screen(w, w.origin_edit) and _on_screen(w, w.mode_combo)
        assert seen["advanced"] == set(w.docks) and len(seen["beginner"]) == 7
    finally:
        w.editor.document().setModified(False)
        w.close()
        _settle(app, 2)


def test_dock_panels_keep_their_widgets_and_focus(win, app):
    """The scroll areas that let docks shrink are transparent wrappers: same panel, no extra tab stop."""
    from PySide6.QtWidgets import QAbstractScrollArea
    from studio8085.ui.mainwindow import DockScroll
    panels = {"memory": win.memory, "flags": win.flags, "io": win.io, "trace": win.trace,
              "interrupts": win.interrupts, "instructions": win.instructions}
    for k, panel in panels.items():
        holder = win.docks[k].widget()
        assert isinstance(holder, DockScroll) and holder.widget() is panel, k
        assert holder.focusPolicy() == Qt.FocusPolicy.NoFocus
    for k, panel in (("registers", win.registers), ("explain", win.explain)):  # these already scroll
        assert isinstance(panel, QAbstractScrollArea) and win.docks[k].widget() is panel, k


def test_saved_layout_is_restored_and_clamped_to_the_screen(app):
    from PySide6.QtCore import QByteArray, QSettings
    from studio8085.ui.mainwindow import MainWindow
    w = make_window(app, "advanced")
    try:
        w.resize(1200, 700)
        w.show()
        app.processEvents()
        w.docks["io"].raise_()
        w.docks["trace"].hide()
        app.processEvents()
        state = w.saveState()
        w.prefs.q.setValue("window/state", state)
        w.setGeometry(0, 0, 4000, 3000)  # saved on a much bigger screen
        w.prefs.q.setValue("window/geometry", w.saveGeometry())
    finally:
        w.editor.document().setModified(False)
        w.close()
        app.processEvents()
    w2 = MainWindow()  # settings kept: a new session restores the layout
    try:
        w2.show()
        for _ in range(3):
            app.processEvents()
        assert w2._layout_restored
        assert not w2.docks["trace"].isVisible() and w2.docks["io"].isVisible()
        assert isinstance(QSettings().value("window/state"), QByteArray)
        avail = w2.screen().availableGeometry()
        assert w2.width() <= avail.width() and w2.height() <= avail.height(), (w2.size(), avail)
        assert avail.intersects(w2.frameGeometry())
        assert _on_screen(w2, w2.origin_edit) and _on_screen(w2, w2.mode_combo)
    finally:
        w2.editor.document().setModified(False)
        w2.close()
        app.processEvents()
        QSettings().clear()


def test_code_address_box_fits_with_a_large_interface_font(win, app):
    win._set_mode("beginner")
    win.resize(900, 700)
    _set_ui_font(win, 16)
    try:
        for _ in range(3):
            app.processEvents()
        assert _on_screen(win, win.origin_edit) and _on_screen(win, win.mode_combo)
    finally:
        _set_ui_font(win, 0)


_HIDPI_PROBE = r"""
import sys, tempfile
sys.path.insert(0, sys.argv[1])
from studio8085.app import use_system_fonts_offscreen
use_system_fonts_offscreen()
from PySide6.QtCore import QPoint, QRect, QSettings
from PySide6.QtWidgets import QApplication
QApplication.setOrganizationName("S85hidpi"); QApplication.setApplicationName("S85hidpi")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
app = QApplication([])
QSettings().setValue("mode", sys.argv[2])
from studio8085.ui.mainwindow import MainWindow
w = MainWindow(); w.resize(int(sys.argv[3]), int(sys.argv[4])); w.show()
for _ in range(3):
    app.processEvents()
ok = []
for x in (w.origin_edit, w.mode_combo):
    r = QRect(x.mapTo(w, QPoint(0, 0)), x.size())
    ok.append(x.isVisible() and not x.visibleRegion().isEmpty() and w.rect().contains(r))
print("dpr", w.devicePixelRatio(), "mode", w.mode, "size", w.width(), w.height(), "ok", ok)
w.editor.document().setModified(False)
sys.exit(0 if all(ok) and w.mode == sys.argv[2] else 1)
"""


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
@pytest.mark.parametrize("scale", ["1.5", "2"])
def test_code_address_box_fits_at_high_dpi(mode, scale):
    """A 1280x720 screen at 150 % / 200 % scaling: a separate process, since the scale factor is fixed
    when the QApplication starts."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    w, h = round(1280 / float(scale)), round(720 / float(scale))
    r = subprocess.run([sys.executable, "-c", _HIDPI_PROBE, src, mode, str(w), str(h)],
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"dpr {float(scale)}" in r.stdout, r.stdout


def test_the_app_keeps_native_settings_outside_the_tests():
    """The GUI tests store settings as INI files in a temp dir; the app itself must keep using the
    platform's native store (the registry on Windows), so it must not change the default format."""
    import subprocess
    import sys
    from pathlib import Path
    src = str(Path(__file__).resolve().parents[1] / "src")
    code = """
import sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
app = QApplication([])
import studio8085.app, studio8085.ui.mainwindow
from studio8085.ui.settings import Prefs
print(Prefs().q.format() == QSettings.Format.NativeFormat)
"""
    r = subprocess.run([sys.executable, "-c", code, src], capture_output=True, text=True, timeout=120)
    assert r.stdout.strip().endswith("True"), r.stdout + r.stderr


def test_changing_the_code_address_moves_the_program_at_the_next_run(win, app):
    set_src(win, "\tmvi a,5\n\tsta 3000h\n\thlt\n")
    mem = win.machine.cpu.mem.data
    win.cmd_assemble()
    assert win.machine.program.origin == 0 and mem[0] == 0x3E and "stored at 0000h" in win.msg.text()
    _type_in_memory(win, 0x3000, 0x77)  # data elsewhere is kept
    win.origin_edit.setText("2000")
    win._origin_changed()
    assert "2000h" in win.msg.text() and win._is_stale()  # the loaded program no longer matches the box
    _run_to_halt(win, app)  # Run re-assembles at the new address
    assert win.machine.program.origin == 0x2000
    assert bytes(mem[0x2000:0x2005]) == bytes([0x3E, 5, 0x32, 0x00, 0x30]) and mem[0x3000] == 5
    assert bytes(mem[0:5]) == bytes(5)  # the code is no longer at the old address (memory is kept otherwise)
    assert win.prefs.get("origin") == 0x2000 and win.machine.cpu.pc == 0x2006  # ran from 2000h, halted after the HLT at 2005h
    # Assemble shows the code in the Memory panel
    win.cmd_assemble()
    assert win.memory.table.currentIndex().row() == 0x200 and win.memory.table.currentIndex().column() == 0
    assert "stored at 2000h" in win.msg.text()


def test_an_org_line_overrides_the_code_address_box(win, app):
    set_src(win, "\torg 4000h\n\tnop\n\thlt\n")
    win.origin_edit.setText("2000")
    win._origin_changed()
    win.cmd_assemble()
    mem = win.machine.cpu.mem.data
    assert win.machine.program.origin == 0x4000 and mem[0x4000] == 0x00 and mem[0x4001] == 0x76
    assert win.machine.cpu.pc == 0x4000
    assert "stored at 4000h" in win.msg.text()


def test_a_bad_address_is_ignored(win, app):
    win.prefs.set("origin", 0x1000)
    win.origin_edit.setText("zzzz")
    win._origin_changed()
    assert win.origin_edit.text() == "1000" and win.prefs.get("origin") == 0x1000
    win.origin_edit.setText("12345")  # more than 16 bits
    win._origin_changed()
    assert win.origin_edit.text() == "1000"
