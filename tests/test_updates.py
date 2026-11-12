"""Versions and updates: version compare, latest.json detection, install guard, the
swap-and-relaunch helper against a fake bundle, pruning, and scripts/version.py."""
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation import __version__
from gamedevworkstation.app import AppState
from gamedevworkstation.features import updates as U
from gamedevworkstation.server import create_app

ROOT = Path(__file__).resolve().parents[1]
H = {"Authorization": "Bearer t"}


def make_bundle(app: Path, version: str, exe: str = "#!/bin/bash\nsleep 30\n") -> Path:
    (app / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    with (app / "Contents" / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleShortVersionString": version, "CFBundleIdentifier": U.BUNDLE_ID,
                       "CFBundleExecutable": "GameDevWorkstation"}, f)
    b = app / "Contents" / "MacOS" / "GameDevWorkstation"
    b.write_text(exe)
    b.chmod(0o755)
    return app


def publish(d: Path, version: str, notes: str = "Notes") -> dict:
    make_bundle(d / version / "GameDevWorkstation.app", version)
    rel = {"version": version, "built_at": "2026-11-06T10:00:00+00:00", "git_commit": "abc1234", "notes": notes}
    U.write_json_atomic(d / version / "release.json", rel)
    U.write_json_atomic(d / "latest.json", {**rel, "app": f"{version}/GameDevWorkstation.app"})
    return rel


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "t.db")
    with TestClient(create_app("t", s)) as c:
        yield c, s, Path(os.environ["GDW_UPDATES_DIR"])


def events(s, type_="update.available"):
    return [json.loads(r["data"]) for r in s.db.all("SELECT data FROM events WHERE type=? ORDER BY seq", [type_])]


# ------------------------------------------------------------------ versions


def test_version_compare():
    assert U.is_newer("0.2.0", "0.1.9")
    assert U.is_newer("1.0.0", "0.99.99")
    assert U.is_newer("0.10.0", "0.9.0")  # numeric, not string order
    assert U.is_newer("1.0.0", "1.0.0-rc.2")  # a release beats its pre-releases
    assert U.is_newer("1.0.0-rc.10", "1.0.0-rc.2")
    assert U.is_newer("v1.2.4", "1.2.3")
    assert not U.is_newer("1.2.3", "1.2.3")
    assert not U.is_newer("garbage", "0.1.0") and not U.is_newer("0.2.0", None)


def test_running_version_is_reported(env):
    c, _, _ = env
    assert c.get("/health").json() == {"ok": True, "version": __version__}
    v = c.get("/api/state", headers=H).json()["version"]
    assert v["version"] == __version__ and v["frozen"] is False
    assert (ROOT / "VERSION").read_text().strip() == __version__


# ------------------------------------------------------------------ detection


def test_latest_json_detected_and_announced_once(env):
    c, s, d = env
    assert c.get("/api/state", headers=H).json()["update"] is None
    publish(d, "99.0.0", notes="- Shiny")
    up = s.extensions["updates"]
    upd = up.check()
    assert upd == {"current": __version__, "latest": "99.0.0", "notes": "- Shiny",
                   "built_at": "2026-11-06T10:00:00+00:00", "git_commit": "abc1234",
                   "install_supported": False}  # tests run from source
    assert len(events(s)) == 1
    up.check()  # unchanged file: not even parsed again
    time.sleep(0.01)
    (d / "latest.json").write_text((d / "latest.json").read_text() + " ")  # touched, same version
    up.check()
    assert c.post("/api/updates/check", headers=H).json()["update"]["latest"] == "99.0.0"
    assert len(events(s)) == 1  # once per version
    assert c.get("/api/state", headers=H).json()["update"]["latest"] == "99.0.0"
    st = c.get("/api/updates", headers=H).json()
    assert [r["version"] for r in st["history"]] == ["99.0.0"] and st["dir_exists"]
    # A newer one is announced again.
    publish(d, "99.1.0")
    up.check()
    assert [e["latest"] for e in events(s)] == ["99.0.0", "99.1.0"]
    # Same version after a restart (new Updater, same database): no second announcement.
    U.Updater(s).check()
    assert len(events(s)) == 2


def test_older_or_same_version_is_not_an_update(env):
    _, s, d = env
    publish(d, __version__)
    assert s.extensions["updates"].check() is None and not events(s)


def test_invalid_or_half_written_latest_json_is_ignored(env):
    _, s, d = env
    up = s.extensions["updates"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text('{"version": "99.0.0", "app": "99.0.0/Work')  # cut off mid-write
    assert up.check() is None
    (d / "latest.json").write_text('{"version": "not-a-version"}')
    assert up.check() is None
    # Advertised before the bundle finished copying: ignored.
    (d / "latest.json").write_text(json.dumps({"version": "99.0.0", "app": "99.0.0/GameDevWorkstation.app"}))
    assert up.check() is None
    # Pointing outside the updates folder: ignored.
    make_bundle(d.parent / "elsewhere" / "GameDevWorkstation.app", "99.0.0")
    (d / "latest.json").write_text(json.dumps({"version": "99.0.0", "app": "../elsewhere/GameDevWorkstation.app"}))
    assert up.check() is None
    assert not events(s)
    # latest.json first, the bundle a little later (a synced folder): found without a rewrite.
    (d / "latest.json").write_text(json.dumps({"version": "99.0.0", "app": "99.0.0/GameDevWorkstation.app"}))
    assert up.check() is None
    make_bundle(d / "99.0.0" / "GameDevWorkstation.app", "99.0.0")
    assert up.check()["latest"] == "99.0.0"
    # Withdrawn: the banner is told to go away.
    (d / "latest.json").unlink()
    assert up.check() is None
    assert events(s, "update.cleared") == [{"version": "99.0.0"}]


def test_missing_folder_is_fine(env):
    c, s, d = env
    assert not d.exists()
    st = c.get("/api/updates", headers=H).json()
    assert st["dir_exists"] is False and st["update"] is None and st["history"] == []


# ------------------------------------------------------------------ install


def test_install_refused_when_not_frozen(env):
    c, s, d = env
    publish(d, "99.0.0")
    st = c.get("/api/updates", headers=H).json()
    assert st["install_supported"] is False and st["reason"]
    for path in ("/api/updates/install", "/api/updates/rollback"):
        r = c.post(path, json={}, headers=H)
        assert r.status_code == 400
        if sys.platform == "darwin":
            assert "make live" in r.json()["detail"]
    assert c.post("/api/updates/install", json={"version": ["x"]}, headers=H).json()["detail"].startswith("version must")
    assert s.extensions["updates"].installing is None
    assert not (d / ".previous").exists()


def test_helper_script_content(tmp_path):
    script = U.helper_script(app_pid=4242, bundle=Path("/Applications/Work space.app"),
                             stage=Path("/Applications/.Work space.app.updating"),
                             backup=tmp_path / ".previous" / "GameDevWorkstation-0.1.0.app")
    assert script.startswith("#!/bin/bash")
    assert "APP_PID=4242" in script
    assert "BUNDLE='/Applications/Work space.app'" in script  # quoted for the shell
    assert 'tell application id \\"$BUNDLE_ID\\" to quit' in script
    assert "BUNDLE_ID=dev.local.gamedevworkstation" in script
    assert '"${WS_OSASCRIPT:-/usr/bin/osascript}"' in script and '"${WS_OPEN:-/usr/bin/open}"' in script
    assert 'rm -rf "${BUNDLE:?}"' in script  # never rm -rf an empty variable
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)


def _fake_app_process() -> int:
    """A process that isn't our child (so it never lingers as a zombie once killed)."""
    out = subprocess.run(["bash", "-c", "sleep 120 >/dev/null 2>&1 & echo $!"], capture_output=True, text=True)
    return int(out.stdout.strip())


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _stubs(tmp_path: Path, *, quit_ok: bool, pid: int) -> tuple[dict, Path]:
    calls = tmp_path / "calls.log"
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    stubs = {
        "osascript": f'#!/bin/bash\necho "osascript $*" >> "{calls}"\n' + (f"kill {pid}\n" if quit_ok else "exit 1\n"),
        # Like `open`: start the bundle's executable in the background.
        "open": f'#!/bin/bash\necho "open $1" >> "{calls}"\nfor f in "$1"/Contents/MacOS/*; do nohup "$f" >/dev/null 2>&1 & done\n',
        "xattr": f'#!/bin/bash\necho "xattr $*" >> "{calls}"\n',
    }
    for name, body in stubs.items():
        (bin_ / name).write_text(body)
        (bin_ / name).chmod(0o755)
    env = {**os.environ, "WS_OSASCRIPT": str(bin_ / "osascript"), "WS_OPEN": str(bin_ / "open"),
           "WS_XATTR": str(bin_ / "xattr"), "WS_START_DELAY": "0", "WS_QUIT_TIMEOUT": "5", "WS_BACKEND_WAIT": "0",
           "WS_LAUNCH_TIMEOUT": "3", "WS_LAUNCH_SETTLE": "0.5"}
    return env, calls


def _version(app: Path) -> str:
    return U.bundle_info(app)["version"]


@pytest.mark.skipif(sys.platform != "darwin", reason="uses macOS ps")
def test_helper_swaps_bundle_and_relaunches(tmp_path):
    apps, upd = tmp_path / "Applications", tmp_path / "updates"
    bundle = make_bundle(apps / "GameDevWorkstation.app", "0.1.0", "#!/bin/bash\nexit 0\n")
    make_bundle(upd / "0.2.0" / "GameDevWorkstation.app", "0.2.0")
    stage = U.stage_path(bundle)
    U.copy_bundle(upd / "0.2.0" / "GameDevWorkstation.app", stage)
    make_bundle(upd / ".previous" / "GameDevWorkstation-0.0.9.app", "0.0.9")  # an older backup gets replaced
    backup = upd / ".previous" / "GameDevWorkstation-0.1.0.app"
    pid = _fake_app_process()
    env, calls = _stubs(tmp_path, quit_ok=True, pid=pid)
    script = tmp_path / "helper.sh"
    script.write_text(U.helper_script(app_pid=pid, bundle=bundle, stage=stage, backup=backup))
    try:
        r = subprocess.run(["/bin/bash", str(script)], env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        assert not _alive(pid)
        assert _version(bundle) == "0.2.0" and _version(backup) == "0.1.0"
        assert not stage.exists() and not (upd / ".previous" / "GameDevWorkstation-0.0.9.app").exists()
        log = calls.read_text()
        assert 'osascript -e tell application id "dev.local.gamedevworkstation" to quit' in log
        assert f"xattr -cr {bundle}" in log and f"open {bundle}" in log
        assert "TERM" not in r.stdout  # it quit when asked
    finally:
        subprocess.run(["pkill", "-f", str(tmp_path)], check=False)
        if _alive(pid):
            os.kill(pid, 9)


@pytest.mark.skipif(sys.platform != "darwin", reason="uses macOS ps")
def test_helper_restores_previous_version_when_new_one_fails(tmp_path):
    apps, upd = tmp_path / "Applications", tmp_path / "updates"
    bundle = make_bundle(apps / "GameDevWorkstation.app", "0.1.0", "#!/bin/bash\nexit 0\n")
    broken = make_bundle(tmp_path / "new" / "GameDevWorkstation.app", "0.2.0", "#!/bin/bash\nexit 1\n")  # crashes on launch
    stage = U.stage_path(bundle)
    U.copy_bundle(broken, stage)
    make_bundle(upd / ".previous" / "GameDevWorkstation-0.0.9.app", "0.0.9")
    backup = upd / ".previous" / "GameDevWorkstation-0.1.0.app"
    pid = _fake_app_process()
    env, calls = _stubs(tmp_path, quit_ok=False, pid=pid)  # quit request fails → TERM
    env["WS_LAUNCH_TIMEOUT"] = "1"
    env["WS_QUIT_TIMEOUT"] = "1"  # a failed quit request still waits (up to this) before TERM
    script = tmp_path / "helper.sh"
    script.write_text(U.helper_script(app_pid=pid, bundle=bundle, stage=stage, backup=backup))
    try:
        r = subprocess.run(["/bin/bash", str(script)], env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "quit request failed; waiting briefly" in r.stdout and "sending TERM" in r.stdout
        assert "restoring the previous version" in r.stdout
        assert not _alive(pid)
        assert _version(bundle) == "0.1.0"  # old app back in place
        assert not backup.exists() and not stage.exists()
        assert (upd / ".previous" / "GameDevWorkstation-0.0.9.app").exists()  # untouched on failure
        assert calls.read_text().count(f"open {bundle}") == 2  # new (failed), then old again
    finally:
        subprocess.run(["pkill", "-f", str(tmp_path)], check=False)
        if _alive(pid):
            os.kill(pid, 9)


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("codesign"), reason="macOS app bundles")
def test_install_end_to_end_with_a_fake_frozen_app(env, tmp_path, monkeypatch):
    """POST /api/updates/install from a backend that believes it runs inside a (fake) app
    bundle: validates + stages the new bundle, answers, and the detached helper swaps it in."""
    from gamedevworkstation.config import logs_dir

    c, s, d = env
    bundle = make_bundle(tmp_path / "Applications" / "GameDevWorkstation.app", __version__, "#!/bin/bash\nexit 0\n").resolve()
    exe = bundle / "Contents" / "Resources" / "backend" / "gamedevworkstation-backend"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    publish(d, "99.0.0", notes="- Big one")
    for app in (bundle, d / "99.0.0" / "GameDevWorkstation.app"):  # ad-hoc signed, like the real builds
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True, capture_output=True)
    pid = _fake_app_process()
    stub_env, calls = _stubs(tmp_path, quit_ok=True, pid=pid)
    for k, v in stub_env.items():
        if k.startswith("WS_"):
            monkeypatch.setenv(k, v)
    monkeypatch.setenv("GDW_PARENT_PID", str(pid))
    monkeypatch.setattr(U, "frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", str(exe))
    try:
        st = c.get("/api/updates", headers=H).json()
        assert st["install_supported"], st["reason"]
        assert st["bundle_path"] == str(bundle)
        r = c.post("/api/updates/install", json={}, headers=H)
        assert r.status_code == 200, r.text
        assert r.json()["version"] == "99.0.0"
        assert c.post("/api/updates/install", json={}, headers=H).status_code == 409  # one at a time
        assert events(s, "update.installing")[0]["version"] == "99.0.0"
        backup = d / ".previous" / f"GameDevWorkstation-{__version__}.app"
        log = logs_dir() / "update.log"

        def wait_for(version: str, n_done: int) -> None:
            for _ in range(300):
                if (U.bundle_info(bundle) or {}).get("version") == version and log.read_text().count("done;") >= n_done:
                    return
                time.sleep(0.1)

        wait_for("99.0.0", 1)
        assert _version(bundle) == "99.0.0" and _version(backup) == __version__
        assert not _alive(pid) and not U.stage_path(bundle).exists()
        assert f"open {bundle}" in calls.read_text()
        assert U.previous_bundle(d)["version"] == __version__  # what "Roll back" would install

        # Roll back (as the new app would): the old version returns, 99.0.0 becomes the backup.
        s.extensions["updates"].installing = None
        pid = _fake_app_process()
        monkeypatch.setenv("GDW_PARENT_PID", str(pid))
        monkeypatch.setenv("WS_OSASCRIPT", "/usr/bin/false")  # quit request fails: TERM instead
        monkeypatch.setenv("WS_QUIT_TIMEOUT", "1")
        r = c.post("/api/updates/rollback", headers=H)
        assert r.status_code == 200 and r.json()["version"] == __version__, r.text
        wait_for(__version__, 2)
        assert _version(bundle) == __version__ and not _alive(pid)
        assert [p.name for p in (d / ".previous").iterdir()] == ["GameDevWorkstation-99.0.0.app"]
    finally:
        subprocess.run(["pkill", "-f", str(tmp_path)], check=False)
        if _alive(pid):
            os.kill(pid, 9)


def test_helper_does_nothing_without_a_staged_copy(tmp_path):
    bundle = make_bundle(tmp_path / "GameDevWorkstation.app", "0.1.0")
    script = tmp_path / "helper.sh"
    script.write_text(U.helper_script(app_pid=999999, bundle=bundle, stage=tmp_path / "missing",
                                      backup=tmp_path / "prev" / "GameDevWorkstation-0.1.0.app"))
    r = subprocess.run(["/bin/bash", str(script)], env={**os.environ, "WS_OPEN": "/bin/false", "WS_START_DELAY": "0"},
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "nothing changed" in r.stdout
    assert _version(bundle) == "0.1.0" and not (tmp_path / "prev").exists()


# ------------------------------------------------------------------ release folder


def test_prune_keeps_newest_latest_and_installed(tmp_path):
    d = tmp_path / "updates"
    for v in ("0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0"):
        publish(d, v)
    (d / "notes").mkdir()  # not a release: never touched
    make_bundle(d / ".previous" / "GameDevWorkstation-0.0.1.app", "0.0.1")
    removed = U.prune(d, keep=2, protect={"0.1.0"})
    assert sorted(removed) == ["0.2.0", "0.3.0"]
    assert [r["version"] for r in U.history(d)] == ["0.5.0", "0.4.0", "0.1.0"]
    assert (d / "notes").is_dir() and (d / ".previous" / "GameDevWorkstation-0.0.1.app").is_dir()
    assert U.previous_bundle(d)["version"] == "0.0.1"


def test_installed_migrates_old_single_record(tmp_path):
    d = tmp_path / "updates"
    app = make_bundle(tmp_path / "Applications" / "GameDevWorkstation.app", "0.2.0")
    U.write_json_atomic(d / "installed.json", {"version": "0.2.0", "bundle": str(app), "at": 1.0})
    assert U.read_installs(d) == {str(app): {"version": "0.2.0", "at": 1.0}}
    dev = make_bundle(tmp_path / "wt" / "dist" / "GameDevWorkstation.app", "0.3.0")
    U.record_install(d, dev, "0.3.0", at=2.0)
    data = json.loads((d / "installed.json").read_text())
    assert data == {"installs": {str(app): {"version": "0.2.0", "at": 1.0}, str(dev): {"version": "0.3.0", "at": 2.0}}}


def test_installed_ignores_and_drops_deleted_bundles(tmp_path):
    d = tmp_path / "updates"
    gone = tmp_path / "scratch" / "dist" / "GameDevWorkstation.app"
    U.write_json_atomic(d / "installed.json", {"version": "0.3.0", "bundle": str(gone), "at": 1.0})  # old format
    assert U.read_installs(d) == {} and U.installed_versions(d) == set()
    app = make_bundle(tmp_path / "Applications" / "GameDevWorkstation.app", "0.2.0")
    U.record_install(d, app, "0.2.0")
    assert list(json.loads((d / "installed.json").read_text())["installs"]) == [str(app)]
    shutil.rmtree(app)
    assert U.installed_versions(d) == set()
    (d / "installed.json").write_text("{not json")  # unreadable: treated as empty, never a crash
    assert U.read_installs(d) == {}


def test_dev_launch_does_not_unprotect_the_applications_version(tmp_path):
    d = tmp_path / "updates"
    for v in ("0.1.0", "0.2.0", "0.3.0", "0.4.0"):
        publish(d, v)
    real = make_bundle(tmp_path / "Applications" / "GameDevWorkstation.app", "0.2.0")
    dev = make_bundle(tmp_path / "wt" / "dist" / "GameDevWorkstation.app", "0.3.0")
    U.record_install(d, real, "0.2.0")
    U.record_install(d, dev, "0.3.0")  # a later test launch must not replace the real app's entry
    assert U.installed_versions(d) == {"0.2.0", "0.3.0"}
    shutil.rmtree(dev.parent)  # the scratch worktree goes away
    removed = U.prune(d, keep=1, protect=U.installed_versions(d))
    assert sorted(removed) == ["0.1.0", "0.3.0"]
    assert [r["version"] for r in U.history(d)] == ["0.4.0", "0.2.0"]


def test_prune_keeps_newest_and_every_live_installed_version(tmp_path):
    d = tmp_path / "updates"
    for v in ("0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0"):
        publish(d, v)
    for i, v in enumerate(("0.1.0", "0.3.0")):
        U.record_install(d, make_bundle(tmp_path / f"loc{i}" / "GameDevWorkstation.app", v), v)
    U.record_install(d, tmp_path / "deleted" / "GameDevWorkstation.app", "0.2.0")  # never existed: ignored
    removed = U.prune(d, keep=1, protect=U.installed_versions(d))
    assert sorted(removed) == ["0.2.0", "0.4.0"]
    assert [r["version"] for r in U.history(d)] == ["0.5.0", "0.3.0", "0.1.0"]


def test_installed_version_read_from_the_bundle_itself(tmp_path):
    d = tmp_path / "updates"
    app = make_bundle(tmp_path / "GameDevWorkstation.app", "0.2.0")
    U.record_install(d, app, "0.2.0")
    make_bundle(app, "0.6.0")  # replaced in place since it last started
    assert U.installed_versions(d) == {"0.6.0"}


def test_record_install_concurrent_writers_keep_every_entry(tmp_path):
    import threading
    d = tmp_path / "updates"
    apps = [make_bundle(tmp_path / f"a{i}" / "GameDevWorkstation.app", f"0.{i}.0") for i in range(8)]
    ts = [threading.Thread(target=U.record_install, args=(d, a, f"0.{i}.0")) for i, a in enumerate(apps)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert set(U.read_installs(d)) == {str(a) for a in apps}
    assert sorted(f.name for f in d.iterdir()) == [".installed.json.lock", "installed.json"]  # no temp files left


def test_status_reports_this_bundles_own_entry(env, monkeypatch, tmp_path):
    c, s, d = env
    d.mkdir(parents=True, exist_ok=True)
    other = make_bundle(tmp_path / "Applications" / "GameDevWorkstation.app", "0.0.9")
    U.record_install(d, other, "0.0.9", at=1.0)
    mine = make_bundle(tmp_path / "dist" / "GameDevWorkstation.app", __version__)
    monkeypatch.setattr(U, "running_bundle", lambda: mine)
    s.extensions["updates"].record_installed()
    st = c.get("/api/updates", headers=H).json()
    assert st["bundle_path"] == str(mine) and st["installed"]["version"] == __version__
    assert set(U.read_installs(d)) == {str(other), str(mine)}


def test_write_json_atomic_leaves_no_temp_files(tmp_path):
    p = tmp_path / "x" / "latest.json"
    U.write_json_atomic(p, {"version": "1.0.0"})
    U.write_json_atomic(p, {"version": "1.0.1"})
    assert json.loads(p.read_text()) == {"version": "1.0.1"}
    assert [f.name for f in p.parent.iterdir()] == ["latest.json"]


# ------------------------------------------------------------------ scripts/version.py

VERSIONED = ["VERSION", "pyproject.toml", "uv.lock", "backend/gamedevworkstation/__init__.py", "frontend/package.json",
             "frontend/package-lock.json", "src-tauri/tauri.conf.json", "src-tauri/Cargo.toml", "src-tauri/Cargo.lock"]


def _run_version(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "version.py"), "--root", str(root), *args],
                          capture_output=True, text=True)


def test_version_script_bumps_every_file(tmp_path):
    for rel in VERSIONED:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    old = (ROOT / "VERSION").read_text().strip()
    assert _run_version(tmp_path, "check").returncode == 0
    major, minor, _ = (int(x) for x in old.split("-")[0].split("."))
    r = _run_version(tmp_path, "bump", "minor")
    new = f"{major}.{minor + 1}.0"
    assert r.returncode == 0 and r.stdout.strip() == new, r.stderr
    assert _run_version(tmp_path, "check").returncode == 0
    assert _run_version(tmp_path, "show").stdout.strip() == new
    assert f'__version__ = "{new}"' in (tmp_path / "backend/gamedevworkstation/__init__.py").read_text()
    assert json.loads((tmp_path / "frontend/package.json").read_text())["version"] == new
    lock = json.loads((tmp_path / "frontend/package-lock.json").read_text())
    assert lock["version"] == new and lock["packages"][""]["version"] == new
    assert json.loads((tmp_path / "src-tauri/tauri.conf.json").read_text())["version"] == new
    # Only the version lines changed; dependency versions are untouched.
    for rel in VERSIONED[1:]:
        before, after = (ROOT / rel).read_text().splitlines(), (tmp_path / rel).read_text().splitlines()
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        assert len(before) == len(after) and changed, rel
        assert all(old in a and new in b for a, b in changed), (rel, changed)
        assert len(changed) == (2 if rel == "frontend/package-lock.json" else 1), (rel, changed)
    assert _run_version(tmp_path, "set", "2.0.0-rc.1").stdout.strip() == "2.0.0-rc.1"
    assert _run_version(tmp_path, "bump", "patch").stdout.strip() == "2.0.0"
    assert _run_version(tmp_path, "set", "nope").returncode != 0
    (tmp_path / "src-tauri/tauri.conf.json").write_text(
        (tmp_path / "src-tauri/tauri.conf.json").read_text().replace('"2.0.0"', '"9.9.9"', 1))
    bad = _run_version(tmp_path, "check")
    assert bad.returncode == 1 and "tauri.conf.json: 9.9.9" in bad.stderr
