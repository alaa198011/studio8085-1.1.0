"""Phase 2 visual QA: real-window screenshots of the CPU Architecture panel.

usage: python tools/phase2_shots.py OUTDIR [prefix]

Run it WITHOUT QT_QPA_PLATFORM=offscreen so that real Windows windows and fonts are used (the offscreen platform
on Windows has no fonts). To test display scaling set QT_SCALE_FACTOR (for example 1.5 or 2) in the environment
and pass a prefix such as ``s150``. Files written: sizes, themes, labs, Experiment 1 masking, a generic instruction.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

out = Path(sys.argv[1])
prefix = (sys.argv[2] + "_") if len(sys.argv) > 2 else ""
out.mkdir(parents=True, exist_ok=True)
QApplication.setOrganizationName("S85shots")
QApplication.setApplicationName("S85shots")
app = QApplication([])
QSettings().clear()
QSettings().setValue("mode", "advanced")
from studio8085.core.lab_content import LABS  # noqa: E402
from studio8085.ui.mainwindow import MainWindow  # noqa: E402


def settle(n=30, delay=0.01):
    for _ in range(n):
        app.processEvents()
        time.sleep(delay)


w = MainWindow()
w.resize(1366, 768)
w.show()
settle()
w.show_cpu_view()
settle()
p = w.cpu_panel
p.apply_settings(explain=True, animate=False, reduce_motion=False)
saved = []


def shot(widget, name):
    settle(8)
    path = out / f"{prefix}{name}.png"
    widget.grab().save(str(path))
    saved.append(path.name)


def panel_shot(name):
    shot(w.cpu_dock, name)


def run_lab(key, steps, kit_switches=None):
    w.editor.document().setModified(False)
    w.open_visual_lab(key)
    if kit_switches is not None:
        w.kit.set_switches(kit_switches)
    w.load_visual_lab(key)
    for _ in range(steps):
        w.cmd_step("into")
        settle(3)


# ---- labs, one screenshot per lab (+ the mid-step states for Lab C)
run_lab("A", 3)
panel_shot("lab_A_register_transfer")
run_lab("B", 3)
panel_shot("lab_B_alu_flags")
run_lab("B", 6)
panel_shot("lab_B_final_flags")
run_lab("C", 1, kit_switches=0xA5)
panel_shot("lab_C_after_IN")
w.cmd_step("into")
settle(3)
panel_shot("lab_C_after_OUT")
w.cmd_step("into")
settle(3)
w.check_visual_lab("C")
p.tabs.setCurrentWidget(p.labs)
panel_shot("lab_C_feedback")
shot(w, "main_window_with_lab_C")

# ---- themes (same step in each)
run_lab("A", 3)
for theme in ("Dark", "Light", "High Contrast"):
    w._apply_theme(theme)
    settle(5)
    panel_shot("theme_" + theme.lower().replace(" ", "_"))

# ---- generic instruction (no detailed visual) and a stack instruction
w._apply_theme("Dark")
w.editor.setPlainText("START: LXI H,1234H\n       DAD H\n       PUSH H\n       HLT\n")
w._live_check()
w._assemble_and_load()
w.cmd_step("into")
w.cmd_step("into")
settle(3)
panel_shot("generic_DAD")
w.cmd_step("into")
settle(3)
panel_shot("stack_PUSH")

# ---- mid-animation frame
p.apply_settings(explain=True, animate=True, reduce_motion=False, speed=0.5)
w._assemble_and_load()
w.cmd_step("into")
w.cmd_step("into")
w.cmd_step("into")
t0 = time.time()
while time.time() - t0 < 0.9:
    app.processEvents()
    time.sleep(0.01)
panel_shot("animation_midway")
p.skip()
p.apply_settings(explain=True, animate=False, reduce_motion=False)

# ---- Experiment 1: masked before the prediction
w.kit.set_switches(0x93)
w.start_experiment()
settle(10)
panel_shot("experiment1_masked_before_prediction")
shot(w, "experiment1_main_window_masked")

# ---- window sizes: real top-level window at each size with the panel open (docked beside the editor)
w.trainer.guide.ask_help()
settle(5)
for (sw, sh) in ((800, 600), (1024, 600), (1280, 720), (1366, 768), (1920, 1080)):
    w.showNormal()
    w.resize(sw, sh)
    settle(15)
    w.cpu_dock.setFloating(False)
    settle(10)
    shot(w, f"size_{sw}x{sh}_docked")
    w.cpu_dock.setFloating(True)
    settle(10)
    w.show_cpu_view()
    settle(10)
    shot(w, f"size_{sw}x{sh}_main")
    panel_shot(f"size_{sw}x{sh}_panel")

# ---- the smallest the panel can get: it scrolls instead of squeezing the labels
w.cpu_dock.setFloating(True)
w.cpu_dock.resize(540, 440)
settle(15)
p.zoom_by(0.0)
settle(10)
panel_shot("panel_smallest_540x440")
p.zoom_by(1.5)
panel_shot("panel_zoomed_in")
p.zoom_by(0.0)
w.cpu_dock.resize(1000, 760)
settle(10)

# ---- a real screen capture of the desktop with everything on it
screen = w.screen()
settle(10)
screen.grabWindow(0).save(str(out / f"{prefix}desktop_real_screen.png"))
saved.append(f"{prefix}desktop_real_screen.png")
w.editor.document().setModified(False)
w.close()
print(len(saved), "screenshots:", *saved, sep="\n  ")
