"""Phase 2: the Interactive CPU Architecture panel in a real MainWindow (offscreen)."""

import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from studio8085.core.lab_content import LABS  # noqa: E402
from studio8085.core.visual import capture_state, kit_view  # noqa: E402
from test_gui import _settle, app, make_window, set_src, wait_until  # noqa: E402,F401
from test_trainer_phase1_fixes import SW, _leaks, close, new_window  # noqa: E402

PROG = "START: MVI A,3FH\n       MVI B,01H\n       ADD B\n       HLT\n"
IO_PROG = "START: IN 00H\n       OUT 01H\n       HLT\n"


def open_panel(w, app, instant=True):
    w.show_cpu_view()
    _settle(app)
    if instant:
        w.cpu_panel.animate = False
    return w.cpu_panel


def load(w, src):
    set_src(w, src)
    assert w._assemble_and_load()


def step(w, app, n=1):
    for _ in range(n):
        w.cmd_step("into")
        _settle(app, 2)


def panel_texts(p):
    return p.node_texts()


# ------------------------------------------------------------ integration
def test_panel_is_opt_in_and_does_not_change_the_existing_panel_sets(app):
    w = new_window(app, "advanced")
    try:
        assert "cpuview" not in w.docks and not w.cpu_dock.isVisible()
        assert not w.visual.enabled  # hidden: no instrumentation at all
        assert any(a is w.cpu_dock.toggleViewAction() for m in w.menuBar().findChildren(QMenu) for a in m.actions())
        assert all(d.isVisible() for d in w.docks.values())
        open_panel(w, app)
        assert w.cpu_dock.isVisible() and w.visual.enabled and w.cpu_dock.isFloating()
        w.cpu_dock.hide()
        _settle(app)
        assert not w.visual.enabled
    finally:
        close(w, app)


def test_beginner_mode_can_open_it_without_changing_beginner_panels(app):
    w = new_window(app, "beginner")
    try:
        before = sorted(k for k, d in w.docks.items() if d.isVisible())
        open_panel(w, app)
        assert sorted(k for k, d in w.docks.items() if d.isVisible()) == before
        assert w.cpu_dock.isVisible()
    finally:
        close(w, app)


def test_step_into_shows_the_real_change_and_the_flow(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, PROG)
        step(w, app, 3)
        rec = p._rec
        assert rec is not None and rec.text == "ADD B" and w.machine.cpu.a == 0x40
        assert p.nodes["A"].changed and p.nodes["A"].old == 0x3F and p.nodes["A"].value == (0x40, 8)
        assert p.nodes["B"].role == "src" and p.nodes["ALU"].role in ("both", "dst", "src")
        assert p.nodes["FLAGS"].flags_changed == {"AC"}
        assert [f.flow.src + ">" + f.flow.dst for f in p.flow_items if f.flow.phase > 0] == ["B>ALU", "A>ALU", "ALU>A", "ALU>FLAGS"]
        html = p.text.toPlainText()
        assert "3Fh" in html and "40h" in html and "conceptual explanation" in html and "AC changed" in html
        assert p.nodes["IR"].tag == "" and "conceptual" in p.nodes["IR"].toolTip().lower()
    finally:
        close(w, app)


def test_step_over_run_and_pause_work_and_leave_a_summary(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, PROG)
        w.cmd_run()
        wait_until(app, lambda: w.state == "halted")
        assert p._rec is not None and p._rec.kind == "multi" and p._rec.n_instr >= 3
        assert not p.flow_items and w.machine.cpu.a == 0x40
        assert "instructions executed" in p.text.toPlainText()
    finally:
        close(w, app)


def test_breakpoint_stops_and_state_is_not_corrupted(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, PROG)
        w.machine.breakpoints.add(4)
        w.cmd_run()
        wait_until(app, lambda: w.state == "paused")
        assert w.machine.cpu.pc == 4 and p._rec.post.pc == 4
        step(w, app)  # continue stepping after the breakpoint
        assert p._rec.text == "ADD B" and w.machine.cpu.a == 0x40
    finally:
        close(w, app)


def test_reload_and_restart_clear_the_panel(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, PROG)
        step(w, app, 2)
        assert p._rec is not None and len(w.visual.history) == 2
        assert w._assemble_and_load()
        assert p._rec is None and len(w.visual.history) == 0 and not p.flow_items
        assert p.nodes["A"].value == (0, 8)
    finally:
        close(w, app)


def test_in_out_chain_uses_the_trainer_kit(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        w.kit.set_switches(0xA5)
        load(w, IO_PROG)
        step(w, app)
        assert p._rec.text == "IN 00h" and w.machine.cpu.a == 0xA5
        assert [(f.flow.src, f.flow.dst) for f in p.flow_items if f.flow.phase == 2] == [("PORT_IN", "A")]
        assert p.nodes["A"].value == (0xA5, 8) and p.nodes["PORT_IN"].role in ("src", "both")
        assert "A5h" in " ".join(p.nodes["PORT_IN"].extra)
        step(w, app)
        assert [(f.flow.src, f.flow.dst) for f in p.flow_items if f.flow.phase == 2] == [("A", "PORT_OUT")]
        assert w.kit.leds.value == 0xA5 and p.nodes["PORT_OUT"].leds == 0xA5
        assert p.nodes["PORT_OUT"].role == "dst"
    finally:
        close(w, app)


# ------------------------------------------------- prediction answer masking
@pytest.mark.parametrize("mode", ["beginner", "advanced"])
def test_panel_never_leaks_the_experiment_1_answer(app, mode):
    w = new_window(app, mode)
    try:
        p = open_panel(w, app)
        w.kit.set_switches(SW)
        load(w, IO_PROG)
        w.cmd_run()
        wait_until(app, lambda: w.state == "halted")
        assert any(_leaks(t, SW) for t in panel_texts(p))  # sanity: without the experiment the answer IS shown
        w.start_experiment()
        _settle(app)
        assert w.trainer.concealed and p.concealed
        assert [t for t in panel_texts(p) if _leaks(t, SW)] == []
        assert p._rec is None and not p.flow_items
        # stepping is refused while concealed, so no record can appear either
        w.cmd_step("into")
        _settle(app)
        assert p._rec is None and [t for t in panel_texts(p) if _leaks(t, SW)] == []
        w.trainer.guide.predict_edit.setText(f"{SW:08b}")
        w.trainer.guide.lock_prediction()
        _settle(app)
        assert not p.concealed
        assert any(_leaks(t, SW) for t in panel_texts(p))
    finally:
        close(w, app)


def test_help_unmasks_the_panel_too(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        w.kit.set_switches(SW)
        w.start_experiment()
        _settle(app)
        assert p.concealed
        w.trainer.guide.ask_help()
        _settle(app)
        assert not p.concealed
    finally:
        close(w, app)


# ------------------------------------------------------------- animation
def test_animation_never_delays_the_cpu_and_can_be_paused_skipped_and_replayed(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app, instant=False)
        p.reduce_motion = False
        p.animate = True
        p.apply_settings(explain=True, animate=True, reduce_motion=False, speed=0.5)
        load(w, PROG)
        step(w, app, 2)
        ic = w.machine.cpu.icount
        w.cmd_step("into")  # not even a processEvents yet: the CPU has already finished
        assert w.machine.cpu.icount == ic + 1 and w.machine.cpu.a == 0x40
        _settle(app, 2)
        assert p._anim is not None  # animation is running on top of an already-finished step
        p.toggle_pause()
        t0 = p._anim["t"], p._anim["idx"]
        time.sleep(0.05)
        _settle(app)
        assert (p._anim["t"], p._anim["idx"]) == t0 and p._paused
        p.toggle_pause()
        p.skip()
        assert p._anim is None and p.nodes["A"].value == (0x40, 8) and p.nodes["A"].changed
        state_before = capture_state(w.machine.cpu)
        p.replay()
        assert p._anim is not None
        assert p.nodes["A"].value == (0x3F, 8)  # replay starts from the captured pre-state ...
        p.skip()
        assert capture_state(w.machine.cpu) == state_before  # ... and never executes anything
        assert w.machine.cpu.icount == ic + 1
    finally:
        close(w, app)


def test_next_step_during_an_animation_is_not_blocked(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app, instant=False)
        p.apply_settings(explain=True, animate=True, reduce_motion=False, speed=0.5)
        load(w, PROG)
        step(w, app, 2)
        w.cmd_step("into")
        w.cmd_step("into")  # HLT while the previous animation is still playing
        assert w.machine.cpu.halted and p._rec.text == "HLT"
    finally:
        close(w, app)


def test_disabled_animation_and_reduced_motion_show_the_result_at_once(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app, instant=False)
        load(w, PROG)
        p.apply_settings(explain=True, animate=False, reduce_motion=False)
        step(w, app, 3)
        assert p._anim is None and p.nodes["A"].value == (0x40, 8)
        p.apply_settings(explain=True, animate=True, reduce_motion=True)
        assert not p.motion_allowed
        w._assemble_and_load()
        step(w, app, 3)
        assert p._anim is None and p.nodes["A"].changed
    finally:
        close(w, app)


def test_explain_off_shows_only_live_values(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, PROG)
        p.apply_settings(explain=False, animate=False)
        step(w, app, 3)
        assert not p.flow_items and p.nodes["A"].value == (0x40, 8) and not p.nodes["A"].changed
        p.explain_cb.setChecked(True)
        assert p.flow_items and p.nodes["A"].changed
    finally:
        close(w, app)


def test_live_refresh_is_coalesced_while_running(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, "LP: INR B\n    JMP LP\n")
        n0 = p.redraws
        w.cmd_run()
        t0 = time.time()
        while time.time() - t0 < 0.6:
            _settle(app, 1)
            time.sleep(0.005)
        w.cmd_pause()
        _settle(app)
        redraws = p.redraws - n0
        assert w.machine.cpu.icount > 1000 and redraws < 40, redraws  # throttled to roughly 10/s, not per chunk
    finally:
        close(w, app)


def test_cpu_behaviour_is_identical_with_the_panel_open_or_closed(app):
    def run(open_it):
        w = new_window(app, "advanced")
        try:
            if open_it:
                open_panel(w, app)
            load(w, PROG + "")
            w.cmd_run()
            wait_until(app, lambda: w.state == "halted")
            c = w.machine.cpu
            return (tuple(c.regs), c.sp, c.pc, c.f, c.icount, c.tstates, bytes(c.mem.data), tuple(w.machine.out_log))
        finally:
            close(w, app)
    assert run(True) == run(False)


# ------------------------------------------------------- themes / layout
@pytest.mark.parametrize("theme", ["Dark", "Light", "High Contrast"])
def test_all_three_themes_draw_the_diagram(app, theme):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        w._apply_theme(theme)
        load(w, PROG)
        step(w, app, 3)
        img = p.view.grab().toImage()
        colours = {img.pixel(x, y) for x in range(0, img.width(), 7) for y in range(0, img.height(), 7)}
        assert len(colours) > 6
        assert p.pal.theme.name == theme
        assert p.pal.hc == (theme == "High Contrast")
    finally:
        close(w, app)


@pytest.mark.parametrize("size", [(800, 600), (1024, 600), (1280, 720), (1366, 768), (1920, 1080)])
def test_editor_is_never_squeezed_and_the_panel_scrolls_when_small(app, size):
    w = new_window(app, "advanced", size)
    try:
        before = w.editor.width()
        p = open_panel(w, app)
        w.refresh_all()
        _settle(app)
        assert w.editor.width() == before  # a floating panel takes nothing from the editor
        assert w.editor.width() >= 150
        d = w.cpu_dock
        scr = w.screen().availableGeometry()
        assert d.width() <= scr.width() and d.height() <= scr.height()
        assert p.minimumSize().width() <= 520 and p.minimumSize().height() <= 420
        assert p.view.viewport().width() > 100 and p.text.width() > 100
        # docked (not floating) in the right area the editor keeps a usable width as well
        d.setFloating(False)
        _settle(app)
        assert w.editor.width() >= 150
    finally:
        close(w, app)


def test_zoom_fit_and_scrolling(app):
    w = new_window(app, "advanced", (1280, 720))
    try:
        p = open_panel(w, app)
        s0 = p.scale_factor
        p.zoom_by(1.5)
        assert p.scale_factor == pytest.approx(s0 * 1.5) and not p._fit
        p.zoom_by(0.0)
        assert p._fit and p.scale_factor >= 0.55
        for _ in range(12):
            p.zoom_by(1 / 1.15)
        assert p.scale_factor >= 0.3
        p.view.resetTransform()
    finally:
        close(w, app)


# --------------------------------------------------------- accessibility
def test_keyboard_access_tooltips_and_names(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, PROG)
        step(w, app, 3)
        for nid, n in p.nodes.items():
            assert n.flags() & n.GraphicsItemFlag.ItemIsFocusable, nid
            assert n.toolTip().strip(), nid
        for fr in p.frames.values():
            assert fr.toolTip().strip()
        for wdg in (p.explain_cb, p.anim_cb, p.reduce_cb, p.dec_cb, p.pause_btn, p.skip_btn, p.replay_btn,
                    p.fit_btn, p.zoom_in_btn, p.zoom_out_btn, p.speed_combo):
            assert wdg.focusPolicy() != Qt.FocusPolicy.NoFocus
            assert wdg.toolTip() or wdg.accessibleName() or wdg.text()
        assert p.zoom_in_btn.accessibleName() == "Zoom in" and p.view.accessibleName()
        a = p.nodes["A"]
        a.setFocus()
        _settle(app)
        assert "Accumulator A" in p.status.text() and "0x" not in p.status.text()
        a.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
        assert p.scene.focusItem() is p.nodes["ALU"]
        before = p.scale_factor
        p.view.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Plus, Qt.KeyboardModifier.NoModifier))
        assert p.scale_factor > before
        p.view.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_0, Qt.KeyboardModifier.NoModifier))
        assert p._fit
    finally:
        close(w, app)


def test_meaning_is_not_carried_by_colour_alone(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, PROG)
        step(w, app, 3)
        desc = p.nodes["A"].describe()
        assert "changed by the last step" in desc and "was 3Fh" in desc
        assert "source of a data movement" in p.nodes["B"].describe()
        assert any(not f.flow.observed for f in p.flow_items) and any(f.flow.observed for f in p.flow_items)
        styles = {f.pen().style() for f in p.flow_items}
        assert len(styles) >= 2  # solid (observed) and dashed (conceptual) are different line styles
        assert "conceptual explanation" in p.text.toPlainText().lower()
        assert p.nodes["IR"].describe().endswith("conceptual block") or "conceptual" in p.nodes["IR"].describe().lower()
    finally:
        close(w, app)


def test_decimal_option_adds_decimal_values(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        load(w, PROG)
        step(w, app, 3)
        assert "(63 → 64)" not in p.text.toPlainText()
        p.dec_cb.setChecked(True)
        assert p.nodes["A"].decimal and "(63 → 64)" in p.text.toPlainText().replace("→", "→")
    finally:
        close(w, app)


# ------------------------------------------------------------------ labs
@pytest.mark.parametrize("key", ["A", "B", "C"])
def test_each_lab_assembles_runs_and_passes_its_own_checks(app, key):
    w = new_window(app, "advanced")
    try:
        lab = LABS[key]
        w.open_visual_lab(key)
        _settle(app)
        if lab.needs_kit:
            w.kit.set_switches(0x5A)
        w.load_visual_lab(key)
        assert w.live.ok and w.state == "ready"
        # before running, the check must say "not yet"
        w.check_visual_lab(key)
        assert "NOT YET" in w.cpu_panel.labs.view.toPlainText()
        w.cmd_run()
        wait_until(app, lambda: w.state == "halted")
        w.check_visual_lab(key)
        text = w.cpu_panel.labs.view.toPlainText()
        assert "NOT YET" not in text and "Lab complete" in text, text
        if key == "C":
            assert w.kit.leds.value == 0x5A
    finally:
        close(w, app)


def test_lab_c_never_prints_the_led_answer_before_the_student_runs_it(app):
    w = new_window(app, "advanced")
    try:
        w.kit.set_switches(SW)
        w.open_visual_lab("C")
        w.load_visual_lab("C")
        _settle(app)
        texts = [w.cpu_panel.labs.view.toPlainText(), w.editor.toPlainText()]
        assert [t for t in texts if _leaks(t, SW)] == []
        assert LABS["C"].expected == () and not LABS["C"].reveal_expected
    finally:
        close(w, app)


def test_labs_do_not_alter_the_approved_phase1_labs(app):
    w = new_window(app, "advanced")
    try:
        assert [n for n, _ in w.TRAINER_EXAMPLES] == ["E1_read_switches_control_leds.asm", "E1b_seven_segment_raw.asm",
                                                      "E1c_seven_segment_hex.asm"]
        assert kit_view(w.kit).seg_port == 2 and w.kit.display.mode == "raw"
    finally:
        close(w, app)
