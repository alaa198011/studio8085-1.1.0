"""Edge cases at the boundaries: address wrap-around, interrupt corners, illegal opcodes,
numeric range limits and unusual source text."""
import pytest

from studio8085.core import CPU, Machine, assemble
from studio8085.core.cpu import HALT, IllegalOpcode
from studio8085.core.machine import Stop
from studio8085.core.opcodes import TABLE


def cpu_with(code, at=0x100, **regs):
    c = CPU()
    c.mem.data[at:at + len(code)] = bytes(code)
    c.pc = at
    for k, v in regs.items():
        setattr(c, k, v)
    return c


# ---------------------------------------------------------- address wrap-around
def test_three_byte_instruction_straddling_the_top_of_memory():
    c = cpu_with([0x21, 0x34, 0x12], at=0xFFFE)  # LXI H,1234h with operands at FFFFh and 0000h
    c.mem.data[0xFFFF], c.mem.data[0x0000] = 0x34, 0x12
    c.step()
    assert c.hl == 0x1234 and c.pc == 0x0001


def test_instruction_fetch_wraps_from_ffff_to_0000():
    c = cpu_with([0x00], at=0xFFFF)  # NOP in the last byte
    c.step()
    assert c.pc == 0x0000


def test_push_with_sp_zero_wraps_into_top_of_memory():
    c = cpu_with([0xC5], b=0, regs=None) if False else cpu_with([0xC5])
    c.regs[0], c.regs[1], c.sp = 0xAB, 0xCD, 0
    c.step()
    assert c.sp == 0xFFFE and c.mem.data[0xFFFF] == 0xAB and c.mem.data[0xFFFE] == 0xCD


def test_xthl_and_call_with_stack_across_zero():
    c = cpu_with([0xE3])
    c.sp = 0xFFFF
    c.mem.data[0xFFFF], c.mem.data[0x0000] = 0x11, 0x22
    c.regs[4], c.regs[5] = 0xAA, 0xBB
    c.step()  # XTHL
    assert (c.regs[4], c.regs[5]) == (0x22, 0x11) and c.mem.data[0xFFFF] == 0xBB and c.mem.data[0] == 0xAA
    c = cpu_with([0xCD, 0x00, 0x20])
    c.sp = 1
    c.step()  # CALL 2000h pushes the return address 0103h at 0000h/FFFFh
    assert c.sp == 0xFFFF and c.mem.data[0x0000] == 0x01 and c.mem.data[0xFFFF] == 0x03 and c.pc == 0x2000


def test_sixteen_bit_inc_dec_wrap():
    c = cpu_with([0x33, 0x3B, 0x3B])  # INX SP ; DCX SP ; DCX SP
    c.sp = 0xFFFF
    c.step()
    assert c.sp == 0
    c.step()
    assert c.sp == 0xFFFF
    c.step()
    assert c.sp == 0xFFFE


def test_ret_with_empty_power_on_stack_reads_ffff_then_wraps():
    c = cpu_with([0xC9])  # RET with SP=FFFFh
    c.mem.data[0xFFFF], c.mem.data[0x0000] = 0x34, 0x12
    c.step()
    assert c.pc == 0x1234 and c.sp == 0x0001


# ---------------------------------------------------------------- halt + interrupts
def test_halted_cpu_does_not_advance_time_or_pc():
    c = cpu_with([0x76])
    assert c.step() == HALT
    t, pc = c.tstates, c.pc
    for _ in range(5):
        assert c.step() == HALT
    assert (c.tstates, c.pc) == (t, pc)


def test_ei_then_hlt_is_woken_by_a_pending_interrupt():
    c = cpu_with([0xFB, 0x76], at=0)  # EI ; HLT
    c.m75 = False
    c.mem.data[0x3C] = 0xC9
    c.raise_interrupt("RST7.5")
    c.step()  # EI (not yet enabled)
    assert c.irq_taken == 0
    c.step()  # HLT executes; EI now takes effect
    assert c.halted
    c.step()  # interrupt wakes the CPU and vectors
    assert c.irq_taken == 1 and c.pc == 0x3C and not c.halted and not c.ie


def test_di_cancels_a_pending_ei():
    c = cpu_with([0xFB, 0xF3, 0x00], at=0)
    c.m75 = False
    c.raise_interrupt("RST7.5")
    for _ in range(3):
        c.step()
    assert c.irq_taken == 0 and not c.ie


def test_intr_uses_the_supplied_rst_vector_and_needs_ie():
    c = cpu_with([0x00, 0x00], at=0)
    c.raise_interrupt("INTR", rst=5)
    c.step()
    assert c.irq_taken == 0  # IE is off
    c.ie = True
    c.step()
    assert c.irq_taken == 1 and c.pc == 0x28


def test_sim_without_mse_leaves_masks_alone_and_trap_ignores_masks():
    c = cpu_with([0x30], at=0)  # SIM
    c.regs[7] = 0x00  # bit 3 (MSE) clear
    c.step()
    assert c.m55 and c.m65 and c.m75
    c = cpu_with([0x00], at=0)
    c.raise_interrupt("TRAP")
    c.step()
    assert c.pc == 0x24


def test_rim_reports_ie_masks_pending_and_sid():
    c = cpu_with([0x20], at=0)
    c.ie, c.sid = True, 1
    c.m55 = c.m75 = False
    c.m65 = True  # 6.5 is masked, so the request stays pending instead of being taken
    c.raise_interrupt("RST6.5")
    c.step()
    assert c.regs[7] == 0b1010_1010  # SID=1, I6.5 pending, IE=1, M6.5=1; other masks clear


# ---------------------------------------------------------------- opcodes and I/O
def test_all_ten_undefined_opcodes_are_illegal():
    undefined = [op for op in range(256) if TABLE[op] is None]
    assert sorted(undefined) == [0x08, 0x10, 0x18, 0x28, 0x38, 0xCB, 0xD9, 0xDD, 0xED, 0xFD]
    for op in undefined:
        c = cpu_with([op])
        with pytest.raises(IllegalOpcode):
            c.step()
        assert c.pc == 0x100 and c.icount == 0


def test_every_port_reads_and_writes():
    c = CPU()
    for port in range(256):
        c.io[port] = port ^ 0x5A
        c.mem.data[0:4] = bytes([0xDB, port, 0xD3, (port + 1) & 0xFF])
        c.pc = 0
        c.step()
        assert c.regs[7] == port ^ 0x5A
        c.step()
        assert c.io[(port + 1) & 0xFF] == port ^ 0x5A


def test_borrow_style_only_changes_ac_for_cmp():
    for borrow in (False, True):
        c = cpu_with([0xFE, 0x01], a=None) if False else cpu_with([0xFE, 0x01])
        c.ac_borrow_style = borrow
        c.regs[7] = 0x10  # 10h - 01h: low nibble must borrow
        c.step()
        assert c.ac == (1 if borrow else 0) and c.cy == 0 and c.z == 0


# ----------------------------------------------------------------- numeric limits
@pytest.mark.parametrize("v,ok", [(-128, True), (-129, False), (255, True), (256, False), (0, True)])
def test_eight_bit_operand_limits(v, ok):
    assert assemble(f"mvi a,{v}\nhlt").ok is ok


@pytest.mark.parametrize("v,ok", [(-32768, True), (-32769, False), (65535, True), (65536, False)])
def test_sixteen_bit_operand_limits(v, ok):
    assert assemble(f"lxi h,{v}\nhlt").ok is ok


def test_negative_values_use_twos_complement():
    r = assemble("mvi a,-1\nlxi h,-2\ndb -128\nhlt")
    assert [r.image[i] for i in range(6)] == [0x3E, 0xFF, 0x21, 0xFE, 0xFF, 0x80]


# ----------------------------------------------------------------- unusual source text
def test_end_stops_assembly_and_ignores_the_rest():
    r = assemble("nop\nhlt\nend\nthis is not valid at all\n")
    assert r.ok and r.size == 2


def test_org_backwards_into_used_space_is_an_error_but_a_gap_is_fine():
    assert not assemble("org 10h\nnop\nnop\norg 10h\nnop").ok
    r = assemble("org 10h\nnop\norg 1000h\nnop\norg 20h\nnop")
    assert r.ok and sorted(r.image) == [0x10, 0x20, 0x1000]


def test_comment_characters_inside_strings_are_data_not_comments():
    r = assemble('db "a;b",\';\'\nhlt')
    assert r.ok and bytes(r.image[i] for i in range(4)) == b"a;b;"


def test_program_may_end_exactly_at_ffff_but_not_run_past_it():
    assert assemble("org 0FFFEh\nnop\nhlt").ok
    r = assemble("org 0FFFEh\nnop\nnop\nhlt")
    assert not r.ok and "64K" in r.errors[0].message


def test_windows_line_endings_tabs_unicode_and_blank_input():
    r = assemble("\tMVI\tA,5\r\n\tHLT\r\n; café ☃\r\n")
    assert r.ok and r.size == 3
    assert assemble("").ok and assemble("; only a comment\n\n").ok and assemble("   \n").size == 0
    assert assemble('db "café"\nhlt').ok  # non-Latin-1 text becomes '?', never crashes


def test_case_insensitivity_of_labels_and_mnemonics():
    r = assemble("Start: JMP start\nSTART2: Hlt")
    assert r.ok and r.symbols["START"].name == "Start"


def test_ds_zero_and_label_on_org_line():
    r = assemble("here: org 200h\nds 0\nnop")
    assert r.ok and r.symbols["HERE"].value == 0x200 and r.image == {0x200: 0}


# ---------------------------------------------------------------- machine-level
def test_run_chunks_cannot_skip_a_breakpoint_inside_a_tight_loop():
    r = assemble("lp: inr a\ninr b\njnz lp\nhlt")
    m = Machine()
    m.load(r)
    m.breakpoints = {r.line_to_addr[2]}
    m.start("run")
    stops = 0
    for _ in range(3):
        why = m.run_chunk(100)
        assert why is Stop.BREAKPOINT and m.cpu.pc == r.line_to_addr[2]
        stops += 1
        m.start("run")
    assert stops == 3 and m.cpu.regs[7] == 3  # A was incremented once per pass
