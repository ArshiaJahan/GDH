#!/usr/bin/env python3
"""Add a release section to CHANGELOG.md (Keep a Changelog 1.1 format) from git history since the last tag.

usage: changelog.py --version X.Y.Z [--repo DIR] [--file CHANGELOG.md] [--date YYYY-MM-DD]
                    [--since REF] [--include-all] [--compare-url URL] [--force] [--dry-run]

- Commits are read with `git log --no-merges <last tag>..HEAD` (all history when there is no tag).
  The last tag is `git describe --tags --abbrev=0 --match 'v[0-9]*'`; override with --since.
- Grouping (Conventional Commits, with a plain-English fallback on the first word):
    feat / add                      -> Added
    fix / bugfix / hotfix           -> Fixed
    perf / refactor / change / update / improve / style -> Changed
    deprecate                       -> Deprecated
    remove / delete / revert        -> Removed
    security / sec                  -> Security
    docs / test / chore / ci / build / release / wip -> skipped unless --include-all (then Changed)
  "type!:" or a "BREAKING CHANGE" footer prefixes the entry with **BREAKING**.
- The new "## [X.Y.Z] - DATE" section goes right after "## [Unreleased]" (whose entries are moved into it),
  or after the header. The file is created with the standard header when missing.
- --compare-url https://host/owner/repo adds/updates link references at the bottom.
- Refuses when the version section already exists, unless --force (then it is replaced).
Exit: 0 written (or printed with --dry-run), 1 error, 2 nothing to release (no commits since the tag).
Python 3 stdlib only. Tagging is separate:  git tag -a vX.Y.Z -m "vX.Y.Z"
"""
import argparse
import datetime
import os
import re
import subprocess
import sys

SECTIONS = ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"]
TYPE_MAP = {
    "feat": "Added", "feature": "Added", "add": "Added", "adds": "Added", "added": "Added", "new": "Added",
    "fix": "Fixed", "fixes": "Fixed", "fixed": "Fixed", "bugfix": "Fixed", "hotfix": "Fixed",
    "perf": "Changed", "refactor": "Changed", "change": "Changed", "changed": "Changed", "update": "Changed",
    "updated": "Changed", "improve": "Changed", "improved": "Changed", "style": "Changed", "tweak": "Changed",
    "deprecate": "Deprecated", "deprecated": "Deprecated",
    "remove": "Removed", "removed": "Removed", "delete": "Removed", "deleted": "Removed", "revert": "Removed",
    "security": "Security", "sec": "Security",
}
SKIP_TYPES = {"docs", "doc", "test", "tests", "chore", "ci", "build", "release", "wip", "merge"}
CC_RE = re.compile(r"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<desc>.+)$")
HEADER = """# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
"""
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), check=True, capture_output=True, text=True).stdout


def last_tag(repo):
    try:
        return git(repo, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*").strip() or None
    except subprocess.CalledProcessError:
        return None


def commits(repo, since):
    rng = [since + "..HEAD"] if since else ["HEAD"]
    out = git(repo, "log", "--no-merges", "--reverse", "--format=%h%x1f%s%x1f%b%x1e", *rng)
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        parts = rec.split("\x1f")
        yield parts[0].strip(), parts[1].strip(), (parts[2] if len(parts) > 2 else "")


def classify(subject, body, include_all):
    m = CC_RE.match(subject)
    breaking = "BREAKING CHANGE" in body or "BREAKING-CHANGE" in body
    if m:
        ctype = m.group("type").lower()
        breaking = breaking or bool(m.group("bang"))
        desc = m.group("desc").strip()
        scope = (m.group("scope") or "").strip()
        if ctype in SKIP_TYPES and not breaking:
            return (None, None) if not include_all else ("Changed", desc)
        section = TYPE_MAP.get(ctype, "Changed")
    else:
        first = re.split(r"[\s:]+", subject.strip(), maxsplit=1)[0].lower()
        if first in SKIP_TYPES and not include_all:
            return None, None
        section = TYPE_MAP.get(first, "Changed")
        desc = subject.strip()
        scope = ""
    desc = desc[0].upper() + desc[1:] if desc else desc
    if scope:
        desc = "**%s:** %s" % (scope, desc)
    if breaking:
        desc = "**BREAKING** " + desc
    return section, desc


def parse_bullets(block):
    """Parse '### Section' + '- item' lines of an existing Unreleased block into {section: [items]}."""
    found, current = {}, None
    for line in block.splitlines():
        h = re.match(r"^###\s+(\w+)", line)
        if h:
            current = h.group(1).capitalize()
            found.setdefault(current, [])
        elif current and re.match(r"^\s*[-*]\s+", line):
            found[current].append(re.sub(r"^\s*[-*]\s+", "", line).rstrip())
    return found


def render(version, date, groups):
    lines = ["## [%s] - %s" % (version, date), ""]
    for sec in SECTIONS + sorted(k for k in groups if k not in SECTIONS):
        items = groups.get(sec)
        if items:
            lines.append("### " + sec)
            lines.extend("- " + i for i in items)
            lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--file", default=None, help="default <repo>/CHANGELOG.md")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--since", default=None)
    ap.add_argument("--include-all", action="store_true")
    ap.add_argument("--compare-url", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    version = a.version[1:] if a.version.startswith("v") else a.version
    if not SEMVER_RE.match(version):
        print("error: --version must be SemVer MAJOR.MINOR.PATCH, got %s" % a.version, file=sys.stderr)
        return 1
    repo = os.path.abspath(a.repo)
    path = a.file or os.path.join(repo, "CHANGELOG.md")
    try:
        since = a.since or last_tag(repo)
        entries = list(commits(repo, since))
    except subprocess.CalledProcessError as e:
        print("error: git failed: %s" % (e.stderr or e).strip(), file=sys.stderr)
        return 1

    groups = {}
    for sha, subject, body in entries:
        sec, desc = classify(subject, body, a.include_all)
        if sec:
            groups.setdefault(sec, []).append("%s (%s)" % (desc, sha))

    text = open(path, encoding="utf-8").read() if os.path.exists(path) else HEADER
    if "## [Unreleased]" not in text:
        text = text.rstrip("\n") + "\n\n## [Unreleased]\n"

    sec_re = re.compile(r"^## \[%s\][^\n]*\n.*?(?=^## \[|^\[[^\]]+\]:|\Z)" % re.escape(version), re.S | re.M)
    if sec_re.search(text):
        if not a.force:
            print("error: CHANGELOG already has a [%s] section (use --force to replace)" % version, file=sys.stderr)
            return 1
        text = sec_re.sub("", text)

    # Move hand-written Unreleased entries into the release.
    unrel_re = re.compile(r"^## \[Unreleased\][^\n]*\n(?P<body>.*?)(?=^## \[|^\[[^\]]+\]:|\Z)", re.S | re.M)
    m = unrel_re.search(text)
    manual = parse_bullets(m.group("body")) if m else {}
    for sec, items in manual.items():
        groups.setdefault(sec, [])
        groups[sec] = items + [i for i in groups[sec] if i not in items]

    if not any(groups.values()):
        print("nothing to release: no relevant commits since %s" % (since or "the beginning"), file=sys.stderr)
        return 2

    section = render(version, a.date, groups)
    text = unrel_re.sub(lambda _m: "## [Unreleased]\n\n" + section + "\n", text, count=1)

    if a.compare_url:
        base = a.compare_url.rstrip("/")
        links = re.compile(r"^\[(Unreleased|%s)\]:.*\n?" % re.escape(version), re.M)
        text = links.sub("", text).rstrip("\n") + "\n"
        prev = since or ""
        new_links = ["[Unreleased]: %s/compare/v%s...HEAD" % (base, version)]
        new_links.append("[%s]: %s/compare/%s...v%s" % (version, base, prev, version) if prev
                         else "[%s]: %s/releases/tag/v%s" % (version, base, version))
        # Put new link refs before older ones (keeps the bottom block sorted newest first).
        first_ref = re.search(r"^\[[^\]]+\]:", text, re.M)
        if first_ref:
            text = text[:first_ref.start()] + "\n".join(new_links) + "\n" + text[first_ref.start():]
        else:
            text += "\n" + "\n".join(new_links) + "\n"

    text = re.sub(r"\n{3,}", "\n\n", text)
    if a.dry_run:
        print(section)
        return 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    n = sum(len(v) for v in groups.values())
    print("CHANGELOG: wrote [%s] with %d entries from %d commits since %s -> %s"
          % (version, n, len(entries), since or "start", path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
