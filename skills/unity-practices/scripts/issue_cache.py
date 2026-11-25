#!/usr/bin/env python3
"""A per-project cache of issues that were fixed before, so a repeat costs one lookup.

    issue_cache.py find "<error text or symptom>" [--project <root>] [--top 3]
    issue_cache.py add  "<symptom>" --fix "<what fixed it>" [--files a.cs,b.prefab] [--scene <debug scene>]
                        [--tags pooling,ai] [--project <root>]
    issue_cache.py list [--project <root>]

Entries live in <root>/.gdw/unity-issues.jsonl (commit it, so the team shares it). Matching is
fuzzy: compiler codes (CS0246), Unity error types and the words of the message, with paths,
numbers and GUIDs ignored. `find` prints `HIT score=… id=…` lines with the stored fix, or `MISS`.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

STOP = {"the", "a", "an", "is", "in", "on", "of", "to", "and", "or", "at", "for", "with", "not", "be", "it", "this",
        "that", "error", "warning", "unity", "assets", "cs", "line", "was", "are", "does", "when", "after"}
HIT_AT = 0.34


def store(project: Path) -> Path:
    return project / ".gdw" / "unity-issues.jsonl"


def norm_tokens(text: str) -> set[str]:
    t = text.lower()
    t = re.sub(r"[0-9a-f]{32}", " ", t)                      # GUIDs
    t = re.sub(r"(?:[a-z]:)?[\w./\\-]+\.(cs|prefab|unity|asset|meta|shader)\b", r" \1file ", t)  # paths
    codes = set(re.findall(r"\bcs\d{4}\b", t))
    t = re.sub(r"\(\d+,\d+\)|\b\d+(\.\d+)?\b", " ", t)       # positions and numbers
    words = {w for w in re.findall(r"[a-z_][a-z0-9_]{2,}", t) if w not in STOP}
    return words | {c.upper() for c in codes}


def score(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    codes_a, codes_b = {x for x in a if x.startswith("CS")}, {x for x in b if x.startswith("CS")}
    if codes_a and codes_b and not codes_a & codes_b:
        return 0.0  # different compiler errors never match
    j = len(a & b) / len(a | b)
    contain = len(a & b) / min(len(a), len(b))
    return round(0.5 * j + 0.5 * contain, 3)


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def save(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")


def find(project: Path, text: str, top: int = 3) -> list[tuple[float, dict]]:
    entries = load(store(project))
    q = norm_tokens(text)
    ranked = sorted(((score(q, set(e.get("tokens") or norm_tokens(e["symptom"]))), e) for e in entries),
                    key=lambda x: -x[0])
    hits = [(s, e) for s, e in ranked if s >= HIT_AT][:top]
    if hits:
        ids = {e["id"] for _s, e in hits[:1]}
        for e in entries:
            if e["id"] in ids:
                e["hits"] = int(e.get("hits", 0)) + 1
                e["last_used"] = time.strftime("%Y-%m-%d")
        save(store(project), entries)
    return hits


def add(project: Path, symptom: str, fix: str, files: list[str], scene: str, tags: list[str]) -> dict:
    path = store(project)
    entries = load(path)
    toks = norm_tokens(symptom)
    for e in entries:  # the same symptom again: update the fix instead of adding a duplicate
        if score(toks, set(e.get("tokens") or [])) >= 0.9:
            e.update(fix=fix, files=files or e.get("files", []), scene=scene or e.get("scene", ""),
                     tags=sorted(set(e.get("tags", [])) | set(tags)), updated=time.strftime("%Y-%m-%d"))
            save(path, entries)
            return e
    e = {"id": f"I{len(entries) + 1:03d}", "symptom": symptom.strip()[:500], "fix": fix.strip()[:1000],
         "files": files, "scene": scene, "tags": tags, "tokens": sorted(toks), "hits": 0,
         "added": time.strftime("%Y-%m-%d")}
    entries.append(e)
    save(path, entries)
    return e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("find", "add", "list"):
        p = sub.add_parser(name)
        p.add_argument("--project", type=Path, default=Path("."))
        if name in ("find", "add"):
            p.add_argument("text")
        if name == "find":
            p.add_argument("--top", type=int, default=3)
        if name == "add":
            p.add_argument("--fix", required=True)
            p.add_argument("--files", default="")
            p.add_argument("--scene", default="")
            p.add_argument("--tags", default="")
    a = ap.parse_args(argv)
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]  # noqa: E731
    if a.cmd == "find":
        hits = find(a.project, a.text, a.top)
        if not hits:
            print("MISS no stored fix; reproduce, fix, then `issue_cache.py add`")
            return 1
        for s, e in hits:
            extra = "".join(f" {k}={','.join(v) if isinstance(v, list) else v}" for k in ("files", "scene")
                            if (v := e.get(k)))
            print(f"HIT score={s} id={e['id']} hits={e.get('hits', 0)}{extra}\n  symptom: {e['symptom'][:160]}\n"
                  f"  fix: {e['fix']}")
        return 0
    if a.cmd == "add":
        e = add(a.project, a.text, a.fix, split(a.files), a.scene, split(a.tags))
        print(f"SAVED id={e['id']} in {store(a.project)}")
        return 0
    entries = load(store(a.project))
    for e in entries:
        print(f"{e['id']} hits={e.get('hits', 0)} {e['symptom'][:100]}")
    print(f"RESULT: OK entries={len(entries)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
