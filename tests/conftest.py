import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from studio8085.app import use_system_fonts_offscreen  # noqa: E402

use_system_fonts_offscreen()  # same fonts as the real app on Windows too (see the docstring)


# ---------------------------------------------------------------------------------------------- test isolation
# Many GUI tests build a MainWindow and only close() it. A closed-but-alive window keeps its timers (the CPU panel's
# 16 ms animation timer, the coalescing timers, ...) and widgets, and every later processEvents() has to serve all of
# them, so the SAME test took 0.4 s as the first and 3.7 s as the twentieth: the suite got slower quadratically
# (hours on CI). After every test all top-level widgets are closed and really deleted, so each test starts clean.
import gc  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _delete_leftover_windows():
    yield
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:  # core tests run without PySide6
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in QApplication.topLevelWidgets():
        try:
            doc = getattr(getattr(w, "editor", None), "document", None)
            if doc is not None:
                doc().setModified(False)  # no "unsaved changes" prompt
            w.close()
            w.deleteLater()
        except RuntimeError:  # already deleted
            pass
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def pytest_collection_modifyitems(items):
    """Mark every test module that uses Qt with ``gui``, so CI can run the fast core tests first and the GUI tests as
    their own job (``-m "not gui"`` and ``-m gui`` together are exactly the whole suite)."""
    cache: dict[str, bool] = {}
    for item in items:
        path = str(item.fspath)
        if path not in cache:
            try:
                text = Path(path).read_text(encoding="utf-8")
            except OSError:
                text = ""
            cache[path] = "PySide6" in text or "test_gui" in text
        if cache[path]:
            item.add_marker(pytest.mark.gui)
