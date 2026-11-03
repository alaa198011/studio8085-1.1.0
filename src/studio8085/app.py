"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from . import APP_NAME, __version__


def use_system_fonts_offscreen() -> None:
    """Give Qt's offscreen/minimal platforms the real system fonts on Windows.

    On Linux those platforms find fonts through fontconfig. On Windows they use Qt's FreeType font
    database, which only looks in ``QT_QPA_FONTDIR`` (default ``<Qt>/lib/fonts``, not shipped in the
    PySide6 wheels). The font database is then empty: every glyph is drawn by a fallback "box" engine
    about twice as wide as real text and no font reports fixed pitch, so headless runs (tests, CI,
    ``--selftest``, screenshots) lay the window out very differently from the real app. Pointing
    ``QT_QPA_FONTDIR`` at the Windows font folder makes them use the same fonts as a normal start.
    Call it before the QApplication is created. It never overrides an explicit ``QT_QPA_FONTDIR``.
    """
    import os
    if sys.platform != "win32" or os.environ.get("QT_QPA_FONTDIR"):
        return
    platform = os.environ.get("QT_QPA_PLATFORM", "").split(":", 1)[0].strip().lower()
    if platform not in ("offscreen", "minimal"):
        return
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if fonts.is_dir():
        os.environ["QT_QPA_FONTDIR"] = str(fonts)


def selftest() -> int:
    """Build the window offscreen, run an example and check the answer (used by CI/installers)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    use_system_fonts_offscreen()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Studio8085-selftest")
    app.setApplicationName("Studio8085-selftest")
    from .core.machine import Stop
    from .ui.mainwindow import MainWindow

    QSettings().clear()
    w = MainWindow()
    w.show()
    w._load_example("02_sum_array.asm")
    if not w._assemble_and_load():
        print("selftest FAILED: assembly error")
        return 1
    why = w.machine.run_to_end()
    ok = why is Stop.HALT and w.machine.cpu.hl == 961 and not w.grab().isNull()
    QSettings().clear()
    print("selftest ok" if ok else f"selftest FAILED: {why} HL={w.machine.cpu.hl}")
    w.editor.document().setModified(False)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--selftest" in argv:
        return selftest()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    use_system_fonts_offscreen()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName("Studio8085")
    app.setOrganizationName("Studio8085")
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    QGuiApplication.setDesktopFileName("studio8085")

    from .ui.icons import app_icon
    from .ui.mainwindow import MainWindow

    app.setWindowIcon(app_icon())
    win = MainWindow()
    win.show()
    files = [a for a in argv[1:] if not a.startswith("-")]
    if files:
        win.open_file(Path(files[0]), checked=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
