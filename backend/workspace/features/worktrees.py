"""Git worktrees: one per parallel code unit, merged back by the orchestrator.

They live at <data dir>/worktrees/<session id>/<unit id> on branch `workspace/<unit id>`.
Besides merge_worktree, they go away when:
- the main agent calls discard_worktree, or the user presses Discard on the Changes card
  (work that isn't merged yet needs an explicit confirmation);
- their session is deleted for good: `cleanup_session(app, session_id)`;
- at startup, their session no longer exists (`sweep_orphans`). Worktrees with uncommitted
  changes are never removed by the sweep; they're listed in the log instead.
Only folders under the app's worktrees root that git confirms are linked worktrees are touched.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI

    from ..app import AppState

log = logging.getLogger(__name__)
UNIT_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

GIT_ID = ["-c", "user.name=Workspace", "-c", "user.email=workspace@localhost"]
# Every git command the app runs by itself (worktree add, commit, merge, the Changes card's diff, ...)
# skips hooks and fsmonitor, and never treats a folder as a bare repository just because it looks like
# one: a repository's own hooks or config must not turn "show the diff" into running a program.
# Command-line -c beats repository config (safe.bareRepository is only read from protected config).
# Agent file tools can't write under .git either (agent/tools.py), so new driver/filter config can't
# be planted; diffs also pass --no-ext-diff --no-textconv.
GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "safe.bareRepository=explicit"]


class GitError(RuntimeError):
    pass


async def git(cwd: Path, *args: str, check: bool = True, strip: bool = True) -> tuple[int, str]:
    """`git <GIT_SAFE> <args>` in cwd. Every git command the backend starts goes through here."""
    p = await asyncio.create_subprocess_exec("git", *GIT_SAFE, *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE,
                                             stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL)
    out, _ = await p.communicate()
    text = out.decode(errors="replace")
    text = text.strip() if strip else text
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {text}")
    return p.returncode or 0, text


async def is_repo(folder: Path) -> bool:
    code, out = await git(folder, "rev-parse", "--is-inside-work-tree", check=False)
    return code == 0 and out == "true"


async def repo_root(folder: Path) -> Path:
    return Path((await git(folder, "rev-parse", "--show-toplevel"))[1])


def branch_name(unit_id: str) -> str:
    return f"workspace/{unit_id}"


async def create(folder: Path, root: Path, unit_id: str) -> Path:
    """New worktree at <root>/<unit_id> on branch workspace/<unit_id>, from HEAD."""
    if not await is_repo(folder):
        raise GitError(f"{folder} is not a git repository, so code units can't get their own worktree. "
                       "Run `git init` and commit first, or run the unit without worktree=true.")
    code, _ = await git(folder, "rev-parse", "--verify", "HEAD", check=False)
    if code != 0:
        raise GitError("The repository has no commits yet; commit once so worktrees have a base.")
    root.mkdir(parents=True, exist_ok=True)
    path = root / unit_id
    await git(folder, "worktree", "add", "-b", branch_name(unit_id), str(path), "HEAD")
    return path


async def commit_all(path: Path, message: str) -> bool:
    await git(path, "add", "-A")
    code, _ = await git(path, "diff", "--cached", "--quiet", check=False)
    if code == 0:
        return False
    await git(path, *GIT_ID, "commit", "-q", "-m", message)
    return True


async def diff_stat(folder: Path, unit_id: str) -> str:
    _, out = await git(folder, "diff", "--no-ext-diff", "--no-textconv", "--stat", f"HEAD...{branch_name(unit_id)}",
                       check=False)
    return out


async def merge(folder: Path, root: Path, unit_id: str, message: str | None = None) -> dict:
    """Commit the worktree's changes and merge its branch into the folder's current branch.
    On conflict the merge is aborted and the conflicting files are reported."""
    path = root / unit_id
    if path.exists():
        info = await inspect(path)
        if info is not None and not info["on_branch"]:
            raise GitError(f"The worktree {path} has {describe(info)}, so merging {branch_name(unit_id)} wouldn't "
                           f"include its work. Check out {branch_name(unit_id)} there (or merge by hand) first.")
        await commit_all(path, message or f"Workspace unit {unit_id}")
    branch = branch_name(unit_id)
    code, ahead = await git(folder, "rev-list", "--count", f"HEAD..{branch}", check=False)
    if code != 0:
        raise GitError(f"No branch {branch}")
    if ahead.strip() == "0":
        await remove(folder, root, unit_id)
        return {"merged": True, "changes": False, "conflicts": []}
    stat = await diff_stat(folder, unit_id)
    code, out = await git(folder, *GIT_ID, "merge", "--no-ff", "-m", message or f"Merge {branch}", branch,
                          check=False)
    if code != 0:
        _, files = await git(folder, "diff", "--name-only", "--diff-filter=U", check=False)
        await git(folder, "merge", "--abort", check=False)
        return {"merged": False, "conflicts": [f for f in files.splitlines() if f], "detail": out[-2000:]}
    await remove(folder, root, unit_id)
    return {"merged": True, "changes": True, "conflicts": [], "stat": stat}


async def remove(folder: Path, root: Path, unit_id: str, delete_branch: bool = True) -> None:
    path = root / unit_id
    if path.exists():
        if (info := await inspect(path)) is not None:
            await keep_head(info)  # commits only a detached HEAD holds survive on a branch
        await git(folder, "worktree", "remove", "--force", str(path), check=False)
    if delete_branch:
        await git(folder, "branch", "-D", branch_name(unit_id), check=False)


# ------------------------------------------------------------------ cleanup


# Git-ignored files `git worktree remove --force` may delete without asking: build output and caches
# that a rebuild brings back. Anything else ignored (.env, local config, data files) counts as work.
DISPOSABLE_IGNORED = {"node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target", ".pytest_cache",
                      ".mypy_cache", ".ruff_cache", ".tox", ".next", ".cache", ".parcel-cache", ".turbo",
                      ".DS_Store"}
DISPOSABLE_SUFFIXES = (".pyc", ".pyo")


def _disposable(rel: str) -> bool:
    parts = [p for p in rel.rstrip("/").split("/") if p]
    return any(p in DISPOSABLE_IGNORED for p in parts) or rel.rstrip("/").endswith(DISPOSABLE_SUFFIXES)


def _parse_status(out: str) -> tuple[list[str], list[str]]:
    """`git status --porcelain -z --ignored=matching` → (changed paths, ignored paths). In matching mode
    an ignored directory is listed itself (node_modules/), and an otherwise untracked folder whose files
    are all ignored lists those files (pkg/__pycache__/) rather than the folder (pkg/)."""
    changed: list[str] = []
    ignored: list[str] = []
    tokens = out.split("\0")
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if len(tok) < 4:
            continue
        xy, rel = tok[:2], tok[3:]
        if xy == "!!":
            ignored.append(rel)
            continue
        changed.append(rel)
        if "R" in xy or "C" in xy:
            i += 1  # the rename/copy source follows as its own field
    return changed, ignored


async def _count(repo: Path, *args: str) -> int:
    code, out = await git(repo, "rev-list", "--count", *args, check=False)
    return int(out) if code == 0 and out.isdigit() else 0


async def inspect(path: Path) -> dict | None:
    """Facts about one Workspace worktree folder, or None if git doesn't confirm it is a linked
    worktree rooted exactly there.
    dirty: uncommitted changes (untracked files included); changed_files: how many;
    head / head_ref: the worktree's checked-out commit and symbolic ref ("" when detached);
    on_branch: it is on `workspace/<unit>`; branch_exists: that branch exists;
    ahead: commits on the worktree's HEAD or its branch that the repository's HEAD doesn't have;
    branch_ahead: commits on `workspace/<unit>` the repository's HEAD doesn't have (deleting the branch
    loses them); unreachable: commits on the worktree's HEAD no branch contains (removing the worktree
    loses them); ignored: git-ignored files beyond build output and caches (`worktree remove --force`
    deletes them)."""
    if not UNIT_RE.match(path.name) or not (path / ".git").is_file():
        return None  # a linked worktree has a .git *file*; without one git would search parent folders
    code, top = await git(path, "rev-parse", "--show-toplevel", check=False)
    if code != 0 or Path(top).resolve() != path.resolve():
        return None
    code, common = await git(path, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False)
    if code != 0 or not common:
        return None
    common_dir = Path(common)
    repo = common_dir.parent if common_dir.name == ".git" else common_dir
    branch = branch_name(path.name)
    _, status = await git(path, "status", "--porcelain", "-z", "--ignored=matching", check=False, strip=False)
    changed, ignored = _parse_status(status)
    code, head = await git(path, "rev-parse", "--verify", "-q", "HEAD", check=False)
    head = head if code == 0 else ""
    code, head_ref = await git(path, "symbolic-ref", "-q", "HEAD", check=False)
    head_ref = head_ref if code == 0 else ""
    code, branch_sha = await git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
    branch_sha = branch_sha if code == 0 else ""
    tips = [t for t in (head, branch_sha) if t]
    return {"unit": path.name, "path": str(path), "repo": str(repo), "branch": branch,
            "dirty": bool(changed), "changed_files": len(changed),
            "head": head, "head_ref": head_ref, "on_branch": head_ref == f"refs/heads/{branch}",
            "branch_exists": bool(branch_sha),
            "ahead": await _count(repo, *tips, "--not", "HEAD") if tips else 0,
            "branch_ahead": await _count(repo, f"HEAD..{branch_sha}") if branch_sha else 0,
            "unreachable": await _count(repo, head, "--not", "--branches") if head else 0,
            "ignored": [f for f in ignored if not _disposable(f)]}


def unmerged(info: dict) -> bool:
    """Work that removing the worktree and its branch would throw away (or that sits somewhere the
    merge doesn't look: a worktree no longer on `workspace/<unit>`)."""
    return bool(info["dirty"] or info["ahead"] or info["unreachable"] or not info["on_branch"])


def needs_confirm(info: dict) -> bool:
    """Discarding needs the user's explicit OK: unmerged work, or ignored files like .env."""
    return unmerged(info) or bool(info["ignored"])


def describe(info: dict) -> str:
    parts = []
    if not info["on_branch"]:
        ref = info.get("head_ref") or ""
        parts.append(f"a checkout of {ref.removeprefix('refs/heads/')} instead of {info['branch']}" if ref
                     else f"a detached HEAD instead of {info['branch']}")
    if info["ahead"]:
        parts.append(f"{info['ahead']} unmerged commit{'s' * (info['ahead'] != 1)}")
    if info["dirty"]:
        n = info.get("changed_files") or 0
        parts.append(f"uncommitted changes in {n} file{'s' * (n != 1)}")
    if info.get("ignored"):
        n = len(info["ignored"])
        shown = ", ".join(info["ignored"][:5]) + (", …" if n > 5 else "")
        parts.append(f"{n} git-ignored file{'s' * (n != 1)} ({shown})")
    return " and ".join(parts) or "no unmerged work"


async def keep_head(info: dict) -> str | None:
    """If the worktree's HEAD has commits no branch contains (a detached HEAD with work), point a branch
    at it so removing the worktree doesn't make them unreachable: `workspace/<unit>` when that's free,
    else `workspace/<unit>-kept-<short sha>`. Returns the branch name (and logs it), or None."""
    if not info.get("unreachable") or not info.get("head"):
        return None
    repo, head = Path(info["repo"]), info["head"]
    name = info["branch"]
    code, sha = await git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False)
    if code == 0 and sha != head:
        name = f"{info['branch']}-kept-{head[:10]}"
        code, sha = await git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False)
    if code != 0:
        await git(repo, "branch", name, head)
    elif sha != head:
        raise GitError(f"Can't keep {head[:10]}: branch {name} already exists")
    log.warning("worktree %s had %d commit(s) on a detached HEAD; kept them on branch %s in %s",
                info["path"], info["unreachable"], name, info["repo"])
    info["kept_branch"] = name
    return name


def _rmdir_empty(d: Path) -> None:
    try:
        d.rmdir()
    except OSError:
        pass


async def _remove(info: dict, delete_branch: bool) -> str | None:
    """Remove the worktree folder (and `workspace/<unit>` if delete_branch). Commits only its detached
    HEAD holds are put on a branch first (keep_head), which is never deleted here. Returns that branch."""
    repo, path = Path(info["repo"]), Path(info["path"])
    kept = await keep_head(info)
    await git(repo, "worktree", "remove", "--force", str(path))
    if delete_branch and kept != info["branch"]:
        await git(repo, "branch", "-D", info["branch"], check=False)
    return kept


async def list_session(app: "AppState", session_id: str) -> list[dict]:
    root = app.worktrees_root(session_id)
    out = []
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if p.is_dir() and (info := await inspect(p)):
                out.append(info)
    return out


async def discard(app: "AppState", session_id: str, unit_id: str, force: bool = False) -> dict:
    """Remove one worktree and its branch. Without force it refuses (returns needs_confirm) when the
    worktree has uncommitted changes, unmerged commits, isn't on its branch, or holds git-ignored files
    that aren't build output (.env and the like). Even with force, commits only a detached HEAD holds
    are kept on a branch (see keep_head). Raises KeyError / GitError / RuntimeError."""
    root = app.worktrees_root(session_id)
    path = root / unit_id
    if not UNIT_RE.match(unit_id) or not path.is_dir():
        raise KeyError(unit_id)
    subs = app.extensions.get("subagents")
    sub = getattr(subs, "subs", {}).get(unit_id)
    if sub is not None and sub.status in ("queued", "running"):
        raise RuntimeError(f"{sub.name} is still working in this worktree; stop it first.")
    info = await inspect(path)
    if info is None:
        raise GitError(f"{path} isn't a git worktree Workspace can remove.")
    if needs_confirm(info) and not force:
        return {"discarded": False, "needs_confirm": True, "detail": describe(info), **info}
    await _remove(info, delete_branch=True)
    _rmdir_empty(root)
    app.bus.publish("file.changed", {"path": info["path"], "discarded": unit_id}, session_id)
    return {"discarded": True, **info}


async def cleanup_session(app: "AppState", session_id: str) -> dict:
    """Call when a session is deleted for good (hard delete / purge): stop its subagents and remove
    every worktree folder it has. Work nobody merged isn't thrown away: leftover changes are
    committed to the worktree's HEAD and `workspace/<unit>` is kept in the repository (and logged)
    while it has unmerged commits; commits on a detached HEAD get a branch of their own (keep_head).
    Clean worktrees lose their branch too. Git-ignored files (other than build output and caches)
    can't be kept; they're listed in the log. Never raises; returns what happened."""
    removed: list[str] = []
    kept_branches: list[str] = []
    left: list[str] = []
    subs = app.extensions.get("subagents")
    for sub in list(getattr(subs, "subs", {}).values()):
        if sub.session_id == session_id and sub.status in ("queued", "running"):
            try:
                await subs.stop(sub.id)  # type: ignore[union-attr]
                await asyncio.wait_for(sub.done_event.wait(), 10)
            except Exception:  # noqa: BLE001
                log.warning("cleanup_session: subagent %s didn't stop", sub.id, exc_info=True)
    root = app.worktrees_root(session_id)
    if not root.is_dir():
        return {"removed": removed, "kept_branches": kept_branches, "left": left}
    for path in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            info = await inspect(path)
            if info is None:
                left.append(str(path))
                continue
            if info["dirty"]:
                await git(path, "add", "-A")
                await git(path, *GIT_ID, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m",
                          f"Workspace unit {info['unit']} (kept when its session was deleted)")
                info = await inspect(path)
                if info is None:
                    raise GitError("not a worktree any more after committing")
            kept = await _remove(info, delete_branch=not info["branch_ahead"])
            removed.append(str(path))
            if info["branch_ahead"] and kept != info["branch"]:
                kept_branches.append(f"{info['repo']}: {info['branch']}")
            if kept:
                kept_branches.append(f"{info['repo']}: {kept}")
            if info["ignored"]:
                log.warning("session %s deleted; git-ignored files removed with worktree %s: %s", session_id,
                            path, ", ".join(info["ignored"]))
        except Exception as e:  # noqa: BLE001
            log.warning("cleanup_session: couldn't remove %s: %s", path, e)
            left.append(str(path))
    _rmdir_empty(root)
    if kept_branches:
        log.info("session %s deleted; unmerged work kept on branches: %s", session_id, "; ".join(kept_branches))
    if left:
        log.warning("session %s deleted; worktree folders left in place: %s", session_id, "; ".join(left))
    return {"removed": removed, "kept_branches": kept_branches, "left": left}


async def sweep_orphans(app: "AppState") -> dict:
    """Startup: remove worktrees whose session no longer exists. A worktree with uncommitted changes
    or git-ignored files that aren't build output (.env, local data) is never removed here (the user
    hasn't approved losing them); it's listed in the log. One with unmerged commits loses only its
    folder; its branch keeps the commits (commits on a detached HEAD get a branch, see keep_head)."""
    base = app.worktrees_root("_").parent
    removed: list[str] = []
    kept: list[str] = []
    if not base.is_dir():
        return {"removed": removed, "kept": kept}
    for sdir in sorted(p for p in base.iterdir() if p.is_dir()):
        if not UNIT_RE.match(sdir.name) or app.db.one("SELECT 1 FROM sessions WHERE id=?", [sdir.name]):
            continue
        for path in sorted(p for p in sdir.iterdir() if p.is_dir()):
            try:
                info = await inspect(path)
                if info is None or info["dirty"] or info["ignored"]:
                    kept.append(str(path) + (f" ({describe(info)})" if info else " (not a git worktree)"))
                    continue
                await _remove(info, delete_branch=not info["branch_ahead"])
                removed.append(str(path))
            except Exception as e:  # noqa: BLE001
                kept.append(f"{path} ({e})")
        _rmdir_empty(sdir)
    if removed:
        log.info("removed %d worktree(s) of deleted sessions", len(removed))
    if kept:
        log.warning("worktrees of deleted sessions kept because they hold uncommitted work or git-ignored files "
                    "(remove them yourself "
                    "with `git worktree remove` once you've checked them): %s", "; ".join(kept))
    return {"removed": removed, "kept": kept}


# ------------------------------------------------------------- tool and API


class _Janitor:
    """Runs the orphan sweep once at startup, in the background."""

    def __init__(self, app: "AppState"):
        self.app = app
        self.task: asyncio.Task | None = None

    async def astart(self) -> None:
        async def run() -> None:
            try:
                await sweep_orphans(self.app)
            except Exception:  # noqa: BLE001
                log.exception("worktree sweep failed")

        self.task = asyncio.create_task(run())

    async def aclose(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()


def register(app_: "FastAPI", api: "APIRouter", S: "AppState") -> None:
    from fastapi import Body, HTTPException

    from ..agent.tools import Tool, ToolContext, ToolOutput, obj
    from ..core.types import ToolSpec

    S.extensions["worktrees"] = _Janitor(S)

    async def discard_tool(ctx: ToolContext, a: dict) -> ToolOutput:
        unit = str(a.get("id") or "")
        path = S.worktrees_root(ctx.session_id) / unit
        if not UNIT_RE.match(unit) or not path.is_dir():
            return ToolOutput("No worktree for that subagent in this session.", is_error=True)
        sub = getattr(S.extensions.get("subagents"), "subs", {}).get(unit)
        if sub is not None and sub.status in ("queued", "running"):
            return ToolOutput(f"{sub.name} is still working in this worktree; stop it first.", is_error=True)
        info = await inspect(path)
        if info is None:
            return ToolOutput(f"{path} isn't a git worktree Workspace can remove.", is_error=True)
        force = bool(a.get("force"))
        if needs_confirm(info) and not force:
            return ToolOutput(f"Refused: {branch_name(unit)} has {describe(info)}. Merge it with merge_worktree, "
                              "or, if that work really should be thrown away, call discard_worktree again with "
                              "force=true (the user is asked to confirm).", is_error=True)
        await ctx.approve("delete", f"discard worktree {branch_name(unit)}", {
            "path": str(path), "branch": branch_name(unit), "action": "discard_worktree",
            "detail": describe(info), "unmerged": needs_confirm(info)})
        try:
            r = await discard(S, ctx.session_id, unit, force=True)
        except (KeyError, GitError, RuntimeError) as e:
            return ToolOutput(str(e.args[0] if e.args else e), is_error=True)
        return ToolOutput(f"Discarded worktree {r['unit']} and branch {r['branch']}"
                          + (f" ({describe(info)} thrown away)." if needs_confirm(info) else ".")
                          + (f" Commits on its detached HEAD were kept on branch {r['kept_branch']}."
                             if r.get("kept_branch") else ""))

    S.tools.register(Tool(ToolSpec(
        name="discard_worktree",
        description="Remove a subagent's worktree and its workspace/<unit> branch without merging (failed, "
                    "abandoned or superseded units). Refuses when it holds unmerged work unless force=true; always "
                    "asks the user first.",
        input_schema=obj({"id": {"type": "string", "description": "The subagent id (= worktree name)"},
                          "force": {"type": "boolean", "description": "Throw away unmerged work too"}}, ["id"])),
        discard_tool, main_only=True))

    @api.post("/sessions/{sid}/worktrees/{unit}/discard")
    async def discard_route(sid: str, unit: str, body: dict = Body(default={})) -> dict[str, Any]:
        if not S.store.get(sid):
            raise HTTPException(404)
        try:
            r = await discard(S, sid, unit, force=bool(body.get("force")))
        except KeyError:
            raise HTTPException(404, "No such worktree") from None
        except RuntimeError as e:  # GitError included
            raise HTTPException(409, str(e)) from e
        return r  # {"discarded": false, "needs_confirm": true, "detail"} when unmerged work needs force
