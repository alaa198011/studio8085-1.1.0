from importlib import resources

import pytest

from studio8085.core.assembler import assemble
from studio8085.core.machine import Machine, Stop


def load_example(name):
    text = resources.files("studio8085").joinpath("examples", name).read_text(encoding="utf-8")
    r = assemble(text, 0)
    assert r.ok and not r.warnings, [(d.line, d.message) for d in r.diagnostics]
    m = Machine()
    m.load(r)
    return m, r


def mem(m, r, sym, n=1):
    a = r.symbols[sym.upper()].value
    return bytes(m.cpu.mem.data[a:a + n])


def test_all_examples_assemble_cleanly():
    for f in resources.files("studio8085").joinpath("examples").iterdir():
        if f.name.endswith(".asm"):
            r = assemble(f.read_text(encoding="utf-8"), 0)
            assert r.ok and not r.warnings, (f.name, [(d.line, d.message) for d in r.diagnostics])


def test_counter_leds():
    m, r = load_example("01_counter_leds.asm")
    assert m.run_to_end() is Stop.HALT
    assert m.cpu.io[1] == 255 and m.cpu.regs[0] == 0
    assert [v for _, p, v in m.out_log][:3] == [0, 1, 2] and len(m.out_log) == 256


def test_sum_array():
    m, r = load_example("02_sum_array.asm")
    assert m.run_to_end() is Stop.HALT
    assert mem(m, r, "total", 2) == (961).to_bytes(2, "little") and m.cpu.hl == 961


def test_bubble_sort_handles_duplicates():
    m, r = load_example("03_bubble_sort.asm")
    assert m.run_to_end() is Stop.HALT
    assert list(mem(m, r, "list", 8)) == [0, 1, 7, 7, 19, 42, 63, 255]


def test_bcd_add():
    m, r = load_example("04_bcd_add.asm")
    assert m.run_to_end() is Stop.HALT
    assert mem(m, r, "result", 2) == bytes([0x86, 0x00]) and m.cpu.cy == 1 and m.cpu.z == 1


def test_fibonacci():
    m, r = load_example("05_fibonacci.asm")
    assert m.run_to_end() is Stop.HALT
    assert list(mem(m, r, "series", 13)) == [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]


def test_multiply():
    m, r = load_example("06_multiply.asm")
    assert m.run_to_end() is Stop.HALT
    assert m.cpu.hl == 221 and mem(m, r, "product", 2) == bytes([221, 0])


@pytest.mark.parametrize("a,b", [(0, 5), (255, 255), (16, 16), (1, 200), (7, 0)])
def test_multiply_other_inputs(a, b):
    m, r = load_example("06_multiply.asm")
    m.cpu.mem.data[1], m.cpu.mem.data[3] = a, b  # patch the two MVI immediates
    assert m.run_to_end() is Stop.HALT
    assert m.cpu.hl == a * b


def test_subroutines_and_stack_balance():
    m, r = load_example("07_subroutines.asm")
    assert m.run_to_end() is Stop.HALT
    assert mem(m, r, "result") == bytes([81]) and m.cpu.regs[7] == 3 and m.cpu.sp == 0x8000
    assert (m.cpu.regs[0], m.cpu.regs[1]) == (0, 0)  # PUSH B / POP B preserved BC


def test_interrupt_demo():
    m, r = load_example("08_interrupts.asm")
    assert m.run_to_end() is Stop.HALT and m.cpu.halted
    for _ in range(3):
        m.cpu.raise_interrupt("RST7.5")
        assert m.run_to_end() is Stop.HALT
    m.cpu.raise_interrupt("TRAP")
    assert m.run_to_end() is Stop.HALT
    assert mem(m, r, "presses") == bytes([3]) and mem(m, r, "traps") == bytes([1])
    assert m.cpu.io[1] == 3


def test_string_reverse():
    m, r = load_example("09_string_reverse.asm")
    assert m.run_to_end() is Stop.HALT
    assert mem(m, r, "text", 12) == b"!5808 ,olleH"


def test_memory_heatmap_copy():
    m, r = load_example("10_memory_heatmap.asm")
    assert m.run_to_end() is Stop.HALT
    d = m.cpu.mem.data
    assert d[0x2000:0x2100] == bytes(range(256)) and d[0x3000:0x3100] == bytes(range(256))
    assert m.cpu.mem.wr[0x2005] == 1 and m.cpu.mem.rd[0x2005] == 1
