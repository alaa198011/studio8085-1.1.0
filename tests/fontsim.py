"""Font simulation for the layout tests.

Linux CI uses DejaVu Sans, which is a good deal wider than Segoe UI on Windows, and geometry that was tuned on one
font broke on the other (PR #4, run 43306570209). The layout invariants must hold for ANY font, so the layout tests
are parametrized over the platform default and a deliberately wide family (DejaVu Sans / Verdana when installed,
otherwise the default family two points larger)."""

import pytest
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

WIDE_FAMILIES = ("DejaVu Sans", "Verdana")


def wide_font(base: QFont) -> QFont:
    f = QFont(base)
    have = set(QFontDatabase.families())
    for fam in WIDE_FAMILIES:
        if fam in have:
            f.setFamily(fam)
            f.setPointSize(max(base.pointSize(), 9))
            return f
    f.setPointSize(base.pointSize() + 2)
    return f


@pytest.fixture(params=["default", "wide"])
def ui_font(request, app):
    """Run the test with the platform default UI font, then with a wide one. Always restores the default."""
    original = QFont(QApplication.font())
    if request.param == "wide":
        QApplication.setFont(wide_font(original))
    yield request.param
    QApplication.setFont(original)
