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


_GUI_MODULE_CACHE: dict[str, bool] = {}


def _is_gui_module(path) -> bool:
    """A test module is a GUI module if it uses Qt (or the shared GUI helpers in test_gui)."""
    key = str(path)
    if key not in _GUI_MODULE_CACHE:
        try:
            text = Path(key).read_text(encoding="utf-8")
        except OSError:
            text = ""
        _GUI_MODULE_CACHE[key] = "PySide6" in text or "test_gui" in text
    return _GUI_MODULE_CACHE[key]


def pytest_ignore_collect(collection_path, config):
    """With exactly ``-m "not gui"`` (the CI unit stage), do not even import the GUI modules: deselection happens only
    after import, and importing PySide6 needs the Qt system libraries (libEGL ...). The unit stage therefore runs
    without Qt, and the CI unit job proves it by not installing those libraries on Linux."""
    if (config.getoption("markexpr", "") or "").strip() != "not gui":
        return None
    if collection_path.suffix == ".py" and collection_path.name.startswith("test_") and _is_gui_module(collection_path):
        return True
    return None


def pytest_collection_modifyitems(items):
    """Mark every test module that uses Qt with ``gui``, so CI can run the fast core tests first and the GUI tests as
    their own job (``-m "not gui"`` and ``-m gui`` together are exactly the whole suite). A single test in a core
    module is marked too when its own code imports Qt or the ``studio8085.ui`` package (which loads PySide6)."""
    import inspect

    for item in items:
        gui = _is_gui_module(item.fspath)
        if not gui and getattr(item, "function", None) is not None:
            try:
                src = inspect.getsource(item.function)
            except (OSError, TypeError):
                src = ""
            gui = "PySide6" in src or "studio8085.ui" in src
        if gui:
            item.add_marker(pytest.mark.gui)
