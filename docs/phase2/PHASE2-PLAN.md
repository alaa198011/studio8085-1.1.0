# Phase 2 plan: Interactive CPU Architecture (visual CPU)

Branch `feature/phase2-visual-cpu`, created from Phase 1 head `bd82989` (Draft PR #1, awaiting owner review).
Nothing is pushed. CI status: PENDING.

## Interfaces inspected (findings that shape the design)
- `Machine.run_chunk` / `cpu.step()` is the single execution engine. `MainWindow._begin` (before) and `_finish`
  (after) bracket every Step Into / Over / Out / Run; that is where passive capture attaches. The CPU, Machine,
  assembler and debugger are not modified.
- `cpu.on_in` / `cpu.on_out` belong to `PeripheralBus` (which chains the Machine OUT log). The visualizer does not
  install hooks; it reads the Machine OUT log counters and decodes IN/OUT operands, so the bus restore logic is untouched.
- `Memory` already counts reads/writes (`rd`, `wr`). Memory accesses are *observed* by counter deltas on the
  addresses an instruction can touch; anything else is labelled expected/conceptual.
- `core/explain.py` (`explain_instruction`, `flag_notes`) already produces correct plain-language text; reused.
- Experiment 1 answer masking: `TrainerPanel.concealed` (set until the student predicts or asks for help) and
  `_begin` refuses to step while concealed. The CPU panel also masks every kit value and clears its last step while
  concealed, and re-reads the same flag; no second copy of the rule.

## Layers (strictly separate)
1. `core/visual.py` (no Qt): immutable `CpuState`, `StepRecord`, diff, instruction families, logical flows,
   explanations, bounded `StepHistory`, `StepRecorder` (begin/end around a debugger action; passive).
2. `ui/cpuview.py` (Qt): `CpuArchitecturePanel` (QGraphicsView vector diagram + controls + text), consumes only
   `StepRecord` / `CpuState`. Never touches the CPU.
3. `core/lab_content.py`: the three teaching labs as data (objectives, steps, expected outcomes, feedback, programs);
   the UI only renders it. Programs live in `examples/trainer/`... as `.asm` files so the existing example tests cover them.
4. `MainWindow` wiring: a separate `cpu_dock` (not in `self.docks`, so existing panel-set tests and Beginner layout
   rules are unchanged), View/Lab menu entries, throttled refresh during Run, capture in `_begin`/`_finish`.

## Behaviour
- Step Into: pre `CpuState` -> existing engine -> post `CpuState` -> diff -> record. Memory/port changes from byte diff
  (64K copy only for single steps) and counter deltas. Step Over/Out/Run: summarised (N instructions) generic view.
- Families with detailed flows: data transfer, arithmetic, logical, control flow, stack, I/O, NOP/HLT. Others get a
  generic before/after view and no animation. Flows are drawn solid when the destination change was observed and
  dashed when conceptual only; micro-operations are always labelled "conceptual explanation".
- Explain Execution toggle (default off), animation speed, disable-animation, reduced motion (OS hint + preference),
  Pause / Skip, Replay of the stored record (no CPU access). Animation is a QTimer on the UI only.
- Run: panel refresh coalesced to <= ~10 Hz and only when visible.
- Themes: Dark / Light / High Contrast via existing `Theme` colours; state also encoded by line style, text and
  badges (not colour alone). Hex + binary always, decimal optional.
- Phase 1: input port -> A -> output port -> LEDs chain for `IN 00H / OUT 01H / HLT`, using the kit's ports and values.

## Tests / evidence
`tests/test_visual_core.py`, `tests/test_visual_gui.py`, `tests/test_visual_labs.py`; full regression (baseline 793);
screenshots at 5 sizes, 3 themes, 3 labs; performance on/off; PyInstaller build + `--selftest`.
