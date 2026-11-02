"""CPU tests. The ALU is checked against a bit-by-bit full-adder model (a
different method from the one the CPU uses), BCD arithmetic is checked against
real decimal arithmetic, and timing against Intel's published T-state counts."""

import pytest

from studio8085.core.assembler import assemble
from studio8085.core.cpu import CPU, HALT, IllegalOpcode, IRQ_75
from studio8085.core.machine import Machine, Stop


def run(src, origin=0, setup=None, steps=100000, borrow=False):
    r = assemble(src, origin)
    assert r.ok, [(d.line, d.message) for d in r.diagnostics]
    m = Machine(ac_borrow_style=borrow)
    m.load(r)
    if setup:
        setup(m.cpu)
    for _ in range(steps):
        if m.cpu.step() == HALT:
            break
    return m.cpu


def adder(a, b, cin):
    """Add two bytes one bit at a time. Returns (result, carry_out_of_bit3, carry_out)."""
    carry, out, c3 = cin, 0, 0
    for i in range(8):
        x, y = (a >> i) & 1, (b >> i) & 1
        s = x ^ y ^ carry
        carry = (x & y) | (carry & (x ^ y))
        out |= s << i
        if i == 3:
            c3 = carry
    return out, c3, carry


def parity_even(v):
    return 1 if bin(v).count("1") % 2 == 0 else 0


def set_state(cpu, a, b, cy):
    cpu.regs[7], cpu.regs[0], cpu.cy = a, b, cy


# ------------------------------------------------------------- ALU
@pytest.mark.parametrize("mn,sub,use_carry", [
    ("ADD", 0, 0), ("ADC", 0, 1), ("SUB", 1, 0), ("SBB", 1, 1), ("CMP", 1, 0)])
def test_arithmetic_exhaustive(mn, sub, use_carry):
    cpu = CPU()
    cpu.mem.data[0] = {"ADD": 0x80, "ADC": 0x88, "SUB": 0x90, "SBB": 0x98, "CMP": 0xB8}[mn]
    cpu.mem.data[1] = 0x76
    for cy in (0, 1):
        for a in range(256):
            for b in range(256):
                cpu.pc, cpu.halted = 0, False
                set_state(cpu, a, b, cy)
                cpu.step()
                cin = cy if use_carry else 0
                if sub:
                    # the 8085 subtracts by adding the complement with an inverted carry-in
                    res, c3, c7 = adder(a, b ^ 0xFF, 1 - cin)
                    exp_cy = 1 - c7
                    exp_ac = c3
                else:
                    res, c3, c7 = adder(a, b, cin)
                    exp_cy, exp_ac = c7, c3
                got_a = cpu.regs[7]
                assert got_a == (a if mn == "CMP" else res), (mn, a, b, cy)
                assert (cpu.cy, cpu.ac) == (exp_cy, exp_ac), (mn, a, b, cy)
                assert (cpu.s, cpu.z, cpu.p) == (res >> 7, int(res == 0), parity_even(res)), (mn, a, b, cy)


@pytest.mark.parametrize("op,fn,ac", [(0xA0, lambda a, b: a & b, 1), (0xA8, lambda a, b: a ^ b, 0),
                                      (0xB0, lambda a, b: a | b, 0)])
def test_logic_ops_exhaustive(op, fn, ac):
    cpu = CPU()
    cpu.mem.data[0] = op
    for a in range(256):
        for b in range(0, 256, 3):
            cpu.pc = 0
            set_state(cpu, a, b, 1)
            cpu.step()
            r = fn(a, b)
            assert cpu.regs[7] == r and cpu.cy == 0 and cpu.ac == ac
            assert (cpu.s, cpu.z, cpu.p) == (r >> 7, int(r == 0), parity_even(r))


def test_borrow_style_ac_is_the_only_difference():
    hw, tb = CPU(), CPU(ac_borrow_style=True)
    for c in (hw, tb):
        c.mem.data[0] = 0x90
    diffs = 0
    for a in range(256):
        for b in range(256):
            for c in (hw, tb):
                c.pc = 0
                set_state(c, a, b, 0)
                c.step()
            assert (hw.regs[7], hw.cy, hw.s, hw.z, hw.p) == (tb.regs[7], tb.cy, tb.s, tb.z, tb.p)
            assert hw.ac != tb.ac  # exact opposites
            diffs += 1
    assert diffs == 65536


def test_inr_dcr_flags_and_carry_untouched():
    cpu = CPU()
    for reg in range(8):
        if reg == 6:
            continue
        for v in range(256):
            for op, delta in ((0x04 | reg << 3, 1), (0x05 | reg << 3, -1)):
                cpu.mem.data[0] = op
                cpu.pc, cpu.cy, cpu.regs[reg] = 0, 1, v
                cpu.step()
                r = (v + delta) & 255
                assert cpu.regs[reg] == r and cpu.cy == 1
                assert (cpu.s, cpu.z, cpu.p) == (r >> 7, int(r == 0), parity_even(r))
                if delta == 1:
                    assert cpu.ac == int((v & 15) + 1 > 15)
                else:
                    assert cpu.ac == int((v & 15) != 0)  # carry out of bit 3 of v + 0FFh


def test_inr_dcr_memory():
    cpu = run("lxi h,100h\nmvi m,0FFh\ninr m\ndcr m\nhlt")
    assert cpu.mem.data[0x100] == 0xFF


def to_bcd(n):
    return ((n // 10) << 4) | (n % 10)


def test_daa_gives_correct_decimal_sums_for_every_bcd_pair():
    cpu = CPU()
    cpu.mem.data[0:2] = bytes([0x88, 0x27])  # ADC B ; DAA
    for cin in (0, 1):
        for x in range(100):
            for y in range(100):
                cpu.pc = 0
                set_state(cpu, to_bcd(x), to_bcd(y), cin)
                cpu.step()
                cpu.step()
                total = x + y + cin
                assert cpu.regs[7] == to_bcd(total % 100), (x, y, cin)
                assert cpu.cy == int(total >= 100)
                assert cpu.z == int(cpu.regs[7] == 0)  # DAA must update Z (a bug in other simulators)
                assert cpu.p == parity_even(cpu.regs[7])


def test_daa_known_vectors():
    cpu = run("mvi a,99h\nadi 1\ndaa\nhlt")
    assert (cpu.regs[7], cpu.cy, cpu.z, cpu.p) == (0, 1, 1, 1)
    cpu = run("mvi a,9Bh\ndaa\nhlt")
    assert (cpu.regs[7], cpu.cy) == (0x01, 1)
    cpu = run("mvi a,15h\nadi 27h\ndaa\nhlt")
    assert cpu.regs[7] == 0x42 and cpu.cy == 0


# ------------------------------------------------------- data movement
def test_mov_mvi_lxi_and_memory_operand():
    cpu = run("lxi h,200h\nmvi m,5Ah\nmov a,m\nmov b,a\nmvi c,1\nlxi b,1234h\nhlt")
    assert cpu.regs[7] == 0x5A and cpu.mem.data[0x200] == 0x5A
    assert (cpu.regs[0], cpu.regs[1]) == (0x12, 0x34)


def test_load_store_and_wraparound_at_top_of_memory():
    cpu = run("lxi h,0AA55h\nshld 0FFFFh\nlhld 0FFFFh\nlxi h,0\nlhld 0FFFFh\nhlt")
    assert cpu.mem.data[0xFFFF] == 0x55 and cpu.mem.data[0] == 0xAA
    assert cpu.hl == 0xAA55
    assert cpu.io[0] == 0  # nothing leaks into I/O space


def test_ldax_stax_xchg_and_pairs():
    cpu = run("lxi b,300h\nlxi d,301h\nmvi a,7\nstax b\nmvi a,9\nstax d\nldax b\nmov h,a\nldax d\n"
              "mov l,a\nxchg\nhlt")
    assert cpu.mem.data[0x300:0x302] == bytes([7, 9]) and cpu.hl == 0x0301
    assert (cpu.regs[2], cpu.regs[3]) == (7, 9)


def test_inx_dcx_dad_wrap_and_carry():
    cpu = run("lxi h,0FFFFh\ninx h\nlxi b,0\ndcx b\nlxi d,1\nlxi h,0FFFFh\ndad d\nhlt")
    assert cpu.hl == 0 and cpu.cy == 1 and cpu.get_rp(0) == 0xFFFF
    cpu = run("lxi h,1\nlxi d,2\nstc\ndad d\nhlt")
    assert cpu.hl == 3 and cpu.cy == 0


def test_rotates():
    cpu = run("mvi a,81h\nrlc\nhlt")
    assert (cpu.regs[7], cpu.cy) == (0x03, 1)
    cpu = run("mvi a,81h\nrrc\nhlt")
    assert (cpu.regs[7], cpu.cy) == (0xC0, 1)
    cpu = run("mvi a,81h\nstc\nral\nhlt")
    assert (cpu.regs[7], cpu.cy) == (0x03, 1)
    cpu = run("mvi a,81h\nstc\nrar\nhlt")
    assert (cpu.regs[7], cpu.cy) == (0xC0, 1)
    cpu = run("mvi a,80h\nstc\nral\nhlt")
    assert cpu.regs[7] == 1 and cpu.cy == 1


def test_cma_stc_cmc_leave_other_flags():
    cpu = run("mvi a,0F0h\nora a\ncma\nstc\ncmc\nhlt")
    assert cpu.regs[7] == 0x0F and cpu.cy == 0 and cpu.s == 1  # S from the ORA, untouched since


# ------------------------------------------------------------ stack
def test_push_pop_psw_round_trips_all_flags():
    cpu = run("mvi a,0A5h\nstc\npush psw\nxra a\npop psw\nhlt")
    assert cpu.regs[7] == 0xA5 and cpu.cy == 1
    cpu = CPU()
    cpu.regs[7] = 0x12
    for f in range(256):
        cpu.f = f
        saved = cpu.f
        cpu._push16((cpu.regs[7] << 8) | cpu.f)
        cpu.f = 0
        v = cpu._pop16()
        cpu.f = v & 255
        assert cpu.f == saved
    assert (cpu.f & 0x02) == 2 and (cpu.f & 0x28) == 0  # bit 1 always 1, bits 3 and 5 always 0


def test_stack_pointer_wraps_through_zero_like_the_real_chip():
    cpu = run("lxi sp,0\nlxi b,0BEEFh\npush b\nlxi b,0\npop b\nhlt")
    assert cpu.get_rp(0) == 0xBEEF and cpu.sp == 0
    # popping with the power-on SP (FFFFh) reads address FFFFh, then wraps to 0
    def setup(c):
        c.mem.data[0xFFFF], c.mem.data[0] = 0x42, 0x77
    cpu = run("pop b\nhlt", 0x100, setup)
    assert (cpu.regs[0], cpu.regs[1], cpu.sp) == (0x77, 0x42, 1)


def test_xthl_sphl_pchl():
    cpu = run("lxi sp,500h\nlxi h,1111h\npush h\nlxi h,2222h\nxthl\nhlt")
    assert cpu.hl == 0x1111 and cpu.mem.data[0x4FE:0x500] == bytes([0x22, 0x22])
    cpu = run("lxi h,700h\nsphl\nhlt")
    assert cpu.sp == 0x700
    cpu = run("lxi h,target\npchl\nhlt\ntarget: mvi a,9\nhlt")
    assert cpu.regs[7] == 9


# ---------------------------------------------------- control flow
def test_all_conditional_jumps_calls_and_returns():
    # (flag setup, mnemonic suffix, taken?)
    cases = [("xra a", "z", 1), ("xra a", "nz", 0), ("mvi a,1\nora a", "nz", 1), ("stc", "c", 1),
             ("stc", "nc", 0), ("stc\ncmc", "nc", 1), ("mvi a,3\nora a", "pe", 1), ("mvi a,1\nora a", "po", 1),
             ("mvi a,1\nora a", "pe", 0), ("mvi a,80h\nora a", "m", 1), ("mvi a,1\nora a", "p", 1),
             ("mvi a,1\nora a", "m", 0)]
    for setup, cc, taken in cases:
        for kind in ("j", "c", "r"):
            if kind == "j":
                src = f"{setup}\nmvi b,0\nj{cc} hit\nhlt\nhit: mvi b,1\nhlt"
            elif kind == "c":
                src = f"{setup}\nmvi b,0\nc{cc} fn\nhlt\nfn: mvi b,1\nret"
            else:
                src = f"{setup}\nmvi b,0\nlxi h,back\npush h\nr{cc}\nmvi b,2\nhlt\nback: mvi b,1\nhlt"
            cpu = run(src)
            want = (1 if taken else 0) if kind != "r" else (1 if taken else 2)
            assert cpu.regs[0] == want, (kind, cc, setup, cpu.regs[0])


def test_call_and_return_use_the_stack():
    cpu = run("lxi sp,1000h\ncall f\nhlt\nf: mvi a,5\nret")
    assert cpu.regs[7] == 5 and cpu.sp == 0x1000 and cpu.mem.data[0xFFE:0x1000] == bytes([6, 0])


def test_rst_calls_vector_and_returns():
    src = "org 0\njmp main\norg 8\nrst1: mvi a,0AAh\nret\norg 100h\nmain: rst 1\nmvi b,1\nhlt"
    r = assemble(src)
    assert r.ok, r.diagnostics
    m = Machine()
    m.load(r)
    m.cpu.pc = 0
    assert m.run_to_end() is Stop.HALT
    assert m.cpu.regs[7] == 0xAA and m.cpu.regs[0] == 1


def test_in_out_ports_and_hook():
    seen = []
    def setup(c):
        c.io[0x10] = 0x5C
        c.on_out = lambda p, v: seen.append((p, v))
    cpu = run("in 10h\ncma\nout 20h\nhlt", 0, setup)
    assert cpu.io[0x20] == 0xA3 and seen == [(0x20, 0xA3)]


def test_illegal_opcode_raises_and_leaves_pc_at_it():
    cpu = CPU()
    cpu.mem.data[0x10] = 0x08  # undocumented on the 8085
    cpu.pc = 0x10
    with pytest.raises(IllegalOpcode) as e:
        cpu.step()
    assert cpu.pc == 0x10 and e.value.opcode == 8


# ------------------------------------------------------- interrupts
INT_PROG = """
org 0
jmp main
org 24h
trap:   mvi d,1
        ret
org 2Ch
r55:    mvi e,1
        ret
org 34h
r65:    mvi h,1
        ret
org 3Ch
r75:    mvi l,1
        ret
org 100h
main:   lxi sp,0FFFFh
        {setup}
wait:   nop
        nop
        hlt
"""


def machine_with(setup):
    r = assemble(INT_PROG.format(setup=setup))
    assert r.ok, r.diagnostics
    m = Machine()
    m.load(r)
    return m


def test_interrupts_are_masked_after_reset_and_need_ei():
    m = machine_with("nop")
    m.cpu.raise_interrupt("RST7.5")
    m.cpu.raise_interrupt("RST5.5")
    assert m.run_to_end() is Stop.HALT
    assert (m.cpu.regs[5], m.cpu.regs[3]) == (0, 0)  # masked and IE=0 -> nothing happened


def test_unmask_with_sim_then_ei_delivers_all_in_priority_order():
    m = machine_with("mvi a,08h\nsim\nei")  # MSE=1, all masks cleared
    for name in ("RST5.5", "RST6.5", "RST7.5"):
        m.cpu.raise_interrupt(name)
    order = []
    cpu = m.cpu
    cpu.pc = 0x100
    for _ in range(200):
        before = cpu.irq_taken
        if cpu.step() == HALT:
            break
        if cpu.irq_taken != before:
            order.append(hex(cpu.pc))
            cpu.ie = True  # the handlers return with RET; re-enable like a real ISR would (EI; RET)
    assert order == ["0x3c", "0x34", "0x2c"]


def test_ei_takes_effect_only_after_the_next_instruction():
    m = machine_with("mvi a,08h\nsim\nei\nmvi b,0EEh")
    m.cpu.raise_interrupt("RST7.5")
    cpu = m.cpu
    cpu.pc = 0x100
    seq = []
    while cpu.step() == 0 and len(seq) < 50:
        seq.append((cpu.pc, cpu.irq_taken))
        if cpu.irq_taken:
            break
    # the interrupt must come after MVI B (the instruction following EI) has executed
    assert cpu.regs[0] == 0xEE and cpu.pc == 0x3C


def test_trap_ignores_masks_and_ie():
    m = machine_with("nop")
    m.cpu.raise_interrupt("TRAP")
    m.run_to_end()
    assert m.cpu.regs[2] == 1  # D set by the TRAP handler


def test_interrupt_wakes_halted_cpu():
    m = machine_with("mvi a,08h\nsim\nei")
    assert m.run_to_end() is Stop.HALT and m.cpu.halted
    m.cpu.raise_interrupt("RST6.5")
    assert m.run_to_end() is Stop.HALT
    assert m.cpu.regs[4] == 1  # H set by the RST 6.5 handler, then back to HLT


def test_rim_and_sim_bits():
    cpu = run("mvi a,09h\nsim\nrim\nhlt")  # MSE=1, mask 5.5 only
    assert cpu.regs[7] & 0b111 == 0b001 and not cpu.m65 and not cpu.m75 and cpu.m55
    cpu = run("mvi a,40h\nsim\nhlt")  # SOE only: SOD bit comes from bit 7
    assert cpu.sod == 0
    cpu = run("mvi a,0C0h\nsim\nhlt")
    assert cpu.sod == 1
    cpu = CPU()
    cpu.raise_interrupt("RST7.5")
    cpu.mem.data[0] = 0x20
    cpu.step()
    assert cpu.regs[7] & 0x40  # pending 7.5 latch visible through RIM
    cpu.mem.data[1], cpu.regs[7] = 0x30, 0x10  # SIM with R7.5 reset bit
    cpu.step()
    assert not cpu.pending & IRQ_75


# ------------------------------------------------------------ timing
@pytest.mark.parametrize("src,ts", [
    ("nop", 4), ("mov a,b", 4), ("mov a,m", 7), ("mov m,a", 7), ("mvi a,1", 7), ("mvi m,1", 10),
    ("lxi h,0", 10), ("lda 0", 13), ("sta 0", 13), ("lhld 0", 16), ("shld 0", 16), ("ldax b", 7),
    ("xchg", 4), ("xthl", 16), ("sphl", 6), ("pchl", 6), ("push b", 12), ("pop b", 10),
    ("add b", 4), ("add m", 7), ("adi 1", 7), ("inr b", 4), ("inr m", 10), ("inx h", 6), ("dcx h", 6),
    ("dad b", 10), ("rlc", 4), ("daa", 4), ("jmp 0", 10), ("call 100h", 18), ("ret", 10),
    ("rst 0", 12), ("in 0", 10), ("out 0", 10), ("ei", 4), ("di", 4), ("rim", 4), ("sim", 4), ("hlt", 5),
])
def test_t_states_match_the_intel_table(src, ts):
    r = assemble(src, 0x200)
    m = Machine()
    m.load(r)
    m.cpu.sp = 0x8000
    m.cpu.step()
    assert m.cpu.tstates == ts


@pytest.mark.parametrize("src,taken,not_taken", [("jnz 0", 10, 7), ("cnz 0", 18, 9), ("rnz", 12, 6)])
def test_conditional_timing_depends_on_taken(src, taken, not_taken):
    for z, want in ((0, taken), (1, not_taken)):
        m = Machine()
        m.load(assemble(src, 0x200))
        m.cpu.z, m.cpu.sp = z, 0x8000
        m.cpu.step()
        assert m.cpu.tstates == want


def test_classic_delay_loop_timing():
    # MVI B,n (7) + n x (DCR B 4 + JNZ 10) - 3 for the final not-taken JNZ
    cpu = run("mvi b,100\nlp: dcr b\njnz lp\nhlt")
    assert cpu.tstates == 7 + 100 * 14 - 3 + 5


def test_memory_heat_tracking():
    cpu = run("lxi h,300h\nmvi m,9\nmov a,m\nhlt")
    mem = cpu.mem
    assert 0x300 in mem.hot and mem.wr[0x300] == 1 and mem.rd[0x300] == 1
    mem.set_tracking(False)
    mem.write(0x400, 1)
    assert mem.wr[0x400] == 0 and mem.data[0x400] == 1
