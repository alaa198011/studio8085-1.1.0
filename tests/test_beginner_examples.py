"""The beginner example set: every program's result is checked, and together they must
exercise the essential instructions a first course covers."""

from importlib import resources

import pytest

from studio8085.core.assembler import assemble
from studio8085.core.catalog import ESSENTIAL  # the set the Instructions panel offers by default
from studio8085.core.machine import Machine, Stop
from studio8085.core.meta import parse_metadata
from studio8085.core.opcodes import TABLE

FOLDER = resources.files("studio8085").joinpath("examples", "beginner")

def run(name, setup=None):
    text = FOLDER.joinpath(name).read_text(encoding="utf-8")
    r = assemble(text, 0)
    assert r.ok and not r.warnings, (name, [(d.line, d.message) for d in r.diagnostics])
    m = Machine()
    m.load(r)
    if setup:
        setup(m)
    assert m.run_to_end(100_000) is Stop.HALT, name
    return m, r


def mem(m, r, sym, n=1):
    a = r.symbols[sym.upper()].value
    return bytes(m.cpu.mem.data[a:a + n])


def regs(m):
    c = m.cpu
    return dict(A=c.regs[7], B=c.regs[0], C=c.regs[1], D=c.regs[2], E=c.regs[3], HL=c.hl)


def test_the_set_is_complete_and_numbered():
    names = [f.name for f in sources()]
    assert [n.split("_")[0] for n in names] == [f"{i:02d}" for i in range(1, 18)]


def sources():
    return [f for f in sorted(FOLDER.iterdir(), key=lambda f: f.name) if f.name.endswith(".asm")]


def mnemonics(text):
    """Mnemonics of the instructions the assembler actually emitted (not words in comments)."""
    r = assemble(text, 0)
    return {TABLE[r.image[a]].mnemonic for a in r.addr_to_line}


def test_every_example_is_labelled_short_and_ends_in_hlt():
    for f in sources():
        text = f.read_text(encoding="utf-8")
        meta = parse_metadata(text.splitlines())
        assert meta.get("title") and meta.get("topic"), f.name
        assert meta.get("validation") == "T", f.name
        assert "HLT" in mnemonics(text), f.name
        assert len(text.splitlines()) <= 45, f"{f.name} is not 'simple' any more"
        m, _ = run(f.name)
        assert m.cpu.icount < 100, f.name  # short enough to step through by hand


def test_together_they_use_every_essential_instruction():
    used = set()
    for f in sources():
        used |= mnemonics(f.read_text(encoding="utf-8"))
    assert ESSENTIAL <= used, sorted(ESSENTIAL - used)


def test_01_first_program():
    m, _ = run("01_first_program.asm")
    assert regs(m) == dict(A=5, B=10, C=0xFF, D=0, E=0, HL=0) and m.cpu.icount == 5


def test_02_move_data_copies_and_swaps():
    m, _ = run("02_move_data.asm")
    assert regs(m) == dict(A=2, B=1, C=1, D=0x42, E=0x42, HL=0)


def test_03_add_numbers():
    m, r = run("03_add_numbers.asm")
    assert m.cpu.regs[7] == 50 and mem(m, r, "result") == bytes([50]) and m.cpu.cy == 0


def test_04_subtract_and_borrow():
    m, r = run("04_subtract_and_borrow.asm")
    assert mem(m, r, "diff", 2) == bytes([32, 0xFB])
    assert m.cpu.regs[7] == 0xFB and m.cpu.cy == 1  # the borrow from 5 - 10


def test_05_inr_dcr_set_zero_but_never_carry():
    m, _ = run("05_increment_decrement.asm")
    c = m.cpu
    assert (c.regs[0], c.regs[1], c.hl, c.regs[2]) == (3, 0, 0x0100, 0)
    assert c.z == 1 and c.cy == 0  # INR D wrapped 255 -> 0: Z set, CY untouched


def test_06_carry_flag_and_16_bit_add():
    m, _ = run("06_carry_flag.asm")
    assert m.cpu.hl == 0x0200 and m.cpu.regs[7] == 2
    assert m.cpu.cy == 0  # STC then CMC


def test_06_first_step_shows_the_carry():
    r = assemble(FOLDER.joinpath("06_carry_flag.asm").read_text(encoding="utf-8"), 0)
    m = Machine()
    m.load(r)
    m.step_into()
    m.step_into()  # MVI A,FFh ; ADI 1
    assert (m.cpu.regs[7], m.cpu.cy, m.cpu.z) == (0, 1, 1)


def test_07_load_store_memory():
    m, r = run("07_load_store_memory.asm")
    assert mem(m, r, "total") == bytes([42]) and m.cpu.regs[7] == 42


def test_08_hl_pointer_and_m_register():
    m, r = run("08_hl_pointer_memory.asm")
    assert mem(m, r, "table", 3) == bytes([0x11, 0x23, 0x33]) and m.cpu.regs[7] == 0x22


@pytest.mark.parametrize("a,code", [(7, 1), (0, 1), (9, 1), (10, 2), (11, 3), (255, 3)])
def test_09_compare_and_branch_classifies_the_number(a, code):
    def patch(m):
        m.cpu.mem.data[1] = a  # the immediate of "mvi a,7"
    m, _ = run("09_compare_and_branch.asm", patch)
    assert m.cpu.regs[0] == code


def test_10_loop_adds_ten_down_to_one():
    m, r = run("10_loop_with_counter.asm")
    assert mem(m, r, "total") == bytes([55]) and m.cpu.regs[1] == 0 and m.cpu.z == 1


def test_11_logic_masks():
    m, _ = run("11_logic_masks.asm")
    assert regs(m) == dict(A=0, B=0x05, C=0xA5, D=0xF0, E=0x0F, HL=0)
    assert m.cpu.z == 1 and m.cpu.cy == 0  # XRA A


def test_12_rotate_double_and_halve():
    m, _ = run("12_rotate_double_halve.asm")
    assert m.cpu.regs[0] == 20 and m.cpu.regs[7] == 2 and m.cpu.cy == 1  # 5 / 2 = 2 remainder 1


def test_13_stack_swap_and_psw():
    m, _ = run("13_stack_push_pop.asm")
    c = m.cpu
    assert (c.get_rp(0), c.get_rp(1)) == (0x2222, 0x1111) and c.regs[7] == 7 and c.sp == 0x2000


def test_14_call_ret_doubles_three_times():
    m, _ = run("14_call_and_return.asm")
    assert m.cpu.regs[7] == 24 and m.cpu.sp == 0xFFFF  # the stack is balanced again


def test_15_ports_in_and_out():
    m, _ = run("15_input_output_ports.asm")
    assert m.cpu.io[1] == 1 and [(p, v) for _, p, v in m.out_log] == [(1, 1)]  # nothing typed on port 0
    m, _ = run("15_input_output_ports.asm", lambda mm: mm.cpu.io.__setitem__(0, 0x41))
    assert m.cpu.io[1] == 0x42


def test_16_sixteen_bit_pairs():
    m, _ = run("16_sixteen_bit_registers.asm")
    c = m.cpu
    assert (c.hl, c.get_rp(1), c.cy) == (0x0233, 0x1235, 0)


def test_17_copy_five_bytes():
    m, r = run("17_copy_bytes.asm")
    assert mem(m, r, "dest", 5) == bytes([10, 20, 30, 40, 50]) == mem(m, r, "source", 5)
    assert m.cpu.regs[1] == 0
