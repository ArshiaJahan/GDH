"""Worktrees don't leak: discard (API and main-agent tool), session delete, startup sweep."""
import asyncio
import subprocess

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.features import worktrees as wt
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}


def sh(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    (r / "a.txt").write_text("one\n")
    sh(r, "init", "-q")
    sh(r, "add", "-A")
    sh(r, "commit", "-qm", "init")
    return r


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "w.db")
    with TestClient(create_app("t", s)) as c:
        yield c, s


def branches(repo) -> set[str]:
    return set(sh(repo, "branch", "--list", "gdw/*", "--format=%(refname:short)").split())


def make(c, s, repo, sid, unit, dirty=False, commit=False):
    path = c.portal.call(wt.create, repo, s.worktrees_root(sid), unit)
    if dirty or commit:
        (path / f"{unit}.txt").write_text("work\n")
    if commit:
        sh(path, "add", "-A")
        sh(path, "commit", "-qm", "unit work")
    return path


def test_changes_card_lists_and_discards(env, repo):
    c, s = env
    sid = s.store.create(folder=str(repo))["id"]
    clean = make(c, s, repo, sid, "sub_clean")
    dirty = make(c, s, repo, sid, "sub_dirty", dirty=True)
    ch = c.get(f"/api/sessions/{sid}/changes", headers=H).json()
    by = {w["unit"]: w for w in ch["worktrees"]}
    assert by["sub_clean"]["unmerged"] is False and by["sub_dirty"]["dirty"] is True

    r = c.post(f"/api/sessions/{sid}/worktrees/sub_clean/discard", json={}, headers=H).json()
    assert r["discarded"] and not clean.exists() and "gdw/sub_clean" not in branches(repo)
    # Unmerged work: refused until confirmed.
    r = c.post(f"/api/sessions/{sid}/worktrees/sub_dirty/discard", json={}, headers=H).json()
    assert r == {**r, "discarded": False, "needs_confirm": True} and dirty.exists()
    assert "uncommitted changes in 1 file" in r["detail"]
    r = c.post(f"/api/sessions/{sid}/worktrees/sub_dirty/discard", json={"force": True}, headers=H).json()
    assert r["discarded"] and not dirty.exists() and not branches(repo)
    assert not s.worktrees_root(sid).exists()
    assert c.get(f"/api/sessions/{sid}/changes", headers=H).json()["worktrees"] == []
    # Only worktrees of this session, by plain name.
    assert c.post(f"/api/sessions/{sid}/worktrees/../discard", json={}, headers=H).status_code in (404, 405)
    assert c.post(f"/api/sessions/{sid}/worktrees/.git/discard", json={}, headers=H).status_code == 404
    assert c.post(f"/api/sessions/{sid}/worktrees/sub_nope/discard", json={}, headers=H).status_code == 404


def test_discard_worktree_tool(env, repo):
    c, s = env
    sess = s.store.create(folder=str(repo))
    path = make(c, s, repo, sess["id"], "sub_tool", commit=True)
    ctx = ToolContext(app=s, session=sess, run_id="main:x")

    async def flow():
        out = await s.tools.run(ctx, "discard_worktree", {"id": "sub_tool"})
        assert out.is_error and "1 unmerged commit" in out.text and path.exists()
        task = asyncio.create_task(s.tools.run(ctx, "discard_worktree", {"id": "sub_tool", "force": True}))
        for _ in range(300):
            if pend := s.approvals.pending(sess["id"]):
                break
            await asyncio.sleep(0.01)
        assert pend[0]["kind"] == "delete" and pend[0]["payload"]["unmerged"] is True
        s.approvals.resolve(pend[0]["id"], "approve")
        return await task

    out = c.portal.call(flow)
    assert not out.is_error, out.text
    assert not path.exists() and not branches(repo)
    # Subagents can't call it.
    sub_ctx = ToolContext(app=s, session=sess, run_id="sub_x", role="subagent")
    assert c.portal.call(s.tools.run, sub_ctx, "discard_worktree", {"id": "sub_tool"}).is_error


def test_session_delete_removes_worktrees_keeping_unmerged_work(env, repo):
    c, s = env
    sid = s.store.create(folder=str(repo))["id"]
    clean = make(c, s, repo, sid, "sub_a")
    dirty = make(c, s, repo, sid, "sub_b", dirty=True)
    # Moving to Trash keeps everything (the session can be restored) ...
    assert c.delete(f"/api/sessions/{sid}", headers=H).status_code == 200
    assert clean.exists() and dirty.exists()
    # ... deleting it for good removes the worktrees.
    assert c.delete(f"/api/sessions/{sid}?purge=1", headers=H).status_code == 200
    assert not clean.exists() and not dirty.exists() and not s.worktrees_root(sid).exists()
    # The clean unit's branch is gone; the unmerged work survives on its branch.
    assert branches(repo) == {"gdw/sub_b"}
    assert sh(repo, "show", "gdw/sub_b:sub_b.txt") == "work"
    assert "sub_b" not in sh(repo, "worktree", "list")


def test_startup_sweep_only_touches_orphans_and_never_dirty_ones(env, repo, caplog):
    c, s = env
    live = s.store.create(folder=str(repo))["id"]
    keep_live = make(c, s, repo, live, "sub_live")
    gone = "ses_deleted0000000"
    orphan_clean = make(c, s, repo, gone, "sub_oc")
    orphan_commit = make(c, s, repo, gone, "sub_om", commit=True)
    orphan_dirty = make(c, s, repo, gone, "sub_od", dirty=True)
    stray = s.worktrees_root(gone) / "not_a_worktree"
    stray.mkdir()
    (stray / "keep.txt").write_text("mine")

    res = c.portal.call(wt.sweep_orphans, s)
    assert sorted(res["removed"]) == sorted([str(orphan_clean), str(orphan_commit)])
    assert keep_live.exists() and orphan_dirty.exists() and (stray / "keep.txt").exists()
    assert not orphan_clean.exists() and not orphan_commit.exists()
    # Commits nobody merged stay on their branch; the dirty worktree keeps its branch too.
    assert branches(repo) == {"gdw/sub_live", "gdw/sub_om", "gdw/sub_od"}
    assert "sub_od" in caplog.text and "uncommitted" in caplog.text


# ------------------------------------------------- detached HEADs and ignored files (review fixes)


def reachable_from_branches(repo, sha) -> bool:
    return sh(repo, "rev-list", "--count", sha, "--not", "--branches") == "0"


def detach_with_commit(path, name="detached.txt") -> str:
    sh(path, "checkout", "-q", "--detach")
    (path / name).write_text("detached work\n")
    sh(path, "add", "-A")
    sh(path, "commit", "-qm", "work on a detached HEAD")
    return sh(path, "rev-parse", "HEAD")


def test_inspect_sees_work_on_a_detached_head(env, repo):
    c, s = env
    sid = s.store.create(folder=str(repo))["id"]
    path = make(c, s, repo, sid, "sub_det")
    sha = detach_with_commit(path)
    info = c.portal.call(wt.inspect, path)
    assert info["on_branch"] is False and info["head"] == sha and info["head_ref"] == ""
    assert info["unreachable"] == 1 and info["ahead"] == 1 and info["branch_ahead"] == 0
    assert not info["dirty"] and wt.unmerged(info) and "detached HEAD" in wt.describe(info)
    ch = c.get(f"/api/sessions/{sid}/changes", headers=H).json()
    assert ch["worktrees"][0]["unmerged"] is True
    # Discard asks first; with force the commit still survives on a branch.
    r = c.post(f"/api/sessions/{sid}/worktrees/sub_det/discard", json={}, headers=H).json()
    assert r["needs_confirm"] and path.exists()
    r = c.post(f"/api/sessions/{sid}/worktrees/sub_det/discard", json={"force": True}, headers=H).json()
    assert r["discarded"] and not path.exists()
    assert r["kept_branch"] == f"gdw/sub_det-kept-{sha[:10]}" and reachable_from_branches(repo, sha)
    assert sh(repo, "show", f"{r['kept_branch']}:detached.txt") == "detached work"


def test_off_branch_without_new_commits_is_unmerged_but_loses_nothing(env, repo):
    c, s = env
    gone = "ses_gone_offbranch"
    path = make(c, s, repo, gone, "sub_off")
    sh(path, "checkout", "-q", "--detach")
    info = c.portal.call(wt.inspect, path)
    assert wt.unmerged(info) and info["unreachable"] == 0 and info["ahead"] == 0
    res = c.portal.call(wt.sweep_orphans, s)
    assert res["removed"] == [str(path)] and not branches(repo)


def test_sweep_keeps_detached_commits_on_a_branch(env, repo, caplog):
    c, s = env
    gone = "ses_gone_detached"
    path = make(c, s, repo, gone, "sub_sd")
    sha = detach_with_commit(path)
    sh(repo, "branch", "-D", "gdw/sub_sd")  # branch name free: the commit gets gdw/sub_sd itself
    res = c.portal.call(wt.sweep_orphans, s)
    assert res["removed"] == [str(path)] and not path.exists()
    assert branches(repo) == {"gdw/sub_sd"} and sh(repo, "rev-parse", "gdw/sub_sd") == sha
    assert "gdw/sub_sd" in caplog.text


def test_session_delete_keeps_commits_made_on_a_detached_head(env, repo):
    c, s = env
    sid = s.store.create(folder=str(repo))["id"]
    path = make(c, s, repo, sid, "sub_cd")
    sha = detach_with_commit(path)
    (path / "loose.txt").write_text("uncommitted\n")  # committed onto the detached HEAD by cleanup
    res = c.portal.call(wt.cleanup_session, s, sid)
    assert res["removed"] == [str(path)] and not res["left"]
    kept = [b.split(": ", 1)[1] for b in res["kept_branches"]]
    assert len(kept) == 1 and kept[0].startswith("gdw/sub_cd-kept-")
    assert sh(repo, "rev-parse", f"{kept[0]}~1") == sha
    assert sh(repo, "show", f"{kept[0]}:loose.txt") == "uncommitted"
    assert "gdw/sub_cd" not in branches(repo)  # the original branch had nothing unmerged


def test_merge_refuses_a_worktree_that_left_its_branch(env, repo):
    c, s = env
    sid = s.store.create(folder=str(repo))["id"]
    path = make(c, s, repo, sid, "sub_mg")
    detach_with_commit(path)
    with pytest.raises(wt.GitError, match="detached HEAD"):
        c.portal.call(wt.merge, repo, s.worktrees_root(sid), "sub_mg")
    assert path.exists()


def ignore(repo, *patterns):
    (repo / ".gitignore").write_text("".join(f"{p}\n" for p in patterns))
    sh(repo, "add", ".gitignore")
    sh(repo, "commit", "-qm", "ignore")


def test_ignored_files_need_confirmation_and_block_the_sweep(env, repo, caplog):
    c, s = env
    ignore(repo, ".env", "node_modules/", "__pycache__/", "build/")
    sid = s.store.create(folder=str(repo))["id"]
    junk = make(c, s, repo, sid, "sub_junk")
    (junk / "node_modules" / "x").mkdir(parents=True)
    (junk / "node_modules" / "x" / "i.js").write_text("")
    (junk / "pkg" / "__pycache__").mkdir(parents=True)
    (junk / "pkg" / "__pycache__" / "m.pyc").write_text("")
    info = c.portal.call(wt.inspect, junk)
    assert info["ignored"] == [] and not wt.needs_confirm(info)
    secret = make(c, s, repo, sid, "sub_env")
    (secret / ".env").write_text("KEY=1\n")
    info = c.portal.call(wt.inspect, secret)
    assert info["ignored"] == [".env"] and not wt.unmerged(info) and wt.needs_confirm(info)
    assert "git-ignored" in wt.describe(info) and ".env" in wt.describe(info)
    by = {w["unit"]: w for w in c.get(f"/api/sessions/{sid}/changes", headers=H).json()["worktrees"]}
    assert by["sub_junk"]["unmerged"] is False and by["sub_env"]["unmerged"] is True
    r = c.post(f"/api/sessions/{sid}/worktrees/sub_env/discard", json={}, headers=H).json()
    assert r["needs_confirm"] and (secret / ".env").exists()
    r = c.post(f"/api/sessions/{sid}/worktrees/sub_junk/discard", json={}, headers=H).json()
    assert r["discarded"]

    gone = "ses_gone_ignored"
    orphan = make(c, s, repo, gone, "sub_oenv")
    (orphan / ".env").write_text("KEY=1\n")
    res = c.portal.call(wt.sweep_orphans, s)
    assert res["removed"] == [] and (orphan / ".env").exists() and ".env" in caplog.text

    # Deleting the session for good may remove them, but says what went.
    caplog.clear()
    res = c.portal.call(wt.cleanup_session, s, sid)
    assert res["removed"] == [str(secret)] and not secret.exists()
    assert "git-ignored files removed" in caplog.text and ".env" in caplog.text
