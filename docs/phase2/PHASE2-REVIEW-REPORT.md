# Phase 2 review report: Interactive CPU Architecture (visual CPU)

Branch `feature/phase2-visual-cpu` (from Phase 1 head `bd82989`), pushed to origin. Pushed SHAs: `6f4734a` (Phase 2 as
first reviewed), `995a34a` (+ CALL explanation fix), then a final commit with the `fetch-depth: 0` workflow change and this
report (section 11 and 15). No PR was created; main, Phase 0, Phase 1 (`bd82989`) and draft PR #1 were not touched.
Phase 1 re-check: `origin/feature/phase1-virtual-trainer-kit` is still `bd82989`; PR #1 head `bd82989`, draft, open.

## 1. Architecture and data-flow design
```
CPU / Machine (unchanged)  --read-only-->  StepRecorder  -->  StepRecord (immutable)  -->  Qt panel
 core/cpu.py, machine.py     core/visual.py: CpuState       families, diff, Flow list     ui/cpuview.py
                             pre/post snapshot + diff        explanations                  CpuArchitecturePanel
```
- `core/visual.py` (no Qt): immutable `CpuState` snapshots, `StepRecorder.begin()/end()` bracketing the existing
  debugger action, state diff, instruction families, logical `Flow`s, bounded `StepHistory`. It never executes or
  calculates; every value shown is read from the simulator before/after the step.
- `core/lab_content.py`: three teaching labs as data. `ui/cpulabs.py` renders them.
- `ui/cpuview.py` (Qt): QGraphicsView vector diagram, controls (Explain Execution, Animate, Reduce motion, Decimal,
  speed, Pause/Skip/Replay, zoom/fit), step-explanation text, Labs tab. Consumes only `StepRecord`/`CpuState`.
- `ui/mainwindow.py`: separate lazily built `cpu_dock` (not in `self.docks`, so Phase 1 panel-set tests and layout
  rules are untouched), View/Lab menu entries, capture in `_begin`/`_finish`, redraw throttled to <= ~10 Hz during Run.
- CPU semantics, assembler, and Phase 1 behaviour are not modified. Experiment 1 masking is reused (the panel masks
  accumulator and ports and clears its last step while the answer is concealed).

## 2. Instruction families
Detailed visuals (flows, highlighted source/destination, flag animation): Data transfer (MOV, MVI, LXI, LDA, STA,
LHLD, SHLD), Arithmetic (ADD, ADC, SUB, SBB, INR, DCR, INX, DCX), Logical (ANA, ORA, XRA, CMP), Control flow (JMP,
CALL, RET, conditional jumps), Stack (PUSH, POP), I/O (IN, OUT; switches -> A -> LEDs chain), Other (NOP, HLT).
Generic before/after view (no animation, changes still highlighted): all remaining opcodes (e.g. DAD, DAA, XCHG, LDAX,
STAX, immediates ADI/ANI/..., rotates, RST, EI/DI, RIM/SIM, conditional CALL/RET). Step Over/Out/Run show an
N-instruction summary.

## 3. Files changed (vs bd82989, 44 files, +3658)
Source: `core/visual.py` (742), `core/lab_content.py` (178), `ui/cpuview.py` (1283), `ui/cpulabs.py` (82),
`ui/mainwindow.py` (+151), `app.py` (+24, self-test covers the CPU panel), `ui/settings.py` (+2).
Tests: `tests/test_visual_core.py` (336 lines, 24 tests), `tests/test_visual_gui.py` (538 lines, 36 tests).
Tools: `tools/phase2_perf.py`, `tools/phase2_shots.py`. Docs: `docs/phase2/PHASE2-PLAN.md`, this report,
`docs/phase2/screenshots/` (32 PNGs).

## 4. Test results (Windows, offscreen Qt, `python -m pytest`)
Local, before the CALL fix: Phase 1 baseline 793 passed -> Phase 2 **853 passed, 0 failed** (+60 new: 24 core + 36 GUI). Because the machine was
heavily loaded, the suite was run as four parallel pytest invocations covering every test file once:
483 + 127 + 129 + 114 = 853 collected = 853 passed. No test was weakened or skipped.
(`tests/test_visual_labs.py` named in the plan was folded into the two visual test files.)

## 5. Performance (`tools/phase2_perf.py 3`, offscreen, loop program)
| Measure | Visualizer off | Visualizer on | Overhead |
|---|---|---|---|
| Core Run (Machine.run_chunk), instr/s | 1,495,180 | 1,488,346 | 0.46% |
| Whole app, Max-speed Run, instr/s (panel hidden vs visible) | 1,350,909 | 1,338,433 | 0.92% (about 6.6 redraws/s) |
| Single Step Into, per step | 1.24 us | 59.8 us | +58.6 us (capture + diff, imperceptible) |
Step-by-step the visualizer costs ~60 us per Step Into; continuous Run is essentially unaffected.

## 6. Packaged build (local; the CI result is in section 11)
`pyinstaller packaging/studio8085.spec` (PyInstaller installed into the dev Python for this check; output to a temp
directory, not the repo) built successfully in ~35 s. `8085Studio.exe --selftest` printed `selftest ok`, exit 0
(self-test includes the CPU panel). The installer (`.iss`) and Linux build were not exercised.

## 7. Screenshots (`docs/phase2/screenshots/`)
Labs: lab_A_register_transfer, lab_B_alu_flags, lab_B_final_flags, lab_C_after_IN, lab_C_after_OUT, lab_C_feedback.
Themes: theme_dark, theme_light, theme_high_contrast. Sizes (main/panel/docked) at 800x600, 1024x600, 1280x720,
1366x768, 1920x1080. Others: main_window_with_lab_C, panel_smallest_540x440, panel_zoomed_in, stack_PUSH, generic_DAD,
animation_midway, experiment1_masked_before_prediction, experiment1_main_window_masked.
All 32 were later opened and reviewed one by one; see the table in section 12. No re-capture was needed.

## 8. Verified vs uncertain
Verified: test suite (853 pass); perf numbers; PyInstaller build and `--selftest` on Windows; masking in screenshots;
layout at the sampled screenshots.
Uncertain / not verified: CI (not pushed, PENDING); Linux/macOS rendering; installer build; real GPU/DPI-scaling and
screen-reader behaviour; classroom usability (owner review); long-session memory use beyond the bounded history.

## 9. Known limitations
- Instruction-level, not cycle-accurate: no T-state or bus-cycle timing is modelled.
- Micro-operations and data-path/bus flows are conceptual teaching diagrams (labelled "conceptual explanation"); solid
  lines mean a destination change was observed, dashed means conceptual only.
- Only the families above have detailed visuals; others use the generic view.
- At 800x600 the docked panel is cramped; use float/maximize or a larger window.
- Test suite is slow on a loaded machine (test_gui.py took ~29 min here under four-way parallel load).
- Untested scaling: very long Runs with the panel visible beyond the 3 s perf sample; interrupts are not visualized.

## 10. Next steps
Owner review of this branch; push and let CI run on all platforms; decide on a Phase 2 PR (stacked on Phase 1 PR #1);
optional: detailed visuals for DAD/XCHG/rotates, a larger-window preset for 800x600, a Linux packaged-build check.

## 11. CI evidence and fixes made after the first report
**Fixes made**
1. **CALL explanation bug (found by an independent review, predates Phase 2).** `core/explain.py` printed the CALL
   return address as `pc + 2`; CALL is 3 bytes, so a CALL at 0016h said "return address (0018h)" while the real push and the
   following RET use 0019h. This contradicted the panel's own recorded stack writes. It is now `(pc + ins.length) & FFFFh`.
   Conditional calls (CNZ..CM) print no address and RST (1 byte) prints none; the new tests assert the real pushed address
   for CALL at 4 origins, all 8 conditional calls (pc+3) and RST 3 (pc+1). The regression test fails on the old code
   (verified) and no existing assertion had to be changed. CPU semantics are untouched.
2. **CI checkout depth.** `test_cpu_core_files_are_untouched_by_phase2` diffs against `bd82989` and skipped on CI because the
   checkout was shallow. `.github/workflows/build.yml` now uses `fetch-depth: 0` on `actions/checkout` so the guard runs.

**CI runs** (workflow `build`, job `test-and-package` on ubuntu and windows; each job tests, packages with PyInstaller and
self-tests; Linux builds the wheel; Windows builds the Inno Setup installer with ISCC via choco):

| Run | SHA | Result |
|---|---|---|
| https://github.com/alaa198011/studio8085-1.1.0/actions/runs/42251098065 | 6f4734a | Cancelled by me while slow (see below). Linux Test step had finished: 851 passed, 2 skipped (1:58:25). Windows was about 92% through with no failures. |
| https://github.com/alaa198011/studio8085-1.1.0/actions/runs/42259526228 | 995a34a | **Success.** Windows: 864 passed, 1 skipped (1:54:32). Linux: 863 passed, 2 skipped (1:50:56). |

The cancellation of 42251098065 was a mistaken cancel of a slow but healthy run, not a hang: the suite is simply slow on CI
(about 2 h, the same order as Phase 1's 1h53m). Phase 1 baseline was Windows 793 / Linux 792 + 1 skip; Phase 2 adds 60 tests
and the CALL fix adds 12, giving 865 collected on each OS (Windows 864 + 1 skip, Linux 863 + 2 skips).

**Skips and why**
- Windows-only font database test (`tests/test_platform_fonts.py`, `skipif(sys.platform != "win32")`): skipped on Linux only (the Phase 1 expected skip).
- `test_cpu_core_files_are_untouched_by_phase2` (`pytest.skip("git history not available")`): skipped on both OSes in run 42259526228
  because of the shallow checkout. New with Phase 2; addressed by `fetch-depth: 0` (result in section 15).

**Packaged build, self-test, installer (run 42259526228):** PyInstaller package: success on both OSes. `--selftest`: `selftest ok` on Windows and on
Linux. Windows installer (`packaging/windows/studio8085.iss` via ISCC): built successfully in CI. Wheel build (Linux): success. The workflow
uploads its normal CI artifacts; nothing was published, tagged or released by me.

## 12. Screenshot review (32 of 32 opened)
Values were checked by hand against the programs: LXI/DAD gives HL=2468h with CY=0; Lab B 7Fh+01h gives 80h with S=1 AC=1 P=0 CY=0, and
FFh+01h gives 00h with Z=1 AC=1 P=1 CY=1; Lab C moves A5h through IN 00h / OUT 01h, 25 T-states, no flag change. No answer is shown
before prediction in the Experiment 1 shots.

| File | Verdict |
|---|---|
| lab_A_register_transfer, lab_B_alu_flags, lab_B_final_flags, lab_C_after_IN, lab_C_after_OUT, lab_C_feedback | OK |
| main_window_with_lab_C | OK (A=A5h, halted, 3 instructions, 25 T-states) |
| generic_DAD, animation_midway | OK |
| stack_PUSH | OK; cosmetic: the one-line caption under the diagram is ellipsised ("...high byt..."), full text is in the explanation pane |
| experiment1_masked_before_prediction | OK: A shows `??`, ports "hidden until predicted", no step shown |
| experiment1_main_window_masked | OK (A is 00h; this scripted shot does not execute the experiment program, so it shows no leak but does not exercise one) |
| theme_dark, theme_high_contrast | OK |
| theme_light | OK; cosmetic: unchecked checkbox boxes are not visible on the light background (same in High Contrast), labels are readable |
| panel_zoomed_in, panel_smallest_540x440 | OK (scrolls instead of squeezing) |
| size_1280x720, 1366x768, 1920x1080 (main, panel); size_1024x600_panel; size_800x600_panel | OK |
| size_*_docked (five files) | Usable but cramped: the docked panel is a strip about 100 px high in the right column, so the diagram is scrolled; float it or use a larger window |
| size_1024x600_main, size_800x600_main | Layout note (pre-existing Phase 1 layout, not caused by the panel): at 800x600 the code editor is about 65 px wide |

Total: 25 OK, 5 OK with a cosmetic or layout note on docked sizes, 2 pre-existing layout notes; no real Phase 2 defect, so nothing was re-captured.

## 13. Performance re-check (real MainWindow, offscreen, 1000 Step Into calls per mode, includes the UI refresh)
| Mode | mean | p95 |
|---|---|---|
| Panel off | 18.5 ms | 26.2 ms |
| Panel on (floating) | 24.3 ms | 32.5 ms |
| Panel on (docked) | 14.7 ms | 19.1 ms |

Per-step cost is dominated by the existing window refresh, not the visualizer (the recorder itself is about 60 us). Over 1500 steps with the
panel on, traced Python memory grew by about 0.9 MB versus 0.2 MB with it off; `StepHistory` is bounded (tested) and the machine trace stays
empty, so no unbounded growth was seen.
800x600: the main window cannot shrink below about 895 px wide; the editor is 63 px wide at that size with or without the CPU panel, because the
existing right-hand Memory Map / Trainer Kit docks take the width. This is Phase 1 layout and the panel is floating by default, so Phase 2 does not
cause it. I did not add a layout fix because it would change approved Phase 1 behaviour.

## 14. Remaining limitations (additions)
- Experiment 1 masking covers only A, the input port and the output port; flags and register pairs are not masked (fine for this IN/OUT experiment).
- `StepRecorder.history` holds unmasked records, but no UI reads it.
- At small window sizes (800x600) the editor now keeps 440 px (section 16); a docked CPU panel is small there and scrolls: float it.
- CI takes about 2 hours per run (GUI tests); not changed here.

## 15. Final CI (last commit)
The last commit contains only the workflow `fetch-depth` change and this report; its CI run and result are given in the final hand-off message.

## 16. Final UX correction (responsive workspace, caption, check boxes, screenshots)

**Cause.** At 800x600 the editor was 187-204 px wide on Phase 1 alone (63 px once the CPU panel's right-hand dock was involved):
side docks were sized in fixed proportions and nothing guaranteed the editor a minimum.

**Fix (Phase 1 branch, merged here by a merge commit).** The central widget has a minimum width of 440 logical px (about 60 source columns plus
the gutter). Below about 980 px the docks of both sides are tabbed into one column (reversible, never closes or hides a dock, regroups a dock
opened later, not saved as the user's layout, a big-screen layout is clamped on restore, re-evaluated on resize / dock change / screen change).
See `docs/TRAINER_KIT.md`, "Responsive layout".

**Phase 2 specifics.** The CPU panel dock takes part in the same logic (`_adaptive_docks`): docked on the right it joins the right-hand tab
group, is brought to the front and gets up to 640 px (the editor keeps its minimum); on a narrow window it tabifies with every other dock; floating,
docking, hiding and widening again all keep it where the user put it. Opening it floating at a wide size, narrowing the window and docking it
afterwards is covered (it used to stay in a separate stacked group).

| Editor width (px), Advanced, all docks shown | 800x600 | 1024x600 | 1280x720 | 1366x768 | 1920x1080 |
|---|---|---|---|---|---|
| before (Phase 1 branch bd82989) | 187 | 313 | 436 | 466 | 1018 |
| after | 544 | 440 | 440 | 466 | 1018 |

Beginner before: 204 / 335 / 458 / 544 / 1098; after: 544 / 440 / 458 / 544 / 1098. With the CPU panel docked (screenshots) the editor is
over 440 px at every size; it was 63 px at 800x600 before.

**Caption.** The one-line explanation under the diagram (`stack_PUSH`) was cut with "..." after 118 characters. It is now a word-wrapped text item
(up to three lines, 10 pt bold unchanged) placed below every block inside the scene; a test checks the longest explanation of every opcode.

**Check boxes.** Unchecked boxes were drawn with the ordinary border colour (1.4:1 on the Light panel). Themes have a `control_border` colour and the
QSS draws the indicator with it (4.4:1 or more on panel, window and editor in all themes; checked boxes fill with the accent, 5.2:1+). Verified by
`tools/contrast_check.py`, by theme tests and by rendering the real widgets (Phase 1 and Phase 2 panels).

**Experiment 1 masking after the layout change.** Docking, tabifying (narrow window), raising, floating, hiding / re-showing and widening again
with the CPU panel open before the prediction: A, the IN port and the OUT port stay masked in every state (new test
`test_masking_survives_tabifying_floating_and_restoring_the_cpu_panel`, both the narrow and the wide ending); the earlier masking tests pass unchanged.

**Controlled Step Into cost** (`tools/phase2_step_perf.py`, offscreen, Windows, 12 logical CPUs, nothing else running; 1366x768 Advanced, loop program,
200 warm-up steps, 1000 timed Step Into calls per run, 3 runs; each call includes the window refresh and panel update):

| Mode | median of the 3 means | median of the 3 p95 |
|---|---|---|
| Panel off | 11.28 ms | 12.51 ms |
| Panel docked (tabbed with the other docks) | 9.09 ms | 10.31 ms |
| Panel floating | 15.48 ms | 17.30 ms |

Docked is faster than off because the other right-hand panels are hidden tabs and are not refreshed; the floating panel costs about 4 ms per step
in this refresh-everything measurement. The load of the machine was not otherwise measured (no other Python or test process running).

**Screenshots** (`docs/phase2/screenshots/`, regenerated with `tools/phase2_shots.py`, real Windows windows): 64 files, including
`size_{800x600,1024x600,1280x720,1366x768,1920x1080}_{docked,main,panel}_{dark,light,high_contrast}` (45), `stack_PUSH`, `stack_PUSH_light`,
`stack_PUSH_high_contrast`, the experiment 1 masked shots and the labs. Opened and checked after the fix: `stack_PUSH_light` (caption complete, boxes
visible), `size_800x600_docked_dark`, `size_800x600_main_light`, `size_1024x600_docked_light` and `_docked_high_contrast`, `size_1024x600_main_dark`,
`size_1280x720_docked_high_contrast`, `size_1280x720_main_light`, `size_1366x768_docked_dark` and `_docked_light`, `size_1920x1080_docked_dark`
and `_docked_light`. Remaining note: on an 800x600 window a docked panel is still small (about 300 px wide beside the 440 px editor) and scrolls;
floating it is better there.

STATUS: READY_FOR_OWNER_REVIEW

## 17. Owner review fixes (PR #3 review by Alaa: RAM cells, text size, stack pointer, enlarge icon)

`cpu.py`, `assembler.py`, `machine.py` and `opcodes.py` are untouched (the guard test passes). All changes are in the visualization model
(`core/visual.py`), the panel (`ui/cpuview.py`), the Memory view (`ui/memory.py`), the window glue (`ui/mainwindow.py`), the icon set and one
setting (`cpu_zoom`).

### 17.1 Memory cells used during execution
**What the recorder really provides.** `StepRecorder` watches the simulator's own per-cell counters (`Memory.rd`, `Memory.wr`) for the addresses an
instruction can touch (operands, HL for `M`, SP for stack instructions). Therefore:
* Step Into: every read and write of that instruction is reported when access tracking is on (the default). A write also carries the byte before
  (`Access.old`); a read carries the byte as it was when read (INR M: reads 3Fh, writes 40h).
* Tracking off: only writes that change a cell can be proven; **no read is ever reported** (nothing is fabricated).
* Run / Step Over / Step Out: no per-access record. The panel shows the **recently used** list instead, taken from the simulator's last-access
  statistics (last 400 instructions, newest first, at most 6 kept, 4 drawn). Limitation: those statistics keep only the *last* access kind per cell, and
  interrupt entry pushes are not itemised.

**Diagram.** The Memory block at the memory interface now has: "this step" rows (`WRITE 2000h  00h -> 3Fh`, `READ  3000h = 3Fh`; text labels, so
meaning does not depend on colour), a short recently-used line (`W20FD W20FC ...`), and two strips of five cells (around HL = M, and around the last
accessed address) with the used cells outlined, filled and prefixed `R`, `W` or `RW`, and `HL` written next to the HL cell.
**Memory dock.** The same cells are coloured with an `R` / `W` letter in the cell, the tooltip says READ / WRITTEN by the last step, a line above
the table lists them, and the table scrolls to the first one. Marks are cleared by any step without access, a reload, and Experiment 1 masking.
Run keeps its existing heat map; nothing is animated per access. The dock marks need the CPU panel to have been opened (the recorder only runs
then, as before).

### 17.2 Readable text
The diagram text was 8-10 pt in scene units and the fit scale could drop to 0.55 (about 4.5-5.5 pt on screen). Now:

| Text | Before | After (scene pt, 100%) | At the smallest fit scale (0.80) |
|---|---|---|---|
| register / PC / SP / flag values | 10 | 16 bold mono | 12.8 |
| box titles | 10 bold | 12.5 bold | 10.0 |
| binary, was, tags, ports, memory rows | 8 | 11.5 (mono for numbers) | 9.2 |
| pair label | 10 | 13.5 bold mono | 10.8 |
| caption | 10 bold | 11.5 bold | 9.2 |

The scene grew from 1030x722 to 1200x722 with larger boxes (registers 104x118, SP 286x184, Memory 748x172); the fit never goes below 0.80
(it scrolls, and a step that used memory or the stack scrolls to those blocks). Every text goes through one helper that records
its rectangle; a text that would be wider than its box is shrunk a quarter point at a time, never below 10.5 pt (13 pt for the big values), so a
wider system font does not clip it (checked with DejaVu Sans / Sans Mono as well as Segoe UI / Cascadia). New option **Size** (Fit, 100 %, 125 %,
150 %, 200 %) is saved in settings (`cpu_zoom`). Tests render the diagram in 3 themes x 5 window sizes x several states (decimal on) and assert
that no text is wider or taller than its box and that nothing is below the minimums.

### 17.3 Stack pointer contents
The SP box shows the address, `[SP]`, `[SP+1]` and the 16-bit word (low byte at SP, high at SP+1), plus the top four words of the stack with the top
marked `>` (only words really pushed, i.e. below the stack base the Stack panel already tracks; "(stack empty)" otherwise). Values come from
real memory after the step (`capture_memview`); while an animation shows the pre-step SP the contents are shown only when they belong to the same SP.
Tests cover PUSH H, PUSH PSW (A high, flags low), POP, CALL (return address) and RET.

### 17.4 Enlarge icon (owner note 4)
There is no separate "lab" widget: the labs are the **Labs tab of the CPU Architecture panel**, so the panel is what is enlarged. New icon buttons in
its header (drawn vector icons, themed): Zoom out, Zoom in, Fit and **Enlarge / Restore** (Ctrl+Shift+F; Esc restores; F11 is Step Into so it is not
used). Each has a tooltip with its shortcut, an accessible name and a keyboard shortcut (Ctrl+= / Ctrl++, Ctrl+-, Ctrl+0). Enlarging lends the panel to a
maximized top-level window; the dock is never touched, so floating / docked / tabbed state, geometry and visibility come back exactly (tested floating
and docked). Closing the big window by its title bar also restores. Experiment 1 masking holds in the enlarged view (same panel object; tested,
including starting the experiment while enlarged).

### 17.5 Masking (Experiment 1)
Before the prediction nothing from memory is stored or drawn: the panel drops memory snapshots while concealed, the Memory block says
"hidden until you predict", the SP contents say "contents hidden", the Memory dock marks are cleared, and larger labels do not change the existing
masking of A, the IN port and the OUT port. Test: the secret byte is first written to memory at HL and onto the stack (real recorded accesses,
visible when unmasked), then the experiment starts; every text (`node_texts`, tooltips, painted text) is searched for the byte in hex and binary:
no match; it reappears after the prediction or Help.

### 17.6 Tests and screenshots
New: `tests/test_phase2_review_fixes.py` (25 test cases). Screenshots re-captured with `tools/phase2_shots.py`; new: `memory_access_STA/LDA/INR_M`,
`memory_dock_marks_STA/INR_M`, `stack_PSW/POP/CALL/RET`, `stepped_panel_*`, `stepped_docked_800x600/1366x768`, `enlarged_view`, `enlarged_view_labs`,
`enlarged_view_from_800x600`.

### 17.7 QA fixes (PR #4 QA)
1. **Answer leak (critical).** The Registers dock was never part of the Experiment 1 masking, so after an earlier run the stale A was shown before the
   prediction. This was already the case in Phase 1 (the masking list there covered the I/O table, Output, Trace and Explain, not Registers).
   `_apply_conceal` now also calls `RegistersPanel.set_concealed(("A",))`: A shows `??` / `??` / `????????` and cannot be edited until the student
   predicts, asks for help or ends the experiment. Display only; the CPU is not touched. Checked and not leaking: Memory dock, Stack, Flags,
   status bar, I/O Ports, Output, CPU diagram (there is no debugger watch window).
2. **Ctrl+= / Ctrl+- in the CPU panel.** Root cause: the main window action (Zoom In/Out, window shortcut) and the panel's own shortcut matched the
   same key, which Qt treats as ambiguous, so neither ran. The main window now owns the keys and dispatches by focus (panel or anything in it:
   diagram zoom; elsewhere: editor zoom); the enlarged window, which is a separate top-level window, keeps the panel's own shortcuts. Tooltips say
   "while this panel has the focus". Ctrl++ also zooms in now.
3. **F11 (and F5/F10/...) while enlarged.** Root cause: the enlarged view is a separate top-level window, so the main window's actions were not
   active there. The window now lends it the run/step actions (assemble, run, pause, stop, restart, step into/over/out) and takes them back on restore.
4. **Flow arrow across "Register pair BC".** The tap of B, D and H (and the MOV B,B self-loop) went up through the pair title. The first register of each
   pair now leaves its box at the left corner and the pair title starts 4 px further right; a test checks every flow and bus tap against all three titles.

Tests: `tests/test_phase2_qa_fixes.py` (18 cases: stale-A sweep over all docks and the diagram, reveal after predict/help/end, key events for
docked/floating/enlarged, editor zoom still works, F11/F10/F5 enlarged, no arrow through a title). Screenshots re-captured: `enlarged_view*`,
`experiment1_*`, `lab_A_register_transfer`.
