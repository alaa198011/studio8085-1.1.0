# Phase 2 review report: Interactive CPU Architecture (visual CPU)

Branch `feature/phase2-visual-cpu` (from Phase 1 head `bd82989`). **Nothing is pushed. CI status: PENDING (not pushed).**
Phase 1 re-check (`git fetch`): `origin/feature/phase1-virtual-trainer-kit` is still `bd82989` - no change, no rebase needed.

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
Phase 1 baseline 793 passed -> Phase 2 **853 passed, 0 failed** (+60 new: 24 core + 36 GUI). Because the machine was
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

## 6. Packaged build
`pyinstaller packaging/studio8085.spec` (PyInstaller installed into the dev Python for this check; output to a temp
directory, not the repo) built successfully in ~35 s. `8085Studio.exe --selftest` printed `selftest ok`, exit 0
(self-test includes the CPU panel). The installer (`.iss`) and Linux build were not exercised.

## 7. Screenshots (`docs/phase2/screenshots/`)
Labs: lab_A_register_transfer, lab_B_alu_flags, lab_B_final_flags, lab_C_after_IN, lab_C_after_OUT, lab_C_feedback.
Themes: theme_dark, theme_light, theme_high_contrast. Sizes (main/panel/docked) at 800x600, 1024x600, 1280x720,
1366x768, 1920x1080. Others: main_window_with_lab_C, panel_smallest_540x440, panel_zoomed_in, stack_PUSH, generic_DAD,
animation_midway, experiment1_masked_before_prediction, experiment1_main_window_masked.
Reviewed by eye in this pass: lab_A, lab_B_final_flags, lab_C_feedback, theme_light, theme_high_contrast,
size_800x600_docked, experiment1_masked_before_prediction, experiment1_main_window_masked. No overlap, clipped text or
leaked answer found: masked shots show `??` / "hidden until you predict" for A and ports and no step. At 800x600
docked, the panel shares a short column with other docks and is mostly scrolled (see limitations). No re-capture needed.

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

STATUS: READY_FOR_OWNER_REVIEW
