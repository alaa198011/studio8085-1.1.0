# Accuracy, scope and limitations

This document says exactly what Studio8085 models, how that was checked, and what has **not** been checked.
Where this page and the README disagree, this page wins.

## 1. What the simulator is

Studio8085 is an **instruction-level functional simulator** of the Intel 8085 with **documented T-state
accounting**. It executes one instruction at a time, updates registers, flags and memory exactly as the
instruction is defined, and adds the instruction's documented T-state cost to a running total.

It is **not cycle-accurate** and it does not model the chip at bus level. Please do not describe it as
"cycle-accurate" in teaching material; use *"instruction-level T-state accounting based on documented
instruction timing"*.

### Not modelled
- Machine cycles, ALE/RD/WR/IO-M/S0/S1 signals, bus timing diagrams, address/data bus values.
- `READY` and wait states, `HOLD`/`HLDA`/DMA, clock stretching, the `CLK`/`X1`/`X2` pins.
- Interrupt *sampling* inside an instruction: requests are checked at instruction boundaries only.
- The undocumented 8085 instructions (`DSUB 08`, `ARHL 10`, `RDEL 18`, `LDHI 28`, `LDSI 38`, `RSTV CB`,
  `SHLX D9`, `JNK DD`, `LHLX ED`, `JK FD`) and the undocumented K and V flags. Those ten opcodes stop the
  program with an "illegal opcode" message.
- Real peripherals. I/O ports are 256 editable bytes; `IN` reads one, `OUT` stores one and logs it.
- Serial I/O timing. `SID`/`SOD` are plain software bits.
- Power-up randomness. Registers and memory start at zero.

## 2. Behaviour reference

Status: **V** = verified against an independent source or test described in section 3,
**D** = implemented from the published description of the 8085 but not independently verified,
**C** = a deliberate convenience that differs from the real chip.

| Topic | Behaviour in Studio8085 | Status |
|---|---|---|
| Opcode set | All 246 documented opcodes: lengths and T-states match four published tables (see §3.3) | V |
| Reset state | PC = 0 (or the program entry), registers, flags, IE = 0, **RST 7.5/6.5/5.5 masked**, SID/SOD = 0 | D |
| Stack pointer initial value | `FFFFh` (the first `PUSH` writes `FFFEh`). The real chip leaves SP undefined | **C** |
| ALU flags S, Z, P, CY | Per the instruction definitions; checked exhaustively for ADD/ADC/SUB/SBB/CMP/ANA/XRA/ORA (register B form), INR/DCR (all registers) | V |
| AC after addition / INR | Carry out of bit 3 | V |
| AC after subtraction / CMP / DCR | **Default: carry out of bit 3 of `A + (not operand) + 1`** (what the 8085 ALU does). *Option:* textbook borrow convention (the opposite value). The two conventions are exact opposites | D |
| `ANA`/`ANI` | CY cleared, AC **set** (8085 behaviour) | V (vs. GNUSim8085 core) |
| `XRA`/`ORA` | CY and AC cleared | V |
| `DAA` | Standard correction (+06h if low digit > 9 or AC; +60h if high digit > 9 or CY); S, Z, P, CY, AC updated. Correct decimal result for every valid BCD pair with and without carry-in | V for valid BCD, D otherwise |
| `INX`/`DCX`/`DAD` | 16-bit wrap; `DAD` changes only CY | V |
| `PUSH PSW` / `POP PSW` | Flag byte `S Z 0 AC 0 P 1 CY`; bits 1, 3, 5 forced to 1, 0, 0 on POP | D |
| Address wrap | PC, SP, register pairs and 16-bit operands wrap at `FFFFh -> 0000h`, including an instruction whose operand bytes straddle the top of memory and a stack that crosses address 0 | D |
| `HLT` | Ends the run. An interrupt that is accepted resumes execution at its vector. T-states of the halt state are not counted (5 T-states are counted once, for the `HLT` itself) | D |
| `IN`/`OUT` | 256-byte port array; no device behaviour | C |
| `RST n` | Pushes PC, jumps to 8 x n | V (T-states), D (behaviour) |
| `EI` | Interrupts become enabled **after the instruction following `EI`** | D |
| `DI` | Disables interrupts and cancels a pending `EI` | D |
| Interrupt priority | `TRAP` > `RST 7.5` > `RST 6.5` > `RST 5.5` > `INTR` | D |
| Vectors | TRAP 0024h, RST 7.5 003Ch, RST 6.5 0034h, RST 5.5 002Ch, INTR = the `RST n` chosen in the panel | D |
| Interrupt acceptance | Resets IE, pushes PC, jumps to the vector, costs 12 T-states. **Assumption:** this also applies to `TRAP` (not verified; see §4) | D / assumption |
| `RST 7.5` | Edge-triggered **latch**: stays pending while masked or while IE = 0; cleared when taken or by `SIM` bit 4 | D |
| `RST 6.5`, `RST 5.5`, `INTR` | Modelled as **latched requests**: taken once, then cleared. (On the real chip 6.5 and 5.5 are level-sensitive inputs) | **C** |
| `SIM` | Bit 3 enables the mask change; bits 0-2 = M5.5, M6.5, M7.5; bit 4 resets the 7.5 latch; bits 6-7 = SOE/SOD | D |
| `RIM` | Bits 0-2 masks, bit 3 IE, bits 4-6 pending 5.5/6.5/7.5, bit 7 SID | D |
| Step Over / Step Out | Based on the real stack pointer, so conditional CALL/RET, RST and interrupts are handled correctly | V (unit tests) |

## 3. How it was verified

All of this can be re-run from the repository.

### 3.1 Property and exhaustive tests (`tests/test_cpu.py`)
- ADD, ADC, SUB, SBB, CMP: all 256 x 256 x 2 combinations of A, operand and carry-in, against a bit-by-bit
  full-adder model (a different method from the one the CPU uses). SUB/SBB/CMP are checked as
  *A + (not B) + (1 - carry-in)* with inverted carry-out, which is what establishes the hardware AC convention.
- ANA, XRA, ORA, INR, DCR: exhaustive.
- DAA: every pair of packed-BCD values (100 x 100) with and without carry-in, compared with real decimal
  arithmetic, including Z and P.
- Rotates, DAD, INX/DCX wrap, stack, XTHL, SPHL, PCHL, all 8 x 3 conditional jump/call/return forms, RST,
  IN/OUT on all 256 ports, interrupt priority and masking, EI delay, TRAP, SIM/RIM bits, T-states (`tests/test_edge_cases.py`,
  `tests/test_cpu.py`).

### 3.2 Differential test against the original GNUSim8085 core (`tools/diff_vs_gnusim8085`)
- 235 opcodes x ~400 random machine states = **93,990 runs, 0 mismatches** (registers, flags, memory windows,
  stack, all I/O ports).
- Excluded because the GNUSim8085 core is known to be wrong or incomplete there: RST, RIM, SIM, DAA, the AC flag
  after subtraction, and the carry/AC corner of ADC/SBB when the operand is FFh with carry set.
- This shows the two independent implementations agree wherever GNUSim8085 is right. It does **not** prove
  either is right on the real chip.

### 3.3 Published tables for lengths and T-states (`tests/test_opcode_reference.py`)
All 246 opcode entries (214 from a general table, 24 conditional jump/call/return forms and 8 `RST`s from two further
summaries) match, with 0 differences. Sources are *secondary* (course material and web references), not a scan of the Intel
datasheet:

- S1: <https://www.rfwireless-world.com/Tutorials/8085-instruction-set.html>
- S2: McGraw-Hill, "Instruction Set of 8085 Microprocessor" (conditional jump 7/10, call 9/18, return 6/12)
- S3: <https://loe.apps.uotechnology.edu.iq/wp-content/uploads/2024/10/CODES.pdf>
- S4: <https://mark-ogden.uk/files/intel/publications/8085%20Instruction%20Set.pdf> (opcode map; consistent with the conditional timings)

### 3.4 Real programs
- The nine sample programs shipped with GNUSim8085 assemble to **byte-identical** machine code, and the seven that can be
  compared end with identical registers. N-Queens runs 5.1 million instructions to the same answer.
- All 27 bundled examples have an automated test of their result: the ten larger ones in `tests/test_examples.py`, the 17 beginner
  ones in `tests/test_beginner_examples.py`.

- The Instructions panel (opcode, size and T-state columns) is generated from the same opcode table as the assembler. `tests/test_catalog.py` assembles the
  text each of the 246 rows inserts and checks that the first byte is the listed opcode and the length is the listed size, and compares 67 opcodes with a chart
  written out separately from the project's table (from Intel's published opcode chart).

- Memory handling when assembling is covered by `tests/test_keep_memory.py`: typed data and earlier results survive, `DB` and `DS n,fill` are initialised again, plain `DS` is left
  alone, and the previous version's unchanged bytes are removed.

### 3.5 Source-level behaviour
Assembler, debugger (step over/out, breakpoints, loop detection), trace export, state diff and GUI behaviour are
covered by the remaining tests (about 270 in total).

## 4. Not yet verified - please read before relying on it for assessment

1. **No comparison with physical 8085 hardware or a trainer kit has been made.** Everything above is software against
   software or against published tables.
2. **AC after subtraction.** Sources disagree on wording: the 8085 reverse-engineering analysis describes AC as the carry out of
   bit 3 of the ALU ([Ken Shirriff, "Reverse-engineering the flag circuits in the 8085"](https://www.righto.com/2013/07/reverse-engineering-flag-circuits-in.html)),
   which is the default here, while many textbooks describe a borrow. Both are provided; verify the choice on hardware before
   fixing the convention in a book.
3. **Does acceptance of TRAP reset IE?** Implemented as "yes, like every interrupt". Unverified.
4. **DAA on non-BCD input** and the **AC value after DAA** follow the common algorithm; not hardware-verified.
5. **RIM/SIM bit layout** is implemented from the published description; no hardware check.
6. **Instruction straddling `FFFFh`**, **stack crossing address 0**, **`LHLD`/`SHLD` at `FFFFh`** wrap in the obvious way; not hardware-verified.
7. **`INTR` acknowledge sequence**: only `RST n` vectors are supported (not a `CALL` placed on the bus).
8. **Tables S1-S4 are secondary sources.** A comparison with the Intel MCS-80/85 manual itself is still to be done.

### Recommended hardware/reference checks (in priority order)
`DAA` with valid and invalid BCD; AC after `SUB`/`CMP`/`DCR`; `CALL`/`RET` and conditional forms; interrupt entry/return
including `TRAP` and `EI` followed by `HLT`; `SIM`/`RIM`; stack wrap at 0000h/FFFFh; `HLT` wake-up; `IN`/`OUT`.

## 5. Validation labels for book examples

These are the definitions used in the book's front matter. **No label is inherited**: each example earns its own, and a
variation exercise carries a label only after it has been run or checked in its own right.

| Label | Meaning | What it does **not** prove |
|---|---|---|
| **T** | **Tool-tested**: assembled or run in the stated simulator, at the version recorded in the reproducibility table | Real timing, electrical behaviour or true interrupt behaviour |
| **M** | **Manually validated**: traced, calculated or checked independently by the author. Paper design exercises are M | That any code runs; pair with T where code exists |
| **H** | **Hardware-validated**: run on a specified physical system or circuit simulator, with a schematic and a measurement | Anything outside the documented setup |

Combinations (`T+M`, `T+H`, `M+H`, `T+M+H`) mean each check was done independently.

Add the label to a source file with a leading comment line `; @validation: T+M`; it is shown in the **Explain** panel
(hover the card for what the label does not prove).

**What the bundled examples claim.** Each of the 27 examples carries `T` only: its result is checked by an automated test
in this repository (`tests/test_examples.py`, `tests/test_beginner_examples.py`) under Studio8085 itself. None claims `M` or `H`. A book example labelled `T`
must be re-run in the simulator and version the book states; the label here does not transfer.

**What the simulator's own behaviour claims.** In the table of section 2, *V* means verified by an automated test or
differential run in this repository, which is **T-level** evidence only. No row has M-level evidence (an independent
manual check by the author of the book) and no row has H-level evidence (hardware) yet.

## 6. Known limitations (summary)
No bus-level timing, wait states, HOLD/DMA; no undocumented opcodes or flags; interrupts sampled at instruction boundaries; RST
6.5/5.5 and INTR latch instead of level-sense; no peripherals or serial timing; SP starts at `FFFFh`; one 64 KB RAM with no ROM/RAM map;
no hardware validation yet (§4).
