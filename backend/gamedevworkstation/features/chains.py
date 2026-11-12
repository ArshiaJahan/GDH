"""Workflow templates ("chains"): the phase lists campaigns and chains are built from.

A template is a TOML file in a skill's `chains/` folder (`skills/<skill>/chains/*.toml`). The
built-ins ship with the Unity pack in `skills/unity-router/chains/`; user skills can ship more and
are trusted on install, like the rest of the skill. Every file is validated when it is loaded; an
invalid one is left out and listed with its errors (GET /api/chains shows them).

    id = "new-mechanic"                 # [a-z0-9-], unique
    title = "New mechanic"
    summary = "Spec → backlog story → code → …"
    kinds = ["chain", "campaign"]       # what it can run as (default both)
    applies_to = "unity"                # any (default) | unity (ProjectSettings/ProjectVersion.txt)
                                        # | backlog (a BACKLOG.md in the folder)
    critique = false                    # true: L4 critique is required for the stories it touches
    blocking_gates = []                 # gate ids that block in this workflow (hooks integration)

    [[phase]]
    name = "Spec"                       # with for_each: "{id} {title}" of each story
    type = "plan"                       # research | plan | build | wire | verify | prune (hooks read it:
                                        # verify-only gates such as unity.tests fire in verify phases)
    skills = ["game-designer"]          # loaded when the phase starts
    done_when = [{ type = "file_exists", path = "docs/specs/*.md", newer_than = "phase_start" }]
    retries = 3                         # failed campaign_phase_done calls before the campaign parks
    instructions = "…"                  # optional, shown in the brief
    critique = false                    # optional, L4 required while this phase runs
    fleet = false                       # optional, fleet-eligible (a wave of units may run it; WP6/WP7)
    for_each = "milestone_story"        # optional: one phase per story of the current milestone

`done_when` conditions (every phase needs at least one that isn't `manual`):

| type             | fields                                              | passes when (observed by the app)              |
|------------------|-----------------------------------------------------|------------------------------------------------|
| file_exists      | path (glob), newer_than = "phase_start"             | a matching file exists (changed since start)   |
| command_passes   | observe (script name, e.g. backlog_lint)            | its newest observed RESULT since the phase     |
|                  |                                                     | started is OK (backlog_lint runs in-process)   |
| metric_threshold | key, op (>= <= > < == !=), value                    | the newest [VERIFY]/[PERF] value since start   |
| gate             | level (L1 L2 L3 L4 manual story) or name (gate id); | quality-ladder level of the campaign's stories |
|                  | stories = scope | phase | milestone; expect = fail;  | (or the hook gate) passes                      |
|                  | tests = "repro"                                     |                                                |
| visual_verify    | newer_than = "phase_start"                          | a fresh screenshot                             |
| git_clean        | paths = [...]                                       | `git status` shows nothing there               |
| manual           | question                                            | the user answers Pass on a card                |

The done_when types are adapted from SethGammon/Citadel (MIT).
"""
from __future__ import annotations

import copy
import logging
import re
import tomllib
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PHASE_TYPES = ("research", "plan", "build", "wire", "verify", "prune")
KINDS = ("chain", "campaign")
APPLIES = ("any", "unity", "backlog")
DONE_TYPES = ("file_exists", "command_passes", "metric_threshold", "gate", "visual_verify", "git_clean", "manual")
GATE_LEVELS = ("L1", "L2", "L3", "L4", "manual", "story")
GATE_STORIES = ("scope", "phase", "milestone")
METRIC_OPS = (">=", "<=", ">", "<", "==", "!=")
FOR_EACH = ("milestone_story",)
DEFAULT_RETRIES = 3

TEMPLATE_KEYS = {"id", "title", "summary", "kinds", "applies_to", "critique", "blocking_gates", "phase"}
PHASE_KEYS = {"name", "type", "skills", "done_when", "retries", "instructions", "critique", "fleet", "for_each",
              "stories"}
CONDITION_KEYS = {
    "file_exists": {"path", "newer_than"},
    "command_passes": {"observe"},
    "metric_threshold": {"key", "op", "value"},
    "gate": {"level", "name", "stories", "expect", "tests"},
    "visual_verify": {"newer_than"},
    "git_clean": {"paths"},
    "manual": {"question"},
}
RE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
RE_STORY = re.compile(r"^M\d+-S\d{2,3}$")


class TemplateError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# ------------------------------------------------------------------- validation


def _str_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)


def validate_condition(d: Any, where: str) -> tuple[dict | None, list[str]]:
    """One done_when entry → (normalized copy, errors)."""
    if not isinstance(d, dict):
        return None, [f"{where}: a condition must be a table like {{ type = \"gate\", level = \"L1\" }}"]
    t = d.get("type")
    if t not in DONE_TYPES:
        return None, [f"{where}: unknown type {t!r} (one of: {', '.join(DONE_TYPES)})"]
    errs = [f"{where}: unknown key {k!r} for {t}" for k in d if k != "type" and k not in CONDITION_KEYS[t]]
    out = {"type": t}
    if t == "file_exists":
        if not isinstance(d.get("path"), str) or not d["path"].strip():
            errs.append(f"{where}: file_exists needs path (a glob relative to the project)")
        elif d["path"].startswith("/") or ".." in Path(d["path"]).parts:
            errs.append(f"{where}: file_exists path must stay inside the project")
        else:
            out["path"] = d["path"].strip()
    if t in ("file_exists", "visual_verify") and "newer_than" in d:
        if d["newer_than"] != "phase_start":
            errs.append(f"{where}: newer_than can only be \"phase_start\"")
        else:
            out["newer_than"] = "phase_start"
    if t == "command_passes":
        if not isinstance(d.get("observe"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", d["observe"]):
            errs.append(f"{where}: command_passes needs observe (a script name such as backlog_lint)")
        else:
            out["observe"] = re.sub(r"\.(py|sh)$", "", d["observe"])
    if t == "metric_threshold":
        if not isinstance(d.get("key"), str) or not d["key"].strip():
            errs.append(f"{where}: metric_threshold needs key (a [VERIFY] or [PERF] metric)")
        if d.get("op") not in METRIC_OPS:
            errs.append(f"{where}: metric_threshold op must be one of {' '.join(METRIC_OPS)}")
        if isinstance(d.get("value"), bool) or not isinstance(d.get("value"), (int, float)):
            errs.append(f"{where}: metric_threshold needs a numeric value")
        out.update({k: d[k] for k in ("key", "op", "value") if k in d})
    if t == "gate":
        level, name = d.get("level"), d.get("name")
        if (level is None) == (name is None):
            errs.append(f"{where}: gate needs either level ({' '.join(GATE_LEVELS)}) or name (a gate id)")
        elif level is not None and level not in GATE_LEVELS:
            errs.append(f"{where}: gate level must be one of {' '.join(GATE_LEVELS)}")
        elif name is not None and (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", name)):
            errs.append(f"{where}: gate name must be a gate id such as unity.antipatterns")
        if "stories" in d and d["stories"] not in GATE_STORIES:
            errs.append(f"{where}: gate stories must be one of {' '.join(GATE_STORIES)}")
        if "expect" in d and (d["expect"] not in ("pass", "fail") or level != "L2"):
            errs.append(f"{where}: expect = \"fail\" is only for level L2 (a reproducing test)")
        if "tests" in d and (d["tests"] != "repro" or level != "L2"):
            errs.append(f"{where}: tests = \"repro\" is only for level L2")
        out.update({k: d[k] for k in ("level", "name", "stories", "expect", "tests") if k in d})
    if t == "git_clean":
        if "paths" in d and not _str_list(d["paths"]):
            errs.append(f"{where}: git_clean paths must be a list of folders or files")
        else:
            out["paths"] = list(d.get("paths") or [])
    if t == "manual":
        if "question" in d and not isinstance(d["question"], str):
            errs.append(f"{where}: manual question must be text")
        out["question"] = str(d.get("question") or "").strip()
    return (None if errs else out), errs


def validate_phase(p: Any, where: str) -> tuple[dict | None, list[str]]:
    if not isinstance(p, dict):
        return None, [f"{where}: a phase must be a table"]
    errs = [f"{where}: unknown key {k!r}" for k in p if k not in PHASE_KEYS]
    name = p.get("name")
    if not isinstance(name, str) or not name.strip():
        errs.append(f"{where}: phase needs a name")
    where = f"{where} ({name})" if isinstance(name, str) and name.strip() else where
    if p.get("type") not in PHASE_TYPES:
        errs.append(f"{where}: type must be one of {', '.join(PHASE_TYPES)}")
    skills = p.get("skills", [])
    if not isinstance(skills, list) or not all(isinstance(s, str) and s.strip() for s in skills):
        errs.append(f"{where}: skills must be a list of skill names")
        skills = []
    retries = p.get("retries", DEFAULT_RETRIES)
    if isinstance(retries, bool) or not isinstance(retries, int) or not 1 <= retries <= 10:
        errs.append(f"{where}: retries must be a whole number from 1 to 10")
    if "for_each" in p and p["for_each"] not in FOR_EACH:
        errs.append(f"{where}: for_each must be one of {', '.join(FOR_EACH)}")
    if "stories" in p and (not _str_list(p["stories"]) or not all(RE_STORY.match(s) for s in p["stories"])):
        errs.append(f"{where}: stories must be BACKLOG.md story ids such as M1-S02")
    for k in ("critique", "fleet"):
        if k in p and not isinstance(p[k], bool):
            errs.append(f"{where}: {k} must be true or false")
    if "instructions" in p and not isinstance(p["instructions"], str):
        errs.append(f"{where}: instructions must be text")
    raw = p.get("done_when")
    conds: list[dict] = []
    if not isinstance(raw, list) or not raw:
        errs.append(f"{where}: done_when needs at least one condition")
    else:
        for i, d in enumerate(raw):
            c, e = validate_condition(d, f"{where} done_when[{i}]")
            errs += e
            if c:
                conds.append(c)
        if conds and all(c["type"] == "manual" for c in conds):
            errs.append(f"{where}: needs at least one condition the app can check itself (not only manual)")
    if errs:
        return None, errs
    out = {"name": name.strip(), "type": p["type"], "skills": [s.strip() for s in skills], "done_when": conds,
           "retries": retries}
    for k in ("instructions", "critique", "fleet", "for_each", "stories"):
        if k in p:
            out[k] = p[k]
    return out, []


def validate_phases(phases: Any, where: str = "phases") -> tuple[list[dict], list[str]]:
    if not isinstance(phases, list) or not phases:
        return [], [f"{where}: at least one phase is needed"]
    out, errs = [], []
    for i, p in enumerate(phases):
        v, e = validate_phase(p, f"phase {i + 1}")
        errs += e
        if v:
            out.append(v)
    return out, errs


def validate_template(data: Any, source: str = "") -> dict:
    """A parsed TOML file → the normalized template. Raises TemplateError listing every problem."""
    if not isinstance(data, dict):
        raise TemplateError(["not a table"])
    errs = [f"unknown key {k!r}" for k in data if k not in TEMPLATE_KEYS]
    tid = data.get("id")
    if not isinstance(tid, str) or not RE_ID.match(tid):
        errs.append("id must be lowercase letters, digits and dashes")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        errs.append("title is required")
    kinds = data.get("kinds", list(KINDS))
    if not isinstance(kinds, list) or not kinds or any(k not in KINDS for k in kinds):
        errs.append("kinds must list chain and/or campaign")
        kinds = list(KINDS)
    applies = data.get("applies_to", "any")
    if applies not in APPLIES:
        errs.append(f"applies_to must be one of {', '.join(APPLIES)}")
    if "critique" in data and not isinstance(data["critique"], bool):
        errs.append("critique must be true or false")
    if "blocking_gates" in data and not _str_list(data["blocking_gates"]):
        errs.append("blocking_gates must be a list of gate ids")
    phases, e = validate_phases(data.get("phase"), "phase")
    errs += e
    if any(p.get("for_each") for p in phases) and "chain" in kinds:
        errs.append("for_each phases are generated from BACKLOG.md: only kind campaign can use them")
    if errs:
        raise TemplateError(errs)
    return {"id": tid, "title": data["title"].strip(), "summary": str(data.get("summary") or "").strip(),
            "kinds": list(dict.fromkeys(kinds)), "applies_to": applies, "critique": bool(data.get("critique", False)),
            "blocking_gates": list(data.get("blocking_gates") or []), "phases": phases, "source": source}


# -------------------------------------------------------------------- discovery


def template_dirs() -> list[tuple[str, Path]]:
    """(skill name, its chains/ folder) for every installed skill that has one. A user skill with
    a built-in's name replaces it, chains included (skills.list_skills decides)."""
    from ..skills import list_skills

    out = []
    for s in list_skills():
        d = Path(s["path"]).parent / "chains"
        if d.is_dir():
            out.append((s["name"], d))
    return out


def discover() -> tuple[dict[str, dict], list[dict]]:
    """Every valid template by id, and the files that failed ({file, skill, errors})."""
    templates: dict[str, dict] = {}
    bad: list[dict] = []
    for skill, d in template_dirs():
        for f in sorted(d.glob("*.toml")):
            try:
                t = validate_template(tomllib.loads(f.read_text(encoding="utf-8")), source=str(f))
            except TemplateError as e:
                bad.append({"file": str(f), "skill": skill, "errors": e.errors})
                continue
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
                bad.append({"file": str(f), "skill": skill, "errors": [f"not readable TOML: {e}"]})
                continue
            if t["id"] in templates:
                bad.append({"file": str(f), "skill": skill,
                            "errors": [f"id {t['id']!r} is already used by {templates[t['id']]['source']}"]})
                continue
            t["skill"] = skill
            templates[t["id"]] = t
    return templates, bad


def get_template(tid: str) -> dict | None:
    t = discover()[0].get(tid)
    return copy.deepcopy(t) if t else None


def is_unity(folder: Path | str | None) -> bool:
    return bool(folder) and (Path(folder) / "ProjectSettings" / "ProjectVersion.txt").is_file()


def applies(t: dict, folder: Path | str | None) -> bool:
    a = t.get("applies_to", "any")
    if a == "unity":
        return is_unity(folder)
    if a == "backlog":
        return bool(folder) and (Path(folder) / "BACKLOG.md").is_file()
    return True


def applicable(folder: Path | str | None, kind: str | None = None) -> list[dict]:
    """Templates that apply to the folder (and can run as `kind`), sorted by title."""
    ts = [t for t in discover()[0].values() if applies(t, folder) and (kind is None or kind in t["kinds"])]
    return sorted(ts, key=lambda t: t["title"].lower())


# ------------------------------------------------------------------- expansion


def needs_expansion(phases: list[dict]) -> bool:
    return any(p.get("for_each") for p in phases)


def expand_phases(phases: list[dict], folder: Path | str | None) -> tuple[list[dict], list[str]]:
    """Generate for_each phases from the folder's BACKLOG.md: one per story of the current
    milestone that isn't done yet, in BACKLOG order. Returns (phases, problems); a phase that
    can't be generated yet stays as it is and is reported."""
    out, problems = [], []
    for p in phases:
        if p.get("for_each") != "milestone_story":
            out.append(p)
            continue
        stories = milestone_stories(folder)
        if stories is None:
            problems.append(f"phase {p['name']!r}: needs a BACKLOG.md with a current milestone")
            out.append(p)
            continue
        todo = [s for s in stories if s.status != "done"]
        if not todo:
            problems.append(f"phase {p['name']!r}: every story of the current milestone is already done")
            out.append(p)
            continue
        for s in todo:
            q = {k: copy.deepcopy(v) for k, v in p.items() if k != "for_each"}
            q["name"] = p["name"].replace("{id}", s.id).replace("{title}", s.title).strip() or s.id
            q["stories"] = [s.id]
            out.append(q)
    return out, problems


def milestone_stories(folder: Path | str | None) -> list | None:
    """Stories (ladder.Story) of the current milestone in BACKLOG order, or None."""
    if not folder:
        return None
    try:
        from .ladder import read_backlog

        bl = read_backlog(folder)
    except Exception:  # noqa: BLE001 — the pack scripts may be missing
        log.warning("chains: BACKLOG.md not readable", exc_info=True)
        return None
    if bl is None or not bl.current:
        return None
    return [s for s in bl.stories.values() if s.milestone == bl.current]


# ------------------------------------------------------------------ describing


def describe(c: dict) -> str:
    """One condition in words (UI chips, briefs, the Phases table)."""
    t = c.get("type")
    if t == "file_exists":
        return f"file {c.get('path')}" + (" (new this phase)" if c.get("newer_than") else "")
    if t == "command_passes":
        return f"{c.get('observe')} passes"
    if t == "metric_threshold":
        return f"{c.get('key')} {c.get('op')} {c.get('value')}"
    if t == "gate":
        what = c.get("name") or {"story": "stories done", "manual": "manual checks"}.get(c.get("level"), c.get("level"))
        extra = []
        if c.get("stories"):
            extra.append(f"{c['stories']} stories")
        if c.get("expect") == "fail":
            extra.append("a failing repro test")
        if c.get("tests") == "repro":
            extra.append("repro tests pass")
        return f"gate {what}" + (f" ({', '.join(extra)})" if extra else "")
    if t == "visual_verify":
        return "fresh screenshot" + (" (this phase)" if c.get("newer_than") else "")
    if t == "git_clean":
        return "git clean" + (f": {', '.join(c['paths'])}" if c.get("paths") else "")
    if t == "manual":
        return f"you check: {c.get('question') or 'the phase result'}"
    return str(t)
