"""Phase 2 owner review fixes: memory cells used by a step, readable diagram text, the stack pointer's contents,
and the enlarge (full window) button. Core tests have no Qt; the GUI tests run offscreen."""

import pytest

from studio8085.core.assembler import assemble
from studio8085.core.machine import Machine
from studio8085.core.visual import (CELLS_AROUND, RECENT_LIMIT, StepRecorder, capture_memview)

PROG = """
        ORG 0
        LXI SP,2100H
        LXI H,3000H
        MVI A,3FH
        STA 2000H
        LDA 2000H
        MOV M,A
        INR M
        PUSH H
        PUSH PSW
        POP D
        CALL SUB1
        HLT
SUB1:   RET
"""


def machine(src: str) -> Machine:
    r = assemble(src)
    assert not r.errors, r.errors
    m = Machine()
    m.load(r)
    return m


def run_all(src=PROG, tracking=True, limit=30):
    m = machine(src)
    m.cpu.mem.set_tracking(tracking)
    rec = StepRecorder(m)
    out = []
    for _ in range(limit):
        rec.begin("into")
        m.step_into()
        r = rec.end()
        out.append((r, capture_memview(m.cpu, 0x2100)))
        if m.cpu.halted:
            break
    return m, out


def by_text(out, prefix):
    return next((r, mv) for r, mv in out if r is not None and r.text.lower().startswith(prefix.lower()))


# ------------------------------------------------ 1. memory cells used by a step (core)
def test_a_write_records_the_old_and_the_new_value():
    _, out = run_all()
    r, _ = by_text(out, "STA")
    (a,) = r.mem_accesses
    assert (a.kind, a.addr, a.old, a.value, a.observed) == ("W", 0x2000, 0x00, 0x3F, True)
    r, _ = by_text(out, "INR M")
    kinds = sorted((a.kind, a.addr) for a in r.mem_accesses)
    assert kinds == [("R", 0x3000), ("W", 0x3000)]  # INR M reads then writes the same cell
    assert next(a for a in r.mem_accesses if a.kind == "R").value == 0x3F  # the byte that was read, not the result
    w = next(a for a in r.mem_accesses if a.kind == "W")
    assert (w.old, w.value) == (0x3F, 0x40)


def test_reads_are_reported_only_when_the_simulator_can_prove_them():
    _, tracked = run_all(tracking=True)
    r, _ = by_text(tracked, "LDA")
    assert [(a.kind, a.addr) for a in r.mem_accesses] == [("R", 0x2000)]
    assert all(a.observed for rec, _ in tracked if rec for a in rec.mem_accesses)
    # access tracking off: a read leaves no evidence, so none is invented; a change of a cell is still provable
    _, untracked = run_all(tracking=False)
    r, _ = by_text(untracked, "LDA")
    assert r.mem_accesses == ()
    r, _ = by_text(untracked, "STA")
    assert [(a.kind, a.addr) for a in r.mem_accesses] == [("W", 0x2000)]
    r, _ = by_text(untracked, "INR M")
    assert [a.kind for a in r.mem_accesses] == ["W"]
    for rec, mv in untracked:
        assert mv.recent == ()  # no per-cell history without tracking


def test_run_summaries_never_claim_individual_accesses():
    m = machine(PROG)
    rec = StepRecorder(m)
    rec.begin("run")
    while not m.cpu.halted:
        m.step_into()
    r = rec.end()
    assert r.kind == "multi" and r.mem_accesses == ()
    mv = capture_memview(m.cpu, 0x2100)
    assert 0 < len(mv.recent) <= RECENT_LIMIT  # the recently-used list comes from the simulator's own statistics


def test_recent_list_is_bounded_and_newest_first():
    src = "        LXI H,4000H\n        MVI B,40H\nLP:     MOV M,B\n        INX H\n        DCR B\n        JNZ LP\n        HLT\n"
    m = machine(src)
    while not m.cpu.halted:
        m.step_into()
    mv = capture_memview(m.cpu, None)
    assert len(mv.recent) == RECENT_LIMIT
    lasts = [int(m.cpu.mem.last[a.addr]) for a in mv.recent]
    assert lasts == sorted(lasts, reverse=True)
    assert mv.last == mv.recent[0].addr
    assert len(mv.last_cells) == CELLS_AROUND and len(mv.hl_cells) == CELLS_AROUND


# ------------------------------------------------ 3. SP address and contents (core)
def test_sp_contents_after_push_pop_call_and_ret():
    m, out = run_all()
    for _r, mv in out:  # the view is read from real memory: the word is always low byte at SP, high byte at SP+1
        assert mv.sp_word == mv.sp_lo | mv.sp_hi << 8
    r, mv = by_text(out, "PUSH H")
    assert mv.sp == 0x20FE and (mv.sp_lo, mv.sp_hi) == (0x00, 0x30) and mv.sp_word == 0x3000
    assert mv.stack == ((0x20FE, 0x3000),) and not mv.stack_empty
    r, mv = by_text(out, "PUSH PSW")
    assert mv.sp == 0x20FC and mv.sp_hi == 0x3F  # A is the high byte; the flag byte is the low byte
    assert mv.sp_lo == r.post.flag_byte()
    assert mv.stack == ((0x20FC, mv.sp_word), (0x20FE, 0x3000))  # the top is first
    r, mv = by_text(out, "POP D")
    assert mv.sp == 0x20FE and r.post.reg("D") == 0x3F and mv.stack == ((0x20FE, 0x3000),)
    r, mv = by_text(out, "CALL")
    ret_addr = r.pre.pc + 3
    assert mv.sp == 0x20FC and mv.sp_word == ret_addr and mv.stack[0] == (0x20FC, ret_addr)
    r, mv = by_text(out, "RET")
    assert mv.sp == 0x20FE and mv.stack == ((0x20FE, 0x3000),)


def test_stack_view_lists_only_words_that_were_really_pushed():
    m = machine("        LXI SP,2100H\n        HLT\n")
    m.step_into()
    mv = capture_memview(m.cpu, 0x2100)
    assert mv.stack == () and mv.stack_empty
    assert (mv.sp, mv.sp_word) == (0x2100, 0)  # [SP] is still shown: it is real memory, just not part of the stack
    m.cpu.mem.data[0x2100] = 0x77  # a byte above the stack base is not a pushed word
    assert capture_memview(m.cpu, 0x2100).stack == ()


# --------------------------------------------------------------------------------- GUI
pytest.importorskip("PySide6")
from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from studio8085.ui import cpuview  # noqa: E402
from studio8085.ui.memory import MARK_ROLE  # noqa: E402
from test_gui import _settle, app, wait_until  # noqa: E402,F401
from test_trainer_phase1_fixes import SW, _leaks, close, new_window  # noqa: E402
from test_visual_gui import IO_PROG, load, open_panel, step  # noqa: E402

GUI_PROG = ("START: LXI SP,2100H\n LXI H,3000H\n MVI A,3FH\n STA 2000H\n LDA 2000H\n MOV M,A\n INR M\n"
            " PUSH H\n PUSH PSW\n POP D\n CALL SUB1\n HLT\nSUB1: RET\n")


def sp_rows(p):
    return p.nodes["SP"].sp_lines()


def test_diagram_lists_the_cells_a_step_used_with_a_non_colour_read_write_label(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, GUI_PROG)
        step(w, app, 4)  # STA 2000h
        mem = p.nodes["MEM"]
        assert mem.mem_lines() == ["WRITE 2000h  00h -> 3Fh"]
        assert "WRITE 2000h" in mem.describe() and "WRITE 2000h" in " ".join(p.node_texts())
        step(w, app)  # LDA 2000h
        assert mem.mem_lines() == ["READ  2000h = 3Fh"]
        step(w, app, 2)  # MOV M,A ; INR M
        assert mem.mem_lines() == ["READ  3000h = 3Fh", "WRITE 3000h  3Fh -> 40h"]
        # the cells around HL (M), with the used cell marked "RW" and HL labelled in text
        caption, cells = mem.strips()[0]
        assert caption == "around HL (M) = 3000h" and len(cells) == CELLS_AROUND
        assert (0x3000, 0x40, "RW") in cells
        assert [m for _a, _v, m in cells].count("") == CELLS_AROUND - 1
        assert any(t.text.startswith("3000 HL") for t in p.audit_paint())
        # a step that touches no memory says so
        w.cmd_restart()
        _settle(app)
        step(w, app, 3)
        assert p.nodes["MEM"].mem_lines() == ["no memory access in this step"]
    finally:
        close(w, app)


def test_memory_view_marks_the_same_cells_with_r_and_w_and_scrolls_to_them(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        w.docks["memory"].show()
        _settle(app)
        load(w, "START: MVI A,5AH\n STA 8123H\n LDA 8123H\n HLT\n")
        step(w, app, 2)
        mp = w.memory
        assert mp.model.marks == {0x8123: "W"}
        idx = mp.model.index(0x8123 // 16, 0x8123 % 16)
        assert mp.model.data(idx, MARK_ROLE) == "W" and "WRITTEN" in mp.model.data(idx, Qt.ItemDataRole.ToolTipRole)
        assert mp.step_label.isVisible() and "WRITE 8123h 00h -> 5Ah" in mp.step_label.text()
        assert mp.table.viewport().rect().intersects(mp.table.visualRect(idx))  # scrolled into view
        step(w, app)
        assert mp.model.marks == {0x8123: "R"} and "READ 8123h = 5Ah" in mp.step_label.text()
        step(w, app)  # HLT touches nothing: the marks are cleared
        assert mp.model.marks == {} and not mp.step_label.isVisible()
    finally:
        close(w, app)


def test_run_keeps_a_short_recently_used_list_instead_of_animating_each_access(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, "      LXI H,4000H\n      MVI B,0C0H\nLP:   MOV M,B\n      INX H\n      DCR B\n      JNZ LP\n      HLT\n")
        n0 = p.redraws
        w.cmd_run()
        wait_until(app, lambda: w.state == "halted")
        mem = p.nodes["MEM"]
        assert mem.uses == () and mem.mem_lines() == ["many instructions ran: see recent use"]
        assert 0 < len(p._mv.recent) <= RECENT_LIMIT and len(mem.recent_text().split()) <= 4
        assert p.redraws - n0 < 60  # 192 loop iterations did not cause 192 x 4 redraws
        assert w.memory.model.marks == {}
    finally:
        close(w, app)


def test_sp_box_shows_address_and_contents_after_push_pop_call_and_ret(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, GUI_PROG)
        step(w, app, 8)  # ... PUSH H
        sp = p.nodes["SP"]
        assert sp.value == (0x20FE, 16)
        assert sp_rows(p) == (["[SP]   = 00h", "[SP+1] = 30h", "word   = 3000h"], ["> 20FE 3000h"])
        step(w, app)  # PUSH PSW
        flags = w.machine.cpu.mem.data[0x20FC]
        left, stack = sp_rows(p)
        assert left == [f"[SP]   = {flags:02X}h", "[SP+1] = 3Fh", f"word   = 3F{flags:02X}h"]
        assert stack == [f"> 20FC 3F{flags:02X}h", "  20FE 3000h"]
        step(w, app)  # POP D
        assert sp.value == (0x20FE, 16) and sp_rows(p)[1] == ["> 20FE 3000h"]
        step(w, app)  # CALL
        assert sp.value == (0x20FC, 16)
        ret = w.machine.cpu.mem.data[0x20FC] | w.machine.cpu.mem.data[0x20FD] << 8
        assert sp_rows(p)[0][2] == f"word   = {ret:04X}h" and sp_rows(p)[1][0] == f"> 20FC {ret:04X}h"
        step(w, app, 2)  # RET (HLT is next)
        assert sp.value == (0x20FE, 16) and sp_rows(p)[1] == ["> 20FE 3000h"]
        assert "word   = 3000h" in sp.describe()
    finally:
        close(w, app)


# ----------------------------------------------------------- 2. readable text, no clipping
def _states(w, p, app):
    """Yield after a number of different drawn states (and with the decimal option) in every theme."""
    for theme in ("Dark", "Light", "High Contrast"):
        w._apply_theme(theme)
        w.cmd_restart()
        _settle(app)
        for i in range(11):
            step(w, app)
            if i in (2, 3, 6, 8, 10):
                yield theme


def test_text_is_large_and_never_clipped_in_any_state_or_theme(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, GUI_PROG)
        p.decimal = True
        p.dec_cb.setChecked(True)
        sizes, n = set(), 0
        for theme in _states(w, p, app):
            texts = p.audit_paint()
            assert texts
            n += len(texts)
            assert [(theme, t.nid, t.text) for t in texts if not t.fits()] == []
            sizes |= {t.font.pointSizeF() for t in texts}
        assert n > 300
        # design minimums (at 100% zoom): values 16 pt, titles 12.5 pt, details 11.5 pt; nothing below 10.5 pt
        assert cpuview.FONT_VALUE >= 12 and cpuview.FONT_LABEL >= 10 and cpuview.FONT_DETAIL >= 10
        assert min(sizes) >= 10.5 and max(sizes) >= 16
        # even at the smallest fit scale the text is readable
        assert cpuview.MIN_FIT_SCALE * cpuview.FONT_VALUE >= 12 and cpuview.MIN_FIT_SCALE * cpuview.FONT_DETAIL >= 9
        assert p.scale_factor >= cpuview.MIN_FIT_SCALE
    finally:
        close(w, app)


def test_register_values_are_drawn_in_the_big_font(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, "START: MVI A,3FH\n HLT\n")
        step(w, app)
        recs = {(t.nid, t.text): t for t in p.audit_paint()}
        assert recs[("A", "3Fh")].font.pointSizeF() >= 13 and recs[("A", "3Fh")].font.bold()
        assert recs[("A", "was 00h")].font.pointSizeF() >= 10.5
    finally:
        close(w, app)


@pytest.mark.parametrize("size", [(800, 600), (1024, 600), (1280, 720), (1366, 768), (1920, 1080)])
def test_text_fits_and_layout_holds_at_every_window_size(app, size):
    w = new_window(app, "advanced", size)
    try:
        p = open_panel(w, app)
        load(w, GUI_PROG)
        step(w, app, 9)
        assert all(t.fits() for t in p.audit_paint())
        assert p.scale_factor >= cpuview.MIN_FIT_SCALE
        w.cpu_dock.setFloating(False)
        _settle(app)
        assert w.editor.width() >= 150
        assert all(t.fits() for t in p.audit_paint())
    finally:
        close(w, app)


def test_diagram_size_option_persists_in_settings(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        i = p.size_combo.findData(1.5)
        p.size_combo.setCurrentIndex(i)
        assert p.scale_factor == pytest.approx(1.5) and not p._fit
        assert w.prefs.get("cpu_zoom") == 1.5 and p.settings()["zoom"] == 1.5
        p.apply_settings(zoom=0.0)
        assert p._fit and p.size_combo.currentData() == 0.0
        p.apply_settings(zoom=1.25)
        assert p.scale_factor == pytest.approx(1.25)
        p.zoom_by(0.0)
        assert p._fit and p.size_combo.currentData() == 0.0
    finally:
        close(w, app)


# ------------------------------------------------------- masking (Experiment 1)
def test_memory_list_stack_and_bigger_labels_never_leak_the_answer(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        w.docks["memory"].show()
        w.kit.set_switches(SW)
        # put the secret value in memory, at HL and on the stack, with real recorded accesses
        load(w, f"START: LXI SP,2100H\n LXI H,2200H\n MVI A,{SW:02X}H\n MOV M,A\n PUSH PSW\n IN 00H\n OUT 01H\n HLT\n")
        step(w, app, 5)
        assert any(_leaks(t, SW) for t in p.node_texts())  # sanity: unmasked, the new areas DO show it
        assert w.memory.model.marks and w.memory.step_label.isVisible()
        w.start_experiment()
        _settle(app)
        assert w.trainer.concealed and p.concealed
        assert p._mv is None and p.nodes["SP"].mv is None and p.nodes["MEM"].mv is None
        assert p.nodes["MEM"].mem_lines() == ["hidden until you predict"] and p.nodes["MEM"].strips() == []
        assert p.nodes["SP"].sp_lines() == (["contents hidden", "until you predict"], [])
        leaks = [t for t in p.node_texts() if _leaks(t, SW)]
        assert leaks == []
        drawn = [t.text for t in p.audit_paint()]
        assert [t for t in drawn if _leaks(t, SW)] == []
        assert w.memory.model.marks == {} and not w.memory.step_label.isVisible()
        # a snapshot pushed in while concealed is dropped, not stored
        from studio8085.core.visual import capture_memview as cm
        p.set_memview(cm(w.machine.cpu, 0x2100))
        assert p._mv is None
        p.nodes["MEM"].set_state(mv=None)
        w.refresh_all()
        _settle(app)
        assert p._mv is None and [t for t in p.node_texts() if _leaks(t, SW)] == []
        w.trainer.guide.ask_help()
        _settle(app)
        assert not p.concealed
    finally:
        close(w, app)


def test_masking_also_holds_in_the_enlarged_view(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        w.kit.set_switches(SW)
        load(w, IO_PROG)
        step(w, app, 1)
        p.set_enlarged(True)
        _settle(app)
        assert p.enlarged and w.cpu_big is not None
        w.start_experiment()
        _settle(app)
        assert p.concealed and p.enlarged
        assert [t for t in p.node_texts() if _leaks(t, SW)] == []
        assert [t.text for t in p.audit_paint() if _leaks(t.text, SW)] == []
        assert p._rec is None and p._mv is None
        p.set_enlarged(False)
        _settle(app)
        assert p.concealed and w.cpu_big is None
        assert [t for t in p.node_texts() if _leaks(t, SW)] == []
    finally:
        close(w, app)


# --------------------------------------------------------------- 4. the enlarge button
def test_enlarge_buttons_have_icons_tooltips_names_and_shortcuts(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        for b, name, key in ((p.max_btn, "Enlarge", "Ctrl+Shift+F"), (p.zoom_in_btn, "Zoom in", "Ctrl+="),
                             (p.zoom_out_btn, "Zoom out", "Ctrl+-"), (p.fit_btn, "Fit", "Ctrl+0")):
            assert not b.icon().isNull() and b.text() == ""
            assert name in b.accessibleName() and key in b.toolTip()
            assert b.isVisible() and b.width() >= 30 and b.height() >= 28
        keys = {sc.key().toString() for sc in p._shortcuts}
        assert {"Ctrl+Shift+F", "Ctrl+=", "Ctrl+-", "Ctrl+0", "Esc"} <= keys
        s0 = p.scale_factor
        for sc in p._shortcuts:
            if sc.key().toString() == "Ctrl+=":
                sc.activated.emit()
                break
        assert p.scale_factor > s0
        for sc in p._shortcuts:
            if sc.key().toString() == "Ctrl+0":
                sc.activated.emit()
        assert p._fit
    finally:
        close(w, app)


@pytest.mark.parametrize("docked", [False, True])
def test_enlarge_toggle_and_exact_restore_of_the_dock_state(app, docked):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        d = w.cpu_dock
        if docked:
            d.setFloating(False)
            _settle(app)
        state = (d.isFloating(), d.isVisible(), w.dockWidgetArea(d), tuple(w.tabifiedDockWidgets(d)),
                 d.geometry(), w.editor.width())
        scroll = d.widget()
        load(w, GUI_PROG)
        step(w, app, 4)
        icon_before = p.max_btn.accessibleName()
        QTest.mouseClick(p.max_btn, Qt.MouseButton.LeftButton)  # the button enlarges
        _settle(app)
        big = w.cpu_big
        assert big is not None and big.isVisible() and p.enlarged and big.isAncestorOf(p)
        assert not scroll.isAncestorOf(p) and w.visual.enabled
        assert "Restore" in p.max_btn.accessibleName() and p.max_btn.accessibleName() != icon_before
        assert p.view.viewport().width() > 300 and p.nodes["MEM"].mem_lines()  # live and usable
        step(w, app)  # stepping still works while enlarged, and the diagram follows
        assert p.nodes["MEM"].mem_lines()[0].startswith("READ")
        QTest.mouseClick(p.max_btn, Qt.MouseButton.LeftButton)  # the same button restores
        _settle(app)
        assert w.cpu_big is None and not p.enlarged and scroll.isAncestorOf(p) and d.widget() is scroll
        assert p.max_btn.accessibleName() == icon_before
        assert (d.isFloating(), d.isVisible(), w.dockWidgetArea(d), tuple(w.tabifiedDockWidgets(d)),
                d.geometry(), w.editor.width()) == state
        # Esc also restores
        p.set_enlarged(True)
        _settle(app)
        assert w.cpu_big is not None
        QTest.keyClick(w.cpu_big, Qt.Key.Key_Escape)
        _settle(app)
        assert w.cpu_big is None and scroll.isAncestorOf(p)
        # closing the big window with its title-bar button restores as well
        p.set_enlarged(True)
        _settle(app)
        w.cpu_big.close()
        _settle(app)
        assert w.cpu_big is None and scroll.isAncestorOf(p)
        assert w.visual.enabled == d.isVisible()
    finally:
        close(w, app)


def test_enlarged_view_at_800x600_breaks_nothing(app):
    w = new_window(app, "advanced", (800, 600))
    try:
        p = open_panel(w, app)
        load(w, GUI_PROG)
        step(w, app, 9)
        editor_w = w.editor.width()
        docks = {k: (d.isVisible(), d.isFloating()) for k, d in w.docks.items()}
        p.set_enlarged(True)
        _settle(app)
        big = w.cpu_big
        assert big is not None and big.isVisible()
        assert p.view.viewport().width() > 100 and p.text.width() > 100
        assert all(t.fits() for t in p.audit_paint())
        assert p.scale_factor >= cpuview.MIN_FIT_SCALE
        p.tabs.setCurrentWidget(p.labs)  # the labs live in the same enlarged panel
        _settle(app)
        assert p.labs.isVisible()
        p.set_enlarged(False)
        _settle(app)
        assert w.editor.width() == editor_w and w.editor.width() >= 150
        assert {k: (d.isVisible(), d.isFloating()) for k, d in w.docks.items()} == docks
        assert w.cpu_dock.width() <= w.screen().availableGeometry().width()
    finally:
        close(w, app)


def test_fonts_exist_so_the_fit_check_means_something(app):
    # sanity for the clipping tests: the audit uses real font metrics, so some font family must be installed
    assert QFontDatabase.families()
    assert cpuview.fnt(cpuview.FONT_DETAIL, True).pointSizeF() == pytest.approx(cpuview.FONT_DETAIL)
    assert QRect(0, 0, 1, 1).isValid()
