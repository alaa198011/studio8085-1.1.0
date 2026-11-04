"""Virtual peripherals on the 8085 I/O ports (no Qt).

The CPU already offers two hooks (see ``cpu.py``):

* ``cpu.on_in(port) -> int | None``: called by ``IN port``; a non-``None`` result is what A receives,
  ``None`` means "read ``cpu.io[port]``" (the I/O Ports table).
* ``cpu.on_out(port, value)``: called by ``OUT port`` *after* ``cpu.io[port]`` was written and the
  ``('OUT', port, value)`` event was logged.

:class:`PeripheralBus` installs itself on those hooks and **chains** to whatever was installed before it
(``Machine`` uses ``on_out`` for its OUT log): the previous ``on_out`` is always called first, with the same
arguments, and a port no device owns falls through to the previous ``on_in`` (or to ``cpu.io``). Nothing in
the CPU changes, and ``cpu.events`` is untouched because the CPU appends to it itself.

While the bus is *disabled* it is not installed at all: ``cpu.on_in`` / ``cpu.on_out`` are exactly the
objects they were before it was attached, so execution is byte-for-byte what it was without peripherals.

The default port numbers (IN 00H switches, OUT 01H LEDs, OUT 02H seven-segment display) are *virtual
software assignments chosen for teaching*. They are not the addresses of any real 8085 trainer or chip
(a real kit decodes its own addresses, usually through an 8255 PPI). See ``docs/TRAINER_KIT.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

IN, OUT = "in", "out"

# --------------------------------------------------------------- seven-segment
SEGMENTS = "abcdefg"  # + "p" for the decimal point
DEFAULT_SEGMENT_ORDER = "abcdefgp"  # bit 0 = a ... bit 6 = g, bit 7 = DP
RAW, HEX = "raw", "hex"

# Hex Decode lookup (active-high, bit 0 = a ... bit 6 = g). A teaching convention, as on most trainer kits:
#   0 1 2 3 4 5 6 7 8 9 A b C d E F
HEX_DIGITS = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07,
              0x7F, 0x6F, 0x77, 0x7C, 0x39, 0x5E, 0x79, 0x71)
HEX_GLYPHS = "0123456789AbCdEF"


class PeripheralConfigError(ValueError):
    """An invalid port number, mapping or option."""


class PortConflictError(PeripheralConfigError):
    """Two devices claim the same port in the same direction."""


def check_port(port) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 0xFF:
        raise PeripheralConfigError(f"Port must be a whole number from 00H to FFH, not {port!r}")
    return port


# ------------------------------------------------------------------ devices
class Peripheral:
    """Base class. A device owns zero or more input ports and output ports (port -> role)."""

    name = "device"
    kind = "device"

    def __init__(self, name: str | None = None):
        if name:
            self.name = name
        self.in_ports: dict[int, str] = {}
        self.out_ports: dict[int, str] = {}

    # called by the bus
    def read(self, port: int) -> int:  # pragma: no cover - only for devices with input ports
        raise NotImplementedError

    def peek(self, port: int) -> int:
        """The value ``read`` would return, without side effects (used to mirror it into ``cpu.io``)."""
        return self.read(port)

    def write(self, port: int, value: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def reset(self) -> None:
        """Power-on state."""

    def reset_outputs(self) -> None:
        """Clear output latches only (a program reload); inputs such as switch positions stay."""

    def snapshot(self) -> dict:
        return {"name": self.name, "kind": self.kind,
                "in_ports": dict(self.in_ports), "out_ports": dict(self.out_ports)}


class SwitchBank(Peripheral):
    """Eight toggle switches SW7..SW0 read by ``IN port``. Bit n of the byte is SWn (1 = up / on)."""

    kind = "switches"

    def __init__(self, port: int = 0x00, name: str = "switches"):
        super().__init__(name)
        self.in_ports = {check_port(port): "switches"}
        self.value = 0
        self.reads = 0

    @property
    def port(self) -> int:
        return next(iter(self.in_ports))

    def read(self, port: int) -> int:
        self.reads += 1
        return self.value

    def peek(self, port: int) -> int:
        return self.value

    def set_value(self, value: int):
        self.value = value & 0xFF

    def bit(self, n: int) -> bool:
        return bool(self.value >> n & 1)

    def set_bit(self, n: int, on: bool):
        if not 0 <= n <= 7:
            raise PeripheralConfigError(f"Switch number must be 0-7, not {n}")
        self.value = (self.value | 1 << n) if on else (self.value & ~(1 << n) & 0xFF)

    def toggle(self, n: int):
        self.set_bit(n, not self.bit(n))

    def reset(self):
        self.value = 0
        self.reads = 0

    def snapshot(self) -> dict:
        return {**super().snapshot(), "value": self.value, "reads": self.reads}


class OutputLatch(Peripheral):
    """A byte latched by ``OUT port`` (it holds its value until the next OUT or a reset)."""

    kind = "latch"

    def __init__(self, port: int, name: str):
        super().__init__(name)
        self.out_ports = {check_port(port): name}
        self.value = 0
        self.writes = 0
        self.written = False  # False until the first OUT after a reset (blank, not "00H was written")

    @property
    def port(self) -> int:
        return next(iter(self.out_ports))

    def write(self, port: int, value: int):
        self.value = value & 0xFF
        self.writes += 1
        self.written = True

    def reset(self):
        self.value = 0
        self.writes = 0
        self.written = False

    def reset_outputs(self):
        self.reset()

    def snapshot(self) -> dict:
        return {**super().snapshot(), "value": self.value, "writes": self.writes, "written": self.written}


class LedBank(OutputLatch):
    """Eight LEDs LED7..LED0 driven by ``OUT port``. Bit n lights LEDn (active-high: 1 = on)."""

    kind = "leds"

    def __init__(self, port: int = 0x01, name: str = "leds"):
        super().__init__(port, name)

    def lit(self, n: int) -> bool:
        return bool(self.value >> n & 1)


class SevenSegment(OutputLatch):
    """One seven-segment digit with decimal point driven by ``OUT port``.

    * ``mode = RAW`` (default): each bit drives one segment. ``segment_order[n]`` names the segment of bit n
      (default ``"abcdefgp"``: bit0=a ... bit6=g, bit7=DP). ``active_low`` inverts the byte first (a 0 bit
      lights the segment, as for a common-anode display).
    * ``mode = HEX``: the low nibble selects a glyph 0-F from :data:`HEX_DIGITS`; the high nibble is ignored
      and the decimal point stays off. Polarity does not apply (the decoder drives the segments).

    Mode, mapping and polarity only change how the latched byte is *shown*; they never touch the CPU.
    """

    kind = "seven_segment"

    def __init__(self, port: int = 0x02, name: str = "seven_segment", mode: str = RAW,
                 segment_order: str = DEFAULT_SEGMENT_ORDER, active_low: bool = False):
        super().__init__(port, name)
        self.mode = RAW
        self.segment_order = DEFAULT_SEGMENT_ORDER
        self.active_low = bool(active_low)
        self.set_mode(mode)
        self.set_segment_order(segment_order)

    def set_mode(self, mode: str):
        if mode not in (RAW, HEX):
            raise PeripheralConfigError(f"Seven-segment mode must be {RAW!r} or {HEX!r}, not {mode!r}")
        self.mode = mode

    def set_segment_order(self, order: str):
        order = str(order).lower()
        if len(order) != 8 or set(order) != set(SEGMENTS + "p"):
            raise PeripheralConfigError(
                "Segment order must name each of a, b, c, d, e, f, g and p (decimal point) exactly once, "
                f"bit 0 first; got {order!r}")
        self.segment_order = order

    def segments(self) -> set[str]:
        """The lit segments: a subset of ``{'a',...,'g','p'}``."""
        if self.mode == HEX:
            pattern = HEX_DIGITS[self.value & 0x0F]
            return {SEGMENTS[i] for i in range(7) if pattern >> i & 1}
        v = (~self.value & 0xFF) if self.active_low else self.value
        return {self.segment_order[i] for i in range(8) if v >> i & 1}

    def glyph(self) -> str | None:
        """The hex digit shown in Hex Decode mode (None in Raw mode)."""
        return HEX_GLYPHS[self.value & 0x0F] if self.mode == HEX else None

    def snapshot(self) -> dict:
        return {**super().snapshot(), "mode": self.mode, "segment_order": self.segment_order,
                "active_low": self.active_low, "segments": "".join(s for s in SEGMENTS + "p" if s in self.segments())}


# ---------------------------------------------------------------------- bus
@dataclass(frozen=True)
class PortMap:
    """Where the three trainer-kit devices sit. Defaults are virtual teaching assignments."""

    switches_in: int = 0x00
    leds_out: int = 0x01
    seven_segment_out: int = 0x02

    def validate(self) -> "PortMap":
        for name in ("switches_in", "leds_out", "seven_segment_out"):
            try:
                check_port(getattr(self, name))
            except PeripheralConfigError as e:
                raise PeripheralConfigError(f"{name.replace('_', ' ')}: {e}") from None
        if self.leds_out == self.seven_segment_out:
            raise PortConflictError(
                f"Port conflict: the LEDs and the seven-segment display are both on OUT {self.leds_out:02X}H. "
                "Give each output device its own port.")
        return self


class PeripheralBus:
    """Routes IN/OUT of one CPU to attached devices, chaining to the hooks that were there before."""

    def __init__(self, cpu):
        self.cpu = cpu
        self.devices: list[Peripheral] = []
        self._in: dict[int, Peripheral] = {}
        self._out: dict[int, Peripheral] = {}
        self.enabled = False
        self._prev_in = None
        self._prev_out = None
        self.last_in: tuple[int, int] | None = None  # (port, value) of the last IN a device answered
        self.last_out: tuple[int, int] | None = None  # (port, value) of the last OUT a device received

    # ---------------------------------------------------------- devices
    def add(self, dev: Peripheral) -> Peripheral:
        self._check(dev, dev.in_ports, dev.out_ports)
        self.devices.append(dev)
        self._rebuild()
        return dev

    def remove(self, dev: Peripheral):
        self.devices.remove(dev)
        self._rebuild()

    def _check(self, dev: Peripheral, in_ports, out_ports):
        for port in in_ports:
            check_port(port)
            other = self._owner(IN, port)
            if other is not None and other is not dev:
                raise PortConflictError(f"Port conflict: IN {port:02X}H already belongs to {other.name}; "
                                        f"{dev.name} cannot use it too.")
        for port in out_ports:
            check_port(port)
            other = self._owner(OUT, port)
            if other is not None and other is not dev:
                raise PortConflictError(f"Port conflict: OUT {port:02X}H already belongs to {other.name}; "
                                        f"{dev.name} cannot use it too.")

    def _owner(self, direction: str, port: int) -> Peripheral | None:
        return (self._in if direction == IN else self._out).get(port)

    def owner(self, direction: str, port: int) -> Peripheral | None:
        return self._owner(direction, port)

    def _rebuild(self):
        self._in = {p: d for d in self.devices for p in d.in_ports}
        self._out = {p: d for d in self.devices for p in d.out_ports}

    def remap(self, dev: Peripheral, in_ports: dict[int, str] | None = None,
              out_ports: dict[int, str] | None = None):
        """Move a device to other ports. Validated first: on an error nothing changes."""
        new_in = dict(dev.in_ports if in_ports is None else in_ports)
        new_out = dict(dev.out_ports if out_ports is None else out_ports)
        self._check(dev, new_in, new_out)
        dev.in_ports, dev.out_ports = new_in, new_out
        self._rebuild()
        if self.enabled:
            self.sync_inputs()

    # ------------------------------------------------------- attachment
    def set_enabled(self, on: bool):
        if on == self.enabled:
            return
        if on:
            self._prev_in, self._prev_out = self.cpu.on_in, self.cpu.on_out
            self.cpu.on_in, self.cpu.on_out = self._on_in, self._on_out
            self.enabled = True
            self.sync_inputs()
        else:
            # put back exactly what was there (unless someone replaced the hooks after us - then keep theirs)
            if self.cpu.on_in == self._on_in:
                self.cpu.on_in = self._prev_in
            if self.cpu.on_out == self._on_out:
                self.cpu.on_out = self._prev_out
            self._prev_in = self._prev_out = None
            self.enabled = False

    def sync_inputs(self):
        """Copy each input device's value into ``cpu.io`` so the I/O Ports table shows what IN will read."""
        if not self.enabled:
            return
        for port, dev in self._in.items():
            self.cpu.io[port] = dev.peek(port) & 0xFF

    def _on_in(self, port):
        dev = self._in.get(port)
        if dev is not None:
            v = dev.read(port) & 0xFF
            self.last_in = (port, v)
            return v
        return self._prev_in(port) if self._prev_in else None

    def _on_out(self, port, value):
        if self._prev_out:
            self._prev_out(port, value)  # the Machine's OUT log (and anything else) first, unchanged
        dev = self._out.get(port)
        if dev is not None:
            dev.write(port, value)
            self.last_out = (port, value)

    # ------------------------------------------------------------ state
    def reset(self):
        """Hardware reset: every device to its power-on state (switches off, latches blank)."""
        for d in self.devices:
            d.reset()
        self.last_in = self.last_out = None
        self.sync_inputs()

    def reset_outputs(self):
        """Program reload / restart: blank the output latches; switch positions stay."""
        for d in self.devices:
            d.reset_outputs()
        self.last_in = self.last_out = None

    def snapshot(self) -> dict:
        return {"enabled": self.enabled, "devices": [d.snapshot() for d in self.devices],
                "last_in": self.last_in, "last_out": self.last_out}


class TrainerKit:
    """The Phase 1 "Virtual 8085 Trainer Kit": 8 switches, 8 LEDs and one seven-segment digit on a bus."""

    def __init__(self, cpu, ports: PortMap = PortMap(), enabled: bool = False):
        ports.validate()
        self.bus = PeripheralBus(cpu)
        self.switches = self.bus.add(SwitchBank(ports.switches_in))
        self.leds = self.bus.add(LedBank(ports.leds_out))
        self.display = self.bus.add(SevenSegment(ports.seven_segment_out))
        self.bus.set_enabled(enabled)

    @property
    def enabled(self) -> bool:
        return self.bus.enabled

    def set_enabled(self, on: bool):
        self.bus.set_enabled(on)

    @property
    def ports(self) -> PortMap:
        return PortMap(self.switches.port, self.leds.port, self.display.port)

    def set_ports(self, ports: PortMap):
        """Validate the whole map first, then move the devices (an invalid map changes nothing)."""
        ports.validate()
        old = self.ports
        bus = self.bus
        # move the outputs through a free state so swapping LED <-> display ports is possible
        bus.remap(self.leds, out_ports={})
        bus.remap(self.display, out_ports={})
        try:
            bus.remap(self.switches, in_ports={ports.switches_in: "switches"})
            bus.remap(self.leds, out_ports={ports.leds_out: "leds"})
            bus.remap(self.display, out_ports={ports.seven_segment_out: "seven_segment"})
        except PeripheralConfigError:
            bus.remap(self.leds, out_ports={})
            bus.remap(self.display, out_ports={})
            bus.remap(self.switches, in_ports={old.switches_in: "switches"})
            bus.remap(self.leds, out_ports={old.leds_out: "leds"})
            bus.remap(self.display, out_ports={old.seven_segment_out: "seven_segment"})
            raise

    def set_switches(self, value: int):
        self.switches.set_value(value)
        self.bus.sync_inputs()

    def toggle_switch(self, n: int):
        self.switches.toggle(n)
        self.bus.sync_inputs()

    def reset_hardware(self):
        self.bus.reset()

    def reset_outputs(self):
        self.bus.reset_outputs()

    def snapshot(self) -> dict:
        return {**self.bus.snapshot(), "ports": self.ports}
