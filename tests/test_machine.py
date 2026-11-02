import pytest

from studio8085.core.assembler import assemble
from studio8085.core.machine import Machine, Stop

PROG = """
        lxi sp,8000h
        call outer          ; line 3
        mvi b,1             ; line 4
        hlt                 ; line 5
outer:  mvi a,1             ; line 6
        call inner          ; line 7
        mvi a,2             ; line 8
        ret                 ; line 9
inner:  cpi 5               ; CPI must NOT be mistaken for a call (a bug in other simulators)
        jz skip
        rz                  ; conditional return
        nop
skip:   ret
"""


def load(src=PROG, origin=0):
    r = assemble(src, origin)
    assert r.ok, r.diagnostics
    m = Machine()
    m.load(r)
    return m, r


def test_step_into_follows_calls():
    m, r = load()
    m.step_into()
    m.step_into()
    assert m.cpu.pc == r.symbols["OUTER"].value and m.current_line() == 6


def test_step_over_runs_the_whole_subroutine():
    m, r = load()
    m.step_into()  # lxi sp
    assert m.step_over() is Stop.STEP
    assert m.current_line() == 4 and m.cpu.regs[7] == 2  # subroutine fully executed


def test_step_over_a_non_call_is_a_single_step_even_for_cpi():
    m, r = load()
    m.cpu.pc = r.symbols["INNER"].value
    m.cpu.regs[7] = 0
    assert m.step_over() is Stop.STEP
    assert m.cpu.pc == r.symbols["INNER"].value + 2  # advanced one instruction only


def test_step_out_returns_to_caller_including_conditional_return():
    m, r = load()
    m.cpu.pc = r.symbols["INNER"].value
    m.cpu.sp = 0x7FFE
    m.cpu.mem.data[0x7FFE:0x8000] = bytes([0x30, 0x00])
    m.cpu.regs[7] = 9  # not 5 -> falls to RZ (not taken), NOP, then RET at 'skip'
    assert m.step_out() is Stop.STEP
    assert m.cpu.pc == 0x0030

    m, r = load()
    m.cpu.pc = r.symbols["INNER"].value
    m.cpu.sp = 0x7FFE
    m.cpu.mem.data[0x7FFE:0x8000] = bytes([0x30, 0x00])
    m.cpu.regs[7] = 5  # equal -> JZ skip -> RET
    assert m.step_out() is Stop.STEP and m.cpu.pc == 0x0030


def test_step_out_skips_nested_calls():
    m, r = load()
    m.step_into()
    m.step_into()  # at 'outer'
    assert m.step_out() is Stop.STEP
    assert m.current_line() == 4 and m.cpu.regs[7] == 2


def test_breakpoints_stop_before_the_instruction_and_resume_cleanly():
    m, r = load()
    m.breakpoints = {r.line_to_addr[8], r.line_to_addr[4]}
    m.start("run")
    assert m.run_chunk(1000) is Stop.BREAKPOINT and m.current_line() == 8
    assert m.cpu.regs[7] == 1  # not yet executed
    m.start("run")  # resuming from a breakpoint must execute that instruction
    assert m.run_chunk(1000) is Stop.BREAKPOINT and m.current_line() == 4
    m.start("run")
    assert m.run_chunk(1000) is Stop.HALT


def test_run_chunks_resume_where_they_left_off():
    m, _ = load("mvi b,200\nlp: dcr b\njnz lp\nhlt")
    m.start("run")
    chunks = 0
    while (why := m.run_chunk(50)) is None:
        chunks += 1
    assert why is Stop.HALT and chunks > 3 and m.cpu.regs[0] == 0


def test_idle_loop_detection_and_override():
    m, _ = load("here: jmp here")
    assert m.run_to_end() is Stop.LOOP
    assert "jumps to itself" in m.stop_reason_text(Stop.LOOP)
    m.start("run")  # asking again keeps spinning (so interrupts can be demonstrated)
    assert m.run_chunk(500) is None
    m, _ = load("ei\nhere: jmp here")
    m.start("run")
    assert m.run_chunk(500) is None  # interrupts enabled -> waiting for one is legitimate


def test_instruction_limit():
    m, _ = load("a1: nop\njmp a1")
    m.max_instructions = 1000
    assert m.run_to_end() is Stop.LIMIT and m.cpu.icount == 1000


def test_illegal_opcode_stops_with_message():
    m, _ = load("nop")
    m.cpu.mem.data[1] = 0xCB
    assert m.run_to_end() is Stop.ILLEGAL
    assert "CBh" in m.last_error and m.cpu.pc == 1


def test_step_through_interrupt_counts_as_a_call_for_step_out():
    src = "org 0\njmp go\norg 3Ch\nisr: nop\nnop\nei\nret\norg 100h\ngo: lxi sp,9000h\nmvi a,0Bh\nsim\nei\nnop\nnop\nhlt"
    r = assemble(src)
    m = Machine()
    m.load(r)
    m.cpu.pc = 0
    m.run_to_end()
    resume_at = m.cpu.pc  # the HLT has executed; PC points past it
    m.cpu.raise_interrupt("RST7.5")
    m.step_into()
    assert m.cpu.pc == 0x3C
    assert m.step_out() is Stop.STEP and m.cpu.pc == resume_at


def test_symbol_lookup_for_addresses():
    m, r = load()
    inner = r.symbols["INNER"].value
    assert m.symbol_for(inner) == "inner" and m.symbol_for(inner + 2) == "inner+2"
    assert m.symbol_for(0xF000) is None


def test_reload_keeps_io_inputs_but_resets_cpu():
    m, r = load("in 5\nhlt")
    m.cpu.io[5] = 0x77
    m.run_to_end()
    m.reset_cpu()
    assert m.cpu.pc == r.entry and m.cpu.icount == 0 and m.cpu.io[5] == 0x77
    m.run_to_end()
    assert m.cpu.regs[7] == 0x77


def test_out_log_records_port_writes():
    m, _ = load("mvi a,1\nout 7\nmvi a,2\nout 8\nhlt")
    m.run_to_end()
    assert [(p, v) for _, p, v in m.out_log] == [(7, 1), (8, 2)]
