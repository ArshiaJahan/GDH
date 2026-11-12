"""Unity CLI phase 3: the HarnessCli installer (research §2.14 case 14), batch jobs on a copy of the
project while the Editor holds it (case 15), `needs_harness` results, the install_harness and
use_clone actions, and menu items in batch. Unity, the real Unity CLI and the user's projects are
never touched: `unity` is tests/fixtures/fake_unity_cli.py, `cp` / `rsync` are replaced by an
in-process copy, and the clones live under the test's GDW_HOME."""
import asyncio
import json
import os
import shutil
import stat
import subprocess
import threading
from pathlib import Path

import pytest

from gamedevworkstation.features import hooks as H
from gamedevworkstation.features import unity_clone as uclone
from gamedevworkstation.features import unity_harness as uh
from gamedevworkstation.features import unity_tool as UT

from .test_unity_cli import app, bridge, consent, fake_cli, proj, session  # noqa: F401 (fixtures)

TPL = uh.templates_dir()


def has_git() -> bool:
    return shutil.which("git") is not None


async def wait_card(app, sid, n=300):
    for _ in range(n):
        if cards := app.approvals.pending(sid):
            return cards
        await asyncio.sleep(0.02)
    return []


def ours(proj: Path) -> Path:
    return proj / uh.HARNESS_DIR


# ------------------------------------------------------------------ case 14: installer


def test_template_carries_the_version_marker_and_known_hashes():
    data = (TPL / "HarnessCli.cs").read_bytes()
    assert data.startswith(b"// harness-version: ") and uh.version_of(data) == 2
    assert b"public static void MenuItem()" in data and b'Get("buildOutput")' in data
    # The shipped files are never listed as "older" (a template change must add the old hash).
    for name in uh.FILES:
        assert uh._digest((TPL / name).read_bytes()) not in uh.PREVIOUS.get(name, set()), name
    assert uh.version_of(b"// Harness.Headless: ...") == 1 and uh.version_of(None) is None


@pytest.mark.skipif(not has_git(), reason="needs git")
def test_install_copies_files_metas_and_excludes_once(proj, tmp_path):
    repo = tmp_path  # the project is a subfolder (Game/) of the work tree
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    st = uh.harness_status(proj)
    assert not st["installed"] and st["missing"] == list(uh.FILES)
    r = uh.install_harness(proj)
    assert r["ok"] and r["status"] == "installed"
    for name in uh.FILES:
        assert (ours(proj) / name).read_bytes() == (TPL / name).read_bytes()
        meta = (ours(proj) / f"{name}.meta").read_text()
        assert f"guid: {uh.guid_for(f'{uh.HARNESS_DIR}/{name}')}" in meta
    assert "MonoImporter" in (ours(proj) / "HarnessCli.cs.meta").read_text()
    assert "AssemblyDefinitionImporter" in (ours(proj) / "Harness.Headless.Editor.asmdef.meta").read_text()
    assert "folderAsset: yes" in (proj / "Assets/Harness.meta").read_text()
    st = uh.harness_status(proj)
    assert st["installed"] and st["complete"] and st["version"] == 2 and not st["outdated"] and not st["modified"]
    excl = repo / ".git/info/exclude"
    lines = excl.read_text().splitlines()
    assert "/Game/Assets/Harness/Headless/" in lines and "/Game/Assets/Harness/Headless.meta" in lines
    assert "/Game/Assets/Harness.meta" in lines  # we created Assets/Harness
    assert "/Game/Assets/Harness/" not in lines  # other skills' Assets/Harness/* stay visible to git
    out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
                         capture_output=True, text=True, check=True).stdout
    assert "Harness" not in out and "Game/Assets/Game/Hit.cs" in out
    # Idempotent: nothing rewritten, the exclude lines only once.
    before = excl.read_text()
    r = uh.install_harness(proj)
    assert r["ok"] and r["status"] == "up_to_date" and r["written"] == []
    assert excl.read_text() == before
    guids = {n: (ours(proj) / f"{n}.meta").read_text() for n in uh.FILES}
    # Uninstall + reinstall: same GUIDs, exclude block still once.
    u = uh.uninstall_harness(proj)
    assert u["ok"] and not (proj / "Assets/Harness").exists() and not (proj / "Assets/Harness.meta").exists()
    assert "Headless" not in excl.read_text()
    uh.install_harness(proj)
    assert {n: (ours(proj) / f"{n}.meta").read_text() for n in uh.FILES} == guids
    assert excl.read_text().count("/Game/Assets/Harness/Headless/") == 1
    assert excl.read_text().count(uh.EXCLUDE_HEADER) == 1


def test_install_outside_git_and_exclude_off(proj):
    r = uh.install_harness(proj)
    assert r["ok"] and r["git_exclude"]["status"] == "not_git"
    uh.uninstall_harness(proj)
    r = uh.install_harness(proj, exclude_from_git=False)
    assert r["ok"] and r["git_exclude"] == {"status": "off"}


async def test_install_missing_assets_fails_without_card(app, tmp_path):
    root = tmp_path / "empty-project"
    root.mkdir()
    r = uh.install_harness(root)
    assert not r["ok"] and r["written"] == [] and "Assets" in r["message"]
    s = session(app, root)
    result = await asyncio.wait_for(UT.install_harness_action(app, s), 2)
    assert result.status == "fail" and "Assets" in result.summary
    assert not app.approvals.pending(s["id"]) and not (root / "Assets").exists()


@pytest.mark.skipif(not has_git(), reason="needs git")
@pytest.mark.parametrize("preexisting", [True, False])
def test_uninstall_preserves_preexisting_empty_harness(proj, tmp_path, preexisting):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    harness = proj / "Assets/Harness"
    if preexisting:
        harness.mkdir()
        (proj / "Assets/Harness.meta").write_text("existing meta")
    uh.install_harness(proj)
    marker = json.loads((proj / uh.MARKER).read_text())
    assert marker == {"created_harness": not preexisting}
    # Repairing a partial installation preserves the original ownership record.
    (ours(proj) / "HarnessArgs.cs").unlink()
    uh.install_harness(proj)
    assert json.loads((proj / uh.MARKER).read_text()) == marker
    exclude = tmp_path / ".git/info/exclude"
    if preexisting:
        with exclude.open("a") as f:
            f.write("/Game/Assets/Harness.meta\n")  # an existing user rule must survive
    uh.uninstall_harness(proj)
    assert harness.exists() == preexisting
    assert (proj / "Assets/Harness.meta").exists() == preexisting
    assert ("/Game/Assets/Harness.meta" in exclude.read_text()) == preexisting
    if preexisting:
        assert (proj / "Assets/Harness.meta").read_text() == "existing meta"


@pytest.mark.skipif(not has_git(), reason="needs git")
def test_git_exclude_keeps_shared_header_for_other_project(proj, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    other = tmp_path / "Other"
    (other / "Assets").mkdir(parents=True)
    uh.install_harness(proj)
    uh.install_harness(other)
    uh.uninstall_harness(proj)
    text = (tmp_path / ".git/info/exclude").read_text()
    assert text.count(uh.EXCLUDE_HEADER) == 1 and "/Other/Assets/Harness/Headless/" in text
    assert "/Game/Assets/Harness/Headless/" not in text
    uh.uninstall_harness(other)
    assert uh.EXCLUDE_HEADER not in (tmp_path / ".git/info/exclude").read_text()


@pytest.mark.parametrize("rel", uh.FOLDERS)
def test_uninstall_refuses_symlinked_folders(proj, rel):
    uh.install_harness(proj)
    folder = proj / rel
    target = folder.with_name(folder.name + "-original")
    folder.rename(target)
    folder.symlink_to(target, target_is_directory=True)
    before = (ours(proj) / "HarnessCli.cs").read_bytes()
    result = uh.uninstall_harness(proj)
    assert not result["ok"] and result["removed"] == [] and "symlink" in result["message"]
    assert folder.is_symlink() and (ours(proj) / "HarnessCli.cs").read_bytes() == before


def test_refuses_to_overwrite_a_user_edited_file(proj):
    uh.install_harness(proj)
    edited = ours(proj) / "HarnessArgs.cs"
    edited.write_text(edited.read_text() + "\n// my tweak\n")
    st = uh.harness_status(proj)
    assert st["modified"] == ["HarnessArgs.cs"] and not st["outdated"]
    (ours(proj) / "HarnessCli.cs").unlink()  # even with a file missing, nothing is written
    r = uh.install_harness(proj, allow_upgrade=True)
    assert not r["ok"] and r["status"] == "modified" and "HarnessArgs.cs" in r["message"]
    assert "my tweak" in edited.read_text() and not (ours(proj) / "HarnessCli.cs").exists()
    # Uninstall keeps the edited file (and its folder), removes ours.
    u = uh.uninstall_harness(proj)
    assert u["kept"] == [f"{uh.HARNESS_DIR}/HarnessArgs.cs"] and edited.is_file()
    assert not (ours(proj) / "Harness.Headless.Editor.asmdef").exists()


def test_upgrades_an_older_version_only_with_consent(proj, monkeypatch):
    uh.install_harness(proj)
    old = b"// harness-version: 1\n// an older shipped HarnessCli\nnamespace Harness.Headless { class HarnessCli {} }\n"
    monkeypatch.setitem(uh.PREVIOUS, "HarnessCli.cs", {uh._digest(old)})
    (ours(proj) / "HarnessCli.cs").write_bytes(old)
    st = uh.harness_status(proj)
    assert st["files"]["HarnessCli.cs"] == "older" and st["outdated"] and st["version"] == 1
    r = uh.install_harness(proj)
    assert not r["ok"] and r["status"] == "needs_upgrade_consent" and (ours(proj) / "HarnessCli.cs").read_bytes() == old
    r = uh.install_harness(proj, allow_upgrade=True)
    assert r["ok"] and r["status"] == "upgraded" and r["written"] == [f"{uh.HARNESS_DIR}/HarnessCli.cs"]
    assert (ours(proj) / "HarnessCli.cs").read_bytes() == (TPL / "HarnessCli.cs").read_bytes()
    assert uh.harness_status(proj)["version"] == 2


def test_uninstall_removes_only_our_files(proj):
    feel = proj / "Assets/Harness/Feel"
    feel.mkdir(parents=True)
    (feel / "Juice.cs").write_text("class Juice {}\n")
    (proj / "Assets/Harness.meta").write_text("fileFormatVersion: 2\nguid: 0123\n")
    uh.install_harness(proj)
    assert (proj / "Assets/Harness.meta").read_text() == "fileFormatVersion: 2\nguid: 0123\n"  # never rewritten
    (ours(proj) / "Notes.txt").write_text("mine")
    u = uh.uninstall_harness(proj)
    assert (ours(proj) / "Notes.txt").is_file() and not (ours(proj) / "HarnessCli.cs").exists()
    assert not (ours(proj) / "HarnessCli.cs.meta").exists()
    (ours(proj) / "Notes.txt").unlink()
    u = uh.uninstall_harness(proj)
    assert not (proj / "Assets/Harness/Headless").exists() and not (proj / "Assets/Harness/Headless.meta").exists()
    assert (feel / "Juice.cs").is_file() and (proj / "Assets/Harness.meta").is_file()
    assert u["ok"]


def test_harness_present_matches_unity_sh(proj):
    assert not uh.harness_present(proj)
    d = proj / "Assets/Tools/Editor"
    d.mkdir(parents=True)
    (d / "MyCli.cs").write_text("namespace Harness.Headless { public static class HarnessCli {} }\n")
    assert uh.harness_present(proj)


@pytest.mark.parametrize("rel", ["Assets/Tools/MyCli.cs", "Packages/custom/Editor/MyCli.cs"])
async def test_external_harness_refuses_install_without_card(app, proj, fake_cli, rel):
    app.config.unity = {**app.config.unity, "backend": "mcp"}
    b = bridge(app)
    s = session(app, proj)
    await b.import_assets(s, [])  # remember a prior request for installation
    p = proj / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("namespace Harness.Headless { class HarnessCli {} }\n")
    r = await asyncio.wait_for(UT.install_harness_action(app, s), 2)
    assert r.status == "fail" and rel in r.summary
    assert not app.approvals.pending(s["id"])
    assert "install_harness" not in (await b.editor_state(s)).actions
    installed = uh.install_harness(proj)
    assert not installed["ok"] and rel in installed["message"]
    assert not ours(proj).exists() and p.read_text().endswith("class HarnessCli {} }\n")


def test_harness_scan_reads_only_first_64kb_and_stops_at_first_match(proj, monkeypatch):
    p = proj / "Assets/Game/Large.cs"
    p.write_bytes(b" " * 65536 + b"class HarnessCli {}")
    assert not uh.harness_present(proj)
    p.write_bytes(b"class HarnessCli {}" + b" " * 65536)
    original_open = Path.open
    reads = []

    class BoundedRead:
        def __enter__(self):
            self.f = original_open(p, "rb")
            return self

        def read(self, size=-1):
            reads.append(size)
            assert 0 < size <= 65536
            return self.f.read(size)

        def __exit__(self, *exc):
            self.f.close()

    def open_file(path, *args, **kwargs):
        return BoundedRead() if path == p else original_open(path, *args, **kwargs)

    def walk(top):
        if Path(top) == ours(proj):
            return
        yield str(p.parent), [], [p.name]
        pytest.fail("the harness scan continued after finding a class")

    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(uh.os, "walk", walk)
    assert uh.harness_present(proj) and reads == [65536]
    # Our installed path is checked before walking either project tree.
    ours(proj).mkdir(parents=True)
    (ours(proj) / uh.VERSION_FILE).write_text("class HarnessCli {}")
    reads.clear()
    assert uh.harness_present(proj) and reads == []


@pytest.mark.parametrize("op", ["import", "menu", "exec", "build", "compile"])
async def test_harness_probe_runs_off_event_loop(app, proj, fake_cli, monkeypatch, op):
    app.config.unity = {**app.config.unity, "backend": "mcp"}
    b = bridge(app)
    s = session(app, proj)
    loop_thread = threading.get_ident()
    probe_threads = []

    def present(root):
        probe_threads.append(threading.get_ident())
        return False

    monkeypatch.setattr(uh, "harness_present", present)
    calls = {
        "import": lambda: b.import_assets(s),
        "menu": lambda: b.menu_item(s, "Tools/Rebuild"),
        "exec": lambda: b.exec_method(s, "Harness.Headless.HarnessCli.Compile"),
        "build": lambda: b.build(s, target="macos", dev=True),
        "compile": lambda: b.compile(s, force=True),
    }
    r = await calls[op]()
    assert r.evidence["needs_harness"]
    assert probe_threads and all(t != loop_thread for t in probe_threads)


# ------------------------------------------------------------ needs_harness + install action


async def test_ops_that_need_harnesscli_say_needs_harness(app, proj, fake_cli):
    app.config.unity = {**app.config.unity, "backend": "mcp"}  # Editor closed → unity.sh (raw_batch)
    b = bridge(app)
    s = session(app, proj)
    st = await b.editor_state(s)
    assert "install_harness" not in st.actions and st.extra["harness"]["installed"] is False
    for r in (await b.import_assets(s, ["Assets/Game"]),
              await b.compile(s, force=True, source="tool"),
              await b.build(s, target="macos", dev=True),
              await b.exec_method(s, "Harness.Headless.HarnessCli.Compile"),
              await b.menu_item(s, "Tools/Rebuild Atlas")):
        assert r.status == "skipped" and r.summary.startswith("needs_harness:"), r.summary
        assert r.evidence["needs_harness"] is True and r.evidence["actions"] == ["install_harness"]
    assert app.approvals.pending(s["id"]) == []  # no card before the harness is there
    # The chip / state now offers the action (after an op asked for it).
    st = await b.editor_state(s)
    assert "install_harness" in st.actions and st.extra["harness"]["offer"]
    out = await UT.run_op(app, s, {"op": "import"})
    assert "needs_harness" in out.text and '"install_harness"' in out.text
    assert await b._needs_harness(proj, "x", "raw_batch") is not None
    app.config.unity = {**app.config.unity, "harness_scripts": "never"}
    assert await b._needs_harness(proj, "x", "raw_batch") is None
    assert "install_harness" not in (await b.editor_state(s)).actions


async def test_install_harness_action_asks_then_installs(app, proj, fake_cli):
    app.config.unity = {**app.config.unity, "backend": "mcp"}
    b = bridge(app)
    s = session(app, proj)
    await b.import_assets(s, [])
    t = asyncio.create_task(UT.run_op(app, s, {"op": "install_harness"}))
    (card,) = await wait_card(app, s["id"])
    assert card["kind"] == "unity" and card["payload"]["op"] == "install_harness"
    assert uh.HARNESS_DIR in card["payload"]["markdown"] and "info/exclude" in card["payload"]["markdown"]
    assert [x["id"] for x in card["payload"]["buttons"]] == ["once", "deny"]  # setup: no "always"
    app.approvals.resolve(card["id"], "approve")
    out = await t
    assert '"status": "pass"' in out.text and uh.harness_status(proj)["complete"]
    st = await b.editor_state(s)
    assert "install_harness" not in st.actions and st.extra["harness"]["installed"]
    assert await b._needs_harness(proj, "an asset import", "raw_batch") is None
    # Already current: no card.
    out = await UT.run_op(app, s, {"op": "install_harness"})
    assert "already installed" in out.text and not app.approvals.pending(s["id"])
    # An edited file: refused without a card.
    p = ours(proj) / "HarnessCli.cs"
    p.write_text(p.read_text() + "// edit\n")
    out = await UT.run_op(app, s, {"op": "install_harness"})
    assert out.is_error and "was changed" in out.text and not app.approvals.pending(s["id"])
    # Plan only mode never installs.
    plan = session(app, proj, mode="plan")
    assert "Plan only mode" in (await UT.run_op(app, plan, {"op": "install_harness"})).text


async def test_outdated_harness_offers_the_upgrade_with_consent(app, proj, fake_cli, monkeypatch):
    app.config.unity = {**app.config.unity, "backend": "mcp"}
    b = bridge(app)
    s = session(app, proj)
    uh.install_harness(proj)
    old = b"// harness-version: 1\nclass HarnessCli {}\n"
    monkeypatch.setitem(uh.PREVIOUS, "HarnessCli.cs", {uh._digest(old)})
    (ours(proj) / "HarnessCli.cs").write_bytes(old)
    assert "install_harness" in (await b.editor_state(s)).actions
    t = asyncio.create_task(UT.setup_action(app, s, "install_harness"))
    (card,) = await wait_card(app, s["id"])
    assert "from version 1 to 2" in card["payload"]["markdown"]
    app.approvals.resolve(card["id"], "approve")
    r = await t
    assert r.status == "pass" and "upgraded" in r.summary and uh.harness_status(proj)["version"] == 2


async def test_menu_runs_in_batch_through_unity_sh(app, proj, tmp_path, monkeypatch):
    """OP_ROUTES menu: cli_live or (Editor closed) unity.sh `menu` → HarnessCli.MenuItem."""
    bindir = tmp_path / "shbin"
    bindir.mkdir()
    rec = tmp_path / "sh-args.txt"
    sh = bindir / "unity.sh"
    sh.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" > {rec}\necho "[HARNESS] MENU OK $2"\n'
                  'echo "RESULT: OK menu $2 (log x)"; exit 0\n')
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr("gamedevworkstation.services.default_shell", lambda: "/bin/bash")
    app.config.unity = {**(app.config.unity or {}), "backend": "mcp"}
    b = bridge(app)
    s = session(app, proj)
    assert (await b.editor_state(s, "menu")).mode == "raw_batch"
    uh.install_harness(proj)
    t = asyncio.create_task(UT.run_op(app, s, {"op": "menu", "menu": "Tools/Rebuild Atlas"}))
    (card,) = await wait_card(app, s["id"])
    assert card["payload"]["op"] == "menu" and "Tools/Rebuild Atlas" in card["payload"]["markdown"]
    app.approvals.resolve(card["id"], "approve")
    out = await t
    assert '"status": "pass"' in out.text and '"route": "raw_batch"' in out.text
    assert rec.read_text().splitlines()[:2] == ["menu", "Tools/Rebuild Atlas"]
    assert (await b.menu_item(s, "no-slash")).status == "error"


async def test_batch_menu_requires_version_2(app, proj, fake_cli, monkeypatch):
    app.config.unity = {**app.config.unity, "backend": "mcp"}
    b = bridge(app)
    s = session(app, proj)
    uh.install_harness(proj)
    # Even an unrecognised/modified v1 script lacks the MenuItem entry point.
    (ours(proj) / "HarnessCli.cs").write_text("class HarnessCli {}\n")

    async def raw(*args, **kwargs):
        pytest.fail("menu must not run unity.sh with a version 1 harness")

    monkeypatch.setattr(b, "_raw", raw)
    r = await b.menu_item(s, "Tools/Rebuild Atlas")
    assert r.status == "skipped" and r.summary.startswith("needs_harness:")
    assert "upgrade" in r.summary.lower() and r.evidence["actions"] == ["install_harness"]
    assert r.evidence["harness"]["version"] == 1 and not app.approvals.pending(s["id"])


def test_unity_sh_menu_needs_harness_and_a_path(proj, tmp_path):
    """The real unity.sh: `menu` is a known command that needs HarnessCli (fake editor binary)."""
    ed = tmp_path / "Unity"
    ed.write_text("#!/bin/bash\nexit 0\n")
    ed.chmod(ed.stat().st_mode | stat.S_IEXEC)
    sh = Path(__file__).parents[1] / "skills/headless-ops/scripts/unity.sh"
    env = {**os.environ, "UNITY_PATH": str(ed)}
    r = subprocess.run(["bash", str(sh), "menu", "Tools/X", "--project", str(proj)], capture_output=True, text=True,
                       env=env, timeout=60)
    assert r.returncode == 3 and "HarnessCli.cs missing" in r.stdout
    uh.install_harness(proj)
    r = subprocess.run(["bash", str(sh), "menu", "NoSlash", "--project", str(proj)], capture_output=True, text=True,
                       env=env, timeout=60)
    assert r.returncode == 3 and "not a menu path" in r.stdout


# ------------------------------------------------------------------ case 15: clone mode


@pytest.fixture
def fake_copy(monkeypatch):
    """cp -cR / rsync -a --delete done in-process; every argv recorded."""
    calls: list[list[str]] = []

    async def run(argv, timeout_s):
        calls.append(list(argv))
        if argv[0] == uclone.CP:
            assert argv[1] == "-cR"
            shutil.copytree(argv[2], argv[3], symlinks=True)
        elif argv[0] == uclone.RSYNC:
            assert argv[1:3] == ["-a", "--delete"] and argv[3].endswith("/") and argv[4].endswith("/")
            shutil.rmtree(argv[4], ignore_errors=True)
            shutil.copytree(argv[3], argv[4], symlinks=True)
        else:
            raise AssertionError(argv)
        return 0, ""

    monkeypatch.setattr(uclone, "_exec", run)
    return calls


def open_editor_cli(app, fake_cli, policy="ask"):
    app.config.unity = {**app.config.unity, "backend": "cli", "clone_when_open": policy}
    fake_cli.set(status="none", run={"result": "pass"})  # the Editor holds the project, no Pipeline
    return bridge(app, open_=True)


def test_clone_dir_is_under_gdw_home(proj, tmp_path):
    d = uclone.clone_dir(proj)
    assert d.parent == tmp_path / "home" / "cache" / "unity-clones" and len(d.name) == 12


@pytest.mark.parametrize("first", [True, False])
@pytest.mark.parametrize("rel", ["Assets", "Packages", "ProjectSettings", "Assets/Game/Linked", "Packages/link.cs"])
async def test_clone_refuses_source_symlinks(proj, tmp_path, fake_copy, first, rel):
    if not first:
        await uclone.sync_clone(proj)
        fake_copy.clear()
    p = proj / rel
    # Top-level symlinks are refused even when their target is inside the project.
    if p.is_dir():
        target = proj / f"{p.name}-original"
        p.rename(target)
    else:
        target = tmp_path / "external"
        if rel.endswith(".cs"):
            target.write_text("class External {}")
        else:
            target.mkdir()
    p.symlink_to(target, target_is_directory=target.is_dir())
    with pytest.raises(uclone.CloneError) as exc:
        await uclone.sync_clone(proj)
    assert f"project uses symlinks ({rel}): running on a copy could write into the linked folder" in str(exc.value)
    assert fake_copy == []


@pytest.mark.parametrize("name", uclone.SYNC_DIRS)
async def test_clone_refuses_destination_symlinks(proj, tmp_path, fake_copy, name):
    await uclone.sync_clone(proj)
    dst = uclone.clone_dir(proj)
    (dst / name).rename(dst / f"{name}-original")
    outside = tmp_path / "linked-destination"
    outside.mkdir()
    (outside / "keep").write_text("untouched")
    (dst / name).symlink_to(outside, target_is_directory=True)
    fake_copy.clear()
    with pytest.raises(uclone.CloneError, match="project uses symlinks") as exc:
        await uclone.sync_clone(proj)
    assert name in str(exc.value) and fake_copy == []
    assert (outside / "keep").read_text() == "untouched"


async def test_clone_refuses_different_volume_before_copy(proj, fake_copy, monkeypatch):
    cache = uclone.clones_root()
    original_stat = os.stat

    def other_volume(path, *args, **kwargs):
        st = original_stat(path, *args, **kwargs)
        if Path(path) == cache:
            fields = list(st)
            fields[2] = st.st_dev + 1
            return os.stat_result(fields)
        return st

    monkeypatch.setattr(uclone.os, "stat", other_volume)
    with pytest.raises(uclone.CloneError) as exc:
        await uclone.sync_clone(proj)
    assert str(exc.value) == ("the project is on a different volume than the clone cache, "
                              "so an APFS clone would be a full copy")
    assert cache.is_dir() and fake_copy == [] and not uclone.clone_dir(proj).exists()


@pytest.mark.parametrize("marker", ["{broken", "[]", "null", '"text"', "42"])
async def test_corrupt_clone_marker_recopies(proj, fake_copy, marker):
    await uclone.sync_clone(proj)
    dst = uclone.clone_dir(proj)
    (dst / uclone.MARKER).write_text(marker)
    (dst / "leftover").write_text("stale")
    fake_copy.clear()
    r = await uclone.sync_clone(proj)
    assert r["first"] and fake_copy == [[uclone.CP, "-cR", str(proj), str(dst)]]
    assert not (dst / "leftover").exists()
    assert isinstance(json.loads((dst / uclone.MARKER).read_text()), dict)


async def test_clone_first_cp_then_rsync_three_folders(app, proj, fake_cli, fake_copy):
    b = open_editor_cli(app, fake_cli)
    s = session(app, proj)
    st = await b.editor_state(s)
    assert st.mode == "unavailable" and "use_clone" in st.actions
    (proj / "Temp").mkdir()
    (proj / "Temp/UnityLockfile").write_text("")
    (proj / "Library").mkdir()
    (proj / "Library/ArtifactDB").write_text("warm")
    r = await b.compile(s, consent=consent(app, proj), force_route="clone")
    clone = uclone.clone_dir(proj)
    assert r.status == "pass" and r.mode == "cli_batch" and r.evidence["clone"] is True
    assert "on a copy of the files on disk (unsaved Editor changes not included)" in r.summary
    assert fake_copy == [[uclone.CP, "-cR", str(proj), str(clone)]]
    assert (clone / "Library/ArtifactDB").read_text() == "warm" and not (clone / "Temp").exists()
    (run,) = fake_cli.calls_of("run")
    assert run[1] == str(clone)  # Unity ran on the copy, never on the open project
    assert str(proj) not in " ".join(run)
    # Later runs: rsync of Assets/, Packages/, ProjectSettings/ only.
    (proj / "Assets/Game/New.cs").write_text("class New {}\n")
    (proj / "Assets/Game/Hit.cs").unlink()
    fake_copy.clear()
    r = await b.compile(s, consent=consent(app, proj), force_route="clone")
    assert r.status == "pass" and r.evidence["clone"] is True and r.evidence["clone_first"] is False
    assert [c[0] for c in fake_copy] == [uclone.RSYNC] * 3
    assert [c[3] for c in fake_copy] == [f"{proj / d}/" for d in ("Assets", "Packages", "ProjectSettings")]
    assert [c[4] for c in fake_copy] == [f"{clone / d}/" for d in ("Assets", "Packages", "ProjectSettings")]
    assert (clone / "Assets/Game/New.cs").is_file() and not (clone / "Assets/Game/Hit.cs").exists()


async def test_forced_compile_on_clone_discloses_regular_compile(app, proj, fake_cli, fake_copy):
    b = open_editor_cli(app, fake_cli)
    r = await b.compile(session(app, proj), force=True, consent=consent(app, proj), force_route="clone")
    assert r.status == "pass" and r.evidence["clone"]
    assert "force=True is not supported on the clone path" in r.summary and "regular batch compile" in r.summary


async def test_bad_route_probe_budget_uses_default(app, proj, fake_cli, monkeypatch):
    bridge(app)
    app.config.hooks["unity_route_probe_s"] = "not a number"
    original_wait_for = asyncio.wait_for
    budgets = []

    async def wait_for(awaitable, timeout):
        budgets.append(timeout)
        return await original_wait_for(awaitable, timeout)

    monkeypatch.setattr(H.asyncio, "wait_for", wait_for)
    result = await H.get_engine(app).unity_route(session(app, proj))
    assert H.UNITY_ROUTE_PROBE_S in budgets and result["route"] != "unknown"


async def test_clone_policy_always_never_and_tests(app, proj, fake_cli, fake_copy):
    H.get_engine(app).enable_preset(proj)
    b = open_editor_cli(app, fake_cli, "always")
    s = session(app, proj)
    st = await b.editor_state(s)
    assert st.mode == "cli_batch" and st.extra["clone"] is True and st.actions == []
    assert "unsaved Editor changes not included" in st.reason
    assert (await b.editor_state(s, "build")).mode == "unavailable"  # only compile/tests run on a copy
    out = await UT.run_op(app, s, {"op": "compile"})  # the agent tool: no card (gate consent), on the copy
    assert '"status": "pass"' in out.text and '"clone": true' in out.text and not app.approvals.pending(s["id"])
    (l1,) = app.extensions["ladder"].evidence(proj, levels=["L1"])
    assert l1["detail"]["clone"] is True and l1["status"] == "pass"
    fake_cli.set(test={"result": "pass"})
    r = await b.run_tests(s, consent=consent(app, proj))
    assert r.status == "pass" and r.evidence["clone"] is True and r.evidence["xml"].startswith(str(uclone.clone_dir(proj)))
    UT.record_evidence(app, s, "test", r)
    (l2,) = app.extensions["ladder"].evidence(proj, levels=["L2"])
    assert l2["detail"]["clone"] is True
    # never: neither offered nor used, even when asked for.
    app.config.unity = {**app.config.unity, "clone_when_open": "never"}
    st = await b.editor_state(s)
    assert st.mode == "unavailable" and "use_clone" not in st.actions
    r = await b.compile(s, consent=consent(app, proj), force_route="clone")
    assert r.status == "skipped" and "never" in r.summary


async def test_gate_never_clones_under_ask(app, proj, fake_cli, fake_copy):
    b = open_editor_cli(app, fake_cli, "ask")
    r = await b.compile(session(app, proj), consent=consent(app, proj))
    assert r.status == "skipped" and "use_clone" in r.evidence["state"]["actions"] and fake_copy == []
    assert fake_cli.calls_of("run") == []


async def test_clone_failure_is_skipped_not_run(app, proj, fake_cli, monkeypatch):
    async def fail(argv, timeout_s):
        return 1, "cp: clonefile failed: Operation not supported"

    monkeypatch.setattr(uclone, "_exec", fail)
    b = open_editor_cli(app, fake_cli)
    r = await b.compile(session(app, proj), consent=consent(app, proj), force_route="clone")
    assert r.status == "skipped" and "clonefile failed" in r.summary and fake_cli.calls_of("run") == []
    assert not uclone.clone_dir(proj).exists()


def test_api_actions_accept_use_clone_and_install_harness(tmp_path, proj, fake_cli, fake_copy):
    """The actions run in the background (cards are covered above; here the routing only)."""
    import time

    from fastapi.testclient import TestClient

    from gamedevworkstation.app import AppState
    from gamedevworkstation.server import create_app

    st = AppState(db_path=tmp_path / "api.db")
    st.config.unity = {"cli_path": str(fake_cli.path), "editor_root": str(tmp_path / "Editors"), "backend": "cli"}
    fake_cli.set(status="none", run={"result": "pass"})
    h = {"Authorization": "Bearer t"}
    with TestClient(create_app("t", st)) as c:
        b = bridge(st, open_=True)
        s = st.store.create(folder=str(proj), mode="ask")
        b.allow_op(proj, "compile")  # "always allow compile in this project": no card
        r = c.get("/api/unity/state", params={"session_id": s["id"]}, headers=h).json()
        assert "use_clone" in r["actions"] and r["harness"]["installed"] is False
        r = c.post("/api/unity/actions/use_clone", json={"session_id": s["id"]}, headers=h).json()
        assert r["status"] == "pending" and "copy" in r["message"]
        for _ in range(300):
            if fake_cli.calls_of("run") and fake_copy:
                break
            time.sleep(0.02)
        assert fake_cli.calls_of("run")[0][1] == str(uclone.clone_dir(proj))
        st.config.unity = {**st.config.unity, "harness_scripts": "never"}
        r = c.post("/api/unity/actions/install_harness", json={"session_id": s["id"]}, headers=h).json()
        assert r["status"] == "pending"
        assert c.post("/api/unity/actions/nope", json={"session_id": s["id"]}, headers=h).status_code == 404
