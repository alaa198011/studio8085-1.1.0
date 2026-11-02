import random
import string

import pytest

from studio8085.core.assembler import assemble
from studio8085.core.disasm import disassemble
from studio8085.core.opcodes import TABLE


def code(src, origin=0):
    r = assemble(src, origin)
    assert r.ok, [(d.line, d.message) for d in r.diagnostics]
    return r


def bytes_of(src, origin=0):
    r = code(src, origin)
    return bytes(r.image[a] for a in sorted(r.image))


@pytest.mark.parametrize("line,expected", [
    ("MOV A,B", "78"), ("MOV M,A", "77"), ("mvi m,10h", "3610"), ("LXI SP,1234h", "313412"),
    ("PUSH PSW", "F5"), ("POP H", "E1"), ("RST 7", "FF"), ("CALL 1234h", "CD3412"),
    ("JPE 5", "EA0500"), ("IN 0F0h", "DBF0"), ("XTHL", "E3"), ("SIM", "30"), ("RIM", "20"),
    ("ADI 0FFh", "C6FF"), ("CPI 'A'", "FE41"), ("LDAX D", "1A"), ("DAD SP", "39"),
    ("HLT", "76"), ("RNZ", "C0"), ("CM 0", "FC0000"), ("INR M", "34"), ("ORA C", "B1"),
])
def test_encoding(line, expected):
    assert bytes_of(line + "\nhlt" if line != "HLT" else line).hex().upper().startswith(expected)


def test_every_opcode_round_trips_through_disassembler():
    """assemble(disassemble(op)) == op for all 246 opcodes, with awkward operands."""
    for imm in (0x34, 0xF0, 0xABCD):
        for ins in TABLE:
            if not ins:
                continue
            raw = [ins.opcode, imm & 0xFF, (imm >> 8) & 0xFF][:ins.length]
            mem = bytearray(raw + [0] * 3)
            text, length, _ = disassemble(mem, 0)
            assert length == ins.length
            out = assemble(text + "\nhlt")
            assert out.ok, (text, out.diagnostics)
            got = [out.image[i] for i in range(length)]
            assert got == raw, (text, got, raw)


def test_data_directives_and_little_endian_words():
    b = bytes_of('db 1,2Ah,"Hi",\'!\',-1\ndw 1234h,5\nds 2,0AAh\nhlt')
    assert b == bytes([1, 0x2A, 0x48, 0x69, 0x21, 0xFF, 0x34, 0x12, 5, 0, 0xAA, 0xAA, 0x76])


def test_org_and_entry_and_end():
    r = code("org 4200h\nstart: nop\nhlt\norg 5000h\nx: db 1\nend start")
    assert r.entry == 0x4200 and r.symbols["X"].value == 0x5000
    assert r.segments() == [(0x4200, bytes([0, 0x76])), (0x5000, bytes([1]))]
    r = code("jmp go\ndata: db 1\ngo: hlt\nend go")
    assert r.entry == r.symbols["GO"].value


def test_labels_forward_refs_and_equ():
    r = code("""
        lxi h,table+1
        mvi a,count*2
        jmp done
        count: equ 3
        table: db 7,8
        done:  hlt
        total  equ count+HIGH(1234h)+LOW 1234h
    """)
    assert r.symbols["COUNT"].value == 3
    assert r.symbols["TOTAL"].value == 3 + 0x12 + 0x34
    assert r.image[0] == 0x21
    assert r.symbols["TABLE"].kind == "data" and r.symbols["TABLE"].size == 2


@pytest.mark.parametrize("expr,val", [
    ("1+2*3", 7), ("(1+2)*3", 9), ("10h", 16), ("0x1F", 31), ("1010b", 10), ("17o", 15), ("0FFh", 255),
    ("'A'", 65), ("7 AND 3", 3), ("1 SHL 4", 16), ("0F0h SHR 4", 15), ("-1", 255), ("~0", 255),
    ("10 MOD 3", 1), ("7/2", 3), ("-7/2", 253), ("2|1", 3), ("6^3", 5), ("HIGH 0ABCDh", 0xAB),
    ("$", 0), ("$+2", 2), ("LOW NOT 0F0h", 0x0F), ("1<<3|1", 9),
])
def test_expressions(expr, val):
    assert bytes_of(f"mvi a,{expr}\nhlt")[1] == val


def test_diagnostics_have_exact_columns():
    r = assemble("  mvi a,300\n")
    d = r.errors[0]
    assert d.line == 1 and r.errors and "300" in d.message
    assert "  mvi a,300"[d.start:d.end] == "300"
    r = assemble("loop: foo a,b")
    assert "foo" in r.errors[0].message
    assert "loop: foo a,b"[r.errors[0].start:r.errors[0].end] == "foo"


def test_helpful_messages():
    def msgs(src):
        return [d.message for d in assemble(src).errors]

    assert any("did you mean MOV" in m for m in msgs("mob a,b"))
    assert any("register name" in m for m in msgs("mvi a,b"))
    assert any("accepts" in m for m in msgs("mov a,5"))
    assert any("accepts B, D, H, PSW" in m or "PSW" in m for m in msgs("push a"))
    assert any("Undefined symbol" in m and "start" in m for m in msgs("jmp start"))
    assert any("0ABh" in m for m in msgs("mvi a,ABh"))
    assert any("already defined" in m for m in msgs("x: nop\nx: nop"))
    assert any("instruction and cannot be a label" in m for m in msgs("sub: nop"))
    assert any("register name and cannot be a label" in m for m in msgs("b: nop"))
    assert any("put a ':'" in m for m in msgs("start mov a,b"))
    assert any("Missing operand" in m for m in msgs("mvi a,"))
    assert any("takes 2 operands" in m or "needs 2" in m for m in msgs("mov a"))
    assert any("takes no operands" in m for m in msgs("nop 5"))
    assert any("does not fit" in m for m in msgs("lxi h,70000"))
    assert any("Division by zero" in m for m in msgs("mvi a,1/0"))
    assert any("Missing closing" in m for m in msgs("mvi a,(1+2"))
    assert any("overlapping" in m for m in msgs("org 10h\nnop\norg 10h\nnop"))
    assert any("must be defined before" in m for m in msgs("ds later\nlater: equ 3"))
    assert any("EQU needs a name" in m for m in msgs("equ 5"))
    assert any("RST number" in m for m in msgs("rst 9"))
    assert any("Invalid binary" in m for m in msgs("mvi a,12b"))


def test_all_errors_reported_at_once():
    r = assemble("mvi a,300\nfoo\nmov a,5\njmp nowhere\nhlt")
    assert [d.line for d in r.errors] == [1, 2, 3, 4]


def test_warning_for_missing_hlt_only():
    assert assemble("nop\nnop").warnings
    assert not assemble("nop\nhlt").warnings
    assert not assemble("loop: jmp loop").warnings


def test_listing_and_line_maps():
    r = code("; c\n  mvi a,5\nx: db 1,2\n  hlt")
    assert r.line_to_addr == {2: 0, 4: 4} and r.addr_to_line == {0: 2, 4: 4}
    assert [(l.line, l.addr, l.data.hex()) for l in r.listing] == [
        (1, None, ""), (2, 0, "3e05"), (3, 2, "0102"), (4, 4, "76")]


def test_gnusim8085_style_programs_still_assemble():
    r = code("""
        jmp start
        ;data
        hai:    db 34,56h
        tmp:    equ 39h
        start:  lxi h,hai+1
                mov a,m
                out tmp
                sta hai
                hlt
    """, 0x4200)
    assert r.image[0x4200] == 0xC3 and r.symbols["TMP"].value == 0x39


def test_assembler_never_raises_on_garbage():
    rnd = random.Random(1234)
    alphabet = string.ascii_letters + string.digits + " ,:;'\"()+-*/$%&|^~<>@.?\t"
    keywords = ["mov", "mvi", "db", "dw", "ds", "org", "equ", "end", "a", "b", "m", "sp", "lxi", "'", '"']
    for _ in range(3000):
        n = rnd.randint(1, 4)
        lines = []
        for _ in range(n):
            parts = [rnd.choice(keywords) if rnd.random() < 0.4 else
                     "".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 6)))
                     for _ in range(rnd.randint(1, 5))]
            lines.append(rnd.choice([" ", ""]) + " ".join(parts))
        r = assemble("\n".join(lines), rnd.choice([0, 0x4200, 0xFFFE]))
        for d in r.diagnostics:
            assert d.line >= 1 and d.start >= 0 and d.end > d.start
