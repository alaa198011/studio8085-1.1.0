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
w.editor.setPlainText("START: LXI SP,2100H\n       LXI H,1234H\n       DAD H\n       PUSH H\n       PUSH PSW\n"
                      "       POP D\n       CALL SUBR\n       HLT\nSUBR:  RET\n")
w._live_check()
w._assemble_and_load()
for _ in range(3):
    w.cmd_step("into")
settle(3)
panel_shot("generic_DAD")
w.cmd_step("into")
settle(3)
panel_shot("stack_PUSH")
for theme in ("Light", "High Contrast"):
    w._apply_theme(theme)
    settle(5)
    panel_shot("stack_PUSH_" + theme.lower().replace(" ", "_"))
w._apply_theme("Dark")
settle(5)
for name in ("PSW", "POP", "CALL", "RET"):  # the stack pointer's contents follow every stack instruction
    w.cmd_step("into")
    settle(3)
    panel_shot("stack_" + name)

# ---- memory cells used by a step: the diagram's Memory area and the Memory dock
md = w.docks["memory"]
md.show()
md.setFloating(True)  # a taller window, so the hex table with the marked cells is in the picture
md.resize(640, 640)
settle(10)
w.editor.setPlainText("START: LXI SP,2100H\n       LXI H,3000H\n       MVI A,3FH\n       STA 2000H\n       LDA 2000H\n"
                      "       MOV M,A\n       INR M\n       HLT\n")
w._live_check()
w._assemble_and_load()
for _ in range(4):
    w.cmd_step("into")
settle(5)
panel_shot("memory_access_STA")
shot(w.docks["memory"], "memory_dock_marks_STA")
w.cmd_step("into")
settle(5)
panel_shot("memory_access_LDA")
w.cmd_step("into")
w.cmd_step("into")
settle(5)
panel_shot("memory_access_INR_M")
shot(w.docks["memory"], "memory_dock_marks_INR_M")
md.setFloating(False)
settle(10)

# ---- the enlarge (full window) button
w.cpu_dock.setFloating(True)
w.show_cpu_view()
settle(5)
p.max_btn.click()
settle(25)
shot(w.cpu_big, "enlarged_view")
p.tabs.setCurrentWidget(p.labs)
shot(w.cpu_big, "enlarged_view_labs")
p.tabs.setCurrentWidget(p.text)
p.max_btn.click()
settle(10)

# ---- a stepped (not masked) state in every theme and at the two extreme window sizes
for theme in ("Dark", "Light", "High Contrast"):
    w._apply_theme(theme)
    settle(5)
    p.zoom_by(0.0)
    panel_shot("stepped_panel_" + theme.lower().replace(" ", "_"))
w._apply_theme("Dark")
for (sw, sh) in ((800, 600), (1366, 768)):
    w.showNormal()
    w.resize(sw, sh)
    settle(15)
    w.cpu_dock.setFloating(False)
    w.cpu_dock.show()
    w.cpu_dock.raise_()
    settle(15)
    shot(w, f"stepped_docked_{sw}x{sh}")
    w.cpu_dock.setFloating(True)
    w.show_cpu_view()
    settle(10)
w.showNormal()
w.resize(1366, 768)
settle(10)

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

# ---- window sizes: a real top-level window at each size, in every theme, with the panel docked beside the
# editor (tabbed with the other docks on narrow windows) and floating
w.trainer.guide.ask_help()
settle(5)
for theme in ("Dark", "Light", "High Contrast"):
    tag = theme.lower().replace(" ", "_")
    w._apply_theme(theme)
    settle(5)
    for (sw, sh) in ((800, 600), (1024, 600), (1280, 720), (1366, 768), (1920, 1080)):
        w.showNormal()
        w.resize(sw, sh)
        settle(15)
        w.cpu_dock.setFloating(False)
        w.cpu_dock.show()
        settle(10)
        w.cpu_dock.raise_()
        settle(10)
        shot(w, f"size_{sw}x{sh}_docked_{tag}")
        w.cpu_dock.setFloating(True)
        settle(10)
        w.show_cpu_view()
        settle(10)
        shot(w, f"size_{sw}x{sh}_main_{tag}")
        panel_shot(f"size_{sw}x{sh}_panel_{tag}")
w._apply_theme("Dark")
settle(5)

# ---- enlarged at 800x600
w.showNormal()
w.resize(800, 600)
settle(15)
p.max_btn.click()
settle(25)
shot(w.cpu_big, "enlarged_view_from_800x600")
p.max_btn.click()
settle(10)

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

w.editor.document().setModified(False)
w.close()
print(len(saved), "screenshots:", *saved, sep="\n  ")
