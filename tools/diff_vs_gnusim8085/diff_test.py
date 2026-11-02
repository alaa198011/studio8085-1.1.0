"""Differential test: Studio8085 CPU core vs the ORIGINAL GNUSim8085 C core (used as an oracle).

Build the oracle first:  ./build.sh /path/to/GNUSim8085/src   (needs gcc + glib dev files)
Run:                     python diff_test.py [cases_per_opcode] [seed]

Every legal opcode is run on identical random machine states in both cores and
the full register/flag/memory/IO result is compared. Behaviours where the C core
is known to deviate from the Intel manual are masked (and listed in the report):
  * AC after SUB/SBB/CMP/SUI/SBI/CPI/DCR (C core never sets it)
  * ADC/ACI/SBB/SBI AC, and the CY corner when operand == FFh with carry set
  * DAA (flags S/Z/P not updated by the C core)
  * RST n, RIM, SIM (not implemented in the C core)
"""
import ctypes
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from studio8085.core.cpu import CPU, HALT
from studio8085.core.opcodes import TABLE

lib = ctypes.CDLL(str(HERE / "libref.so"))
IntArr13 = ctypes.c_int * 13
IntArr14 = ctypes.c_int * 14

CODE, MEMW, STKW, JMPW = 0x2000, 0x4000, 0x5000, 0x6000
SKIP_ALL = {0x20, 0x30, 0x27} | {0xC7 | n << 3 for n in range(8)}
SUB_AC = set(range(0x90, 0xA0)) | set(range(0xB8, 0xC0)) | {0xD6, 0xDE, 0xFE} | {0x05 | d << 3 for d in range(8)}
ADC_SBB = set(range(0x88, 0x90)) | set(range(0x98, 0xA0)) | {0xCE, 0xDE}
MEM_OPS = {i.opcode for i in TABLE if i and "M" in i.operands} | {0x0A, 0x1A, 0x02, 0x12}
JUMPS = {i.opcode for i in TABLE if i and i.mnemonic[0] in "JC" and i.length == 3 and i.mnemonic not in ("CMA", "CMC")}
DATAADDR = {0x3A, 0x32, 0x2A, 0x22}
RETS = {i.opcode for i in TABLE if i and i.mnemonic[0] == "R" and i.length == 1 and i.mnemonic not in ("RLC", "RRC", "RAL", "RAR", "RIM", "RST")}
RETS |= {0xC9}


def one_case(rnd, ins, mine, stats):
    op = ins.opcode
    if op in SKIP_ALL:
        return
    regs = [rnd.randrange(256) for _ in range(7)]  # a b c d e h l
    flags = [rnd.randrange(2) for _ in range(5)]  # s z ac p cy
    sp = rnd.randrange(STKW + 0x10, STKW + 0xF0)
    if op in MEM_OPS:
        regs[5] = 0x40  # H
        if op in (0x0A, 0x02):
            regs[1] = 0x40  # B
        if op in (0x1A, 0x12):
            regs[3] = 0x40  # D
    if op == 0xE9:  # PCHL
        regs[5], regs[6] = 0x60, rnd.randrange(256)
    b1, b2 = rnd.randrange(256), rnd.randrange(256)
    if op in JUMPS:
        b1, b2 = rnd.randrange(256), 0x60
    elif op in DATAADDR:
        b1, b2 = rnd.randrange(0xFE), 0x40
    if op in ADC_SBB and flags[4]:
        if ins.length == 2:
            operand = b1
        else:
            memval = None  # filled below once the memory window exists
            operand = [regs[1], regs[2], regs[3], regs[4], regs[5], regs[6], None, regs[0]][op & 7]
        if operand == 0xFF:
            return  # known C-core corner: operand FFh with carry set
    prog = [op] + [b1, b2][: ins.length - 1] + [0x76]
    memw = bytes(rnd.randrange(256) for _ in range(0x100))
    if op in ADC_SBB and ins.length == 1 and (op & 7) == 6 and flags[4] and memw[regs[6]] == 0xFF:
        return
    stkw = bytearray(rnd.randrange(256) for _ in range(0x100))
    if op in RETS or op in (0xC1, 0xD1, 0xE1, 0xF1):
        pass
    if op in RETS:
        stkw[sp - STKW + 1] = 0x60
    io = bytes(rnd.randrange(256) for _ in range(256))
    jmpw = bytes([0x76]) * 0x100

    # ---- C core
    lib.ref_reset()
    lib.ref_load(MEMW, memw, 256)
    lib.ref_load(STKW, bytes(stkw), 256)
    lib.ref_load(JMPW, jmpw, 256)
    lib.ref_load(CODE, bytes(prog), len(prog))
    lib.ref_load_io(io)
    lib.ref_set(IntArr13(*regs, sp, *flags))
    lib.ref_run(CODE)
    out = IntArr14()
    lib.ref_get(out)
    cmem = ctypes.create_string_buffer(0x300)
    lib.ref_dump(MEMW, cmem, 0x100)
    cstk = ctypes.create_string_buffer(0x100)
    lib.ref_dump(STKW, cstk, 0x100)
    cio = ctypes.create_string_buffer(256)
    lib.ref_dump_io(cio)

    # ---- Python core
    cpu = mine
    cpu.reset()
    cpu.mem.data[MEMW:MEMW + 0x100] = memw
    cpu.mem.data[STKW:STKW + 0x100] = stkw
    cpu.mem.data[JMPW:JMPW + 0x100] = jmpw
    cpu.mem.data[CODE:CODE + len(prog)] = bytes(prog)
    cpu.io[:] = io
    a, b, c, d, e, h, l = regs
    cpu.regs[:] = [b, c, d, e, h, l, 0, a]
    cpu.sp = sp
    cpu.s, cpu.z, cpu.ac, cpu.p, cpu.cy = flags
    cpu.pc = CODE
    for _ in range(10):
        if cpu.step() == HALT:
            break
    mine_state = [cpu.regs[7], cpu.regs[0], cpu.regs[1], cpu.regs[2], cpu.regs[3], cpu.regs[4], cpu.regs[5],
                  cpu.sp, cpu.s, cpu.z, cpu.ac, cpu.p, cpu.cy, cpu.pc]
    names = ["a", "b", "c", "d", "e", "h", "l", "sp", "s", "z", "ac", "p", "cy", "pc"]
    bad = []
    for i, nme in enumerate(names):
        if nme == "ac" and (op in SUB_AC or op in ADC_SBB):
            continue
        if out[i] != mine_state[i]:
            bad.append((nme, out[i], mine_state[i]))
    if bytes(cmem.raw[:0x100]) != bytes(cpu.mem.data[MEMW:MEMW + 0x100]):
        bad.append(("memwin", None, None))
    if bytes(cstk.raw) != bytes(cpu.mem.data[STKW:STKW + 0x100]):
        bad.append(("stackwin", None, None))
    if bytes(cio.raw) != bytes(cpu.io):
        bad.append(("io", None, None))
    stats["cases"] += 1
    if bad:
        stats["bad"] += 1
        stats.setdefault("examples", []).append((ins.mnemonic, ins.operands, regs, flags, sp, b1, b2, bad))


def main(n_per_op=400, seed=85):
    rnd = random.Random(seed)
    mine = CPU()
    stats = {"cases": 0, "bad": 0}
    per_op = {}
    for ins in TABLE:
        if ins is None:
            continue
        before = stats["bad"]
        for _ in range(n_per_op):
            one_case(rnd, ins, mine, stats)
        per_op[ins.opcode] = stats["bad"] - before
    print(f"opcodes compared: {sum(1 for i in TABLE if i and i.opcode not in SKIP_ALL)} of 246 "
          f"(skipped {len(SKIP_ALL)}: RST x8, RIM, SIM, DAA)")
    print(f"cases run: {stats['cases']:,}   mismatches: {stats['bad']}")
    for ex in stats.get("examples", [])[:10]:
        print("  MISMATCH", ex)
    return stats["bad"]


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 85
    sys.exit(1 if main(n, seed) else 0)
