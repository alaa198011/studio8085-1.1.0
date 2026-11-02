# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for 8085 Studio (Windows and Linux).
#   pip install pyinstaller
#   pyinstaller packaging/studio8085.spec --noconfirm
# Output: dist/8085Studio/  (a folder; run 8085Studio.exe / 8085Studio inside it)
import sys
from pathlib import Path

root = Path(SPECPATH).parent
src = root / "src" / "studio8085"
icon = str(root / "packaging" / "icons" / ("studio8085.ico" if sys.platform == "win32" else "studio8085.png"))

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root / "src")],
    datas=[
        (str(src / "ui" / "styles" / "theme.qss"), "studio8085/ui/styles"),
        (str(src / "examples"), "studio8085/examples"),
    ],
    hiddenimports=[],
    excludes=["tkinter", "pytest", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="8085Studio",
    console=False,
    icon=icon,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="8085Studio")
