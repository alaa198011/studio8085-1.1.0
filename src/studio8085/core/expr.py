"""Expression evaluator for assembler operands.

Supports numbers (``10``, ``0Ah``, ``0x0A``, ``1010b``, ``12o``), character
constants (``'A'``), symbols, ``$`` (the current address), parentheses and the
operators ``+ - * / % & | ^ ~ << >>`` plus the classic word forms
``AND OR XOR NOT SHL SHR MOD HIGH LOW``.
"""

from __future__ import annotations

import re
from typing import Callable

WORD_OPS = {"AND", "OR", "XOR", "NOT", "SHL", "SHR", "MOD", "HIGH", "LOW"}


class ExprError(Exception):
    """A problem in an expression. ``start``/``end`` are columns inside it."""

    def __init__(self, message: str, start: int = 0, end: int | None = None):
        super().__init__(message)
        self.message = message
        self.start = start
        self.end = start + 1 if end is None else end


class UndefinedSymbol(ExprError):
    def __init__(self, name: str, start: int, end: int):
        hint = ""
        if re.fullmatch(r"[0-9A-Fa-f]+[hH]", name):
            hint = f" (hex numbers must start with a digit, e.g. 0{name})"
        super().__init__(f"Undefined symbol '{name}'{hint}", start, end)
        self.name = name


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<num>(?:0[xX][0-9A-Fa-f]+|[0-9][0-9A-Fa-f]*[hH]|[0-9]+[bBoOqQdD]?)(?![A-Za-z0-9_?@.]))
       |(?P<id>[A-Za-z_?@.][A-Za-z0-9_?@.]*)
       |(?P<chr>'[^']*'|"[^"]*")
       |(?P<op><<|>>|[-+*/%&|^~()])
       |(?P<here>\$)
    )""",
    re.X,
)


def parse_number(tok: str, start: int = 0) -> int:
    t = tok.upper()
    end = start + len(tok)
    try:
        if t.startswith("0X"):
            return int(t[2:], 16)
        if t[-1] == "H":
            return int(t[:-1], 16)
        if t[-1] == "B":
            if set(t[:-1]) - set("01"):
                raise ValueError
            return int(t[:-1], 2)
        if t[-1] in "OQ":
            return int(t[:-1], 8)
        if t[-1] == "D":
            return int(t[:-1], 10)
        return int(t, 10)
    except ValueError:
        kind = {"B": "binary", "O": "octal", "Q": "octal", "D": "decimal"}.get(t[-1], "decimal")
        raise ExprError(f"Invalid {kind} number '{tok}'", start, end) from None


def tokenize(text: str):
    toks = []
    pos = 0
    n = len(text)
    while pos < n:
        if text[pos:].strip() == "":
            break
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            ws = len(text[pos:]) - len(text[pos:].lstrip())
            start = pos + ws
            m2 = re.match(r"\S+", text[start:])
            bad = m2.group(0) if m2 else text[start:start + 1]
            if bad[0].isdigit():
                raise ExprError(f"Invalid number '{bad}'", start, start + len(bad))
            raise ExprError(f"Unexpected '{bad[0]}'", start, start + 1)
        kind = m.lastgroup
        tok = m.group(kind)
        s = m.start(kind)
        toks.append((kind, tok, s, s + len(tok)))
        pos = m.end()
    return toks


class _Parser:
    def __init__(self, text, lookup, here, reserved):
        self.toks = tokenize(text)
        self.i = 0
        self.lookup = lookup
        self.here = here
        self.reserved = reserved
        self.text = text

    # -- token helpers
    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _is_op(self, tok, *ops):
        if tok is None:
            return None
        kind, text = tok[0], tok[1]
        if kind == "op" and text in ops:
            return text
        if kind == "id" and text.upper() in WORD_OPS and text.upper() in ops:
            return text.upper()
        return None

    def parse(self):
        if not self.toks:
            raise ExprError("Missing value", 0, max(1, len(self.text)))
        v = self._binary(0)
        tok = self._peek()
        if tok is not None:
            raise ExprError(f"Unexpected '{tok[1]}'", tok[2], tok[3])
        return v

    _LEVELS = [
        ("|", "OR"), ("^", "XOR"), ("&", "AND"),
        ("<<", ">>", "SHL", "SHR"), ("+", "-"), ("*", "/", "%", "MOD"),
    ]

    def _binary(self, level):
        if level == len(self._LEVELS):
            return self._unary()
        ops = self._LEVELS[level]
        left = self._binary(level + 1)
        while True:
            tok = self._peek()
            op = self._is_op(tok, *ops)
            if not op:
                return left
            self.i += 1
            right = self._binary(level + 1)
            left = self._apply(op, left, right, tok)

    def _apply(self, op, a, b, tok):
        if op in ("|", "OR"):
            return a | b
        if op in ("^", "XOR"):
            return a ^ b
        if op in ("&", "AND"):
            return a & b
        if op in ("<<", "SHL"):
            return a << b if 0 <= b < 32 else 0
        if op in (">>", "SHR"):
            return a >> b if 0 <= b < 32 else 0
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op in ("/", "%", "MOD"):
            if b == 0:
                raise ExprError("Division by zero", tok[2], tok[3])
            q = abs(a) // abs(b)
            if (a < 0) != (b < 0):
                q = -q
            return q if op == "/" else a - q * b
        raise AssertionError(op)

    def _unary(self):
        tok = self._peek()
        if tok is None:
            raise ExprError("Incomplete expression", len(self.text) - 1, len(self.text))
        op = self._is_op(tok, "+", "-", "~", "NOT", "HIGH", "LOW")
        if op:
            self.i += 1
            v = self._unary()
            if op == "+":
                return v
            if op == "-":
                return -v
            if op in ("~", "NOT"):
                return ~v
            if op == "HIGH":
                return (v >> 8) & 0xFF
            return v & 0xFF
        return self._primary()

    def _primary(self):
        tok = self._peek()
        kind, text, s, e = tok
        self.i += 1
        if kind == "num":
            return parse_number(text, s)
        if kind == "chr":
            inner = text[1:-1]
            if len(inner) != 1:
                raise ExprError("A character constant must be exactly one character "
                                "(use DB for longer strings)", s, e)
            return ord(inner)
        if kind == "here":
            return self.here
        if kind == "id":
            up = text.upper()
            if up in WORD_OPS:
                raise ExprError(f"'{text}' needs a value after it" if up in ("NOT", "HIGH", "LOW")
                                else f"Unexpected operator '{text}'", s, e)
            if up in self.reserved:
                raise ExprError(f"'{text}' is a register name, not a value", s, e)
            v = self.lookup(up)
            if v is None:
                raise UndefinedSymbol(text, s, e)
            return v
        if kind == "op" and text == "(":
            v = self._binary(0)
            close = self._peek()
            if close is None or close[1] != ")":
                raise ExprError("Missing closing ')'", s, e)
            self.i += 1
            return v
        raise ExprError(f"Unexpected '{text}'", s, e)


def evaluate(text: str, lookup: Callable[[str], int | None], here: int = 0,
             reserved=frozenset()) -> int:
    """Evaluate ``text``. ``lookup`` maps an UPPERCASE symbol to a value or None."""
    return _Parser(text, lookup, here, reserved).parse()
