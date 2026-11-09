# Examples

8085 Studio ships 27 programs under **File > Examples**:

- **Beginner: the essential instructions** - 17 short programs (each under 45 lines, fewer than 100 instructions executed),
  one idea per program, in the order a first course teaches them.
- Ten larger programs (counter, sorting, BCD, interrupts, ...), listed below the beginner set.

Every program starts with `; @title`, `; @topic` and `; @validation: T` lines (shown in the **Explain** panel) and explains
itself in comments. `T` means the result is checked by an automated test in this repository
([ACCURACY.md section 5](ACCURACY.md#5-validation-labels-for-book-examples)); it does not claim `M` or `H`.

Beginner mode opens `01 Your first program` on the first start. Press **F7** to assemble, **F11** to step, and tick
**Predict first** in the Explain panel to guess each result before it is shown.

## Beginner set

| # | Program | Instructions introduced | What to observe | Result |
|---|---|---|---|---|
| 01 | Your first program | `MVI` `NOP` `HLT` | The highlighted line is the *next* instruction. Decimal and `0FFh` hex constants. | A=5, B=10, C=FFh |
| 02 | Moving data between registers | `MOV` | `MOV` copies; the source keeps its value. Swapping needs a third register. | D=E=42h; A=2, B=1 |
| 03 | Adding numbers | `ADD` `ADI` `STA` `DS` | Arithmetic happens in A. A label names a memory byte. | memory `result` = 50 |
| 04 | Subtracting, and what "borrow" means | `SUB` `SUI` | 5 - 10 wraps to FBh and sets CY: the borrow. | `diff` = 32, FBh; CY=1 |
| 05 | Counting up and down | `INR` `DCR` `INX` `LXI` | Z lights when a count reaches 0; `INR`/`DCR` never change CY. | B=3, C=0, HL=0100h, D=0 (Z=1, CY=0) |
| 06 | The carry flag | `ADC` `STC` `CMC` | 255+1 sets CY and Z; `ADC` carries into the next byte (01FFh + 1 = 0200h). | HL=0200h, CY=0 |
| 07 | Reading and writing memory | `LDA` `STA` `DB` `DS` | `DB` gives a byte a starting value; `DS` reserves zeros. | memory `total` = 42 |
| 08 | HL as a memory pointer | `LXI H` `MOV A,M` `MVI M` `INR M` | `M` is memory reached through HL, not a register. | table = 11h 23h 33h; A=22h |
| 09 | Making a decision | `CPI` `JZ` `JC` `JMP` | `CPI` changes only flags (Z = equal, CY = smaller). Change the `7` and re-run. | B=1 (below 10), 2 (equal), 3 (above) |
| 10 | A loop with a counter | `DCR` + `JNZ` | The classic count-down loop. Set a breakpoint on `again`. | memory `total` = 55 (10+9+...+1) |
| 11 | Bits: AND, OR, XOR and complement | `ANI` `ORI` `XRI` `CMA` `XRA A` | Watch the BINARY column of A. `XRA A` clears A, sets Z, clears CY. | B=05h, C=A5h, D=F0h, E=0Fh, A=0 |
| 12 | Rotating bits: doubling and halving | `RLC` `RAR` `ORA A` | `RLC` doubles; `RAR` halves and moves the odd bit into CY. | B=20, A=2, CY=1 (5/2 = 2 remainder 1) |
| 13 | The stack: PUSH and POP | `LXI SP` `PUSH` `POP` `PUSH PSW` | Last in, first out; SP moves by 2. Open the Stack panel (Advanced mode). | BC=2222h, DE=1111h, A=7, SP=2000h |
| 14 | A simple subroutine | `CALL` `RET` | Step Into, Step Over and Step Out on the same `CALL`. | A=24, SP back to FFFFh |
| 15 | Input and output ports | `IN` `OUT` | Type a value for port 00h *before* running. | port 01h = port 00h + 1 (41h gives 42h) |
| 16 | 16-bit register pairs | `DAD` `XCHG` `INX` `DCX` | `DAD` adds pairs and changes only CY. | HL=0233h, DE=1235h |
| 17 | Copying a list of bytes | `STAX` with pointers and a loop | Everything together: two pointers and a counter. Watch `dest` fill. | `dest` = 10 20 30 40 50 |

Together these use `MVI MOV LXI LDA STA STAX XCHG PUSH POP ADD ADI ADC SUB SUI INR DCR INX DCX DAD ANI ORI XRI XRA ORA CMA
CPI RLC RAR STC CMC JMP JZ JC JNZ CALL RET IN OUT NOP HLT`; a test fails if any of these is missing from the set.

Suggested order for a first lab: 01 - 03, then 05, 07, 09, 10 (the first loop), then 14, then 17.

## Larger programs

| # | Program | Shows |
|---|---|---|
| 01 | Counter LEDs | a loop with `OUT` |
| 02 | Sum array | 16-bit totals and carry |
| 03 | Bubble sort | memory addressing, compare/branch, duplicates |
| 04 | BCD add | `DAA` |
| 05 | Fibonacci | a series stored in memory |
| 06 | Multiply | repeated addition |
| 07 | Subroutines | `CALL`/`RET`, `PUSH`/`POP`, the Stack panel |
| 08 | Interrupts | `TRAP`, `RST 7.5`, `SIM`, `EI`, sleeping in `HLT` |
| 09 | Reverse a string | two pointers, a 16-bit compare, ASCII data |
| 10 | Fill and copy a memory page | block moves and the memory heatmap |

## Trainer Kit lab programs

Three more programs, under **Lab** (not counted in the 27 above), use the Virtual 8085 Trainer Kit
(see [TRAINER_KIT.md](TRAINER_KIT.md)):

| Program | Shows |
|---|---|
| E1 Read switches, control LEDs | `IN 00H` / `OUT 01H` / `HLT` - the program of Experiment 1 |
| E1b Seven-segment raw bits | `MVI A,76H` / `OUT 02H` lights b, c, e, f, g = **H**; `F6H` adds the decimal point |
| E1c Seven-segment hex decode | `IN 00H` / `OUT 01H` / `OUT 02H` with the display in Hex decode mode: the low nibble as 0-F |

Each has a result test in `tests/test_trainer_gui.py` and `tests/test_peripherals.py`.

## Adding your own

Put `; @title: ...`, `; @topic: ...` and `; @validation: T` in the leading comment block of any `.asm` file. The Explain panel
shows them. Keep the label honest: use `T` only if a test checks the result.
Beginner programs are plain text in `src/studio8085/examples/beginner/`; add `tests/test_beginner_examples.py` entries for new ones.
