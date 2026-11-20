"""A throwaway git repo for Eval Forge tests: one commit adds a clamp to a score function, with a test."""
from __future__ import annotations

import subprocess
from pathlib import Path

MESSAGE = """Clamp scores to the board's range

Scores could go negative after a penalty. Add clamp_score so every update
stays within 0..max, and use it in apply_penalty.

```python
def clamp_score(v, hi):
    return max(0, min(v, hi))
```

Tested in tests/test_scores.py (test_penalty_never_goes_negative).

Co-Authored-By: Someone <someone@example.com>
"""

START = "def apply_penalty(v, p):\n    return v - p\n"
SOLVED = ("def clamp_score(v, hi):\n    if v < 0:\n        return 0\n    if v > hi:\n        return hi\n    return v\n\n\n"
          "def apply_penalty(v, p, hi=100):\n    return clamp_score(v - p, hi)\n")
TEST = ("from src.scores import apply_penalty\n\n\n"
        "def test_penalty_never_goes_negative():\n    assert apply_penalty(3, 10) == 0\n\n\n"
        "def test_penalty_inside_the_range():\n    assert apply_penalty(50, 10) == 40\n\n\n"
        "def test_capped_at_the_top():\n    assert apply_penalty(150, 10) == 100\n\n\n"
        "def test_exactly_zero_and_max():\n    assert apply_penalty(10, 10) == 0 and apply_penalty(110, 10) == 100\n")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def make_repo(root: Path) -> Path:
    r = root / "game"
    (r / "src").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main", str(r))
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "T")
    git(r, "config", "commit.gpgsign", "false")
    (r / "src" / "__init__.py").write_text("", encoding="utf-8")
    (r / "src" / "scores.py").write_text(START, encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "Start")
    (r / "src" / "scores.py").write_text(SOLVED, encoding="utf-8")
    (r / "tests").mkdir()
    (r / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (r / "tests" / "test_scores.py").write_text(TEST, encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", MESSAGE)
    return r
