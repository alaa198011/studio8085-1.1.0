"""Generate the application icon files (PNG set + Windows .ico) from the vector
drawing in studio8085/ui/icons.py.   usage: python tools/make_icons.py"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtWidgets import QApplication

app = QApplication([])
from studio8085.ui.icons import app_pixmap

out = ROOT / "packaging" / "icons"
out.mkdir(parents=True, exist_ok=True)
for px in (16, 32, 48, 64, 128, 256, 512):
    app_pixmap(px).save(str(out / f"studio8085-{px}.png"))
app_pixmap(256).save(str(out / "studio8085.png"))

# .ico containing PNG-compressed images (supported since Windows Vista)
sizes = (16, 24, 32, 48, 64, 128, 256)
blobs = []
for px in sizes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    app_pixmap(px).save(buf, "PNG")
    blobs.append(bytes(ba))
header = struct.pack("<HHH", 0, 1, len(sizes))
offset = 6 + 16 * len(sizes)
entries = b""
for px, data in zip(sizes, blobs):
    entries += struct.pack("<BBBBHHII", px % 256, px % 256, 0, 0, 1, 32, len(data), offset)
    offset += len(data)
(out / "studio8085.ico").write_bytes(header + entries + b"".join(blobs))
print("wrote icons to", out)
