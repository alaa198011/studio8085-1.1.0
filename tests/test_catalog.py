"""The instruction catalog behind the Instructions panel: the opcode a student sees must be the byte
the assembler produces for the text a click inserts."""

import pytest

from studio8085.core.assembler import assemble
from studio8085.core.catalog import (CATALOG, CATEGORIES, ESSENTIAL, FORM_OF, SCOPE_ALL, SCOPE_ESSENTIAL,
                                     category_of, describe, search)
from studio8085.core.opcodes import BY_MNEMONIC, TABLE

ALL_FORMS = [f for e in CATALOG for f in e.forms]


def test_every_one_of_the_246_opcodes_is_listed_exactly_once():
    assert sorted(f.opcode for f in ALL_FORMS) == sorted(i.opcode for i in TABLE if i)
    assert len(ALL_FORMS) == 246
    assert [e.mnemonic for e in CATALOG].count("MOV") == 1 and len(CATALOG) == len(BY_MNEMONIC)


def test_categories_cover_everything_and_branch_is_not_confused_with_logic():
    assert {e.category for e in CATALOG} == set(CATEGORIES)
    # CMP/CMA/CMC are logic, CC/CM/CP/CPE/CPO are calls: the names look alike but are different instructions
    for mn in ("CMP", "CMA", "CMC", "CPI"):
        assert category_of(mn) == "Logic and rotate"
    for mn in ("CC", "CM", "CP", "CPE", "CPO", "RC", "RM", "RP", "JM", "JP", "RST", "PCHL"):
        assert category_of(mn) == "Branch"
    assert category_of("MOV") == "Data transfer" and category_of("DAD") == "Arithmetic"
    assert category_of("PUSH") == "Stack, I/O and control" and category_of("OUT") == "Stack, I/O and control"


@pytest.mark.parametrize("form", ALL_FORMS, ids=lambda f: f"{f.opcode:02X}-{f.label}")
def test_inserted_text_assembles_to_the_listed_opcode(form):
    r = assemble("        " + form.insert + "\nlabel:  hlt\n", 0)
    assert r.ok and not r.warnings, (form.insert, [d.message for d in r.diagnostics])
    assert r.image[0] == form.opcode, (form.insert, f"{r.image[0]:02X} != {form.opcode:02X}")
    size = r.symbols["LABEL"].value  # bytes before the label = the instruction's length
    assert size == form.length
    assert len(form.machine_code.split()) == form.length  # "3E dd" / "C3 lo hi"
    # the placeholder that gets selected is exactly the operand to type over
    if form.select:
        start, n = form.select
        assert form.insert[start:start + n] in ("00h", "0000h", "label")
    else:
        assert form.length == 1


def test_placeholders_by_operand_kind():
    by = {f.label: f for f in ALL_FORMS}
    assert by["MVI A,data8"].insert == "mvi   a,00h" and by["MVI A,data8"].select == (8, 3)
    assert by["LXI H,data16"].insert == "lxi   h,0000h" and by["LXI H,data16"].select == (8, 5)
    assert by["LDA addr"].insert == "lda   0000h" and by["LDA addr"].select == (6, 5)
    assert by["JMP addr"].insert == "jmp   label" and by["JMP addr"].select == (6, 5)
    assert by["CNZ addr"].insert == "cnz   label"
    assert by["IN port"].insert == "in    00h" and by["OUT port"].insert == "out   00h"
    assert by["MOV A,B"].insert == "mov   a,b" and by["MOV A,B"].select is None
    assert by["PUSH PSW"].insert == "push  psw" and by["LXI SP,data16"].insert == "lxi   sp,0000h"
    assert by["RST 5"].insert == "rst   5" and by["HLT"].insert == "hlt" and by["NOP"].select is None


# independent of the project's opcode table: values from Intel's 8085 opcode chart
CHART = {
    "NOP": 0x00, "HLT": 0x76, "MOV A,B": 0x78, "MOV B,A": 0x47, "MOV A,M": 0x7E, "MOV M,A": 0x77,
    "MVI A,data8": 0x3E, "MVI M,data8": 0x36, "LXI B,data16": 0x01, "LXI H,data16": 0x21,
    "LXI SP,data16": 0x31, "LDA addr": 0x3A, "STA addr": 0x32, "LHLD addr": 0x2A, "SHLD addr": 0x22,
    "LDAX B": 0x0A, "STAX D": 0x12, "XCHG": 0xEB, "ADD B": 0x80, "ADD M": 0x86, "ADI data8": 0xC6,
    "ADC B": 0x88, "SUB B": 0x90, "SUI data8": 0xD6, "SBB B": 0x98, "INR A": 0x3C, "DCR A": 0x3D,
    "INX H": 0x23, "DCX H": 0x2B, "DAD H": 0x29, "DAA": 0x27, "ANA B": 0xA0, "ANI data8": 0xE6,
    "ORA B": 0xB0, "ORI data8": 0xF6, "XRA A": 0xAF, "XRI data8": 0xEE, "CMP B": 0xB8, "CPI data8": 0xFE,
    "RLC": 0x07, "RRC": 0x0F, "RAL": 0x17, "RAR": 0x1F, "CMA": 0x2F, "STC": 0x37, "CMC": 0x3F,
    "JMP addr": 0xC3, "JZ addr": 0xCA, "JNZ addr": 0xC2, "JC addr": 0xDA, "JNC addr": 0xD2,
    "CALL addr": 0xCD, "RET": 0xC9, "RZ": 0xC8, "PUSH B": 0xC5, "PUSH PSW": 0xF5, "POP PSW": 0xF1,
    "IN port": 0xDB, "OUT port": 0xD3, "EI": 0xFB, "DI": 0xF3, "RIM": 0x20, "SIM": 0x30, "RST 7": 0xFF,
    "XTHL": 0xE3, "SPHL": 0xF9, "PCHL": 0xE9,
}
TIMES = {"MOV A,B": "4", "MOV A,M": "7", "MVI A,data8": "7", "MVI M,data8": "10", "JNZ addr": "7/10",
         "CALL addr": "18", "CNZ addr": "9/18", "RET": "10", "RNZ": "6/12", "IN port": "10", "PUSH B": "12",
         "POP B": "10", "XTHL": "16", "SHLD addr": "16", "LDA addr": "13", "HLT": "5", "NOP": "4",
         "LXI H,data16": "10", "DAD H": "10", "INX H": "6", "RST 7": "12"}


def test_opcodes_match_the_published_chart():
    by = {f.label: f for f in ALL_FORMS}
    for label, op in CHART.items():
        assert by[label].opcode == op, label
        assert FORM_OF[op] is by[label]


def test_timing_text():
    by = {f.label: f for f in ALL_FORMS}
    for label, t in TIMES.items():
        assert by[label].timing == t, label


def test_binary_and_machine_code_text():
    by = {f.label: f for f in ALL_FORMS}
    assert by["MOV A,B"].binary == "0111 1000" and by["MOV A,B"].hex == "78"
    assert by["MVI A,data8"].machine_code == "3E dd" and by["JMP addr"].machine_code == "C3 lo hi"
    assert by["IN port"].machine_code == "DB pp" and by["HLT"].machine_code == "76"


def test_essential_set_is_in_the_catalog_and_scopes_filter():
    assert ESSENTIAL <= {e.mnemonic for e in CATALOG}
    ess = [e for e, _ in search("", SCOPE_ESSENTIAL)]
    assert {e.mnemonic for e in ess} == ESSENTIAL
    assert len(search("", SCOPE_ALL)) == len(CATALOG)
    assert all(e.category == "Branch" for e, _ in search("", "Branch"))
    assert sum(len(search("", c)) for c in CATEGORIES) == len(CATALOG)  # a partition


def test_search_by_mnemonic_operands_and_opcode():
    hit = search("mov a,b")
    assert [(e.mnemonic, [f.hex for f in fs]) for e, fs in hit] == [("MOV", ["78"])]
    assert [f.hex for f in search("78")[0][1]] == ["78"]
    assert [f.hex for f in search("78h")[0][1]] == ["78"]
    assert [f.label for f in search("0x3E")[0][1]] == ["MVI A,data8"]
    assert [f.label for f in search("3eh")[0][1]] == ["MVI A,data8"]
    mov_a = {f.label for f in search("mov a")[0][1]}
    assert {"MOV A,B", "MOV A,M"} <= mov_a and not ({"MOV B,A", "MOV B,C"} & mov_a) and len(mov_a) == 8
    assert [f.label for f in search("mov b,a")[0][1]] == ["MOV B,A"]
    assert {f.label for _, fs in search("psw") for f in fs} == {"PUSH PSW", "POP PSW"}  # an operand finds its users
    assert [e.mnemonic for e, _ in search("ad")] == ["ADD", "ADI", "ADC"]  # letters beat hex "AD"
    assert [e.mnemonic for e, _ in search("add")] == ["ADD"]  # not LDA/STA, whose syntax says "addr"
    assert [e.mnemonic for e, _ in search("INR")] == ["INR"] and len(search("inr")[0][1]) == 8
    assert search("zzz") == []


def test_search_falls_back_to_what_an_instruction_does():
    names = {e.mnemonic for e, _ in search("carry")}
    assert {"STC", "CMC", "RAL", "RAR"} <= names
    assert {"RLC", "RRC", "RAL", "RAR"} <= {e.mnemonic for e, _ in search("rotate")}
    # the scope still applies
    assert {e.mnemonic for e, _ in search("carry", SCOPE_ESSENTIAL)} <= ESSENTIAL


def test_describe_mentions_the_opcode_size_and_timing():
    by = {f.label: (e, f) for e in CATALOG for f in e.forms}
    e, f = by["MVI A,data8"]
    text = describe(e, f)
    assert "3Eh" in text and "0011 1110b" in text and "2 bytes" in text and "3E dd" in text and "7 T-states" in text
    e, f = by["JNZ addr"]
    assert "7/10 T-states" in describe(e, f)
    mov = next(e for e in CATALOG if e.mnemonic == "MOV")
    assert "64 opcodes" not in describe(mov) and f"{len(mov.forms)} opcodes between 40h and 7Fh" in describe(mov)
    assert "4-7 T-states" in describe(mov)
