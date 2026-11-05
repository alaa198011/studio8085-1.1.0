# Release notes

## Unreleased - Phase 1: Virtual 8085 Trainer Kit

### New
- **Virtual 8085 Trainer Kit** dock (*Lab > Show the Virtual 8085 Trainer Kit*, or *View*): 8 toggle switches SW7...SW0 on
  `IN 00H`, 8 LEDs LED7...LED0 on `OUT 01H` and a seven-segment digit with decimal point on `OUT 02H`. These are virtual teaching
  port assignments, not real kit addresses; they can be changed (*Lab > Trainer Kit Port Mapping...*, validated, conflicts rejected).
  Switches work with the mouse and the keyboard (Space/Enter, arrows) and show their value in binary and hex; the LEDs and the display
  follow every `OUT` while stepping and while running. Vector drawing, sharp at 150 % / 200 %, readable in Dark, Light and High Contrast.
- **Seven-segment modes:** *Raw segment bits* (default, active-high: bit0 = a ... bit6 = g, bit7 = DP) and *Hex decode* (the low nibble
  shows 0-F). Changing the mode never touches the CPU.
- **Experiment 1: Read Switches and Control LEDs** (*Lab* menu): a guided set - predict - assemble - step - compare flow. The answer is
  not shown before the student predicts (unless they press *Help me*); the comparison reads the real accumulator and LED latch.
  Lab programs for the experiment, a raw-segment pattern and a hex-decode display (`examples/trainer/`).
- **Experiment 1 keeps the answer hidden until the student predicts.** Before a prediction (or *Help me*), the switch value and the
  expected LED/output result are shown as `??` in the Trainer panel (readouts, LED lamps, display), the I/O Ports rows of the configured
  switch, LED and display ports, the Output log's `OUT` lines, the Explain panel's `IN`/`OUT` details and the Trace table. This is display
  only: `cpu.io`, the switches and the CPU are untouched. Run and Step wait for the prediction. Predicting, *Help me*, *End experiment*
  (new button) or opening another program shows everything again.
- **Beginner mode keeps the kit visible during a lab.** Starting Experiment 1 or a Lab program shows the kit (tabbed next to Explain) and
  keeps it through mode switches and *Reset layout* until the lab ends; it still starts hidden when no lab is running, and stays reachable
  from the View menu. It fits and leaves the editor usable at 800x600, 1024x600, 1280x720 and 1366x768.
- `docs/TRAINER_KIT.md`: ports, bit order, segment map, polarity, hex table, resets, limitations, how to run the lab.
- `--selftest` also checks the trainer kit (switches -> `IN` -> A -> `OUT` -> LEDs, and that disconnecting restores the CPU hooks).

### Compatibility
- No CPU instruction changed. The kit attaches to the existing `IN`/`OUT` hooks and chains to the debugger's OUT log; the trace and
  the Output log are unchanged. With *Kit connected* unchecked it is detached and `IN`/`OUT` behave byte-for-byte as in 1.1.0 (tested).
- While connected, the switches own their port: `IN 00H` reads them and the I/O Ports row 00h mirrors them (typing there sets them).
- Beginner mode does not show the kit until it is opened from the Lab or View menu, so the Beginner layout is unchanged. Layouts saved
  by 1.1.0 are restored as before.

### Fixed
- **A session saved in Beginner mode restored all 13 panels** instead of the Beginner set (a bug present since 1.1.0: Qt's `restoreState`
  does not hide the docks the default layout had shown, and nothing enforced the Beginner set afterwards). Beginner now always comes back
  as the Beginner set; Advanced restores its own saved layout; layouts saved by 1.1.0 restore sensibly.

## 1.1.0 - learning-focused release

Built from a review of 1.0 whose main finding was: *the core feature set is already substantial; make it a clearer learning tool.*

### New
- **Beginner and Advanced modes.** Beginner (default on first start) shows editor, registers, flags, Explain, a hex memory table, Problems and
  Output, with text labels on the run/step buttons. Advanced shows everything. Each mode remembers its layout.
- **Explain panel.** Plain-language description of the next instruction using the actual values (including whether a branch will be taken),
  and a before/after table of what the last step or run changed, with a sentence per changed flag explaining why.
- **Execution trace** with **CSV, Markdown, HTML and PDF** export; live Trace panel (*Debug > Record Execution Trace*).
- **GNUSim8085 compatibility checking** (off / notes / strict) based on probing the real GNUSim8085 assembler; `docs/COMPATIBILITY.md`.
- **Memory cell detail**: click any byte to see its type (code, data, reserved, stack, unused), source line, read/write counts and last access;
  heatmap legend spells out *read* vs *written* vs *executed*; 4 KB per-byte zoom.
- **Restart** now states exactly what it resets; I/O port values you entered are kept.
- **Accessibility:** High Contrast theme, visible keyboard-focus outlines, interface font size, editor font up to 72 pt, Compact layout, Focus-editor mode (F12).
- **Program metadata** comments (`; @title`, `@topic`, `@chapter`, `@validation`, ...) shown in the Explain panel; bundled examples tagged `T`.
- **Documentation:** getting started, user guide, teaching guide, accuracy and limitations, compatibility, per-opcode instruction matrix.
- **Verification tooling:** the differential test against the original GNUSim8085 core is now in the repository (`tools/diff_vs_gnusim8085`);
  opcode lengths/T-states are asserted against published tables (`tests/test_opcode_reference.py`); the instruction matrix is generated and checked.

- **Instructions panel** (toolbar button, `Ctrl+I`, View/Edit menus): a searchable list of the instruction set. **One click inserts the instruction** into the
  editor (on a blank line, or a new line below; indentation kept; the operand placeholder is selected for typing; one `Ctrl+Z` undoes it). Typing by hand is
  unchanged. Each row shows the **opcode**, size and T-states (`7/10` for conditional jumps); the line under the list gives the description, the opcode in binary,
  the machine-code bytes and the flags. Search by instruction (`mov a,b`), opcode (`78h`) or meaning (`carry`); scope *Essential* / *All* / by group, remembered.
  Opcodes come from the same table as the assembler, and a test assembles all 246 inserted texts and compares the resulting opcode.
- **Store code at** box (was *Load at*, Advanced only) is on the toolbar in both modes: the memory address where the program is saved and where it starts. `ORG` still overrides it.
  Assemble scrolls the Memory panel to the code and says where it was stored. Changing the address now makes the loaded program out of date, so the next Run or Step re-assembles it
  there (before, it kept running the copy at the old address).
- **Machine code in the status bar** for the instruction on the cursor line (`Machine code: 3E 05`).
- **17 beginner examples** (*File > Examples > Beginner: the essential instructions*): one short program per idea - `MVI`/`MOV`, `ADD`/`SUB`, flags and
  carry, memory and the `M` register, `CPI` + jumps, loops, logic and rotates, the stack, `CALL`/`RET`, `IN`/`OUT`, 16-bit pairs, and a final
  byte-copy program. Beginner mode opens the first one on the first start. Each has a result test and a `T` label; a test checks that the
  set covers every essential mnemonic. See `docs/EXAMPLES.md`.
- **Credit** to the idea's author, Alaa A. Aldhalemi (University of Kufa), in *Help > About* and the README.
- **Predict first** option in the Explain panel: hides what the next instruction will produce (results, carry decision, branch outcome) while
  keeping what it does and the current input values visible - for the book's *predict, trace, run, compare* workflow.

### Changed
- **Memory is kept** when assembling, running, stepping, restarting and opening another file. Before, every assemble wiped all of memory, so values typed into the
  Memory panel (or left by a previous run) turned to zero when Run was pressed. Now only the program's own code and initialised data are written (`DB`, `DW`,
  `DS n,fill`); a plain `DS n` is storage and is left alone; the previous version's unchanged bytes are removed so no stale code remains. **Preferences > Simulation >
  Keep memory contents...** switches the old wipe-everything behaviour back on, and *Debug > Clear Memory and Heat* wipes on demand. Heat statistics are still reset at
  every load.
- Validation labels **T / M / H** now use the book's front-matter definitions (T = tool-tested in the stated simulator, M = manually
  validated, H = hardware-validated; *no label is inherited*). The Explain panel tooltip says what each label does not prove.
- High Contrast theme now reaches WCAG AAA (7:1) for text, and this is tested.
- Explain wording: input values and predicted results are listed separately ("A = 99h, the constant = 01h" instead of "01h = 01h").
- Theme colours adjusted so that all built-in themes pass WCAG AA contrast checks (`tools/contrast_check.py`, tested). Before: dark line numbers/comments/accent text and several light-theme colours were below 4.5:1.
- Package status is now **Beta** (no hardware validation yet - see `docs/ACCURACY.md` section 4).
- Wording: "cycle-accurate" is no longer used; the model is *instruction-level T-state accounting from documented timing*.
- Trace column header `T` renamed `T-states`.
- Changing the assembler syntax mode forces a re-assembly on the next run.

### Fixed
- **Window too tall on first start (Beginner mode).** In about half of the starts the window grew up to ~260 px beyond the size it was given, because the Memory
  panel's splitter kept counting the hidden heatmap when Beginner mode hid it. The splitter is now refreshed, and the Beginner layout's dock sizes scale down on
  short windows (for example a 768 px laptop screen) instead of forcing the window taller.
- **Font size did not change.** *Preferences > Font size* and editor zoom were undone whenever the theme was applied (Qt resets widget fonts when the
  application stylesheet is set again), so the editor snapped back to 11 pt. The editor font is now re-applied after every theme change, and a zoom
  (Ctrl+wheel, Ctrl+= / Ctrl+-) is remembered as the new font size.
- **Interface font size only reached labels and menus.** The register, stack, memory, I/O, listing, symbol, trace and explain panels use their own monospace
  fonts and ignored it. They now follow the setting, with row heights and column widths growing with the text; the heatmap's address labels no longer clip.
- Memory-cell detail called every byte above SP "stack" while the Stack panel was hidden (always the case in Beginner mode); unused memory such as
  `9000h` is now reported as unused. The stack extent is tracked independently of panel visibility; regression test added.
- Compact layout could fail to tab panels together.
- Problems panel now distinguishes notes from warnings.

### Tests
About 270 tests (1.0: 186), including edge cases for address wrap-around, interrupt corners, undefined opcodes, numeric limits and unusual source text.

### Not in this release (planned)
Guided lessons/tutorial panel and exercise mode with grading, stable book-linked example IDs with chapter metadata, bus-cycle visualisation, student/instructor profiles,
macOS builds, AppImage/Flatpak, hardware comparison.

## 1.0.0
First public version: assembler, CPU with interrupts and T-states, debugger, dockable Qt interface, memory heatmap, themes, Linux and Windows packaging.
