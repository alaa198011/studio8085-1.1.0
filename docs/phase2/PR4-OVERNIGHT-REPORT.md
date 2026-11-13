# PR #4 overnight report (release 1.2.0 preparation)

Branch `feature/phase2-visual-cpu`. Status legend: DONE = finished and verified locally, PENDING = not finished.

## 1. What was fixed

### Alaa's four requests (PR #3 review) - DONE
1. Memory cells used by each step: WRITE/READ rows with values in the diagram and R/W marks in the Memory dock.
2. Readable text in all three themes, plus the Size option (Fit / 100 / 125 / 150 / 200 %).
3. Stack pointer contents: `[SP]`, `[SP+1]`, the 16-bit word and the top words.
4. Enlarge / Restore with an icon, tooltips, accessible names and exact restore of the dock state.

### QA round 1-2 defects - DONE
- Experiment 1 answer leak in the Registers dock (stale A from an earlier run); pre-existing since Phase 1.
- Ctrl+= / Ctrl+- ignored in the docked or floating CPU panel (window action and panel shortcut were ambiguous).
- F5 / F10 / F11 not working while the view was enlarged (separate top-level window).
- Flow arrows crossing the register-pair titles.
- Full audit of every surface for the concealed value in hex, binary, decimal and signed form.

### Round 3 (D1-D3) - DONE
- D1: at 800x600 the docked panel was wider than its dock (minimum 520 px). The header now wraps to more rows, the panel minimum is
  300 px, every control is inside the dock viewport, the editor keeps at least 440 px.
- D2: Enlarge then Restore reset the horizontal scroll; the zoom level and both scroll positions are now saved and restored.
- D3: Experiment 1 now masks A, B, C, D, E, H, L, the pairs BC/DE/HL and the flags (Registers dock, Flags dock, diagram), with identical
  placeholders so nothing says which register holds what. PC and SP stay visible. Presentation only; the test asserts the CPU, memory,
  ports and machine state are identical. RAM is not masked (see section 3).

### Release prep - DONE
Version 1.1.0 to 1.2.0 in `pyproject.toml`, `src/studio8085/__init__.py`, `packaging/windows/studio8085.iss`; new `CHANGELOG.md`.

## 2. QA summary (independent verification pass, real windows)
Six sections: (1) sizes x themes, docked and floating; (2) Labs A, B, C; (3) Experiment 1 masking, lock and reveal; (4) keys;
(5) Alaa's four fixes; (6) fonts. Results: sections 2-6 PASS; section 1 found D1 (fixed above). Equivalence of the CPU panel on and
off: 33 programs, 66 comparisons, 0 differences. 119+ evidence PNGs and all scripts live outside the repository in
`studio8085-proposals\pr4-qa` (and `pr4-qa\final`). Full details: `pr4-qa\final\QA-RESULTS.md`.
Local tests (offscreen, per file in parallel, test_gui included): 25 files, 997 passed, 0 failed (test_gui 114 passed in 27 min). After the round-3 fixes the real-window scripts c1s (800x600 header), c5 (Alaa, 33 checks, 0 fail) and t13 (masking, F11 enlarged) were re-run; evidence in `pr4-qa\final`.

## 3. Remaining limitations
- RAM in the Memory dock is not masked during Experiment 1 (an earlier program may have stored the answer there).
- Memory reads are shown only on Step Into (access tracking), not during Run.
- A physical Ctrl+Shift+= keypress was not tested (synthetic key events only; Ctrl+= and Ctrl+Plus were tested).

## 4. CI
Pending - see PR #4 checks.

- 62c785e: Linux 3 failures (font-metric layout), fixed in the next commit (local, not yet pushed; layout now derived from font metrics, tests run with the default and a wide font).
- Test stage was 3-6 h per OS: closed MainWindows were never deleted, so every later test got slower. Fixed by deleting leftover windows after each test; CI is split into unit / gui / package jobs with timeouts.

## 5. Decisions for owner
- **RAM masking in Experiment 1.** Options: (a) keep as is and document it (current); (b) hide the Memory dock values (or only cells
  written by an earlier run) while the answer is concealed; (c) clear RAM when Experiment 1 starts (changes machine state, so it
  contradicts the display-only rule). Not implemented; needs an owner decision.
- Merge PR #4 and release 1.2.0 (authorized, not done by this report; no tag or release has been created).
