"""Render the main window offscreen for documentation / visual checks.

usage: python tools/screenshot.py OUT.png [Dark|Light|High Contrast] [example.asm] [run|step|slow|irq|trace|compat|instructions] [beginner|advanced]
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

out = sys.argv[1]
theme = sys.argv[2] if len(sys.argv) > 2 else "Dark"
example = sys.argv[3] if len(sys.argv) > 3 else "07_subroutines.asm"
action = sys.argv[4] if len(sys.argv) > 4 else "step"
mode = sys.argv[5] if len(sys.argv) > 5 else "advanced"

QApplication.setOrganizationName("S85shot")
QApplication.setApplicationName("S85shot")
app = QApplication([])
QSettings().clear()
QSettings().setValue("mode", mode)
from studio8085.ui.mainwindow import MainWindow

w = MainWindow()
w.resize(1500, 920)
w.show()
app.processEvents()
w._apply_theme(theme)
w._load_example(example)
app.processEvents()
if action == "step":
    w.cmd_assemble()
    for _ in range(6):
        w.cmd_step("into")
    w.editor.toggle_breakpoint(13)
elif action == "run":
    w.cmd_run()
    for _ in range(50):
        app.processEvents()
elif action == "slow":
    import time
    w.speed.setCurrentIndex(2)  # 10,000 instr/s
    w.cmd_run()
    t0 = time.time()
    while w.machine.cpu.icount < 1900 and time.time() - t0 < 10:
        app.processEvents()
        time.sleep(0.002)
    w.cmd_pause()
    w.docks["memory"].raise_()
    w.memory._zoom_to(0x2000)
elif action == "trace":
    w.cmd_assemble()
    w.a_trace.trigger()
    w.cmd_run()
    for _ in range(40):
        app.processEvents()
    w.trace.refresh(w.machine)
    w.docks["trace"].raise_()
elif action == "errors":
    w._set_source('''; A program with mistakes - hover the red wavy lines
        org 4200h
start:  mvi a,300        ; too big for 8 bits
        mov b,5          ; B,5 is not valid
        jmp strat        ; typo in label
        mob c,a          ; unknown instruction
count:  equ 3
loop:   dcr c
        jnz loop
        lxi h,table+count
        add b            ; fine
        out 07h
''', None, "mistakes.asm")
    app.processEvents()
    w.docks["problems"].raise_()
    w.editor.toggle_breakpoint(7)
elif action == "compat":
    w.a_compat["note"].trigger()
    w.docks["problems"].raise_()
elif action == "flags":
    w.cmd_assemble()
    for _ in range(int(os.environ.get("STEPS", "3"))):
        w.cmd_step("into")
elif action == "instructions":
    # a student building a program from the list: three lines inserted, the MVI group open
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    w.new_file()
    w.editor.setPlainText("; Add two numbers\n")
    app.processEvents()
    w.show_instructions()
    tree = w.instructions.tree
    top = lambda p: next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).text(0).startswith(p))
    def click(item):
        tree.scrollToItem(item)
        app.processEvents()
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, tree.visualItemRect(item).center())
        app.processEvents()
    mvi = top("MVI")
    click(mvi)
    click(mvi.child(7))
    QTest.keyClicks(w.editor, "25")
    click(top("ADI"))
    QTest.keyClicks(w.editor, "17")
    click(top("STA"))
    QTest.keyClicks(w.editor, "0200h")
    click(top("HLT"))
    click(mvi)  # reopen to show the opcodes of the eight MVI forms
    tree.setCurrentItem(mvi.child(7))
    for _ in range(40):
        app.processEvents()
        __import__("time").sleep(0.01)
    w.editor.goto(3)
elif action == "irq":
    w.cmd_run()
    for _ in range(20):
        app.processEvents()
    w._raise_irq("RST7.5", 0)
    for _ in range(20):
        app.processEvents()
for _ in range(10):
    app.processEvents()
w.grab().save(out)
print("saved", out, "state:", w.state)
