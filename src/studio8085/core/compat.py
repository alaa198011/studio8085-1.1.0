"""Detect source that Studio8085 accepts but the original GNUSim8085 does not.

The rules come from probing the real GNUSim8085 1.4.x assembler (see
docs/COMPATIBILITY.md): it has only the DB, DS and EQU directives; an operand
is a number, a symbol, or ``symbol +/- number``; labels need a colon and must
sit on the same line as code or data; labels are case-sensitive; and it drops
the sign of negative literals.
"""

from __future__ import annotations

import re

from .expr import WORD_OPS
from .opcodes import BY_MNEMONIC, DIRECTIVES, RESERVED_REGISTERS

_NUM = r"(?:[0-9][0-9A-Fa-f]*[hH]|[01]+[bB]|[0-7]+[oO]|[0-9]+)"
_SYM = r"[A-Za-z_?@.][A-Za-z0-9_?@.]*"
_SIMPLE = re.compile(rf"^(?:{_NUM}|{_SYM}|{_SYM}\s*[+-]\s*{_NUM})$")
_NEG = re.compile(rf"^-\s*{_NUM}$")
_IDENT = re.compile(_SYM)

_EXTENSION_DIRECTIVES = {
    "ORG": "the ORG directive (GNUSim8085 has only DB, DS and EQU)",
    "DW": "the DW directive (GNUSim8085 has only DB, DS and EQU; write two DB bytes instead)",
    "END": "the END directive (GNUSim8085 has only DB, DS and EQU)",
}


def _value_slots(word: str, n: int) -> list[int]:
    if word in DIRECTIVES:
        return list(range(n))
    forms = BY_MNEMONIC.get(word)
    if not forms:
        return []
    if word == "RST":
        return [0]
    return [i for i in range(len(forms[0].operands)) if any(f.operands[i].startswith("#") for f in forms)]


def _operand_problem(text: str) -> str | None:
    t = text.strip()
    if _SIMPLE.match(t):
        return None
    if _NEG.match(t):
        return ("GNUSim8085 ignores the minus sign of a negative number (it assembles "
                f"'{t}' as +{t[1:].strip()}); Studio8085 uses two's complement")
    if re.match(r"^0[xX][0-9A-Fa-f]+$", t):
        return f"'{t}': the 0x prefix is not supported - write {t[2:]}h (start with 0 if it begins with a letter)"
    if re.match(r"^[0-9]+[qQ]$", t):
        return f"'{t}': the q suffix for octal is not supported - use o"
    if re.match(r"^[0-9]+[dD]$", t):
        return f"'{t}': the d suffix for decimal is not supported - write the number alone"
    if re.match(r"""^(?:'[^']*'|"[^"]*")$""", t):
        return f"{t}: character and string constants are not supported - use the numeric code"
    if "$" in t:
        return f"'{t}': $ (the current address) is not supported - use a label"
    return (f"'{t}': expressions are not supported (GNUSim8085 accepts a number, a label, "
            "or a label +/- one number)")


def check_compat(parsed, symbols) -> list[tuple[int, int, int, str]]:
    """Return ``(line, start, end, message)`` for every GNUSim8085 difference found."""
    out: list[tuple[int, int, int, str]] = []
    for p in parsed:
        if p.label is not None:
            if p.op is None:
                out.append((p.line, p.label.start, p.label.end,
                            "a label must be on the same line as an instruction or data directive"))
            if not p.label_colon:
                out.append((p.line, p.label.start, p.label.end, "labels must end with ':'"))
        if p.op is None:
            continue
        word = p.op.text.upper()
        if word in _EXTENSION_DIRECTIVES:
            out.append((p.line, p.op.start, p.op.end, _EXTENSION_DIRECTIVES[word]))
        if word == "DS" and len(p.operands) > 1:
            o = p.operands[1]
            out.append((p.line, o.start, o.end, "DS with a fill value is not supported"))
        slots = set(_value_slots(word, len(p.operands)))
        for i, o in enumerate(p.operands):
            if i not in slots:
                continue
            if word == "DS" and i > 0:
                continue
            msg = _operand_problem(o.text)
            if msg:
                out.append((p.line, o.start, o.end, msg))
            # labels are case-sensitive in GNUSim8085
            for m in _IDENT.finditer(o.text):
                up = m.group(0).upper()
                if up in RESERVED_REGISTERS or up in WORD_OPS:
                    continue
                sym = symbols.get(up)
                if sym and sym.name != m.group(0):
                    out.append((p.line, o.start + m.start(), o.start + m.end(),
                                f"labels are case-sensitive in GNUSim8085: '{m.group(0)}' would not match '{sym.name}'"))
    return out
