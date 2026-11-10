"""Visualization model for the Interactive CPU Architecture panel (Phase 2).

This module has no Qt in it and never changes the CPU. It is the middle layer between the simulator and the
drawing code:

    CPU / Machine  --(read-only)-->  StepRecorder  -->  StepRecord (immutable)  -->  Qt panel

* ``CpuState`` is an immutable snapshot of the registers, flags, SP, PC and counters.
* ``StepRecorder.begin()`` captures the pre-state, the debugger then runs the EXISTING engine, and
  ``StepRecorder.end()`` captures the post-state and diffs the two. Nothing here executes an instruction or
  calculates a result: every value shown is read from the simulator before or after the step.
* What the engine did not report is labelled ``conceptual``. The simulator is instruction-level; bus signals and
  micro-operations are not modelled, so ``Flow`` objects are teaching diagrams, drawn solid only when the state
  diff shows that their destination really changed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .disasm import disassemble
from .explain import explain_instruction, flag_notes
from .opcodes import TABLE

REG_ORDER = ("A", "B", "C", "D", "E", "H", "L")
FLAG_ORDER = ("S", "Z", "AC", "P", "CY")
PAIRS = {"BC": ("B", "C"), "DE": ("D", "E"), "HL": ("H", "L")}
_PAIR_OF_OPERAND = {"B": "BC", "D": "DE", "H": "HL", "SP": "SP", "PSW": "PSW"}
CONDITIONAL_JUMPS = frozenset({"JNZ", "JZ", "JNC", "JC", "JPO", "JPE", "JP", "JM"})

CONCEPTUAL = "conceptual explanation"

# ---------------------------------------------------------------- families
FAMILIES: dict[str, frozenset[str]] = {
    "Data transfer": frozenset({"MOV", "MVI", "LXI", "LDA", "STA", "LHLD", "SHLD"}),
    "Arithmetic": frozenset({"ADD", "ADC", "SUB", "SBB", "INR", "DCR", "INX", "DCX"}),
    "Logical": frozenset({"ANA", "ORA", "XRA", "CMP"}),
    "Control flow": frozenset({"JMP", "CALL", "RET"}) | CONDITIONAL_JUMPS,
    "Stack": frozenset({"PUSH", "POP"}),
    "I/O": frozenset({"IN", "OUT"}),
    "Other": frozenset({"NOP", "HLT"}),
}
DETAILED = {mn: fam for fam, mns in FAMILIES.items() for mn in mns}
_GENERIC_FAMILY = {
    "LDAX": "Data transfer", "STAX": "Data transfer", "XCHG": "Data transfer", "XTHL": "Stack", "SPHL": "Stack",
    "PCHL": "Control flow", "RST": "Control flow", "DAD": "Arithmetic", "DAA": "Arithmetic",
    "ADI": "Arithmetic", "ACI": "Arithmetic", "SUI": "Arithmetic", "SBI": "Arithmetic", "CPI": "Logical",
    "ANI": "Logical", "ORI": "Logical", "XRI": "Logical", "RLC": "Logical", "RRC": "Logical", "RAL": "Logical",
    "RAR": "Logical", "CMA": "Logical", "STC": "Logical", "CMC": "Logical", "EI": "Other", "DI": "Other",
    "RIM": "Other", "SIM": "Other",
}


def family_of(mnemonic: str) -> tuple[str, bool]:
    """(family name, has a detailed visual). Conditional CALL/RET and other mnemonics fall back to a generic view."""
    if mnemonic in DETAILED:
        return DETAILED[mnemonic], True
    if mnemonic in _GENERIC_FAMILY:
        return _GENERIC_FAMILY[mnemonic], False
    if len(mnemonic) > 1 and mnemonic[0] == "C":
        return "Control flow", False
    if len(mnemonic) > 1 and mnemonic[0] == "R":
        return "Control flow", False
    return "Other", False


# ---------------------------------------------------------------- snapshots
@dataclass(frozen=True)
class CpuState:
    """Immutable snapshot of the programmer-visible 8085 state."""

    regs: tuple[int, ...]  # A B C D E H L
    flags: tuple[int, ...]  # S Z AC P CY
    sp: int
    pc: int
    ie: bool
    halted: bool
    icount: int
    tstates: int

    def reg(self, name: str) -> int:
        return self.regs[REG_ORDER.index(name)]

    def flag(self, name: str) -> int:
        return self.flags[FLAG_ORDER.index(name)]

    def pair(self, name: str) -> int:
        hi, lo = PAIRS[name]
        return self.reg(hi) << 8 | self.reg(lo)

    def flag_byte(self) -> int:
        s, z, ac, p, cy = self.flags
        return (s << 7) | (z << 6) | (ac << 4) | (p << 2) | 2 | cy

    def flag_dict(self) -> dict[str, int]:
        return dict(zip(FLAG_ORDER, self.flags))

    def node_value(self, node: str) -> tuple[int, int] | None:
        """(value, bits) shown on an architecture node, or None for nodes without a value."""
        if node in REG_ORDER:
            return self.reg(node), 8
        if node in PAIRS:
            return self.pair(node), 16
        if node == "PC":
            return self.pc, 16
        if node == "SP":
            return self.sp, 16
        if node == "FLAGS":
            return self.flag_byte(), 8
        return None


def capture_state(cpu) -> CpuState:
    r = cpu.regs
    return CpuState((r[7], r[0], r[1], r[2], r[3], r[4], r[5]), (cpu.s, cpu.z, cpu.ac, cpu.p, cpu.cy),
                    cpu.sp, cpu.pc, bool(cpu.ie), bool(cpu.halted), cpu.icount, cpu.tstates)


@dataclass(frozen=True)
class KitView:
    """What the Phase 1 Trainer Kit currently shows (read from the kit; never owned or changed here)."""

    enabled: bool = False
    switch_port: int = 0x00
    led_port: int = 0x01
    seg_port: int = 0x02
    switches: int = 0
    leds: int = 0
    leds_written: bool = False


def kit_view(kit) -> KitView:
    if kit is None:
        return KitView()
    return KitView(bool(kit.enabled), kit.switches.port, kit.leds.port, kit.display.port, kit.switches.value,
                   kit.leds.value, bool(kit.leds.written))


# ------------------------------------------------------------------- records
@dataclass(frozen=True)
class Access:
    kind: str  # "R" or "W"
    addr: int
    value: int
    observed: bool  # True: seen by the simulator's access counters/diff; False: expected from the instruction


@dataclass(frozen=True)
class PortEvent:
    direction: str  # "IN" or "OUT"
    port: int
    value: int
    observed: bool


@dataclass(frozen=True)
class Flow:
    """One conceptual data movement. ``observed`` means the state diff confirms the destination changed."""

    src: str
    dst: str
    kind: str  # data8 | data16 | addr16 | addr8 | ctl
    label: str
    phase: int  # 0 fetch, 1 operand/address, 2 execute, 3 write-back (animation order)
    observed: bool = False


@dataclass(frozen=True)
class StepRecord:
    seq: int
    kind: str  # instr | interrupt | multi | none
    mode: str  # into | over | out | run
    pre: CpuState
    post: CpuState
    text: str
    mnemonic: str
    family: str
    detailed: bool
    address: int
    length: int
    raw: bytes
    n_instr: int
    reg_changes: tuple[tuple[str, int, int], ...]
    flag_changes: tuple[tuple[str, int, int], ...]
    sp_change: tuple[int, int] | None
    pc_change: tuple[int, int] | None
    mem_accesses: tuple[Access, ...]
    mem_diff: tuple[tuple[int, int, int], ...]
    port_events: tuple[PortEvent, ...]
    flows: tuple[Flow, ...]
    roles: tuple[tuple[str, str], ...]  # node -> "src" | "dst" | "both"
    tags: tuple[tuple[str, str], ...]  # node -> short badge ("+1", "-2", "result discarded")
    summary: str
    details: tuple[str, ...]
    why: tuple[str, ...]
    flag_why: tuple[str, ...]
    taken: bool | None
    conceptual_steps: tuple[str, ...]
    tracking: bool

    @property
    def changed_nodes(self) -> frozenset[str]:
        return changed_nodes_of(self.reg_changes, self.flag_changes, self.sp_change, self.pc_change)

    @property
    def role_map(self) -> dict[str, str]:
        return dict(self.roles)

    @property
    def tag_map(self) -> dict[str, str]:
        return dict(self.tags)

    @property
    def involved(self) -> frozenset[str]:
        return frozenset(n for fl in self.flows for n in (fl.src, fl.dst)) | self.changed_nodes


def changed_nodes_of(reg_changes, flag_changes, sp_change, pc_change) -> frozenset[str]:
    s = {n for n, _, _ in reg_changes}
    if flag_changes:
        s.add("FLAGS")
    if sp_change:
        s.add("SP")
    if pc_change:
        s.add("PC")
    for pair, (hi, lo) in PAIRS.items():
        if hi in s or lo in s:
            s.add(pair)
    return frozenset(s)


class StepHistory:
    """A bounded list of the most recent step records (replay never re-executes the CPU)."""

    def __init__(self, limit: int = 200):
        self._items: deque[StepRecord] = deque(maxlen=limit)

    def add(self, rec: StepRecord):
        self._items.append(rec)

    def clear(self):
        self._items.clear()

    def __len__(self):
        return len(self._items)

    def __getitem__(self, i: int) -> StepRecord:
        return self._items[i]

    @property
    def latest(self) -> StepRecord | None:
        return self._items[-1] if self._items else None


# --------------------------------------------------------------- decoding
@dataclass(frozen=True)
class Decoded:
    text: str
    mnemonic: str
    operands: tuple[str, ...]
    length: int
    raw: bytes
    imm: int | None
    opcode: int
    valid: bool


def decode(data, pc: int) -> Decoded:
    text, length, raw = disassemble(data, pc)
    op = data[pc & 0xFFFF]
    ins = TABLE[op]
    if ins is None:
        return Decoded(text, "DB", (), 1, raw, None, op, False)
    imm = None
    if ins.length == 2:
        imm = raw[1]
    elif ins.length == 3:
        imm = raw[1] | raw[2] << 8
    return Decoded(text, ins.mnemonic, tuple(ins.operands), ins.length, raw, imm, op, True)


def _node(operand: str) -> str:
    return _PAIR_OF_OPERAND.get(operand, operand)


def candidate_addresses(dec: Decoded, pre: CpuState) -> tuple[int, ...]:
    """Memory addresses this instruction could read or write, from its operands and the pre-state.

    The step recorder does not trust this list as fact: an access counts as *observed* only if the memory
    counters of one of these addresses moved while the existing engine ran.
    """
    mn, ops = dec.mnemonic, dec.operands
    out: list[int] = []
    hl = pre.pair("HL")
    if "M" in ops:
        out.append(hl)
    if mn in ("LDAX", "STAX"):
        out.append(pre.pair(_node(ops[0])))
    if mn in ("LDA", "STA", "LHLD", "SHLD") and dec.imm is not None:
        out += [dec.imm, (dec.imm + 1) & 0xFFFF]
    if mn in ("PUSH", "CALL", "RST") or mn.startswith("C") and mn[1:] in ("NZ", "Z", "NC", "C", "PO", "PE", "P", "M"):
        out += [(pre.sp - 1) & 0xFFFF, (pre.sp - 2) & 0xFFFF]
    if mn in ("POP", "RET", "XTHL") or mn.startswith("R") and mn[1:] in ("NZ", "Z", "NC", "C", "PO", "PE", "P", "M"):
        out += [pre.sp, (pre.sp + 1) & 0xFFFF]
    if mn == "XTHL":
        out += [(pre.sp + 1) & 0xFFFF]
    return tuple(dict.fromkeys(a & 0xFFFF for a in out))


# ------------------------------------------------------------------ flows
def build_flows(dec: Decoded, pre: CpuState, post: CpuState, rec_taken: bool | None) -> tuple[
        list[Flow], dict[str, str], list[str]]:
    """Return (flows, tags, conceptual micro-steps) for a family with a detailed visual.

    Everything returned is a *conceptual* teaching model of where data logically travels for this instruction.
    """
    mn, o = dec.mnemonic, dec.operands
    flows: list[Flow] = []
    tags: dict[str, str] = {}
    steps: list[str] = []

    def f(src, dst, kind, label, phase):
        flows.append(Flow(src, dst, kind, label, phase))

    def fetch(extra: str = ""):
        f("PC", "MEM", "addr16", "PC supplies the address of the opcode" + extra, 0)
        f("MEM", "IR", "data8", "the opcode byte is placed in the Instruction Register", 0)
        steps.append(f"PC addresses memory; the opcode byte goes to the Instruction Register / Decoder{extra}.")

    fetch(" (and the operand bytes follow)" if dec.length > 1 else "")

    def mem_addr_from(reg_pair="HL"):
        f(reg_pair, "MEM", "addr16", f"{reg_pair} supplies the memory address", 1)

    if mn == "MOV":
        d, s = o
        if d != "M" and s != "M":
            f(s, d, "data8", f"copy {s} into {d}", 2)
            steps.append(f"The value in {s} is copied into {d}; {s} is unchanged.")
        elif s == "M":
            mem_addr_from()
            f("MEM", d, "data8", f"memory byte at HL goes to {d}", 2)
            steps.append(f"HL addresses memory; the byte read there goes into {d}.")
        else:
            mem_addr_from()
            f(s, "MEM", "data8", f"{s} is written to memory at HL", 2)
            steps.append(f"HL addresses memory; {s} is written to that location.")
    elif mn == "MVI":
        d = o[0]
        if d == "M":
            mem_addr_from()
            f("IR", "MEM", "data8", "the immediate byte is written to memory at HL", 2)
        else:
            f("IR", d, "data8", f"the immediate byte from the instruction goes into {d}", 2)
        steps.append("The second byte of the instruction (the constant) is moved to the destination.")
    elif mn == "LXI":
        p = _node(o[0])
        f("IR", p, "data16", f"the 16-bit constant is loaded into {p}", 2)
        steps.append(f"The two operand bytes of the instruction (low byte first) become the 16-bit value in {p}.")
    elif mn == "LDA":
        f("IR", "MEM", "addr16", "the address operand of the instruction selects the memory byte", 1)
        f("MEM", "A", "data8", "the byte at that address is loaded into A", 2)
        steps.append("The 16-bit address in the instruction selects a memory byte; it is loaded into A.")
    elif mn == "STA":
        f("IR", "MEM", "addr16", "the address operand of the instruction selects the memory byte", 1)
        f("A", "MEM", "data8", "A is written to that address", 2)
        steps.append("The 16-bit address in the instruction selects a memory byte; A is stored there.")
    elif mn == "LHLD":
        f("IR", "MEM", "addr16", "the address operand selects two consecutive memory bytes", 1)
        f("MEM", "L", "data8", "the byte at addr goes to L", 2)
        f("MEM", "H", "data8", "the byte at addr+1 goes to H", 2)
        steps.append("The byte at addr goes to L and the byte at addr+1 goes to H.")
    elif mn == "SHLD":
        f("IR", "MEM", "addr16", "the address operand selects two consecutive memory bytes", 1)
        f("L", "MEM", "data8", "L is written to addr", 2)
        f("H", "MEM", "data8", "H is written to addr+1", 2)
        steps.append("L is stored at addr and H is stored at addr+1.")
    elif mn in ("ADD", "ADC", "SUB", "SBB", "ANA", "ORA", "XRA", "CMP"):
        r = o[0]
        if r == "M":
            mem_addr_from()
            f("MEM", "ALU", "data8", "the memory byte at HL is the second ALU operand", 1)
        else:
            f(r, "ALU", "data8", f"{r} is the second ALU operand", 1)
        f("A", "ALU", "data8", "A is the first ALU operand", 1)
        if mn in ("ADC", "SBB"):
            f("FLAGS", "ALU", "ctl", "the Carry flag is an extra input", 1)
        if mn == "CMP":
            f("ALU", "FLAGS", "ctl", "only the flags are updated (the result is discarded)", 2)
            tags["A"] = "unchanged"
            steps.append("The ALU subtracts internally to compare; the result is thrown away and only the flags change.")
        else:
            f("ALU", "A", "data8", "the ALU result is written back to A", 2)
            f("ALU", "FLAGS", "ctl", "the flags are updated from the result", 2)
            verb = {"ADD": "adds", "ADC": "adds with carry", "SUB": "subtracts", "SBB": "subtracts with borrow",
                    "ANA": "ANDs", "ORA": "ORs", "XRA": "XORs"}[mn]
            steps.append(f"The ALU {verb} the two operands; the result goes to A and the flags are updated.")
    elif mn in ("INR", "DCR"):
        r = o[0]
        sign = "+1" if mn == "INR" else "-1"
        if r == "M":
            mem_addr_from()
            f("MEM", "ALU", "data8", "the memory byte at HL is read", 1)
            f("ALU", "MEM", "data8", f"the byte {sign} is written back to memory", 2)
        else:
            f(r, "ALU", "data8", f"{r} goes to the ALU", 1)
            f("ALU", r, "data8", f"{r} {sign} is written back to {r}", 2)
        f("ALU", "FLAGS", "ctl", "S, Z, AC, P are updated (CY is not changed)", 2)
        tags[r if r != "M" else "ALU"] = sign
        steps.append(f"The ALU adds {sign} to the value; the result is written back and S, Z, AC, P are updated; CY is not touched.")
    elif mn in ("INX", "DCX"):
        p = _node(o[0])
        sign = "+1" if mn == "INX" else "-1"
        f(p, p, "data16", f"the 16-bit pair {p} changes by {sign}", 2)
        tags[p] = sign
        steps.append(f"The 16-bit register pair {p} is changed by {sign}. No flags are affected.")
    elif mn in CONDITIONAL_JUMPS or mn == "JMP":
        if mn in CONDITIONAL_JUMPS:
            f("FLAGS", "IR", "ctl", f"the decoder tests the flag for {mn}", 1)
            steps.append(f"The condition for {mn} is tested against the flags.")
        if mn == "JMP" or rec_taken:
            f("IR", "PC", "addr16", "the jump address replaces PC", 2)
            steps.append("The 16-bit address in the instruction is loaded into PC.")
        else:
            steps.append("The condition was false, so PC simply moves to the next instruction.")
    elif mn == "CALL":
        f("PC", "MEM", "data16", "the return address is pushed on the stack", 1)
        f("SP", "MEM", "addr16", "SP addresses the stack in memory", 1)
        f("IR", "PC", "addr16", "the call address replaces PC", 2)
        tags["SP"] = "-2"
        steps.append("The address of the next instruction is pushed (SP decreases by 2); then PC is loaded with the call address.")
    elif mn == "RET":
        f("SP", "MEM", "addr16", "SP addresses the return address on the stack", 1)
        f("MEM", "PC", "data16", "the return address is popped into PC", 2)
        tags["SP"] = "+2"
        steps.append("Two bytes are popped from the stack into PC (SP increases by 2).")
    elif mn == "PUSH":
        p = _node(o[0])
        f("SP", "MEM", "addr16", "SP addresses the stack", 1)
        if p == "PSW":
            f("A", "MEM", "data8", "A is pushed (high byte)", 2)
            f("FLAGS", "MEM", "data8", "the flag byte is pushed (low byte)", 2)
        else:
            f(p, "MEM", "data16", f"{p} is pushed (high byte first)", 2)
        tags["SP"] = "-2"
        steps.append("SP decreases by 2 and the register pair is written to the stack (high byte at the higher address).")
    elif mn == "POP":
        p = _node(o[0])
        f("SP", "MEM", "addr16", "SP addresses the stack", 1)
        if p == "PSW":
            f("MEM", "A", "data8", "the byte at SP+1 goes to A", 2)
            f("MEM", "FLAGS", "data8", "the byte at SP restores the flags", 2)
        else:
            f("MEM", p, "data16", f"the two stack bytes go into {p}", 2)
        tags["SP"] = "+2"
        steps.append("Two bytes are read from the stack into the register pair, then SP increases by 2.")
    elif mn == "IN":
        f("IR", "PORT_IN", "addr8", "the port number comes from the instruction", 1)
        f("PORT_IN", "A", "data8", "the byte at the input port goes into A", 2)
        steps.append("The port number in the instruction selects an input port; its byte is loaded into A. No flags change.")
    elif mn == "OUT":
        f("IR", "PORT_OUT", "addr8", "the port number comes from the instruction", 1)
        f("A", "PORT_OUT", "data8", "A is sent to the output port", 2)
        steps.append("A is copied to the output port named in the instruction. No flags change, A is unchanged.")
    elif mn == "NOP":
        steps.append("Nothing happens except that PC moves to the next instruction.")
    elif mn == "HLT":
        tags["IR"] = "halted"
        steps.append("The CPU stops fetching instructions until an interrupt or reset.")
    return flows, tags, steps


def _mark_observed(flows: list[Flow], changed: frozenset[str], accesses: tuple[Access, ...],
                   ports: tuple[PortEvent, ...]) -> list[Flow]:
    """A flow is drawn solid only when the simulator's own evidence confirms its destination: a changed register,
    flag, PC or SP, a memory counter that moved, or a port event. Fetch and ALU-input flows are conceptual."""
    reads = any(a.kind == "R" and a.observed for a in accesses)
    writes = any(a.kind == "W" and a.observed for a in accesses)
    port_seen = any(p.observed for p in ports)

    def seen(fl: Flow) -> bool:
        if fl.phase == 0 or fl.dst == "ALU" and fl.src != "MEM":
            return False
        if fl.src == fl.dst:
            return fl.dst in changed
        if fl.dst == "MEM":
            return writes if fl.kind != "addr16" else (reads or writes)
        if fl.src == "MEM":
            return reads if fl.dst in ("ALU", "IR") else reads and fl.dst in changed
        if "PORT_IN" in (fl.src, fl.dst) or "PORT_OUT" in (fl.src, fl.dst):
            return port_seen
        if fl.dst == "IR":
            return False
        return fl.dst in changed

    first = [seen(fl) for fl in flows]
    alu_out = any(ok and fl.src == "ALU" for fl, ok in zip(flows, first))
    out = []
    for fl, ok in zip(flows, first):
        if fl.dst == "ALU":
            ok = alu_out or (fl.src == "MEM" and reads)
        out.append(Flow(fl.src, fl.dst, fl.kind, fl.label, fl.phase, bool(ok)))
    return out


# ------------------------------------------------------------- the recorder
def _hx(v: int, w: int = 2) -> str:
    return f"{v:0{w}X}h"


class StepRecorder:
    """Passive instrumentation around a debugger action.

    ``begin(mode)`` is called just before the Machine runs; ``end()`` just after. Neither touches the CPU: they
    read registers, flags, the memory access counters and the Machine's OUT log, and they never raise into the
    caller (a failure is stored in ``last_error`` and the step is simply not recorded).
    """

    def __init__(self, machine, history_limit: int = 200):
        self.machine = machine
        self.enabled = True
        self.history = StepHistory(history_limit)
        self.last_error = ""
        self.seq = 0
        self._pending: dict | None = None

    def reset(self):
        self.history.clear()
        self._pending = None

    # ------------------------------------------------------------ begin
    def begin(self, mode: str):
        self._pending = None
        if not self.enabled:
            return
        try:
            m = self.machine
            cpu = m.cpu
            pre = capture_state(cpu)
            dec = decode(cpu.mem.data, cpu.pc)
            single = mode == "into"
            expl = None
            if single and dec.valid:
                try:
                    expl = explain_instruction(TABLE[dec.opcode], dec.raw, cpu)
                except Exception:  # explanation text is optional
                    expl = None
            cands = candidate_addresses(dec, pre) if single else ()
            mem = cpu.mem
            counters = {a: (mem.rd[a], mem.wr[a], mem.data[a]) for a in cands} if mem.track else \
                {a: (None, None, mem.data[a]) for a in cands}
            self._pending = {
                "mode": mode, "pre": pre, "dec": dec, "expl": expl, "irq": cpu.irq_taken, "cands": cands,
                "counters": counters, "out_count": m.out_count, "track": mem.track,
                "ac_borrow": bool(getattr(cpu, "ac_borrow_style", False)),
                "mem": bytes(mem.data) if mode in ("into", "over", "out") else None,
            }
        except Exception as e:  # pragma: no cover - defensive; must never disturb the debugger
            self.last_error = f"begin: {e}"
            self._pending = None

    # -------------------------------------------------------------- end
    def end(self) -> StepRecord | None:
        p, self._pending = self._pending, None
        if p is None or not self.enabled:
            return None
        try:
            rec = self._build(p)
        except Exception as e:  # pragma: no cover - defensive
            self.last_error = f"end: {e}"
            return None
        if rec is not None:
            self.history.add(rec)
        return rec

    def _build(self, p: dict) -> StepRecord | None:
        m = self.machine
        cpu = m.cpu
        post = capture_state(cpu)
        pre: CpuState = p["pre"]
        dec: Decoded = p["dec"]
        mode = p["mode"]
        n = post.icount - pre.icount
        irq = cpu.irq_taken != p["irq"]
        if n == 0 and not irq:
            kind = "none"
        elif irq and n == 0 or irq and mode == "into":
            kind = "interrupt"
        elif n == 1 and mode == "into":
            kind = "instr"
        else:
            kind = "multi"
        self.seq += 1

        reg_changes = tuple((r, pre.reg(r), post.reg(r)) for r in REG_ORDER if pre.reg(r) != post.reg(r))
        flag_changes = tuple((fl, pre.flag(fl), post.flag(fl)) for fl in FLAG_ORDER if pre.flag(fl) != post.flag(fl))
        sp_change = (pre.sp, post.sp) if pre.sp != post.sp else None
        pc_change = (pre.pc, post.pc) if pre.pc != post.pc else None

        mem_diff: tuple[tuple[int, int, int], ...] = ()
        if p["mem"] is not None:
            before, after = p["mem"], cpu.mem.data
            if before != after:
                diff = []
                for i in range(65536):  # only reached when something changed; bounded below
                    if before[i] != after[i]:
                        diff.append((i, before[i], after[i]))
                        if len(diff) >= 64:
                            break
                mem_diff = tuple(diff)

        accesses: list[Access] = []
        if kind == "instr":
            mem = cpu.mem
            for a in p["cands"]:
                rd0, wr0, v0 = p["counters"][a]
                if p["track"] and mem.track and rd0 is not None:
                    if mem.rd[a] != rd0:
                        accesses.append(Access("R", a, mem.data[a], True))
                    if mem.wr[a] != wr0:
                        accesses.append(Access("W", a, mem.data[a], True))
                elif mem.data[a] != v0:
                    accesses.append(Access("W", a, mem.data[a], True))  # no counters: only changes are provable
        ports: list[PortEvent] = []
        if kind == "instr" and dec.mnemonic == "IN" and dec.imm is not None:
            ports.append(PortEvent("IN", dec.imm, post.reg("A"), True))
        new_out = m.out_count - p["out_count"]
        if new_out > 0:
            for _ic, port, value in m.out_log[-min(new_out, len(m.out_log)):][-8:]:
                ports.append(PortEvent("OUT", port, value, True))
        elif kind == "instr" and dec.mnemonic == "OUT" and dec.imm is not None:
            ports.append(PortEvent("OUT", dec.imm, pre.reg("A"), False))
        mem_accesses = tuple(accesses)
        port_events = tuple(ports)

        taken: bool | None = None
        flows: list[Flow] = []
        tags: dict[str, str] = {}
        steps: list[str] = []
        family, detailed = family_of(dec.mnemonic) if dec.valid else ("Other", False)
        text = dec.text
        if kind == "interrupt":
            family, detailed, text = "Interrupt", False, f"<interrupt> -> {post.pc:04X}h"
        elif kind == "multi":
            text = f"{dec.text}  (+{n - 1} more)" if n > 1 else dec.text
            detailed = False
        elif kind == "none":
            detailed = False
            text = "(no instruction executed - the CPU is halted)" if pre.halted else "(no instruction executed)"

        if kind == "instr" and dec.mnemonic in CONDITIONAL_JUMPS:
            extra = post.tstates - pre.tstates
            base = TABLE[dec.opcode].tstates
            taken = extra > base if extra != base else (post.pc != (pre.pc + dec.length) & 0xFFFF)
        if kind == "instr" and detailed:
            flows, tags, steps = build_flows(dec, pre, post, taken)

        flows = _mark_observed(flows, changed_nodes_of(reg_changes, flag_changes, sp_change, pc_change),
                               mem_accesses, port_events)
        roles: dict[str, str] = {}
        for fl in flows:
            if fl.phase == 0:  # the fetch is shown as an animation step; it does not mark PC/memory as "used"
                continue
            roles[fl.src] = "both" if roles.get(fl.src) in ("dst", "both") else "src"
            roles[fl.dst] = "both" if roles.get(fl.dst) in ("src", "both") else "dst"
        if kind == "instr" and detailed:
            roles["IR"] = "both" if roles.get("IR") == "src" else "dst"
        roles = {k: v for k, v in roles.items() if v}

        why, flag_why, summary, details = self._explain(p, dec, kind, pre, post, taken, n)
        return StepRecord(
            self.seq, kind, mode, pre, post, text, dec.mnemonic, family, detailed, pre.pc, dec.length, dec.raw, n,
            reg_changes, flag_changes, sp_change, pc_change, mem_accesses, mem_diff, port_events, tuple(flows),
            tuple(sorted(roles.items())), tuple(sorted(tags.items())), summary, tuple(details), tuple(why),
            tuple(flag_why), taken, tuple(steps), bool(p["track"]))

    # ------------------------------------------------------ explanation
    def _explain(self, p, dec: Decoded, kind: str, pre: CpuState, post: CpuState, taken, n: int):
        why: list[str] = []
        flag_why: list[str] = []
        summary, details = "", []
        expl = p.get("expl")
        if kind == "interrupt":
            summary = ("An interrupt was accepted before the next instruction: the CPU pushed PC on the stack and "
                       "jumped to the interrupt vector.")
            why.append(f"PC changed from {_hx(pre.pc, 4)} to {_hx(post.pc, 4)} and SP from {_hx(pre.sp, 4)} to "
                       f"{_hx(post.sp, 4)}; interrupts are disabled (IE=0) on entry.")
            return why, flag_why, summary, details
        if kind == "none":
            return ["Nothing executed: the CPU is halted. An interrupt or a restart wakes it."], [], \
                "The CPU is halted.", []
        if kind == "multi":
            summary = (f"{n:,} instructions ran in this action ({p['mode']}). The panel shows the exact state "
                       "before and after; use Step Into to see one instruction at a time.")
            return why, flag_why, summary, details
        if expl is not None:
            summary = expl.summary
            details = list(expl.details)
        mn = dec.mnemonic
        # why the result happened: use the observed values only
        for name, old, new in [(r, pre.reg(r), post.reg(r)) for r in REG_ORDER if pre.reg(r) != post.reg(r)]:
            why.append(f"{name} was {_hx(old)} and is now {_hx(new)} ({old} -> {new}), read from the CPU after the step.")
        if mn in ("ADD", "ADC", "SUB", "SBB", "ANA", "ORA", "XRA", "CMP") and len(dec.operands) == 1:
            r = dec.operands[0]
            second = _hx(pre.reg(r)) if r != "M" else "the memory byte at HL"
            verb = {"ADD": "added to", "ADC": "added (with carry) to", "SUB": "subtracted from", "SBB": "subtracted (with borrow) from",
                    "ANA": "ANDed with", "ORA": "ORed with", "XRA": "XORed with", "CMP": "compared with"}[mn]
            why.insert(0, f"The ALU took A = {_hx(pre.reg('A'))} and the second operand {second}; "
                          f"the operand was {verb} A.")
            if mn == "CMP":
                why.append("A was not modified: CMP only updates the flags.")
        if mn in ("INX", "DCX") and dec.operands:
            pnode = _node(dec.operands[0])
            if pnode in PAIRS:
                why.append(f"{pnode} was {_hx(pre.pair(pnode), 4)} and is now {_hx(post.pair(pnode), 4)}.")
        if mn in CONDITIONAL_JUMPS:
            cond = (expl.condition if expl and expl.condition else "")
            why.append(("The jump WAS taken: " if taken else "The jump was NOT taken: ")
                       + f"PC went from {_hx(pre.pc, 4)} to {_hx(post.pc, 4)}.")
        elif mn == "JMP":
            why.append(f"PC was loaded with the jump address: {_hx(pre.pc, 4)} -> {_hx(post.pc, 4)}.")
        elif mn in ("CALL", "RET", "PUSH", "POP"):
            why.append(f"SP moved from {_hx(pre.sp, 4)} to {_hx(post.sp, 4)}; PC from {_hx(pre.pc, 4)} to {_hx(post.pc, 4)}.")
        elif mn == "HLT":
            why.append("HLT stopped the CPU; no register, flag or memory value changed.")
        elif mn == "NOP":
            why.append("NOP did nothing except advance PC.")
        elif mn == "OUT":
            why.append("OUT copies A to the port; A and all flags are unchanged.")
        elif mn == "IN":
            why.append("IN loads A from the port; no flag is changed.")
        if not why:
            why.append("No register value changed (a new value equal to the old one, or the effect is on PC, memory or a port).")
        if len(why) == 1 and not (pre.pc != post.pc):
            pass
        pre_f, post_f = pre.flag_dict(), post.flag_dict()
        flag_why = flag_notes(mn, pre_f, post_f, post.reg("A"), bool(p.get("ac_borrow", False)))
        if not flag_why and mn not in ("NOP", "HLT"):
            unaffected = "Flags are unchanged by this step."
            flag_why = [unaffected]
        return why, flag_why, summary, details
