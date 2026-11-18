"""Deterministic CI failure triage: turn a failed CI log into a short list of classified failures.

Input is whatever CI hands over: `gh run view <id> --log-failed` output (`<job>\\t<step>\\t<timestamp>
<text>` per line), a raw Actions step log (`<timestamp> <text>`), plain tool output, or a Unity Test
Framework (NUnit 3) / JUnit XML result file. `normalize` strips timestamps, ANSI colours (real ESC
and the literal `^[[36;1m` GitHub leaves in), the BOM and `##[group]` markers; consecutive lines of
one (job, step) form a block.

Each block runs through RULES, an ordered list of regexes with a category, where the file/line/test
come from and an optional fix. The first rule that matches a line owns it, so specific rules come
before generic ones. A block that looks failing (`##[error]`, a non-zero exit) but matches no rule
becomes one `unknown` failure, which `triage()` can hand to an LLM callback.

Categories are ranked by PRECEDENCE: a runner that died mid-test is an infra problem first, a
missing package outranks the compile errors it causes, and so on. `primary` is the top one.
"""
from __future__ import annotations

import logging
import re
import subprocess
import xml.etree.ElementTree as ET
from xml.parsers import expat
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

log = logging.getLogger(__name__)

Category = Literal["compile", "test", "flaky", "infra", "dependency", "timeout", "unknown"]
PRECEDENCE: tuple[str, ...] = ("timeout", "infra", "dependency", "compile", "flaky", "test", "unknown")

MAX_SUMMARY = 200
MAX_FIX = 300
MAX_EVIDENCE_LINES = 8
MAX_EVIDENCE_CHARS = 300
UNKNOWN_KEEP_LINES = 120
NUNIT_MAX_BYTES = 20 * 1024 * 1024
MARKDOWN_MAX_BYTES = 60_000
_MATCH_CHARS = 4000  # longer lines are matched on their start only


class Failure(BaseModel):
    """One classified failure. `file` is repo-relative with forward slashes."""

    model_config = ConfigDict(extra="ignore")

    category: Category
    summary: str
    file: str | None = None
    line: int | None = None
    test: str | None = None
    evidence: list[str] = []
    rule: str | None = None
    source: Literal["rule", "llm", "none"] = "rule"
    confidence: float = 1.0
    fix: str | None = None
    job: str | None = None
    step: str | None = None

    _order: int = PrivateAttr(default=0)  # appearance in the log, for stable sorting

    @field_validator("summary", mode="before")
    @classmethod
    def _one_line(cls, v: Any) -> str:
        s = " ".join(str(v or "").split())
        return s if len(s) <= MAX_SUMMARY else s[: MAX_SUMMARY - 1] + "…"

    @field_validator("fix", mode="before")
    @classmethod
    def _one_line_fix(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = " ".join(str(v).split())
        if not s:
            return None
        return s if len(s) <= MAX_FIX else s[: MAX_FIX - 1] + "…"

    @field_validator("evidence", mode="before")
    @classmethod
    def _cap_evidence(cls, v: Any) -> list[str]:
        lines = [str(x) for x in (v or [])][:MAX_EVIDENCE_LINES]
        return [x if len(x) <= MAX_EVIDENCE_CHARS else x[: MAX_EVIDENCE_CHARS - 1] + "…" for x in lines]


class TriageReport(BaseModel):
    """Failures of one source, sorted by PRECEDENCE then appearance."""

    source: str
    failures: list[Failure]
    blocks: int
    by_rules: int
    by_llm: int = 0
    unclassified: int = 0
    # cleaned lines (last 120) of each unknown block, in the order of the unknown failures
    block_lines: list[list[str]] = Field(default_factory=list, exclude=True)

    @property
    def primary(self) -> Failure | None:
        if not self.failures:
            return None
        return min(self.failures, key=lambda f: PRECEDENCE.index(f.category))

    @property
    def rule_coverage(self) -> float:
        return 1.0 if self.blocks == 0 else self.by_rules / self.blocks


LlmClassify = Callable[[list[str]], Awaitable[Failure | None]]


@dataclass(frozen=True)
class LogLine:
    job: str | None
    step: str | None
    text: str


# ---------------------------------------------------------------------------------------------
# Normalising

_ANSI = re.compile(r"(?:\x1b|\^\[)\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[@-Z\\-_]")
_GH_LINE = re.compile(r"^(?P<job>[^\t]*)\t(?P<step>[^\t]*)\t(?P<rest>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z.*)$")
_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ?")


def normalize(text: str) -> list[LogLine]:
    """Split a log into cleaned lines, keeping the job and step of `gh --log-failed` output."""
    out: list[LogLine] = []
    job: str | None = None
    step: str | None = None
    for raw in text.replace("\ufeff", "").replace("\r\n", "\n").split("\n"):
        m = _GH_LINE.match(raw)
        if m:
            job, step, body = m["job"], m["step"], m["rest"]
        else:
            body = raw
        body = _ANSI.sub("", _TIMESTAMP.sub("", body, count=1))
        body = body.rstrip("\r")
        if "\r" in body:  # progress output rewritten in place: keep what was shown last
            body = body.rsplit("\r", 1)[-1]
        body = body.rstrip()
        if body.startswith("##[endgroup]"):
            continue
        body = body.removeprefix("##[group]")
        out.append(LogLine(job, step, body))
    while out and not out[-1].text:
        out.pop()
    return out


@dataclass
class _Block:
    job: str | None
    step: str | None
    start: int
    lines: list[str]


def _split_blocks(lines: list[LogLine]) -> list[_Block]:
    blocks: list[_Block] = []
    for i, ln in enumerate(lines):
        if blocks and (blocks[-1].job, blocks[-1].step) == (ln.job, ln.step):
            blocks[-1].lines.append(ln.text)
        else:
            blocks.append(_Block(ln.job, ln.step, i, [ln.text]))
    return blocks


_CI_PREFIX = re.compile(
    r"^(?:(?:/home/runner/work|/Users/runner/work|[A-Za-z]:/a|/__w)/[^/]+/[^/]+/|/github/workspace/|.*?/_work/[^/]+/[^/]+/)"
)
_UNITY_ROOT = re.compile(r"^(?:[A-Za-z]:)?/?(?:[^/]+/)*?(?=(?:Assets|Packages)/)")


def clean_path(path: str) -> str:
    """Forward slashes, no CI workspace prefix, Unity paths from Assets/ or Packages/."""
    p = re.sub(r"^\d+>", "", path.strip().strip("'\"").strip()).replace("\\", "/")
    stripped = _CI_PREFIX.sub("", p, count=1)
    if stripped != p or p.startswith("/") or re.match(r"[A-Za-z]:/", p):
        stripped = _UNITY_ROOT.sub("", stripped, count=1)
    while stripped.startswith("./"):
        stripped = stripped[2:]
    return stripped


# ---------------------------------------------------------------------------------------------
# Block context: the pieces of test-runner output that several rules look at

_PYTEST_HEADER = re.compile(r"^_+ (?P<name>\S.*?) _+$")
_PYTEST_LOC = re.compile(r"^(?P<file>(?:[A-Za-z]:[\\/])?[^\s:\"'][^:\"']*?\.py):(?P<line>\d+):(?:\s|$)")
_PY_FRAME = re.compile(r"File \"(?P<file>[^\"]+)\", line (?P<line>\d+)(?:, in (?P<func>\S+))?")
_PYTEST_ZONE_START = re.compile(r"^=+ (?:FAILURES|ERRORS) =+$")
_PYTEST_ZONE_END = re.compile(r"^=+ .* =+$|^##\[")
_PYTEST_SUMMARY = re.compile(r"^(?:FAILED|ERROR) \S+\.py")
_VITEST_ZONE_START = re.compile(r"Failed Tests \d+")
_VITEST_ZONE_END = re.compile(r"^\s*Test Files\s|^##\[")
_JEST_ZONE_START = re.compile(r"^\s*● ")
_JEST_ZONE_END = re.compile(r"^\s*(?:PASS|FAIL)\s|^Test Suites:|^##\[")
_SECTION_PREFIX = re.compile(r"^(?:ERROR at (?:setup|teardown) of |ERROR collecting )")
_LIBRARY_PATH = re.compile(r"site-packages|dist-packages|/lib/python\d|<frozen|importlib|hostedtoolcache")


def _same_file(found: str, want: str) -> bool:
    """`found` (possibly absolute, from a traceback) is the repo-relative file `want`."""
    f = clean_path(found)
    return f == want or f.endswith("/" + want)


class _Ctx:
    """One block's lines plus lazily built lookups (pytest sections, report zones)."""

    def __init__(self, lines: list[str]):
        self.lines = lines
        self._sections: dict[str, tuple[int, int]] | None = None
        self._zone: set[int] | None = None

    def sections(self) -> dict[str, tuple[int, int]]:
        """pytest `____ name ____` sections: name (without ERROR at setup of ...) -> (start, end)."""
        if self._sections is None:
            self._sections = {}
            heads = []
            for i, t in enumerate(self.lines):
                m = _PYTEST_HEADER.match(t)
                if m and set(m["name"]) - {"_", " "}:
                    heads.append((i, m["name"]))
            for k, (i, name) in enumerate(heads):
                end = heads[k + 1][0] if k + 1 < len(heads) else len(self.lines)
                for j in range(i + 1, end):
                    if _PYTEST_ZONE_END.match(self.lines[j]):
                        end = j
                        break
                key = _SECTION_PREFIX.sub("", name)
                self._sections.setdefault(key, (i, end))
                if name.startswith("ERROR collecting "):
                    self._sections.setdefault(clean_path(key), (i, end))
        return self._sections

    def in_report(self, i: int) -> bool:
        """True for lines of test-report output (tracebacks, diffs), where infra words are just text."""
        if self._zone is None:
            zone: set[int] = set()
            for start, end in ((_PYTEST_ZONE_START, _PYTEST_ZONE_END), (_VITEST_ZONE_START, _VITEST_ZONE_END),
                               (_JEST_ZONE_START, _JEST_ZONE_END)):
                inside = False
                for j, t in enumerate(self.lines):
                    if inside and end.search(t) and not start.search(t):
                        inside = False
                    if not inside and start.search(t):
                        inside = True
                    if inside and not t.startswith("##["):
                        zone.add(j)
            zone.update(j for j, t in enumerate(self.lines) if _PYTEST_SUMMARY.match(t))
            self._zone = zone
        return i in self._zone

    def pytest_frame(self, nodeid: str) -> tuple[str, int | None, list[str]]:
        """(file, line, evidence) for a pytest node id, from the test's own frame in its section."""
        path, _, rest = nodeid.partition("::")
        want = clean_path(path)
        secs = self.sections()
        names = [rest.replace("::", "."), rest.split("::")[-1]] if rest else [path, want]
        span = next((secs[n] for n in names if n in secs), None)
        if span is None:
            return want, None, []
        start, end = span
        line: int | None = None
        loc_text = None
        for j in range(start + 1, end):
            t = self.lines[j]
            m = _PYTEST_LOC.match(t)
            if m and _same_file(m["file"], want):
                line, loc_text = int(m["line"]), t
                break
            fm = _PY_FRAME.search(t)
            if fm and _same_file(fm["file"], want):
                line, loc_text = int(fm["line"]), t.strip()
                break
        ev = [t for t in self.lines[start + 1:end] if t.startswith("E ")][:6]
        if loc_text:
            ev.append(loc_text)
        return want, line, ev


# ---------------------------------------------------------------------------------------------
# Rules

Locate = Callable[[_Ctx, int, "re.Match[str]"], "dict[str, Any] | None"]


@dataclass(frozen=True)
class Rule:
    """A line pattern and how to turn a match into a Failure.

    Named groups `file`, `line` (or `line2`), `test`, `msg` fill the Failure; every group can be
    used in the `summary` and `fix` templates, plus `{text}` (the matched line). `after` looks for
    the file/line on one of the next `window` lines (Rust ` --> `), `locate` is a function for
    anything that needs more context and returns field overrides, or None to drop the match.
    A `fallback` rule (a test-run summary line, "could not compile") only counts when nothing
    else in its block matched.
    """

    id: str
    category: Category
    pattern: re.Pattern[str]
    summary: str = "{text}"
    fix: str | None = None
    after: re.Pattern[str] | None = None
    window: int = 6
    require_after: bool = False
    locate: Locate | None = None
    fallback: bool = False
    in_reports: bool = True  # False: skip lines inside test-report output
    unless: re.Pattern[str] | None = None
    file: str | None = None
    confidence: float = 1.0


def _rx(p: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(p, flags)


_PATH_CS = r"(?P<file>(?:[A-Za-z]:[\\/])?[^:()\[\]\n\"']*?\.cs)"
_PATH_TS = r"(?P<file>(?:[A-Za-z]:[\\/])?[^:()\[\]\n\"'\s][^:()\[\]\n\"']*?\.(?:[cm]?tsx?|[cm]?jsx?|vue|svelte))"
_TS_WHERE = r"(?:\((?P<line>\d+),\d+\):|:(?P<line2>\d+):\d+ -)"
_RETRYING = _rx(r"(?i)\bwarn(?:ing)?\b|\bretry|\bretrying\b|attempt \d")

_FIX_TIMEOUT = ("Find the step that hangs (where its output stops) and fix it, or raise `timeout-minutes` "
                "if the job legitimately needs longer.")
_FIX_DISK = ("Free disk space before this step (remove unused toolchains or Docker images, clean build "
             "caches) or use a runner with more disk.")
_FIX_CS_NAME = ("Check that `{name}` is spelled right and declared, and add the missing `using` directive "
                "or assembly reference (in Unity, the asmdef reference) if it lives elsewhere.")
_FIX_CS_TYPE = ("Check the spelling of `{name}` and add the `using` directive or assembly/package reference "
                "(in Unity, the asmdef reference) that provides it.")
_FIX_TS2307 = "Install the package that provides `{mod}` (add it to package.json) or fix the import path."
_FIX_PY_MODULE = ("Add `{top}` to the project's dependencies (pyproject.toml or requirements) and run "
                  "`uv sync` or `pip install`.")
_FIX_NPM_LOCK = "Run `npm install` and commit the updated package-lock.json."


def _nearest(ctx: _Ctx, i: int, pattern: re.Pattern[str], back: int = 0, fwd: int = 0,
             stop: re.Pattern[str] | None = None) -> tuple[int, re.Match[str]] | None:
    """First match of `pattern` going back `back` lines, or forward `fwd` lines, from line i."""
    rng = range(i - 1, max(-1, i - 1 - back), -1) if back else range(i + 1, min(len(ctx.lines), i + 1 + fwd))
    for j in rng:
        t = ctx.lines[j]
        if stop is not None and stop.search(t):
            return None
        m = pattern.search(t)
        if m:
            return j, m
    return None


def _loc_pytest(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    nodeid = m["test"]
    if "::" not in nodeid:  # collection error: its own rule (missing module, syntax) owns it
        span = ctx.sections().get(clean_path(nodeid)) or ctx.sections().get(nodeid)
        if span and any(re.search(r"ModuleNotFoundError|SyntaxError|IndentationError|TabError", t)
                        for t in ctx.lines[span[0]:span[1]]):
            return None
    file, line, ev = ctx.pytest_frame(nodeid)
    return {"file": file, "line": line, "test": nodeid if "::" in nodeid else None,
            "evidence": [ctx.lines[i]] + ev}


def _loc_module(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    text = ctx.lines[i]
    sm = re.match(r"^(?:FAILED|ERROR) (\S+?\.py(?:::.+?)?)(?: - |$)", text)
    if sm:
        nodeid = sm[1]
        file, line, _ = ctx.pytest_frame(nodeid)
        return {"file": file, "line": line, "test": nodeid if "::" in nodeid else None}
    for j in range(i - 1, max(-1, i - 40), -1):
        t = ctx.lines[j]
        if _PYTEST_HEADER.match(t):
            name = _PYTEST_HEADER.match(t)["name"]  # type: ignore[index]
            if name.startswith("ERROR collecting "):
                return {"file": clean_path(name.removeprefix("ERROR collecting "))}
            break
        fm = _PYTEST_LOC.match(t) or _PY_FRAME.search(t)
        if fm and not _LIBRARY_PATH.search(fm["file"]):
            return {"file": fm["file"], "line": int(fm["line"])}
    return {}


def _loc_syntax(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    head = _nearest(ctx, i, re.compile(r"^_+ ERROR collecting (?P<f>\S+) _+$"), back=40)
    hit = _nearest(ctx, i, _PY_FRAME, back=8)
    if hit:
        file = hit[1]["file"]
        if head and _same_file(file, clean_path(head[1]["f"])):
            file = head[1]["f"]  # the collected path is repo-relative even when the frame isn't
        return {"file": file, "line": int(hit[1]["line"])}
    return {"file": head[1]["f"]} if head else {}


_VITEST_FAIL = re.compile(r"^\s*FAIL\s+(?P<file>\S+?\.(?:[cm]?[jt]sx?|vue|svelte))\s+>\s+(?P<test>.+?)\s*$")
_VITEST_LOC = re.compile(r"[❯>]\s+(?P<file>[^\s:()]+?):(?P<line>\d+):\d+")
_VITEST_END = re.compile(r"^\s*FAIL\s|⎯{3,}|^\s*Test Files\s|^##\[")


def _vitest_section(ctx: _Ctx, i: int) -> list[str]:
    end = next((j for j in range(i + 1, len(ctx.lines)) if _VITEST_END.search(ctx.lines[j])), len(ctx.lines))
    return ctx.lines[i + 1:end]


def _vitest_where(sec: list[str], file: str) -> tuple[int | None, list[str]]:
    ev: list[str] = []
    for t in sec:
        lm = _VITEST_LOC.search(t)
        if lm and _same_file(lm["file"], clean_path(file)):
            return int(lm["line"]), ev[:6] + [t.strip()]
        if t.strip():
            ev.append(t)
    return None, ev[:6]


def _loc_vitest(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    sec = _vitest_section(ctx, i)
    if any("Test timed out in" in t for t in sec):
        return None  # vitest.timeout owns this test
    line, ev = _vitest_where(sec, m["file"])
    return {"line": line, "evidence": [ctx.lines[i].strip()] + ev}


def _loc_vitest_timeout(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    hit = _nearest(ctx, i, _VITEST_FAIL, back=10)
    if not hit:
        return {}
    j, fm = hit
    line, ev = _vitest_where(_vitest_section(ctx, j), fm["file"])
    return {"file": fm["file"], "test": fm["test"], "line": line, "evidence": [ctx.lines[j].strip()] + ev}


_JEST_FILE = re.compile(r"^\s*FAIL\s+(?P<file>\S+?\.(?:[cm]?[jt]sx?|vue|svelte))(?:\s+\(.*\))?\s*$")
_JEST_TEST = re.compile(r"^\s*● (?P<test>.+?)\s*$")
_JEST_END = re.compile(r"^\s*● |^\s*(?:PASS|FAIL)\s|^Test Suites:|^##\[")
_JEST_AT = re.compile(r"^\s*at .*?\(?(?P<file>[^\s()]+?):(?P<line>\d+):\d+\)?\s*$")


def _jest_details(ctx: _Ctx, i: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    hit = _nearest(ctx, i, _JEST_FILE, back=len(ctx.lines))
    file = hit[1]["file"] if hit else None
    end = next((j for j in range(i + 1, len(ctx.lines)) if _JEST_END.search(ctx.lines[j])), len(ctx.lines))
    sec = ctx.lines[i + 1:end]
    out["_section"] = sec
    if file:
        out["file"] = file
        for t in sec:
            am = _JEST_AT.match(t)
            if am and _same_file(am["file"], clean_path(file)):
                out["line"] = int(am["line"])
                break
    out["evidence"] = [ctx.lines[i].strip()] + [t.strip() for t in sec if t.strip()][:6]
    return out


def _loc_jest(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    if m["test"].startswith("Console"):
        return None
    d = _jest_details(ctx, i)
    if any("Exceeded timeout of" in t for t in d.pop("_section")):
        return None  # jest.timeout owns this test
    if m["test"] == "Test suite failed to run":
        d["test"] = None
    return d


def _loc_jest_timeout(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    hit = _nearest(ctx, i, _JEST_TEST, back=30)
    if not hit:
        return {}
    d = _jest_details(ctx, hit[0])
    d.pop("_section")
    d["test"] = hit[1]["test"]
    return d


def _loc_cargo_panic(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    d: dict[str, Any] = {}
    if m["test"] == "main":
        d["test"] = None
    if not m["msg"] and i + 1 < len(ctx.lines) and ctx.lines[i + 1].strip():
        d["summary"] = ctx.lines[i + 1].strip()
    return d


_DOTNET_IN = re.compile(r" in (?P<file>.+?):line (?P<line>\d+)\s*$|\] in (?P<file2>.+?):(?P<line3>\d+)\s*$")


def _loc_stack_forward(stop: str) -> Locate:
    stop_re = re.compile(stop)

    def locate(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
        first: dict[str, Any] | None = None
        ev = [ctx.lines[i].strip()]
        for j in range(i + 1, min(len(ctx.lines), i + 40)):
            t = ctx.lines[j]
            if stop_re.search(t):
                break
            if t.strip() and len(ev) < 6:
                ev.append(t.strip())
            dm = _DOTNET_IN.search(t)
            if dm:
                f = clean_path(dm["file"] or dm["file2"])
                cand = {"file": f, "line": int(dm["line"] or dm["line3"])}
                if first is None:
                    first = cand
                if "PackageCache" not in f and "nunit" not in f.lower():
                    first = cand
                    break
        return {**(first or {}), "evidence": ev}

    return locate


def _loc_go(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    hit = _nearest(ctx, i, re.compile(r"^\s+(?P<file>\S+\.go):(?P<line>\d+):"), fwd=20,
                   stop=re.compile(r"^\s*--- (?:FAIL|PASS)|^(?:FAIL|ok)\s"))
    return {"file": hit[1]["file"], "line": int(hit[1]["line"])} if hit else {}


_PW_ITEM = re.compile(r"^\s*\[[^\]]+\] › (?P<file>[^:\s]+):(?P<line>\d+):\d+ › (?P<test>.+?)\s*$")


def _loc_pw_flaky(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    hit = _nearest(ctx, i, _PW_ITEM, fwd=1)
    if not hit:
        return {}
    return {"file": hit[1]["file"], "line": int(hit[1]["line"]), "test": hit[1]["test"]}


def _loc_retry_passed(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    hit = _nearest(ctx, i, re.compile(r"Attempt \d+ failed"), back=len(ctx.lines))
    return {"evidence": [ctx.lines[hit[0]].strip(), ctx.lines[i].strip()]} if hit else None


def _loc_next_line(ctx: _Ctx, i: int, m: re.Match[str]) -> dict[str, Any] | None:
    """Summary = this line plus the next informative one (uv's `Because ...`, Unity's package line)."""
    hit = _nearest(ctx, i, re.compile(r"\S"), fwd=4)
    if hit:
        return {"summary": f"{ctx.lines[i].strip()} {hit[1].string.strip()}"}
    return {}


RULES: list[Rule] = [
    # --- timeout
    Rule("gha.job_timeout", "timeout",
         _rx(r"has exceeded the maximum execution time of (?P<min>\d+) minutes"),
         summary="Job exceeded the maximum execution time of {min} minutes", fix=_FIX_TIMEOUT, in_reports=False),
    Rule("gha.step_timeout", "timeout", _rx(r"has timed out after (?P<min>\d+) minutes"),
         summary="Step timed out after {min} minutes", fix=_FIX_TIMEOUT, in_reports=False),
    Rule("pytest.timeout", "timeout",
         _rx(r"^(?:FAILED|ERROR) (?P<test>\S+?\.py::.+?) - Failed: Timeout >(?P<secs>[\d.]+)s"),
         summary="pytest-timeout: test ran longer than {secs}s", locate=_loc_pytest),
    Rule("pytest.timeout_banner", "timeout", _rx(r"^\+{5,} Timeout \+{5,}$"),
         summary="pytest-timeout fired", fallback=True),
    Rule("vitest.timeout", "timeout", _rx(r"^(?:Error: )?Test timed out in (?P<ms>\d+) ?ms"),
         summary="Test timed out in {ms}ms", locate=_loc_vitest_timeout),
    Rule("jest.timeout", "timeout", _rx(r"Exceeded timeout of (?P<ms>\d+) ?ms for a (?:test|hook)"),
         summary="Test exceeded the {ms}ms timeout", locate=_loc_jest_timeout),
    Rule("unity.test_timeout", "timeout", _rx(r"Test exceeded Timeout value of (?P<ms>\d+) ?ms"),
         summary="Unity test exceeded its {ms}ms timeout"),
    Rule("nextest.timeout", "timeout", _rx(r"^\s*TIMEOUT \[[^\]]*\] (?:\S+ )?(?P<test>\S+)\s*$"),
         summary="Test timed out (nextest)"),
    # --- infra
    Rule("gha.runner_shutdown", "infra", _rx(r"The runner has received a shutdown signal"),
         summary="The runner received a shutdown signal (runner stopped or the job was cancelled)",
         in_reports=False),
    Rule("gha.runner_lost", "infra", _rx(r"lost communication with the server"),
         summary="The runner lost communication with GitHub (crashed, starved for CPU/memory or lost network)",
         in_reports=False),
    Rule("infra.disk_full", "infra",
         _rx(r"No space left on device|\bENOSPC\b|not enough space on the disk|##\[error\].*running out of disk space"),
         summary="The runner ran out of disk space", fix=_FIX_DISK, in_reports=False),
    Rule("unity.license", "infra",
         _rx(r"no valid unity (?:editor )?licen[cs]e|licen[cs]e (?:is not active|not activated|activation failed|"
             r"has expired|is invalid)|\[Licensing::(?:Module|Client)\].*\b(?:error|fail)|no ulf licen[cs]e|"
             r"(?:failed to|could not|unable to) (?:activate|return|acquire) (?:the )?(?:unity )?licen[cs]e|"
             r"unity licen[cs]e.*\b(?:failed|invalid|expired|error)", re.IGNORECASE),
         summary="Unity licence problem: {text}", in_reports=False),
    Rule("net.rate_limit", "infra",
         _rx(r"API rate limit exceeded|secondary rate limit|\b429\b[ :-]*Too Many Requests|pull rate limit", re.IGNORECASE),
         summary="Rate limited: {text}", in_reports=False),
    Rule("nuget.unreachable", "infra", _rx(r"error NU1301\b"), summary="NuGet feed unreachable: {text}",
         in_reports=False),
    Rule("net.dns", "infra",
         _rx(r"Could not resolve host|getaddrinfo (?:ENOTFOUND|EAI_AGAIN)|Temporary failure in name resolution|"
             r"Name or service not known|nodename nor servname provided|No such host is known"),
         summary="DNS lookup failed: {text}", in_reports=False, unless=_RETRYING),
    Rule("net.http_5xx", "infra",
         _rx(r"\b50[0234] (?:Service Unavailable|Bad Gateway|Gateway Time-?out|Internal Server Error)\b|"
             r"(?:HTTP error|status code|returned error:|Response status code does not indicate success:) ?50[234]\b",
             re.IGNORECASE),
         summary="Server error from a remote service: {text}", in_reports=False, unless=_RETRYING),
    Rule("net.connection", "infra",
         _rx(r"\bECONNRESET\b|\bETIMEDOUT\b|Connection reset by peer|Connection timed out|\bsocket hang up\b|"
             r"TLS handshake timeout"),
         summary="Network connection failed: {text}", in_reports=False, unless=_RETRYING),
    # --- dependency
    Rule("uv.lock_outdated", "dependency", _rx(r"The lockfile at `?uv\.lock`? needs to be updated"),
         summary="uv.lock is out of date with pyproject.toml", file="uv.lock"),
    Rule("uv.resolution", "dependency",
         _rx(r"No solution found when resolving dependencies|requirements are unsatisfiable"),
         locate=_loc_next_line),
    Rule("uv.build_failed", "dependency", _rx(r"Failed to build `(?P<pkg>[^`]+)`"),
         summary="Failed to build dependency {pkg}"),
    Rule("pip.resolution", "dependency",
         _rx(r"ERROR: (?:Could not find a version that satisfies the requirement|No matching distribution found for|"
             r"ResolutionImpossible|Cannot install .+ because these package versions have conflicting dependencies)")),
    Rule("python.module_not_found", "dependency", _rx(r"ModuleNotFoundError: No module named '(?P<module>[\w.]+)'"),
         summary="ModuleNotFoundError: No module named '{module}'", fix=_FIX_PY_MODULE, locate=_loc_module),
    Rule("python.no_module", "dependency", _rx(r"^(?:\S*python\S*: )?No module named (?P<module>[\w.]+)\s*$"),
         summary="No module named {module}", fix=_FIX_PY_MODULE),
    Rule("npm.lockfile", "dependency",
         _rx(r"can only install packages when your package\.json and package-lock\.json (?:or npm-shrinkwrap\.json )?"
             r"are in sync|Missing: \S+ from lock file|Invalid: lock file's"),
         summary="package-lock.json is out of sync with package.json", fix=_FIX_NPM_LOCK, file="package-lock.json"),
    Rule("npm.eresolve", "dependency",
         _rx(r"npm (?:ERR!|error) (?:code )?ERESOLVE|ERESOLVE (?:unable to resolve dependency tree|could not resolve)"),
         summary="npm could not resolve the dependency tree (ERESOLVE)"),
    Rule("npm.e404", "dependency",
         _rx(r"npm (?:ERR!|error) (?:code E404|404 )"), summary="npm package not found (E404): {text}"),
    Rule("pnpm.lockfile", "dependency", _rx(r"ERR_PNPM_OUTDATED_LOCKFILE|ERR_PNPM_LOCKFILE_CONFIG_MISMATCH"),
         summary="pnpm-lock.yaml is out of date", file="pnpm-lock.yaml"),
    Rule("yarn.lockfile", "dependency",
         _rx(r"Your lockfile needs to be updated, but yarn was run with `--frozen-lockfile`|"
             r"The lockfile would have been modified by this install, which is explicitly forbidden"),
         summary="yarn.lock is out of date", file="yarn.lock"),
    Rule("node.module_not_found", "dependency",
         _rx(r"Cannot find (?:module|package) '(?P<mod>[^'./][^']*)'|Failed to resolve import \"(?P<mod2>[^\"./][^\"]*)\""
             r"(?: from \"(?P<file>[^\"]+)\")?"),
         summary="Package not found: {mod}{mod2}", unless=_rx(r"error TS\d+")),
    Rule("cargo.version_select", "dependency",
         _rx(r"failed to select a version for (?:the requirement )?`(?P<req>[^`]+)`|"
             r"no matching package named `(?P<pkg>[^`]+)` found"),
         file="Cargo.toml"),
    Rule("dotnet.nuget", "dependency", _rx(r"error NU1(?:10[1-3]|202|605)\b"), summary="NuGet restore failed: {text}"),
    Rule("unity.packages", "dependency",
         _rx(r"An error occurred while resolving packages|Project has invalid dependencies|"
             r"Package \[?[\w.-]+@[^\]\s]+\]? cannot be found|\[Package Manager\].*\b(?:error|failed)|"
             r"Cannot resolve package"),
         file="Packages/manifest.json", locate=_loc_next_line),
    # --- compile
    Rule("csharp.cs0103", "compile",
         _rx(_PATH_CS + r"\((?P<line>\d+),\d+\): error CS0103: (?P<msg>The name '(?P<name>[^']+)' does not exist"
             r" in the current context)"),
         summary="CS0103: {msg}", fix=_FIX_CS_NAME),
    Rule("csharp.cs0246", "compile",
         _rx(_PATH_CS + r"\((?P<line>\d+),\d+\): error CS0246: (?P<msg>The type or namespace name '(?P<name>[^']+)'"
             r" could not be found.*?)(?:\s+\[[^\]]*\.csproj\])?$"),
         summary="CS0246: {msg}", fix=_FIX_CS_TYPE),
    Rule("csharp.error", "compile",
         _rx(_PATH_CS + r"\((?P<line>\d+),\d+\): error (?P<code>CS\d{4}): (?P<msg>.*?)(?:\s+\[[^\]]*\.csproj\])?$"),
         summary="{code}: {msg}"),
    Rule("csharp.error_nofile", "compile", _rx(r"\berror (?P<code>CS\d{4}): (?P<msg>.*?)(?:\s+\[[^\]]*\.csproj\])?$"),
         summary="{code}: {msg}"),
    Rule("unity.compile_errors", "compile", _rx(r"Scripts have compiler errors"),
         summary="Unity: scripts have compiler errors", fallback=True),
    Rule("ts.ts2307", "compile",
         _rx(_PATH_TS + _TS_WHERE + r" error TS2307: (?P<msg>Cannot find module '(?P<mod>[^']+)'.*)"),
         summary="TS2307: {msg}", fix=_FIX_TS2307),
    Rule("ts.error", "compile", _rx(_PATH_TS + _TS_WHERE + r" error (?P<code>TS\d+): (?P<msg>.*)"),
         summary="{code}: {msg}"),
    Rule("esbuild.error", "compile", _rx(r"✘ \[ERROR\] (?P<msg>.+)"),
         after=_rx(r"^\s+(?P<file>\S+?):(?P<line>\d+):\d+:\s*$"), summary="{msg}"),
    Rule("rust.could_not_compile", "compile", _rx(r"^error: could not compile `(?P<crate>[^`]+)`"),
         summary="Rust: could not compile {crate}", fallback=True),
    Rule("rust.error_code", "compile", _rx(r"^error\[(?P<code>E\d{4})\]: (?P<msg>.+)$"),
         after=_rx(r"^\s*--> (?P<file>.+?):(?P<line>\d+):\d+\s*$"), summary="{code}: {msg}"),
    Rule("rust.error", "compile", _rx(r"^error: (?P<msg>.+)$"),
         after=_rx(r"^\s*--> (?P<file>.+?):(?P<line>\d+):\d+\s*$"), require_after=True, window=3, summary="{msg}"),
    Rule("python.syntax", "compile",
         _rx(r"^(?:E\s+)?(?P<exc>SyntaxError|IndentationError|TabError): (?P<msg>.+)$"),
         summary="{exc}: {msg}", locate=_loc_syntax),
    Rule("mypy.error", "compile",
         _rx(r"^(?P<file>[^\s:]+\.pyi?):(?P<line>\d+):(?:\d+:)? error: (?P<msg>.+?)(?:\s+\[[\w-]+\])?$"),
         summary="mypy: {msg}"),
    # --- flaky
    Rule("pytest.rerun", "flaky", _rx(r"^RERUN (?P<test>\S+?\.py::.+?)(?: - .*)?$"),
         summary="Failed, then rerun by pytest-rerunfailures", locate=_loc_pytest, confidence=0.9),
    Rule("pytest.rerun_verbose", "flaky", _rx(r"^(?P<test>\S+?\.py::\S+) RERUN\b"),
         summary="Failed, then rerun by pytest-rerunfailures", locate=_loc_pytest, confidence=0.9),
    Rule("nextest.flaky", "flaky", _rx(r"^\s*FLAKY \d+/\d+ \[[^\]]*\] (?:\S+ )?(?P<test>\S+)\s*$"),
         summary="Failed, then passed on retry (nextest)", confidence=0.9),
    Rule("playwright.flaky", "flaky", _rx(r"^\s*\d+ flaky\s*$"), summary="Failed, then passed on retry (Playwright)",
         locate=_loc_pw_flaky, confidence=0.9),
    Rule("retry.passed", "flaky", _rx(r"completed after (?P<n>[2-9]|\d{2,}) attempt"),
         summary="Command failed, then passed on attempt {n}", locate=_loc_retry_passed, confidence=0.8),
    # --- test
    Rule("pytest.failed", "test", _rx(r"^FAILED (?P<test>\S+?\.py::.+?)(?: - (?P<msg>.*))?$"),
         summary="{msg}", locate=_loc_pytest),
    Rule("pytest.error", "test", _rx(r"^ERROR (?P<test>\S+?\.py(?:::.+?)?)(?: - (?P<msg>.*))?$"),
         summary="pytest error: {msg}", locate=_loc_pytest),
    Rule("vitest.failed", "test", _VITEST_FAIL, summary="Test failed: {test}", locate=_loc_vitest),
    Rule("vitest.suite_failed", "test",
         _rx(r"^\s*FAIL\s+(?P<file>\S+?\.(?:[cm]?[jt]sx?|vue|svelte))\s+\[ \S+ \]\s*$"),
         summary="Test file failed to load"),
    Rule("jest.failed", "test", _JEST_TEST, summary="Test failed: {test}", locate=_loc_jest),
    Rule("cargo.test_panic", "test",
         _rx(r"^thread '(?P<test>[^']+)'(?: \(\d+\))? panicked at (?:'(?P<msg>.*)', )?(?P<file>[^\s:]+\.rs):"
             r"(?P<line>\d+):\d+:?$"),
         summary="{msg}", locate=_loc_cargo_panic),
    Rule("cargo.test_failed", "test", _rx(r"^test (?P<test>\S+) \.\.\. FAILED$"), summary="Rust test failed"),
    Rule("nextest.fail", "test", _rx(r"^\s*FAIL \[[^\]]*\] (?:\S+ )?(?P<test>\S+)\s*$"), summary="Rust test failed"),
    Rule("dotnet.failed", "test",
         _rx(r"^\s*Failed (?P<test>[^\s\[]+(?:\(.*?\))?) \[(?:< ?)?\d+(?:\.\d+)? ?(?:ms|s|m)\]\s*$"),
         summary="Test failed: {test}", locate=_loc_stack_forward(r"^\s*(?:Failed|Passed|Skipped) \S")),
    Rule("nunit.console_failed", "test", _rx(r"^\s*(?:\d+\) )?(?:Failed|Error) : (?P<test>[\w.+]+(?:\([^)]*\))?)"),
         summary="Test failed: {test}", locate=_loc_stack_forward(r"^\s*(?:\d+\) |(?:Failed|Error|Running) )")),
    Rule("go.test_failed", "test", _rx(r"^\s*--- FAIL: (?P<test>\S+) \("), summary="Go test failed", locate=_loc_go),
    Rule("playwright.failed", "test",
         _rx(r"^\s*\d+\) \[[^\]]+\] › (?P<file>[^:\s]+):(?P<line>\d+):\d+ › (?P<test>.+?)(?:\s+─+)?\s*$"),
         summary="Test failed: {test}"),
    # --- test-run summaries, used only when the details above are missing
    Rule("pytest.summary", "test",
         _rx(r"^(?:=+ )?(?:\d+ \w+, )*\d+ (?:failed|errors?)(?:, \d+ \w+)* in [\d.]+s"), fallback=True),
    Rule("vitest.summary", "test", _rx(r"^\s*Tests\s+\d+ failed"), fallback=True),
    Rule("jest.summary", "test", _rx(r"^Tests:\s+\d+ failed"), fallback=True),
    Rule("dotnet.summary", "test", _rx(r"^\s*Failed!\s+-\s+Failed:\s+\d+"), fallback=True),
    Rule("cargo.summary", "test", _rx(r"^test result: FAILED\."), fallback=True),
]

_FAILING = re.compile(
    r"##\[error\]|Process completed with exit code [1-9]|^(?:Error|error|ERROR|FATAL|fatal):|"
    r"exit(?:ed)? (?:with )?(?:code|status) [1-9]|returned non-zero exit status [1-9]|"
    r"Command failed with exit code [1-9]|make(?:\[\d+\])?: \*\*\* .*Error \d+|Build FAILED|BUILD FAILED|"
    r"Traceback \(most recent call last\):|\bnpm (?:ERR!|error)\b|Unhandled exception|\bFAILED\b"
)
_ERRORISH = re.compile(r"(?i)\berror\b|\bfailed\b|\bexception\b|\bfatal\b")
_EXIT_LINE = re.compile(r"Process completed with exit code")


class _Fmt(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _safe(v: Any) -> str:
    return re.sub(r"[`<>\n\r]", "", str(v))


def _build(rule: Rule, ctx: _Ctx, i: int, m: re.Match[str], job: str | None, step: str | None) -> Failure | None:
    text = ctx.lines[i]
    g: dict[str, Any] = {k: v for k, v in m.groupdict().items() if v is not None}
    file = g.get("file")
    line = g.get("line") or g.get("line2")
    after_line: str | None = None
    if rule.after is not None:
        hit = _nearest(ctx, i, rule.after, fwd=rule.window)
        if hit:
            file, line, after_line = hit[1]["file"], hit[1]["line"], ctx.lines[hit[0]].strip()
        elif rule.require_after:
            return None
    extra: dict[str, Any] = {}
    if rule.locate is not None:
        got = rule.locate(ctx, i, m)
        if got is None:
            return None
        extra = got
    file = extra.get("file", file)
    line = extra.get("line", line)
    test = extra.get("test", g.get("test"))
    if "module" in g:
        g["top"] = g["module"].split(".")[0]
    vals = _Fmt({k: str(v) for k, v in g.items()}, text=text.strip())
    safe = _Fmt({k: _safe(v) for k, v in vals.items()})
    summary = extra.get("summary") or rule.summary.format_map(vals).strip(" :") or text.strip()
    if not summary.strip(" :"):
        summary = text.strip()
    evidence = extra.get("evidence")
    if evidence is None:
        evidence = [text.strip()] + ([after_line] if after_line else [])
    return Failure(
        category=extra.get("category", rule.category), summary=summary,
        file=clean_path(file) if file else rule.file, line=int(line) if line else None, test=test,
        evidence=[e for e in evidence if e.strip()], rule=rule.id, source="rule", confidence=rule.confidence,
        fix=rule.fix.format_map(safe) if rule.fix else None, job=job, step=step,
    )


def _match_block(block: _Block) -> list[tuple[int, Failure]]:
    """Rule failures of one block, as (global line index, failure)."""
    ctx = _Ctx(block.lines)
    hits: list[tuple[int, Failure, bool]] = []
    for i, full in enumerate(block.lines):
        if not full.strip():
            continue
        text = full[:_MATCH_CHARS]
        for rule in RULES:
            m = rule.pattern.search(text)
            if not m:
                continue
            if (not rule.in_reports and ctx.in_report(i)) or (rule.unless is not None and rule.unless.search(text)):
                continue
            f = _build(rule, ctx, i, m, block.job, block.step)
            if f is not None:
                hits.append((block.start + i, f, rule.fallback))
            break  # the first matching rule owns the line, even when it declines it
    if any(not fb for _, _, fb in hits):  # fallbacks only speak when nothing specific matched
        hits = [h for h in hits if not h[2]]
    return [(pos, f) for pos, f, _ in hits]


def _looks_failing(lines: list[str]) -> bool:
    return any(_FAILING.search(t) for t in lines)


def _unknown(block: _Block) -> Failure:
    nonempty = [t.strip() for t in block.lines if t.strip()]
    told = [t for t in nonempty if not _EXIT_LINE.search(t)]
    errs = [t for t in told if _ERRORISH.search(t)]
    summary = (errs[-1] if errs else told[-1] if told else nonempty[-1] if nonempty else "Step failed")
    summary = summary.removeprefix("##[error]")
    return Failure(category="unknown", summary=summary, evidence=nonempty[-MAX_EVIDENCE_LINES:], rule=None,
                   source="none", confidence=0.0, job=block.job, step=block.step)


# ---------------------------------------------------------------------------------------------
# Cross-block passes: flaky detection, dedup, ordering


_PYTEST_PASSED = re.compile(r"^(?:(?:\[gw\d+\] )?(?P<a>\S+?\.py::.+?)\s+PASSED\b|(?:\[gw\d+\] \[\s*\d+%\] )?PASSED (?P<b>\S+?\.py::.+?)\s*$)")


_RUN_PASSED = re.compile(r"^\s*(?:Running|Passed)(?::[ \t]*|[ \t]+(?::[ \t]*)?)(?P<t>[\w.+]+(?:\([^)]*\))?)(?:\s*\.\.\.\s*Passed|\s*$)")
_TEST_RULES_FLAKYABLE = ("nunit.console_failed", "dotnet.failed", "pytest.failed", "pytest.error")


def _mark_flaky(hits: list[tuple[int, Failure]], lines: list[LogLine]) -> list[tuple[int, Failure]]:
    """A test that failed and later passed in the same log is flaky; a rerun that never passed is not."""
    failed_tests = {f.test for _, f in hits if f.category == "test" and f.test}
    last_pass: dict[str, int] = {}
    for j, ln in enumerate(lines):
        text = ln.text[:_MATCH_CHARS]
        pm = _PYTEST_PASSED.match(text)
        if pm:
            last_pass[pm["a"] or pm["b"]] = j
        rm = _RUN_PASSED.match(text)
        if rm and (text.rstrip().endswith("Passed") or text.lstrip().startswith("Passed")):
            last_pass[rm["t"]] = j
    out: list[tuple[int, Failure]] = []
    for pos, f in hits:
        if f.rule in ("pytest.rerun", "pytest.rerun_verbose") and f.test in failed_tests:
            continue  # rerun and still failed: a real failure, reported by pytest.failed
        if f.category == "test" and f.test and f.rule in _TEST_RULES_FLAKYABLE:
            if last_pass.get(f.test, -1) > pos:
                f = f.model_copy(update={"category": "flaky", "rule": "pytest.passed_on_rerun" if f.rule.startswith("pytest.") else "test.passed_on_rerun",
                                         "summary": f"Failed, then passed on rerun: {f.summary}"[:MAX_SUMMARY],
                                         "confidence": 0.8})
        if f.category == "test" and f.rule == "playwright.failed":
            if any(ff.rule == "playwright.flaky" and ff.test == f.test for _, ff in hits):
                continue
        out.append((pos, f))
    return out


def _key(f: Failure) -> tuple[Any, ...]:
    return f.category, f.file, f.line, f.test


def _specificity(f: Failure) -> int:
    return sum(v is not None for v in (f.file, f.line, f.test))


def _subsumed(a: Failure, b: Failure) -> bool:
    """a says nothing b doesn't: same category, b more specific, a's known fields agree with b."""
    if a.category != b.category or _specificity(a) >= _specificity(b):
        return False
    if any(va is not None and va != vb for va, vb in ((a.file, b.file), (a.line, b.line), (a.test, b.test))):
        return False
    return a.test is not None or a.summary == b.summary


def _dedupe(fs: list[Failure]) -> list[Failure]:
    seen: set[tuple[Any, ...]] = set()
    out: list[Failure] = []
    for f in fs:
        if f.category != "unknown":
            if _key(f) in seen:
                continue
            seen.add(_key(f))
        out.append(f)
    # a is only subsumed by a b of the same category that agrees on test (when a has one) or summary,
    # so index the candidates instead of comparing every pair.
    by_test: dict[tuple[Any, ...], list[Failure]] = {}
    by_summary: dict[tuple[Any, ...], list[Failure]] = {}
    for b in out:
        if b.test is not None:
            by_test.setdefault((b.category, b.test), []).append(b)
        by_summary.setdefault((b.category, b.summary), []).append(b)

    def covered(a: Failure) -> bool:
        cands = by_test.get((a.category, a.test), []) if a.test is not None else by_summary.get((a.category, a.summary), [])
        return any(b is not a and _subsumed(a, b) for b in cands)

    return [a for a in out if a.category == "unknown" or not covered(a)]


def _rank(f: Failure) -> tuple[int, int]:
    return PRECEDENCE.index(f.category), f._order


def _sorted(fs: list[Failure]) -> list[Failure]:
    return sorted(fs, key=_rank)


def _with_order(f: Failure, order: int) -> Failure:
    f._order = order
    return f


# ---------------------------------------------------------------------------------------------
# Public entry points


def classify(text: str, source: str = "log") -> TriageReport:
    """Rules-only triage of one log."""
    lines = normalize(text)
    hits: list[tuple[int, Failure]] = []
    unknown_lines: list[list[str]] = []
    blocks = by_rules = 0
    for block in _split_blocks(lines):
        found = _match_block(block)
        if found:
            blocks += 1
            by_rules += 1
            hits.extend(found)
        elif _looks_failing(block.lines):
            blocks += 1
            hits.append((block.start + len(block.lines), _unknown(block)))
            unknown_lines.append(block.lines[-UNKNOWN_KEEP_LINES:])
    hits = _mark_flaky(hits, lines)
    failures = _dedupe([_with_order(f, pos) for pos, f in hits])
    return TriageReport(source=source, failures=_sorted(failures), blocks=blocks, by_rules=by_rules,
                        unclassified=len(unknown_lines), block_lines=unknown_lines)


_STACK_FRAME = re.compile(r"\bin (?P<file>.+?):(?:line )?(?P<line>\d+)\s*$")
_TIMEOUT_MSG = re.compile(r"(?i)\bexceeded\s+timeout\b|\btimed[ -]out\s+after\b|\bTimeoutException\b|\btest timed out\b")


def _frame_of(stack: str) -> tuple[str | None, int | None, list[str]]:
    first: tuple[str | None, int | None, list[str]] = (None, None, [])
    for t in stack.splitlines():
        t = t[:_MATCH_CHARS]
        m = _STACK_FRAME.search(t) or _PYTEST_LOC.match(t.strip())
        if not m:
            continue
        f = clean_path(m["file"])
        cand = (f, int(m["line"]), [t.strip()])
        if "PackageCache" not in f and "nunit" not in f.lower():
            return cand
        if first[0] is None:
            first = cand
    return first


def parse_nunit_xml(data: bytes | str, source: str) -> TriageReport:
    """Failed test cases of an NUnit 3 (Unity Test Framework), NUnit 2 or JUnit XML file."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > NUNIT_MAX_BYTES:
        raise ValueError(f"{source}: test result file is larger than {NUNIT_MAX_BYTES // (1024 * 1024)} MB")
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", raw, re.IGNORECASE):
        raise ValueError(f"{source}: DOCTYPE/ENTITY declarations are not allowed in test result XML")
    def _no_dtd(*_a: Any) -> None:
        raise ValueError(f"{source}: DOCTYPE/ENTITY declarations are not allowed in test result XML")

    # The byte search above misses other encodings (UTF-16), so also watch the real parser: a first
    # expat pass that only looks for declarations (the C ElementTree parser does not expose its expat).
    scan = expat.ParserCreate()
    scan.StartDoctypeDeclHandler = _no_dtd
    scan.EntityDeclHandler = _no_dtd
    try:
        scan.Parse(raw, True)
    except expat.ExpatError:
        pass  # malformed XML is reported by the real parse below
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError(f"{source}: not valid XML ({e})") from e
    failures: list[Failure] = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "test-case":
            if el.get("result") not in ("Failed", "Failure", "Error"):
                continue
            node = el.find("failure")
            msg = (node.findtext("message") if node is not None else None) or ""
            stack = (node.findtext("stack-trace") if node is not None else None) or ""
            test = el.get("fullname") or el.get("name")
            label = el.get("label") or ""
            file, line, frame = _frame_of(stack)
            rule = "nunit"
        elif tag == "testcase":
            node = el.find("failure")
            if node is None:
                node = el.find("error")
            if node is None:
                continue
            stack = node.text or ""
            msg = node.get("message") or stack.strip().split("\n", 1)[0]
            cls, name = el.get("classname") or "", el.get("name") or ""
            test = f"{cls}.{name}" if cls and name else name or cls or None
            label = ""
            file, line, frame = _frame_of(stack)
            if el.get("file"):
                file = clean_path(el.get("file") or "")
                line = int(el.get("line") or 0) or line
            rule = "junit"
        else:
            continue
        msg = msg.strip()
        timeout = label == "Timeout" or bool(_TIMEOUT_MSG.search(msg)) or (
            tag == "testcase" and (node.get("type") or "").rsplit(".", 1)[-1] in ("TimeoutException", "TestTimedOutException"))
        first = msg.split("\n", 1)[0].strip() if msg else ""
        ev = [t.rstrip() for t in msg.splitlines() if t.strip()][:5] + frame
        f = Failure(category="timeout" if timeout else "test", summary=first or "Test failed", file=file, line=line,
                    test=test, evidence=ev, rule=f"{rule}.timeout" if timeout else f"{rule}.failed")
        failures.append(_with_order(f, len(failures)))
    n = len(failures)
    return TriageReport(source=source, failures=_sorted(_dedupe(failures)), blocks=n, by_rules=n)


def load(path: Path) -> TriageReport:
    """Triage a file (.xml as NUnit/JUnit, anything else as a log) or every log/xml in a folder."""
    path = Path(path)
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in (".log", ".txt", ".xml"))
        return merge([load(p) for p in files], source=str(path))
    if path.suffix.lower() == ".xml":
        return parse_nunit_xml(path.read_bytes(), str(path))
    return classify(path.read_text(encoding="utf-8", errors="replace"), str(path))


def merge(reports: list[TriageReport], source: str | None = None) -> TriageReport:
    """One report from several (a log plus its test-result XML, several jobs)."""
    failures: list[Failure] = []
    unknown_lines: list[list[str]] = []
    for k, r in enumerate(reports):
        for f in r.failures:
            failures.append(_with_order(f.model_copy(), k * 10**9 + f._order))
        unknown_lines.extend(r.block_lines)
    return TriageReport(
        source=source if source is not None else ", ".join(r.source for r in reports),
        failures=_sorted(_dedupe(failures)), blocks=sum(r.blocks for r in reports),
        by_rules=sum(r.by_rules for r in reports), by_llm=sum(r.by_llm for r in reports),
        unclassified=sum(r.unclassified for r in reports), block_lines=unknown_lines,
    )


async def triage(report: TriageReport, llm: LlmClassify | None = None, *, max_llm_blocks: int = 5) -> TriageReport:
    """Ask `llm` about the unknown blocks (at most `max_llm_blocks` calls); returns a new report."""
    failures = [_with_order(f.model_copy(), f._order) for f in report.failures]
    if llm is None:
        return report.model_copy(update={"failures": failures, "block_lines": [list(b) for b in report.block_lines]})
    left: list[list[str]] = []
    calls = filled = 0
    k = 0
    for idx, old in enumerate(failures):
        if old.source != "none":
            continue
        lines = report.block_lines[k] if k < len(report.block_lines) else list(old.evidence)
        k += 1
        got: Failure | None = None
        if calls < max_llm_blocks:
            calls += 1
            try:
                res = await llm(list(lines))
                if res is not None:
                    d = res.model_dump() if isinstance(res, BaseModel) else dict(res)
                    d.update(source="llm", rule=None, job=d.get("job") or old.job, step=d.get("step") or old.step)
                    if not d.get("evidence"):
                        d["evidence"] = old.evidence
                    got = Failure.model_validate(d)
            except PermissionError:
                raise  # e.g. EffortApprovalRequired: the user must decide, never swallow it
            except Exception as e:  # noqa: BLE001 — a failing classifier leaves the block unknown
                log.info("llm triage failed: %s", e)
                got = None
        if got is not None and got.category != "unknown":
            failures[idx] = _with_order(got, old._order)
            filled += 1
        else:
            left.append(list(lines))
    return TriageReport(source=report.source, failures=_sorted(failures), blocks=report.blocks,
                        by_rules=report.by_rules, by_llm=report.by_llm + filled,
                        unclassified=max(0, report.unclassified - filled), block_lines=left)


# ---------------------------------------------------------------------------------------------
# Markdown


# Characters entity-encoded inside a code span so the text can't become markdown (links, images,
# headings, emphasis), an autolink, a mention or a cross-reference, nor break out of a table cell.
_CODE_ESCAPES = {ord(c): f"&#{ord(c)};" for c in "&<>|`[]()!*_\\~#@:."}


def _code(s: str | None, limit: int = 160) -> str:
    """Untrusted text as an inline `<code>` span: one line, truncated, and inert in a GitHub comment."""
    if not s:
        return "—"
    s = " ".join(str(s).split())
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return "<code>" + s.translate(_CODE_ESCAPES) + "</code>"


def _fence(lines: list[str]) -> str:
    longest = max((len(r) for t in lines for r in re.findall(r"`+", t)), default=0)
    return "`" * max(3, longest + 1)


def _where(f: Failure) -> str | None:
    if not f.file:
        return None
    return f"{f.file}:{f.line}" if f.line else f.file


def _render(report: TriageReport, ev_cap: int, shown: int) -> str:
    n = len(report.failures)
    out = [f"### CI triage: {n} failure(s)", ""]
    fs = report.failures[:shown]
    if fs:
        out += ["| # | Category | Location | Test | Summary |", "|---|---|---|---|---|"]
        for k, f in enumerate(fs, 1):
            out.append(f"| {k} | {f.category} | {_code(_where(f))} | {_code(f.test)} | {_code(f.summary)} |")
        if shown < n:
            out.append(f"\n…and {n - shown} more failure(s) not shown.")
        out.append("")
        for k, f in enumerate(fs, 1):
            meta = [f"Rule: {_code(f.rule)}" if f.source == "rule" else
                    "Classified by: LLM" if f.source == "llm" else "Classified by: nothing (no rule matched)"]
            if f.job:
                meta.append(f"Job: {_code(f.job)}" + (f" / {_code(f.step)}" if f.step else ""))
            out += ["<details>", f"<summary>{k}. {f.category}: {_code(f.summary, MAX_SUMMARY)}</summary>", "",
                    " · ".join(meta), ""]
            ev = f.evidence[:ev_cap]
            if ev:
                fence = _fence(ev)
                out += [fence + "text", *ev, fence, ""]
            if f.fix:
                out += [f"**Suggested fix:** {_code(f.fix, MAX_FIX)}", ""]
            out += ["</details>", ""]
    else:
        out += ["No failures found.", ""]
    foot = f"Classified by rules: {report.by_rules}/{report.blocks} blocks"
    if report.by_llm:
        foot += f", by LLM: {report.by_llm}"
    if report.unclassified:
        foot += f", unclassified: {report.unclassified}"
    out.append(foot)
    return "\n".join(out) + "\n"


def render_markdown(report: TriageReport) -> str:
    """A PR-comment-sized summary (< 60 KB): evidence is cut first, then the list itself."""
    n = len(report.failures)
    for cap in (MAX_EVIDENCE_LINES, 4, 2, 1, 0):
        md = _render(report, cap, n)
        if len(md.encode("utf-8")) < MARKDOWN_MAX_BYTES:
            return md
    shown = n
    while shown > 1:
        shown //= 2
        md = _render(report, 0, shown)
        if len(md.encode("utf-8")) < MARKDOWN_MAX_BYTES:
            return md
    return md.encode("utf-8")[: MARKDOWN_MAX_BYTES - 100].decode("utf-8", "ignore") + "\n\n…(truncated)\n"


# ---------------------------------------------------------------------------------------------
# GitHub


def fetch_run_log(run_id: str, repo: str | None = None) -> str:
    """`gh run view <id> --log-failed`: the failed steps of a workflow run."""
    run_id = str(run_id)
    if not re.fullmatch(r"\d+", run_id):
        raise ValueError(f"run id must be digits: {run_id!r}")
    if repo is not None and not re.fullmatch(r"[\w.][\w.-]*/[\w.][\w.-]*", repo):
        raise ValueError(f"repo must look like owner/name: {repo!r}")
    cmd = ["gh", "run", "view", run_id, "--log-failed"] + (["-R", repo] if repo else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                           check=False)
    except FileNotFoundError as e:
        raise RuntimeError("the GitHub CLI (gh) is not installed or not on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"gh run view {run_id} timed out after 120 s") from e
    if r.returncode != 0:
        raise RuntimeError(f"gh run view {run_id} failed: {(r.stderr or r.stdout or '').strip()[:500]}")
    return r.stdout
