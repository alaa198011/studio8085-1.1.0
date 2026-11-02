"""Tests for the 1.1 core features: explanations, trace, state diff, compatibility checks, regions."""
import csv
import io

import pytest

from studio8085.core import Machine, assemble, diff
from studio8085.core.compat import check_compat
from studio8085.core.explain import explain_instruction, explain_next, flag_notes
from studio8085.core.meta import describe_validation, parse_metadata
from studio8085.core.opcodes import TABLE
from studio8085.core.trace import COLUMNS, to_csv, to_html, to_markdown


def machine(src, origin=0):
    r = assemble(src, origin)
    assert r.ok, [(d.line, d.message) for d in r.diagnostics]
    m = Machine()
    m.load(r)
    return m, r


# ------------------------------------------------------------ explanations
def test_every_opcode_has_a_nonempty_explanation():
    m, _ = machine("nop")
    for ins in TABLE:
        if not ins:
            continue
        raw = bytes([ins.opcode, 0x34, 0x12][:ins.length])
        e = explain_instruction(ins, raw, m.cpu)
        assert e.title.startswith(ins.mnemonic) and e.summary and e.tstates and e.code_bytes
        assert e.html().startswith("<p")


def test_explanation_uses_live_register_values():
    m, _ = machine("mvi a,3Fh\nmvi b,1\nadd b\nhlt")
    m.step_into()
    m.step_into()
    e = explain_next(m.cpu)
    assert e.title == "ADD B" and "3Fh" in " ".join(e.details) and "40h" in " ".join(e.outcomes)
    assert e.flags_changed == ["S", "Z", "AC", "P", "CY"] and e.flags_kept == []
    assert e.tstates == "4"


def test_inr_dcr_explanation_says_carry_is_untouched():
    m, _ = machine("mvi b,5\ndcr b\nhlt")
    m.step_into()
    e = explain_next(m.cpu)
    assert e.flags_changed == ["S", "Z", "AC", "P"] and e.flags_kept == ["CY"]
    assert "05h" in e.details[0] and "04h" in e.outcomes[0] and "CY" in e.flag_comment


@pytest.mark.parametrize("setup,taken", [("xra a", True), ("mvi a,1\nora a", False)])
def test_conditional_branch_prediction(setup, taken):
    m, _ = machine(f"{setup}\njz done\nnop\ndone: hlt")
    m.step_into()
    if "\n" in setup:
        m.step_into()
    e = explain_next(m.cpu)
    assert ("WILL be taken" in e.condition) == taken
    assert e.tstates == "7/10 (not taken/taken)"
    assert ("10 T-states" if taken else "7 T-states") in e.condition


def test_memory_operand_names_the_address():
    m, _ = machine("lxi h,2000h\nmov a,m\nhlt")
    m.cpu.mem.data[0x2000] = 0x7F
    m.step_into()
    e = explain_next(m.cpu)
    assert "2000h" in e.summary and "7Fh" in e.summary


def test_flag_notes_explain_carry_zero_sign():
    m, _ = machine("mvi a,0FFh\nadi 1\nhlt")
    m.step_into()
    b = diff.take(m)
    m.step_into()
    a = diff.take(m)
    notes = flag_notes("ADI", b.flags, a.flags)
    joined = " ".join(notes)
    assert "CY changed from 0 to 1" in joined and "carry out of bit 7" in joined
    assert "Z changed from 0 to 1" in joined and "00h" in joined
    assert "S" not in "".join(n[:1] for n in notes if n.startswith("S "))  # S stayed 0


def test_subtraction_flag_notes_follow_the_selected_convention():
    hw = flag_notes("SUB", {"AC": 0}, {"AC": 1}, ac_borrow_style=False)[0]
    tb = flag_notes("SUB", {"AC": 0}, {"AC": 1}, ac_borrow_style=True)[0]
    assert "hardware" in hw and "textbook" in tb
    assert "borrow" in flag_notes("SUB", {"CY": 0}, {"CY": 1})[0]
    assert "smaller" in flag_notes("CMP", {"CY": 0}, {"CY": 1})[0]


# ------------------------------------------------------------------- diff
def test_state_diff_lists_registers_flags_memory_and_io():
    m, _ = machine("mvi a,5\nsta 100h\nout 7\nhlt")
    before = diff.take(m)
    m.run_to_end()
    d = diff.compare(before, diff.take(m))
    names = [i[0] for i in d.items]
    assert "A" in names and "PC" in names and d.mem == [(0x100, 0, 5)] and d.io == [(7, 0, 5)]
    assert d.instructions == 4 and d.tstates == 7 + 13 + 10 + 5


# ------------------------------------------------------------------ trace
def test_trace_records_state_after_each_instruction_with_events():
    m, r = machine("mvi a,0FFh\nadi 1\nout 5\npush psw\nhlt")
    m.set_trace(True)
    m.run_to_end()
    rows = m.trace
    assert [x.text for x in rows] == ["MVI A,0FFh", "ADI 01h", "OUT 05h", "PUSH PSW", "HLT"]
    assert rows[1].flags == (0, 1, 1, 1, 1) and rows[1].regs[0] == 0
    assert rows[2].events == (("OUT", 5, 0),)
    assert rows[3].events == (("W", 0xFFFE, 0), ("W", 0xFFFD, 0x57)) and rows[3].sp == 0xFFFD
    assert rows[-1].tstates == m.cpu.tstates == 41 and rows[0].line == 1


def test_trace_records_interrupts_and_stays_off_by_default():
    src = "org 0\njmp go\norg 3Ch\nisr: inr b\nei\nret\norg 100h\ngo: mvi a,0Bh\nsim\nei\nhlt"
    m, _ = machine(src)
    m.run_to_end()
    assert m.trace == []  # off by default: no cost, no memory
    m.reset_cpu()
    m.set_trace(True)
    m.cpu.pc = 0
    m.run_to_end()
    m.cpu.raise_interrupt("RST7.5")
    m.run_to_end()
    texts = [x.text for x in m.trace]
    assert any(t.startswith("<interrupt>") for t in texts) and "INR B" in texts
    assert any(("INT", 0x3C) in x.events for x in m.trace)


def test_trace_limit_truncates_and_reports():
    m, _ = machine("lp: inr a\njnz lp\nhlt")
    m.trace_limit = 100
    m.set_trace(True)
    m.run_to_end()
    assert len(m.trace) == 100 and m.trace_truncated


def test_trace_exports_are_well_formed():
    m, _ = machine("mvi a,1\nout 9\nhlt")
    m.set_trace(True)
    m.run_to_end()
    rows = list(csv.reader(io.StringIO(to_csv(m.trace))))
    assert rows[0] == COLUMNS and len(rows) == 4 and all(len(r) == len(COLUMNS) for r in rows)
    md = to_markdown(m.trace, "T", "note")
    assert md.startswith("# T") and md.count("\n| ") >= 4 and "OUT 09h=01h" in md
    html = to_html(m.trace, "T<>")
    assert "<table>" in html and "T&lt;&gt;" in html and html.count("<tr>") == 4


# ------------------------------------------------------ regions + metadata
def test_regions_classify_code_data_and_reserved():
    r = assemble("lxi h,tbl\nhlt\ntbl: db 1,2\nw: dw 5\nbuf: ds 4\n")
    kinds = [(x.start, x.size, x.kind, x.line) for x in r.regions]
    assert kinds == [(0, 3, "code", 1), (3, 1, "code", 2), (4, 2, "data", 3), (6, 2, "data", 4), (8, 4, "reserved", 5)]
    assert r.region_at(1).line == 1 and r.region_at(5).kind == "data" and r.region_at(99) is None


def test_metadata_block_and_validation_labels():
    r = assemble("; @title: Demo\n; @topic: Carry flag\n; @validation: T+M\n\n; plain comment\n\thlt\n; @late: ignored\n")
    assert r.metadata == {"title": "Demo", "topic": "Carry flag", "validation": "T+M"}
    d = describe_validation("T+M")
    assert d[0].startswith("T = Tool-tested") and d[1].startswith("M = Manually validated")
    full = describe_validation("T+M+H", with_limits=True)
    assert "true interrupt behaviour" in full[0] and "pair with T" in full[1] and "outside the documented setup" in full[2]
    assert parse_metadata(["hlt", "; @x: y"]) == {}


# ------------------------------------------------------------ compatibility
def notes(src, mode="note"):
    r = assemble(src, 0, compat=mode)
    return r, [d.message for d in r.diagnostics if d.severity in ("info", "error")]


def test_compat_off_is_silent_and_gnusim_style_source_is_clean():
    r, msgs = notes("jmp start\nhai: db 34,56h,0ffh\ntmp: equ 39h\nstart: lxi h,hai+1\nmov a,m\nout tmp\nsta hai\nhlt")
    assert r.ok and msgs == []
    r = assemble("org 100h\nhlt", 0, compat="off")
    assert r.diagnostics == [] or all(d.severity == "warning" for d in r.diagnostics)


@pytest.mark.parametrize("src,needle", [
    ("org 100h\nhlt", "ORG"), ("dw 1234h\nhlt", "DW"), ("hlt\nend", "END"),
    ("foo:\n\tnop\n\thlt", "same line"), ("foo equ 5\nhlt", "end with ':'"),
    ("mvi a,0x10\nhlt", "0x prefix"), ("mvi a,17q\nhlt", "q suffix"), ("mvi a,10d\nhlt", "d suffix"),
    ("mvi a,'A'\nhlt", "character"), ("db \"hi\"\nhlt", "character and string"),
    ("jmp $\nhlt", "$"), ("mvi a,2*3\nhlt", "expressions are not supported"),
    ("mvi a,(1)\nhlt", "expressions"), ("mvi a,1+2\nhlt", "expressions"),
    ("x: db 1\nlxi h,x+x\nhlt", "expressions"), ("ds 2,5\nhlt", "fill value"),
    ("mvi a,-5\nhlt", "minus sign"), ("Foo: nop\njmp foo\nhlt", "case-sensitive"),
])
def test_compat_notes_name_each_difference(src, needle):
    r, msgs = notes(src)
    assert r.ok  # notes never block assembly
    assert any(needle in m for m in msgs), (needle, msgs)
    assert all(m.startswith("GNUSim8085 difference:") for m in msgs)


def test_compat_strict_turns_differences_into_errors():
    r, msgs = notes("org 100h\nmvi a,2*3\nhlt", "strict")
    assert not r.ok and len(r.errors) == 2 and msgs[0].startswith("Not allowed in GNUSim8085-compatible mode:")


def test_compat_accepts_what_gnusim_accepts():
    ok = ["mvi a,5-0\nhlt" if False else "mvi a,5\nhlt", "x1: db 1,2\nlxi h,x1+1\nhlt", "k: equ 2\nmvi a,k+1\nhlt",
          "mvi a,101b\nhlt", "mvi a,17o\nhlt", "mvi a,0AH\nhlt", "x1: nop\njmp x1-0\nhlt", "rst 3\nhlt"]
    for src in ok:
        r, msgs = notes(src)
        assert msgs == [], (src, msgs)


# ---- predict-first mode (added after review: the explanation must not give away the answer)
def _explain_after(src, steps=0):
    from studio8085.core.assembler import assemble
    from studio8085.core.explain import explain_next
    from studio8085.core.machine import Machine
    m = Machine()
    m.load(assemble(src, 0))
    for _ in range(steps):
        m.step_into()
    return explain_next(m.cpu)


def test_predict_first_hides_every_result_but_keeps_inputs():
    cases = [
        ("mvi a,99h\nadi 01h\nhlt", 1, ["9Ah"]),            # ALU result
        ("mvi a,5\ncpi 5\nhlt", 1, ["equal"]),                # compare outcome
        ("mvi b,7\ninr b\nhlt", 1, ["8"]),                    # INR result
        ("mvi a,3\ncma\nhlt", 1, ["FCh"]),                    # CMA result
        ("xra a\njz 5\nhlt", 1, ["WILL"]),                    # branch decision
        ("mvi a,1\nrlc\nhlt", 1, ["00000010b"]),              # rotate result
    ]
    for src, steps, secrets in cases:
        e = _explain_after(src, steps)
        shown, hidden = e.text(), e.text(hide_outcome=True)
        for secret in secrets:
            assert secret in shown, (src, secret, shown)
            assert secret not in hidden, (src, secret, hidden)
        assert "predict-first" in hidden
        assert e.summary in hidden  # what the instruction *does* stays visible
        assert "A = " in hidden or "B = " in hidden or "Z is" not in hidden


def test_predict_first_keeps_input_values_visible():
    hidden = _explain_after("mvi a,99h\nadi 01h\nhlt", 1).text(hide_outcome=True)
    assert "A = 99h" in hidden and "the constant = 01h" in hidden and "01h = 01h" not in hidden


def test_instructions_without_outcome_show_no_hint():
    e = _explain_after("nop\nhlt")
    assert "predict-first" not in e.text(hide_outcome=True)
