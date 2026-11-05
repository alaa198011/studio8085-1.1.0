"""Teaching content for the three Phase 2 labs. Data only: no Qt, no CPU access beyond the read-only
``CpuState`` / ``KitView`` snapshots handed to ``check``. The UI renders whatever is here.

These labs are additional to, and do not change, the approved Phase 1 Trainer Kit labs (Experiment 1 and the
seven-segment programs). Lab C deliberately never states the LED pattern: the student predicts it first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .visual import CpuState, KitView


@dataclass(frozen=True)
class Check:
    text: str  # what is being checked
    ok: bool
    hint: str  # feedback shown when it is not (yet) true


@dataclass(frozen=True)
class LabSpec:
    key: str
    title: str
    objectives: tuple[str, ...]
    instructions: tuple[str, ...]
    expected: tuple[str, ...]  # shown only after the program has run (see ``reveal_expected``)
    program: str
    check: Callable[[CpuState, KitView], list[Check]]
    needs_kit: bool = False
    reveal_expected: bool = True  # Lab C keeps its answer for the student to find


def _hx(v: int) -> str:
    return f"{v:02X}h"


# ------------------------------------------------------------------- Lab A
LAB_A_PROGRAM = """\
; @title: Visual Lab A - Register transfer (MOV and MVI)
; @topic: Moving data between registers
; @validation: T
;
; MVI loads a constant, MOV copies one register into another.
START:  MVI A,3CH       ; A = 3Ch
        MVI B,00H       ; B = 00h
        MOV B,A         ; copy A into B
        MOV C,B         ; copy B into C
        MOV D,C         ; copy C into D
        HLT
"""


def _check_a(s: CpuState, _k: KitView) -> list[Check]:
    done = s.halted
    out = [Check("The program ran to HLT", done, "Press Step Into (F11) until HLT has executed, or press Run.")]
    for r in "ABCD":
        out.append(Check(f"{r} = 3Ch", s.reg(r) == 0x3C and done,
                         f"{r} is {_hx(s.reg(r))} now. MOV copies the value; keep stepping until all four registers hold 3Ch."))
    out.append(Check("A is still 3Ch (MOV never changes its source)", s.reg("A") == 0x3C and done,
                     "A should still hold 3Ch: MOV copies, it does not move the value out of the source."))
    out.append(Check("No flag changed (MOV and MVI do not touch flags)", s.flags == (0, 0, 0, 0, 0) and done,
                     "MOV and MVI never change S, Z, AC, P or CY; if a flag is set, something else ran."))
    return out


LAB_A = LabSpec(
    "A", "Lab A: Register transfer (MOV / MVI)",
    objectives=("See how MVI loads a constant into a register.",
                "See that MOV copies a register into another and leaves the source unchanged.",
                "Follow the value through A, B, C and D on the diagram."),
    instructions=("Load the lab program with the button above and assemble it (F7).",
                  "Before each Step Into (F11), say which register will receive a new value and what it will hold.",
                  "Step through MVI A, MVI B, MOV B,A, MOV C,B and MOV D,C. Watch the arrow between the registers.",
                  "After HLT press Check my result."),
    expected=("A, B, C and D all hold 3Ch.", "No flag changes at any step: MOV and MVI do not affect flags.",
              "MVI B,00h writes 00h into B first, so the first MOV visibly changes B from 00h to 3Ch."),
    program=LAB_A_PROGRAM, check=_check_a)

# ------------------------------------------------------------------- Lab B
LAB_B_PROGRAM = """\
; @title: Visual Lab B - The ALU and the flags
; @topic: ADD, SUB and the S Z AC P CY flags
; @validation: T
;
START:  MVI A,7FH       ; A = 7Fh (the largest positive 8-bit signed number)
        MVI B,01H
        ADD B           ; 7Fh + 01h: watch S, AC and P
        SUB B           ; back to 7Fh
        MVI A,0FFH
        ADD B           ; FFh + 01h wraps to 00h: watch Z, CY, AC and P
        HLT
"""


def _check_b(s: CpuState, _k: KitView) -> list[Check]:
    f = s.flag_dict()
    done = s.halted
    return [
        Check("The program ran to HLT", done, "Step Into until HLT has executed."),
        Check("A = 00h", s.reg("A") == 0 and done, f"A is {_hx(s.reg('A'))}. The last ADD B adds 01h to FFh."),
        Check("Z = 1 (the result was zero)", f["Z"] == 1 and done, "Z is set only when the result is exactly 00h."),
        Check("CY = 1 (carry out of bit 7)", f["CY"] == 1 and done,
              "FFh + 01h does not fit in 8 bits, so a carry leaves bit 7."),
        Check("AC = 1 (carry from bit 3 into bit 4)", f["AC"] == 1 and done,
              "Fh + 1h in the low nibble carries into bit 4."),
        Check("P = 1 (even parity)", f["P"] == 1 and done, "00h has zero 1-bits, which is an even count."),
        Check("S = 0 (bit 7 of the result is 0)", f["S"] == 0 and done, "S copies bit 7 of the result."),
    ]


LAB_B = LabSpec(
    "B", "Lab B: ALU and flags",
    objectives=("See operands travel from A and a register into the ALU and the result return to A.",
                "Predict which of S, Z, AC, P and CY change before each arithmetic step.",
                "Read why each flag changed in the Flags explanation."),
    instructions=("Load the lab program with the button above and assemble it (F7).",
                  "Step to the first ADD B. Predict the new A and the flags, then press Step Into.",
                  "Compare with the diagram: the flags box marks every flag that changed.",
                  "Repeat for SUB B and for the final ADD B (FFh + 01h). After HLT press Check my result."),
    expected=("First ADD B: A = 80h, S = 1, AC = 1, P = 0 (80h has one 1-bit), Z = 0, CY = 0.",
              "SUB B: A = 7Fh again.",
              "Last ADD B: A = 00h with Z = 1, CY = 1, AC = 1, P = 1, S = 0."),
    program=LAB_B_PROGRAM, check=_check_b)

# ------------------------------------------------------------------- Lab C
LAB_C_PROGRAM = """\
; @title: Visual Lab C - I/O data flow: switches, accumulator, LEDs
; @topic: IN and OUT through the accumulator (Virtual 8085 Trainer Kit)
; @validation: T
;
; Virtual hardware (Lab > Show the Virtual 8085 Trainer Kit):
;   IN  00H   8 switches      OUT 01H   8 LEDs
; These port numbers are virtual teaching assignments, not real kit addresses.
START:  IN  00H         ; switches -> A
        OUT 01H         ; A -> LEDs
        HLT
"""


def _check_c(s: CpuState, k: KitView) -> list[Check]:
    if not k.enabled:
        return [Check("The Trainer Kit is connected", False,
                      "Tick 'Kit connected' in the Virtual 8085 Trainer Kit panel, then run the lab again.")]
    done = s.halted
    return [
        Check("The program ran to HLT", done, "Step Into until HLT has executed."),
        Check("A holds the switch byte (IN copied it)", done and s.reg("A") == k.switches,
              "After IN, A must equal the switch pattern. Did you change the switches after IN ran?"),
        Check("The LEDs show the same byte (OUT copied A)", done and k.leds_written and k.leds == s.reg("A"),
              "OUT sends A to the LED latch; run the program to OUT, then HLT."),
        Check("No flag changed (IN and OUT do not touch flags)", done and s.flags == (0, 0, 0, 0, 0),
              "IN and OUT never change flags."),
    ]


LAB_C = LabSpec(
    "C", "Lab C: I/O data flow (switches, A, LEDs)",
    objectives=("Follow one byte: input port, then the accumulator A, then the output port, then the LEDs.",
                "Explain why A is the go-between for every IN and OUT.",
                "Predict the LEDs before you run, as in Experiment 1."),
    instructions=("Open the Virtual 8085 Trainer Kit and set the 8 switches to any pattern.",
                  "Write down the LED pattern you expect. (This lab does not tell you.)",
                  "Load the lab program with the button above and assemble it (F7).",
                  "Step Into once: watch the arrow input port to A. Step Into again: A to the output port and LEDs.",
                  "After HLT press Check my result, which compares your switches, A and the LEDs."),
    expected=(),
    program=LAB_C_PROGRAM, check=_check_c, needs_kit=True, reveal_expected=False)

LABS: dict[str, LabSpec] = {"A": LAB_A, "B": LAB_B, "C": LAB_C}


def feedback(lab: LabSpec, state: CpuState, kit: KitView) -> tuple[list[Check], bool]:
    """(per-check results, all passed)."""
    results = lab.check(state, kit)
    return results, all(c.ok for c in results)
