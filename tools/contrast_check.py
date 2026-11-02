"""WCAG contrast ratios for the built-in themes.  usage: python tools/contrast_check.py
Text should reach 4.5:1 (AA); graphical marks 3:1."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from studio8085.ui.themes import DARK, HIGH_CONTRAST, LIGHT, _theme_from_dict  # noqa: E402


def lum(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def pairs(t):
    c, sx = t.colors, {k: v.split("|")[0] for k, v in t.syntax.items()}
    text = [("text on editor", c["text"], c["base"]), ("dim text on panel", c["text_dim"], c["panel"]),
            ("dim text on window", c["text_dim"], c["window"]), ("line numbers on gutter", c["gutter_text"], c["gutter_bg"]),
            ("text on execution line", c["text"], c["exec_line"]), ("accent text on accent", c["accent_text"], c["accent"]),
            ("error text on panel", c["error"], c["panel"]), ("warning text on panel", c["warning"], c["panel"]),
            ("ok text on window", c["ok"], c["window"]), ("info text on panel", c["info"], c["panel"])]
    text += [(f"syntax {k} on editor", v, c["base"]) for k, v in sx.items()]
    marks = [("read heat on editor", c["heat_read"], c["base"]), ("write heat on editor", c["heat_write"], c["base"]),
             ("exec heat on editor", c["heat_exec"], c["base"]), ("breakpoint on gutter", c["bp"], c["gutter_bg"]),
             ("exec arrow on gutter", c["exec_arrow"], c["gutter_bg"])]
    return text, marks


def main() -> int:
    bad = 0
    for raw, base in ((DARK, DARK), (LIGHT, LIGHT), (HIGH_CONTRAST, DARK)):
        t = _theme_from_dict(raw, base)
        text, marks = pairs(t)
        print(f"== {t.name}")
        for label, fg, bg, need in [(*p, 4.5) for p in text] + [(*p, 3.0) for p in marks]:
            r = ratio(fg, bg)
            flag = "" if r >= need else "  <-- below " + str(need)
            bad += r < need
            print(f"  {r:5.2f}  {label}{flag}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
