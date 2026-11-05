"""Phase 2 performance check: the cost of the CPU Architecture visualizer, on versus off.

usage: python tools/phase2_perf.py [seconds]

Three measurements:
  1. Core: instructions/second of Machine.run_chunk alone vs. with a StepRecorder bracketing each Run.
  2. Single steps: microseconds per Step Into with the recorder disabled vs. enabled (capture + diff).
  3. Whole app: instructions executed in a fixed time at Max speed, panel hidden vs. panel visible
     (this includes the throttled live redraws). Uses the real Qt platform unless QT_QPA_PLATFORM is set.
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studio8085.core.assembler import assemble
from studio8085.core.machine import Machine
from studio8085.core.visual import StepRecorder

LOOP = "START: MVI B,00H\nLP:    INR B\n       MOV A,B\n       ADD B\n       JMP LP\n"
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0


def machine():
    m = Machine()
    m.load(assemble(LOOP))
    return m


def core_run(with_rec: bool) -> float:
    m = machine()
    rec = StepRecorder(m)
    rec.enabled = with_rec
    m.start("run")
    rec.begin("run")
    t0 = time.perf_counter()
    n0 = m.cpu.icount
    while time.perf_counter() - t0 < SECONDS:
        m.run_chunk(20_000)
    dt = time.perf_counter() - t0
    rec.end()
    return (m.cpu.icount - n0) / dt


def step_cost(with_rec: bool, n: int = 20_000) -> float:
    m = machine()
    rec = StepRecorder(m)
    rec.enabled = with_rec
    t0 = time.perf_counter()
    for _ in range(n):
        rec.begin("into")
        m.step_into()
        rec.end()
    return (time.perf_counter() - t0) / n * 1e6


def app_run(panel: bool) -> dict:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QApplication.setOrganizationName("S85perf")
    QApplication.setApplicationName("S85perf")
    app = QApplication.instance() or QApplication([])
    QSettings().clear()
    QSettings().setValue("mode", "advanced")
    from studio8085.ui.mainwindow import MainWindow
    w = MainWindow()
    w.resize(1366, 768)
    w.show()
    app.processEvents()
    if panel:
        w.show_cpu_view()
        app.processEvents()
        w.cpu_panel.animate = False
    w.editor.setPlainText(LOOP)
    w._live_check()
    assert w._assemble_and_load()
    w.speed.setCurrentIndex(0)  # Max speed
    n0 = w.machine.cpu.icount
    redraws0 = w.cpu_panel.redraws
    w.cmd_run()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < SECONDS:
        app.processEvents()
    dt = time.perf_counter() - t0
    done = w.machine.cpu.icount - n0
    w.cmd_pause()
    out = {"ips": done / dt, "redraws": w.cpu_panel.redraws - redraws0, "seconds": dt}
    w.editor.document().setModified(False)
    w.close()
    app.processEvents()
    return out


def best(f, *a, k=3):
    return statistics.median(f(*a) for _ in range(k))


if __name__ == "__main__":
    res = {}
    off, on = best(core_run, False), best(core_run, True)
    res["core_ips_off"], res["core_ips_on"] = off, on
    res["core_overhead_pct"] = (off - on) / off * 100
    so, sn = best(step_cost, False), best(step_cost, True)
    res["step_us_off"], res["step_us_on"], res["step_extra_us"] = so, sn, sn - so
    if os.environ.get("PHASE2_PERF_NO_APP") != "1":
        a_off = [app_run(False) for _ in range(3)]
        a_on = [app_run(True) for _ in range(3)]
        res["app_ips_hidden"] = statistics.median(r["ips"] for r in a_off)
        res["app_ips_visible"] = statistics.median(r["ips"] for r in a_on)
        res["app_overhead_pct"] = (res["app_ips_hidden"] - res["app_ips_visible"]) / res["app_ips_hidden"] * 100
        res["app_redraws_per_sec_visible"] = statistics.median(r["redraws"] / r["seconds"] for r in a_on)
    print(json.dumps(res, indent=2))
