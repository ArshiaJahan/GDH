#!/usr/bin/env python3
"""Check that named skills exist (a SKILL.md whose frontmatter `name:` matches) in the known skill roots.

Search order (first hit wins):
  --root DIR (repeatable) -> $UNITY_SKILLS_DIRS (colon-separated) -> the folder that holds this skill
  (sibling skills) -> ./.claude/skills -> ~/.claude/skills -> ~/.agents/skills
  -> ~/Library/Application Support/Connector Manager/skills

Matches by frontmatter name, not folder name (unity-mcp-orchestrator lives in a folder called unity-mcp-skill).
Exit codes: 0 all found, 1 some missing, 2 usage error. Last line: "RESULT: OK ..." or "RESULT: FAIL ...".
Python 3.9+ stdlib only.
"""
import argparse
import os
import re
import sys

HARNESS = [
    "unity-router", "compile-fix-loop", "play-verify", "headless-ops", "scene-prefab-safety", "gdd-to-backlog",
    "project-memory", "architecture-patterns", "asset-pipeline", "perf-pass", "game-feel-pass", "build-ship",
    "vcs-hygiene", "design-critique", "postmortem", "trailer-maker",
]
EXISTING = ["unity-mcp-orchestrator", "game-designer"]


def roots(extra):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../<skills>/unity-router
    out = list(extra)
    out += [p for p in os.environ.get("UNITY_SKILLS_DIRS", "").split(":") if p]
    out += [os.path.dirname(here), os.path.join(os.getcwd(), ".claude", "skills"),
            os.path.expanduser("~/.claude/skills"), os.path.expanduser("~/.agents/skills"),
            os.path.expanduser("~/Library/Application Support/Connector Manager/skills")]
    seen, res = set(), []
    for r in out:
        r = os.path.abspath(os.path.expanduser(r))
        if r not in seen and os.path.isdir(r):
            seen.add(r)
            res.append(r)
    return res


def frontmatter_name(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except OSError:
        return None, None
    m = re.match(r"^---\s*\n(.*?)\n---", head, re.S)
    if not m:
        return None, None
    n = re.search(r"^name:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", m.group(1), re.M)
    d = re.search(r"^description:\s*(.+)$", m.group(1), re.M)
    return (n.group(1).strip() if n else None), (d.group(1).strip() if d else "")


def index(search_roots):
    found = {}
    for r in search_roots:
        try:
            entries = sorted(os.listdir(r))
        except OSError:
            continue
        for e in entries:
            sk = os.path.join(r, e, "SKILL.md")
            if os.path.isfile(sk):
                name, desc = frontmatter_name(sk)
                if name and name not in found:
                    found[name] = (sk, e, desc)
    return found


def main():
    ap = argparse.ArgumentParser(description="Check that skills exist by frontmatter name in the known skill roots.",
                                 epilog="Examples:\n  check_skills.py compile-fix-loop play-verify\n"
                                        "  check_skills.py --all            # all 16 harness skills + the 2 existing ones\n"
                                        "  check_skills.py --list           # list every skill found\n"
                                        "  check_skills.py --root ~/skills headless-ops",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skills", nargs="*", help="skill names to check")
    ap.add_argument("--all", action="store_true", help="check the 16 harness skills plus unity-mcp-orchestrator and game-designer")
    ap.add_argument("--list", action="store_true", help="list every skill found and where")
    ap.add_argument("--root", action="append", default=[], metavar="DIR", help="extra skill root to search first (repeatable)")
    a = ap.parse_args()
    rs = roots(a.root)
    found = index(rs)
    if a.list:
        for name in sorted(found):
            print("%-28s %s" % (name, found[name][0]))
        print("searched: " + "; ".join(rs))
        if not a.skills and not a.all:
            print("RESULT: OK %d skills found" % len(found))
            return 0
    wanted = list(a.skills) + ((HARNESS + EXISTING) if a.all else [])
    if not wanted:
        ap.print_usage()
        print("RESULT: FAIL no skill names given")
        return 2
    missing = []
    for name in dict.fromkeys(wanted):
        if name in found:
            path, folder, desc = found[name]
            note = "" if folder == name or name in EXISTING else "  (folder '%s' != name)" % folder
            print("OK      %-26s %s%s" % (name, path, note))
        else:
            missing.append(name)
            print("MISSING %-26s" % name)
    if missing:
        print("searched: " + "; ".join(rs))
        print("RESULT: FAIL missing %s" % ", ".join(missing))
        return 1
    print("RESULT: OK %d skill(s) found" % len(dict.fromkeys(wanted)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
