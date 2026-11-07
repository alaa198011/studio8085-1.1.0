"""Controlled Step Into cost with the CPU Architecture panel off / docked / floating.

usage: QT_QPA_PLATFORM=offscreen python tools/phase2_step_perf.py

For each mode: a fresh MainWindow (Advanced, 1366x768), a warm-up of 200 Step Into calls (discarded), then 1000 timed
Step Into calls (each includes the window refresh and the panel update). Three runs per mode; the median over the runs
of the mean and of the p95 is printed, in milliseconds, plus the load of the machine while measuring.
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

LOOP = "START: MVI B,00H\nLP:    INR B\n       MOV A,B\n       ADD B\n       JMP LP\n"
WARM, N, RUNS = 200, 1000, 3

QApplication.setOrganizationName("S85stepperf")
QApplication.setApplicationName("S85stepperf")
app = QApplication.instance() or QApplication([])


def run(mode: str) -> tuple[float, float]:
    QSettings().clear()
    QSettings().setValue("mode", "advanced")
    from studio8085.ui.mainwindow import MainWindow
    w = MainWindow()
    w.resize(1366, 768)
    w.show()
    app.processEvents()
    if mode != "off":
        w.show_cpu_view()
        app.processEvents()
        w.cpu_panel.apply_settings(explain=True, animate=False, reduce_motion=True)
        w.cpu_dock.setFloating(mode == "floating")
        app.processEvents()
        assert w.cpu_dock.isVisible() and w.cpu_dock.isFloating() == (mode == "floating"), mode
    w.editor.setPlainText(LOOP)
    w._live_check()
    assert w._assemble_and_load()
    for _ in range(WARM):
        w.cmd_step("into")
        app.processEvents()
    times = []
    for _ in range(N):
        t0 = time.perf_counter()
        w.cmd_step("into")
        app.processEvents()
        times.append((time.perf_counter() - t0) * 1000)
    w.editor.document().setModified(False)
    w.close()
    app.processEvents()
    times.sort()
    return statistics.fmean(times), times[int(0.95 * len(times)) - 1]


if __name__ == "__main__":
    out = {"cpu_count": os.cpu_count()}
    try:
        import psutil
        psutil.cpu_percent(None)
    except ImportError:
        psutil = None
    for mode in ("off", "docked", "floating"):
        res = [run(mode) for _ in range(RUNS)]
        out[mode] = {"mean_ms_runs": [round(r[0], 2) for r in res], "p95_ms_runs": [round(r[1], 2) for r in res],
                     "median_of_means_ms": round(statistics.median(r[0] for r in res), 2),
                     "median_p95_ms": round(statistics.median(r[1] for r in res), 2)}
    if psutil:
        out["cpu_percent_during"] = psutil.cpu_percent(None)
    print(json.dumps(out, indent=2))
