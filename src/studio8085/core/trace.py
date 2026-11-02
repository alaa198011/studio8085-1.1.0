"""Execution trace records and export (CSV, Markdown, HTML)."""

from __future__ import annotations

import csv
import io
from html import escape

COLUMNS = ["#", "Address", "Line", "Instruction", "A", "B", "C", "D", "E", "H", "L",
           "SP", "PC", "S", "Z", "AC", "P", "CY", "T-states", "T total", "Events"]


class TraceRow:
    __slots__ = ("n", "addr", "line", "text", "regs", "sp", "pc", "flags", "dt", "tstates", "events")

    def __init__(self, n, addr, line, text, regs, sp, pc, flags, dt, tstates, events):
        self.n, self.addr, self.line, self.text = n, addr, line, text
        self.regs, self.sp, self.pc, self.flags = regs, sp, pc, flags
        self.dt, self.tstates, self.events = dt, tstates, events

    def as_dict(self) -> dict:
        return dict(zip(COLUMNS, self.cells()))

    def cells(self) -> list[str]:
        a, b, c, d, e, h, l = self.regs
        s, z, ac, p, cy = self.flags
        return [str(self.n), f"{self.addr:04X}", str(self.line or ""), self.text,
                f"{a:02X}", f"{b:02X}", f"{c:02X}", f"{d:02X}", f"{e:02X}", f"{h:02X}", f"{l:02X}",
                f"{self.sp:04X}", f"{self.pc:04X}", str(s), str(z), str(ac), str(p), str(cy),
                str(self.dt), str(self.tstates), format_events(self.events)]


def format_events(events) -> str:
    out = []
    for ev in events:
        k = ev[0]
        if k == "W":
            out.append(f"[{ev[1]:04X}h]={ev[2]:02X}h")
        elif k == "OUT":
            out.append(f"OUT {ev[1]:02X}h={ev[2]:02X}h")
        elif k == "IN":
            out.append(f"IN {ev[1]:02X}h={ev[2]:02X}h")
        elif k == "INT":
            out.append(f"interrupt -> {ev[1]:04X}h")
    return "; ".join(out)


def to_csv(rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow(r.cells())
    return buf.getvalue()


def to_markdown(rows, title: str = "Execution trace", note: str = "") -> str:
    out = [f"# {title}", ""]
    if note:
        out += [note, ""]
    out.append("| " + " | ".join(COLUMNS) + " |")
    out.append("|" + "|".join("---:" if c not in ("Instruction", "Events") else "---" for c in COLUMNS) + "|")
    for r in rows:
        out.append("| " + " | ".join(c.replace("|", "\\|") for c in r.cells()) + " |")
    out.append("")
    out.append("_Registers and flags are shown **after** each instruction. T-states = cost of this instruction, "
               "T total = running total; Events = memory writes, port I/O and interrupts._")
    return "\n".join(out) + "\n"


def to_html(rows, title: str = "Execution trace", note: str = "", font_pt: int = 9) -> str:
    head = "".join(f"<th>{escape(c)}</th>" for c in COLUMNS)
    body = []
    for r in rows:
        cells = r.cells()
        body.append("<tr>" + "".join(
            f"<td class='{'txt' if COLUMNS[i] in ('Instruction', 'Events') else 'num'}'>{escape(c)}</td>"
            for i, c in enumerate(cells)) + "</tr>")
    style = (f"body{{font-family:Arial,Helvetica,sans-serif;font-size:{font_pt}pt}}"
             "table{border-collapse:collapse}th,td{border:1px solid #999;padding:2px 5px}"
             "th{background:#e8e8e8}td.num{text-align:right;font-family:monospace}td.txt{font-family:monospace}")
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{escape(title)}</title>"
            f"<style>{style}</style></head><body><h2>{escape(title)}</h2>"
            + (f"<p>{escape(note)}</p>" if note else "")
            + f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
            "<p><i>Registers and flags are shown after each instruction.</i></p></body></html>")
