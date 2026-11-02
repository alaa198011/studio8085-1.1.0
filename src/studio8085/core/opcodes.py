"""The Intel 8085 instruction set: opcode table, T-states and reference text.

Everything here is data. The assembler, disassembler, CPU and the in-app
instruction reference are all driven from the one table built below, so they
cannot disagree with each other.
"""

from __future__ import annotations

from dataclasses import dataclass

REG = ["B", "C", "D", "E", "H", "L", "M", "A"]  # 3-bit register field
RP = ["B", "D", "H", "SP"]  # LXI / INX / DCX / DAD
RPP = ["B", "D", "H", "PSW"]  # PUSH / POP
CC = ["NZ", "Z", "NC", "C", "PO", "PE", "P", "M"]  # condition field

RESERVED_REGISTERS = frozenset(REG) | {"SP", "PSW"}


@dataclass(frozen=True)
class Instr:
    """One opcode.

    ``operands`` is a pattern: register names are literal, ``#8`` and ``#16``
    stand for an 8-bit / 16-bit expression. ``tstates`` is the base cost;
    ``taken_extra`` is added when a conditional jump/call/return is taken.
    """

    opcode: int
    mnemonic: str
    operands: tuple[str, ...]
    length: int
    tstates: int
    taken_extra: int = 0

    @property
    def imm_kind(self) -> str | None:
        for tok in self.operands:
            if tok.startswith("#"):
                return tok
        return None


def _build() -> list[Instr | None]:
    t: list[Instr | None] = [None] * 256

    def add(op, mn, ops=(), length=1, ts=4, extra=0):
        assert t[op] is None, f"duplicate opcode {op:02X}"
        t[op] = Instr(op, mn, tuple(ops), length, ts, extra)

    for d in range(8):
        for s in range(8):
            op = 0x40 | d << 3 | s
            if op == 0x76:
                add(op, "HLT", (), 1, 5)
            else:
                add(op, "MOV", (REG[d], REG[s]), 1, 7 if 6 in (d, s) else 4)
    for d in range(8):
        add(0x06 | d << 3, "MVI", (REG[d], "#8"), 2, 10 if d == 6 else 7)
    for i in range(4):
        add(0x01 | i << 4, "LXI", (RP[i], "#16"), 3, 10)
    add(0x0A, "LDAX", ("B",), 1, 7)
    add(0x1A, "LDAX", ("D",), 1, 7)
    add(0x02, "STAX", ("B",), 1, 7)
    add(0x12, "STAX", ("D",), 1, 7)
    add(0x3A, "LDA", ("#16",), 3, 13)
    add(0x32, "STA", ("#16",), 3, 13)
    add(0x2A, "LHLD", ("#16",), 3, 16)
    add(0x22, "SHLD", ("#16",), 3, 16)
    add(0xEB, "XCHG", (), 1, 4)
    add(0xE3, "XTHL", (), 1, 16)
    add(0xF9, "SPHL", (), 1, 6)
    add(0xE9, "PCHL", (), 1, 6)
    for i in range(4):
        add(0xC5 | i << 4, "PUSH", (RPP[i],), 1, 12)
        add(0xC1 | i << 4, "POP", (RPP[i],), 1, 10)

    alu = ["ADD", "ADC", "SUB", "SBB", "ANA", "XRA", "ORA", "CMP"]
    alu_imm = ["ADI", "ACI", "SUI", "SBI", "ANI", "XRI", "ORI", "CPI"]
    for k, mn in enumerate(alu):
        for s in range(8):
            add(0x80 | k << 3 | s, mn, (REG[s],), 1, 7 if s == 6 else 4)
        add(0xC6 | k << 3, alu_imm[k], ("#8",), 2, 7)
    for d in range(8):
        add(0x04 | d << 3, "INR", (REG[d],), 1, 10 if d == 6 else 4)
        add(0x05 | d << 3, "DCR", (REG[d],), 1, 10 if d == 6 else 4)
    for i in range(4):
        add(0x03 | i << 4, "INX", (RP[i],), 1, 6)
        add(0x0B | i << 4, "DCX", (RP[i],), 1, 6)
        add(0x09 | i << 4, "DAD", (RP[i],), 1, 10)
    for op, mn in [(0x07, "RLC"), (0x0F, "RRC"), (0x17, "RAL"), (0x1F, "RAR"),
                   (0x27, "DAA"), (0x2F, "CMA"), (0x37, "STC"), (0x3F, "CMC"),
                   (0x00, "NOP"), (0xF3, "DI"), (0xFB, "EI"),
                   (0x20, "RIM"), (0x30, "SIM")]:
        add(op, mn)

    add(0xC3, "JMP", ("#16",), 3, 10)
    add(0xCD, "CALL", ("#16",), 3, 18)
    add(0xC9, "RET", (), 1, 10)
    for i, cc in enumerate(CC):
        add(0xC2 | i << 3, "J" + cc, ("#16",), 3, 7, 3)
        add(0xC4 | i << 3, "C" + cc, ("#16",), 3, 9, 9)
        add(0xC0 | i << 3, "R" + cc, (), 1, 6, 6)
    for n in range(8):
        add(0xC7 | n << 3, "RST", (str(n),), 1, 12)
    add(0xDB, "IN", ("#8",), 2, 10)
    add(0xD3, "OUT", ("#8",), 2, 10)
    return t


TABLE: list[Instr | None] = _build()
assert sum(1 for i in TABLE if i) == 246  # the documented 8085 opcode count

# mnemonic -> every encoding of it
BY_MNEMONIC: dict[str, list[Instr]] = {}
for _i in TABLE:
    if _i:
        BY_MNEMONIC.setdefault(_i.mnemonic, []).append(_i)
MNEMONICS = frozenset(BY_MNEMONIC)

DIRECTIVES = frozenset({"ORG", "DB", "DW", "DS", "EQU", "END"})

CALL_OPCODES = frozenset(i.opcode for i in TABLE if i and (i.mnemonic == "CALL"
                         or (i.mnemonic[0] == "C" and i.mnemonic[1:] in CC)
                         or i.mnemonic == "RST"))
RET_OPCODES = frozenset(i.opcode for i in TABLE if i and (i.mnemonic == "RET"
                        or (i.mnemonic[0] == "R" and i.mnemonic[1:] in CC)))

# ---------------------------------------------------------------- reference
_ALL = "S Z AC P CY"
_COND = {
    "NZ": "Z = 0 (result not zero)", "Z": "Z = 1 (result zero)",
    "NC": "CY = 0 (no carry)", "C": "CY = 1 (carry)",
    "PO": "P = 0 (parity odd)", "PE": "P = 1 (parity even)",
    "P": "S = 0 (positive)", "M": "S = 1 (minus)",
}

# mnemonic -> (syntax, description, flags affected)
INFO: dict[str, tuple[str, str, str]] = {
    "MOV": ("MOV r1,r2", "Copy r2 into r1. Either may be M (the byte at address HL), but not both.", "none"),
    "MVI": ("MVI r,data8", "Load an 8-bit constant into r (or into M).", "none"),
    "LXI": ("LXI rp,data16", "Load a 16-bit constant into register pair rp (B, D, H or SP).", "none"),
    "LDA": ("LDA addr", "Load A from the memory address.", "none"),
    "STA": ("STA addr", "Store A at the memory address.", "none"),
    "LHLD": ("LHLD addr", "Load L from addr and H from addr+1.", "none"),
    "SHLD": ("SHLD addr", "Store L at addr and H at addr+1.", "none"),
    "LDAX": ("LDAX B|D", "Load A from the address held in BC or DE.", "none"),
    "STAX": ("STAX B|D", "Store A at the address held in BC or DE.", "none"),
    "XCHG": ("XCHG", "Exchange HL with DE.", "none"),
    "XTHL": ("XTHL", "Exchange HL with the 16-bit value on top of the stack.", "none"),
    "SPHL": ("SPHL", "Copy HL into the stack pointer.", "none"),
    "PCHL": ("PCHL", "Copy HL into the program counter (jump to HL).", "none"),
    "PUSH": ("PUSH rp", "Push register pair rp (B, D, H or PSW) onto the stack.", "none"),
    "POP": ("POP rp", "Pop the top of the stack into register pair rp (B, D, H or PSW). POP PSW restores the flags.", "S Z AC P CY (POP PSW only)"),
    "ADD": ("ADD r", "A = A + r.", _ALL),
    "ADC": ("ADC r", "A = A + r + CY.", _ALL),
    "SUB": ("SUB r", "A = A - r.", _ALL),
    "SBB": ("SBB r", "A = A - r - CY.", _ALL),
    "ANA": ("ANA r", "A = A AND r. CY is cleared and AC is set.", _ALL),
    "XRA": ("XRA r", "A = A XOR r. CY and AC are cleared.", _ALL),
    "ORA": ("ORA r", "A = A OR r. CY and AC are cleared.", _ALL),
    "CMP": ("CMP r", "Compare A with r (A is unchanged). Z=1 if equal, CY=1 if A < r.", _ALL),
    "ADI": ("ADI data8", "A = A + data8.", _ALL),
    "ACI": ("ACI data8", "A = A + data8 + CY.", _ALL),
    "SUI": ("SUI data8", "A = A - data8.", _ALL),
    "SBI": ("SBI data8", "A = A - data8 - CY.", _ALL),
    "ANI": ("ANI data8", "A = A AND data8. CY is cleared and AC is set.", _ALL),
    "XRI": ("XRI data8", "A = A XOR data8. CY and AC are cleared.", _ALL),
    "ORI": ("ORI data8", "A = A OR data8. CY and AC are cleared.", _ALL),
    "CPI": ("CPI data8", "Compare A with data8 (A is unchanged). Z=1 if equal, CY=1 if A < data8.", _ALL),
    "INR": ("INR r", "r = r + 1. CY is not affected.", "S Z AC P"),
    "DCR": ("DCR r", "r = r - 1. CY is not affected.", "S Z AC P"),
    "INX": ("INX rp", "rp = rp + 1 (16-bit, wraps).", "none"),
    "DCX": ("DCX rp", "rp = rp - 1 (16-bit, wraps).", "none"),
    "DAD": ("DAD rp", "HL = HL + rp (16-bit).", "CY"),
    "RLC": ("RLC", "Rotate A left. Bit 7 goes to CY and to bit 0.", "CY"),
    "RRC": ("RRC", "Rotate A right. Bit 0 goes to CY and to bit 7.", "CY"),
    "RAL": ("RAL", "Rotate A left through carry (9-bit rotate with CY).", "CY"),
    "RAR": ("RAR", "Rotate A right through carry (9-bit rotate with CY).", "CY"),
    "DAA": ("DAA", "Decimal-adjust A after adding two BCD numbers.", _ALL),
    "CMA": ("CMA", "Complement A (A = NOT A).", "none"),
    "STC": ("STC", "Set the carry flag.", "CY"),
    "CMC": ("CMC", "Complement the carry flag.", "CY"),
    "JMP": ("JMP addr", "Jump to addr.", "none"),
    "CALL": ("CALL addr", "Push the return address and jump to addr.", "none"),
    "RET": ("RET", "Pop the return address into PC.", "none"),
    "RST": ("RST n", "Call the routine at address 8 x n (n = 0 to 7).", "none"),
    "IN": ("IN port", "Read the I/O port into A.", "none"),
    "OUT": ("OUT port", "Write A to the I/O port.", "none"),
    "EI": ("EI", "Enable interrupts (effective after the next instruction).", "none"),
    "DI": ("DI", "Disable interrupts.", "none"),
    "NOP": ("NOP", "Do nothing.", "none"),
    "HLT": ("HLT", "Halt the processor. Only an interrupt resumes it.", "none"),
    "RIM": ("RIM", "Read interrupt masks, pending interrupts and serial input into A.", "none"),
    "SIM": ("SIM", "Set interrupt masks and serial output from A.", "none"),
}
for _cc in CC:
    INFO["J" + _cc] = (f"J{_cc} addr", f"Jump to addr if {_COND[_cc]}.", "none")
    INFO["C" + _cc] = (f"C{_cc} addr", f"Call addr if {_COND[_cc]}.", "none")
    INFO["R" + _cc] = (f"R{_cc}", f"Return if {_COND[_cc]}.", "none")

DIRECTIVE_INFO = {
    "ORG": ("ORG addr", "Set the address where the following code or data is placed."),
    "DB": ("DB v1[,v2...]", "Define bytes. Values may be expressions or \"strings\"."),
    "DW": ("DW v1[,v2...]", "Define 16-bit words (stored low byte first)."),
    "DS": ("DS n[,fill]", "Reserve n bytes (filled with 0 or the fill value)."),
    "EQU": ("name: EQU value", "Give a name to a constant."),
    "END": ("END [entry]", "Stop assembling. An optional entry label sets the start address."),
}

# Names a user could mistake for instructions, used for "did you mean" hints
ALL_WORDS = sorted(MNEMONICS | DIRECTIVES)


def hex_literal(value: int, width: int) -> str:
    """``0Ah``-style literal (a leading 0 keeps it from looking like a name)."""
    digits = f"{value & ((1 << (4 * width)) - 1):0{width}X}"
    return ("0" if digits[0] in "ABCDEF" else "") + digits + "h"


def format_operands(instr: Instr, imm: int | None = None) -> str:
    """Render the operand part of an instruction, e.g. ``A,05h``."""
    out = []
    for tok in instr.operands:
        if tok == "#8":
            out.append(hex_literal(imm or 0, 2))
        elif tok == "#16":
            out.append(hex_literal(imm or 0, 4))
        else:
            out.append(tok)
    return ",".join(out)
