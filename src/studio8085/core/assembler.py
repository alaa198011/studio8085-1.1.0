"""Two-pass 8085 assembler with precise, column-accurate diagnostics.

``assemble()`` never raises on bad source: every problem becomes a
``Diagnostic`` and assembly continues, so an editor can show all errors at
once. Syntax::

    [label:] mnemonic [operand[,operand]] [; comment]
    name:  EQU  expression          ; constants
           ORG  4200h               ; set the address
           DB   1, 2Ah, 'A', "text" ; bytes
           DW   1234h, label        ; words (low byte first)
           DS   16                  ; reserve 16 zero bytes
           END  [entry_label]
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .compat import check_compat
from .expr import ExprError, UndefinedSymbol, evaluate
from .meta import parse_metadata
from .opcodes import (ALL_WORDS, BY_MNEMONIC, DIRECTIVE_INFO, DIRECTIVES, INFO,
                      MNEMONICS, RESERVED_REGISTERS, Instr)

ERROR = "error"
WARNING = "warning"
NOTE = "info"  # compatibility notes: shown, never block anything


@dataclass(frozen=True)
class Diagnostic:
    line: int  # 1-based
    start: int  # 0-based column
    end: int
    severity: str
    message: str


@dataclass
class Symbol:
    name: str
    value: int
    kind: str  # 'label' | 'equ' | 'data'
    line: int
    size: int = 0  # bytes, for data symbols


@dataclass(frozen=True)
class Region:
    """A run of bytes produced by one source line."""

    start: int
    size: int
    kind: str  # 'code' | 'data' | 'reserved'
    line: int


@dataclass
class ListingLine:
    line: int
    addr: int | None
    data: bytes
    text: str


@dataclass
class AsmResult:
    diagnostics: list[Diagnostic] = field(default_factory=list)
    image: dict[int, int] = field(default_factory=dict)  # address -> byte
    symbols: dict[str, Symbol] = field(default_factory=dict)  # UPPERCASE key
    addr_to_line: dict[int, int] = field(default_factory=dict)  # instruction starts
    line_to_addr: dict[int, int] = field(default_factory=dict)
    listing: list[ListingLine] = field(default_factory=list)
    entry: int = 0
    origin: int = 0
    regions: list[Region] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    # (start, size) of space reserved with a plain ``DS n`` (no fill value): it is storage, not initialised
    # data, so a loader that keeps memory leaves whatever is already there
    uninitialized: list[tuple[int, int]] = field(default_factory=list)

    @property
    def notes(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == NOTE]

    def region_at(self, addr: int) -> Region | None:
        for r in self.regions:
            if r.start <= addr < r.start + r.size:
                return r
        return None

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def size(self) -> int:
        return len(self.image)

    def segments(self) -> list[tuple[int, bytes]]:
        out: list[tuple[int, bytearray]] = []
        for a in sorted(self.image):
            if out and out[-1][0] + len(out[-1][1]) == a:
                out[-1][1].append(self.image[a])
            else:
                out.append((a, bytearray([self.image[a]])))
        return [(a, bytes(b)) for a, b in out]


# ------------------------------------------------------------------ parsing
@dataclass
class Span:
    text: str
    start: int
    end: int


@dataclass
class Parsed:
    line: int
    raw: str
    label: Span | None = None
    label_colon: bool = True
    op: Span | None = None
    operands: list[Span] = field(default_factory=list)


class _SyntaxProblem(Exception):
    def __init__(self, message, start, end):
        super().__init__(message)
        self.message, self.start, self.end = message, start, end


_LABEL_RE = re.compile(r"^\s*([A-Za-z_?@.][A-Za-z0-9_?@.]*)\s*:")
_WORD_RE = re.compile(r"\s*([A-Za-z_?@.][A-Za-z0-9_?@.]*)")


def find_comment(text: str) -> int:
    """Column of the ';' that starts the comment, or len(text)."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == ";":
            return i
    return len(text)


def split_operands(text: str, base: int) -> list[Span]:
    """Split on top-level commas (not inside quotes or parentheses)."""
    parts: list[Span] = []
    depth = 0
    quote = None
    start = 0
    flush_at = len(text)
    for i, ch in enumerate(text + ","):
        if i < flush_at:
            if quote:
                if ch == quote:
                    quote = None
                continue
            if ch in "'\"":
                quote = ch
                continue
            if ch == "(":
                depth += 1
                continue
            if ch == ")":
                depth -= 1
                continue
            if ch != "," or depth > 0:
                continue
        piece = text[start:i]
        lead = len(piece) - len(piece.lstrip())
        stripped = piece.strip()
        parts.append(Span(stripped, base + start + lead, base + start + lead + len(stripped)))
        start = i + 1
    return parts


def parse_line(raw: str, lineno: int) -> Parsed:
    code = raw[:find_comment(raw)]
    p = Parsed(lineno, raw)
    if not code.strip():
        return p
    pos = 0
    m = _LABEL_RE.match(code)
    if m:
        p.label = Span(m.group(1), m.start(1), m.end(1))
        pos = m.end()
    m = _WORD_RE.match(code, pos)
    if not m:
        rest = code[pos:].strip()
        if rest:
            s = code.index(rest, pos)
            raise _SyntaxProblem(f"Expected an instruction, found '{rest[0]}'", s, s + 1)
        return p
    word = m.group(1)
    if not p.label and word.upper() not in MNEMONICS and word.upper() not in DIRECTIVES:
        # "NAME EQU 5" / "TABLE DB 1,2" : a label written without a colon
        m2 = _WORD_RE.match(code, m.end())
        if m2 and m2.group(1).upper() in ("EQU", "DB", "DW", "DS"):
            p.label = Span(word, m.start(1), m.end(1))
            p.label_colon = False
            m = m2
            word = m.group(1)
    p.op = Span(word, m.start(1), m.end(1))
    rest = code[m.end():]
    if rest.strip():
        p.operands = split_operands(rest, m.end())
        for o in p.operands:
            if not o.text:
                raise _SyntaxProblem("Missing operand (empty value between commas)",
                                     o.start, o.start + 1)
    return p


# ---------------------------------------------------------------- assembler
def _hex(v: int, width: int = 4) -> str:
    return f"{v:0{width}X}h"


class _Assembler:
    def __init__(self, source: str, origin: int, compat: str = "off"):
        self.compat = compat
        self.parsed: list[Parsed] = []
        self.lines = source.splitlines()
        self.res = AsmResult(origin=origin & 0xFFFF, entry=origin & 0xFFFF)
        self.pc = origin & 0xFFFF
        self.owner: dict[int, int] = {}  # address -> source line that wrote it
        self.plan: list[tuple] = []  # (kind, parsed, pc, payload)
        self.deferred_equ: list[tuple[Parsed, Span]] = []
        self.entry_set = False
        self.end_entry: Span | None = None
        self.end_line = 0
        self.end_seen = False
        self.data_regions: dict[int, tuple[int, int]] = {}  # addr -> (size, line)

    # -- diagnostics ----------------------------------------------------
    def error(self, line, start, end, msg):
        self.res.diagnostics.append(Diagnostic(line, start, max(end, start + 1), ERROR, msg))

    def warn(self, line, start, end, msg):
        self.res.diagnostics.append(Diagnostic(line, start, max(end, start + 1), WARNING, msg))

    # -- symbols --------------------------------------------------------
    def lookup(self, name: str):
        s = self.res.symbols.get(name)
        return s.value if s else None

    def define(self, span: Span, line: int, value: int, kind: str):
        name = span.text
        up = name.upper()
        if up in RESERVED_REGISTERS:
            self.error(line, span.start, span.end, f"'{name}' is a register name and cannot be a label")
            return
        if up in MNEMONICS or up in DIRECTIVES:
            self.error(line, span.start, span.end, f"'{name}' is an instruction and cannot be a label")
            return
        old = self.res.symbols.get(up)
        if old:
            self.error(line, span.start, span.end,
                       f"'{name}' is already defined on line {old.line}")
            return
        self.res.symbols[up] = Symbol(name, value & 0xFFFF if kind == "label" else value, kind, line)

    def eval_now(self, span: Span, line: int, here: int):
        """Evaluate in pass 1 where forward references are not allowed."""
        try:
            return evaluate(span.text, self.lookup, here, RESERVED_REGISTERS)
        except UndefinedSymbol as e:
            self.error(line, span.start + e.start, span.start + e.end,
                       f"'{e.name}' must be defined before this line (forward references "
                       f"are not allowed here)")
        except ExprError as e:
            self.error(line, span.start + e.start, span.start + e.end, e.message)
        return None

    # -- passes ---------------------------------------------------------
    def run(self) -> AsmResult:
        parsed: list[Parsed] = []
        for n, raw in enumerate(self.lines, 1):
            if self.end_seen:
                parsed.append(Parsed(n, raw))
                continue
            try:
                p = parse_line(raw, n)
            except _SyntaxProblem as e:
                self.error(n, e.start, e.end, e.message)
                p = Parsed(n, raw)
            parsed.append(p)
            self.pass1(p)
        self.resolve_deferred()
        self.finish_symbols()
        for kind, p, pc, payload in self.plan:
            self.pass2(kind, p, pc, payload)
        self.build_listing(parsed)
        self.build_regions()
        self.parsed = parsed
        self.final_checks()
        self.apply_compat()
        self.res.metadata = parse_metadata(self.lines)
        return self.res

    def pass1(self, p: Parsed):
        op = p.op
        if op is None:
            if p.label:
                self.define(p.label, p.line, self.pc, "label")
            return
        word = op.text.upper()
        if word == "EQU":
            self.pass1_equ(p)
            return
        if p.label:
            self.define(p.label, p.line, self.pc, "label")
        if word in DIRECTIVES:
            getattr(self, "d_" + word.lower())(p)
        elif word in MNEMONICS:
            self.pass1_instr(p, word)
        else:
            msg = f"Unknown instruction '{op.text}'"
            close = difflib.get_close_matches(word, ALL_WORDS, n=1, cutoff=0.6)
            nxt = p.operands[0].text.split()[0].upper() if p.operands and p.operands[0].text.split() else ""
            if nxt in MNEMONICS or nxt in DIRECTIVES:
                msg += f" - if '{op.text}' is a label, put a ':' after it ({op.text}:)"
            elif close:
                msg += f" - did you mean {close[0]}?"
            self.error(p.line, op.start, op.end, msg)

    # -- directives (pass 1) -------------------------------------------
    def need_operands(self, p, low, high=None) -> bool:
        n = len(p.operands)
        high = low if high is None else high
        if low <= n <= high:
            return True
        word = p.op.text.upper()
        syntax = DIRECTIVE_INFO[word][0] if word in DIRECTIVE_INFO else INFO[word][0]
        if n == 0:
            self.error(p.line, p.op.start, p.op.end, f"{word} needs an operand ({syntax})")
        else:
            first = p.operands[min(high, n - 1)]
            last = p.operands[-1]
            self.error(p.line, first.start, last.end,
                       f"{word} takes {'no' if high == 0 else high} operand{'s' if high != 1 else ''}"
                       f" ({syntax}) but {n} were given")
        return False

    def d_org(self, p):
        if not self.need_operands(p, 1):
            return
        v = self.eval_now(p.operands[0], p.line, self.pc)
        if v is None:
            return
        if not 0 <= v <= 0xFFFF:
            self.error(p.line, p.operands[0].start, p.operands[0].end,
                       f"ORG address {v} is outside 0000h-FFFFh")
            return
        self.pc = v
        if p.label:  # "name: ORG x" labels the new address
            sym = self.res.symbols.get(p.label.text.upper())
            if sym:
                sym.value = v
        if not self.res.image and not self.entry_set:
            self.res.origin = v
            self.res.entry = v

    def d_db(self, p):
        if not self.need_operands(p, 1, 10**6):
            return
        size = 0
        for o in p.operands:
            size += len(o.text) - 2 if self._is_string(o.text) else 1
        self.plan.append(("db", p, self.pc, None))
        self.note_data(p, size)
        self.emit_placeholder(p, size)

    def d_dw(self, p):
        if not self.need_operands(p, 1, 10**6):
            return
        size = 2 * len(p.operands)
        self.plan.append(("dw", p, self.pc, None))
        self.note_data(p, size)
        self.emit_placeholder(p, size)

    def d_ds(self, p):
        if not self.need_operands(p, 1, 2):
            return
        n = self.eval_now(p.operands[0], p.line, self.pc)
        if n is None:
            return
        if not 0 <= n <= 0x10000:
            self.error(p.line, p.operands[0].start, p.operands[0].end,
                       f"DS size {n} is out of range (0-65536)")
            return
        fill = 0
        if len(p.operands) == 2:
            f = self.eval_now(p.operands[1], p.line, self.pc)
            if f is None:
                return
            if not -128 <= f <= 255:
                self.error(p.line, p.operands[1].start, p.operands[1].end,
                           f"Fill value {f} does not fit in 8 bits")
                return
            fill = f & 0xFF
        self.note_data(p, n)
        self.plan.append(("ds", p, self.pc, (n, fill)))
        self.emit_placeholder(p, n)

    def d_end(self, p):
        if not self.need_operands(p, 0, 1):
            return
        if p.operands:
            self.end_entry = p.operands[0]
            self.end_line = p.line
        self.end_seen = True

    def note_data(self, p, size):
        self.data_regions[self.pc] = (size, p.line)

    def emit_placeholder(self, p, size):
        """Reserve addresses in pass 1 (bytes are filled in pass 2)."""
        start = self.pc
        for i in range(size):
            a = start + i
            if a > 0xFFFF:
                self.error(p.line, p.op.start, p.op.end, "Program runs past the end of the 64K address space")
                break
            if a in self.owner:
                self.error(p.line, p.op.start, p.operands[-1].end if p.operands else p.op.end,
                           f"Address {_hex(a)} is already used by line {self.owner[a]} "
                           f"(overlapping ORG?)")
                break
            self.owner[a] = p.line
            self.res.image[a] = 0
        self.pc = start + size
        self.entry_note(start)

    def entry_note(self, start):
        if not self.entry_set:
            self.entry_set = True
            self.res.entry = start

    @staticmethod
    def _is_string(text: str) -> bool:
        return len(text) >= 4 and text[0] in "'\"" and text[-1] == text[0]

    # -- EQU ------------------------------------------------------------
    def pass1_equ(self, p):
        if not p.label:
            self.error(p.line, p.op.start, p.op.end, "EQU needs a name, e.g.  COUNT: EQU 10")
            return
        if not self.need_operands(p, 1):
            return
        try:
            v = evaluate(p.operands[0].text, self.lookup, self.pc, RESERVED_REGISTERS)
        except UndefinedSymbol:
            self.deferred_equ.append((p, p.operands[0]))
            return
        except ExprError as e:
            o = p.operands[0]
            self.error(p.line, o.start + e.start, o.start + e.end, e.message)
            return
        self.define(p.label, p.line, v, "equ")

    def resolve_deferred(self):
        pending = self.deferred_equ
        progress = True
        while pending and progress:
            progress = False
            rest = []
            for p, o in pending:
                try:
                    v = evaluate(o.text, self.lookup, 0, RESERVED_REGISTERS)
                except UndefinedSymbol:
                    rest.append((p, o))
                    continue
                except ExprError as e:
                    self.error(p.line, o.start + e.start, o.start + e.end, e.message)
                    progress = True
                    continue
                self.define(p.label, p.line, v, "equ")
                progress = True
            pending = rest
        for p, o in pending:
            try:
                evaluate(o.text, self.lookup, 0, RESERVED_REGISTERS)
            except ExprError as e:
                self.error(p.line, o.start + e.start, o.start + e.end, e.message)

    def finish_symbols(self):
        for addr, (size, line) in self.data_regions.items():
            for s in self.res.symbols.values():
                if s.kind == "label" and s.value == addr:
                    s.kind, s.size = "data", size

    # -- instructions ---------------------------------------------------
    def pass1_instr(self, p: Parsed, word: str):
        instr = self.match(p, word)
        if instr is None:
            self.emit_placeholder(p, 1)  # keep addresses roughly right
            return
        self.plan.append(("op", p, self.pc, instr))
        start = self.pc
        self.res.addr_to_line[start] = p.line
        self.res.line_to_addr.setdefault(p.line, start)
        self.emit_placeholder(p, instr.length)

    def match(self, p: Parsed, word: str) -> Instr | None:
        ops = p.operands
        forms = BY_MNEMONIC[word]
        if word == "RST":
            if len(ops) != 1:
                self.error(p.line, p.op.start, p.operands[-1].end if ops else p.op.end,
                           "RST needs one operand: RST n (n = 0 to 7)")
                return None
            v = self.eval_now(ops[0], p.line, self.pc)
            if v is None:
                return None
            if not 0 <= v <= 7:
                self.error(p.line, ops[0].start, ops[0].end, f"RST number {v} must be 0 to 7")
                return None
            return forms[v]
        arity = len(forms[0].operands)
        syntax = INFO[word][0]
        if len(ops) != arity:
            end = ops[-1].end if ops else p.op.end
            if not ops:
                self.error(p.line, p.op.start, p.op.end, f"{word} needs {arity} operand{'s' if arity != 1 else ''}: {syntax}")
            elif arity == 0:
                self.error(p.line, ops[0].start, end, f"{word} takes no operands")
            else:
                self.error(p.line, ops[0].start, end,
                           f"{word} takes {arity} operand{'s' if arity != 1 else ''}: {syntax}")
            return None
        for ins in forms:
            if all(tok.startswith("#") or tok == o.text.upper() for tok, o in zip(ins.operands, ops)):
                # an immediate slot must not be a bare register name
                if all(not tok.startswith("#") or o.text.upper() not in RESERVED_REGISTERS
                       for tok, o in zip(ins.operands, ops)):
                    return ins
        # find which operand is wrong for a helpful message
        for i, o in enumerate(ops):
            literal = {ins.operands[i] for ins in forms if not ins.operands[i].startswith("#")}
            if literal:
                if o.text.upper() not in literal:
                    names = ", ".join(sorted(literal, key=lambda x: (len(x), x)))
                    self.error(p.line, o.start, o.end, f"'{o.text}' is not valid here: {word} accepts {names}  ({syntax})")
                    return None
            elif o.text.upper() in RESERVED_REGISTERS:
                self.error(p.line, o.start, o.end,
                           f"'{o.text}' is a register name, but {word} needs a number or label here  ({syntax})")
                return None
        self.error(p.line, ops[0].start, ops[-1].end, f"Invalid operands for {word}  ({syntax})")
        return None

    # -- pass 2 ---------------------------------------------------------
    def value(self, o: Span, line: int, here: int, bits: int):
        try:
            v = evaluate(o.text, self.lookup, here, RESERVED_REGISTERS)
        except ExprError as e:
            self.error(line, o.start + e.start, o.start + e.end, e.message)
            return 0
        lo, hi = (-128, 255) if bits == 8 else (-32768, 65535)
        if not lo <= v <= hi:
            self.error(line, o.start, o.end,
                       f"Value {v} ({'-' if v < 0 else ''}{abs(v):X}h) does not fit in {bits} bits "
                       f"({lo} to {hi})")
            return 0
        return v & ((1 << bits) - 1)

    def put(self, addr: int, data: bytes):
        for i, b in enumerate(data):
            if addr + i <= 0xFFFF and addr + i in self.res.image:
                self.res.image[addr + i] = b

    def pass2(self, kind, p: Parsed, pc: int, payload):
        if kind == "op":
            ins: Instr = payload
            data = [ins.opcode]
            imm = ins.imm_kind
            if imm:
                o = next(o for tok, o in zip(ins.operands, p.operands) if tok.startswith("#"))
                bits = 8 if imm == "#8" else 16
                v = self.value(o, p.line, pc, bits)
                data += [v] if bits == 8 else [v & 0xFF, v >> 8]
            self.put(pc, bytes(data))
        elif kind == "db":
            out = bytearray()
            for o in p.operands:
                if self._is_string(o.text):
                    out += o.text[1:-1].encode("latin-1", "replace")
                else:
                    out.append(self.value(o, p.line, pc + len(out), 8))
            self.put(pc, bytes(out))
        elif kind == "dw":
            out = bytearray()
            for o in p.operands:
                v = self.value(o, p.line, pc + len(out), 16)
                out += bytes([v & 0xFF, v >> 8])
            self.put(pc, bytes(out))
        elif kind == "ds":
            n, fill = payload
            self.put(pc, bytes([fill]) * n)

    # -- results --------------------------------------------------------
    def build_listing(self, parsed: list[Parsed]):
        spans: dict[int, tuple[int, int]] = {}
        for kind, p, pc, payload in self.plan:
            size = payload.length if kind == "op" else None
            if kind == "db":
                size = sum(len(o.text) - 2 if self._is_string(o.text) else 1 for o in p.operands)
            elif kind == "dw":
                size = 2 * len(p.operands)
            elif kind == "ds":
                size = payload[0]
            spans[p.line] = (pc, size or 0)
        for p in parsed:
            if p.line in spans:
                pc, size = spans[p.line]
                data = bytes(self.res.image.get(pc + i, 0) for i in range(size))
                self.res.listing.append(ListingLine(p.line, pc, data, p.raw))
            else:
                self.res.listing.append(ListingLine(p.line, None, b"", p.raw))
        self.res.listing.sort(key=lambda l: l.line)

    def build_regions(self):
        kinds = {"op": "code", "db": "data", "dw": "data", "ds": "reserved"}
        for kind, p, pc, payload in self.plan:
            size = payload.length if kind == "op" else self._data_size(kind, p, payload)
            if size:
                self.res.regions.append(Region(pc, size, kinds[kind], p.line))
                if kind == "ds" and len(p.operands) == 1:
                    self.res.uninitialized.append((pc, size))
        self.res.regions.sort(key=lambda r: r.start)

    def _data_size(self, kind, p, payload) -> int:
        if kind == "db":
            return sum(len(o.text) - 2 if self._is_string(o.text) else 1 for o in p.operands)
        if kind == "dw":
            return 2 * len(p.operands)
        return payload[0]

    def apply_compat(self):
        if self.compat not in ("note", "strict"):
            return
        sev = ERROR if self.compat == "strict" else NOTE
        prefix = "Not allowed in GNUSim8085-compatible mode: " if sev == ERROR else "GNUSim8085 difference: "
        for line, start, end, msg in check_compat(self.parsed, self.res.symbols):
            self.res.diagnostics.append(Diagnostic(line, start, max(end, start + 1), sev, prefix + msg))
        self.res.diagnostics.sort(key=lambda d: (d.line, d.start, d.severity != ERROR))

    def final_checks(self):
        res = self.res
        if self.end_entry is not None:
            o = self.end_entry
            try:
                res.entry = evaluate(o.text, self.lookup, 0, RESERVED_REGISTERS) & 0xFFFF
            except ExprError as e:
                self.error(self.end_line, o.start + e.start, o.start + e.end, e.message)
        # warn when nothing can ever stop the program
        ops = [(pc, ins) for kind, p, pc, ins in self.plan if kind == "op"]
        if ops and res.ok:
            mnems = {i.mnemonic for _, i in ops}
            last_pc, last = max(ops, key=lambda t: t[0])
            if "HLT" not in mnems and last.mnemonic not in ("JMP", "RET", "PCHL"):
                line = res.addr_to_line[last_pc]
                raw = self.lines[line - 1]
                self.warn(line, 0, max(1, len(raw[:find_comment(raw)].rstrip())),
                          "The program has no HLT; execution will run on into empty memory (NOPs)")
        res.diagnostics.sort(key=lambda d: (d.line, d.start, d.severity != ERROR))


def assemble(source: str, origin: int = 0, compat: str = "off") -> AsmResult:
    """Assemble ``source``; the code starts at ``origin`` unless it uses ORG.

    ``compat`` is ``"off"``, ``"note"`` (report syntax GNUSim8085 would not accept as
    informational notes) or ``"strict"`` (report it as errors).
    """
    return _Assembler(source, origin, compat).run()
