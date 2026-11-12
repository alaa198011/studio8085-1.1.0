"""PR #4 round 3: D1 the CPU panel header wraps in a narrow dock, D2 Enlarge/Restore keeps zoom and scroll,
D3 Experiment 1 masks every general register, pair and flag (presentation only), and the 1.2.0 version bump."""

import re

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from studio8085.ui.mainwindow import CONCEALED_REGISTERS  # noqa: E402
from test_gui import _settle, app, set_src  # noqa: E402,F401
from test_phase2_qa_fixes import every_text, leaks_any_format, machine_state  # noqa: E402
from test_trainer_phase1_fixes import SW, close, new_window  # noqa: E402
from test_visual_gui import open_panel  # noqa: E402


def _header_widgets(p):
    return [w for left, right in p._header_groups for w in left + right]


def _inside(widget, viewport):
    tl = widget.mapTo(viewport, QPoint(0, 0))
    return viewport.rect().contains(QRect(tl, widget.size()))


# ------------------------------------------------ D1
@pytest.mark.parametrize("mode", ["advanced", "beginner"])
@pytest.mark.parametrize("size", [(800, 600), (1024, 600)])
def test_d1_every_header_control_is_inside_the_dock_at_a_small_window(app, mode, size):
    w = new_window(app, mode, size)
    try:
        p = open_panel(w, app)
        w.cpu_dock.setFloating(False)
        w.cpu_dock.show()
        w.cpu_dock.raise_()
        _settle(app, 40)
        scroll = w.cpu_dock.widget()
        assert scroll.horizontalScrollBar().maximum() == 0, "the panel is wider than its dock"
        assert p.width() <= scroll.viewport().width()
        for wd in _header_widgets(p):
            assert wd.isVisible(), wd
            assert _inside(wd, scroll.viewport()), (wd.accessibleName() or wd.text(), wd.geometry(),
                                                    scroll.viewport().rect())
        assert w.editor.width() >= 440
    finally:
        close(w, app)


def test_d1_the_header_wraps_to_more_rows_when_narrow_and_keeps_every_control(app):
    w = new_window(app, "advanced", (1366, 768))
    try:
        p = open_panel(w, app)
        w.cpu_dock.setFloating(True)
        w.cpu_dock.setGeometry(100, 50, 1000, 700)
        _settle(app, 20)
        counts = {}
        for width in (1000, 520, 400, 320):
            w.cpu_dock.resize(width, 700)
            _settle(app, 15)
            rows = p.header.count()
            counts[width] = rows
            seen = []
            for i in range(rows):
                lay = p.header.itemAt(i).layout()
                seen += [lay.itemAt(k).widget() for k in range(lay.count()) if lay.itemAt(k).widget() is not None]
            assert sorted(map(id, seen)) == sorted(map(id, _header_widgets(p))), width
        assert counts[1000] == 2 and counts[320] > counts[1000]
        assert p.minimumSize().width() <= 320
    finally:
        close(w, app)


# ------------------------------------------------ D2
def test_d2_enlarge_then_restore_keeps_the_zoom_and_both_scroll_positions(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        p.size_combo.setCurrentIndex(p.size_combo.findData(1.25))
        _settle(app, 20)
        hb, vb = p.view.horizontalScrollBar(), p.view.verticalScrollBar()
        assert hb.maximum() > 25 and not p._fit
        hb.setValue(25)
        vb.setValue(min(vb.maximum(), 10))
        _settle(app, 5)
        before = (p._fit, p._zoom_pref, round(p.scale_factor, 4), hb.value(), vb.value())
        assert before[3] == 25
        p.set_enlarged(True)
        _settle(app, 30)
        assert p.enlarged
        p.set_enlarged(False)
        for _ in range(30):
            _settle(app, 5)
            QTest.qWait(10)
        after = (p._fit, p._zoom_pref, round(p.scale_factor, 4), p.view.horizontalScrollBar().value(),
                 p.view.verticalScrollBar().value())
        assert after == before
    finally:
        close(w, app)


# ------------------------------------------------ D3
def _row(w, name):
    return next(r for r, (n, *_x) in enumerate(w.registers.ROWS) if n == name)


def test_d3_every_general_register_pair_and_flag_is_masked_and_state_is_untouched(app):
    w = new_window(app, "advanced")
    try:
        p = open_panel(w, app)
        w.kit.set_switches(SW)
        w._set_trace(True)
        # an earlier program left copies of the answer in B, D, H, L and the flags (ANA A)
        set_src(w, "START: IN 00H\n MOV B,A\n MOV D,A\n MOV L,A\n MOV H,A\n ANA A\n OUT 01H\n HLT\n")
        assert w._assemble_and_load()
        for _ in range(8):
            w.cmd_step("into")
            for _ in range(100):
                _settle(app, 1)
                if w.state != "running":
                    break
        cpu = w.machine.cpu
        assert cpu.a == SW and w.state == "halted"
        w.docks["flags"].show()
        w.refresh_all()
        extra = (w.cpu_big,)
        for name in ("A", "B", "D", "H", "L"):  # the stale copies are on screen before the experiment
            assert w.registers.item(_row(w, name), 1).text() == f"{SW:02X}"
        assert any(leaks_any_format(t) for t in every_text(w, extra))
        before = machine_state(w)
        w.start_experiment()
        _settle(app, 20)
        assert w.trainer.concealed
        kinds = {}
        for r, (name, kind, _idx) in enumerate(w.registers.ROWS):
            cells = [w.registers.item(r, k).text() for k in (1, 2, 3)]
            if name in ("PC", "SP"):
                assert "?" not in "".join(cells), name  # PC and SP may stay visible
            else:
                assert name in CONCEALED_REGISTERS
                assert cells[:2] == ["??", "??"], (name, cells)
                assert cells[2] == ("????????" if kind == "r8" else ""), (name, cells)
                assert not (w.registers.item(r, 1).flags() & Qt.ItemFlag.ItemIsEditable)
                kinds.setdefault(kind, set()).add(tuple(cells))
        assert all(len(v) == 1 for v in kinds.values())  # identical placeholders: no hint which register holds what
        assert all(not b.isEnabled() and b.text() == "?" and not b.isChecked() for b in w.flags.buttons.values())
        assert w.flags.fbyte.text() == "F = ??h   ???? ????b"
        assert [t for t in every_text(w, extra) if leaks_any_format(t)] == []
        for nid in ("A", "B", "C", "D", "E", "H", "L", "FLAGS"):
            assert p.nodes[nid].masked, nid
        assert all(fr.masked for fr in p.frames.values())
        drawn = " ".join(t.text for t in p.audit_paint())
        assert drawn.count("????h") == 3 and not re.search(r"\b(BC|DE|HL) = [0-9A-F]{4}h", drawn)
        # presentation only: the CPU, memory, ports and machine are exactly as before
        assert machine_state(w) == before
        assert cpu.a == SW and cpu.regs[0] == SW and cpu.regs[2] == SW and cpu.regs[4] == SW
        # revealed after the prediction
        w.trainer.guide.predict_edit.setText(f"{SW:08b}")
        w.trainer.guide.lock_prediction()
        _settle(app, 20)
        for name in ("A", "B", "D", "H", "L"):
            assert w.registers.item(_row(w, name), 1).text() == f"{SW:02X}"
        assert all(b.isEnabled() for b in w.flags.buttons.values())
        assert "?" not in w.flags.fbyte.text()
        assert not any(p.nodes[n].masked for n in ("A", "B", "H", "FLAGS"))
        assert machine_state(w) == before
    finally:
        close(w, app)


# ------------------------------------------------ release prep
def test_the_version_is_1_2_0_in_every_place_it_is_defined():
    import pathlib

    import studio8085
    root = pathlib.Path(__file__).resolve().parents[1]
    assert studio8085.__version__ == "1.2.0"
    assert 'version = "1.2.0"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    iss = (root / "packaging" / "windows" / "studio8085.iss").read_text(encoding="utf-8")
    assert '#define AppVersion "1.2.0"' in iss
    log = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.2.0]" in log
