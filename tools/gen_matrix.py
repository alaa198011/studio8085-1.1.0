"""Generate docs/INSTRUCTION_MATRIX.md (one row per opcode) from the opcode table.

usage: python tools/gen_matrix.py          # rewrites the file
       python tools/gen_matrix.py --check  # exit 1 if the file is out of date (used by the test-suite)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from studio8085.core.opcodes import INFO, TABLE, format_operands  # noqa: E402

OUT = ROOT / "docs" / "INSTRUCTION_MATRIX.md"

# Mnemonics whose length/T-states were cross-checked against table S1 (see docs/ACCURACY.md)
S1 = set("""ACI ADC ADD ADI ANA ANI CALL CMA CMC CMP CPI DAA DAD DCR DCX DI EI HLT IN INR INX JMP LDA LDAX LHLD
LXI MOV MVI NOP ORA ORI OUT PCHL POP PUSH RAL RAR RLC RRC RET RIM SBB SBI SHLD SIM SPHL STA STAX STC SUB SUI
XCHG XRA XRI XTHL""".split())
CONDITIONAL = set()
for cc in ("NZ", "Z", "NC", "C", "PO", "PE", "P", "M"):
    CONDITIONAL |= {"J" + cc, "C" + cc, "R" + cc}

ALU = {"ADD", "ADC", "SUB", "SBB", "CMP", "ANA", "XRA", "ORA"}
SUBTRACT_AC = {"SUB", "SBB", "CMP", "SUI", "SBI", "CPI", "DCR"}

NOTES = {
    "DAA": "Correction as in the 8080/8085 manual; AC = carry out of bit 3 of the +06h step. Behaviour for non-BCD "
           "input follows the algorithm and is not hardware-verified. Undocumented K/V flags not modelled.",
    "HLT": "Ends the run (resumes only through an interrupt). T-states of the halt state itself are not counted.",
    "EI": "Takes effect after the NEXT instruction (modelled).",
    "DI": "Also cancels a pending EI.",
    "RIM": "Software model of SID, pending latches, masks and IE. No serial timing.",
    "SIM": "Software model of mask set (bit 3), R7.5 reset (bit 4) and SOD (bits 6-7). No serial timing.",
    "RST": "Pushes PC, jumps to 8 x n. Same path as interrupt vectors 0024h/002Ch/0034h/003Ch.",
    "POP": "POP PSW: flag bits 1, 3 and 5 are forced to their fixed values (1, 0, 0).",
    "IN": "Reads the simulated port byte (editable in the I/O panel); no device model.",
    "OUT": "Stores to the simulated port and logs the write; no device model.",
    "XTHL": "Stack addresses wrap around 0000h/FFFFh.",
    "LHLD": "Second byte address wraps (FFFFh -> 0000h).",
    "SHLD": "Second byte address wraps (FFFFh -> 0000h).",
    "ADC": "Carry-in is included in both CY and AC.",
    "SBB": "Borrow-in is included in both CY and AC.",
}


def addressing(mn: str, ops: tuple) -> str:
    if mn in ("LDA", "STA", "LHLD", "SHLD"):
        return "direct"
    if mn in ("LDAX", "STAX"):
        return "register indirect (BC/DE)"
    if mn in ("PUSH", "POP", "XTHL", "SPHL"):
        return "stack"
    if mn in ("JMP", "CALL") or (mn[0] in "JC" and len(mn) <= 3 and ops == ("#16",)):
        return "immediate address"
    if mn in ("RET", "RST") or (mn[0] == "R" and ops == () and len(mn) <= 3 and mn not in ("RAL", "RAR", "RLC", "RRC", "RIM")):
        return "stack / fixed vector"
    if mn in ("IN", "OUT"):
        return "port (direct)"
    if "M" in ops:
        return "register indirect (HL)"
    if any(o == "#8" for o in ops):
        return "immediate"
    if any(o == "#16" for o in ops):
        return "immediate (16-bit)"
    if mn in ("PCHL",):
        return "register (HL)"
    if ops:
        return "register" if len(ops) else "implied"
    return "implied"


def tests_for(mn: str, ops: tuple) -> str:
    t = ["R", "T"]
    if mn in ALU and "M" not in ops and ops == ("B",):
        t.insert(0, "E")
    elif mn in ("INR", "DCR") and "M" not in ops:
        t.insert(0, "E")
    elif mn == "DAA":
        t.insert(0, "E")
    if mn not in ("RST", "RIM", "SIM", "DAA"):
        t.append("D")
    if mn in ("EI", "DI", "RIM", "SIM", "RST", "HLT", "IN", "OUT", "XTHL", "PUSH", "POP", "CALL", "RET") or \
            (mn[0] in "JCR" and mn[1:] in ("NZ", "Z", "NC", "C", "PO", "PE", "P", "M")):
        t.append("U")
    return " ".join(t)


def reference(mn: str) -> str:
    if mn in S1:
        return "S1"
    if mn in CONDITIONAL:
        return "S2 S3 S4"
    if mn == "RST":
        return "S3 S4"
    return "-"


def build() -> str:
    rows = []
    for ins in TABLE:
        if not ins:
            continue
        ops = format_operands(ins, None).replace("00h", "dd").replace("0000h", "dddd") if ins.imm_kind else ",".join(ins.operands)
        ops = ",".join("data8" if o == "#8" else "addr16" if o == "#16" and ins.mnemonic not in ("LXI",) else
                       "data16" if o == "#16" else o for o in ins.operands)
        form = f"{ins.mnemonic} {ops}".strip()
        ts = f"{ins.tstates}/{ins.tstates + ins.taken_extra}" if ins.taken_extra else str(ins.tstates)
        flags = INFO[ins.mnemonic][2]
        note = NOTES.get(ins.mnemonic, "")
        if ins.mnemonic in SUBTRACT_AC:
            note = (note + " " if note else "") + "AC convention is selectable (hardware carry vs textbook borrow)."
        if ins.taken_extra:
            note = (note + " " if note else "") + "T-states shown as not-taken/taken."
        rows.append(f"| `{ins.opcode:02X}` | `{form}` | {ins.length} | {ts} | {flags} | {addressing(ins.mnemonic, ins.operands)} | "
                    f"{tests_for(ins.mnemonic, ins.operands)} | {reference(ins.mnemonic)} | {note.strip() or '-'} |")
    head = """# 8085 instruction matrix

Generated by `tools/gen_matrix.py` from `src/studio8085/core/opcodes.py` - do not edit by hand.
All 246 documented opcodes. The 10 undefined opcodes (`08 10 18 28 38 CB D9 DD ED FD`) stop the program with an
"illegal opcode" message; the undocumented instructions of real silicon are **not** implemented.

**Test status codes** - what covers each row (see `docs/ACCURACY.md` for details and limits):

| Code | Meaning |
|---|---|
| E | Exhaustive: every input combination checked (ALU register-B forms against a bit-level full-adder model, INR/DCR on all registers, DAA for every BCD pair) |
| D | Differential: ~400 random machine states per opcode compared with the original GNUSim8085 core (`tools/diff_vs_gnusim8085`); not run for RST, RIM, SIM, DAA |
| U | Dedicated unit tests of the behaviour (stack, wrap-around, interrupts, I/O, branches) |
| T | Length and T-states asserted by `tests/test_cpu.py` / opcode-table tests |
| R | Assemble -> disassemble -> re-assemble round trip reproduces the opcode |

**Reference codes** - where length and T-states were cross-checked (all are secondary sources, **not** a scan of the Intel
datasheet and **not** hardware measurements):
S1 = rfwireless-world.com "8085 Instruction Set" table; S2 = McGraw-Hill "Instruction Set of 8085 Microprocessor" summary (conditional
jump/call/return); S3 = uotechnology.edu.iq "CODES.pdf" timing summary; S4 = mark-ogden.uk "8085 Instruction Set.pdf" opcode map.

| Opcode | Instruction | Bytes | T-states | Flags affected | Addressing | Tests | Reference | Notes / known deviations |
|---|---|---:|---:|---|---|---|---|---|
"""
    return head + "\n".join(rows) + "\n"


if __name__ == "__main__":
    text = build()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.exists() and OUT.read_text(encoding="utf-8") == text else 1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print("wrote", OUT, f"({text.count(chr(10))} lines)")
