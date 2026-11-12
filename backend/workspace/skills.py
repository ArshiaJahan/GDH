"""Skills: folders with a SKILL.md (YAML-ish frontmatter: name, description, optional keys).

Built-in skills ship in the repo's `skills/` folder; user skills live in the data dir
and override built-ins with the same name.

Skills written for Workspace mark themselves with `runtime: workspace` in their
frontmatter (the delegation skill is native by name, since its file stays byte-identical
to the published version). Every other skill is assumed to come from Claude Code, so
`skills_prompt` adds one short note mapping Claude Code's tools to Workspace's.
"""
from __future__ import annotations

import logging
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .config import data_dir, get_config

if TYPE_CHECKING:
    from .features.hookbus import TurnState

log = logging.getLogger(__name__)

# Built-in skills shown first in the composer's skill menu (in this order).
FEATURED_SKILLS = ["graphify", "grill-me", "claude-handoff", "game-designer",
                   "cost-effective-claude-delegation", "high-performance-claude-delegation", "unity-router"]
NATIVE_BY_NAME = {"delegation"}
MAX_SKILL_FILE = 200_000


def builtin_skills_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        return Path(getattr(sys, "_MEIPASS", ".")) / "skills"
    return Path(__file__).resolve().parents[2] / "skills"


def user_skills_dir() -> Path:
    p = data_dir() / "skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


_FM = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.S)
_KEY = re.compile(r"^([A-Za-z0-9_.-]+)[ \t]*:(.*)$")


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return re.sub(r'\\(["\\])', r"\1", v[1:-1])
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v.strip('"')  # the old behaviour for anything else


def parse_skill(text: str) -> tuple[dict[str, str], str]:
    """Split SKILL.md into (frontmatter, body).

    Handles the YAML subset skills use: `key: value` lines with plain, "double" or
    'single' quoted values, `>` / `|` block scalars, indented continuation lines,
    comments and CRLF line endings. Nested mappings and lists keep their raw text.
    """
    m = _FM.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    lines = m.group(1).replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        km = _KEY.match(line)
        if not km:  # comments, stray lines
            continue
        key, raw = km.group(1), km.group(2).strip()
        cont: list[str] = []  # indented (or blank) lines that belong to this key
        while i < len(lines) and (lines[i][:1].isspace() or not lines[i].strip()):
            cont.append(lines[i])
            i += 1
        filled = [c for c in cont if c.strip()]
        if not filled:
            meta[key] = _unquote(raw)
        elif re.fullmatch(r"[>|][+-]?\d*", raw):  # block scalar
            while not cont[-1].strip():
                cont.pop()
            ind = min(len(c) - len(c.lstrip()) for c in filled)
            body = "\n".join(c[ind:] if c.strip() else "" for c in cont)
            # literal keeps newlines; folded joins lines with spaces and keeps blank lines as breaks
            meta[key] = body.strip() if raw[0] == "|" else \
                re.sub(r"(?<!\n)\n(?!\n)", " ", body).replace("\n\n", "\n").strip()
        elif not raw and (filled[0].lstrip().startswith("- ") or _KEY.match(filled[0].strip())):
            meta[key] = "\n".join(filled)  # nested list or mapping: keep its raw text
        else:  # a plain or quoted scalar wrapped over several lines
            meta[key] = _unquote(" ".join([raw, *(c.strip() for c in filled)]).strip())
    return meta, text[m.end():]


def is_native(name: str, meta: dict[str, str]) -> bool:
    return name in NATIVE_BY_NAME or meta.get("runtime", "").strip().lower() == "workspace"


def set_skill_name(content: str, name: str) -> str:
    """Make the frontmatter name the folder name: every key that parses as `name` (`name:`,
    `name :`, duplicates, block scalars with their continuation lines) is dropped and one
    `name: <name>` goes first. Content without frontmatter is unchanged (it lists under its
    folder name). Files that already have exactly one matching `name:` are left byte-identical."""
    m = _FM.match(content)
    if not m:
        return content
    lines = m.group(1).replace("\r\n", "\n").split("\n")
    n_names = sum(1 for km in map(_KEY.match, lines) if km and km.group(1) == "name")
    if n_names == 1 and parse_skill(content)[0].get("name") == name:
        return content
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        km = _KEY.match(line)
        if km and km.group(1) == "name":
            while i < len(lines) and (lines[i][:1].isspace() or not lines[i].strip()):
                i += 1  # its continuation lines go with it
            continue
        out.append(line)
    while out and (out[0][:1].isspace() or not out[0].strip()):
        out.pop(0)  # orphan lines the parser ignores; they'd otherwise continue the new name
    nl = "\r\n" if "\r\n" in m.group(1) else "\n"
    new = content[:m.start(1)] + nl.join([f"name: {name}", *out]) + content[m.end(1):]
    if parse_skill(new)[0].get("name") != name:  # defensive: never save a file that parses to another name
        raise ValueError(f"couldn't set the skill's frontmatter name to '{name}'")
    return new


def list_skills() -> list[dict]:
    found: dict[str, dict] = {}
    for src, root in (("builtin", builtin_skills_dir()), ("user", user_skills_dir())):
        if not root.exists():
            continue
        for f in sorted(root.glob("*/SKILL.md")):
            meta, _ = parse_skill(f.read_text())
            name = meta.get("name") or f.parent.name
            if src == "user" and name != f.parent.name:
                # A user skill is known by its folder: a file whose frontmatter claims another name
                # must not shadow that skill (e.g. a built-in that every session enables).
                log.warning("user skill %s: frontmatter name %r differs from its folder; using the folder name",
                            f.parent, name)
                name = f.parent.name
            found[name] = {"name": name, "description": meta.get("description", ""), "path": str(f), "source": src,
                           "native": is_native(name, meta), "featured": src == "builtin" and name in FEATURED_SKILLS,
                           "argument_hint": meta.get("argument-hint", ""),
                           # a user copy that takes precedence over the built-in of the same name
                           "overrides_builtin": src == "user" and found.get(name, {}).get("source") == "builtin"}
    return list(found.values())


def get_skill(name: str) -> dict | None:
    for s in list_skills():
        if s["name"] == name:
            return {**s, "content": Path(s["path"]).read_text()}
    return None


NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def _check_name(name: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise ValueError("skill names are lowercase letters, digits and dashes")


def _builtin_folder(name: str) -> Path | None:
    d = builtin_skills_dir() / name
    return d if (d / "SKILL.md").is_file() else None


def _copy_builtin(name: str) -> bool:
    """Copy a built-in skill's whole folder (references/, scripts/, templates/ too) into the user
    skills dir, where it overrides the built-in. Does nothing when the user already has that folder."""
    src, dest = _builtin_folder(name), user_skills_dir() / name
    if not src or dest.exists():
        return False
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".*", "__pycache__"))
    return True


def save_skill(name: str, content: str) -> dict:
    _check_name(name)
    content = set_skill_name(content, name)  # the folder name is the skill's name, whatever the file says
    _copy_builtin(name)  # a first override of a built-in keeps the files its SKILL.md refers to
    d = user_skills_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content)
    return get_skill(name)  # type: ignore[return-value]


def customize_skill(name: str) -> dict:
    """"Customize" on a built-in: the user's own editable copy, which takes precedence from now on."""
    _check_name(name)
    if not _builtin_folder(name):
        s = get_skill(name)
        if s and s["source"] == "user":
            return s  # already the user's own
        raise KeyError(name)
    _copy_builtin(name)
    return get_skill(name)  # type: ignore[return-value]


def skill_files(name: str) -> list[str]:
    """Other files in a skill's folder (relative paths), e.g. references/ and templates/."""
    s = get_skill(name)
    if not s:
        return []
    root = Path(s["path"]).parent
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")
                  if p.is_file() and p.name != "SKILL.md" and not any(x.startswith(".") or x == "__pycache__"
                                                                      for x in p.relative_to(root).parts))


def _skill_path(name: str, path: str) -> tuple[dict, Path]:
    """(skill, file) for a path inside the skill's folder; FileNotFoundError for anything else."""
    s = get_skill(name)
    if not s:
        raise KeyError(name)
    root = Path(s["path"]).parent.resolve()
    p = (root / path).resolve()
    if not path or root not in p.parents or not p.is_file() or (p.name == "SKILL.md" and p.parent == root):
        raise FileNotFoundError(f"{path} is not a file in the {name} skill")
    if any(x.startswith(".") or x == "__pycache__" for x in p.relative_to(root).parts):
        raise FileNotFoundError(f"{path} is not a file in the {name} skill")
    return s, p


def skill_file(name: str, path: str) -> dict:
    """One of a skill's other files for the editor: text (capped) or a note that it's binary."""
    s, p = _skill_path(name, path)
    raw = p.read_bytes()
    binary = b"\0" in raw[:8192]
    if not binary:
        try:
            raw[:MAX_SKILL_FILE].decode("utf-8")
        except UnicodeDecodeError as e:
            binary = e.start < MAX_SKILL_FILE - 4  # a cut multibyte character at the cap is fine
    return {"path": path, "size": len(raw), "binary": binary, "truncated": not binary and len(raw) > MAX_SKILL_FILE,
            "content": "" if binary else raw[:MAX_SKILL_FILE].decode("utf-8", errors="replace"),
            "editable": s["source"] == "user"}


def write_skill_file(name: str, path: str, content: str) -> dict:
    """Save one of a user skill's existing text files (built-ins are read-only: customize them first)."""
    s, p = _skill_path(name, path)
    if s["source"] != "user":
        raise PermissionError(f"{name} is a built-in skill; customize it to edit its files")
    if len(content.encode()) > MAX_SKILL_FILE:
        raise ValueError(f"files in a skill are at most {MAX_SKILL_FILE // 1000} KB here")
    cur = skill_file(name, path)
    if cur["binary"] or cur["truncated"]:
        raise ValueError(f"{path} isn't a text file that can be edited here")
    p.write_text(content)
    return skill_file(name, path)


def read_skill_file(name: str, path: str = "") -> str:
    """SKILL.md (with a list of the skill's other files) or one file inside the skill's folder."""
    s = get_skill(name)
    if not s:
        raise KeyError(f"No skill named '{name}'. Available: {', '.join(x['name'] for x in list_skills())}")
    root = Path(s["path"]).parent.resolve()
    if not path or path in ("SKILL.md", "./SKILL.md"):
        files = skill_files(name)
        # The file list first: a long SKILL.md gets cut at the tool output cap, the list must not.
        return (f"[files in {root}: {', '.join(files)}]\n\n" if files else "") + s["content"]
    p = (root / path).resolve()
    if root not in p.parents or not p.is_file():
        raise FileNotFoundError(f"{path} is not a file in the {name} skill")
    return p.read_text(errors="replace")[:MAX_SKILL_FILE]


def skill_invocation(name: str) -> str:
    """The visible first line of a user message that invokes a skill."""
    return f"Use the {name} skill."


TOOL_MAPPING_NOTE = """Skills marked runtime="claude-code" were written for Claude Code. Follow them with Workspace's tools:
- Agent/Task subagents → spawn_subagent (opus → tier claude.deep, sonnet → claude.standard, haiku → claude.fast; \
Codex/GPT models → codex.fast, codex.standard or codex.cli). Parallel or background agents → run_in_background true, \
then get_subagent_result.
- Bash → run_command. Read → read_file; Glob/LS → list_dir; Grep → search. Write → write_file; Edit/MultiEdit → edit_file.
- WebSearch → web_search; WebFetch → web_fetch.
- AskUserQuestion → ask the user in your reply and end the turn. TodoWrite/TaskCreate → a short checklist in your reply.
- Skill tool → read_skill(name). Files a skill names by relative path (references/, templates/, scripts/) → \
read_skill(name, path); run its scripts with run_command using the skill's folder.
- MCP tools named in a skill by bare name (e.g. read_console) are available as mcp__<server>__<tool> when that \
MCP server is enabled for the session.
- $ARGUMENTS → the user's request in the message that invoked the skill.
- Any other tool → use the closest available tool, or tell the user what's missing."""


def skills_prompt(names: list[str]) -> str:
    parts = []
    foreign = False
    for n in names:
        s = get_skill(n)
        if s:
            meta, body = parse_skill(s["content"])
            if s["native"]:
                parts.append(f'<skill name="{n}">\n{body.strip()}\n</skill>')
            else:
                foreign = True
                folder = Path(s["path"]).parent
                parts.append(f'<skill name="{n}" runtime="claude-code" folder="{folder}">\n{body.strip()}\n</skill>')
    if foreign:
        parts.insert(0, TOOL_MAPPING_NOTE)
    return "\n\n".join(parts)


def system_skill_segments(settings: dict) -> list[str]:
    """The skill part of the main agent's system prompt for a session with these settings, as
    system segments (the loop puts them right after BASE_SYSTEM). Progressive sessions only put
    pinned skills and the index here: loading a skill never changes these cached segments."""
    settings = settings or {}
    if settings.get("skill_mode") == "progressive":
        pinned = pinned_skill_names(settings)
        parts = []
        if text := "\n\n".join(t for n in pinned if (t := skill_load_text(n))):
            parts.append("Enabled skills:\n\n" + text)
        if any(not s["native"] for s in list_skills()):
            parts.append(TOOL_MAPPING_NOTE)
        parts.append(skills_index(settings))
        return parts
    if sp := skills_prompt((settings or {}).get("skills", [])):
        return ["Enabled skills:\n\n" + sp]
    return []


def turn_skill_segments(settings: dict, turn: TurnState | None) -> list[str]:
    """Freeze progressive skill text for the active turn, including catalog and pin edits.

    TurnState is discarded at turn end, so the next turn sees the updated catalog and pins.
    Legacy sessions still build exactly the same prompt on every call.
    """
    if turn is not None and "skill_segments" in turn.data:
        return list(turn.data["skill_segments"])
    parts = system_skill_segments(settings)
    if turn is not None and settings.get("skill_mode") == "progressive":
        turn.data["skill_segments"] = tuple(parts)
    return parts


def pinned_skill_names(settings: dict) -> list[str]:
    """Delegation remains a system skill; users can pin and unpin the other protocols."""
    return list(dict.fromkeys([*settings.get("pinned_skills", []), "delegation"]))


def skills_index(settings: dict) -> str:
    """A stable, name-sorted index of installed skills, excluding the pinned full text."""
    pinned = set(pinned_skill_names(settings))
    limit = max(0, int(get_config().skills.get("index_description_chars", 300)))
    lines = ["<skill-index>"]
    for s in sorted(list_skills(), key=lambda s: s["name"]):
        if s["name"] not in pinned:
            description = " ".join(s["description"].split())[:limit]
            lines.append(f"- {s['name']}: {description}")
    lines += ["To follow a skill, load it first with read_skill(name); a loaded skill stays loaded until the "
              "conversation is compacted and it is no longer among the 3 most recent.", "</skill-index>"]
    return "\n".join(lines)


def skill_load_text(name: str) -> str:
    """The same skill wrapper as skills_prompt, without the system-wide tool mapping note."""
    s = get_skill(name)
    if not s:
        return ""
    _meta, body = parse_skill(s["content"])
    if s["native"]:
        return f'<skill name="{name}">\n{body.strip()}\n</skill>'
    folder = Path(s["path"]).parent
    return f'<skill name="{name}" runtime="claude-code" folder="{folder}">\n{body.strip()}\n</skill>'


def skill_lru(settings: dict, name: str, max_loaded: int) -> list[str]:
    """Touch one loaded skill; pinned skills never take a slot in the LRU."""
    pinned = set(pinned_skill_names(settings))
    loaded = list(dict.fromkeys(n for n in settings.get("loaded_skills", []) if n != name and n not in pinned))
    if name not in pinned:
        loaded.append(name)
    return loaded[-max_loaded:] if max_loaded > 0 else []
