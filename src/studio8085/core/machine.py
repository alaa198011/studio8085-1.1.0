"""Debugger layer: loads an assembled program into a CPU and drives execution.

The GUI never steps the CPU directly. It calls ``start(mode)`` and then
``run_chunk(budget)`` from a timer, so a runaway program can always be stopped
and the interface stays responsive. Step-over and step-out are implemented from
the real stack pointer, so conditional calls/returns, RST and interrupts are all
handled correctly.
"""

from __future__ import annotations

import enum

from .assembler import AsmResult
from .cpu import CPU, HALT, IllegalOpcode, Memory
from .disasm import disassemble
from .opcodes import CALL_OPCODES, RET_OPCODES
from .trace import TraceRow


class Stop(enum.Enum):
    STEP = "Stepped"
    BREAKPOINT = "Breakpoint"
    HALT = "Halted"
    ILLEGAL = "Illegal opcode"
    LOOP = "Infinite loop"
    LIMIT = "Instruction limit reached"
    USER = "Stopped"


class Machine:
    def __init__(self, ac_borrow_style: bool = False):
        self.cpu = CPU(Memory(), ac_borrow_style)
        self.program: AsmResult | None = None
        self.breakpoints: set[int] = set()
        self.max_instructions = 0  # 0 = unlimited
        self.stop_on_idle_loop = True
        self.last_error: str = ""
        self._mode = "run"
        self._first = True
        self._start_icount = 0
        self._over_target: tuple[int, int] | None = None
        self._out_depth = 0
        self._idle_pc = -1
        self.trace_on = False
        self.trace: list[TraceRow] = []
        self.trace_limit = 100_000
        self.trace_truncated = False
        self.out_log: list[tuple[int, int, int]] = []  # (icount, port, value), newest last
        self.out_count = 0  # total OUTs since the last restart (the log keeps only the tail)
        self.cpu.on_out = self._record_out

    def _record_out(self, port, value):
        self.out_log.append((self.cpu.icount, port, value))
        self.out_count += 1
        if len(self.out_log) > 5000:
            del self.out_log[:1000]

    # ------------------------------------------------------------- trace
    def set_trace(self, on: bool):
        """Record one TraceRow per executed instruction (registers/flags after it)."""
        self.trace_on = on
        if on:
            self.cpu.events = []
            self.cpu.mem.log = self.cpu.events
        else:
            self.cpu.events = None
            self.cpu.mem.log = None

    def clear_trace(self):
        self.trace.clear()
        self.trace_truncated = False
        if self.cpu.events is not None:
            self.cpu.events.clear()

    def _record(self, pc0: int, ic0: int, tt0: int, irq0: int):
        cpu = self.cpu
        if len(self.trace) >= self.trace_limit:
            self.trace_truncated = True
            cpu.events.clear()
            return
        taken_irq = cpu.irq_taken != irq0
        if taken_irq:
            text = f"<interrupt> -> {cpu.pc:04X}h"
        else:
            text = disassemble(cpu.mem.data, pc0)[0]
        r = cpu.regs
        row = TraceRow(
            self.trace_count + 1, pc0, self.program.addr_to_line.get(pc0) if self.program else None, text,
            (r[7], r[0], r[1], r[2], r[3], r[4], r[5]), cpu.sp, cpu.pc,
            (cpu.s, cpu.z, cpu.ac, cpu.p, cpu.cy), cpu.tstates - tt0, cpu.tstates, tuple(cpu.events))
        cpu.events.clear()
        self.trace.append(row)

    @property
    def trace_count(self) -> int:
        return len(self.trace)

    # --------------------------------------------------------- loading
    @property
    def loaded(self) -> bool:
        return self.program is not None

    def load(self, result: AsmResult, clear_memory: bool = True, keep_memory: bool = False):
        """Put an assembled program into memory and reset the CPU to its entry.

        By default all 64K is wiped first (``clear_memory``). With ``keep_memory`` nothing else is touched: bytes
        a student typed into memory, or that an earlier run produced, survive assembling, running and restarting.
        Only the *previous program's own bytes that nobody changed* are removed (so no stale code is left behind),
        then the new program's code and initialised data (``DB``, ``DW``, ``DS n,fill``) are written. Space
        reserved with a plain ``DS n`` is storage, so it is left as it is.
        """
        mem = self.cpu.mem
        if keep_memory:
            self._remove_program_bytes()
        elif clear_memory:
            mem.clear()
        skip = set()
        if keep_memory:
            for start, size in result.uninitialized:
                skip.update(range(start, start + size))
        for addr, byte in result.image.items():
            if addr not in skip:
                mem.data[addr] = byte
        self.program = result
        self.reset_cpu()

    def _remove_program_bytes(self):
        """Zero the bytes of the loaded program that still hold the value it put there."""
        if self.program:
            data = self.cpu.mem.data
            for addr, byte in self.program.image.items():
                if data[addr] == byte:
                    data[addr] = 0

    def reset_cpu(self):
        io = bytes(self.cpu.io)
        self.cpu.reset()
        self.cpu.io[:] = io  # user-entered input ports survive a restart
        self.cpu.mem.clear_stats()
        if self.program:
            self.cpu.pc = self.program.entry
        self.out_log.clear()
        self.out_count = 0
        self.clear_trace()
        self.last_error = ""
        self._mode, self._first, self._over_target = "run", True, None
        self._idle_pc = -1

    def unload(self, keep_memory: bool = False):
        """Forget the program (used when the source is replaced) and wipe memory, or with ``keep_memory`` only
        remove the program's own unchanged bytes."""
        if keep_memory:
            self._remove_program_bytes()
            self.cpu.mem.clear_stats()
        else:
            self.cpu.mem.clear()
        self.program = None
        self.reset_cpu()

    def reload_program_bytes(self):
        """Re-write the assembled bytes (used by 'restart' to undo self-modifying code)."""
        if self.program:
            for addr, byte in self.program.image.items():
                self.cpu.mem.data[addr] = byte

    # ------------------------------------------------------ line mapping
    def current_line(self) -> int | None:
        return self.program.addr_to_line.get(self.cpu.pc) if self.program else None

    def next_instruction(self) -> str:
        text, _, _ = disassemble(self.cpu.mem.data, self.cpu.pc)
        return text

    def symbol_for(self, addr: int) -> str | None:
        """'label' or 'label+n' for an address inside the program."""
        if not self.program:
            return None
        best = None
        for s in self.program.symbols.values():
            if s.kind in ("label", "data") and s.value <= addr and (best is None or s.value > best.value):
                best = s
        if best is None or addr - best.value > 0x40:
            return None
        off = addr - best.value
        return best.name if off == 0 else f"{best.name}+{off}"

    # -------------------------------------------------------- execution
    def start(self, mode: str):
        """Prepare a run. ``mode`` is run | into | over | out."""
        self._mode = mode
        self._first = True
        self._start_icount = self.cpu.icount
        self._over_target = None
        self._out_depth = 0
        self.last_error = ""

    def stop_reason_text(self, why: Stop) -> str:
        if why is Stop.ILLEGAL:
            return self.last_error
        if why is Stop.LOOP:
            return f"Infinite loop: the instruction at {self.cpu.pc:04X}h jumps to itself"
        if why is Stop.LIMIT:
            return f"Stopped after {self.max_instructions:,} instructions (limit in Preferences)"
        return why.value

    def run_chunk(self, budget: int) -> Stop | None:
        """Run up to ``budget`` instructions. Returns why it stopped, or None to continue."""
        cpu = self.cpu
        bps = self.breakpoints
        mode = self._mode
        limit = self.max_instructions
        n = 0
        try:
            while n < budget:
                pc0, sp0, irq0 = cpu.pc, cpu.sp, cpu.irq_taken
                op = cpu.mem.data[pc0]
                ic0, tt0 = cpu.icount, cpu.tstates
                res = cpu.step()
                if self.trace_on and (cpu.icount != ic0 or cpu.irq_taken != irq0):
                    self._record(pc0, ic0, tt0, irq0)
                if res == HALT:
                    return Stop.HALT
                n += 1
                first, self._first = self._first, False
                irq = cpu.irq_taken != irq0  # this step vectored to an interrupt
                if mode == "into":
                    return Stop.STEP
                if mode == "over":
                    if first:
                        if not irq and op in CALL_OPCODES and cpu.sp == (sp0 - 2) & 0xFFFF:
                            self._over_target = (self._return_address(pc0, op), sp0)
                        else:
                            return Stop.STEP
                    elif self._over_target and cpu.pc == self._over_target[0] \
                            and cpu.sp == self._over_target[1]:
                        return Stop.STEP
                elif mode == "out":
                    if irq:
                        self._out_depth += 1
                    elif op in CALL_OPCODES and cpu.sp == (sp0 - 2) & 0xFFFF:
                        self._out_depth += 1
                    elif op in RET_OPCODES and cpu.sp == (sp0 + 2) & 0xFFFF:
                        if self._out_depth == 0:
                            return Stop.STEP
                        self._out_depth -= 1
                if cpu.pc in bps:
                    return Stop.BREAKPOINT
                if cpu.pc == pc0 and cpu.sp == sp0 and not irq and self.stop_on_idle_loop \
                        and not cpu.ie and not cpu.pending and cpu.pc != self._idle_pc:
                    self._idle_pc = cpu.pc  # report once; a second Run keeps spinning
                    return Stop.LOOP
                if limit and cpu.icount - self._start_icount >= limit:
                    return Stop.LIMIT
        except IllegalOpcode as e:
            self.last_error = str(e)
            return Stop.ILLEGAL
        return None

    @staticmethod
    def _return_address(pc0: int, op: int) -> int:
        # CALL/Ccc are 3 bytes, RST is 1 byte
        return (pc0 + (1 if (op & 0xC7) == 0xC7 else 3)) & 0xFFFF

    # convenience wrappers used by tests and scripting -------------------
    def run_to_end(self, max_instructions: int = 5_000_000) -> Stop:
        self.start("run")
        done = 0
        while True:
            r = self.run_chunk(10_000)
            done += 10_000
            if r is not None:
                return r
            if done >= max_instructions:
                return Stop.LIMIT

    def step_into(self) -> Stop:
        self.start("into")
        return self.run_chunk(1) or Stop.STEP

    def step_over(self, budget: int = 5_000_000) -> Stop:
        self.start("over")
        return self._finish(budget)

    def step_out(self, budget: int = 5_000_000) -> Stop:
        self.start("out")
        return self._finish(budget)

    def _finish(self, budget: int) -> Stop:
        done = 0
        while done < budget:
            r = self.run_chunk(1000)
            done += 1000
            if r is not None:
                return r
        return Stop.LIMIT
