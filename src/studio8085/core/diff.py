"""Before/after comparison of machine state (for the 'what just happened' view)."""

from __future__ import annotations

from dataclasses import dataclass, field

REG_NAMES = ["A", "B", "C", "D", "E", "H", "L"]
FLAG_NAMES = ["S", "Z", "AC", "P", "CY"]


@dataclass
class Snapshot:
    regs: dict[str, int]
    flags: dict[str, int]
    sp: int
    pc: int
    ie: bool
    icount: int
    tstates: int
    mem: bytes
    io: bytes


@dataclass
class Diff:
    """Items are ``(name, before, after)`` strings for everything that changed."""

    items: list[tuple[str, str, str]] = field(default_factory=list)
    mem: list[tuple[int, int, int]] = field(default_factory=list)  # (addr, old, new)
    io: list[tuple[int, int, int]] = field(default_factory=list)
    instructions: int = 0
    tstates: int = 0

    @property
    def empty(self) -> bool:
        return not (self.items or self.mem or self.io)


def take(machine) -> Snapshot:
    cpu = machine.cpu
    r = cpu.regs
    return Snapshot(
        regs={"A": r[7], "B": r[0], "C": r[1], "D": r[2], "E": r[3], "H": r[4], "L": r[5]},
        flags={"S": cpu.s, "Z": cpu.z, "AC": cpu.ac, "P": cpu.p, "CY": cpu.cy},
        sp=cpu.sp, pc=cpu.pc, ie=bool(cpu.ie), icount=cpu.icount, tstates=cpu.tstates,
        mem=bytes(cpu.mem.data), io=bytes(cpu.io))


def compare(before: Snapshot, after: Snapshot, max_mem: int = 64) -> Diff:
    d = Diff(instructions=after.icount - before.icount, tstates=after.tstates - before.tstates)
    for n in REG_NAMES:
        if before.regs[n] != after.regs[n]:
            d.items.append((n, f"{before.regs[n]:02X}h", f"{after.regs[n]:02X}h"))
    for n in FLAG_NAMES:
        if before.flags[n] != after.flags[n]:
            d.items.append((n, str(before.flags[n]), str(after.flags[n])))
    if before.sp != after.sp:
        d.items.append(("SP", f"{before.sp:04X}h", f"{after.sp:04X}h"))
    if before.pc != after.pc:
        d.items.append(("PC", f"{before.pc:04X}h", f"{after.pc:04X}h"))
    if before.ie != after.ie:
        d.items.append(("IE", str(int(before.ie)), str(int(after.ie))))
    if before.mem != after.mem:
        for i, (x, y) in enumerate(zip(before.mem, after.mem)):
            if x != y:
                d.mem.append((i, x, y))
                if len(d.mem) >= max_mem:
                    break
    if before.io != after.io:
        for i, (x, y) in enumerate(zip(before.io, after.io)):
            if x != y:
                d.io.append((i, x, y))
    return d
