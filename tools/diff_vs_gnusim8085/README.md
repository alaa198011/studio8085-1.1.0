# Differential test against the original GNUSim8085 CPU core

Runs every legal 8085 opcode on identical random machine states in Studio8085 and in the original
GNUSim8085 C core, then compares registers, flags, memory windows, the stack and all I/O ports.

```bash
./build.sh /path/to/GNUSim8085-master/src      # builds libref.so (needs gcc + libglib2.0-dev)
python diff_test.py                            # 400 random cases per opcode, ~95,000 runs
```

Skipped on purpose (the GNUSim8085 core does not implement them or gets them wrong, see
`docs/COMPATIBILITY.md`): `RST n`, `RIM`, `SIM`, `DAA`; the auxiliary-carry flag after
`SUB/SBB/CMP/SUI/SBI/CPI/DCR`; the carry/AC corner of `ADC/SBB/ACI/SBI` when the operand is `FFh`
and carry is set.

A passing run prints `mismatches: 0`.
