"""The campaign file: `<project>/.workspace/campaigns/<slug>.md`, committed with the project.

It holds what has to outlive sessions and be readable by a human: the request, design target,
scope, constraints, phases, coverage, ledger, review queue, decisions, discoveries, the active
context and the continuation state. SQLite stays authoritative for status, claims and budgets
(the frontmatter only mirrors them). Section names are adapted from SethGammon/Citadel (MIT).

Parsing is tolerant and lossless: `render(parse(text)) == text` for any text. Sections are found
by their `## ` heading (case and the trailing `(…)` / `<!-- … -->` don't matter); sections the
harness doesn't know are kept where they are. Harness-owned sections (HARNESS_OWNED) are
rewritten whole; every other section is the user's and the agent's and is only touched by
explicit appends (Decision log, Discoveries, Review queue) or rewrites (Active context, Completion
record) the harness itself makes. Writes are atomic (temp file + rename) and serialized per
campaign by FileLocks.
"""
from __future__ import annotations

import asyncio
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

# (key, heading as written in new files). Order = order in a new file.
SECTIONS: list[tuple[str, str]] = [
    ("request", "Request (verbatim)"),
    ("design_target", "Design target (done when all are true)"),
    ("scope", "Scope"),
    ("constraints", "Constraints"),
    ("phases", "Phases            <!-- harness-owned table -->"),
    ("coverage", "Coverage          <!-- harness-owned: decomposition validation -->"),
    ("ledger", "Feature ledger    <!-- harness-owned: mirrors BACKLOG statuses + non-backlog items -->"),
    ("review", "Review queue      <!-- manual checks and escalations for you -->"),
    ("decisions", "Decision log      <!-- append-only -->"),
    ("discoveries", "Discoveries       <!-- append-only, from sessions and fleet units -->"),
    ("active", "Active context    <!-- rewritten at compaction and phase end -->"),
    ("continuation", "Continuation state <!-- harness-owned: phase, next action, files, blocking, checkpoint -->"),
    ("completion", "Completion record"),
]
KEYS = [k for k, _ in SECTIONS]
HARNESS_OWNED = {"phases", "coverage", "ledger", "continuation"}
_NAMES = {"request": "request", "design target": "design_target", "scope": "scope", "constraints": "constraints",
          "phases": "phases", "coverage": "coverage", "feature ledger": "ledger", "ledger": "ledger",
          "review queue": "review", "decision log": "decisions", "decisions": "decisions",
          "discoveries": "discoveries", "active context": "active", "continuation state": "continuation",
          "continuation": "continuation", "completion record": "completion", "completion": "completion"}

FRONT = re.compile(r"^---[ \t]*\r?\n(.*?)(?:\r?\n)?^---[ \t]*(?:\r?\n|$)", re.S | re.M)
RE_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
RE_CHECK = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s*(.*)$")
RE_STORY = re.compile(r"\bM\d+-S\d{2,3}\b")


def section_key(heading: str) -> str | None:
    """The canonical key of a `## ` heading's text, or None for a section of the user's own."""
    h = re.sub(r"<!--.*?(-->|$)", "", heading)
    h = re.sub(r"\(.*?\)", "", h).strip().lower().rstrip(":").strip()
    return _NAMES.get(h)


@dataclass
class Section:
    key: str | None
    heading: str  # the heading line without "## " and the newline
    body: str  # everything after the heading line up to the next section (newlines included)


@dataclass
class CampaignDoc:
    front: list[str] = field(default_factory=list)  # frontmatter lines (without the --- fences)
    has_front: bool = False
    head: str = ""  # text after the frontmatter up to the first section (title, preamble)
    sections: list[Section] = field(default_factory=list)

    # ------------------------------------------------------------ frontmatter

    def front_get(self, key: str) -> str | None:
        for ln in self.front:
            m = re.match(rf"^{re.escape(key)}\s*:\s*(.*?)\s*(?:#.*)?$", ln)
            if m:
                return m.group(1).strip().strip("\"'")
        return None

    def front_set(self, key: str, value: object) -> None:
        """Set a frontmatter value, keeping a trailing `# comment` (and its column) on its line."""
        v = "" if value is None else str(value).replace("\n", " ")
        for i, ln in enumerate(self.front):
            m = re.match(rf"^{re.escape(key)}\s*:", ln)
            if not m:
                continue
            base = f"{key}: {v}".rstrip()
            c = re.search(r"\s#", ln[m.end():])
            if c:
                col = m.end() + c.start() + 1  # where the comment's # is
                self.front[i] = (base.ljust(col) if len(base) < col else base + "  ") + ln[col:]
            else:
                self.front[i] = base
            return
        self.front.append(f"{key}: {v}".rstrip())
        self.has_front = True

    @property
    def title(self) -> str:
        m = re.search(r"^# (.+)$", self.head, re.M)
        return m.group(1).strip() if m else ""

    # --------------------------------------------------------------- sections

    def section(self, key: str) -> Section | None:
        return next((s for s in self.sections if s.key == key), None)

    def get(self, key: str) -> str:
        """A section's body without surrounding blank lines and the heading comment ('' if absent)."""
        s = self.section(key)
        return s.body.strip("\n") if s else ""

    def set(self, key: str, body: str) -> None:
        """Replace a section's body (added at its usual place when missing)."""
        text = body.strip("\n") + "\n\n" if body.strip() else "\n"
        s = self.section(key)
        if s:
            s.body = text
            return
        heading = dict(SECTIONS)[key]
        idx = KEYS.index(key)
        pos = len(self.sections)
        for i, other in enumerate(self.sections):
            if other.key in KEYS and KEYS.index(other.key) > idx:
                pos = i
                break
        if pos > 0 and self.sections[pos - 1].body.strip() and not self.sections[pos - 1].body.endswith("\n\n"):
            self.sections[pos - 1].body = self.sections[pos - 1].body.rstrip("\n") + "\n\n"
        self.sections.insert(pos, Section(key, heading, text))

    def append(self, key: str, line: str) -> None:
        """Add a line at the end of a section (append-only sections)."""
        cur = self.get(key)
        # A lone placeholder comment line stays above new entries.
        self.set(key, (cur + "\n" if cur else "") + line.rstrip("\n"))

    def checklist(self, key: str = "design_target") -> list[tuple[bool, str]]:
        """`- [ ] text` / `- [x] text` items of a section (empty ones left out)."""
        out = []
        for ln in self.get(key).splitlines():
            if m := RE_CHECK.match(ln):
                if m.group(2).strip():
                    out.append((m.group(1).lower() == "x", m.group(2).strip()))
        return out

    def bullets(self, key: str) -> list[str]:
        return [m.group(1).strip() for ln in self.get(key).splitlines()
                if (m := re.match(r"^\s*[-*]\s+(?!\[[ xX]\])(.+)$", ln)) and m.group(1).strip()]

    def scope(self) -> dict:
        """Stories, claimed paths and out-of-scope items from the Scope section."""
        out: dict[str, list[str]] = {"stories": [], "paths": [], "out_of_scope": []}
        for ln in self.get("scope").splitlines():
            m = re.match(r"^\s*[-*]?\s*(Stories|Claimed paths|Out of scope)[^:]*:\s*(.*)$", ln, re.I)
            if not m:
                continue
            label, val = m.group(1).lower(), m.group(2)
            if label == "stories":
                out["stories"] += RE_STORY.findall(val)
            else:
                items = [x.strip().strip("`") for x in re.split(r",(?![^{]*})", val) if x.strip()]
                out["paths" if label.startswith("claimed") else "out_of_scope"] += items
        out["stories"] = list(dict.fromkeys(out["stories"]))
        return out


# ------------------------------------------------------------------ parse/render


def parse(text: str) -> CampaignDoc:
    """Tolerant and lossless: render(parse(t)) == t."""
    doc = CampaignDoc()
    rest = text
    m = FRONT.match(text)
    if m:
        doc.has_front = True
        doc.front = m.group(1).split("\n") if m.group(1) else []
        doc._front_raw = text[:m.end()]  # type: ignore[attr-defined]
        rest = text[m.end():]
    lines = rest.splitlines(keepends=True)
    head: list[str] = []
    cur: Section | None = None
    fence = False
    for ln in lines:
        if RE_FENCE.match(ln):
            fence = not fence
        if not fence and ln.startswith("## "):
            heading = ln[3:].rstrip("\r\n")
            cur = Section(section_key(heading), heading, "")
            cur._eol = ln[3 + len(heading):]  # type: ignore[attr-defined]
            doc.sections.append(cur)
            continue
        if cur is None:
            head.append(ln)
        else:
            cur.body += ln
    doc.head = "".join(head)
    return doc


def render(doc: CampaignDoc) -> str:
    out = []
    if doc.has_front:
        raw = getattr(doc, "_front_raw", None)
        built = "---\n" + "\n".join(doc.front) + "\n---\n"
        # Unchanged frontmatter is written back byte for byte (line endings and all).
        if raw is not None and _front_lines(raw) == doc.front:
            out.append(raw)
        else:
            out.append(built)
    out.append(doc.head)
    for s in doc.sections:
        out.append("## " + s.heading + getattr(s, "_eol", "\n"))
        out.append(s.body)
    return "".join(out)


def _front_lines(raw: str) -> list[str]:
    m = FRONT.match(raw)
    return (m.group(1).split("\n") if m and m.group(1) else [])


def new_doc(*, slug: str, template: str, title: str, request: str, budget_usd: float | None,
            created: float | None = None) -> CampaignDoc:
    """A fresh campaign file from the template's skeleton."""
    day = time.strftime("%Y-%m-%d", time.localtime(created or time.time()))
    quoted = "\n".join("> " + ln if ln.strip() else ">" for ln in (request.strip() or "(none)").splitlines())
    budget = "" if budget_usd is None else f"{budget_usd:g}"
    text = f"""---
campaign: {slug}
template: {template}
status: draft              # mirror only; Workspace's database is authoritative
claimed_by:                # mirror of the claim, for humans
created: {day}
budget_usd: {budget}
---
# {title}

## {dict(SECTIONS)['request']}
{quoted}

## {dict(SECTIONS)['design_target']}
<!-- End states, not deltas: "Death returns to Title in < 3 s", never "improve X" or "refactor Y". -->
- [ ] 

## Scope
Stories: 
Claimed paths: 
Out of scope (user-acknowledged): 

## Constraints

"""
    doc = parse(text)
    for key in KEYS[KEYS.index("phases"):]:
        doc.set(key, "")
    return doc


# --------------------------------------------------------------------- tables


def md_cell(v: object) -> str:
    return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def table(headers: list[str], rows: list[list[object]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(md_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


# ----------------------------------------------------------------- reading/IO


def read(path: Path) -> CampaignDoc | None:
    try:
        return parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same folder, then rename over the target (never half-written)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{secrets.token_hex(4)}")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


class FileLocks:
    """One asyncio lock per campaign: every read-modify-write of its file goes through it."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, cid: str) -> asyncio.Lock:
        lk = self._locks.get(cid)
        if lk is None:
            lk = self._locks[cid] = asyncio.Lock()
        return lk

    async def update(self, cid: str, path: Path, fn, *, create=None) -> CampaignDoc | None:
        """Read the file, apply fn(doc) and write it back atomically, under the campaign's lock.
        A missing or unreadable file is created from create() when given, else left alone (None)."""
        async with self.lock(cid):
            doc = read(path) if path.is_file() else None
            if doc is None:
                if create is None:
                    return None
                doc = create()
            before = render(doc)
            fn(doc)
            after = render(doc)
            if after != before or not path.is_file():
                await asyncio.to_thread(write_atomic, path, after)
            return doc
