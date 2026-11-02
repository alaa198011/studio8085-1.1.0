"""Keeping memory: data typed into memory, or left by an earlier run, survives assembling, running and restarting."""

from studio8085.core.assembler import assemble
from studio8085.core.machine import Machine, Stop

PROGRAM = """
        lda   2000h
        adi   1
        sta   2001h
        hlt
"""


def asm(text):
    r = assemble(text, 0)
    assert r.ok and not r.warnings, [(d.line, d.message) for d in r.diagnostics]
    return r


def run(m):
    assert m.run_to_end() is Stop.HALT


def test_default_load_still_wipes_memory():
    m = Machine()
    m.cpu.mem.data[0x2000] = 0x41
    m.load(asm(PROGRAM))
    assert m.cpu.mem.data[0x2000] == 0


def test_typed_data_survives_loading_and_running():
    """The reported problem: values typed into memory vanished when the program was run."""
    m = Machine()
    m.cpu.mem.data[0x2000] = 0x41  # typed before assembling
    m.load(asm(PROGRAM), keep_memory=True)
    assert m.cpu.mem.data[0x2000] == 0x41
    run(m)
    assert (m.cpu.regs[7], m.cpu.mem.data[0x2001]) == (0x42, 0x42)
    # ... and it still survives a restart (re-assemble + reload) after the run
    m.load(asm(PROGRAM), keep_memory=True)
    assert m.cpu.mem.data[0x2000] == 0x41 and m.cpu.mem.data[0x2001] == 0x42  # the result is kept too
    assert m.cpu.pc == 0 and m.cpu.regs[7] == 0  # but the CPU is reset
    run(m)
    assert m.cpu.mem.data[0x2001] == 0x42


def test_data_changed_after_assembling_is_kept_by_the_next_run():
    m = Machine()
    m.load(asm(PROGRAM), keep_memory=True)
    m.cpu.mem.data[0x2000] = 0x10  # typed after assembling
    run(m)
    assert m.cpu.mem.data[0x2001] == 0x11
    m.cpu.mem.data[0x2000] = 0x20
    m.load(asm(PROGRAM), keep_memory=True)
    run(m)
    assert m.cpu.mem.data[0x2001] == 0x21


def test_a_shorter_program_leaves_no_stale_code_behind():
    long = asm("\tmvi a,1\n\tmvi b,2\n\tmvi c,3\n\tmvi d,4\n\thlt\n")  # 9 bytes
    short = asm("\tmvi a,9\n\thlt\n")
    m = Machine()
    m.load(long, keep_memory=True)
    m.load(short, keep_memory=True)
    assert bytes(m.cpu.mem.data[:9]) == bytes([0x3E, 9, 0x76, 0, 0, 0, 0, 0, 0])
    # the default mode agrees on the result
    m2 = Machine()
    m2.load(long)
    m2.load(short)
    assert bytes(m2.cpu.mem.data[:9]) == bytes(m.cpu.mem.data[:9])


def test_bytes_the_user_changed_inside_the_old_program_are_not_removed():
    m = Machine()
    m.load(asm("\tmvi a,1\n\tmvi b,2\n\tmvi c,3\n\thlt\n"), keep_memory=True)
    m.cpu.mem.data[5] = 0x99  # the immediate of "mvi c": typed by the student
    m.load(asm("\tmvi a,9\n\thlt\n"), keep_memory=True)  # the new program ends at address 2
    assert m.cpu.mem.data[5] == 0x99  # kept
    assert m.cpu.mem.data[3] == 0 and m.cpu.mem.data[4] == 0  # unchanged old bytes are gone


def test_plain_ds_keeps_its_contents_but_initialised_data_is_reset():
    text = """
        lda   keep
        adi   1
        sta   keep           ; plain DS: storage that stays between runs
        lda   count
        adi   1
        sta   count          ; DB: initialised data, set again at every assembly
        lda   zeroed
        adi   1
        sta   zeroed         ; DS with a fill value: initialised again too
        hlt
keep:   ds    1
count:  db    5
zeroed: ds    1,0
"""
    r = asm(text)
    keep, count, zeroed = (r.symbols[n.upper()].value for n in ("keep", "count", "zeroed"))
    assert r.uninitialized == [(keep, 1)]  # only the plain DS is "uninitialised"
    m = Machine()
    m.load(r, keep_memory=True)
    run(m)
    assert [m.cpu.mem.data[a] for a in (keep, count, zeroed)] == [1, 6, 1]
    m.load(asm(text), keep_memory=True)
    assert [m.cpu.mem.data[a] for a in (keep, count, zeroed)] == [1, 5, 0]  # keep stays; the others restart
    run(m)
    assert [m.cpu.mem.data[a] for a in (keep, count, zeroed)] == [2, 6, 1]  # a second run continues from keep
    # with memory wiped (the old behaviour) every run starts from scratch
    m.load(asm(text))
    run(m)
    assert [m.cpu.mem.data[a] for a in (keep, count, zeroed)] == [1, 6, 1]


def test_self_modifying_code_is_restored_when_the_program_is_reloaded():
    text = "\tmvi a,1\n\tmvi b,7\n\thlt\n"
    m = Machine()
    m.load(asm(text), keep_memory=True)
    m.cpu.mem.data[3] = 0x55  # the program "modified itself"
    m.load(asm(text), keep_memory=True)
    assert m.cpu.mem.data[3] == 7


def test_uninitialised_ranges_are_recorded_exactly():
    assert asm("\thlt\nbuf:\tds 4\n").uninitialized == [(1, 4)]
    assert asm("\thlt\nbuf:\tds 4,0FFh\n").uninitialized == []
    assert asm("\thlt\n\tds 0\n").uninitialized == []
    two = asm("\thlt\nfirst:\tds 2\n\torg 100h\nsecond:\tds 3\n")
    assert two.uninitialized == [(1, 2), (0x100, 3)]


def test_unload_can_keep_typed_data_while_dropping_the_old_program():
    m = Machine()
    m.load(asm(PROGRAM), keep_memory=True)
    m.cpu.mem.data[0x2000] = 0x41
    m.unload(keep_memory=True)
    assert m.program is None and m.cpu.mem.data[0x2000] == 0x41
    assert bytes(m.cpu.mem.data[:8]) == bytes(8)  # the old code is gone
    m.cpu.mem.data[0x2001] = 7
    m.unload()  # the default wipes everything
    assert m.cpu.mem.data[0x2000] == 0 and m.cpu.mem.data[0x2001] == 0


def test_loading_resets_the_heat_statistics_even_when_memory_is_kept():
    m = Machine()
    m.load(asm(PROGRAM), keep_memory=True)
    run(m)
    assert any(m.cpu.mem.wr)
    m.load(asm(PROGRAM), keep_memory=True)
    assert not any(m.cpu.mem.wr) and not any(m.cpu.mem.rd)
