"""A browsable catalog of the instruction set, for the Instructions panel.

GUI-free. Every entry is derived from the one opcode table in :mod:`opcodes`, so the opcode a
student sees in the list is, by construction, the byte the assembler produces for the text that
a click inserts (``tests/test_catalog.py`` assembles all 246 insert templates to prove it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .opcodes import BY_MNEMONIC, CC, INFO, TABLE, Instr

CATEGORIES = ("Data transfer", "Arithmetic", "Logic and rotate", "Branch", "Stack, I/O and control")

# The instructions the beginner examples use (docs/EXAMPLES.md); tests/test_beginner_examples.py
# checks that the beginner programs together cover every one of them.
ESSENTIAL = frozenset({
    "MVI", "MOV", "LXI", "LDA", "STA", "STAX", "XCHG", "PUSH", "POP",
    "ADD", "ADI", "ADC", "SUB", "SUI", "INR", "DCR", "INX", "DCX", "DAD",
    "ANI", "ORI", "XRI", "XRA", "ORA", "CMA", "CPI", "RLC", "RAR", "STC", "CMC",
    "JMP", "JZ", "JC", "JNZ", "CALL", "RET", "IN", "OUT", "NOP", "HLT",
})

_JUMP_ORDER = ("Z", "NZ", "C", "NC", "P", "M", "PE", "PO")  # the common conditions first
assert sorted(_JUMP_ORDER) == sorted(CC)


def _branch_order() -> list[str]:
    out = ["JMP"] + ["J" + c for c in _JUMP_ORDER]
    out += ["CALL"] + ["C" + c for c in _JUMP_ORDER]
    out += ["RET"] + ["R" + c for c in _JUMP_ORDER]
    return out + ["RST", "PCHL"]


_ORDER: dict[str, list[str]] = {
    "Data transfer": ["MOV", "MVI", "LXI", "LDA", "STA", "LDAX", "STAX", "LHLD", "SHLD", "XCHG"],
    "Arithmetic": ["ADD", "ADI", "ADC", "ACI", "SUB", "SUI", "SBB", "SBI", "INR", "DCR", "INX", "DCX",
                   "DAD", "DAA"],
    "Logic and rotate": ["ANA", "ANI", "ORA", "ORI", "XRA", "XRI", "CMP", "CPI", "CMA", "RLC", "RRC",
                         "RAL", "RAR", "STC", "CMC"],
    "Branch": _branch_order(),
    "Stack, I/O and control": ["PUSH", "POP", "XTHL", "SPHL", "IN", "OUT", "NOP", "HLT", "EI", "DI",
                               "RIM", "SIM"],
}
_CATEGORY_OF = {mn: cat for cat, mns in _ORDER.items() for mn in mns}
assert set(_CATEGORY_OF) == set(BY_MNEMONIC), set(BY_MNEMONIC) ^ set(_CATEGORY_OF)
assert sum(len(v) for v in _ORDER.values()) == len(BY_MNEMONIC)  # none listed twice

_PLACEHOLDER_16 = "0000h"
_PLACEHOLDER_8 = "00h"
_PLACEHOLDER_LABEL = "label"
_ADDRESS_LIKE = {"LDA", "STA", "LHLD", "SHLD"}


def category_of(mnemonic: str) -> str:
    return _CATEGORY_OF[mnemonic]


def _is_branch(mn: str) -> bool:
    return _CATEGORY_OF[mn] == "Branch"


@dataclass(frozen=True)
class Form:
    """One concrete opcode, e.g. ``MOV A,B`` = 78h."""

    opcode: int
    mnemonic: str
    label: str            # shown in the list: "MVI A,data8"
    key: str              # searchable text without placeholders: "mvi a"
    insert: str           # text a click puts in the editor: "mvi   a,00h"
    select: tuple[int, int] | None  # (start, length) of the placeholder inside ``insert``
    length: int           # bytes
    tstates: int
    taken_extra: int = 0
    operand_bytes: str = ""  # "dd", "lo hi", "pp" ...

    @property
    def hex(self) -> str:
        return f"{self.opcode:02X}"

    @property
    def binary(self) -> str:
        b = f"{self.opcode:08b}"
        return f"{b[:4]} {b[4:]}"

    @property
    def machine_code(self) -> str:
        """The bytes this instruction occupies, e.g. ``3E dd``."""
        return f"{self.hex} {self.operand_bytes}".strip()

    @property
    def timing(self) -> str:
        """T-states; conditional jumps/calls/returns show not-taken/taken."""
        return f"{self.tstates}/{self.tstates + self.taken_extra}" if self.taken_extra else str(self.tstates)


@dataclass(frozen=True)
class Entry:
    """One mnemonic with all of its encodings."""

    mnemonic: str
    category: str
    syntax: str
    description: str
    flags: str
    forms: tuple[Form, ...]

    @property
    def essential(self) -> bool:
        return self.mnemonic in ESSENTIAL

    @property
    def single(self) -> bool:
        return len(self.forms) == 1

    @property
    def timing(self) -> str:
        times = sorted({f.timing for f in self.forms}, key=lambda s: int(s.split("/")[0]))
        return times[0] if len(times) == 1 else f"{times[0]}-{times[-1]}"

    @property
    def length(self) -> int:
        return self.forms[0].length  # every encoding of one mnemonic has the same length


def _form(ins: Instr) -> Form:
    mn = ins.mnemonic
    shown, typed, key = [], [], []
    placeholder = None
    op_bytes = ""
    for tok in ins.operands:
        if tok == "#8":
            name = "port" if mn in ("IN", "OUT") else "data8"
            shown.append(name)
            typed.append(_PLACEHOLDER_8)
            placeholder = len(typed) - 1
            op_bytes = "pp" if mn in ("IN", "OUT") else "dd"
        elif tok == "#16":
            if _is_branch(mn):
                shown.append("addr")
                typed.append(_PLACEHOLDER_LABEL)
            elif mn in _ADDRESS_LIKE:
                shown.append("addr")
                typed.append(_PLACEHOLDER_16)
            else:
                shown.append("data16")
                typed.append(_PLACEHOLDER_16)
            placeholder = len(typed) - 1
            op_bytes = "lo hi"
        else:
            shown.append(tok)
            typed.append(tok.lower())
            key.append(tok.lower())
    label = f"{mn} {','.join(shown)}".strip()
    head = f"{mn.lower():<6}"
    body = ",".join(typed)
    text = (head + body) if body else mn.lower()
    select = None
    if placeholder is not None:
        start = len(head) + len(",".join(typed[:placeholder])) + (1 if placeholder else 0)
        select = (start, len(typed[placeholder]))
    return Form(ins.opcode, mn, label, (mn.lower() + " " + " ".join(key)).strip(), text, select,
                ins.length, ins.tstates, ins.taken_extra, op_bytes)


def build_catalog() -> list[Entry]:
    """Every mnemonic, grouped by category in teaching order."""
    out = []
    for cat in CATEGORIES:
        for mn in _ORDER[cat]:
            syntax, desc, flags = INFO[mn]
            forms = tuple(_form(i) for i in sorted(BY_MNEMONIC[mn], key=lambda i: i.opcode))
            out.append(Entry(mn, cat, syntax, desc, flags, forms))
    return out


CATALOG: list[Entry] = build_catalog()
SCOPE_ESSENTIAL = "Essential"
SCOPE_ALL = "All"
SCOPES = (SCOPE_ESSENTIAL, SCOPE_ALL, *CATEGORIES)

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _token(tok: str) -> str:
    tok = tok.removeprefix("0x")
    return tok[:-1] if re.fullmatch(r"[0-9a-f]{1,2}h", tok) else tok  # "3Eh" -> "3e"


def in_scope(entry: Entry, scope: str) -> bool:
    if scope == SCOPE_ALL:
        return True
    if scope == SCOPE_ESSENTIAL:
        return entry.essential
    return entry.category == scope


def search(query: str = "", scope: str = SCOPE_ALL,
           catalog: list[Entry] | None = None) -> list[tuple[Entry, tuple[Form, ...]]]:
    """Entries (with the forms to show) that fit ``scope`` and ``query``.

    The first of these that finds anything wins, so typing more narrows the list:

    1. the words typed begin the instruction in order: ``mov a`` -> MOV A,x; ``mov b,a`` -> MOV B,A;
    2. an opcode in hex: ``78``, ``78h``, ``0x3E``;
    3. the words typed begin any word of the instruction, in any order: ``sp``;
    4. the description, so a student can find an instruction by what it does: ``carry``, ``rotate``.
    """
    catalog = CATALOG if catalog is None else catalog
    scoped = [e for e in catalog if in_scope(e, scope)]
    raw = [t for t in re.split(r"[\s,]+", query.strip().lower()) if t]
    if not raw:
        return [(e, e.forms) for e in scoped]
    tokens = [_token(t) for t in raw]

    def forms_where(test):
        out = []
        for e in scoped:
            fs = tuple(f for f in e.forms if test(f))
            if fs:
                out.append((e, fs))
        return out

    def ordered(f: Form) -> bool:
        words = _words(f.key)
        return len(tokens) <= len(words) and all(w.startswith(t) for w, t in zip(words, tokens))

    def anywhere(f: Form) -> bool:
        words = _words(f.key)
        return all(any(w.startswith(t) for w in words) for t in tokens)

    for test in (ordered,
                 lambda f: len(tokens) == 1 and bool(re.fullmatch(r"[0-9a-f]{1,2}", tokens[0]))
                 and f.hex.lower().startswith(tokens[0]),
                 anywhere):
        found = forms_where(test)
        if found:
            return found
    text_hit = lambda e: all(any(w.startswith(t) for w in _words(
        f"{e.description} {e.category} {e.syntax} {e.flags}")) for t in tokens)
    return [(e, e.forms) for e in scoped if text_hit(e)]


def describe(entry: Entry, form: Form | None = None) -> str:
    """One paragraph for the detail line under the list."""
    f = form or entry.forms[0]
    head = f.label if form else entry.syntax
    bits = (f"Opcode {f.hex}h = {f.binary}b" if form or entry.single else
            f"{len(entry.forms)} opcodes between {entry.forms[0].hex}h and {entry.forms[-1].hex}h")
    size = f"{f.length} byte{'s' if f.length != 1 else ''}"
    code = f" ({f.machine_code})" if form or entry.single else ""
    return (f"{head}: {entry.description}  {bits}, {size}{code}, {entry.timing if not form else f.timing} "
            f"T-states. Flags: {entry.flags}.")


# a single table lookup for the status bar: opcode byte -> Form
FORM_OF: dict[int, Form] = {f.opcode: f for e in CATALOG for f in e.forms}
assert len(FORM_OF) == sum(1 for i in TABLE if i) == 246
