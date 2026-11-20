"""Every text read/write and text-mode subprocess in the backend names its encoding.

Python on Windows decodes text with the ANSI code page (cp1252) unless told otherwise, so a UTF-8 file
with a curly quote (bytes E2 80 9D) fails with "'charmap' codec can't decode byte 0x9d". This check
walks the source so a new call without `encoding=` fails here on every platform, not only on Windows.
"""
import ast
import sys
from pathlib import Path

import pytest

ROOTS = [Path(__file__).resolve().parents[1] / d for d in ("backend/gamedevworkstation", "scripts")]
SUBPROCESS = {"run", "check_output", "Popen", "call", "check_call"}
NOT_FILES = {"webbrowser", "zipfile", "zf", "zip", "z", "tarfile", "tar", "tf", "Image", "img", "wave", "aifc"}


def _kw(call: ast.Call, name: str):
    return next((k.value for k in call.keywords if k.arg == name), None)


def _text_mode(call: ast.Call, index: int) -> bool | None:
    mode = _kw(call, "mode") or (call.args[index] if len(call.args) > index else None)
    if mode is None:
        return True
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return "b" not in mode.value
    return None  # computed mode: can't tell


def _receiver(fn: ast.Attribute) -> str:
    v = fn.value
    return v.id if isinstance(v, ast.Name) else (v.attr if isinstance(v, ast.Attribute) else "")


def offenders() -> list[str]:
    bad = []
    for root in ROOTS:
        for p in sorted(root.rglob("*.py")):
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if not isinstance(n, ast.Call) or _kw(n, "encoding") is not None:
                    continue
                fn, why = n.func, ""
                if isinstance(fn, ast.Name) and fn.id == "open" and _text_mode(n, 1):
                    why = "open()"
                elif isinstance(fn, ast.Attribute):
                    if fn.attr == "read_text" and not n.args:
                        why = ".read_text()"
                    elif fn.attr == "write_text" and len(n.args) < 2:
                        why = ".write_text()"
                    elif fn.attr == "fdopen" and _text_mode(n, 1):
                        why = "os.fdopen()"
                    elif fn.attr == "open" and _receiver(fn) not in NOT_FILES and _text_mode(n, 0) \
                            and _receiver(fn) not in ("os",):
                        why = ".open()"
                    elif fn.attr in SUBPROCESS and _receiver(fn) == "subprocess":
                        t = _kw(n, "text") or _kw(n, "universal_newlines")
                        if isinstance(t, ast.Constant) and t.value is True:
                            why = "subprocess text=True"
                if why:
                    bad.append(f"{p.relative_to(root.parent)}:{n.lineno} {why} without encoding=")
    return bad


def test_all_text_io_names_its_encoding():
    assert offenders() == []


def test_the_check_catches_each_form(tmp_path, monkeypatch):
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "m.py").write_text(
        "import os, subprocess\nfrom pathlib import Path\n"
        "open('a')\nPath('a').read_text()\nPath('a').write_text('x')\nos.fdopen(3, 'w')\nPath('a').open('a')\n"
        "subprocess.run(['x'], text=True)\n"
        "open('a', 'rb')\nPath('a').read_text(encoding='utf-8')\nos.fdopen(3, 'wb')\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOTS", [src])
    assert len(offenders()) == 6


@pytest.mark.parametrize("name", ["skill-with-quotes"])
def test_get_skill_reads_utf8_whatever_the_locale(tmp_path, monkeypatch, name):
    from gamedevworkstation import skills
    f = tmp_path / "SKILL.md"
    f.write_bytes("---\nname: x\n---\nSay “hi” — then stop.\n".encode("utf-8"))
    monkeypatch.setattr(skills, "list_skills", lambda *a, **k: [{"name": name, "path": str(f)}])
    assert "“hi” —" in skills.get_skill(name)["content"]
