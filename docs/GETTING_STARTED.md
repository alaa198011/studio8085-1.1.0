# Getting started in five minutes

## 1. Install
- **Linux:** `./packaging/linux/install.sh` (needs Python 3.9+ with `venv`; on Debian/Ubuntu also
  `sudo apt install libxcb-cursor0`). Start **8085 Studio** from the application menu.
- **Windows:** install Python 3.9+ from python.org, then double-click `packaging\windows\install_windows.bat`.
  Start **8085 Studio** from the Start menu.

The first start opens in **Beginner mode** with an example already loaded.

## 2. Look at the screen
- **Middle:** your program. Numbers on the left are line numbers; click next to a number to set a red breakpoint.
- **Left:** the registers and the five flags (S, Z, AC, P, CY).
- **Right, top:** the **Explain** panel - it tells you what the next instruction does and what the last one changed. Its second tab, **Instructions**
  (also the toolbar button or `Ctrl+I`), is a list of all instructions with their opcodes: click one to put it in your program.
- **Right, bottom:** memory as a table of hex bytes.
- **Toolbar:** *Assemble, Run, Pause, Stop, Restart, Step, Over, Out*.

## 3. Run your first step
1. Press **Assemble** (F7). The first instruction is highlighted and the Explain panel describes it.
2. Press **Step** (F11) once. Look at *What just happened*: the table lists every register, flag or memory byte that changed.
3. Read the flag explanation under the table, for example *"CY changed from 0 to 1: the addition produced a carry out of bit 7."*
4. Keep pressing **Step** and watch **A** (the accumulator) and the flags change.
5. Press **Run** (F5) to finish the program. The status bar reports how many instructions and T-states it took.

## 4. Change something
- Edit a number in the source (for example `mvi a,5` to `mvi a,200`) and press **Run** again - the program is re-assembled automatically.
- Store the program somewhere else: type an address (for example `2000`) in **Store code at** on the toolbar, press Enter and Assemble. The Memory panel shows the code at that address.
- Add an instruction without typing it: open the **Instructions** tab, click `INR r` and then `INR A`. The line appears below the cursor with its opcode in the status bar; `Ctrl+Z` undoes it.
- Mistakes are underlined while you type; hover over the line to read the message, or open the **Problems** panel.
- Double-click a register value or a memory byte to edit it directly while the program is paused. Values you type into memory are kept when you run, step or restart
  (switch this off in *Preferences > Simulation*).

## 5. Go further
- **File > Examples > Beginner** has 17 short lessons on the essential instructions (start with `01`); below them are ten larger programs, from a counter to interrupts. See [EXAMPLES.md](EXAMPLES.md).
- Switch **Mode** (toolbar) to *Advanced* for the stack, I/O ports, symbols, listing, interrupts, trace and the memory heatmap.
- **Debug > Record Execution Trace** keeps a table of every instruction; **Debug > Export Trace...** saves it for a lab report.
- `F1` opens the instruction reference.

If something looks wrong, check [USER_GUIDE.md](USER_GUIDE.md); for what the simulator does and does not model,
see [ACCURACY.md](ACCURACY.md).
