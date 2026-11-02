"""Disassembler driven by the same opcode table as the assembler."""

from __future__ import annotations

from .opcodes import TABLE, format_operands


def disassemble(data, addr: int) -> tuple[str, int, bytes]:
    """Return ``(text, length, raw_bytes)`` for the instruction at ``addr``.

    ``data`` is any indexable of 64K bytes. Undefined opcodes come back as
    ``DB xxh`` with length 1.
    """
    addr &= 0xFFFF
    op = data[addr]
    ins = TABLE[op]
    if ins is None:
        return f"DB {op:02X}h", 1, bytes([op])
    raw = bytes(data[(addr + i) & 0xFFFF] for i in range(ins.length))
    imm = None
    if ins.length == 2:
        imm = raw[1]
    elif ins.length == 3:
        imm = raw[1] | raw[2] << 8
    ops = format_operands(ins, imm)
    return (f"{ins.mnemonic} {ops}" if ops else ins.mnemonic), ins.length, raw
