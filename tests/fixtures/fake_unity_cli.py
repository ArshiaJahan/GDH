"""A fake official Unity CLI (`unity`) for tests: installed as an executable `unity` in a tmp bin dir
(see tests/test_unity_cli.py install_fake_cli). Never touches a real Unity.

Behaviour comes from the JSON file named by $FAKE_UNITY_SCENARIO, keyed by subcommand; every call
is appended to calls.jsonl next to it. Envelopes mimic CLI 1.0.0-beta.13 ({success, command, data,
errors: [{code, message}], warnings}); the Editor log streams to stderr like the real CLI under
--format json.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCN_PATH = Path(os.environ.get("FAKE_UNITY_SCENARIO", "/nonexistent"))
SCN = json.loads(SCN_PATH.read_text()) if SCN_PATH.is_file() else {}
ARGV = sys.argv[1:]


def record() -> None:
    with (SCN_PATH.parent / "calls.jsonl").open("a") as f:
        f.write(json.dumps(ARGV) + "\n")


def opt(name: str, default=None):
    head = ARGV[:ARGV.index("--")] if "--" in ARGV else ARGV
    for i, a in enumerate(head[:-1]):
        if a == name:
            return head[i + 1]
    return default


def after_fence() -> list:
    return ARGV[ARGV.index("--") + 1:] if "--" in ARGV else []


def env(command: str, data=None, errors=None, code: int = 0) -> None:
    print(json.dumps({"success": code == 0, "command": command, "data": data,
                      "errors": [{"code": c, "message": m} for c, m in (errors or [])], "warnings": []}))
    sys.stdout.flush()
    sys.exit(code)


def stream(lines, delay: float = 0.05) -> None:
    for ln in lines:
        sys.stderr.write(ln + "\n")
        sys.stderr.flush()
        time.sleep(delay)


def nunit(path: Path, passed: list, failed: list) -> None:
    cases = "".join(f'<test-case name="{n.rsplit(".", 1)[-1]}" fullname="{n}" result="Passed"/>' for n in passed)
    cases += "".join(f'<test-case name="{n.rsplit(".", 1)[-1]}" fullname="{n}" result="Failed">'
                     f'<failure><message>boom</message></failure></test-case>' for n in failed)
    total = len(passed) + len(failed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'<?xml version="1.0"?><test-run total="{total}" passed="{len(passed)}" failed="{len(failed)}" '
                    f'skipped="0"><test-suite>{cases}</test-suite></test-run>')


def grandchild(project: str) -> None:
    """A fake batch-mode Unity in its own session (as if the CLI had setsid'd its Editor)."""
    ed = SCN_PATH.parent / "FakeEditor" / "Unity.app" / "Contents" / "MacOS" / "Unity"
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", str(ed), "-batchmode",
                          "-projectPath", project], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (SCN_PATH.parent / "grandchild.pid").write_text(str(p.pid))


def main() -> None:
    record()
    if ARGV[:1] in (["--version"], ["-V"]):
        print(SCN.get("version", "1.0.0-beta.13"))
        return
    sub = ARGV[0] if ARGV else ""
    if sub == "commands":
        if SCN.get("bogus"):
            print("hello")
            return
        cmds = [{"name": n, "options": [{"long": o} for o in opts]} for n, opts in {
            "recompile": ["--project-path", "--timeout", "--strict"], "status": ["--project-path", "--until-ready"],
            "test": ["--mode", "--filter", "--output", "--timeout"], "run": ["--timeout", "--log-file"],
            "build": ["--profile", "--target", "--output-path", "--log-file", "--timeout"]}.items()]
        env("commands", {"commands": cmds})
    if sub == "editors":
        env("editors", [{"version": SCN.get("editor_version", "6000.3.21f1"), "architecture": "arm64",
                         "location": SCN.get("editor_location", "/Fake/Unity.app")}])
    if sub == "status":
        st = SCN.get("status", "none")
        project = opt("--project-path", "")
        if st == "ready":
            env("status", {"count": 1, "instances": [{"state": "ready", "pid": 4242, "port": 8765,
                                                      "projectPath": project, "pipelineVersion": "1.0.0"}]})
        if st == "load_pending":
            env("status", {"count": 0, "instances": []}, [("STATUS_PIPELINE_LOAD_PENDING", "load pending")], 6)
        if st == "starting":
            env("status", {"count": 1, "instances": [{"state": "starting", "pid": 4242}]},
                [("STATUS_NOT_READY", "starting")], 6)
        env("status", {"count": 0, "instances": []}, [("STATUS_NO_INSTANCES", "No Unity Editor instances found")], 6)
    if sub == "pipeline" and ARGV[1:2] == ["list"]:
        n = 1 if SCN.get("safe_mode") else 0
        env("pipeline list", {"instances": [{"pid": 4242, "safeMode": {"detected": bool(n)}}] if n else [],
                              "summary": {"totalInstances": n, "instancesInSafeMode": n}})
    if sub == "pipeline" and ARGV[1:2] == ["install"]:
        env("pipeline install", {"version": opt("--package-version")})
    if sub == "recompile":
        rc = SCN.get("recompile", {"exit": 0})
        stream(rc.get("lines", ["[recompile] refreshing"]))
        if rc["exit"] == 0:
            env("recompile", {"status": "ok", "errors": [], "warnings": rc.get("warnings", []), "failed": False})
        if rc["exit"] == 7:
            env("recompile", None, [("COMMAND_FAILED", "No Pipeline instance found for project")], 7)
        env("recompile", {"status": "failed", "errors": rc.get("errors", []), "warnings": [], "failed": True,
                          "compilationFailed": True}, [("COMMAND_FAILED", "Compilation failed")], 6)
    if sub == "test":
        t = SCN.get("test", {"result": "pass"})
        out = Path(opt("--output", "test-results.xml"))
        stream(t.get("lines", ["[Unity] Opening project", "[Unity] Running tests", "[Unity] Test run completed"]),
               t.get("delay", 0.05))
        if t.get("sleep"):
            time.sleep(t["sleep"])
        res = t["result"]
        if res == "pass":
            nunit(out, t.get("passed", ["Game.Tests.M1_S01_Move.Moves", "Game.Tests.HitTests.Hits"]), [])
            env("test", {"projectPath": ARGV[1], "output": str(out), "reports": {"nunit": str(out), "junit": None}})
        if res == "fail":
            nunit(out, ["Game.Tests.A.Ok"], ["Game.Tests.HitTests.Flash"])
            env("test", None, [("TESTS_FAILED", "1 test failed")], 8)
        if res == "empty":
            nunit(out, [], [])
            env("test", {"output": str(out), "reports": {"nunit": str(out)}})
        if res == "timeout":
            env("test", None, [("TEST_TIMED_OUT", "Unity timed out")], 6)
        if res == "compile_error":
            stream(["Assets/Game/Hit.cs(3,5): error CS1002: ; expected", "Scripts have compiler errors."])
            env("test", None, [("TEST_RUN_ERROR", "no verdict")], 6)
    if sub == "run":
        r = SCN.get("run", {"result": "pass"})
        log = Path(opt("--log-file", SCN_PATH.parent / "run.log"))
        text = {"pass": "Compiling scripts\nExiting batchmode successfully now!\n",
                "fail": "Assets/Game/Hit.cs(3,5): error CS1002: ; expected\nScripts have compiler errors.\n",
                "multi": "Multiple Unity instances cannot open the same project.\n"}[r["result"]]
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text)
        stream(text.splitlines())
        if r.get("grandchild"):
            grandchild(ARGV[1])
        if r.get("hang"):
            time.sleep(r["hang"])
        env("run", {"exitCode": 0 if r["result"] == "pass" else 1}, None if r["result"] == "pass" else
            [("COMMAND_FAILED", "Unity exited with code 1")], 0 if r["result"] == "pass" else 1)
    if sub == "build":
        b = SCN.get("build", {"exit": 0})
        out = opt("--output-path")
        Path(opt("--log-file")).parent.mkdir(parents=True, exist_ok=True)
        Path(opt("--log-file")).write_text("Build log\n")
        if b["exit"] == 0:
            env("build", {"outputPath": out, "provenance": None})
        env("build", {"editorErrors": [{"message": "error: build failed"}]}, [("BUILD_FAILED", "Build failed")], 6)
    if sub == "command":
        words = []
        for a in ARGV[1:]:
            if a.startswith("-"):
                break
            words.append(a)
        name = " ".join(words)
        if not name:  # listing
            env("command", {"commands": [{"name": n} for n in SCN.get("catalog", ["run_tests", "eval", "screenshot",
                                                                                   "editor_play", "set_autotick"])]})
        fence = after_fence()
        params = {fence[i].lstrip("-"): fence[i + 1] for i in range(0, len(fence) - 1, 2)}
        if "--detach" in ARGV:
            env("command", {"jobId": "job-1", "command": name, "parameters": params})
        if name == "screenshot" and params.get("output"):
            Path(params["output"]).parent.mkdir(parents=True, exist_ok=True)
            Path(params["output"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        env("command", {"command": name, "result": SCN.get("command_result", {"ok": True}), "parameters": params})
    if sub == "job":
        if ARGV[1] == "wait":
            if SCN.get("job_sleep"):
                time.sleep(SCN["job_sleep"])
            env("job wait", SCN.get("job_result", {"result": {
                "Summary": {"Total": 3, "Passed": 2, "Failed": 1},
                "Results": [{"FullName": "Game.Tests.M1_S01_Move.Moves", "Status": "Passed"},
                            {"FullName": "Game.Tests.A.Ok", "Status": "Passed"},
                            {"FullName": "Game.Tests.HitTests.Flash", "Status": "Failed", "Message": "Expected 0"}]}}))
        env("job " + ARGV[1], {"jobId": ARGV[2], "state": "cancelled"})
    if sub in ("close", "open", "self-update"):
        env(sub, {"ok": True})
    env(sub or "unity", None, [("COMMAND_FAILED", f"fake: unknown {ARGV}")], 2)


if __name__ == "__main__":
    main()
