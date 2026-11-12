"""File tools (scoped to the session folder and its worktrees) and run_command."""
from __future__ import annotations

import asyncio
import mimetypes
import os
import re
import time
from pathlib import Path

from .tools import ToolContext, ToolOutput, ToolRegistry, obj

MAX_READ = 200_000
MAX_CMD_OUT = 30_000
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build", ".next", "target"}
SNIFF_BYTES = 8192  # a NUL byte in the first 8 KB means binary
MAX_LINE = 2000  # read_file: longest line shown
COUNT_CAP = 20 * 1024 * 1024  # read_file: only count remaining lines for files up to this size
SEARCH_MAX_FILE = 2 * 1024 * 1024
SEARCH_BUDGET_S = 10.0
SEARCH_LINE_CHARS = 4000  # truncate before matching so one minified line can't stall the matcher
MAX_PATTERN = 500
_ESCAPES_AND_CLASSES = re.compile(r"\\.|\[(?:\\.|[^\]])*\]")


def _risky_regex(pattern: str) -> bool:
    """A repeated group whose body itself repeats or alternates — (a+)+, ((a+))+, (a|aa)*, (.*a){10}:
    the shapes that backtrack catastrophically (Python's re has no timeout)."""
    flat = _ESCAPES_AND_CLASSES.sub("x", pattern)  # escapes and [..] classes can't nest or alternate
    stack: list[int] = []
    for i, c in enumerate(flat):
        if c == "(":
            stack.append(i)
        elif c == ")" and stack:
            start = stack.pop()
            if flat[i + 1:i + 2] in ("+", "*", "{") and any(q in flat[start + 1:i] for q in "+*{|"):
                return True
    return False


def _is_binary(p: Path) -> bool:
    with open(p, "rb") as f:
        return b"\0" in f.read(SNIFF_BYTES)


def _read_slice(p: Path, shown: str, off: int, lim: int) -> tuple[str, bool]:
    """Stream lines [off, off+lim) of a text file without loading it. Returns (text, is_error)."""
    try:
        size = p.stat().st_size
        if _is_binary(p):
            mime = mimetypes.guess_type(p.name)[0] or "unknown type"
            msg = (f"{shown} looks like a binary file ({size} bytes, {mime}); read_file only reads text. "
                   "Use get_item for indexed media/PDFs, or run_command (e.g. `file`, `xxd | head`) to inspect it.")
            return msg, True
        out: list[str] = []
        used = 0
        last = off - 1  # last line number seen
        stopped = False  # stopped early (limit or char budget) with lines possibly remaining
        with open(p, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                if n < off:
                    continue
                if stopped:
                    last = n - 1
                    break
                line = line.rstrip("\r\n")
                if len(line) > MAX_LINE:
                    line = line[:MAX_LINE] + "…[line truncated]"
                out.append(f"{n}\t{line}")
                used += len(line) + 8
                last = n
                if n - off + 1 >= lim or used > MAX_READ:
                    stopped = True
            else:
                stopped = False
        if not stopped:
            return "\n".join(out), False
        # Stopped with at least one more line present (the loop broke on it), so there is more.
        if size <= COUNT_CAP:
            with open(p, encoding="utf-8", errors="replace") as f:
                total = sum(1 for _ in f)
            return "\n".join(out) + f"\n… {total - last} more lines", False
        return "\n".join(out) + f"\n… more lines after line {last} (file is {size / 1_048_576:.1f} MB)", False
    except OSError as e:
        return f"Could not read {shown}: {e}", True


def _safe_regex(pattern: str) -> tuple[re.Pattern, str]:
    """Compile a model-supplied regex; fall back to a literal search when it is invalid or risks catastrophic backtracking."""
    why = None
    if len(pattern) > MAX_PATTERN:
        why = f"pattern longer than {MAX_PATTERN} chars"
    elif _risky_regex(pattern):
        why = "nested quantifiers could backtrack catastrophically"
    else:
        try:
            return re.compile(pattern), ""
        except re.error as e:
            why = str(e)
            return re.compile(re.escape(pattern)), f"Invalid regex ({why}); searched for the literal text instead."
    return re.compile(re.escape(pattern)), f"Unsafe regex ({why}); searched for the literal text instead."


def _search_tree(ctx: ToolContext, root: Path, rx: re.Pattern, glob: str) -> str:
    deadline = time.monotonic() + SEARCH_BUDGET_S
    hits: list[str] = []
    timed_out = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS and not x.startswith(".")]
        for f in filenames:
            if time.monotonic() > deadline:  # re has no timeout; check between files and lines
                timed_out = True
                break
            fp = Path(dirpath) / f
            if not fp.match(glob) or not ctx.within_roots(fp):  # symlinks out of the folder are skipped
                continue
            try:
                if fp.stat().st_size > SEARCH_MAX_FILE or _is_binary(fp):
                    continue
                with open(fp, encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if rx.search(line[:SEARCH_LINE_CHARS]):
                            hits.append(f"{fp.relative_to(root)}:{i}: {line.strip()[:200]}")
                            if len(hits) >= 300:
                                return "\n".join(hits) + "\n… truncated"
                        if i % 256 == 0 and time.monotonic() > deadline:
                            timed_out = True
                            break
            except OSError:
                continue
            if timed_out:
                break
        if timed_out:
            break
    text = "\n".join(hits) or "No matches."
    return text + (f"\n…stopped after {SEARCH_BUDGET_S:g} s; narrow path or glob" if timed_out else "")


def register_builtin(reg: ToolRegistry) -> None:
    @reg.add("read_file", "Read a text file in the session folder. Use offset (1-based line) and limit (max 5000) for big files; "
             "binary files are refused and long lines are cut.",
             obj({"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}},
                 ["path"]), read_only=True)
    async def read_file(ctx: ToolContext, a: dict) -> ToolOutput:
        p = ctx.resolve_path(a["path"])
        if not p.is_file():
            return ToolOutput(f"Not a file: {a['path']}", is_error=True)
        if not ctx.app.policy.allows_path(p, ctx.provider):
            return ToolOutput("That file is marked sensitive and the data policy doesn't allow sending it to "
                              f"{ctx.provider}.", is_error=True)
        off = max(int(a.get("offset") or 1), 1)
        lim = min(max(int(a.get("limit") or 2000), 1), 5000)
        text, is_err = await asyncio.to_thread(_read_slice, p, a["path"], off, lim)  # big files must not block the loop
        return ToolOutput(text, is_error=is_err)

    @reg.add("list_dir", "List files in a folder of the session (recursive up to depth 3).",
             obj({"path": {"type": "string"}, "depth": {"type": "integer"}}), read_only=True)
    async def list_dir(ctx: ToolContext, a: dict) -> ToolOutput:
        root = ctx.resolve_path(a.get("path") or ".")
        depth = min(int(a.get("depth") or 2), 3)
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            d = Path(dirpath)
            level = len(d.relative_to(root).parts)
            dirnames[:] = sorted(x for x in dirnames if x not in SKIP_DIRS and not x.startswith("."))
            if level >= depth:
                dirnames[:] = []
            for f in sorted(filenames):
                out.append(str((d / f).relative_to(root)))
            if len(out) > 1000:
                out.append("… truncated")
                break
        return ToolOutput("\n".join(out) or "(empty)")

    @reg.add("search", "Search file contents in the session folder with a regex. Returns path:line: text.",
             obj({"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}},
                 ["pattern"]), read_only=True)
    async def search(ctx: ToolContext, a: dict) -> ToolOutput:
        root = ctx.resolve_path(a.get("path") or ".")
        rx, note = _safe_regex(a["pattern"])
        # The walk reads many files; run it off the event loop (resolve_path/within_roots are pure path ops).
        out = await asyncio.to_thread(_search_tree, ctx, root, rx, a.get("glob") or "*")
        return ToolOutput((note + "\n" if note else "") + out)

    @reg.add("write_file", "Create or overwrite a file in the session folder.",
             obj({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]))
    async def write_file(ctx: ToolContext, a: dict) -> ToolOutput:
        p = ctx.resolve_path(a["path"], write=True)
        await ctx.approve("edit", str(p), {"action": "write", "path": str(p), "bytes": len(a["content"])})
        ctx.app.changes.snapshot(ctx.session_id, p)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(a["content"])
        ctx.app.changes.notify(ctx.session_id, p, ctx.provider, ctx.model)
        return ToolOutput(f"Wrote {len(a['content'])} chars to {a['path']}")

    @reg.add("edit_file", "Replace an exact, unique string in a file.",
             obj({"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
                  "replace_all": {"type": "boolean"}}, ["path", "old", "new"]))
    async def edit_file(ctx: ToolContext, a: dict) -> ToolOutput:
        p = ctx.resolve_path(a["path"], write=True)
        text = p.read_text()
        n = text.count(a["old"])
        if n == 0:
            return ToolOutput("old string not found", is_error=True)
        if n > 1 and not a.get("replace_all"):
            return ToolOutput(f"old string occurs {n} times; make it unique or set replace_all", is_error=True)
        await ctx.approve("edit", str(p), {"action": "edit", "path": str(p), "old": a["old"][:500],
                                           "new": a["new"][:500]})
        ctx.app.changes.snapshot(ctx.session_id, p)
        p.write_text(text.replace(a["old"], a["new"]) if a.get("replace_all") else text.replace(a["old"], a["new"], 1))
        ctx.app.changes.notify(ctx.session_id, p, ctx.provider, ctx.model)
        return ToolOutput(f"Edited {a['path']} ({n if a.get('replace_all') else 1} replacement)")

    @reg.add("delete_file", "Delete a file in the session folder (always asks the user).",
             obj({"path": {"type": "string"}}, ["path"]))
    async def delete_file(ctx: ToolContext, a: dict) -> ToolOutput:
        p = ctx.resolve_path(a["path"], write=True)
        if ctx.mode == "plan":
            return ToolOutput("Plan only mode: no deletes.", is_error=True)
        if not ctx.app.approvals.allowlisted("delete", str(p)):
            res = await ctx.app.approvals.ask(ctx.session_id, "delete", {"subject": str(p), "path": str(p)})
            if res["status"] != "approved":
                return ToolOutput("User declined the delete.", is_error=True)
        ctx.app.changes.snapshot(ctx.session_id, p)
        p.unlink()
        ctx.app.changes.notify(ctx.session_id, p, ctx.provider, ctx.model)
        return ToolOutput(f"Deleted {a['path']}")

    @reg.add("run_command", "Run a shell command in the session folder (zsh login shell on macOS). "
             "Asks the user unless allowlisted. Output is shown in its own terminal tab.",
             obj({"command": {"type": "string"}, "timeout_s": {"type": "integer"},
                  "background": {"type": "boolean"}}, ["command"]))
    async def run_command(ctx: ToolContext, a: dict) -> ToolOutput:
        cmd = a["command"]
        if ctx.mode == "plan":
            return ToolOutput("Plan only mode: commands are not run.", is_error=True)
        # ctx.consented: a hook context's consented command lines (always empty for agents).
        if not (ctx.consented("run_command", cmd) or ctx.app.approvals.allowlisted("run_command", cmd)):
            res = await ctx.app.approvals.ask(ctx.session_id, "command",
                                              {"subject": cmd, "command": cmd, "cwd": str(ctx.folder or "~"),
                                               "role": ctx.role, "run_id": ctx.run_id})
            if res["status"] != "approved":
                return ToolOutput("User declined to run this command.", is_error=True)
        cwd = ctx.folder or Path.home()
        timeout = min(int(a.get("timeout_s") or 120), 1800)
        job = ctx.app.jobs.start(ctx.session_id, "command", cmd, {"cwd": str(cwd), "run_id": ctx.run_id})
        coro = ctx.app.commands.run(job, cmd, cwd, timeout)
        if a.get("background"):
            ctx.app.jobs.attach(job, asyncio.create_task(coro))
            return ToolOutput(f"Started in background as job {job}. Check it in Background tasks.")
        code, out = await coro
        out = out if len(out) <= MAX_CMD_OUT else out[:MAX_CMD_OUT // 2] + "\n…[truncated]…\n" + out[-MAX_CMD_OUT // 2:]
        return ToolOutput(f"exit code {code}\n{out}", is_error=code != 0)
