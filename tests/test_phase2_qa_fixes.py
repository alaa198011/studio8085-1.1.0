"""PR #4 QA fixes: (1) Experiment 1 must not show a stale A in the Registers dock (or anywhere else) before the
prediction, (2) Ctrl+= / Ctrl+- zoom the CPU panel when it has the focus and the editor otherwise, (3) the run/step
keys work while the CPU view is enlarged, (4) no flow arrow crosses a register-pair title. Offscreen GUI tests."""

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QFontMetricsF, QPainterPath, QPainterPathStroker  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QTableView, QTableWidget, QWidget  # noqa: E402

from studio8085.core.visual import PAIRS, Flow  # noqa: E402
from studio8085.ui import cpuview  # noqa: E402
from test_gui import _settle, app, set_src  # noqa: E402,F401
from test_trainer_phase1_fixes import SW, _leaks, close, new_window, prepare, visible_texts  # noqa: E402
from test_visual_gui import open_panel  # noqa: E402

CTRL = Qt.KeyboardModifier.ControlModifier


def activate(win, app):
    """Make ``win`` the active window. The offscreen platform does not always follow activateWindow(), and the
    focus-aware keys need a real active window, so fall back to the (deprecated but working) explicit call."""
    win.activateWindow()
    _settle(app, 10)
    if QApplication.activeWindow() is not win:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            QApplication.setActiveWindow(win)
        _settle(app, 10)
    assert QApplication.activeWindow() is win


# ------------------------------------------------ 1. no stale A in the Registers dock
def dock_texts(w, with_panel):
    """Every value the Registers, Flags, Memory, Stack, Symbols and Listing docks, the status bar and
    (optionally) the CPU diagram can show."""
    out = []
    for root in (w.registers, w.flags, w.memory, w.stack, w.symbols, w.listing, w.msg, w.pc_label):
        for c in [root] + root.findChildren(QWidget):
            out += [c.toolTip(), c.accessibleName(), c.accessibleDescription()]
            if isinstance(c, QLabel):
                out.append(c.text())
            if isinstance(c, QTableWidget):
                out += [c.item(r, k).text() for r in range(c.rowCount()) for k in range(c.columnCount())
                        if c.item(r, k) is not None]
            elif isinstance(c, QTableView) and c.model() is not None:
                m = c.model()
                for r in range(m.rowCount()):
                    for k in range(m.columnCount()):
                        for role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
                            v = m.index(r, k).data(role)
                            if v is not None:
                                out.append(str(v))
    if with_panel:
        out += w.cpu_panel.node_texts() + [t.text for t in w.cpu_panel.audit_paint()]
    return [t for t in out if t]


def a_row(w):
    return [w.registers.item(0, k).text() for k in (1, 2, 3)]


@pytest.mark.parametrize("mode", ["beginner", "advanced"])
@pytest.mark.parametrize("panel", [False, True])
def test_a_run_then_a_new_experiment_with_the_same_switches_shows_no_stale_a(app, mode, panel):
    w = prepare(app, mode)  # IN/OUT already run: A == SW is left in the CPU
    try:
        if panel:
            open_panel(w, app)
        assert w.registers.item(0, 0).text() == "A" and a_row(w)[0] == f"{SW:02X}"  # the stale value IS shown
        assert any(_leaks(t) for t in dock_texts(w, panel))  # sanity: the sweep has teeth
        w.start_experiment()
        _settle(app)
        assert w.trainer.concealed
        assert a_row(w) == ["??", "??", "????????"]
        leaks = [t for t in dock_texts(w, panel) + visible_texts(w) if _leaks(t)]
        assert leaks == []
        assert str(SW) not in " ".join(dock_texts(w, panel)).split()
        assert not (w.registers.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable)  # cannot be opened for editing
        assert w.machine.cpu.a == SW  # display only: the CPU still holds it
        w.refresh_all()  # a refresh while concealed must not bring it back
        _settle(app)
        assert a_row(w)[0] == "??"
        # the student predicts: A is shown again, with its real value
        w.trainer.guide.predict_edit.setText(f"{SW:08b}")
        w.trainer.guide.lock_prediction()
        _settle(app)
        assert not w.trainer.concealed
        assert a_row(w) == [f"{SW:02X}", str(SW), f"{SW:08b}"]
        assert w.registers.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable
    finally:
        close(w, app)


@pytest.mark.parametrize("how", ["help", "end"])
def test_a_is_revealed_by_help_and_by_ending_the_experiment(app, how):
    w = prepare(app, "advanced")
    try:
        w.start_experiment()
        _settle(app)
        assert a_row(w)[0] == "??"
        if how == "help":
            w.trainer.guide.ask_help()
        else:
            w.trainer.hide_guide()
        _settle(app)
        assert a_row(w)[0] == f"{SW:02X}"
    finally:
        close(w, app)


def test_pc_and_sp_stay_visible_while_the_general_registers_are_masked(app):
    w = prepare(app, "advanced")
    try:
        w.machine.cpu.regs[0] = 0x12  # B
        w.start_experiment()
        _settle(app, 5)
        assert w.registers.item(1, 0).text() == "B" and w.registers.item(1, 1).text() == "??"
        names = {w.registers.item(r, 0).text(): w.registers.item(r, 1).text() for r in range(w.registers.rowCount())}
        assert names["PC"] != "??" and names["SP"] != "??"
    finally:
        close(w, app)


# ------------------------------------------------ 2. Ctrl+= / Ctrl+- (focus-aware)
def fsz(w):
    return w.editor.font().pointSizeF()


def press(target, key):
    QTest.keyClick(target, key, CTRL)
    QApplication.processEvents()


KEYS = ((Qt.Key.Key_Equal, 1), (Qt.Key.Key_Minus, -1))


def check_panel_zoom(w, app, target):
    p = w.cpu_panel
    for key, sign in KEYS:
        p.zoom_by(0.0)
        _settle(app, 5)
        f0, s0 = fsz(w), p.scale_factor
        press(target, key)
        _settle(app, 5)
        assert fsz(w) == f0, "the editor must not zoom while the CPU panel has the focus"
        assert (p.scale_factor > s0) if sign > 0 else (p.scale_factor < s0), (key, s0, p.scale_factor)


@pytest.mark.parametrize("where", ["docked", "floating", "enlarged"])
def test_ctrl_equal_and_minus_zoom_the_cpu_panel_when_it_has_the_focus(app, where):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        if where == "floating":
            w.cpu_dock.setFloating(True)
            w.cpu_dock.setGeometry(300, 20, 1000, 760)
        elif where == "enlarged":
            p.set_enlarged(True)
        _settle(app, 20)
        activate(w.cpu_big if where == "enlarged" else w.cpu_dock, app)
        p.view.setFocus()
        _settle(app, 10)
        check_panel_zoom(w, app, p.view)
        p.zoom_in_btn.setFocus()
        _settle(app, 5)
        check_panel_zoom(w, app, p.zoom_in_btn)  # any widget inside the panel counts
    finally:
        if w.cpu_big is not None:
            w.cpu_panel.set_enlarged(False)
        close(w, app)


@pytest.mark.parametrize("where", ["docked", "floating"])
def test_ctrl_equal_and_minus_still_zoom_the_editor_when_the_editor_has_the_focus(app, where):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        if where == "floating":
            w.cpu_dock.setFloating(True)
            w.cpu_dock.setGeometry(300, 20, 1000, 760)
        _settle(app, 20)
        activate(w, app)
        w.editor.setFocus()
        _settle(app, 10)
        assert QApplication.focusWidget() is w.editor
        for key, sign in KEYS:
            p.zoom_by(0.0)
            _settle(app, 5)
            f0, s0 = fsz(w), p.scale_factor
            press(w.editor, key)
            assert (fsz(w) > f0) if sign > 0 else (fsz(w) < f0), (key, f0, fsz(w))
            assert p.scale_factor == s0, "the CPU panel must not zoom while the editor has the focus"
            w.editor.zoom(-sign)  # restore
    finally:
        close(w, app)


def test_the_zoom_tooltips_are_accurate_and_the_menu_still_zooms_the_editor(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        assert "Ctrl+=" in p.zoom_in_btn.toolTip() and "focus" in p.zoom_in_btn.toolTip()
        assert "Ctrl+-" in p.zoom_out_btn.toolTip() and "focus" in p.zoom_out_btn.toolTip()
        assert w.a_zoom_in.shortcut().toString() == "Ctrl+=" and w.a_zoom_out.shortcut().toString() == "Ctrl+-"
        activate(w, app)
        w.editor.setFocus()
        _settle(app, 5)
        f0 = fsz(w)
        w.a_zoom_in.trigger()
        assert fsz(w) > f0
        w.a_zoom_out.trigger()
        assert fsz(w) == f0
        activate(w.cpu_dock if w.cpu_dock.isFloating() else w, app)
        p.view.setFocus()  # focus in the panel: the same action zooms the diagram instead
        _settle(app, 5)
        s0 = p.scale_factor
        w.a_zoom_in.trigger()
        assert p.scale_factor > s0 and fsz(w) == f0
    finally:
        close(w, app)


# ------------------------------------------------ 3. run / step keys while enlarged
LOOP = "START: MVI A,01H\n MVI B,02H\n MVI C,03H\n HLT\n"


@pytest.mark.parametrize("key,check", [(Qt.Key.Key_F11, "step"), (Qt.Key.Key_F10, "step"), (Qt.Key.Key_F5, "run")])
def test_run_and_step_keys_work_while_the_cpu_view_is_enlarged(app, key, check):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        set_src(w, LOOP)
        assert w._assemble_and_load()
        p.set_enlarged(True)
        _settle(app, 20)
        assert w.cpu_big is not None and p.enlarged
        activate(w.cpu_big, app)
        p.view.setFocus()
        _settle(app, 10)
        n0 = w.machine.cpu.icount
        QTest.keyClick(p.view, key)
        for _ in range(100):
            _settle(app, 2)
            if check == "step" or w.state == "halted":
                break
        if check == "step":
            assert w.machine.cpu.icount == n0 + 1
            assert w.machine.cpu.a == 1
        else:
            assert w.state == "halted" and w.machine.cpu.regs[1] == 3
        assert p.enlarged  # the view stayed enlarged
    finally:
        if w.cpu_big is not None:
            w.cpu_panel.set_enlarged(False)
        close(w, app)


def test_the_enlarged_window_lends_and_takes_back_the_actions(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        p.set_enlarged(True)
        _settle(app)
        big = w.cpu_big
        assert {w.a_into, w.a_over, w.a_out, w.a_run, w.a_stop} <= set(big.actions())
        p.set_enlarged(False)
        _settle(app)
        assert w.cpu_big is None and w.a_into not in big.actions()
        assert w.a_into.shortcut().toString() == "F11"
    finally:
        close(w, app)


# ------------------------------------------------ 4. no arrow across a pair title
def _title_rects(p):
    out = {}
    for rec in p.audit_paint():
        if rec.nid in PAIRS and rec.text.startswith("Register pair"):
            gx, gy, _, _ = cpuview.GEOM[rec.nid]
            width = QFontMetricsF(rec.font).horizontalAdvance(rec.text)
            out[rec.nid] = QRectF(gx + rec.rect.x(), gy + rec.rect.y(), width, rec.rect.height() - 6)
    return out


def test_no_flow_arrow_or_bus_tap_crosses_a_register_pair_title(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        titles = _title_rects(p)
        assert set(titles) == set(PAIRS)
        nodes = list(cpuview.GEOM)
        paths = []
        for s in nodes:
            for d in nodes:
                for kind in ("data8", "data16", "addr16"):
                    paths.append((f"{s}->{d} {kind}", cpuview.route(Flow(s, d, kind, "", 0))))
        for nid in ("IR", "A", "ALU", "FLAGS", "B", "C", "D", "E", "H", "L", "MEM", "PORT_IN", "PORT_OUT"):
            pts = cpuview._data_tap(nid)
            pp = QPainterPath(pts[0])
            for pt in pts[1:]:
                pp.lineTo(pt)
            paths.append((f"tap {nid}", pp))
        st = QPainterPathStroker()
        st.setWidth(6.0)  # the arrow pen is 4 wide
        bad = [(name, pid) for name, path in paths if path.elementCount() > 1
               for pid, r in titles.items() if st.createStroke(path).intersects(r)]
        assert bad == [], bad
    finally:
        close(w, app)


# ------------------------------------------------ audit: every surface, every number format, state untouched
import re  # noqa: E402

from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QAbstractButton, QTabBar  # noqa: E402


def leaks_any_format(text: str, sw: int = SW) -> bool:
    """The secret byte as hex, binary (also grouped), unsigned decimal or signed decimal, as a number of its own."""
    if _leaks(text, sw):
        return True
    nums = re.findall(r"(?<![0-9A-Za-z.])-?\d+(?![0-9A-Za-z])", text)
    return str(sw) in nums or str(sw - 256) in nums


def every_text(w, extra_windows=()):
    """All strings reachable from the main window and the given extra top-level windows: widget text, tooltips,
    accessible names/descriptions, status tips, table and list models, text edits, the diagram's scene texts."""
    out = []
    roots = [w] + [x for x in extra_windows if x is not None]
    seen = set()
    for root in roots:
        for c in [root] + root.findChildren(QWidget):
            if id(c) in seen:
                continue
            seen.add(id(c))
            out += [c.toolTip(), c.accessibleName(), c.accessibleDescription(), c.statusTip(), c.windowTitle()]
            if isinstance(c, (QLabel, QAbstractButton)):
                out.append(c.text())
            if isinstance(c, QLineEdit):
                out += [c.text(), c.placeholderText()]
            if isinstance(c, (QPlainTextEdit, QTextEdit)) and c is not w.editor:
                out.append(c.toPlainText())
            if isinstance(c, QComboBox):
                out += [c.itemText(i) for i in range(c.count())]
            if isinstance(c, QTabBar):
                out += [c.tabText(i) + c.tabToolTip(i) for i in range(c.count())]
            if isinstance(c, QTableWidget):
                out += [c.item(r, k).text() for r in range(c.rowCount()) for k in range(c.columnCount())
                        if c.item(r, k) is not None]
            elif isinstance(c, QTableView) and c.model() is not None:
                m = c.model()
                for r in range(m.rowCount()):
                    for k in range(m.columnCount()):
                        if m is w.io.model and k == 0:
                            continue  # the port number is an address, not a value
                        for role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole,
                                     Qt.ItemDataRole.EditRole, Qt.ItemDataRole.AccessibleTextRole):
                            v = m.index(r, k).data(role)
                            if v is not None:
                                out.append(str(v))
    p = w.cpu_panel
    if p is not None:
        out += p.node_texts() + [t.text for t in p.audit_paint()]
        out += [it.toolTip() for it in p.scene.items()]
    return [t for t in out if t]


def machine_state(w):
    c = w.machine.cpu
    return (c.a, list(c.regs), c.pc, c.sp, c.flags_byte() if hasattr(c, "flags_byte") else None, list(c.io),
            bytes(c.mem.data), c.icount, c.tstates, w.machine.out_count, list(w.machine.out_log),
            w.kit.switches.value, w.kit.leds.value if hasattr(w.kit, "leds") and hasattr(w.kit.leds, "value") else None,
            w.state, len(w.machine.trace))


def run_with_panel(app, mode, enlarged):
    w = new_window(app, mode)
    p = open_panel(w, app)
    w.kit.set_switches(SW)
    w._set_trace(True)
    set_src(w, "START: IN 00H\n       OUT 01H\n       HLT\n")
    assert w._assemble_and_load()
    for _ in range(3):
        w.cmd_step("into")
        for _ in range(100):
            _settle(app, 1)
            if w.state != "running":
                break
    assert w.machine.cpu.a == SW and w.state == "halted"
    assert p._rec is not None  # the diagram has a finished step (flows, captions, explanation) to leak from
    if enlarged:
        p.set_enlarged(True)
        _settle(app, 20)
        assert w.cpu_big is not None
    return w, p


@pytest.mark.parametrize("mode,enlarged", [("advanced", False), ("advanced", True), ("beginner", False)])
def test_audit_no_surface_shows_the_concealed_value_in_any_format_and_state_is_untouched(app, mode, enlarged):
    w, p = run_with_panel(app, mode, enlarged)
    try:
        for dock in ("memory", "stack", "io", "symbols", "trace", "output", "explain", "registers", "flags"):
            if dock in w.docks:
                w.docks[dock].show()
        w.docks["trainer"].show()
        w.refresh_all()
        _settle(app, 10)
        extra = (w.cpu_big,)
        assert any(leaks_any_format(t) for t in every_text(w, extra))  # the sweep has teeth: unmasked it finds it
        before = machine_state(w)
        w.start_experiment()
        _settle(app, 20)
        assert w.trainer.concealed and p.concealed
        bad = sorted({t[:100] for t in every_text(w, extra) if leaks_any_format(t)})
        assert bad == [], bad
        # presentation only: nothing about the CPU, memory, ports, the machine or the debugger moved
        assert machine_state(w) == before
        assert w.machine.cpu.a == SW
        assert not p.replay_btn.isEnabled()  # no replay of the hidden step
        w.refresh_all()
        _settle(app, 10)
        assert [t for t in every_text(w, extra) if leaks_any_format(t)] == []
        assert machine_state(w) == before
        w.trainer.guide.predict_edit.setText(f"{SW:08b}")
        w.trainer.guide.lock_prediction()
        _settle(app, 20)
        assert any(leaks_any_format(t) for t in every_text(w, extra))  # revealed after the prediction
        assert machine_state(w) == before
    finally:
        if w.cpu_big is not None:
            w.cpu_panel.set_enlarged(False)
        close(w, app)


# ------------------------------------------------ F11 while enlarged, for every place the focus can be
from PySide6.QtWidgets import QAbstractScrollArea  # noqa: E402


def _focus_targets(p):
    p.tabs.setCurrentWidget(p.labs)
    inner = [c for c in p.labs.findChildren(QWidget) if c.focusPolicy() != Qt.FocusPolicy.NoFocus]
    combo = next((c for c in inner if isinstance(c, QComboBox)), None)
    scroll = next((c for c in inner if isinstance(c, QAbstractScrollArea)), None)
    return {"view": p.view, "button": p.zoom_in_btn, "labs_tab_bar": p.tabs.tabBar(), "labs_widget": p.labs,
            "labs_combo": combo, "labs_text": scroll, "checkbox": p.explain_cb, "speed": p.speed_combo}


@pytest.mark.parametrize("target", ["view", "button", "labs_tab_bar", "labs_widget", "labs_combo", "labs_text",
                                    "checkbox", "speed"])
@pytest.mark.parametrize("key", [Qt.Key.Key_F11, Qt.Key.Key_F10])
def test_step_into_and_over_work_while_enlarged_with_the_focus_inside_the_panel(app, target, key):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        set_src(w, LOOP)
        assert w._assemble_and_load()
        p.set_enlarged(True)
        _settle(app, 20)
        activate(w.cpu_big, app)
        widget = _focus_targets(p)[target]
        assert widget is not None
        widget.setFocus()
        _settle(app, 10)
        assert QApplication.focusWidget() is not None and (
            QApplication.focusWidget() is widget or widget.isAncestorOf(QApplication.focusWidget())
            or QApplication.focusWidget().isAncestorOf(widget) or p.isAncestorOf(QApplication.focusWidget()))
        n0 = w.machine.cpu.icount
        QTest.keyClick(QApplication.focusWidget(), key)
        _settle(app, 20)
        assert w.machine.cpu.icount == n0 + 1, f"{key} did nothing with the focus on {target}"
        assert p.enlarged
    finally:
        if w.cpu_big is not None:
            w.cpu_panel.set_enlarged(False)
        close(w, app)


# ------------------------------------------------ the shortcut map: nothing ambiguous, nothing lost
EXPECTED_KEYS = {"a_run": "F5", "a_stop": "Shift+F5", "a_restart": "Ctrl+Shift+F5", "a_into": "F11", "a_over": "F10",
                 "a_out": "Shift+F11", "a_cursor": "Ctrl+F10", "a_bp": "F9", "a_assemble": "F7", "a_pause": "F6",
                 "a_zoom_in": "Ctrl+=", "a_zoom_out": "Ctrl+-", "a_find": "Ctrl+F", "a_goto": "Ctrl+G",
                 "a_comment": "Ctrl+/", "a_theme": "Ctrl+T", "a_ref": "F1", "a_prefs": "Ctrl+,", "a_quit": "Ctrl+Q",
                 "a_saveas": "Ctrl+Shift+S", "a_findnext": "F3", "a_findprev": "Shift+F3", "a_instr": "Ctrl+I"}


def _active_bindings(owner_window):
    """(key, owner) for every enabled QAction shortcut and QShortcut that is live in this top-level window."""
    from PySide6.QtGui import QAction, QShortcut
    out = []
    for a in owner_window.findChildren(QAction) + owner_window.actions():
        if a.isEnabled():
            out += [(s.toString(), f"action:{a.text()}") for s in a.shortcuts()]
    for sc in owner_window.findChildren(QShortcut):
        if sc.isEnabled():
            out.append((sc.key().toString(), "shortcut"))
    return out


def _duplicates(bindings):
    seen, dup = {}, set()
    for key, who in bindings:
        if key in seen and seen[key] != who or (key in seen and who == "shortcut"):
            dup.add(key)
        seen.setdefault(key, who)
    return dup


def test_existing_shortcuts_are_unchanged_and_none_is_ambiguous(app):
    from PySide6.QtGui import QAction
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        for attr, key in EXPECTED_KEYS.items():
            assert getattr(w, attr).shortcut().toString() == key, attr
        # docked / floating: the main window and everything in it (the panel is a child) share one key space
        for floating in (False, True):
            w.cpu_dock.setFloating(floating)
            _settle(app, 10)
            b = _active_bindings(w)
            assert _duplicates(b) == set(), (floating, _duplicates(b))
            assert not any(sc.isEnabled() for sc in p._zoom_shortcuts)  # the window owns Ctrl+= / Ctrl+-
        # enlarged: the separate window has its own key space (lent actions + the panel's own shortcuts)
        p.set_enlarged(True)
        _settle(app, 20)
        big = w.cpu_big
        keys = [(s.toString(), a.text()) for a in big.actions() for s in a.shortcuts()]
        keys += [(sc.key().toString(), "panel") for sc in p._shortcuts if sc.isEnabled()]
        names = [k for k, _ in keys]
        assert len(names) == len(set(names)), [k for k in names if names.count(k) > 1]
        assert {"F5", "F10", "F11", "Shift+F11", "Ctrl+=", "Ctrl+-", "Esc", "Ctrl+Shift+F"} <= set(names)
        p.set_enlarged(False)
        _settle(app, 20)
        assert not any(sc.isEnabled() for sc in p._zoom_shortcuts)
        for attr, key in EXPECTED_KEYS.items():
            assert getattr(w, attr).shortcut().toString() == key, attr
        # every other action in the window: no two share a key
        allk = [s.toString() for a in w.findChildren(QAction) for s in a.shortcuts() if a.isEnabled()]
        assert len(allk) == len(set(allk)), [k for k in allk if allk.count(k) > 1]
    finally:
        close(w, app)
