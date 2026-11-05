"""Phase 2: the visualization model (no Qt). It must observe the existing engine, never change it."""

import dataclasses

import pytest

from studio8085.core.assembler import assemble
from studio8085.core.machine import Machine, Stop
from studio8085.core.peripherals import TrainerKit
from studio8085.core.visual import (FAMILIES, KitView, StepHistory, StepRecorder, capture_state, decode, family_of,
                                    kit_view)


def machine(src: str) -> Machine:
    r = assemble(src)
    assert not r.errors, r.errors
    m = Machine()
    m.load(r)
    return m


def step(m: Machine, rec: StepRecorder):
    rec.begin("into")
    m.step_into()
    return rec.end()


PROGRAM = """
        ORG 0
        MVI A,3FH
        MVI B,01H
        ADD B
        STA 2000H
        LDA 2000H
        LXI H,3000H
        MOV M,A
        MOV C,M
        PUSH B
        POP D
        CALL SUB1
        JNZ DONE
        NOP
DONE:   HLT
SUB1:   INR C
        RET
"""


def run_records(src=PROGRAM, n=40):
    m = machine(src)
    rec = StepRecorder(m)
    out = []
    for _ in range(n):
        r = step(m, rec)
        out.append(r)
        if m.cpu.halted:
            break
    return m, rec, out


def test_pre_and_post_state_are_immutable_snapshots():
    m = machine("MVI A,05H\nHLT\n")
    rec = StepRecorder(m)
    r = step(m, rec)
    assert r.pre.reg("A") == 0 and r.post.reg("A") == 5 and m.cpu.a == 5
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.pre.pc = 3
    m.cpu.regs[7] = 99  # later CPU changes never alter an old record
    assert r.post.reg("A") == 5


def test_register_and_flag_changes_come_from_the_diff():
    m = machine("MVI A,3FH\nMVI B,01H\nADD B\nHLT\n")
    rec = StepRecorder(m)
    step(m, rec), step(m, rec)
    r = step(m, rec)
    assert r.reg_changes == (("A", 0x3F, 0x40),)
    assert ("AC", 0, 1) in r.flag_changes
    assert r.pc_change == (4, 5) and r.sp_change is None
    assert any("AC changed" in t for t in r.flag_why)
    assert r.family == "Arithmetic" and r.detailed and r.kind == "instr"
    assert r.flows and all(f.label for f in r.flows)
    assert any(f.src == "ALU" and f.dst == "A" and f.observed for f in r.flows)
    assert "ALU" in r.involved and "FLAGS" in r.changed_nodes


def test_memory_accesses_are_observed_from_the_access_counters():
    _, _, recs = run_records()
    by = {r.text: r for r in recs if r}
    by.update({r.text.split()[0]: r for r in recs if r})
    sta = by["STA 2000h"]
    assert [(a.kind, a.addr, a.value, a.observed) for a in sta.mem_accesses] == [("W", 0x2000, 0x3F + 1, True)]
    lda = by["LDA 2000h"]
    assert [(a.kind, a.addr) for a in lda.mem_accesses] == [("R", 0x2000)]
    movm = by["MOV M,A"]
    assert [(a.kind, a.addr) for a in movm.mem_accesses] == [("W", 0x3000)]
    # a load that does not touch memory reports no access at all
    assert by["MVI B,01h"].mem_accesses == ()


def test_stack_and_control_flow_explanations():
    m, _, recs = run_records()
    by = {r.text: r for r in recs if r}
    by.update({r.text.split()[0]: r for r in recs if r})
    push = by["PUSH B"]
    assert push.sp_change == (0xFFFF, 0xFFFD)
    assert sorted(a.addr for a in push.mem_accesses if a.kind == "W") == [0xFFFD, 0xFFFE]
    pop = by["POP D"]
    assert pop.sp_change == (0xFFFD, 0xFFFF) and ("D", 0, 1) in pop.reg_changes
    call = by["CALL"]
    assert call.family == "Control flow" and call.sp_change[1] == call.sp_change[0] - 2
    assert any("pushed" in f.label for f in call.flows)
    ret = by["RET"]
    assert ret.sp_change[1] == ret.sp_change[0] + 2 and ret.pc_change is not None
    jnz = by["JNZ"]
    assert jnz.taken is True and any("WAS taken" in w for w in jnz.why)


def test_not_taken_conditional_jump():
    m = machine("MVI A,00H\nORA A\nJNZ SKIP\nNOP\nSKIP: HLT\n")
    rec = StepRecorder(m)
    step(m, rec), step(m, rec)
    r = step(m, rec)
    assert r.taken is False and not any(f.src == "IR" and f.dst == "PC" for f in r.flows)
    assert any("NOT taken" in w for w in r.why)


def test_in_out_events_and_the_phase1_chain():
    m = machine("IN 00H\nOUT 01H\nHLT\n")
    kit = TrainerKit(m.cpu, enabled=True)
    kit.set_switches(0xA5)
    rec = StepRecorder(m)
    r1 = step(m, rec)
    assert r1.family == "I/O" and r1.reg_changes == (("A", 0, 0xA5),)
    assert [(e.direction, e.port, e.value) for e in r1.port_events] == [("IN", 0, 0xA5)]
    assert [(f.src, f.dst) for f in r1.flows if f.phase > 0] == [("IR", "PORT_IN"), ("PORT_IN", "A")]
    r2 = step(m, rec)
    assert [(e.direction, e.port, e.value, e.observed) for e in r2.port_events] == [("OUT", 1, 0xA5, True)]
    assert kit.leds.value == 0xA5  # the kit's own latch, not a copy
    assert kit_view(kit).leds == 0xA5 and kit_view(kit).switches == 0xA5
    assert r2.flag_changes == () and r2.reg_changes == ()


def test_generic_instruction_has_no_misleading_animation():
    m = machine("LXI H,1234H\nDAD H\nXCHG\nHLT\n")
    rec = StepRecorder(m)
    step(m, rec)
    dad = step(m, rec)
    assert dad.mnemonic == "DAD" and not dad.detailed and dad.flows == () and dad.conceptual_steps == ()
    assert dad.reg_changes  # but the exact before/after is there
    assert family_of("DAD") == ("Arithmetic", False)


def test_listed_families_are_the_spec_families():
    assert FAMILIES["Data transfer"] == {"MOV", "MVI", "LXI", "LDA", "STA", "LHLD", "SHLD"}
    assert FAMILIES["Arithmetic"] == {"ADD", "ADC", "SUB", "SBB", "INR", "DCR", "INX", "DCX"}
    assert FAMILIES["Logical"] == {"ANA", "ORA", "XRA", "CMP"}
    assert {"JMP", "CALL", "RET", "JNZ", "JC"} <= FAMILIES["Control flow"]
    assert FAMILIES["Stack"] == {"PUSH", "POP"} and FAMILIES["I/O"] == {"IN", "OUT"}
    assert FAMILIES["Other"] == {"NOP", "HLT"}


def test_step_over_and_run_make_a_summary_record():
    m = machine(PROGRAM)
    rec = StepRecorder(m)
    rec.begin("run")
    assert m.run_to_end() is Stop.HALT
    r = rec.end()
    assert r.kind == "multi" and r.n_instr > 5 and not r.detailed and r.flows == () and r.mem_diff == ()
    assert r.post.icount == m.cpu.icount


def test_halted_step_records_nothing_executed():
    m = machine("HLT\n")
    rec = StepRecorder(m)
    step(m, rec)
    r = step(m, rec)
    assert r.kind == "none" and r.n_instr == 0


def test_recording_does_not_change_cpu_behaviour():
    """The same program, with and without the recorder: identical registers, flags, memory, T-states, OUT log."""
    def final(with_rec: bool):
        m = machine(PROGRAM)
        rec = StepRecorder(m)
        rec.enabled = with_rec
        for _ in range(60):
            rec.begin("into")
            m.step_into()
            rec.end()
            if m.cpu.halted:
                break
        c = m.cpu
        return (tuple(c.regs), c.sp, c.pc, c.f, c.icount, c.tstates, bytes(c.mem.data), tuple(m.out_log))
    assert final(True) == final(False)


def test_cpu_core_files_are_untouched_by_phase2():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run(["git", "diff", "--stat", "bd82989", "--", "src/studio8085/core/cpu.py",
                        "src/studio8085/core/machine.py", "src/studio8085/core/assembler.py",
                        "src/studio8085/core/opcodes.py", "src/studio8085/core/peripherals.py"],
                       cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("git history not available")
    assert r.stdout.strip() == ""


def test_breakpoint_stops_and_is_recorded_as_normal():
    m = machine("NOP\nNOP\nMVI A,01H\nHLT\n")
    m.breakpoints.add(2)
    rec = StepRecorder(m)
    rec.begin("run")
    m.start("run")
    why = m.run_chunk(1000)
    r = rec.end()
    assert why is Stop.BREAKPOINT and m.cpu.pc == 2 and r.post.pc == 2 and r.n_instr == 2


def test_history_is_bounded_and_reset_clears_it():
    m = machine("L: NOP\nJMP L\n")
    rec = StepRecorder(m, history_limit=5)
    for _ in range(20):
        step(m, rec)
    assert len(rec.history) == 5 and rec.history.latest.seq == 20
    rec.reset()
    assert len(rec.history) == 0 and rec.history.latest is None


def test_reload_and_reset_start_clean():
    m = machine("MVI A,07H\nHLT\n")
    rec = StepRecorder(m)
    step(m, rec)
    m.reset_cpu()
    rec.reset()
    r = step(m, rec)
    assert r.pre.reg("A") == 0 and r.post.reg("A") == 7


def test_disabled_recorder_records_nothing():
    m = machine("NOP\nHLT\n")
    rec = StepRecorder(m)
    rec.enabled = False
    rec.begin("into")
    m.step_into()
    assert rec.end() is None and len(rec.history) == 0


def test_decode_matches_disassembler_and_operands():
    m = machine("LXI SP,1234H\nHLT\n")
    d = decode(m.cpu.mem.data, 0)
    assert (d.mnemonic, d.operands, d.imm, d.length) == ("LXI", ("SP", "#16"), 0x1234, 3)
    assert capture_state(m.cpu).sp == 0xFFFF
    assert StepHistory().latest is None and KitView().enabled is False
