import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from studio8085.app import use_system_fonts_offscreen  # noqa: E402

use_system_fonts_offscreen()  # same fonts as the real app on Windows too (see the docstring)
