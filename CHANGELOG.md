# Changelog

All notable changes to 8085 Studio are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses semantic versioning.
Longer notes per release are in `docs/RELEASE_NOTES.md`.

## [1.2.0]

Covers the foundation work (Phase 0), the Virtual 8085 Trainer Kit (Phase 1), the Interactive CPU Architecture panel
(Phase 2) and the review and QA fixes of PR #4. No CPU instruction, the assembler, the machine or the opcode table changed
(a guard test checks it).

### Added
- Virtual 8085 Trainer Kit dock (Phase 1): 8 switches on `IN 00H`, 8 LEDs on `OUT 01H`, a seven-segment digit on `OUT 02H`
  (raw segment bits or hex decode), configurable and validated port mapping, keyboard and mouse operation.
- Experiment 1 "Read switches and control LEDs": a guided predict - assemble - step - compare flow whose answer stays hidden
  until the student predicts or asks for help; lab programs under `examples/trainer/`.
- Responsive workspace: the editor keeps at least 440 px, docks regroup on narrow windows, visible check boxes in the Light and
  High Contrast themes.
- Interactive CPU Architecture panel (Phase 2): vector diagram of registers, pairs, flags, ALU, buses, memory and ports with
  step-by-step data-flow arrows, an explanation of each step, three labs (register transfer, ALU and flags, trainer I/O),
  Explain / Animate / Reduce motion / Decimal options, speed, replay, Size (Fit to 200 %), zoom, and an enlarged full-window view.
- Memory cells used by each step (R/W with the old and new value) in the diagram and marked in the Memory dock; stack-pointer
  contents (`[SP]`, `[SP+1]`, word, top words).
- Keyboard: Ctrl+= / Ctrl+- / Ctrl+0 zoom the CPU panel when it has the focus (the editor otherwise), Ctrl+Shift+F enlarges,
  Esc restores; F5 / F10 / F11 / Shift+F11 also work while the view is enlarged.

### Changed
- The CPU panel header (options, speed, replay, size, zoom, enlarge) wraps onto more rows in a narrow dock instead of being cut off.
- Enlarge followed by Restore keeps the diagram's zoom level and scroll position.
- Version 1.2.0.

### Fixed
- A session saved in Beginner mode restored all panels instead of the Beginner set.
- Experiment 1 answer leaks: before the prediction the Registers dock showed a stale value left by an earlier run, and a stale copy
  in B, C, D, E, H, L, the register pairs or the flags would have shown too. All of them (and the diagram's boxes, pairs and flags)
  now show `??`; display only, the CPU, memory and ports are untouched.
- Ctrl+= and Ctrl+- did nothing in the docked or floating CPU panel (ambiguous shortcut).
- F5 / F10 / F11 did nothing while the CPU view was enlarged.
- A flow arrow crossed the "Register pair BC/DE/HL" titles.
- CALL explanation: the return address is PC + instruction length.

### Known limitations
- The Memory dock shows raw RAM, which is not masked during Experiment 1 (an earlier program may have stored the answer there).
- Memory reads are shown on Step Into (with access tracking on), not while Run is active.

## [1.1.0]

Previous release. See `docs/RELEASE_NOTES.md`.
