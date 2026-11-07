# Virtual 8085 Trainer Kit

8085 Studio can show a small **virtual trainer kit**: 8 toggle switches, 8 LEDs and one seven-segment digit
with a decimal point, connected to the CPU's `IN` and `OUT` instructions. It is meant for first lessons on
ports: a student sets the switches, runs `IN`, sees the byte arrive in the accumulator, runs `OUT` and sees
the LEDs light.

Open it with **Lab > Show the Virtual 8085 Trainer Kit** or **View > Virtual 8085 Trainer Kit**.

> **Virtual, not real hardware.** The port numbers, bit order, segment wiring and polarity below are
> *teaching conventions chosen for this program*. They are not the addresses or wiring of any real 8085
> trainer (real kits decode their own addresses, usually through an 8255 PPI, which is not modelled).
> Timing, electrical behaviour, switch bounce and multiplexed displays are not modelled either.

## Ports (defaults)

| Device | Instruction | Port | Bits |
|---|---|---|---|
| 8 switches SW7...SW0 | `IN 00H` | 00H | bit n = SWn; up = 1, down = 0 |
| 8 LEDs LED7...LED0 | `OUT 01H` | 01H | bit n = 1 lights LEDn (active-high) |
| Seven-segment digit + DP | `OUT 02H` | 02H | see below |

SW7 and LED7 (the most significant bit) are on the **left**, as you write a binary number.

The ports can be changed with **Lab > Trainer Kit Port Mapping...** (or *Ports...* in the panel). Rules:

* every port is a number from 00H to FFH;
* the LEDs and the display must use different `OUT` ports (otherwise the dialog reports a port conflict and
  will not accept the change);
* an `IN` port and an `OUT` port may share a number (for example switches on IN 01H and LEDs on OUT 01H),
  because `IN` and `OUT` are different bus cycles.

The choice is remembered between sessions.

## Switches and the I/O Ports table

While the kit is **connected** (the *Kit connected* box, on by default) the switches **own** their port:

* `IN 00H` always reads the switch byte;
* the I/O Ports table row 00h mirrors the switches, so the table always shows what `IN` will read;
* typing a value into that row of the I/O Ports table sets the switches (the existing beginner lesson
  "Input and output ports" therefore still works exactly as it describes);
* `OUT 00H` still writes the table as before, but it does not move the switches (they are an input).

Ports that no device owns behave exactly as before: `IN` reads the I/O Ports table, `OUT` writes it and is
logged in the Output panel. `OUT 01H` and `OUT 02H` also still write the table and the Output log, in
addition to driving the LEDs and the display.

When the kit is **disconnected**, it is not attached to the CPU at all: `IN`/`OUT` behave byte-for-byte as
in 8085 Studio 1.1.0 (this is tested). The last switch value stays in the I/O Ports table row as if it had
been typed there.

## LEDs

Each `OUT` to the LED port latches the byte: LEDn is lit when bit n is 1. The panel shows the last value in
binary and hex. The LEDs never change registers or flags.

## Seven-segment display

```
     aaa
    f   b
     ggg
    e   c
     ddd   DP
```

### Raw segment bits (default)

Each bit drives one segment, **active-high** (1 = lit):

| bit | 7 | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|---|
| segment | DP | g | f | e | d | c | b | a |

Example: `76H` = 0111 0110b lights b, c, e, f, g = the letter **H**; `F6H` adds the decimal point.

The segment order and an active-low polarity (0 = lit, as for a common-anode digit) are available in the
core model (`SevenSegment(segment_order=..., active_low=...)`) for authors of other exercises; the panel
uses the active-high default above. Both are teaching conventions, not a description of a real display.

### Hex decode (optional)

Choose *Hex decode (low nibble)* in the panel. Bits 3-0 select a digit; **bits 7-4 are ignored and the
decimal point stays off**. Polarity does not apply in this mode (the decoder drives the segments).

| low nibble | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | A | B | C | D | E | F |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| shown | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | A | b | C | d | E | F |
| segments (gfedcba) | 3F | 06 | 5B | 4F | 66 | 6D | 7D | 07 | 7F | 6F | 77 | 7C | 39 | 5E | 79 | 71 |

Switching the mode only changes how the latched byte is drawn; it never touches the CPU.

## Resets

| Action | Switches | LEDs and display |
|---|---|---|
| Assemble, Restart, opening another program | kept | blank (no OUT yet) |
| Stop, Pause, breakpoint, mode switch | kept | kept |
| **Reset hardware** (panel button or Lab menu) | all down (0) | blank |

The CPU and memory are never changed by the kit's reset.

## Experiment 1: Read Switches and Control LEDs

**Lab > Experiment 1** opens the kit with a guided flow underneath it.

Learning objectives: the purpose of `IN`, the purpose of `OUT`, the role of the accumulator, reading an
8-bit binary number, predicting the LEDs, running and debugging a program step by step.

The program (`examples/trainer/E1_read_switches_control_leds.asm`):

```
START: IN 00H
       OUT 01H
       HLT
```

1. **Set the switches** to any pattern.
2. **Predict the LEDs**: type the pattern you expect, as 8 binary digits (`10100101`) or hex (`A5h`), and
   lock it in. Until you do, the answer is hidden everywhere (see below), and Run and Step wait for your
   prediction. *Help me* reveals the answer and the reason, if you ask for it.
3. **Assemble**: *Load and assemble the program* (or F7).
4. **Step through** with Step Into (F11).
5. **Observe A after IN**: the guide reads the accumulator from the CPU.
6. **Observe the LEDs after OUT**: the guide reads the LED latch.
7. **Compare**: your prediction against the real LEDs, naming every LED that differs.
8. **Explain**: why the LEDs show what they show.

Nothing is graded and nothing is hard-coded: if the program is changed (for example to read another port),
the comparison follows what the CPU really did.

**What is hidden before you predict** (shown as `??`, using the *configured* ports, not fixed 00H/01H/02H):

* the Trainer panel: the switch value readout, the LED value readout and lamps, the display latch and segments;
* the I/O Ports table: the value, decimal and binary cells and the tooltip of the switch, LED and display
  port rows (the port number stays);
* the Output log: the value of each `OUT` line to those ports (earlier runs included);
* the Explain panel: the port value of `IN` and the `A = ...` of `OUT`, and the previous step's before/after table;
* the Trace table (it records A and the I/O effects).

This is **display only**: `cpu.io`, the switches, the CPU and the peripherals are never changed, and the
real values are what a program reads and writes (tested). Everything is shown again as soon as you lock in a
prediction, press *Help me*, press *End experiment*, or open or start another program. The positions of the
switch knobs themselves are your own input, so they stay visible. The Registers panel is not masked; Run and
Step are refused until you predict, so A cannot be read early (a value left in A by an earlier run is not
cleared).

Two more lab programs are in **Lab**:

* *Seven-segment raw bits* (`E1b_seven_segment_raw.asm`): `MVI A,76H` / `OUT 02H` shows **H**, then `F6H`
  shows **H.**; the same byte goes to the LEDs so each segment's bit can be seen.
* *Seven-segment hex decode* (`E1c_seven_segment_hex.asm`): `IN 00H` / `OUT 01H` / `OUT 02H` with the
  display in Hex decode mode (opening it from the Lab menu selects that mode): SW3...SW0 = 1010 shows **A**.

## Where the panel appears

* **Advanced mode**: a tab next to Stack / I/O Ports / Symbols (Stack stays in front).
* **Beginner mode**: hidden by default when no lab is running, so the beginner layout stays as small as
  before; the Lab menu and the View menu bring it back as a tab next to Explain / Instructions. Starting
  **Experiment 1** or a **Lab program** shows it and keeps it visible for the whole lab: through switches
  between Beginner and Advanced mode and *Reset layout*. The lab ends with *End experiment* or when you open
  or start another program; the next Beginner layout then hides the kit again. A new session never starts in
  a lab, so a session restored in Beginner mode shows exactly the Beginner panels.
* The panel scrolls inside its dock instead of making the window bigger, so the window still fits small
  screens (tested at 800x600 to 1920x1080, and at 150 % and 200 % scaling).
* Saved layouts are respected. A layout saved by 8085 Studio 1.1.0 (before the kit existed) restores every
  old panel as it was; the kit then takes its default place for the mode.

### Responsive layout (small windows)

The code editor always keeps at least **440 logical pixels** (about 60 source columns plus the line-number
gutter) and the panels scroll instead of squeezing it. On a window narrower than about 980 px the panels
of the left and right sides are gathered into **one tabbed column** (Registers, Flags, Explain, ..., Trainer
Kit); no panel is closed or hidden, and a panel opened from the View menu joins the group. When the window
is wide again (about 1040 px) they separate to where they were, unless you rearranged the panels yourself in
the meantime. The grouping is never saved as your layout, and a layout saved on a large screen is clamped
the same way when it is restored on a small one. Sizes are logical, so it behaves the same at 125 %, 150 % and
200 % display scaling.

## While a program runs

The CPU runs in batches from a timer on the GUI thread; the kit is redrawn from the normal refresh path
(after each step, and about every 80 ms while running), never once per instruction, and never from another
thread. A program that changes the LEDs faster than that shows the value at each refresh. Flipping a switch
while a program runs is allowed, as on a real kit: the next `IN` reads the new position.

## Limitations

* One seven-segment digit only; no multiplexed displays, keypad, 8255 PPI, timers or interrupts from the
  kit (out of scope for this phase).
* No timing or electrical model (no switch bounce, no LED persistence or brightness, no propagation delay).
* Outside Experiment 1 the I/O Ports table shows (and can change) the switch port; inside it the value is
  hidden until the prediction (above). A student can still read the switch knobs, the Registers panel's
  stale contents, or the source program - the masking is a teaching aid, not a security boundary.

## Architecture (for developers)

* `src/studio8085/core/peripherals.py` (no Qt): `Peripheral`, `SwitchBank`, `LedBank`, `SevenSegment`,
  `PeripheralBus`, `PortMap`, `TrainerKit`.
* The bus uses the CPU's existing `on_in` / `on_out` hooks and **chains** to the hooks installed before it:
  the previous `on_out` (the debugger's OUT log) is always called first; a port no device owns falls
  through to the previous `on_in`, then to the I/O Ports table. `cpu.events` (the trace) is written by the
  CPU itself and is unchanged. **No CPU instruction semantics changed.**
* Disconnected = detached: `cpu.on_in` / `cpu.on_out` are the original objects again.
* A new peripheral is a `Peripheral` subclass with `in_ports` / `out_ports`, added with `bus.add(...)`;
  conflicts are rejected with `PortConflictError`.
* `src/studio8085/ui/trainer.py`: the panel (vector QPainter drawing), the port dialog and the Experiment 1
  guide. `MainWindow` owns one `TrainerKit` for its `Machine`.
