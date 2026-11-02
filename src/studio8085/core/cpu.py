"""Intel 8085 CPU and memory model.

Accuracy notes (all covered by tests):

* Flags follow the Intel manual: ADD/ADC/SUB/SBB/CMP/INR/DCR/DAA/logic ops set
  S, Z, P exactly, CY is a borrow for subtraction, ANA sets AC and clears CY.
* AC after a subtraction is the carry out of bit 3 of ``A + ~operand + 1``, which
  is what the 8085's ALU does. ``ac_borrow_style=True`` switches to the
  "textbook" convention (AC = borrow from bit 4) instead.
* RST, EI/DI (with the one-instruction EI delay), TRAP, RST 7.5/6.5/5.5, INTR,
  RIM and SIM are implemented. After reset all three maskable RST inputs are
  masked, as on the real chip.
* Every instruction adds its documented T-state cost.
"""

from __future__ import annotations

from array import array

from .opcodes import TABLE

OK, HALT = 0, 1

PARITY = [1 if bin(i).count("1") % 2 == 0 else 0 for i in range(256)]
TSTATES = [(i.tstates if i else 0) for i in TABLE]

# interrupt request bits
IRQ_TRAP, IRQ_75, IRQ_65, IRQ_55, IRQ_INTR = 1, 2, 4, 8, 16
VECTORS = {IRQ_TRAP: 0x24, IRQ_75: 0x3C, IRQ_65: 0x34, IRQ_55: 0x2C}
IRQ_NAMES = {"TRAP": IRQ_TRAP, "RST7.5": IRQ_75, "RST6.5": IRQ_65,
             "RST5.5": IRQ_55, "INTR": IRQ_INTR}


class IllegalOpcode(Exception):
    def __init__(self, opcode: int, address: int):
        super().__init__(f"Illegal opcode {opcode:02X}h at {address:04X}h")
        self.opcode, self.address = opcode, address


class Memory:
    """64K of RAM that remembers which bytes were read/written (for the heatmap)."""

    __slots__ = ("data", "rd", "wr", "last", "kind", "hot", "clock", "read", "write", "track", "log")

    def __init__(self):
        self.data = bytearray(65536)
        self.rd = array("I", bytes(4 * 65536))
        self.wr = array("I", bytes(4 * 65536))
        self.last = array("Q", bytes(8 * 65536))
        self.kind = bytearray(65536)  # 0 none, 1 read, 2 write
        self.hot: set[int] = set()
        self.clock = 0
        self.log = None  # when a list, every write is appended as ('W', addr, value)
        self.set_tracking(True)

    def set_tracking(self, on: bool):
        self.track = on
        self.read = self._read_tracked if on else self._read_fast
        self.write = self._write_tracked if on else self._write_fast

    def _read_fast(self, a):
        return self.data[a]

    def _write_fast(self, a, v):
        self.data[a] = v
        if self.log is not None:
            self.log.append(("W", a, v))

    def _read_tracked(self, a):
        self.rd[a] += 1
        self.last[a] = self.clock
        self.kind[a] = 1
        self.hot.add(a)
        return self.data[a]

    def _write_tracked(self, a, v):
        self.data[a] = v
        self.wr[a] += 1
        self.last[a] = self.clock
        self.kind[a] = 2
        self.hot.add(a)
        if self.log is not None:
            self.log.append(("W", a, v))

    def clear_stats(self):
        self.rd = array("I", bytes(4 * 65536))
        self.wr = array("I", bytes(4 * 65536))
        self.last = array("Q", bytes(8 * 65536))
        self.kind = bytearray(65536)
        self.hot.clear()

    def clear(self):
        self.data[:] = bytes(65536)
        self.clear_stats()


class CPU:
    def __init__(self, mem: Memory | None = None, ac_borrow_style: bool = False):
        self.mem = mem or Memory()
        self.io = bytearray(256)
        self.ac_borrow_style = ac_borrow_style
        self.on_out = None  # callable(port, value)
        self.on_in = None  # callable(port) -> int | None
        self.events = None  # when a list: ('IN'|'OUT', port, value) and ('INT', vector) are appended
        self.exec_count = [0] * 65536
        self._table = self._build_table()
        self.reset()

    # ------------------------------------------------------------ state
    def reset(self, clear_io: bool = False):
        self.regs = [0] * 8  # B C D E H L (M unused) A
        self.sp = 0xFFFF
        self.pc = 0
        self.s = self.z = self.ac = self.p = self.cy = 0
        self.ie = False
        self.m55 = self.m65 = self.m75 = True
        self.sid = 0
        self.sod = 0
        self.halted = False
        self.icount = 0
        self.tstates = 0
        self.irq_taken = 0
        self._irq = 0
        self._intr_vec = 0
        self._ei_arm = 0
        self.mem.clock = 0
        self.exec_count = [0] * 65536
        if clear_io:
            self.io[:] = bytes(256)

    # 16-bit views --------------------------------------------------
    @property
    def a(self):
        return self.regs[7]

    @a.setter
    def a(self, v):
        self.regs[7] = v & 0xFF

    def get_rp(self, i):  # 0=BC 1=DE 2=HL 3=SP
        if i == 3:
            return self.sp
        r = self.regs
        return (r[2 * i] << 8) | r[2 * i + 1]

    def set_rp(self, i, v):
        v &= 0xFFFF
        if i == 3:
            self.sp = v
        else:
            self.regs[2 * i] = v >> 8
            self.regs[2 * i + 1] = v & 0xFF

    @property
    def hl(self):
        return (self.regs[4] << 8) | self.regs[5]

    @property
    def f(self):
        return (self.s << 7) | (self.z << 6) | (self.ac << 4) | (self.p << 2) | 2 | self.cy

    @f.setter
    def f(self, v):
        self.s, self.z, self.ac = (v >> 7) & 1, (v >> 6) & 1, (v >> 4) & 1
        self.p, self.cy = (v >> 2) & 1, v & 1

    def snapshot(self):
        return (tuple(self.regs), self.sp, self.pc, self.f, self.ie, self.m55, self.m65,
                self.m75, self._irq, self.sod, self.halted)

    # ------------------------------------------------------ interrupts
    def raise_interrupt(self, name: str, rst: int = 7):
        bit = IRQ_NAMES[name]
        self._irq |= bit
        if bit == IRQ_INTR:
            self._intr_vec = (rst & 7) * 8

    def clear_interrupt(self, name: str):
        self._irq &= ~IRQ_NAMES[name]

    @property
    def pending(self) -> int:
        return self._irq

    def _accept_interrupt(self) -> bool:
        irq = self._irq
        vec = None
        if irq & IRQ_TRAP:
            vec, bit = 0x24, IRQ_TRAP
        elif self.ie:
            if irq & IRQ_75 and not self.m75:
                vec, bit = 0x3C, IRQ_75
            elif irq & IRQ_65 and not self.m65:
                vec, bit = 0x34, IRQ_65
            elif irq & IRQ_55 and not self.m55:
                vec, bit = 0x2C, IRQ_55
            elif irq & IRQ_INTR:
                vec, bit = self._intr_vec, IRQ_INTR
        if vec is None:
            return False
        self._irq &= ~bit
        self.halted = False
        self.ie = False
        self._push16(self.pc)
        self.pc = vec
        self.tstates += 12
        self.irq_taken += 1
        if self.events is not None:
            self.events.append(("INT", vec))
        return True

    # ---------------------------------------------------------- stack
    def _push16(self, v):
        w = self.mem.write
        sp = (self.sp - 1) & 0xFFFF
        w(sp, v >> 8)
        sp = (sp - 1) & 0xFFFF
        w(sp, v & 0xFF)
        self.sp = sp

    def _pop16(self):
        r = self.mem.read
        sp = self.sp
        lo = r(sp)
        sp = (sp + 1) & 0xFFFF
        hi = r(sp)
        self.sp = (sp + 1) & 0xFFFF
        return (hi << 8) | lo

    # ----------------------------------------------------------- fetch
    def _fetch8(self):
        pc = self.pc
        self.pc = (pc + 1) & 0xFFFF
        return self.mem.data[pc]

    def _fetch16(self):
        d = self.mem.data
        pc = self.pc
        v = d[pc] | (d[(pc + 1) & 0xFFFF] << 8)
        self.pc = (pc + 2) & 0xFFFF
        return v

    # ------------------------------------------------------------ step
    def step(self) -> int:
        """Execute one instruction (or take one interrupt). Returns OK or HALT."""
        if self._irq and self._accept_interrupt():
            return OK
        if self.halted:
            return HALT
        pc = self.pc
        mem = self.mem
        mem.clock = self.icount
        op = mem.data[pc]
        self.exec_count[pc] += 1
        self.pc = (pc + 1) & 0xFFFF
        try:
            self._table[op](op)
        except IllegalOpcode:
            self.pc = pc
            self.exec_count[pc] -= 1
            raise
        self.tstates += TSTATES[op]
        self.icount += 1
        if self._ei_arm:
            if self._ei_arm == 2:
                self.ie = True
                self._ei_arm = 0
            else:
                self._ei_arm = 2
        return HALT if self.halted else OK

    # --------------------------------------------------------- helpers
    def _szp(self, r):
        self.s = r >> 7
        self.z = 1 if r == 0 else 0
        self.p = PARITY[r]

    def _getr(self, i):
        if i == 6:
            return self.mem.read(self.hl)
        return self.regs[i]

    def _setr(self, i, v):
        if i == 6:
            self.mem.write(self.hl, v)
        else:
            self.regs[i] = v

    def _cond(self, cc):
        return (not self.z, self.z, not self.cy, self.cy,
                not self.p, self.p, not self.s, self.s)[cc]

    def _alu(self, kind, v):
        a = self.regs[7]
        if kind < 2:  # ADD / ADC
            c = self.cy if kind else 0
            r = a + v + c
            self.ac = 1 if (a & 15) + (v & 15) + c > 15 else 0
            self.cy = 1 if r > 255 else 0
            r &= 255
            self.regs[7] = r
        elif kind in (2, 3, 7):  # SUB / SBB / CMP
            b = self.cy if kind == 3 else 0
            r = a - v - b
            low = (a & 15) - (v & 15) - b
            self.cy = 1 if r < 0 else 0
            if self.ac_borrow_style:
                self.ac = 1 if low < 0 else 0
            else:
                self.ac = 1 if low >= 0 else 0
            r &= 255
            if kind != 7:
                self.regs[7] = r
        elif kind == 4:  # ANA
            r = a & v
            self.cy, self.ac = 0, 1
            self.regs[7] = r
        elif kind == 5:  # XRA
            r = a ^ v
            self.cy = self.ac = 0
            self.regs[7] = r
        else:  # ORA
            r = a | v
            self.cy = self.ac = 0
            self.regs[7] = r
        self._szp(r)

    # --------------------------------------------------------- handlers
    def _illegal(self, op):
        raise IllegalOpcode(op, (self.pc - 1) & 0xFFFF)

    def _nop(self, op):
        pass

    def _hlt(self, op):
        self.halted = True

    def _mov(self, op):
        self._setr((op >> 3) & 7, self._getr(op & 7))

    def _mvi(self, op):
        self._setr((op >> 3) & 7, self._fetch8())

    def _lxi(self, op):
        self.set_rp((op >> 4) & 3, self._fetch16())

    def _ldax(self, op):
        self.regs[7] = self.mem.read(self.get_rp((op >> 4) & 1))

    def _stax(self, op):
        self.mem.write(self.get_rp((op >> 4) & 1), self.regs[7])

    def _lda(self, op):
        self.regs[7] = self.mem.read(self._fetch16())

    def _sta(self, op):
        self.mem.write(self._fetch16(), self.regs[7])

    def _lhld(self, op):
        a = self._fetch16()
        self.regs[5] = self.mem.read(a)
        self.regs[4] = self.mem.read((a + 1) & 0xFFFF)

    def _shld(self, op):
        a = self._fetch16()
        self.mem.write(a, self.regs[5])
        self.mem.write((a + 1) & 0xFFFF, self.regs[4])

    def _xchg(self, op):
        r = self.regs
        r[2], r[4] = r[4], r[2]
        r[3], r[5] = r[5], r[3]

    def _xthl(self, op):
        sp = self.sp
        sp1 = (sp + 1) & 0xFFFF
        lo, hi = self.mem.read(sp), self.mem.read(sp1)
        self.mem.write(sp, self.regs[5])
        self.mem.write(sp1, self.regs[4])
        self.regs[5], self.regs[4] = lo, hi

    def _sphl(self, op):
        self.sp = self.hl

    def _pchl(self, op):
        self.pc = self.hl

    def _push(self, op):
        i = (op >> 4) & 3
        self._push16(((self.regs[7] << 8) | self.f) if i == 3 else self.get_rp(i))

    def _pop(self, op):
        i = (op >> 4) & 3
        v = self._pop16()
        if i == 3:
            self.regs[7] = v >> 8
            self.f = v & 0xFF
        else:
            self.set_rp(i, v)

    def _alu_reg(self, op):
        self._alu((op >> 3) & 7, self._getr(op & 7))

    def _alu_imm(self, op):
        self._alu((op >> 3) & 7, self._fetch8())

    def _inr(self, op):
        d = (op >> 3) & 7
        v = self._getr(d)
        r = (v + 1) & 255
        self.ac = 1 if (v & 15) == 15 else 0
        self._setr(d, r)
        self._szp(r)

    def _dcr(self, op):
        d = (op >> 3) & 7
        v = self._getr(d)
        r = (v - 1) & 255
        low_zero = (v & 15) == 0
        self.ac = (1 if low_zero else 0) if self.ac_borrow_style else (0 if low_zero else 1)
        self._setr(d, r)
        self._szp(r)

    def _inx(self, op):
        i = (op >> 4) & 3
        self.set_rp(i, self.get_rp(i) + 1)

    def _dcx(self, op):
        i = (op >> 4) & 3
        self.set_rp(i, self.get_rp(i) - 1)

    def _dad(self, op):
        v = self.hl + self.get_rp((op >> 4) & 3)
        self.cy = 1 if v > 0xFFFF else 0
        self.set_rp(2, v)

    def _rlc(self, op):
        a = self.regs[7]
        self.cy = a >> 7
        self.regs[7] = ((a << 1) | self.cy) & 255

    def _rrc(self, op):
        a = self.regs[7]
        self.cy = a & 1
        self.regs[7] = (a >> 1) | (self.cy << 7)

    def _ral(self, op):
        a = self.regs[7]
        c = self.cy
        self.cy = a >> 7
        self.regs[7] = ((a << 1) | c) & 255

    def _rar(self, op):
        a = self.regs[7]
        c = self.cy
        self.cy = a & 1
        self.regs[7] = (a >> 1) | (c << 7)

    def _daa(self, op):
        a = self.regs[7]
        lsb, msb = a & 15, a >> 4
        corr, cy = 0, self.cy
        if self.ac or lsb > 9:
            corr |= 0x06
        if self.cy or msb > 9 or (msb >= 9 and lsb > 9):
            corr |= 0x60
            cy = 1
        r = a + corr
        self.ac = 1 if lsb + (corr & 15) > 15 else 0
        self.cy = cy
        r &= 255
        self.regs[7] = r
        self._szp(r)

    def _cma(self, op):
        self.regs[7] ^= 255

    def _stc(self, op):
        self.cy = 1

    def _cmc(self, op):
        self.cy ^= 1

    def _jmp(self, op):
        self.pc = self._fetch16()

    def _jcc(self, op):
        t = self._fetch16()
        if self._cond((op >> 3) & 7):
            self.pc = t
            self.tstates += 3

    def _call(self, op):
        t = self._fetch16()
        self._push16(self.pc)
        self.pc = t

    def _ccc(self, op):
        t = self._fetch16()
        if self._cond((op >> 3) & 7):
            self._push16(self.pc)
            self.pc = t
            self.tstates += 9

    def _ret(self, op):
        self.pc = self._pop16()

    def _rcc(self, op):
        if self._cond((op >> 3) & 7):
            self.pc = self._pop16()
            self.tstates += 6

    def _rst(self, op):
        self._push16(self.pc)
        self.pc = op & 0x38

    def _in(self, op):
        port = self._fetch8()
        v = self.on_in(port) if self.on_in else None
        self.regs[7] = self.io[port] if v is None else v & 0xFF
        if self.events is not None:
            self.events.append(("IN", port, self.regs[7]))

    def _out(self, op):
        port = self._fetch8()
        self.io[port] = self.regs[7]
        if self.events is not None:
            self.events.append(("OUT", port, self.regs[7]))
        if self.on_out:
            self.on_out(port, self.regs[7])

    def _ei(self, op):
        self._ei_arm = 1

    def _di(self, op):
        self.ie = False
        self._ei_arm = 0

    def _rim(self, op):
        irq = self._irq
        self.regs[7] = ((self.sid << 7) | ((1 if irq & IRQ_75 else 0) << 6)
                        | ((1 if irq & IRQ_65 else 0) << 5) | ((1 if irq & IRQ_55 else 0) << 4)
                        | ((1 if self.ie else 0) << 3) | (int(self.m75) << 2)
                        | (int(self.m65) << 1) | int(self.m55))

    def _sim(self, op):
        a = self.regs[7]
        if a & 0x08:
            self.m55, self.m65, self.m75 = bool(a & 1), bool(a & 2), bool(a & 4)
        if a & 0x10:
            self._irq &= ~IRQ_75
        if a & 0x40:
            self.sod = (a >> 7) & 1

    # ----------------------------------------------------------- table
    def _build_table(self):
        t = [self._illegal] * 256
        for ins in TABLE:
            if ins is None:
                continue
            m, op = ins.mnemonic, ins.opcode
            if m == "MOV":
                t[op] = self._mov
            elif m == "HLT":
                t[op] = self._hlt
            elif m in ("ADD", "ADC", "SUB", "SBB", "ANA", "XRA", "ORA", "CMP"):
                t[op] = self._alu_reg
            elif m in ("ADI", "ACI", "SUI", "SBI", "ANI", "XRI", "ORI", "CPI"):
                t[op] = self._alu_imm
            elif m in ("JMP",):
                t[op] = self._jmp
            elif m == "CALL":
                t[op] = self._call
            elif m == "RET":
                t[op] = self._ret
            elif m[0] == "J" and len(m) > 1:
                t[op] = self._jcc
            elif m[0] == "C" and m not in ("CMA", "CMC", "CMP", "CPI") and ins.length == 3:
                t[op] = self._ccc
            elif m[0] == "R" and ins.length == 1 and m not in ("RLC", "RRC", "RAL", "RAR", "RIM", "RST"):
                t[op] = self._rcc
            else:
                t[op] = getattr(self, "_" + m.lower(), self._illegal)
        return t
