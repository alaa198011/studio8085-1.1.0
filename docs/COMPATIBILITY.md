# Compatibility with GNUSim8085

Studio8085 can load GNUSim8085 programs, but the two tools are **not** identical. This page lists the differences that
were found by testing the real GNUSim8085 code (version 1.4.1, git snapshot dated 2019-03-03) side by side. Syntax and
CPU statements were checked by assembling or running probe programs in both tools. Rows marked † come from reading the
GNUSim8085 source and were not exercised in its GUI.

## How to check a program for GNUSim8085 compatibility

*Debug > Assembler syntax* (or *Preferences > Simulation > Assembler syntax*):

| Mode | What happens |
|---|---|
| Studio8085 syntax (default) | No checks |
| Note where GNUSim8085 would differ | Blue **notes** appear in the Problems panel and gutter: *"GNUSim8085 difference: the ORG directive ..."*. Nothing is blocked |
| GNUSim8085-compatible | The same findings are **errors**, so the program will not run until it uses only syntax GNUSim8085 accepts |

Checks cover the syntax table below plus semantic differences that change the machine code.
They cannot know about the *behavioural* differences in the last section.

## Syntax

| Construct | GNUSim8085 1.4.1 | Studio8085 | Flagged by compat check |
|---|---|---|---|
| Directives | `DB`, `DS`, `EQU` only | adds `ORG`, `DW`, `END` | yes |
| Label on its own line (code on the next line) | **rejected** ("Label should be given to a code line") | accepted | yes |
| Label without `:` (`COUNT EQU 5`) | rejected | accepted | yes |
| Indented label (`   loop: nop`) | accepted | accepted | - |
| Hex `0FFh` / `0AH` | accepted | accepted | - |
| Binary `101b`, octal `17o` | accepted | accepted | - |
| `0x10`, octal `17q`, decimal `10d` | rejected | accepted | yes |
| Character constant `'A'`, string `db "hi"` | rejected | accepted | yes |
| `$` (current address) | rejected | accepted | yes |
| `DS n,fill` | rejected | accepted | yes |
| Operand = number, symbol, or `symbol +/- number` (e.g. `table+1`, `count-0`) | accepted | accepted | - |
| `EQU` constant plus number (`k+1`) | accepted | accepted | - |
| `5+3`, `label+1+1`, `label+label`, `label+EQUconst` | rejected | accepted | yes |
| `*  /  %  &  \|  ^  ~  <<  >>`, parentheses, `AND OR XOR NOT SHL SHR MOD HIGH LOW` | rejected | accepted | yes |
| `EQU` with an expression (`k: equ 2+3`) | rejected | accepted | yes |
| Case of mnemonics and registers | not significant | not significant | - |

## Semantic differences (same text, different result)

| Construct | GNUSim8085 | Studio8085 | Flagged |
|---|---|---|---|
| **Negative literal** `mvi a,-5` | assembles as `05h` (the **minus sign is silently dropped**) | `FBh` (two's complement) | yes |
| Out-of-range value `mvi a,256`, `db 300`, `mvi a,-129` | silently truncated (`00h`, `2Ch`, `81h`) | **error** "does not fit in 8 bits" | no (Studio is stricter) |
| **Label case** | labels are case-sensitive (`Foo` and `foo` differ) | not case-sensitive; `Foo`/`foo` are the same label (defining both is an error) | yes, for mismatched references |
| Register name used as a label (`b: nop`) | accepted | **error** | no (Studio is stricter) |
| Default load address | set in the "Load me at" box | set in *Store code at* (default `0000h`); `ORG` overrides | - |

## Behavioural differences (execution)

GNUSim8085 was found to behave differently from the 8085 documentation in the following cases. Studio8085 follows the
documentation. Programs that happened to depend on the old behaviour will give different results.

| Behaviour | GNUSim8085 1.4.1 | Studio8085 |
|---|---|---|
| `POP`/`RET` when SP wraps through 0 (e.g. the first `POP` at power-on `SP=FFFFh`) | reads the wrong byte (`mem[-1]`, an out-of-bounds read); the bundled `debugexample.asm` never finishes | correct wrap |
| `RST n` | acts like `HLT` | pushes PC and jumps to 8 x n |
| `RIM`, `SIM` | no-ops (warning only) | implemented |
| `EI`, interrupts | none | implemented (TRAP, RST 7.5/6.5/5.5, INTR) |
| `DAA` | S/Z/P not updated in most cases (e.g. `99h+01h`, `DAA` leaves Z = 0) | S, Z, P, CY, AC all updated |
| AC after `SUB/SBB/CMP/DCR` | never set | set (hardware convention, selectable) |
| `ADC`/`SBB` with operand `FFh` and carry set | wrong CY (8-bit overflow of `operand + carry`) | correct |
| `SHLD` at `FFFFh` (`LHLD` takes the same path†) | writes the high byte into I/O port 0 | wraps to `0000h` |
| Debugger: Step Over / Step Out † | treats `CPI` as a CALL and does not recognise conditional returns | based on the stack pointer |
| Runaway program (`JMP $`) | the CPU core never returns (tested); the GUI has no run loop that could interrupt it † | Stop button; idle-loop detection |
| Opening a file given as a plain path on the command line | hangs | opens |

## Writing examples that run in both tools
1. Switch on **GNUSim8085-compatible** mode and fix every error it reports.
2. Avoid negative literals (write `0FBh`, not `-5`).
3. Avoid relying on the behavioural differences above: `RST`, `SIM`/`RIM`, `DAA` flag results, AC after subtraction, `POP` on an empty stack.
4. Put the first instruction at the load address; use `jmp start` over data as the GNUSim8085 samples do.
5. Keep label spelling identical in every use.

## Method
Probe programs were assembled with the real GNUSim8085 assembler (compiled headless from its source) and with Studio8085's
assembler. The nine sample programs shipped with GNUSim8085 assemble to byte-identical code in both. The reproducible CPU
comparison is in `tools/diff_vs_gnusim8085`.
