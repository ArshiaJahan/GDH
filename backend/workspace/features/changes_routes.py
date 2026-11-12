"""Changes card: files changed in the session folder and its subagent worktrees.

In a git repo: `git diff` against HEAD plus untracked files. Elsewhere: the snapshots
taken before each agent write. Per-file diff and revert.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, FastAPI, HTTPException

from . import worktrees as wt

if TYPE_CHECKING:
    from ..app import AppState

MAX_DIFF_BYTES = 2_000_000
TOO_LARGE_NOTE = "too large to snapshot"  # files over services.SNAPSHOT_MAX_BYTES before the agent's first write
LANG = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript",
        ".json": "json", ".md": "markdown", ".html": "html", ".css": "css", ".rs": "rust", ".go": "go",
        ".sh": "shell", ".yml": "yaml", ".yaml": "yaml", ".toml": "ini", ".sql": "sql", ".swift": "swift",
        ".java": "java", ".c": "c", ".cpp": "cpp", ".rb": "ruby", ".xml": "xml", ".svg": "xml"}


def _read(p: Path) -> str | None:
    if not p.is_file():
        return None
    if p.stat().st_size > MAX_DIFF_BYTES:
        return "[file too large to diff]"
    b = p.read_bytes()
    if b"\0" in b[:8000]:
        return "[binary file]"
    return b.decode("utf-8", "replace")


def _count(a: str | None, b: str | None) -> tuple[int, int]:
    add = rem = 0
    for line in difflib.unified_diff((a or "").splitlines(), (b or "").splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            add += 1
        elif line.startswith("-") and not line.startswith("---"):
            rem += 1
    return add, rem


async def _git_changes(root: Path, label: str) -> list[dict]:
    out: list[dict] = []
    _, numstat = await wt.git(root, "diff", "--no-ext-diff", "--no-textconv", "--numstat", "HEAD", check=False)
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            a, r, path = parts
            out.append({"path": path, "root": str(root), "where": label, "added": int(a) if a.isdigit() else 0,
                        "removed": int(r) if r.isdigit() else 0, "status": "modified" if (root / path).exists() else "deleted",
                        "binary": a == "-"})
    _, untracked = await wt.git(root, "ls-files", "--others", "--exclude-standard", check=False)
    for path in untracked.splitlines()[:500]:
        txt = _read(root / path)
        out.append({"path": path, "root": str(root), "where": label, "added": len((txt or "").splitlines()),
                    "removed": 0, "status": "added", "binary": txt == "[binary file]"})
    return out


class ChangeTracker:
    def __init__(self, app: "AppState"):
        self.app = app

    def _session(self, sid: str) -> dict:
        s = self.app.store.get(sid)
        if not s:
            raise HTTPException(404)
        return s

    def _roots(self, sid: str) -> list[Path]:
        s = self._session(sid)
        roots = [Path(s["folder"])] if s.get("folder") else []
        wroot = self.app.worktrees_root(sid)
        if wroot.exists():
            roots += sorted(p for p in wroot.iterdir() if p.is_dir())
        return roots

    async def list(self, sid: str) -> dict:
        s = self._session(sid)
        folder = Path(s["folder"]) if s.get("folder") else None
        files: list[dict] = []
        worktrees: list[dict] = []
        mode = "none"
        if folder and await wt.is_repo(folder):
            mode = "git"
            files += await _git_changes(folder, "folder")
            wroot = self.app.worktrees_root(sid)
            if wroot.exists():
                for w in sorted(p for p in wroot.iterdir() if p.is_dir()):
                    files += await _git_changes(w, f"worktree {w.name}")
            # Every worktree, changed or not, so the card can offer Discard for each.
            worktrees = [{"unit": i["unit"], "where": f"worktree {i['unit']}", "branch": i["branch"],
                          "dirty": i["dirty"], "ahead": i["ahead"], "unmerged": wt.needs_confirm(i)}
                         for i in await wt.list_session(self.app, sid)]
        elif folder:
            mode = "snapshots"
            for r in self.app.db.all("SELECT path, content, too_large FROM snapshots WHERE session_id=? ORDER BY ts",
                                     [sid]):
                p = Path(r["path"])
                rel = str(p.relative_to(folder)) if folder in p.parents else str(p)
                if r["too_large"]:  # no "before" copy: listed, but can't be diffed or reverted
                    files.append({"path": rel, "root": str(folder), "where": "folder", "added": 0, "removed": 0,
                                  "status": "modified" if p.exists() else "deleted", "binary": False,
                                  "too_large": True, "note": TOO_LARGE_NOTE})
                    continue
                before = r["content"].decode("utf-8", "replace") if r["content"] is not None else None
                after = _read(p)
                if before == after:
                    continue
                a, rem = _count(before, after)
                status = "added" if before is None else "deleted" if after is None else "modified"
                files.append({"path": rel, "root": str(folder), "where": "folder", "added": a, "removed": rem,
                              "status": status, "binary": False})
        return {"mode": mode, "files": files, "worktrees": worktrees, "added": sum(f["added"] for f in files),
                "removed": sum(f["removed"] for f in files)}

    def _check_root(self, sid: str, root: str, path: str) -> tuple[Path, Path]:
        r = Path(root).resolve()
        if r not in [x.resolve() for x in self._roots(sid)]:
            raise HTTPException(403, "Not a folder of this session")
        full = (r / path).resolve()
        if r not in full.parents:
            raise HTTPException(403, "Path outside the folder")
        return r, full

    async def diff(self, sid: str, root: str, path: str) -> dict:
        r, full = self._check_root(sid, root, path)
        if await wt.is_repo(r):
            code, before = await wt.git(r, "show", f"HEAD:{path}", check=False, strip=False)
            original = before if code == 0 else ""
        else:
            row = self.app.db.one("SELECT content, too_large FROM snapshots WHERE session_id=? AND path=?",
                                  [sid, str(full)])
            if row and row["too_large"]:
                original = f"[{TOO_LARGE_NOTE}]"
            else:
                original = (row["content"] or b"").decode("utf-8", "replace") if row else ""
        return {"path": path, "root": str(r), "original": original, "modified": _read(full) or "",
                "language": LANG.get(full.suffix.lower(), "plaintext")}

    async def revert(self, sid: str, root: str, path: str) -> dict:
        r, full = self._check_root(sid, root, path)
        if await wt.is_repo(r):
            code, _ = await wt.git(r, "cat-file", "-e", f"HEAD:{path}", check=False)
            if code == 0:
                await wt.git(r, "checkout", "HEAD", "--", path)
            elif full.exists():
                full.unlink()  # new, untracked file: reverting means removing it
        else:
            row = self.app.db.one("SELECT content, too_large FROM snapshots WHERE session_id=? AND path=?",
                                  [sid, str(full)])
            if not row:
                raise HTTPException(404, "No snapshot for that file")
            if row["too_large"]:
                raise HTTPException(409, f"Can't revert {path}: it was {TOO_LARGE_NOTE}.")
            if row["content"] is None:
                full.unlink(missing_ok=True)
            else:
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_bytes(row["content"])
            self.app.db.execute("DELETE FROM snapshots WHERE session_id=? AND path=?", [sid, str(full)])
        self.app.bus.publish("file.changed", {"path": str(full), "reverted": True}, sid)
        return {"ok": True}


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    ct = ChangeTracker(S)

    @api.get("/sessions/{sid}/changes")
    async def changes(sid: str) -> dict:
        return await ct.list(sid)

    @api.get("/sessions/{sid}/changes/diff")
    async def diff(sid: str, root: str, path: str) -> dict:
        return await ct.diff(sid, root, path)

    @api.post("/sessions/{sid}/changes/revert")
    async def revert(sid: str, body: dict = Body(...)) -> dict:
        return await ct.revert(sid, body["root"], body["path"])
