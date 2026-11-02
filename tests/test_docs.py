import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["GETTING_STARTED.md", "USER_GUIDE.md", "TEACHING_GUIDE.md", "ACCURACY.md", "COMPATIBILITY.md",
        "INSTRUCTION_MATRIX.md", "RELEASE_NOTES.md", "EXAMPLES.md"]


def test_instruction_matrix_is_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_matrix.py"), "--check"])
    assert r.returncode == 0, "run: python tools/gen_matrix.py"


def test_all_documents_exist_and_readme_links_to_them():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for d in DOCS:
        assert (ROOT / "docs" / d).is_file(), d
        assert f"docs/{d}" in readme, d


def test_relative_links_in_markdown_files_resolve():
    for md in [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]:
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", md.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("mailto:"):
                continue
            assert (md.parent / target).exists(), f"{md.name}: broken link {target}"


def test_documents_do_not_overclaim():
    text = "\n".join(p.read_text(encoding="utf-8") for p in [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]).lower()
    assert "cycle-accurate" not in text.replace("not cycle-accurate", "").replace("not \"cycle-accurate\"", "") \
        .replace("\"cycle-accurate\"", "")


def test_examples_guide_describes_every_bundled_program():
    guide = (ROOT / "docs" / "EXAMPLES.md").read_text(encoding="utf-8")
    folder = ROOT / "src" / "studio8085" / "examples"
    beginner = sorted((folder / "beginner").glob("*.asm"))
    larger = sorted(folder.glob("*.asm"))
    assert (len(beginner), len(larger)) == (17, 10)
    assert f"{len(beginner) + len(larger)} programs" in guide
    for f in beginner:
        title = re.search(r"^; @title: (.+)$", f.read_text(encoding="utf-8"), re.M).group(1).strip()
        assert f"| {f.name.split('_')[0]} | {title} |" in guide, f.name
