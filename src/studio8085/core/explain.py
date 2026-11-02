"""Plain-language explanations of instructions and flag changes.

``explain_instruction`` describes the instruction at PC in terms of the *actual*
registers and memory ("A = 3Fh and B = 01h, so A becomes 40h"), and says whether a
conditional branch will be taken. ``flag_notes`` explains why each flag changed
after an instruction ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from .opcodes import BY_MNEMONIC, INFO, TABLE, Instr, format_operands

FLAG_ORDER = ["S", "Z", "AC", "P", "CY"]
_REG_WORDS = {"A": "the accumulator A", "B": "register B", "C": "register C", "D": "register D",
              "E": "register E", "H": "register H", "L": "register L"}
_PAIR_WORDS = {"B": "the pair BC", "D": "the pair DE", "H": "the pair HL", "SP": "the stack pointer SP",
               "PSW": "the accumulator and flags (PSW)"}
_PAIR_PARTS = {"B": ("B", "C"), "D": ("D", "E"), "H": ("H", "L")}
_COND = {
    "NZ": ("Z", 0, "the last result was not zero (Z = 0)"), "Z": ("Z", 1, "the last result was zero (Z = 1)"),
    "NC": ("CY", 0, "there was no carry (CY = 0)"), "C": ("CY", 1, "there was a carry (CY = 1)"),
    "PO": ("P", 0, "the parity is odd (P = 0)"), "PE": ("P", 1, "the parity is even (P = 1)"),
    "P": ("S", 0, "the result was positive (S = 0)"), "M": ("S", 1, "the result was negative (S = 1)"),
}
PREDICT_HINT = "Result hidden (predict-first mode): work out what will happen, then step to check."
_ALU_VERB = {"ADD": "Adds", "ADC": "Adds (with carry)", "SUB": "Subtracts", "SBB": "Subtracts (with borrow)",
             "ANA": "ANDs", "XRA": "XORs", "ORA": "ORs", "CMP": "Compares"}


@dataclass
class Explanation:
    title: str  # "DCR B"
    summary: str  # one-sentence meaning
    details: list[str] = field(default_factory=list)  # live input values
    outcomes: list[str] = field(default_factory=list)  # what will result (hidden in "predict first" mode)
    flags_changed: list[str] = field(default_factory=list)
    flags_kept: list[str] = field(default_factory=list)
    flag_comment: str = ""
    code_bytes: str = ""
    tstates: str = ""
    condition: str = ""  # e.g. "Z is 0 now, so the jump WILL be taken."

    def text(self, hide_outcome: bool = False) -> str:
        lines = [self.title, self.summary, *self.details]
        if hide_outcome:
            if self.outcomes or self.condition:
                lines.append(PREDICT_HINT)
        else:
            lines.extend(self.outcomes)
            if self.condition:
                lines.append(self.condition)
        lines.append("Flags changed: " + (", ".join(self.flags_changed) or "none")
                     + ("; unchanged: " + ", ".join(self.flags_kept) if self.flags_changed else ""))
        if self.flag_comment:
            lines.append(self.flag_comment)
        lines.append(f"Code {self.code_bytes} - {self.tstates} T-states")
        return "\n".join(lines)

    def html(self, hide_outcome: bool = False) -> str:
        e = escape
        out = [f"<p style='margin:0 0 4px 0'><b style='font-size:110%'>{e(self.title)}</b></p>",
               f"<p style='margin:0 0 4px 0'>{e(self.summary)}</p>"]
        for d in self.details:
            out.append(f"<p style='margin:0 0 3px 0'>&bull; {e(d)}</p>")
        if hide_outcome:
            if self.outcomes or self.condition:
                out.append(f"<p style='margin:2px 0 4px 0'><i>{e(PREDICT_HINT)}</i></p>")
        else:
            for d in self.outcomes:
                out.append(f"<p style='margin:0 0 3px 0'>&bull; {e(d)}</p>")
            if self.condition:
                out.append(f"<p style='margin:2px 0 4px 0'><b>{e(self.condition)}</b></p>")
        if self.flags_changed:
            out.append(f"<p style='margin:2px 0'>Flags affected: <b>{e(' '.join(self.flags_changed))}</b>"
                       f" &nbsp; not affected: {e(' '.join(self.flags_kept)) or '-'}</p>")
        else:
            out.append("<p style='margin:2px 0'>No flags are affected.</p>")
        if self.flag_comment:
            out.append(f"<p style='margin:2px 0'><i>{e(self.flag_comment)}</i></p>")
        out.append(f"<p style='margin:4px 0 0 0'><span style='opacity:.75'>Machine code {e(self.code_bytes)}"
                   f" &nbsp;|&nbsp; {e(self.tstates)} T-states</span></p>")
        return "".join(out)


def _flags_for(mn: str) -> tuple[list[str], str]:
    spec = INFO[mn][2]
    comment = ""
    if mn in ("ANA", "ANI"):
        comment = "AND always clears CY and sets AC."
    elif mn in ("XRA", "XRI", "ORA", "ORI"):
        comment = "This logical instruction always clears CY and AC."
    elif mn == "POP":
        comment = "Only POP PSW changes the flags (it restores them from the stack)."
    elif mn == "INR" or mn == "DCR":
        comment = "CY is left alone, so a carry from an earlier instruction survives."
    if spec == "none":
        return [], comment
    names = [t for t in spec.replace("(POP PSW only)", "").split() if t in FLAG_ORDER]
    return names, comment


def _tstate_text(ins: Instr) -> str:
    return f"{ins.tstates}/{ins.tstates + ins.taken_extra} (not taken/taken)" if ins.taken_extra else str(ins.tstates)


class _Ctx:
    """Read-only view of CPU state with friendly accessors."""

    def __init__(self, cpu):
        self.cpu = cpu

    def reg(self, name: str) -> int:
        if name == "M":
            return self.cpu.mem.data[self.cpu.hl]
        return self.cpu.regs["BCDEHLMA".index(name)]

    def desc(self, name: str) -> str:
        if name == "M":
            hl = self.cpu.hl
            return f"the memory byte addressed by HL ({hl:04X}h, now {self.cpu.mem.data[hl]:02X}h)"
        return _REG_WORDS[name]

    def pair(self, name: str) -> int:
        return self.cpu.get_rp({"B": 0, "D": 1, "H": 2, "SP": 3}[name])

    def mem(self, addr: int) -> int:
        return self.cpu.mem.data[addr & 0xFFFF]


def explain_instruction(ins: Instr, raw: bytes, cpu=None) -> Explanation:
    """Explain ``ins`` (with its immediate bytes in ``raw``) against the state in ``cpu``."""
    imm = None
    if ins.length == 2:
        imm = raw[1]
    elif ins.length == 3:
        imm = raw[1] | raw[2] << 8
    ops = format_operands(ins, imm)
    title = f"{ins.mnemonic} {ops}".strip()
    mn, o = ins.mnemonic, ins.operands
    ctx = _Ctx(cpu) if cpu is not None else None
    details: list[str] = []
    outcomes: list[str] = []
    condition = ""
    summary = INFO[mn][1]

    def hx(v, w=2):
        return f"{v & ((1 << 4 * w) - 1):0{w}X}h"

    if mn == "MOV":
        d, s = o
        summary = f"Copies {ctx.desc(s) if ctx else s} into {_REG_WORDS.get(d, 'memory at HL')}; the source is unchanged."
        if ctx:
            details.append(f"{s} holds {hx(ctx.reg(s))}.")
            outcomes.append(f"So {d} becomes {hx(ctx.reg(s))}.")
    elif mn == "MVI":
        summary = f"Loads the constant {hx(imm)} into {_REG_WORDS.get(o[0], 'the memory byte addressed by HL')}."
    elif mn == "LXI":
        r = o[0]
        if r == "SP":
            summary = f"Loads the 16-bit constant {hx(imm, 4)} into the stack pointer SP."
        else:
            hi, lo = _PAIR_PARTS[r]
            summary = f"Loads the 16-bit constant {hx(imm, 4)} into {_PAIR_WORDS[r]} ({hi} = {hx(imm >> 8)}, {lo} = {hx(imm)})."
    elif mn in ("LDA", "STA"):
        verb = "Loads A from" if mn == "LDA" else "Stores A at"
        summary = f"{verb} memory address {hx(imm, 4)}."
        if ctx:
            details.append(f"Address {hx(imm, 4)} holds {hx(ctx.mem(imm))}; A = {hx(ctx.reg('A'))}.")
    elif mn in ("LHLD", "SHLD"):
        summary = (f"Loads L from {hx(imm, 4)} and H from {hx(imm + 1, 4)}." if mn == "LHLD"
                   else f"Stores L at {hx(imm, 4)} and H at {hx(imm + 1, 4)}.")
    elif mn in ("LDAX", "STAX"):
        a = ctx.pair(o[0]) if ctx else None
        summary = (f"Loads A from the address held in {_PAIR_WORDS[o[0]]}." if mn == "LDAX"
                   else f"Stores A at the address held in {_PAIR_WORDS[o[0]]}.")
        if ctx:
            details.append(f"That address is {hx(a, 4)} (holds {hx(ctx.mem(a))}).")
    elif mn == "PUSH":
        summary = (f"Pushes {_PAIR_WORDS[o[0]]} onto the stack: SP decreases by 2 and the 16-bit value is stored "
                   "at the new SP (high byte at SP+1, low byte at SP).")
        if ctx:
            v = (ctx.reg("A") << 8) | cpu.f if o[0] == "PSW" else ctx.pair(o[0])
            details.append(f"Pushes {hx(v, 4)}; SP is {hx(cpu.sp, 4)} now.")
            outcomes.append(f"SP becomes {hx(cpu.sp - 2, 4)}.")
    elif mn == "POP":
        summary = (f"Pops the top two stack bytes into {_PAIR_WORDS[o[0]]} and increases SP by 2.")
        if ctx:
            sp = cpu.sp
            v = ctx.mem(sp) | ctx.mem(sp + 1) << 8
            details.append(f"The word at SP ({hx(sp, 4)}) is {hx(v, 4)}.")
            outcomes.append(f"SP becomes {hx(sp + 2, 4)}.")
    elif mn in _ALU_VERB or mn in ("ADI", "ACI", "SUI", "SBI", "ANI", "XRI", "ORI", "CPI"):
        base = {"ADI": "ADD", "ACI": "ADC", "SUI": "SUB", "SBI": "SBB", "ANI": "ANA", "XRI": "XRA",
                "ORI": "ORA", "CPI": "CMP"}.get(mn, mn)
        src = hx(imm) if ins.length == 2 else (ctx.desc(o[0]) if ctx else o[0])
        sym = {"ADD": "A + x", "ADC": "A + x + CY", "SUB": "A - x", "SBB": "A - x - CY", "ANA": "A AND x",
               "XRA": "A XOR x", "ORA": "A OR x", "CMP": "A - x (result discarded)"}[base]
        what = hx(imm) if ins.length == 2 else o[0]
        label = "the constant" if ins.length == 2 else o[0]
        summary = f"{_ALU_VERB[base]} {what} {'to' if base in ('ADD', 'ADC') else 'with' if base in ('ANA', 'XRA', 'ORA', 'CMP') else 'from'} the accumulator: A = {sym.replace('x', what)}."
        if base == "CMP":
            summary = f"Compares A with {what} by subtracting; only the flags change, A stays as it is."
        if ctx:
            a = ctx.reg("A")
            x = imm if ins.length == 2 else ctx.reg(o[0])
            cy = cpu.cy
            res = {"ADD": a + x, "ADC": a + x + cy, "SUB": a - x, "SBB": a - x - cy, "CMP": a - x,
                   "ANA": a & x, "XRA": a ^ x, "ORA": a | x}[base] & 0xFF
            if base == "CMP":
                details.append(f"A = {hx(a)}, {label} = {hx(x)}.")
                outcomes.append(f"A is {'equal to' if a == x else 'less than' if a < x else 'greater than'}"
                                f" the operand, so Z = {1 if a == x else 0} and CY = {1 if a < x else 0}.")
            else:
                details.append(f"A = {hx(a)}, {label} = {hx(x)}" + (f", CY = {cy}" if base in ("ADC", "SBB") else "") + ".")
                outcomes.append(f"A becomes {hx(res)}.")
    elif mn in ("INR", "DCR"):
        r = o[0]
        up = mn == "INR"
        summary = f"{'Increases' if up else 'Decreases'} {_REG_WORDS.get(r, 'the memory byte addressed by HL')} by one. CY is not affected."
        if ctx:
            v = ctx.reg(r)
            details.append(f"{r} = {hx(v)}.")
            outcomes.append(f"{r} becomes {hx(v + (1 if up else -1))}.")
    elif mn in ("INX", "DCX"):
        up = mn == "INX"
        summary = f"{'Increases' if up else 'Decreases'} {_PAIR_WORDS[o[0]]} by one (16-bit, wraps around). No flags change."
        if ctx:
            v = ctx.pair(o[0])
            details.append(f"The pair holds {hx(v, 4)}.")
            outcomes.append(f"It becomes {hx(v + (1 if up else -1), 4)}.")
    elif mn == "DAD":
        summary = f"Adds {_PAIR_WORDS[o[0]]} to HL (16-bit). Only CY changes: it is set if the sum passes FFFFh."
        if ctx:
            a, b = cpu.hl, ctx.pair(o[0])
            details.append(f"HL = {hx(a, 4)}, {o[0]} = {hx(b, 4)}.")
            outcomes.append(f"HL becomes {hx(a + b, 4)}, CY = {1 if a + b > 0xFFFF else 0}.")
    elif mn in ("RLC", "RRC", "RAL", "RAR"):
        details_map = {"RLC": "Rotates A left one bit; bit 7 goes into CY and also into bit 0.",
                       "RRC": "Rotates A right one bit; bit 0 goes into CY and also into bit 7.",
                       "RAL": "Rotates A left one bit through the carry: CY enters bit 0 and bit 7 enters CY.",
                       "RAR": "Rotates A right one bit through the carry: CY enters bit 7 and bit 0 enters CY."}
        summary = details_map[mn]
        if ctx:
            a, c = ctx.reg("A"), cpu.cy
            res = {"RLC": ((a << 1) | (a >> 7)) & 255, "RRC": (a >> 1) | ((a & 1) << 7),
                   "RAL": ((a << 1) | c) & 255, "RAR": (a >> 1) | (c << 7)}[mn]
            cy = a >> 7 if mn in ("RLC", "RAL") else a & 1
            details.append(f"A = {a:08b}b, CY = {c}.")
            outcomes.append(f"A becomes {res:08b}b, CY becomes {cy}.")
    elif mn == "DAA":
        if ctx:
            details.append(f"A = {hx(ctx.reg('A'))}, AC = {cpu.ac}, CY = {cpu.cy}: DAA adds 06h if the low digit is above 9 or AC is set, "
                           "and 60h if the high digit is above 9 or CY is set.")
    elif mn == "CMA":
        if ctx:
            details.append(f"A = {hx(ctx.reg('A'))}.")
            outcomes.append(f"A becomes {hx(~ctx.reg('A') & 255)}.")
    elif mn in ("STC", "CMC"):
        summary = "Sets the carry flag to 1." if mn == "STC" else "Flips the carry flag (0 becomes 1, 1 becomes 0)."
    elif mn == "XCHG":
        if ctx:
            details.append(f"HL = {hx(cpu.hl, 4)} and DE = {hx(ctx.pair('D'), 4)}.")
            outcomes.append("They swap places.")
    elif mn == "XTHL":
        if ctx:
            sp = cpu.sp
            details.append(f"HL = {hx(cpu.hl, 4)}; the word at SP ({hx(sp, 4)}) is {hx(ctx.mem(sp) | ctx.mem(sp + 1) << 8, 4)}.")
            outcomes.append("HL and that stack word trade places.")
    elif mn in ("SPHL", "PCHL"):
        if ctx:
            details.append(f"HL = {hx(cpu.hl, 4)}.")
    elif mn == "JMP":
        summary = f"Jumps to {hx(imm, 4)}: the next instruction executed is the one there."
    elif mn == "CALL":
        summary = (f"Calls the subroutine at {hx(imm, 4)}: pushes the return address ({hx(cpu.pc + 2 if cpu else 0, 4)}) "
                   "onto the stack, then jumps.") if cpu else f"Calls the subroutine at {hx(imm, 4)}."
    elif mn == "RET":
        summary = "Returns from a subroutine: pops the return address from the stack into PC."
        if ctx:
            sp = cpu.sp
            details.append(f"The word at SP ({hx(sp, 4)}) is {hx(ctx.mem(sp) | ctx.mem(sp + 1) << 8, 4)}; execution continues there.")
    elif mn == "RST":
        n = int(o[0])
        summary = f"Restart {n}: pushes the return address and jumps to {hx(8 * n, 4)} (a one-byte CALL to a fixed address)."
    elif mn[0] in "JCR" and mn[1:] in _COND:
        flag, want, why = _COND[mn[1:]]
        kind = {"J": "Jumps to", "C": "Calls", "R": "Returns"}[mn[0]]
        target = f" {hx(imm, 4)}" if imm is not None else ""
        summary = f"{kind}{target} only if {why}; otherwise execution simply continues with the next instruction."
        if ctx:
            have = getattr(cpu, flag.lower())
            taken = have == want
            condition = (f"{flag} is {have} right now, so this {'WILL' if taken else 'will NOT'} be "
                         f"{'taken' if mn[0] == 'J' else 'executed' if mn[0] == 'C' else 'done'}"
                         f" ({ins.tstates + (ins.taken_extra if taken else 0)} T-states).")
    elif mn == "IN":
        summary = f"Reads I/O port {hx(imm)} into A."
        if ctx:
            details.append(f"Port {hx(imm)} currently holds {hx(cpu.io[imm])}.")
    elif mn == "OUT":
        summary = f"Writes A to I/O port {hx(imm)}."
        if ctx:
            details.append(f"A = {hx(ctx.reg('A'))} will appear on port {hx(imm)}.")
    elif mn == "HLT":
        summary = "Halts the processor. Only an interrupt can wake it; this simulator stops the run here."
    elif mn == "EI":
        summary = "Enables interrupts - but only after the NEXT instruction has finished."
    elif mn == "SIM":
        if ctx:
            a = ctx.reg("A")
            details.append(f"A = {a:08b}b: bit 3 (mask-set enable) is {(a >> 3) & 1}; masks M7.5/M6.5/M5.5 = "
                           f"{(a >> 2) & 1}/{(a >> 1) & 1}/{a & 1} (applied only if bit 3 is 1).")
    elif mn == "RIM":
        pass

    changed, comment = _flags_for(mn)
    kept = [f for f in FLAG_ORDER if f not in changed]
    return Explanation(title, summary, details, outcomes, changed, kept, comment,
                       " ".join(f"{b:02X}" for b in raw[:ins.length]), _tstate_text(ins), condition)


def explain_next(cpu) -> Explanation:
    """Explain the instruction that will execute next (at PC)."""
    pc = cpu.pc
    op = cpu.mem.data[pc]
    ins = TABLE[op]
    if ins is None:
        return Explanation(f"DB {op:02X}h", "This byte is not a documented 8085 instruction; the simulator will stop "
                           "with an 'illegal opcode' message if it is executed.", code_bytes=f"{op:02X}", tstates="-")
    raw = bytes(cpu.mem.data[(pc + i) & 0xFFFF] for i in range(ins.length))
    return explain_instruction(ins, raw, cpu)


# ------------------------------------------------------------ flag changes
_ADD = {"ADD", "ADC", "ADI", "ACI", "INR"}
_SUB = {"SUB", "SBB", "SUI", "SBI", "CMP", "CPI", "DCR"}
_LOGIC = {"ANA", "ANI", "XRA", "XRI", "ORA", "ORI"}


def _kind(mn: str) -> str:
    if mn in _ADD:
        return "add"
    if mn in _SUB:
        return "sub"
    if mn in _LOGIC:
        return "logic"
    return mn


def flag_notes(mnemonic: str, before: dict[str, int], after: dict[str, int], result: int | None = None,
               ac_borrow_style: bool = False) -> list[str]:
    """One sentence per flag that changed, explaining why."""
    kind = _kind(mnemonic)
    notes: list[str] = []
    for f in FLAG_ORDER:
        old, new = before.get(f), after.get(f)
        if old is None or new is None or old == new:
            continue
        head = f"{f} changed from {old} to {new}: "
        if f == "CY":
            if kind == "add":
                why = ("the addition produced a carry out of bit 7 (the 8-bit sum passed FFh)." if new
                       else "there was no carry out of bit 7.")
            elif kind == "sub":
                cmp_ = mnemonic in ("CMP", "CPI")
                why = (("A is smaller than the operand (unsigned), which counts as a borrow." if cmp_
                        else "the value taken away was larger than A (unsigned): a borrow occurred.")
                       if new else "no borrow was needed (A was at least as large).")
            elif kind == "logic":
                why = "logical instructions always clear CY."
            elif kind in ("RLC", "RAL"):
                why = f"bit 7 of A was rotated out into CY ({new})."
            elif kind in ("RRC", "RAR"):
                why = f"bit 0 of A was rotated out into CY ({new})."
            elif kind == "DAD":
                why = "the 16-bit sum passed FFFFh." if new else "the 16-bit sum fit in 16 bits."
            elif kind == "STC":
                why = "STC sets the carry flag."
            elif kind == "CMC":
                why = "CMC flips the carry flag."
            elif kind == "DAA":
                why = "decimal adjustment produced a decimal carry (the value passed 99)." if new else "no decimal carry."
            else:
                why = "restored from the stack." if kind == "POP" else "set by this instruction."
        elif f == "Z":
            why = "the result is 00h." if new else "the result is not zero."
        elif f == "S":
            why = ("bit 7 of the result is 1 (negative when read as a signed number)." if new
                   else "bit 7 of the result is 0.")
        elif f == "P":
            why = ("the result has an even number of 1 bits." if new else "the result has an odd number of 1 bits.")
        else:  # AC
            if kind == "add":
                why = "a carry went from bit 3 into bit 4." if new else "no carry went from bit 3 into bit 4."
            elif kind == "sub":
                if ac_borrow_style:
                    why = ("bit 4 had to borrow from bit 3 (textbook convention)." if new
                           else "no borrow between the low and high nibble (textbook convention).")
                else:
                    why = ("the low nibble subtraction needed no borrow (8085 hardware: carry out of bit 3 of "
                           "A + complement + 1)." if new else
                           "the low nibble subtraction borrowed from bit 4 (8085 hardware convention).")
            elif kind == "logic":
                why = "ANA always sets AC." if new else "this logical instruction clears AC."
            elif kind == "DAA":
                why = ("the +06h decimal correction carried out of bit 3." if new
                       else "the decimal correction did not carry out of bit 3 (AC is recomputed by DAA itself).")
            else:
                why = "set by this instruction." if new else "cleared by this instruction."
        notes.append(head + why)
    return notes
