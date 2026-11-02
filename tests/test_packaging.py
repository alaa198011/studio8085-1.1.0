import re
from importlib import resources
from pathlib import Path

import studio8085

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_consistent_everywhere():
    py = (ROOT / "pyproject.toml").read_text()
    iss = (ROOT / "packaging/windows/studio8085.iss").read_text()
    assert re.search(rf'^version = "{re.escape(studio8085.__version__)}"', py, re.M)
    assert f'#define AppVersion "{studio8085.__version__}"' in iss


def test_package_data_is_present():
    assert resources.files("studio8085.ui").joinpath("styles/theme.qss").is_file()
    examples = [f.name for f in resources.files("studio8085").joinpath("examples").iterdir() if f.name.endswith(".asm")]
    assert len(examples) >= 10
    beginner = [f.name for f in resources.files("studio8085").joinpath("examples", "beginner").iterdir()
                if f.name.endswith(".asm")]
    assert len(beginner) == 17


def test_every_qss_placeholder_has_a_theme_colour():
    from studio8085.ui.themes import DARK, LIGHT
    qss = resources.files("studio8085.ui").joinpath("styles/theme.qss").read_text()
    used = set(re.findall(r"@(\w+)@", qss))
    for palette in (DARK, LIGHT):
        assert used <= set(palette), used - set(palette)


def test_packaging_files_exist():
    for f in ["packaging/studio8085.spec", "packaging/icons/studio8085.ico", "packaging/icons/studio8085-256.png",
              "packaging/linux/install.sh", "packaging/linux/studio8085.desktop",
              "packaging/windows/install_windows.ps1", "packaging/windows/studio8085.iss",
              "tools/diff_vs_gnusim8085/diff_test.py", "tools/gen_matrix.py", "docs/ACCURACY.md",
              ".github/workflows/build.yml", "LICENSE", "README.md"]:
        assert (ROOT / f).is_file(), f
