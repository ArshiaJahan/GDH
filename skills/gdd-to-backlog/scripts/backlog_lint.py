#!/usr/bin/env python3
"""Validate the structure of a BACKLOG.md written by the gdd-to-backlog skill.

Format (see references/BACKLOG.template.md):
  Current milestone: M<n>                       (header line, must name an existing milestone)
  ## M<n> <title>                               (milestones, numbers strictly increasing)
  Goal: ... / Exit: ... / Status: todo|active|done
  ### M<n>-S<nn> <title>                        (stories, IDs unique, prefix = milestone)
  - Status: todo|doing|done|blocked|cut
  - Owner skill: <skill name>
  - Visual: yes|no                            (optional screenshot-evidence override)
  - Critique: yes|no                          (optional design-critique quality tier)
  | AC | Given / When / Then | Test | Signal |   (>= 1 row per story)
  | M<n>-S<nn>-AC<k> | Given ... When ... Then ... | EditMode|PlayMode|play-verify|headless|manual | kind:value[; kind:value] |

Signal kinds: test:<Fixture.Method>  log:"<text>"  screenshot:<name> shows <what>
              metric:<name> <op> <number>[unit]  file:<path>  exit:<code>  observe:<what a human checks>
Test type -> required signal kind:
  EditMode/PlayMode -> test   play-verify -> log|screenshot|metric   headless -> exit|file|log|metric|test
  manual -> any kind (observe/metric recommended)

Exit codes: 0 valid, 1 errors (or warnings with --strict), 2 usage error.
Last line: "RESULT: OK ..." or "RESULT: FAIL <n> error(s)". Python 3.9+ stdlib only.
"""
import argparse
import json
import re
import sys

SKILLS = {
    "unity-router", "compile-fix-loop", "play-verify", "headless-ops", "scene-prefab-safety", "gdd-to-backlog",
    "project-memory", "architecture-patterns", "asset-pipeline", "perf-pass", "game-feel-pass", "build-ship",
    "vcs-hygiene", "unity-mcp-orchestrator", "game-designer", "human",
}
TEST_TYPES = {"editmode": "EditMode", "playmode": "PlayMode", "play-verify": "play-verify",
              "headless": "headless", "manual": "manual"}
REQUIRED_KINDS = {
    "EditMode": {"test"}, "PlayMode": {"test"},
    "play-verify": {"log", "screenshot", "metric"},
    "headless": {"exit", "file", "log", "metric", "test"},
    "manual": {"observe", "metric", "screenshot", "log", "test", "file", "exit"},
}
SIGNAL_KINDS = {"test", "log", "screenshot", "metric", "file", "exit", "observe"}
MILESTONE_STATUS = {"todo", "active", "done"}
STORY_STATUS = {"todo", "doing", "done", "blocked", "cut"}
VAGUE = re.compile(r"(?i)\b(quickly|smooth(ly)?|fun|nice|good|properly|correctly|appropriate(ly)?|responsive|feels?|fast|slow)\b")

RE_MILESTONE = re.compile(r"^##\s+(M(\d+))\b\s*(.*)$")
RE_H2 = re.compile(r"^##\s+")
RE_STORY = re.compile(r"^###\s+(\S+)\s*(.*)$")
RE_STORY_ID = re.compile(r"^M(\d+)-S(\d{2,3})$")
RE_AC_ID = re.compile(r"^(M\d+-S\d{2,3})-AC(\d+)$")
RE_FIELD = re.compile(r"^\s*[-*]?\s*(Goal|Exit|Status|Owner skill|GDD|Notes|Depends on|Visual|Critique)\s*:\s*(.*)$", re.I)
RE_CURRENT = re.compile(r"^\s*[-*]?\s*Current milestone\s*:\s*(M\d+)\b", re.I)
RE_METRIC = re.compile(r"^[A-Za-z_][\w.\-/\[\] ]*?\s*(<=|>=|==|!=|<|>)\s*-?\d+(\.\d+)?\s*[A-Za-z%/]*$")
RE_TEST = re.compile(r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+(\(.*\))?$")


class Linter:
    def __init__(self, path):
        self.path = path
        self.errors = []
        self.warnings = []
        self.milestones = []  # dicts
        self.current = None
        self.current_line = 0

    def err(self, ln, msg):
        self.errors.append((ln, msg))

    def warn(self, ln, msg):
        self.warnings.append((ln, msg))

    def parse(self, text):
        ms = None
        story = None
        in_milestone = False
        for ln, raw in enumerate(text.splitlines(), 1):
            line = raw.rstrip()
            cm = RE_CURRENT.match(line)
            if cm and self.current is None:
                self.current, self.current_line = cm.group(1), ln
                continue
            mm = RE_MILESTONE.match(line)
            if mm:
                ms = {"id": mm.group(1), "num": int(mm.group(2)), "title": mm.group(3).strip(), "line": ln,
                      "fields": {}, "stories": []}
                self.milestones.append(ms)
                story = None
                in_milestone = True
                continue
            if RE_H2.match(line):
                in_milestone, ms, story = False, None, None
                continue
            sm = RE_STORY.match(line)
            if sm:
                if not in_milestone:
                    self.warn(ln, "story heading outside a '## M<n>' milestone is ignored: %s" % line.strip())
                    story = None
                    continue
                story = {"id": sm.group(1), "title": sm.group(2).strip(), "line": ln, "fields": {}, "acs": []}
                ms["stories"].append(story)
                continue
            if not in_milestone:
                continue
            fm = RE_FIELD.match(line)
            if fm and not line.lstrip().startswith("|"):
                key = fm.group(1).lower()
                target = story["fields"] if story else ms["fields"]
                if story and key in ("visual", "critique"):
                    if key in target:
                        self.err(ln, "story %s has duplicate '%s' field (first on line %d)" % (story["id"], key, target[key][1]))
                    if fm.group(2).strip().lower() not in ("yes", "no"):
                        self.err(ln, "story %s %s '%s' must be yes|no" % (story["id"], key, fm.group(2).strip()))
                target[key] = (fm.group(2).strip(), ln)
                continue
            if line.lstrip().startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if not cells or re.match(r"^:?-{2,}", cells[0]) or cells[0].lower() in ("ac", "id"):
                    continue
                if story is None:
                    self.err(ln, "table row outside a story: %s" % line.strip()[:60])
                    continue
                story["acs"].append({"cells": cells, "line": ln})

    def check(self):
        if not self.milestones:
            self.err(0, "no milestones found (expected headings like '## M0 Skeleton / boot')")
        seen_story, seen_ac = {}, {}
        prev = None
        for ms in self.milestones:
            if prev is not None:
                if ms["num"] <= prev:
                    self.err(ms["line"], "%s is out of order (after M%d): milestones must strictly increase" % (ms["id"], prev))
                elif ms["num"] != prev + 1:
                    self.warn(ms["line"], "gap before %s (previous M%d)" % (ms["id"], prev))
            elif ms["num"] != 0:
                self.warn(ms["line"], "first milestone is %s; the skeleton milestone is normally M0" % ms["id"])
            prev = ms["num"] if prev is None or ms["num"] > prev else prev
            f = ms["fields"]
            if "goal" not in f or not f["goal"][0]:
                self.warn(ms["line"], "%s has no 'Goal:' line (one playable increment in one sentence)" % ms["id"])
            if "exit" not in f or not f["exit"][0]:
                self.err(ms["line"], "%s has no 'Exit:' line (testable exit criteria)" % ms["id"])
            st = f.get("status", ("", ms["line"]))
            if st[0] and st[0].lower() not in MILESTONE_STATUS:
                self.err(st[1], "%s status '%s' not in %s" % (ms["id"], st[0], sorted(MILESTONE_STATUS)))
            elif not st[0]:
                self.warn(ms["line"], "%s has no 'Status:' line" % ms["id"])
            if not ms["stories"]:
                self.err(ms["line"], "%s has no stories ('### %s-S01 <title>')" % (ms["id"], ms["id"]))
            for s in ms["stories"]:
                self.check_story(ms, s, seen_story, seen_ac)
        ids = [m["id"] for m in self.milestones]
        if len(ids) != len(set(ids)):
            dup = sorted(set(i for i in ids if ids.count(i) > 1))
            self.err(0, "duplicate milestone IDs: %s" % ", ".join(dup))
        active = [m for m in self.milestones if m["fields"].get("status", ("",))[0].lower() == "active"]
        if len(active) > 1:
            self.err(active[1]["line"], "more than one active milestone: %s" % ", ".join(m["id"] for m in active))
        elif not active and any(m["fields"].get("status", ("",))[0].lower() != "done" for m in self.milestones):
            self.warn(0, "no milestone has 'Status: active'")
        elif active and self.current and active[0]["id"] != self.current:
            self.warn(active[0]["line"], "active milestone %s differs from 'Current milestone: %s'" % (active[0]["id"], self.current))
        if self.current is None:
            self.err(0, "missing header line 'Current milestone: M<n>'")
        elif self.current not in ids:
            self.err(self.current_line, "Current milestone %s is not a milestone in this file" % self.current)
        else:
            for m in self.milestones:
                if m["id"] == self.current:
                    break
                if m["fields"].get("status", ("",))[0].lower() != "done":
                    self.warn(m["line"], "%s is before the current milestone %s but not marked done" % (m["id"], self.current))

    def check_story(self, ms, s, seen_story, seen_ac):
        sid = s["id"]
        m = RE_STORY_ID.match(sid)
        if not m:
            self.err(s["line"], "story ID '%s' must look like %s-S01" % (sid, ms["id"]))
        elif int(m.group(1)) != ms["num"]:
            self.err(s["line"], "story %s sits under %s (prefix must match the milestone)" % (sid, ms["id"]))
        if sid in seen_story:
            self.err(s["line"], "duplicate story ID %s (first on line %d)" % (sid, seen_story[sid]))
        seen_story.setdefault(sid, s["line"])
        if not s["title"]:
            self.warn(s["line"], "story %s has no title" % sid)
        f = s["fields"]
        st = f.get("status")
        if not st:
            self.err(s["line"], "story %s has no '- Status:' line" % sid)
        elif st[0].lower() not in STORY_STATUS:
            self.err(st[1], "story %s status '%s' not in %s" % (sid, st[0], sorted(STORY_STATUS)))
        ow = f.get("owner skill")
        if not ow:
            self.err(s["line"], "story %s has no '- Owner skill:' line" % sid)
        else:
            names = [n.strip() for n in re.split(r"[,+/]", ow[0]) if n.strip()]
            bad = [n for n in names if n not in SKILLS]
            if not names or bad:
                self.err(ow[1], "story %s owner skill %s not in the skill set" % (sid, bad or "(empty)"))
        if not s["acs"]:
            self.err(s["line"], "story %s has no acceptance criteria rows" % sid)
        for ac in s["acs"]:
            self.check_ac(sid, ac, seen_ac)

    def check_ac(self, sid, ac, seen_ac):
        ln, cells = ac["line"], ac["cells"]
        if len(cells) < 4:
            self.err(ln, "criterion row needs 4 cells (AC | Given/When/Then | Test | Signal), got %d" % len(cells))
            return
        aid, gwt, ttype, signal = cells[0], cells[1], cells[2], cells[3]
        m = RE_AC_ID.match(aid)
        if not m:
            self.err(ln, "criterion ID '%s' must look like %s-AC1" % (aid, sid))
        elif m.group(1) != sid:
            self.err(ln, "criterion %s is under story %s (prefix must match)" % (aid, sid))
        if aid in seen_ac:
            self.err(ln, "duplicate criterion ID %s (first on line %d)" % (aid, seen_ac[aid]))
        seen_ac.setdefault(aid, ln)
        def pos(word):
            mm = re.search(r"\b%s\b" % word, gwt, re.I)
            return mm.start() if mm else -1
        gi, wi, ti = pos("given"), pos("when"), pos("then")
        if min(gi, wi, ti) < 0 or not (gi < wi < ti):
            self.err(ln, "%s: criterion must read 'Given ... When ... Then ...'" % aid)
        elif VAGUE.search(gwt[ti:]) and not re.search(r"\d", gwt[ti:]):
            self.warn(ln, "%s: vague 'Then' without a number (%s); state a threshold" % (aid, VAGUE.search(gwt[ti:]).group(0)))
        tt = TEST_TYPES.get(ttype.strip().lower())
        if not tt:
            self.err(ln, "%s: test type '%s' not in EditMode|PlayMode|play-verify|headless|manual" % (aid, ttype))
        sigs = [x.strip() for x in signal.split(";") if x.strip()]
        if not sigs or signal.strip() in ("-", "?", "TBD", "tbd"):
            self.err(ln, "%s: no observable signal" % aid)
            return
        kinds = set()
        for sg in sigs:
            if ":" not in sg:
                self.err(ln, "%s: signal '%s' must be kind:value (kinds: %s)" % (aid, sg, ", ".join(sorted(SIGNAL_KINDS))))
                continue
            kind, val = sg.split(":", 1)
            kind, val = kind.strip().strip("`").lower(), val.strip().strip("`")
            if kind not in SIGNAL_KINDS:
                self.err(ln, "%s: unknown signal kind '%s'" % (aid, kind))
                continue
            if not val:
                self.err(ln, "%s: signal '%s:' has no value" % (aid, kind))
                continue
            kinds.add(kind)
            if kind == "metric" and not RE_METRIC.match(val):
                self.err(ln, "%s: metric '%s' needs '<name> <op> <number>[unit]', e.g. fps_p5 >= 55" % (aid, val))
            if kind == "test" and not RE_TEST.match(val):
                self.err(ln, "%s: test '%s' must be a Fixture.Method name" % (aid, val))
            if kind == "exit" and not re.match(r"^-?\d+$", val):
                self.err(ln, "%s: exit signal '%s' must be an integer exit code" % (aid, val))
            if kind == "screenshot" and " shows " not in (" " + val + " "):
                self.warn(ln, "%s: screenshot signal should say what it shows ('<name> shows <expected>')" % aid)
            if kind == "log" and len(val.strip("\"'")) < 3:
                self.err(ln, "%s: log signal text too short to match reliably" % aid)
        if tt and kinds and not (kinds & REQUIRED_KINDS[tt]):
            self.err(ln, "%s: %s criteria need a %s signal" % (aid, tt, "/".join(sorted(REQUIRED_KINDS[tt]))))

    def counts(self):
        stories = [s for m in self.milestones for s in m["stories"]]
        acs = [a for s in stories for a in s["acs"]]
        return len(self.milestones), len(stories), len(acs)


def milestone_checklist(lint, mid):
    for m in lint.milestones:
        if m["id"] != mid:
            continue
        print("%s %s  (Exit: %s)" % (m["id"], m["title"], m["fields"].get("exit", ("?",))[0]))
        groups = {}
        for s in m["stories"]:
            for a in s["acs"]:
                c = a["cells"] + ["", "", "", ""]
                groups.setdefault(TEST_TYPES.get(c[2].lower(), c[2]), []).append((c[0], c[1], c[3], s["fields"].get("owner skill", ("?",))[0]))
        for tt in ("EditMode", "PlayMode", "play-verify", "headless", "manual"):
            for aid, gwt, sig, owner in groups.get(tt, []):
                print("[%s] %s | %s | %s | owner %s" % (tt, aid, gwt, sig, owner))
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description="Validate BACKLOG.md structure (milestones -> stories -> acceptance criteria).",
                                 epilog="Examples:\n  backlog_lint.py BACKLOG.md\n  backlog_lint.py BACKLOG.md --strict\n"
                                        "  backlog_lint.py BACKLOG.md --milestone M1   # print M1 criteria grouped by test type\n"
                                        "  backlog_lint.py BACKLOG.md --json",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("backlog", help="path to BACKLOG.md")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--json", action="store_true", help="print the parsed backlog as JSON after linting")
    ap.add_argument("--milestone", metavar="M<n>", help="after linting, print that milestone's criteria checklist")
    a = ap.parse_args()
    try:
        with open(a.backlog, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        print("ERROR: cannot read %s: %s" % (a.backlog, e), file=sys.stderr)
        print("RESULT: FAIL cannot read file")
        return 2
    lint = Linter(a.backlog)
    lint.parse(text)
    lint.check()
    for ln, msg in sorted(lint.errors):
        print("ERROR %s:%d: %s" % (a.backlog, ln, msg))
    for ln, msg in sorted(lint.warnings):
        print("WARN  %s:%d: %s" % (a.backlog, ln, msg))
    nm, ns, na = lint.counts()
    if a.json:
        print(json.dumps({"current": lint.current, "milestones": [
            {"id": m["id"], "title": m["title"], "status": m["fields"].get("status", ("",))[0],
             "exit": m["fields"].get("exit", ("",))[0],
             "stories": [{"id": s["id"], "title": s["title"], "status": s["fields"].get("status", ("",))[0],
                          "owner": s["fields"].get("owner skill", ("",))[0],
                          "visual": {"yes": True, "no": False}.get(s["fields"].get("visual", ("",))[0].lower()),
                          "critique": {"yes": True, "no": False}.get(s["fields"].get("critique", ("",))[0].lower()),
                          "acs": [dict(zip(["id", "gwt", "test", "signal"], ac["cells"][:4])) for ac in s["acs"]]}
                         for s in m["stories"]]} for m in lint.milestones]}, indent=2))
    if a.milestone and not milestone_checklist(lint, a.milestone):
        print("ERROR: milestone %s not found" % a.milestone)
        print("RESULT: FAIL milestone not found")
        return 2
    n_err = len(lint.errors) + (len(lint.warnings) if a.strict else 0)
    if n_err:
        print("RESULT: FAIL %d error(s), %d warning(s)" % (len(lint.errors), len(lint.warnings)))
        return 1
    print("RESULT: OK %d milestones, %d stories, %d criteria, %d warning(s), current %s"
          % (nm, ns, na, len(lint.warnings), lint.current))
    return 0


if __name__ == "__main__":
    sys.exit(main())
