#!/usr/bin/env python3
"""Static checks for common Unity C# problems, so a review doesn't have to re-derive them.

    cs_lint.py <file.cs | folder>... [--only RULE,RULE] [--skip RULE] [--max 60] [--list]

Prints `path:line RULE message` per finding (capped by --max), a per-rule summary, and a last
line `RESULT: OK files=N` or `RESULT: FAIL findings=N files=N`. Heuristic (regex, no compiler):
treat a finding as a pointer to look at. Standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

HOT = {"Update", "FixedUpdate", "LateUpdate", "OnGUI", "OnTriggerStay", "OnTriggerStay2D", "OnCollisionStay",
       "OnCollisionStay2D", "OnAnimatorMove", "OnRenderObject"}
SKIP_DIRS = {"Library", "Temp", "Logs", "obj", "PackageCache", "Packages"}
UNITY_TYPES = r"(?:GameObject|Transform|RectTransform|Rigidbody2?D?|Collider2?D?|Renderer|SpriteRenderer|MeshRenderer|" \
              r"Animator|Camera|AudioSource|Light|Material|Texture2?D?|Sprite|ScriptableObject|MonoBehaviour|" \
              r"Component|[A-Z]\w*(?:Config|Asset|Controller|Behaviour|Manager|View))"

RULES = {
    "GETCOMPONENT_HOT": "GetComponent in a per-frame method; cache it in Awake",
    "FIND_HOT": "Find/FindObjectsByType in a per-frame method; keep a reference or a registry",
    "CAMERA_MAIN_HOT": "Camera.main in a per-frame method; cache it",
    "INSTANTIATE_HOT": "Instantiate/Destroy in a per-frame method; use a pool (pooling.md)",
    "STRING_ALLOC_HOT": "string building in a per-frame method allocates; use TMP SetText or cache",
    "LINQ_HOT": "LINQ in a per-frame method allocates; use a loop",
    "DEBUG_LOG_HOT": "Debug.Log in a per-frame method; strip it or log on change",
    "RESOURCES_LOAD_HOT": "Resources.Load in a per-frame method; load once",
    "LAMBDA_HOT": "lambda in a per-frame method may allocate a closure",
    "NEW_COLLECTION_HOT": "new List/Dictionary/array in a per-frame method; reuse a field or ListPool",
    "TAG_COMPARE": "tag == allocates; use CompareTag",
    "NULL_PROPAGATION": "?. or ?? on a Unity object skips the destroyed-object check; use if (obj)",
    "PUBLIC_FIELD": "public field; use [SerializeField] private + a property",
    "MATERIAL_CLONE": ".material clones the material; use sharedMaterial or a MaterialPropertyBlock",
    "SENDMESSAGE": "SendMessage/BroadcastMessage is slow and stringly typed; call an interface or event",
    "WAITFORSECONDS_NEW": "new WaitForSeconds inside a loop allocates every iteration; cache it",
    "EVENT_UNSUB": "event subscribed with += but never unsubscribed with -= in this file",
    "MAGIC_NUMBER": "unnamed number in gameplay code; move it to a const or a config field (tuning.md)",
    "LONG_METHOD": "method longer than 40 lines; split it",
    "NAMING": "naming: class/file mismatch or a method not in PascalCase",
}
DEFAULT_OFF = {"MAGIC_NUMBER"}  # noisy: ask for it with --only

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_STRING = re.compile(r'@"(?:[^"]|"")*"|\$?"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\])\'')
_SIG = re.compile(r"(?:^|[\s;}])(?:(?:public|private|protected|internal|static|virtual|override|async|sealed|"
                  r"abstract|unsafe|new|extern)\s+)*[\w<>\[\],.?]+\s+(\w+)\s*\([^;{}]*\)\s*(?:where[^{]*)?$", re.S)
_KEYWORDS = {"if", "for", "foreach", "while", "switch", "using", "lock", "catch", "return", "new", "else", "fixed"}


def strip(src: str) -> str:
    """Comments removed and string contents blanked, keeping line numbers and the quotes."""
    def blank(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith("//") or s.startswith("/*"):
            return re.sub(r"[^\n]", " ", s)
        q = s.index('"') if '"' in s else 0
        return s[:q + 1] + re.sub(r"[^\n]", " ", s[q + 1:-1]) + s[-1]
    return re.sub(f"{_COMMENT.pattern}|{_STRING.pattern}", blank, src, flags=re.S)


def methods(code: str) -> list[tuple[str, int, int]]:
    """(name, first line, last line) of every method body, found by brace matching."""
    out, stack, last_stmt = [], [], 0
    line = 1
    for i, ch in enumerate(code):
        if ch == "\n":
            line += 1
        elif ch == "{":
            m = _SIG.search(code[last_stmt:i])
            name = m.group(1) if m and m.group(1) not in _KEYWORDS else None
            stack.append((name, line))
            last_stmt = i + 1
        elif ch == "}":
            if stack:
                name, start = stack.pop()
                if name:
                    out.append((name, start, line))
            last_stmt = i + 1
        elif ch == ";":
            last_stmt = i + 1
    return out


def _brace_span(code: str, open_at: int) -> tuple[int, int]:
    """(first line, last line) of the block whose `{` is at open_at."""
    depth = 0
    for i in range(open_at, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return code[:open_at].count("\n") + 1, code[:i].count("\n") + 1
    return code[:open_at].count("\n") + 1, code.count("\n") + 1


def lint_text(src: str, path: str = "x.cs") -> list[tuple[int, str]]:
    code = strip(src)
    lines = code.split("\n")
    meths = methods(code)
    hot_lines: set[int] = set()
    method_lines: set[int] = set()
    found: list[tuple[int, str]] = []
    for name, a, b in meths:
        method_lines.update(range(a + 1, b))
        if name in HOT:
            hot_lines.update(range(a, b + 1))
        if b - a > 40:
            found.append((a, "LONG_METHOD"))
        if not name[0].isupper() and name not in ("get", "set", "add", "remove"):
            found.append((a, "NAMING"))
    editor = "/Editor/" in path.replace("\\", "/") or "UnityEditor" in src
    unity_vars = set(re.findall(rf"\b{UNITY_TYPES}\s+(\w+)\s*[;=)]", code))
    # Plain [Serializable] data classes and structs use public fields by convention (JsonUtility DTOs).
    dto_lines: set[int] = set()
    for m in re.finditer(r"(\[\s*(?:System\.)?Serializable\s*\][^{]*?)?\b(class|struct)\s+\w+[^{]*\{", code):
        if m.group(1) or m.group(2) == "struct":
            start = code[:m.start()].count("\n") + 1
            end = next((b for _n, a, b in [(None, *_brace_span(code, m.end() - 1))]), start)
            dto_lines.update(range(start, end + 1))
    loop_depth_lines = {i for i, l in enumerate(lines, 1) if re.search(r"\b(while|for|foreach)\s*\(", l)}

    for n, l in enumerate(lines, 1):
        hot = n in hot_lines
        if hot:
            if re.search(r"\bGetComponents?(InChildren|InParent)?\s*[<(]", l):
                found.append((n, "GETCOMPONENT_HOT"))
            if re.search(r"\b(GameObject\.Find\w*|FindObjects?OfType|FindObjectsByType|FindFirstObjectByType|"
                         r"FindAnyObjectByType|FindWithTag|FindGameObjectsWithTag)\s*[<(]", l):
                found.append((n, "FIND_HOT"))
            if "Camera.main" in l:
                found.append((n, "CAMERA_MAIN_HOT"))
            if re.search(r"\b(Instantiate|Destroy)\s*[<(]", l):
                found.append((n, "INSTANTIATE_HOT"))
            if re.search(r'\$"|"\s*\+|\+\s*"|\.ToString\(\)|string\.Format\(|string\.Concat\(', l):
                found.append((n, "STRING_ALLOC_HOT"))
            if re.search(r"\.(Where|Select|OrderBy\w*|ToList|ToArray|Any|First\w*|Last\w*|Count|Sum|GroupBy|"
                         r"Distinct)\s*\(", l) and "using System.Linq" in src:
                found.append((n, "LINQ_HOT"))
            if re.search(r"\bDebug\.Log\w*\s*\(", l):
                found.append((n, "DEBUG_LOG_HOT"))
            if re.search(r"\bResources\.Load\w*\s*[<(]", l):
                found.append((n, "RESOURCES_LOAD_HOT"))
            if "=>" in l:
                found.append((n, "LAMBDA_HOT"))
            if re.search(r"\bnew\s+(List|Dictionary|HashSet|Queue|Stack)\s*<|\bnew\s+\w+\s*\[\s*\w", l):
                found.append((n, "NEW_COLLECTION_HOT"))
        if re.search(r"\.tag\s*[!=]=|\btag\s*[!=]=\s*\"", l):
            found.append((n, "TAG_COMPARE"))
        for v in unity_vars:
            if re.search(rf"\b{re.escape(v)}\s*(\?\.|\?\?)", l):
                found.append((n, "NULL_PROPAGATION"))
                break
        if n not in method_lines and n not in dto_lines and re.match(r"\s*public\s+(?!const\b|static\b|readonly\b|event\b|"
                                              r"delegate\b|class\b|struct\b|enum\b|interface\b|record\b|abstract\b|"
                                              r"override\b|virtual\b|partial\b)[\w<>\[\],.?]+\s+\w+\s*(=(?!>)[^;]*)?;", l):
            found.append((n, "PUBLIC_FIELD"))
        if not editor and re.search(r"\.material\b(?!s)", l) and "sharedMaterial" not in l:
            found.append((n, "MATERIAL_CLONE"))
        if re.search(r"\b(SendMessage|BroadcastMessage|SendMessageUpwards)\s*\(", l):
            found.append((n, "SENDMESSAGE"))
        if "new WaitForSeconds" in l and (loop_depth_lines & set(range(max(1, n - 15), n + 1))):
            found.append((n, "WAITFORSECONDS_NEW"))
        if n in method_lines and not re.search(r"\bconst\b|^\s*\[|\bcase\b|Range\(", l):
            for num in re.findall(r"(?<![\w.\"])(-?\d+\.?\d*)f?\b(?![\w\"])", l):
                if num not in ("0", "1", "-1", "2", "0.5", "1.0", "0.0", "100") and not re.search(r"\[\s*" + re.escape(num), l):
                    found.append((n, "MAGIC_NUMBER"))
                    break

    for m in re.finditer(r"([\w.\[\]]+)\s*\+=\s*(?!\d)([\w.]+)\s*;", code):
        lhs, rhs = m.group(1), m.group(2)
        if not re.search(rf"{re.escape(lhs)}\s*-=\s*{re.escape(rhs)}\s*;", code) and not lhs.endswith(("Count", "count")):
            if re.match(r"[A-Z]", lhs.split(".")[-1]) and re.match(r"(On|Handle)?[A-Z]", rhs.split(".")[-1]):
                found.append((code[:m.start()].count("\n") + 1, "EVENT_UNSUB"))

    cls = re.search(r"\b(?:class|struct)\s+(\w+)", code)
    stem = Path(path).stem
    if cls and "MonoBehaviour" in code[:cls.end() + 200] and cls.group(1) != stem and stem != "x":
        found.append((code[:cls.start()].count("\n") + 1, "NAMING"))
    return sorted(set(found))


def iter_files(paths: list[Path]):
    for p in paths:
        if p.is_file() and p.suffix == ".cs":
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*.cs")):
                if not any(part in SKIP_DIRS for part in f.parts):
                    yield f


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--only", default="", help="comma-separated rules (MAGIC_NUMBER is only run when named)")
    ap.add_argument("--skip", default="")
    ap.add_argument("--max", type=int, default=60, help="most finding lines to print (the summary counts all)")
    ap.add_argument("--list", action="store_true", help="list the rules")
    a = ap.parse_args(argv)
    if a.list:
        for k, v in RULES.items():
            print(f"{k}: {v}{' (off unless --only)' if k in DEFAULT_OFF else ''}")
        return 0
    if not a.paths:
        ap.error("give at least one .cs file or folder")
    only = {r.strip().upper() for r in a.only.split(",") if r.strip()}
    if bad := only - RULES.keys():
        print(f"RESULT: FAIL unknown rules: {', '.join(sorted(bad))} (see --list)")
        return 2
    active = (only or (RULES.keys() - DEFAULT_OFF)) - {r.strip().upper() for r in a.skip.split(",") if r.strip()}
    counts: Counter = Counter()
    shown = files = 0
    for f in iter_files(a.paths):
        files += 1
        for line, rule in lint_text(f.read_text(encoding="utf-8", errors="replace"), str(f)):
            if rule not in active:
                continue
            counts[rule] += 1
            if shown < a.max:
                print(f"{f}:{line} {rule} {RULES[rule]}")
                shown += 1
    total = sum(counts.values())
    if total > shown:
        print(f"... {total - shown} more not shown (use --only RULE or --max)")
    if total:
        print("SUMMARY " + " ".join(f"{k}={v}" for k, v in counts.most_common()))
        print(f"RESULT: FAIL findings={total} files={files}")
        return 1
    print(f"RESULT: OK files={files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
