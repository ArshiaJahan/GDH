"""README links: every relative link and image points at a file in the repo, and every #anchor exists."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)\s]+)\)|<img [^>]*src=\"([^\"]+)\"|<a href=\"([^\"]+)\"")


def _slug(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def _anchors(md: Path) -> set[str]:
    text = md.read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return {_slug(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", text, flags=re.M)}


def _links(md: Path) -> list[str]:
    text = re.sub(r"```.*?```", "", md.read_text(encoding="utf-8"), flags=re.S)
    return [next(g for g in m.groups() if g) for m in LINK.finditer(text)]


def test_readme_relative_links_resolve():
    readme = ROOT / "README.md"
    missing = []
    for link in _links(readme):
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, anchor = link.partition("#")
        target = (ROOT / path) if path else readme
        if not target.exists():
            missing.append(link)
        elif anchor and target.suffix == ".md" and anchor not in _anchors(target):
            missing.append(link)
    assert not missing, f"broken README links: {missing}"


def test_readme_puts_proof_and_quick_start_in_the_top_half():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    hero = next(i for i, l in enumerate(lines) if "docs/media/hero-unity-task.gif" in l)
    quick = lines.index("## Quick start")
    assert hero < 40, "the hero GIF should sit above the fold"
    assert quick < len(lines) // 2, "Quick start should be in the top half"
    assert "releases/latest" in "\n".join(lines[:60])


def test_readme_highlights_has_eight_rows_and_guide_has_all():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/GUIDE.md").read_text(encoding="utf-8")
    hl = readme.split("## Highlights", 1)[1].split("\n## ", 1)[0].split("\n### ", 1)[0]
    readme_rows = [l for l in hl.splitlines() if l.startswith("| **")]
    allf = guide.split("## All features", 1)[1].split("\n## ", 1)[0]
    guide_rows = [l for l in allf.splitlines() if l.startswith("| **")]
    assert len(readme_rows) == 8
    assert set(readme_rows) <= set(guide_rows)
