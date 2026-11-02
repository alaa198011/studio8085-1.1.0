import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_builtin_themes_meet_wcag_aa_contrast():
    """Text >= 4.5:1 and graphical marks >= 3:1 in Dark, Light and High Contrast."""
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "contrast_check.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_high_contrast_theme_reaches_wcag_aaa_for_text():
    """The High Contrast theme should do better than AA: >= 7:1 for every text pair (independent WCAG maths)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "src"))
    from studio8085.ui.themes import available_themes

    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    def lum(h):
        h = h.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    def ratio(a, b):
        la, lb = lum(a), lum(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    t = available_themes()["High Contrast"]
    c = t.colors
    pairs = [("text", "base"), ("text", "panel"), ("text_dim", "panel"), ("text_dim", "base"),
             ("gutter_text", "gutter_bg"), ("accent_text", "accent"), ("text", "selection"),
             ("text", "exec_line"), ("text", "current_line")]
    low = [(a, b, round(ratio(c[a], c[b]), 2)) for a, b in pairs if ratio(c[a], c[b]) < 7]
    low += [(f"syntax:{k}", "base", round(ratio(v.split("|")[0], c["base"]), 2))
            for k, v in t.syntax.items() if ratio(v.split("|")[0], c["base"]) < 7]
    assert not low, low
