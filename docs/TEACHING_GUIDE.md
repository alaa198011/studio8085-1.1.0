# Teaching guide

Studio8085 supports a **predict - trace - assemble - run - compare - modify** cycle. This guide suggests how to use it in a course. It describes
what the program offers today; things planned but not yet built are marked *(planned)*.

## Before class
- Decide on the mode: **Beginner** for first sessions, **Advanced** once students meet stacks, interrupts and timing.
- Set *Assembler syntax* to **GNUSim8085-compatible** if students will also use that tool ([COMPATIBILITY.md](COMPATIBILITY.md)).
- Read [ACCURACY.md](ACCURACY.md) once: it lists what is not modelled so that you do not teach it by accident (bus timing, wait states, undocumented opcodes).

## Lectures: live demonstration
1. Open an example, press **Assemble**, and keep **Step** pressed while talking through the **Explain** panel.
2. Ask the class to predict the next register or flag value *before* the step; the *What just happened* table settles the argument. Tick **Predict first** in the Explain panel so the projected explanation does not give the answer away.
3. Use **Run to Cursor** and breakpoints to skip uninteresting loops; use **Speed** to show a loop slowly.
4. Edit a register or memory byte while paused ("what if A were FFh?") and step on.

Suggested path for a first course: the **Beginner** examples in order (`01`-`03` registers and arithmetic, `04`-`06` flags, `07`-`08` memory, `09`-`10` decisions and loops, `11`-`12` bits, `13`-`14` stack and subroutines, `15` ports, `16`-`17` 16-bit pairs and a complete small program); [EXAMPLES.md](EXAMPLES.md) lists what each one shows and its result.

Students who find mnemonics hard to remember can build programs from the **Instructions** panel (click an instruction; the operand placeholder is selected for typing). Its *Opcode* column and the status-bar *Machine code* make the step from mnemonic to machine code concrete: ask students to write a short program, **hand-assemble** it from the opcode column (`MOV A,B` = 78h, `MVI A,data8` = 3Eh + the data byte), and compare with the *Machine code* shown for each line or with the Listing panel. Typing by hand stays possible, so the list can be turned from a crutch into a reference as the course goes on (*Essential* shows only the instructions of the beginner examples; *All* shows every opcode).

Larger examples: `01` loops and `OUT`, `02` 16-bit totals and carry, `03` memory addressing and compare/branch, `04` BCD and `DAA`,
`07` CALL/RET and the stack (use **Step Into/Over/Out** and the Stack panel), `08` interrupts, `10` memory activity.

## Laboratories
Each example's first comment lines give its topic; the Explain panel shows it. A lab sheet can ask students to:
- predict the final register values, then verify (**Run**, read the registers);
- find and fix the deliberate mistakes in a prepared file (the Problems panel names each one);
- modify an example (new data, different loop count) and explain the change;
- extend a program with a subroutine and show the stack depth with the Stack panel.

## Memory between runs
Memory is kept between runs by default (as on a trainer kit): students can type input data into memory and then run. Two consequences to mention: a variable reserved with a plain `DS` keeps the
last run's value (a counter in a `DS` byte continues counting), while `DB` data and `DS n,0` are set again at every assembly; and results of one run are visible to the next. If an
exercise needs every run to start from clean memory (for example when answers are compared), tell students to switch off *Preferences > Simulation > Keep memory contents...*, or to use
*Debug > Clear Memory and Heat* before running.

## Trace-table exercises
1. Turn on *Debug > Record Execution Trace*, run or step the program.
2. *Debug > Export Trace...* gives **CSV** (spreadsheet), **Markdown** (book or wiki), **HTML** or **PDF** (print / hand-in).
3. Students compare their hand-made trace with the exported one; the columns are the same as a classic trace table (instruction, registers, flags, T-states).
Registers and flags are shown *after* each instruction. Memory writes, port I/O and interrupts appear in the **Events** column.

## Timing exercises
- The status bar and the Flags panel (Advanced) report instructions, T-states and elapsed time at the chosen clock (default 3 MHz).
- Classic exercise: delay loops. `MVI B,n` followed by `DCR B` / `JNZ` costs `7 + 14n - 3` T-states for the loop (the last `JNZ` is not taken); students derive the formula and check it against the counter.
- Remind students that this is *instruction-level T-state accounting from documented timing*, not a bus-cycle simulation.

## Interrupt demonstrations
Example `08`: enable `RST 7.5` with `SIM`/`EI`, sleep in `HLT`, then press **RST 7.5** and **TRAP** in the Interrupts panel. Ask first what happens if the interrupt is
masked; the status bar explains when a request cannot be taken. Discuss why the handler executes `EI` before `RET`.

## Homework and assessment
- Ask for the exported trace or a screenshot together with the answer, and for a short explanation in the student's own words.
- Make each student's data different (a `DB` list) so that results cannot be copied.
- Use the *validation* idea for your own examples: put `; @validation: T`, `T+M` or `T+M+H` at the top of the file ([ACCURACY.md §5](ACCURACY.md#5-validation-labels-for-book-examples)).
- *(Planned)* built-in exercise mode with hidden lines, prediction questions and grading; lesson files; student profiles.

## Common misconceptions the tool helps with
| Misconception | Where to look |
|---|---|
| "CY is the sign of the result" | Explain: *CY changed ... carry out of bit 7* vs the S flag |
| "INR/DCR set CY" | Explain lists CY under *not affected* for INR/DCR |
| "CMP changes A" | Explain: *only the flags change, A stays* |
| "A conditional jump always costs the same" | Explain shows 7/10 T-states and whether the branch will be taken |
| "The stack grows upward" | Stack panel and SP in the status bar |
| "An interrupt happens immediately" | `EI` delay; the Interrupts panel explains masked/pending requests |
| "Subtraction sets AC like addition does" | Preferences: hardware vs textbook convention; Explain names the convention in use |
