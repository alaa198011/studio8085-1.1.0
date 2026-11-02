"""Opcode lengths and T-states checked against published tables (not against this project's own data).

Rows below are transcribed from:
  S1  rfwireless-world.com "8085 Instruction Set" (mnemonic, bytes, T-states)
  S2  McGraw-Hill "Instruction Set of 8085 Microprocessor" summary: JCC 7/10, CCC 9/18, RCC 6/12, CALL 18, RET 10
  S3  uotechnology.edu.iq CODES.pdf: PUSH, RST 12; conditional forms as above
Format: MNEMONIC|[operand kind]|bytes|T-states   (operand kind: Reg = not M, Mem = M; RR/MR/RM for MOV)
"""
import pytest

from studio8085.core.opcodes import BY_MNEMONIC, CC, TABLE

S1_ROWS = """ACI|2|7
ADC|Reg|1|4
ADC|Mem|1|7
ADD|Reg|1|4
ADD|Mem|1|7
ADI|2|7
ANA|Reg|1|4
ANA|Mem|1|7
ANI|2|7
CALL|3|18
CMA|1|4
CMC|1|4
CMP|Reg|1|4
CMP|Mem|1|7
CPI|2|7
DAA|1|4
DAD|1|10
DCR|Reg|1|4
DCR|Mem|1|10
DCX|1|6
DI|1|4
EI|1|4
HLT|1|5
IN|2|10
INR|Reg|1|4
INR|Mem|1|10
INX|1|6
JMP|3|10
LDA|3|13
LDAX|1|7
LHLD|3|16
LXI|3|10
MOV|RR|1|4
MOV|MR|1|7
MOV|RM|1|7
MVI|Reg|2|7
MVI|Mem|2|10
NOP|1|4
ORA|Reg|1|4
ORA|Mem|1|7
ORI|2|7
OUT|2|10
PCHL|1|6
POP|1|10
PUSH|1|12
RAL|1|4
RAR|1|4
RLC|1|4
RRC|1|4
RET|1|10
RIM|1|4
SBB|Reg|1|4
SBB|Mem|1|7
SBI|2|7
SHLD|3|16
SIM|1|4
SPHL|1|6
STA|3|13
STAX|1|7
STC|1|4
SUB|Reg|1|4
SUB|Mem|1|7
SUI|2|7
XCHG|1|4
XRA|Reg|1|4
XRA|Mem|1|7
XRI|2|7
XTHL|1|16"""


def _select(mnemonic, kind):
    out = []
    for ins in BY_MNEMONIC[mnemonic]:
        ops = ins.operands
        has_m = "M" in ops
        if kind == "Reg" and has_m or kind == "Mem" and not has_m:
            continue
        if kind == "RR" and "M" in ops or kind == "MR" and ops[0] != "M" or kind == "RM" and ops[1] != "M":
            continue
        out.append(ins)
    return out


def test_every_s1_row_matches_the_opcode_table():
    checked = 0
    for line in S1_ROWS.splitlines():
        p = line.split("|")
        m = p[0]
        if p[1] in ("Reg", "Mem", "RR", "MR", "RM"):
            kind, length, ts = p[1], int(p[2]), int(p[3])
        else:
            kind, length, ts = None, int(p[1]), int(p[2])
        forms = _select(m, kind) if kind else BY_MNEMONIC[m]
        assert forms, (m, kind)
        for ins in forms:
            assert (ins.length, ins.tstates, ins.taken_extra) == (length, ts, 0), (m, ins.operands)
            checked += 1
    assert checked == 214


@pytest.mark.parametrize("prefix,length,not_taken,taken", [("J", 3, 7, 10), ("C", 3, 9, 18), ("R", 1, 6, 12)])
def test_conditional_branch_timings_match_s2_s3(prefix, length, not_taken, taken):
    for cc in CC:
        (ins,) = BY_MNEMONIC[prefix + cc]
        assert (ins.length, ins.tstates, ins.tstates + ins.taken_extra) == (length, not_taken, taken), ins.mnemonic


def test_rst_is_one_byte_twelve_states_and_the_table_has_exactly_246_opcodes():
    assert [(i.length, i.tstates) for i in BY_MNEMONIC["RST"]] == [(1, 12)] * 8
    assert sum(1 for i in TABLE if i) == 246
