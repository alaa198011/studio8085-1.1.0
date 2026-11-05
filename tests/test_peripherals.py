"""Phase 1 peripheral layer (core, no Qt): switches, LEDs, seven-segment display and the I/O bus."""

import pytest

from studio8085.core.assembler import assemble
from studio8085.core.cpu import CPU
from studio8085.core.machine import Machine, Stop
from studio8085.core.peripherals import (DEFAULT_SEGMENT_ORDER, HEX, HEX_DIGITS, HEX_GLYPHS, RAW, IN, OUT,
                                         LedBank, OutputLatch, Peripheral, PeripheralBus,
                                         PeripheralConfigError, PortConflictError, PortMap, SevenSegment,
                                         SwitchBank, TrainerKit)

EXPERIMENT_1 = "START: IN 00H\n       OUT 01H\n       HLT\n"


def machine(src, kit=True, ports=PortMap()):
    r = assemble(src, 0)
    assert r.ok, [(d.line, d.message) for d in r.diagnostics]
    m = Machine()
    m.load(r)
    k = TrainerKit(m.cpu, ports, enabled=kit)
    return m, k


def state(m):
    c = m.cpu
    return (tuple(c.regs), c.sp, c.pc, c.f, c.icount, c.tstates, bytes(c.io), bytes(c.mem.data),
            tuple(m.out_log), m.out_count, c.halted, [(r.text, r.regs, r.events) for r in m.trace])


# ------------------------------------------------------------------ bit mapping
@pytest.mark.parametrize("value", [0x00, 0x01, 0x80, 0xA5, 0x5A, 0xFF])
def test_in_reads_the_switch_byte_into_a_bit_for_bit(value):
    m, k = machine(EXPERIMENT_1)
    k.set_switches(value)
    m.step_into()
    assert m.cpu.a == value
    for n in range(8):
        assert k.switches.bit(n) == bool(value >> n & 1)  # bit n = SWn


def test_switch_bits_set_toggle_and_validate():
    s = SwitchBank()
    s.set_bit(7, True)
    s.set_bit(0, True)
    assert s.value == 0x81
    s.toggle(0)
    assert s.value == 0x80
    with pytest.raises(PeripheralConfigError):
        s.set_bit(8, True)


@pytest.mark.parametrize("value", [0x00, 0x01, 0x80, 0x3C, 0xFF])
def test_out_drives_the_leds_bit_for_bit_and_never_touches_registers_or_flags(value):
    m, k = machine(f"mvi a,{value:03X}h\nout 01h\nhlt")
    m.step_into()
    before = (tuple(m.cpu.regs), m.cpu.f, m.cpu.sp)
    m.step_into()
    assert k.leds.value == value and k.leds.written
    assert [k.leds.lit(n) for n in range(8)] == [bool(value >> n & 1) for n in range(8)]
    assert (tuple(m.cpu.regs), m.cpu.f, m.cpu.sp) == before
    assert k.display.value == 0 and not k.display.written  # only the addressed device changes


def test_out_to_the_display_port_drives_only_the_display():
    m, k = machine("mvi a,06h\nout 02h\nhlt")
    m.run_to_end()
    assert k.display.value == 0x06 and k.display.segments() == {"b", "c"}
    assert k.leds.value == 0 and not k.leds.written


def test_experiment_1_copies_the_switches_to_the_leds():
    m, k = machine(EXPERIMENT_1)
    k.set_switches(0b1010_0101)
    assert m.run_to_end() is Stop.HALT
    assert m.cpu.a == 0xA5 and k.leds.value == 0xA5
    assert [(p, v) for _, p, v in m.out_log] == [(0x01, 0xA5)]  # the Machine OUT log still works


# -------------------------------------------------------------- remapping
def test_remapping_moves_every_device():
    m, k = machine("in 10h\nout 20h\nout 30h\nhlt", ports=PortMap(0x10, 0x20, 0x30))
    k.set_switches(0x3F)
    m.run_to_end()
    assert k.leds.value == 0x3F and k.display.value == 0x3F
    k.set_ports(PortMap(0x00, 0x01, 0x02))
    assert k.ports == PortMap(0x00, 0x01, 0x02)
    assert k.bus.owner(IN, 0x10) is None and k.bus.owner(OUT, 0x01) is k.leds


def test_leds_and_display_can_swap_ports():
    _, k = machine("hlt")
    k.set_ports(PortMap(0x00, 0x02, 0x01))
    assert (k.leds.port, k.display.port) == (0x02, 0x01)


def test_an_input_and_an_output_may_share_a_port_number():
    """IN and OUT are different bus cycles, so IN 01H (switches) and OUT 01H (LEDs) do not conflict."""
    m, k = machine("in 01h\nout 01h\nhlt", ports=PortMap(0x01, 0x01, 0x02))
    k.set_switches(0x42)
    m.run_to_end()
    assert k.leds.value == 0x42


# ----------------------------------------------------- invalid configs
@pytest.mark.parametrize("bad", [PortMap(-1, 1, 2), PortMap(0, 256, 2), PortMap(0, 1, "02"), PortMap(0, 1, 2.0),
                                 PortMap(True, 1, 2)])
def test_invalid_port_numbers_are_rejected(bad):
    with pytest.raises(PeripheralConfigError, match="00H to FFH"):
        bad.validate()


def test_output_conflict_is_reported_clearly_and_changes_nothing():
    _, k = machine("hlt")
    with pytest.raises(PortConflictError, match="LEDs and the seven-segment display are both on OUT 05H"):
        k.set_ports(PortMap(0x00, 0x05, 0x05))
    assert k.ports == PortMap()
    with pytest.raises(PortConflictError):
        TrainerKit(CPU(), PortMap(0, 3, 3))


def test_bus_rejects_two_devices_on_one_port():
    bus = PeripheralBus(CPU())
    bus.add(SwitchBank(0x00))
    with pytest.raises(PortConflictError, match="IN 00H already belongs to switches"):
        bus.add(SwitchBank(0x00, name="more switches"))
    bus.add(LedBank(0x01))
    with pytest.raises(PortConflictError, match="OUT 01H already belongs to leds"):
        bus.add(SevenSegment(0x01))
    assert len(bus.devices) == 2


def test_bad_seven_segment_options_are_rejected():
    with pytest.raises(PeripheralConfigError):
        SevenSegment(mode="bcd")
    with pytest.raises(PeripheralConfigError, match="exactly once"):
        SevenSegment(segment_order="aabcdefg")
    with pytest.raises(PeripheralConfigError):
        SevenSegment(segment_order="abcdefg")


# ----------------------------------------------------------------- reset
def test_reset_hardware_and_reset_outputs():
    m, k = machine("mvi a,0FFh\nout 01h\nout 02h\nhlt")
    k.set_switches(0x81)
    m.run_to_end()
    k.reset_outputs()  # program reload: latches blank, switches stay
    assert (k.leds.value, k.display.value, k.leds.written) == (0, 0, False) and k.switches.value == 0x81
    m.run_to_end()
    k.reset_hardware()  # explicit hardware reset: everything to power-on
    assert (k.leds.value, k.display.value, k.switches.value) == (0, 0, 0)
    assert m.cpu.io[0] == 0  # the I/O table mirror follows the switches


def test_cpu_reset_and_program_reload_keep_switch_positions():
    m, k = machine(EXPERIMENT_1)
    k.set_switches(0x5A)
    m.run_to_end()
    m.reset_cpu()
    m.load(m.program)
    assert k.switches.value == 0x5A
    m.run_to_end()
    assert m.cpu.a == 0x5A


def test_snapshot_describes_every_device():
    m, k = machine(EXPERIMENT_1)
    k.set_switches(0x0F)
    m.run_to_end()
    s = k.snapshot()
    assert s["enabled"] and s["ports"] == PortMap()
    by = {d["kind"]: d for d in s["devices"]}
    assert by["switches"]["value"] == 0x0F and by["switches"]["reads"] == 1
    assert by["leds"]["value"] == 0x0F and by["leds"]["writes"] == 1
    assert by["seven_segment"]["mode"] == RAW and by["seven_segment"]["segments"] == ""
    assert s["last_in"] == (0x00, 0x0F) and s["last_out"] == (0x01, 0x0F)


# ---------------------------------------------------- enable / disable
_PROGRAMS = [
    EXPERIMENT_1,
    "in 00h\nadi 1\nout 01h\nout 02h\nin 07h\nout 00h\nin 00h\nhlt",
    "mvi b,0\nnext: mov a,b\nout 01h\nin 01h\nout 02h\ninr b\njnz next\nhlt",
]


@pytest.mark.parametrize("src", _PROGRAMS)
def test_disabled_kit_is_byte_for_byte_identical_to_no_kit(src):
    def run(make_kit, enable_then_disable=False):
        r = assemble(src, 0)
        m = Machine()
        m.load(r)
        m.set_trace(True)
        m.cpu.io[0], m.cpu.io[7], m.cpu.io[1] = 0x41, 0x99, 0x10  # values a user typed in the I/O table
        hooks = (m.cpu.on_in, m.cpu.on_out)
        if make_kit:
            k = TrainerKit(m.cpu)
            k.switches.set_value(0xEE)  # switches set, but the kit is not connected
            if enable_then_disable:
                k.set_enabled(True)
                k.set_enabled(False)
                m.cpu.io[0] = 0x41  # (enabling mirrored the switches into the I/O table; type it back)
            assert (m.cpu.on_in, m.cpu.on_out) == hooks  # exactly the original hooks
            assert m.cpu.on_in is None
        assert m.run_to_end() is Stop.HALT
        return state(m)

    baseline = run(False)
    assert run(True) == baseline
    assert run(True, enable_then_disable=True) == baseline


def test_enabled_kit_keeps_the_trace_events_and_out_log():
    m, k = machine(EXPERIMENT_1)
    m.set_trace(True)
    k.set_switches(0x3C)
    m.run_to_end()
    assert [r.events for r in m.trace][:2] == [(("IN", 0x00, 0x3C),), (("OUT", 0x01, 0x3C),)]
    assert m.out_log[-1][1:] == (0x01, 0x3C) and m.out_count == 1
    assert m.cpu.io[1] == 0x3C  # OUT still writes the I/O table, as before


def test_ports_no_device_owns_behave_as_before():
    m, k = machine("in 07h\nout 09h\nhlt")
    m.cpu.io[7] = 0x66
    m.run_to_end()
    assert m.cpu.a == 0x66 and m.cpu.io[9] == 0x66 and k.leds.value == 0
    assert m.out_log[-1][1:] == (0x09, 0x66)


def test_the_switches_own_their_port_while_connected():
    """While connected, IN 00H reads the switches, whatever cpu.io[0] holds; the table mirrors them."""
    m, k = machine(EXPERIMENT_1)
    k.set_switches(0x12)
    assert m.cpu.io[0] == 0x12
    m.cpu.io[0] = 0x99  # e.g. a stale value; the switches win
    m.run_to_end()
    assert m.cpu.a == 0x12


# --------------------------------------------------------- callback chaining
def test_bus_chains_to_existing_callbacks_and_restores_them():
    cpu = CPU()
    seen_out, seen_in = [], []

    def prev_out(port, value):
        seen_out.append((port, value))

    def prev_in(port):
        seen_in.append(port)
        return 0x77 if port == 0x30 else None

    cpu.on_out, cpu.on_in = prev_out, prev_in
    bus = PeripheralBus(cpu)
    leds = bus.add(LedBank(0x01))
    sw = bus.add(SwitchBank(0x00))
    sw.set_value(0x21)
    bus.set_enabled(True)
    r = assemble("in 00h\nout 01h\nin 30h\nout 05h\nin 31h\nhlt", 0)
    for a, b in r.image.items():
        cpu.mem.data[a] = b
    while not cpu.halted:
        cpu.step()
    assert seen_out == [(0x01, 0x21), (0x05, 0x77)]  # previous on_out sees every OUT, owned or not
    assert seen_in == [0x30, 0x31]  # previous on_in sees only ports no device owns
    assert leds.value == 0x21 and cpu.a == 0  # IN 31h: prev returned None -> cpu.io[0x31] == 0
    bus.set_enabled(False)
    assert cpu.on_out is prev_out and cpu.on_in is prev_in


def test_disabling_keeps_hooks_installed_after_the_bus():
    cpu = CPU()
    bus = PeripheralBus(cpu)
    bus.set_enabled(True)
    later = lambda port, value: None  # noqa: E731
    cpu.on_out = later
    bus.set_enabled(False)
    assert cpu.on_out is later and cpu.on_in is None


def test_machine_out_log_is_preserved_through_the_chain():
    m = Machine()
    record = m.cpu.on_out
    k = TrainerKit(m.cpu, enabled=True)
    assert m.cpu.on_out is not record
    m.load(assemble("mvi a,7\nout 01h\nout 02h\nout 03h\nhlt", 0))
    m.run_to_end()
    assert [(p, v) for _, p, v in m.out_log] == [(1, 7), (2, 7), (3, 7)] and m.out_count == 3
    k.set_enabled(False)
    assert m.cpu.on_out == record


def test_a_future_peripheral_needs_no_cpu_change():
    class Buzzer(Peripheral):
        kind = "buzzer"

        def __init__(self):
            super().__init__("buzzer")
            self.out_ports = {0x40: "buzzer"}
            self.in_ports = {0x41: "status"}
            self.beeps = 0

        def write(self, port, value):
            self.beeps += 1

        def read(self, port):
            return 0x80 | self.beeps

    m, k = machine("out 40h\nout 40h\nin 41h\nhlt")
    b = k.bus.add(Buzzer())
    m.run_to_end()
    assert b.beeps == 2 and m.cpu.a == 0x82


# ------------------------------------------------------- seven-segment
def test_raw_segment_bits_are_active_high_a_to_dp():
    d = SevenSegment()
    assert d.segment_order == DEFAULT_SEGMENT_ORDER == "abcdefgp"
    for n, seg in enumerate("abcdefgp"):
        d.write(2, 1 << n)
        assert d.segments() == {seg}, (n, seg)
    d.write(2, 0xFF)
    assert d.segments() == set("abcdefgp")
    d.write(2, 0x00)
    assert d.segments() == set()


def test_raw_mode_active_low_and_custom_mapping():
    d = SevenSegment(active_low=True)
    d.write(2, 0xFE)  # only bit 0 low -> only segment a lit
    assert d.segments() == {"a"}
    d = SevenSegment(segment_order="pgfedcba")  # bit 0 = DP ... bit 7 = a
    d.write(2, 0x01)
    assert d.segments() == {"p"}
    d.write(2, 0x80)
    assert d.segments() == {"a"}


_EXPECTED = {  # the classic hex-digit shapes, segment by segment
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg", "5": "acdfg", "6": "acdefg",
    "7": "abc", "8": "abcdefg", "9": "abcdfg", "A": "abcefg", "b": "cdefg", "C": "adef", "d": "bcdeg",
    "E": "adefg", "F": "aefg",
}


@pytest.mark.parametrize("digit", range(16))
def test_hex_decode_shows_all_16_digits(digit):
    d = SevenSegment(mode=HEX)
    for high in (0x00, 0x50, 0xF0):  # the high nibble is ignored, and the DP stays off
        d.write(2, high | digit)
        assert d.glyph() == HEX_GLYPHS[digit]
        assert d.segments() == set(_EXPECTED[HEX_GLYPHS[digit]]), (digit, high)
    assert sum(1 << "abcdefg".index(s) for s in _EXPECTED[HEX_GLYPHS[digit]]) == HEX_DIGITS[digit]


def test_hex_decode_ignores_polarity_and_switching_mode_never_touches_the_cpu():
    m, k = machine("mvi a,0A7h\nout 02h\nhlt")
    m.run_to_end()
    before = state(m)
    k.display.set_mode(HEX)
    k.display.active_low = True
    assert k.display.glyph() == "7" and k.display.segments() == set("abc")
    k.display.set_mode(RAW)
    assert state(m) == before


def test_switches_read_the_hex_digit_into_the_display():
    m, k = machine("in 00h\nout 02h\nhlt")
    k.display.set_mode(HEX)
    for v in range(16):
        k.set_switches(v)
        m.reset_cpu()
        m.run_to_end()
        assert k.display.glyph() == HEX_GLYPHS[v]


def test_output_latch_is_blank_until_written():
    latch = OutputLatch(0x10, "x")
    assert not latch.written
    latch.write(0x10, 0)
    assert latch.written and latch.value == 0


# ------------------------------------------------- the bundled lab programs
def _lab(name):
    from importlib import resources
    return resources.files("studio8085").joinpath("examples", "trainer", name).read_text(encoding="utf-8")


def test_lab_programs_are_bundled_and_assemble_in_both_syntaxes():
    from importlib import resources
    names = sorted(f.name for f in resources.files("studio8085").joinpath("examples", "trainer").iterdir()
                   if f.name.endswith(".asm"))
    assert names == ["E1_read_switches_control_leds.asm", "E1b_seven_segment_raw.asm", "E1c_seven_segment_hex.asm"]
    for n in names:
        for compat in ("off", "strict"):
            r = assemble(_lab(n), 0, compat=compat)
            assert r.ok and not r.warnings, (n, compat, [(d.line, d.message) for d in r.diagnostics])
        assert r.metadata["validation"] == "T"


def test_lab_e1_is_the_owner_program_verbatim():
    src = _lab("E1_read_switches_control_leds.asm")
    assert "START: IN 00H\n       OUT 01H\n       HLT\n" in src
    assert bytes(assemble(src, 0).image[a] for a in range(5)) == bytes([0xDB, 0x00, 0xD3, 0x01, 0x76])
    for v in (0x00, 0xA5, 0xFF):
        m, k = machine(src)
        k.set_switches(v)
        m.step_into()
        assert m.cpu.a == v and not k.leds.written
        m.step_into()
        assert k.leds.value == v
        assert m.step_into() is Stop.HALT


def test_lab_e1b_raw_segments_show_h_then_h_dot():
    m, k = machine(_lab("E1b_seven_segment_raw.asm"))
    m.step_into()
    m.step_into()
    assert k.display.segments() == set("bcefg")  # H
    assert m.run_to_end() is Stop.HALT
    assert k.display.value == 0xF6 == k.leds.value and k.display.segments() == set("bcefgp")  # H.


def test_lab_e1c_hex_decodes_the_low_nibble_of_the_switches():
    r = assemble(_lab("E1c_seven_segment_hex.asm"), 0)
    assert r.metadata["display"] == "hex"
    m, k = machine(_lab("E1c_seven_segment_hex.asm"))
    k.display.set_mode(HEX)
    k.set_switches(0b0101_1010)
    m.run_to_end()
    assert k.leds.value == 0x5A and k.display.glyph() == "A" and k.display.segments() == set("abcefg")
