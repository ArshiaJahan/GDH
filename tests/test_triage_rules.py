"""The deterministic CI triage rules engine (features/triage_rules.py)."""
from __future__ import annotations

import asyncio
import re
import subprocess
import time
from pathlib import Path

import pytest
from gamedevworkstation.features import triage_rules as T
from gamedevworkstation.features.triage_rules import Failure, TriageReport

FIXTURES = Path(__file__).parent / "fixtures" / "ci_logs"


def gh(job: str, step: str, *lines: str) -> str:
    """Lines in `gh run view --log-failed` format."""
    return "\n".join(f"{job}\t{step}\t2026-11-18T06:29:03.2822620Z {t}" for t in lines)


def prim(text: str) -> Failure:
    r = T.classify(text)
    assert r.primary is not None, r
    return r.primary


# --- normalising -----------------------------------------------------------------------------


def test_normalize_gh_format_strips_timestamp_bom_ansi_and_groups():
    text = ("Build\tRun tests\t\ufeff2026-11-18T06:29:03.2822620Z ##[group]Run pytest\n"
            "Build\tRun tests\t2026-11-18T06:29:03.2823000Z ^[[36;1mpytest -q^[[0m\n"
            "Build\tRun tests\t2026-11-18T06:29:03.2853910Z ##[endgroup]\n"
            "Build\tRun tests\t2026-11-18T06:29:04.0000000Z \x1b[31mred\x1b[0m text")
    lines = T.normalize(text)
    assert [ln.text for ln in lines] == ["Run pytest", "pytest -q", "red text"]
    assert {(ln.job, ln.step) for ln in lines} == {("Build", "Run tests")}


def test_normalize_raw_actions_and_plain_text():
    lines = T.normalize("2026-01-02T03:04:05.1234567Z hello\nplain line\r\n")
    assert [(ln.job, ln.step, ln.text) for ln in lines] == [(None, None, "hello"), (None, None, "plain line")]


def test_blocks_split_by_job_and_step():
    text = "\n".join([
        gh("A", "setup", "ok"),
        gh("A", "test", "##[error]Process completed with exit code 1."),
        gh("B", "test", "##[error]Process completed with exit code 2."),
    ])
    r = T.classify(text)
    assert r.blocks == 2 and r.unclassified == 2
    assert [(f.job, f.step) for f in r.failures] == [("A", "test"), ("B", "test")]


def test_clean_path_prefixes():
    assert T.clean_path(r"D:\a\GDH\GDH\tests\x.py") == "tests/x.py"
    assert T.clean_path("/home/runner/work/r/r/src/a.ts") == "src/a.ts"
    assert T.clean_path("/Users/runner/work/r/r/tests/x.py") == "tests/x.py"
    assert T.clean_path("/github/workspace/lib.rs") == "lib.rs"
    assert T.clean_path("/opt/proj/MyGame/Assets/Tests/FooTests.cs") == "Assets/Tests/FooTests.cs"
    assert T.clean_path("/home/runner/work/g/g/Game/Packages/com.x/Runtime/A.cs") == "Packages/com.x/Runtime/A.cs"
    assert T.clean_path(r"tests\x.py") == "tests/x.py"
    assert T.clean_path("./src/a.ts") == "src/a.ts"


# --- the two real CI logs --------------------------------------------------------------------


def test_real_gdh_docs_assert_log():
    r = T.load(FIXTURES / "gdh_pytest_docs_assert.log")
    f = r.primary
    assert (f.category, f.file, f.line) == ("test", "tests/test_claude_code.py", 1281)
    assert f.test == "tests/test_claude_code.py::test_claude_code_docs_describe_verification_isolation_and_billing"
    assert f.job == "Backend tests (Python)" and f.step == "Run pytest"
    assert len(r.failures) == 1 and r.rule_coverage == 1.0


def test_real_gdh_windows_path_log():
    r = T.load(FIXTURES / "gdh_windows_path_assert.log")
    f = r.primary
    assert (f.category, f.file, f.line) == ("test", "tests/test_release_feed.py", 120)
    assert f.test == "tests/test_release_feed.py::test_windows_helper_script_quotes_paths"
    assert len(r.failures) == 1


# --- pytest ----------------------------------------------------------------------------------

PYTEST = """\
=================================== FAILURES ===================================
_________________________________ test_helper __________________________________

    def test_helper():
>       helper(1)

D:\\a\\GDH\\GDH\\tests\\test_a.py:5:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

    def helper(x):
>       assert x == 2
E       assert 1 == 2

D:\\a\\GDH\\GDH\\tests\\test_a.py:3: AssertionError
______________________________ TestK.test_p[a b] _______________________________

>       assert v == "c"
E       AssertionError: assert 'a b' == 'c'

tests/test_a.py:9: AssertionError
=========================== short test summary info ============================
FAILED tests/test_a.py::test_helper - assert 1 == 2
FAILED tests/test_a.py::TestK::test_p[a b] - AssertionError: assert 'a b' == 'c'
2 failed, 1 passed in 0.01s
"""


def test_pytest_uses_the_tests_own_frame_and_windows_paths():
    r = T.classify(PYTEST)
    got = [(f.category, f.file, f.line, f.test) for f in r.failures]
    assert got == [
        ("test", "tests/test_a.py", 5, "tests/test_a.py::test_helper"),
        ("test", "tests/test_a.py", 9, "tests/test_a.py::TestK::test_p[a b]"),
    ]
    assert r.failures[0].summary == "assert 1 == 2"
    assert "E       assert 1 == 2" in r.failures[0].evidence
    assert r.failures[0].rule == "pytest.failed"


def test_pytest_in_function_frame_and_no_section():
    f = prim("tests/x.py:120: in test_y\n    foo()\nFAILED tests/x.py::test_y - ValueError: x")
    assert (f.file, f.line, f.test) == ("tests/x.py", None, "tests/x.py::test_y")
    text = ("______ test_y ______\n\ntests/x.py:120: in test_y\n    foo()\nsrc/m.py:3: ValueError\n"
            "=== short test summary info ===\nFAILED tests/x.py::test_y - ValueError: x")
    f = prim(text)
    assert (f.file, f.line) == ("tests/x.py", 120)


def test_pytest_setup_error():
    text = ("__________ ERROR at setup of test_fix __________\n\n>  raise RuntimeError('boom')\nE  RuntimeError: boom\n\n"
            "tests/test_a.py:12: RuntimeError\n=== short test summary info ===\n"
            "ERROR tests/test_a.py::test_fix - RuntimeError: boom")
    f = prim(text)
    assert (f.category, f.file, f.line, f.test, f.rule) == ("test", "tests/test_a.py", 12, "tests/test_a.py::test_fix",
                                                             "pytest.error")


def test_pytest_collection_module_not_found_is_dependency():
    text = """\
==================================== ERRORS ====================================
_______________________ ERROR collecting tests/test_b.py _______________________
ImportError while importing test module '/home/runner/work/r/r/tests/test_b.py'.
Traceback:
/opt/hostedtoolcache/Python/3.11.0/x64/lib/python3.11/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package)
/home/runner/work/r/r/tests/test_b.py:1: in <module>
    import requests_toolbelt.multipart
E   ModuleNotFoundError: No module named 'requests_toolbelt'
=========================== short test summary info ============================
ERROR tests/test_b.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
"""
    r = T.classify(text)
    assert len(r.failures) == 1
    f = r.primary
    assert (f.category, f.file, f.line, f.rule) == ("dependency", "tests/test_b.py", 1, "python.module_not_found")
    assert "`requests_toolbelt`" in f.fix and "uv sync" in f.fix


def test_python_syntax_error_in_collection():
    text = """\
_______________________ ERROR collecting tests/test_c.py _______________________
../lib/python3.13/ast.py:50: in parse
    return compile(source, filename, mode, flags,
E     File "/home/runner/work/r/r/tests/test_c.py", line 7
E       def f(:
E             ^
E   SyntaxError: invalid syntax
=========================== short test summary info ============================
ERROR tests/test_c.py
"""
    r = T.classify(text)
    assert [(f.category, f.file, f.line, f.rule) for f in r.failures] == [
        ("compile", "tests/test_c.py", 7, "python.syntax")]


def test_pytest_timeout():
    text = ("+++++++++++++++++++++++++++++++++++ Timeout ++++++++++++++++++++++++++++++++++++\n"
            "=== short test summary info ===\nFAILED tests/test_slow.py::test_hang - Failed: Timeout >5.0s")
    r = T.classify(text)
    assert len(r.failures) == 1  # the banner is only a fallback
    f = r.primary
    assert (f.category, f.test, f.file, f.rule) == ("timeout", "tests/test_slow.py::test_hang", "tests/test_slow.py",
                                                    "pytest.timeout")


def test_pytest_native_traceback_frame():
    text = ("__________ test_helper __________\nTraceback (most recent call last):\n"
            '  File "/home/runner/work/r/r/.venv/lib/python3.13/site-packages/_pytest/runner.py", line 361, in call\n'
            '  File "/home/runner/work/r/r/tests/test_a.py", line 5, in test_helper\n    helper(1)\n'
            "AssertionError\n=== short test summary info ===\nFAILED tests/test_a.py::test_helper - AssertionError")
    f = prim(text)
    assert (f.file, f.line) == ("tests/test_a.py", 5)


def test_pytest_summary_fallback_when_details_are_missing():
    f = prim("collected 3 items\n2 failed, 1 passed in 0.3s\n##[error]Process completed with exit code 1.")
    assert (f.category, f.rule) == ("test", "pytest.summary")
    r = T.classify("E   ModuleNotFoundError: No module named 'zz'\n=== 1 error in 0.06s ===")
    assert [f.rule for f in r.failures] == ["python.module_not_found"]  # the summary line adds nothing


# --- flaky -----------------------------------------------------------------------------------


def test_pytest_rerun_that_passed_is_flaky_and_one_that_failed_is_not():
    f = prim("tests/x.py::test_net RERUN\ntests/x.py::test_net PASSED\n1 passed, 1 rerun in 0.2s")
    assert (f.category, f.test, f.rule) == ("flaky", "tests/x.py::test_net", "pytest.rerun_verbose")
    r = T.classify("RERUN tests/x.py::test_net\nFAILED tests/x.py::test_net - assert 0\n1 failed, 1 rerun in 0.2s")
    assert [f.category for f in r.failures] == ["test"]


def test_failed_then_passed_in_a_later_step_is_flaky():
    text = "\n".join([
        gh("Tests", "Run pytest", "FAILED tests/x.py::test_y - assert 0", "1 failed in 0.1s"),
        gh("Tests", "Retry pytest", "tests/x.py::test_y PASSED", "1 passed in 0.1s"),
    ])
    f = prim(text)
    assert (f.category, f.rule, f.test) == ("flaky", "pytest.passed_on_rerun", "tests/x.py::test_y")


def test_nextest_flaky_and_retry_action():
    f = prim("        FLAKY 2/3 [   0.004s] crt tests::sometimes")
    assert (f.category, f.test) == ("flaky", "tests::sometimes")
    f = prim("Attempt 1 failed. Reason: Child_process exited with error code 1\nCommand completed after 2 attempt(s).")
    assert (f.category, f.rule) == ("flaky", "retry.passed")


# --- compile ---------------------------------------------------------------------------------


def test_csharp_three_errors_with_fixes_and_dedup():
    line1 = ("/home/runner/work/g/g/Game/Assets/Scripts/Player.cs(10,5): error CS0103: The name 'speed' does not "
             "exist in the current context [/home/runner/work/g/g/Game/Game.csproj]")
    text = "\n".join([
        line1,
        r"D:\a\g\g\Game\Assets\Scripts\Enemy.cs(3,7): error CS0246: The type or namespace name 'Foo' could not be "
        r"found (are you missing a using directive or an assembly reference?)",
        "Assets/Scripts/Ui.cs(22,1): error CS1002: ; expected",
        "Build FAILED.",
        line1,  # MSBuild repeats errors in its summary
        "Scripts have compiler errors.",
    ])
    r = T.classify(text)
    got = [(f.file, f.line, f.rule) for f in r.failures]
    assert got == [("Assets/Scripts/Player.cs", 10, "csharp.cs0103"), ("Assets/Scripts/Enemy.cs", 3, "csharp.cs0246"),
                   ("Assets/Scripts/Ui.cs", 22, "csharp.error")]
    assert all(f.category == "compile" for f in r.failures)
    assert "`speed`" in r.failures[0].fix and "using" in r.failures[0].fix
    assert "`Foo`" in r.failures[1].fix and r.failures[2].fix is None
    assert r.failures[2].summary == "CS1002: ; expected"


def test_unity_compile_fallback_alone():
    f = prim("Scripts have compiler errors.\n##[error]Process completed with exit code 1.")
    assert (f.category, f.rule) == ("compile", "unity.compile_errors")


def test_typescript_plain_and_pretty():
    r = T.classify("src/a.ts(1,15): error TS2307: Cannot find module 'left-padzz' or its corresponding type "
                   "declarations.\nsrc/a.ts(2,7): error TS2322: Type 'string' is not assignable to type 'number'.")
    assert [(f.file, f.line, f.rule) for f in r.failures] == [("src/a.ts", 1, "ts.ts2307"), ("src/a.ts", 2, "ts.error")]
    assert "`left-padzz`" in r.failures[0].fix and r.failures[1].fix is None
    pretty = ("\x1b[96msrc/b.tsx\x1b[0m:\x1b[93m4\x1b[0m:\x1b[93m9\x1b[0m - \x1b[91merror\x1b[0m\x1b[90m TS2552: "
              "\x1b[0mCannot find name 'x'.")
    f = prim(pretty)
    assert (f.file, f.line, f.summary) == ("src/b.tsx", 4, "TS2552: Cannot find name 'x'.")


def test_rust_compile_errors():
    text = """\
   Compiling crt v0.1.0 (/home/runner/work/r/r)
error[E0425]: cannot find value `bogus` in this scope
 --> src/lib.rs:1:33
  |
1 | pub fn add(a: i32) -> i32 { a + bogus }
  |                                 ^^^^^ not found in this scope

error: this file contains an unclosed delimiter
 --> src/main.rs:2:11

error: could not compile `crt` (lib) due to 2 previous errors"""
    r = T.classify(text)
    assert [(f.file, f.line, f.rule) for f in r.failures] == [("src/lib.rs", 1, "rust.error_code"),
                                                              ("src/main.rs", 2, "rust.error")]
    assert r.failures[0].summary == "E0425: cannot find value `bogus` in this scope"


def test_mypy_and_esbuild():
    f = prim("src/app/x.py:12: error: Incompatible return value type (got \"int\", expected \"str\")  [return-value]")
    assert (f.category, f.file, f.line) == ("compile", "src/app/x.py", 12)
    f = prim('✘ [ERROR] Could not resolve "./missing"\n\n    src/main.ts:3:20:\n      3 │ import x from "./missing"')
    assert (f.category, f.file, f.line) == ("compile", "src/main.ts", 3)


# --- tests in other runners ------------------------------------------------------------------

VITEST = """\
⎯⎯⎯⎯⎯⎯⎯ Failed Tests 2 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/m.test.ts > math > adds
AssertionError: expected 3 to be 4 // Object.is equality

 ❯ src/m.test.ts:4:19
      4|     expect(1 + 2).toBe(4)

⎯⎯⎯⎯⎯⎯⎯[1/2]⎯

 FAIL  src/m.test.ts > math > slow
Error: Test timed out in 50ms.
If this is a long-running test, pass a timeout value as the last argument.
 ❯ src/m.test.ts:6:3

⎯⎯⎯⎯⎯⎯⎯[2/2]⎯

 Test Files  1 failed (1)
      Tests  2 failed | 1 passed (3)
"""


def test_vitest_failure_and_timeout():
    r = T.classify(VITEST)
    got = [(f.category, f.file, f.line, f.test, f.rule) for f in r.failures]
    assert got == [("timeout", "src/m.test.ts", 6, "math > slow", "vitest.timeout"),
                   ("test", "src/m.test.ts", 4, "math > adds", "vitest.failed")]


def test_jest_failure_and_timeout():
    text = """\
FAIL src/a.test.js (5.2 s)
  ● math › adds

    expect(received).toBe(expected) // Object.is equality

      at Object.toBe (src/a.test.js:4:17)

  ● math › slow

    thrown: "Exceeded timeout of 5000 ms for a test.
    Add a timeout value to this test to increase the timeout."

      at test (src/a.test.js:8:3)

Tests:       2 failed, 1 passed, 3 total
"""
    r = T.classify(text)
    got = [(f.category, f.file, f.line, f.test) for f in r.failures]
    assert got == [("timeout", "src/a.test.js", 8, "math › slow"), ("test", "src/a.test.js", 4, "math › adds")]


def test_cargo_test_panic():
    text = """\
running 2 tests
test tests::ok ... ok
test tests::it_works ... FAILED

failures:

---- tests::it_works stdout ----

thread 'tests::it_works' (58777145) panicked at src/lib.rs:6:21:
assertion `left == right` failed
  left: 4
 right: 5

test result: FAILED. 1 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
"""
    r = T.classify(text)
    assert [(f.category, f.file, f.line, f.test) for f in r.failures] == [
        ("test", "src/lib.rs", 6, "tests::it_works")]
    assert r.primary.summary == "assertion `left == right` failed"
    f = prim("thread 'tests::t' panicked at 'boom', src/lib.rs:3:5")
    assert (f.file, f.line, f.summary) == ("src/lib.rs", 3, "boom")


def test_dotnet_test_failed():
    text = """\
  Failed Game.Tests.PlayerTests.Jumps [12 ms]
  Error Message:
   Expected: 2  But was: 1
  Stack Trace:
     at Game.Tests.PlayerTests.Jumps() in /home/runner/work/g/g/Game/Tests/PlayerTests.cs:line 42
Failed!  - Failed:     1, Passed:    10, Skipped:     0, Total:    11
"""
    r = T.classify(text)
    assert [(f.category, f.file, f.line, f.test) for f in r.failures] == [
        ("test", "Game/Tests/PlayerTests.cs", 42, "Game.Tests.PlayerTests.Jumps")]


# --- dependency ------------------------------------------------------------------------------


@pytest.mark.parametrize("text,rule,fix", [
    ("  × No solution found when resolving dependencies:\n  ╰─▶ Because foo==9 was not found, we can conclude ...",
     "uv.resolution", None),
    ("ERROR: Could not find a version that satisfies the requirement foo==9 (from versions: 1.0)\n"
     "ERROR: No matching distribution found for foo==9", "pip.resolution", None),
    ("npm error code ERESOLVE\nnpm error ERESOLVE unable to resolve dependency tree", "npm.eresolve", None),
    ("npm ERR! code E404\nnpm ERR! 404 Not Found - GET https://registry.npmjs.org/nopezz", "npm.e404", None),
    ("npm error `npm ci` can only install packages when your package.json and package-lock.json or "
     "npm-shrinkwrap.json are in sync. Please update your lock file with `npm install` before continuing.\n"
     "npm error Missing: left-pad@1.3.0 from lock file", "npm.lockfile", "npm install"),
    ("error: failed to select a version for the requirement `serde = \"=999.0.0\"`", "cargo.version_select", None),
    ("An error occurred while resolving packages:\n  Project has invalid dependencies:\n"
     "    com.foo.bar: Package [com.foo.bar@1.2.3] cannot be found", "unity.packages", None),
    ("Traceback (most recent call last):\n  File \"scripts/build.py\", line 3, in <module>\n    import yaml\n"
     "ModuleNotFoundError: No module named 'yaml'", "python.module_not_found", "uv sync"),
])
def test_dependency_rules(text, rule, fix):
    r = T.classify(text)
    assert len(r.failures) == 1, r.failures
    f = r.primary
    assert (f.category, f.rule) == ("dependency", rule)
    assert (fix is None and f.fix is None) or fix in f.fix


def test_module_not_found_frame_and_lockfile_paths():
    f = prim("Traceback (most recent call last):\n  File \"/home/runner/work/r/r/scripts/build.py\", line 3, in <module>"
             "\n    import yaml.loader\nModuleNotFoundError: No module named 'yaml.loader'")
    assert (f.file, f.line) == ("scripts/build.py", 3) and "`yaml`" in f.fix
    f = prim("npm error Missing: left-pad@1.3.0 from lock file")
    assert f.file == "package-lock.json"
    f = prim("An error occurred while resolving packages:\n  com.foo: Package [com.foo@1.0] cannot be found")
    assert f.file == "Packages/manifest.json" and "com.foo@1.0" in f.summary


# --- infra / timeout -------------------------------------------------------------------------


@pytest.mark.parametrize("text,rule", [
    ("##[error]The runner has received a shutdown signal. This can happen when the runner service is stopped.",
     "gha.runner_shutdown"),
    ("##[error]The hosted runner: GitHub Actions 12 lost communication with the server.", "gha.runner_lost"),
    ("OSError: [Errno 28] No space left on device", "infra.disk_full"),
    ("fatal: unable to access 'https://github.com/x/y/': Could not resolve host: github.com", "net.dns"),
    ("npm error code ECONNRESET", "net.connection"),
    ("error: RPC failed; HTTP 503 Service Unavailable", "net.http_5xx"),
    ("gh: API rate limit exceeded for installation ID 1234", "net.rate_limit"),
    ("[Licensing::Module] Error: Access token is unavailable; failed to update", "unity.license"),
    ("No valid Unity Editor license found. Please activate your license.", "unity.license"),
])
def test_infra_rules(text, rule):
    f = prim(text)
    assert (f.category, f.rule) == ("infra", rule)


def test_disk_full_and_job_timeout_fixes():
    assert "disk" in prim("ENOSPC: no space left on device, write").fix
    f = prim("##[error]The job running on runner GitHub Actions 3 has exceeded the maximum execution time of 30 minutes.")
    assert (f.category, f.rule) == ("timeout", "gha.job_timeout")
    assert "timeout-minutes" in f.fix and f.summary == "Job exceeded the maximum execution time of 30 minutes"


def test_retried_network_warning_is_not_infra():
    r = T.classify("npm warn retrying fetch after ECONNRESET\nok")
    assert r.failures == []


def test_infra_words_inside_a_test_traceback_are_ignored():
    text = """\
=================================== FAILURES ===================================
___________________________________ test_disk ___________________________________
>       assert classify("No space left on device") == "infra"
E       AssertionError
tests/test_x.py:9: AssertionError
=========================== short test summary info ============================
FAILED tests/test_x.py::test_disk - AssertionError: No space left on device
"""
    r = T.classify(text)
    assert [(f.category, f.line) for f in r.failures] == [("test", 9)]


def test_runner_shutdown_during_tests_makes_infra_primary():
    text = gh("Tests", "Run pytest",
              "=================================== FAILURES ===================================",
              "___________ test_y ___________",
              "E   assert 0",
              "tests/x.py:3: AssertionError",
              "##[error]The runner has received a shutdown signal. This can happen when the runner service is stopped.",
              "FAILED tests/x.py::test_y - assert 0")
    r = T.classify(text)
    assert [f.category for f in r.failures] == ["infra", "test"]
    assert r.primary.rule == "gha.runner_shutdown"


def test_precedence_order_is_stable():
    text = "src/a.ts(1,1): error TS2322: x\nnpm error code ERESOLVE\nFAILED tests/x.py::t - a\nOSError: No space left on device"
    r = T.classify(text)
    assert [f.category for f in r.failures] == ["infra", "dependency", "compile", "test"]


def test_dedup_identical_failures():
    line = "Assets/A.cs(1,2): error CS1002: ; expected"
    r = T.classify("\n".join([line, line, line]))
    assert len(r.failures) == 1


# --- unknown blocks and the llm pass -----------------------------------------------------------


def _two_unknown_blocks() -> TriageReport:
    text = "\n".join([
        gh("Build", "Package", *[f"step line {i}" for i in range(130)], "weird packaging tool exploded",
           "##[error]Process completed with exit code 3."),
        gh("Lint", "Run lint", "something odd", "##[error]Process completed with exit code 1."),
        gh("Tests", "Run pytest", "FAILED tests/x.py::t - assert 0"),
    ])
    return T.classify(text)


def test_unknown_blocks():
    r = _two_unknown_blocks()
    assert (r.blocks, r.by_rules, r.unclassified) == (3, 1, 2)
    unk = [f for f in r.failures if f.category == "unknown"]
    assert [f.source for f in unk] == ["none", "none"] and all(f.rule is None for f in unk)
    assert unk[0].evidence[-1] == "##[error]Process completed with exit code 3."
    assert len(unk[0].evidence) == 8 and unk[0].summary == "weird packaging tool exploded"
    assert len(r.block_lines) == 2 and len(r.block_lines[0]) == 120
    assert r.block_lines[1][-1].endswith("exit code 1.")
    assert r.rule_coverage == pytest.approx(1 / 3)
    assert "block_lines" not in r.model_dump_json()


def test_non_failing_block_without_rules_is_ignored():
    r = T.classify("all good\nnothing to see")
    assert (r.blocks, r.failures, r.rule_coverage) == (0, [], 1.0)


def test_triage_fills_unknowns_with_llm():
    r = _two_unknown_blocks()
    seen: list[list[str]] = []

    async def llm(lines: list[str]) -> Failure | None:
        seen.append(lines)
        return Failure(category="infra", summary="packager crashed", confidence=0.6)

    out = asyncio.run(T.triage(r, llm))
    assert len(seen) == 2 and len(seen[0]) == 120
    assert (out.by_llm, out.unclassified, out.by_rules) == (2, 0, 1)
    assert [f.category for f in out.failures] == ["infra", "infra", "test"]
    llm_f = out.failures[0]
    assert (llm_f.source, llm_f.rule, llm_f.job, llm_f.step) == ("llm", None, "Build", "Package")
    assert out.block_lines == []
    assert r.unclassified == 2 and r.failures[-1].category == "unknown"  # the input is untouched


def test_triage_llm_exception_and_none_leave_unknown():
    r = _two_unknown_blocks()
    calls = 0

    async def llm(lines):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("provider down")

    out = asyncio.run(T.triage(r, llm))
    assert calls == 2 and (out.by_llm, out.unclassified) == (0, 2)
    assert [f.source for f in out.failures if f.category == "unknown"] == ["none", "none"]
    assert len(out.block_lines) == 2


def test_triage_respects_max_llm_blocks():
    r = _two_unknown_blocks()
    calls = 0

    async def llm(lines):
        nonlocal calls
        calls += 1
        return Failure(category="dependency", summary="x")

    out = asyncio.run(T.triage(r, llm, max_llm_blocks=1))
    assert calls == 1 and (out.by_llm, out.unclassified) == (1, 1)
    assert out.primary.category == "dependency" and len(out.block_lines) == 1
    assert out.block_lines[0][-1].endswith("exit code 1.")  # the second block is still unknown
    out0 = asyncio.run(T.triage(r, llm, max_llm_blocks=0))
    assert calls == 1 and out0.unclassified == 2
    assert asyncio.run(T.triage(r, None)).unclassified == 2


# --- NUnit / JUnit XML -----------------------------------------------------------------------

NUNIT = """<?xml version="1.0" encoding="utf-8"?>
<test-run id="2" testcasecount="3" result="Failed" total="3" passed="1" failed="2">
  <test-suite type="Assembly" name="Tests.dll" result="Failed">
    <test-suite type="TestFixture" name="FooTests" fullname="Game.Tests.FooTests" result="Failed">
      <test-case id="1" name="Passes" fullname="Game.Tests.FooTests.Passes" result="Passed"/>
      <test-case id="2" name="Adds" fullname="Game.Tests.FooTests.Adds" result="Failed">
        <failure>
          <message><![CDATA[  Expected: 4
  But was:  3
]]></message>
          <stack-trace><![CDATA[at Game.Tests.FooTests.Adds () [0x00001] in /home/runner/work/g/g/Proj/Assets/Tests/FooTests.cs:42
]]></stack-trace>
        </failure>
      </test-case>
      <test-case id="3" name="Waits" fullname="Game.Tests.FooTests.Waits" result="Failed" label="Timeout">
        <failure><message>Test exceeded Timeout value of 1000ms</message></failure>
      </test-case>
    </test-suite>
  </test-suite>
</test-run>
"""


def test_nunit_failure_and_timeout(tmp_path):
    p = tmp_path / "results.xml"
    p.write_text(NUNIT)
    r = T.load(p)
    assert (r.blocks, r.by_rules) == (2, 2)
    got = [(f.category, f.file, f.line, f.test, f.rule) for f in r.failures]
    assert got == [("timeout", None, None, "Game.Tests.FooTests.Waits", "nunit.timeout"),
                   ("test", "Assets/Tests/FooTests.cs", 42, "Game.Tests.FooTests.Adds", "nunit.failed")]
    assert r.failures[1].summary == "Expected: 4"


def test_nunit_refuses_doctype_entity_and_oversize():
    with pytest.raises(ValueError):
        T.parse_nunit_xml('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><test-run/>', "x.xml")
    with pytest.raises(ValueError):
        T.parse_nunit_xml(b"<test-run><!ENTITY a 'b'></test-run>", "x.xml")
    with pytest.raises(ValueError):
        T.parse_nunit_xml(b"<test-run>" + b" " * (20 * 1024 * 1024) + b"</test-run>", "big.xml")
    with pytest.raises(ValueError):
        T.parse_nunit_xml("<test-run>", "broken.xml")


def test_junit_xml():
    xml = ('<testsuites><testsuite name="pytest"><testcase classname="tests.test_a" name="test_x" '
           'file="tests/test_a.py" line="7"><failure message="assert 1 == 2">tests/test_a.py:8: AssertionError'
           '</failure></testcase><testcase classname="tests.test_a" name="test_ok"/></testsuite></testsuites>')
    r = T.parse_nunit_xml(xml, "junit.xml")
    assert [(f.category, f.file, f.line, f.test) for f in r.failures] == [
        ("test", "tests/test_a.py", 7, "tests.test_a.test_x")]


# --- load / merge ----------------------------------------------------------------------------


def test_load_directory_merges_logs_and_xml(tmp_path):
    (tmp_path / "a.log").write_text("Assets/A.cs(1,2): error CS1002: ; expected")
    (tmp_path / "b.txt").write_text("weird\n##[error]Process completed with exit code 1.")
    (tmp_path / "c.xml").write_text(NUNIT)
    (tmp_path / "ignored.json").write_text("{}")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.log").write_text("OSError: No space left on device")
    r = T.load(tmp_path)
    assert r.source == str(tmp_path)
    assert [f.category for f in r.failures] == ["timeout", "compile", "test", "unknown"]
    assert (r.blocks, r.by_rules, r.unclassified, len(r.block_lines)) == (4, 3, 1, 1)


def test_merge_counts_order_and_dedupe():
    a = T.classify("FAILED tests/x.py::t - a\nAssets/A.cs(1,2): error CS1002: ; expected", "a")
    b = T.classify("FAILED tests/x.py::t - a\nnpm error code ERESOLVE", "b")
    m = T.merge([a, b])
    assert m.source == "a, b"
    assert [(f.category, f.test) for f in m.failures] == [("dependency", None), ("compile", None),
                                                          ("test", "tests/x.py::t")]
    assert (m.blocks, m.by_rules) == (2, 2)
    assert T.merge([], source="none").primary is None


# --- markdown --------------------------------------------------------------------------------


def test_render_markdown_escapes_cells_and_fences_evidence():
    f = Failure(category="test", summary="a | b `c` <script>", file="x|y.py", line=3, test="t`|`",
                evidence=["has ``` fence", "and ````` five"], rule="pytest.failed")
    r = TriageReport(source="s", failures=[f], blocks=1, by_rules=1)
    md = T.render_markdown(r)
    assert md.startswith("### CI triage: 1 failure(s)")
    row = next(ln for ln in md.splitlines() if ln.startswith("| 1 |"))
    assert row.count(" | ") == 4  # the cell pipes are escaped, so the row keeps five columns
    assert "&#124;" in row and "&#96;" in row and "<script>" not in md
    assert "``````text" in md  # a fence longer than the longest backtick run
    assert md.rstrip().endswith("Classified by rules: 1/1 blocks")


def test_render_markdown_stays_under_60kb():
    fs = [Failure(category="test", summary=f"s{i}" + "x" * 190, file=f"tests/t{i}.py", line=i,
                  evidence=["y" * 290] * 8, rule="pytest.failed") for i in range(200)]
    r = TriageReport(source="s", failures=fs, blocks=200, by_rules=200)
    md = T.render_markdown(r)
    assert len(md.encode()) < 60_000 and md.startswith("### CI triage: 200 failure(s)")
    assert "Classified by rules: 200/200 blocks" in md
    small = T.render_markdown(TriageReport(source="s", failures=fs[:3], blocks=3, by_rules=3))
    assert "y" * 290 in small  # evidence is kept when it fits


def test_render_markdown_empty_and_footer_counts():
    md = T.render_markdown(TriageReport(source="s", failures=[], blocks=0, by_rules=0))
    assert "No failures found." in md and "Classified by rules: 0/0 blocks" in md
    r = asyncio.run(T.triage(_two_unknown_blocks(), None))
    assert "unclassified: 2" in T.render_markdown(r)


def test_failure_caps_summary_and_evidence():
    f = Failure(category="test", summary="a\nb " + "x" * 300, evidence=["z" * 400] * 12)
    assert "\n" not in f.summary and len(f.summary) <= 200
    assert len(f.evidence) == 8 and all(len(e) <= 300 for e in f.evidence)


# --- fetch_run_log ---------------------------------------------------------------------------


def test_fetch_run_log_validates_and_calls_gh(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        assert kw["timeout"] == 120 and kw["capture_output"]
        return subprocess.CompletedProcess(cmd, 0, stdout="job\tstep\tlog", stderr="")

    monkeypatch.setattr(T.subprocess, "run", fake_run)
    assert T.fetch_run_log("123", "owner/repo.name") == "job\tstep\tlog"
    assert calls[-1] == ["gh", "run", "view", "123", "--log-failed", "-R", "owner/repo.name"]
    T.fetch_run_log("9")
    assert calls[-1] == ["gh", "run", "view", "9", "--log-failed"]
    for bad_id in ("12a", "", "1; rm -rf /", "--help"):
        with pytest.raises(ValueError):
            T.fetch_run_log(bad_id)
    for bad_repo in ("owner", "a/b/c", "-R/x", "a b/c", "o/r;x"):
        with pytest.raises(ValueError):
            T.fetch_run_log("1", bad_repo)
    assert len(calls) == 2


def test_fetch_run_log_errors(monkeypatch):
    def failing(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP 404: Not Found")

    monkeypatch.setattr(T.subprocess, "run", failing)
    with pytest.raises(RuntimeError, match="404"):
        T.fetch_run_log("1")

    def missing(cmd, **kw):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(T.subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="gh"):
        T.fetch_run_log("1")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 120)

    monkeypatch.setattr(T.subprocess, "run", slow)
    with pytest.raises(RuntimeError, match="timed out"):
        T.fetch_run_log("1")


def test_playwright_flaky_and_go_test():
    text = ("  1) [chromium] › tests/a.spec.ts:3:5 › logs in ───────────\n\n    Error: expect(locator).toBeVisible()\n\n"
            "  1 flaky\n    [chromium] › tests/a.spec.ts:3:5 › logs in\n  4 passed (3.1s)")
    r = T.classify(text)
    assert [(f.category, f.file, f.line, f.test) for f in r.failures] == [
        ("flaky", "tests/a.spec.ts", 3, "logs in")]
    f = prim("=== RUN   TestAdd\n    math_test.go:12: got 3, want 4\n--- FAIL: TestAdd (0.00s)\n"
             "    math_test.go:12: got 3, want 4\nFAIL")
    assert (f.category, f.file, f.line, f.test) == ("test", "math_test.go", 12, "TestAdd")


def test_nunit_xml_bare_timeout_word_is_not_a_timeout():
    xml = ('<test-run><test-suite><test-case fullname="A.B.Config_Default" result="Failed">'
           '<failure><message>Expected: 30 But was: 10 (timeout default)</message>'
           '<stack-trace>at A.B.Config_Default () in /w/Assets/T.cs:5</stack-trace></failure></test-case>'
           '</test-suite></test-run>')
    f = T.parse_nunit_xml(xml, "x.xml").failures
    assert [x.category for x in f] == ["test"]


def test_nunit_xml_real_timeout_signals():
    xml = ('<test-run><test-case fullname="A.B.Slow" result="Failed">'
           '<failure><message>Test exceeded Timeout value of 5000ms</message></failure></test-case>'
           '<test-case fullname="A.B.Lbl" result="Failed" label="Timeout"><failure><message>x</message></failure>'
           '</test-case></test-run>')
    assert [x.category for x in T.parse_nunit_xml(xml, "x.xml").failures] == ["timeout", "timeout"]


def test_junit_timeout_exception_type():
    xml = ('<testsuite><testcase classname="a.B" name="t"><failure type="java.util.concurrent.TimeoutException" '
           'message="boom"/></testcase></testsuite>')
    assert T.parse_nunit_xml(xml, "j.xml").failures[0].category == "timeout"


def test_nunit_console_failed_then_passed_is_flaky_with_frame():
    log = ("Failed : My.Tests.Foo.Bar\n  Expected: 1\n  at My.Tests.Foo.Bar () [0x1] in /github/workspace/Assets/T/Foo.cs:58\n"
           "Retrying failed tests\nRunning My.Tests.Foo.Bar ... Passed\n")
    r = T.classify(log)
    assert [f.category for f in r.failures] == ["flaky"]
    assert r.failures[0].file == "Assets/T/Foo.cs" and r.failures[0].line == 58


def test_nunit_console_numbered_failed_still_failed_stays_test():
    log = "1) Failed : My.Tests.Foo.Bar\n  boom\n  at X () in /w/Assets/Foo.cs:9\nRunning My.Tests.Foo.Bar ... Failed\n"
    assert T.classify(log).failures[0].category == "test"


# --- review fixes ------------------------------------------------------------------------------


def test_triage_reraises_permission_error():
    r = T.classify("##[error]weird thing broke\n")
    assert r.unclassified == 1

    async def llm(lines):
        raise PermissionError("approval needed")

    with pytest.raises(PermissionError):
        asyncio.run(T.triage(r, llm))

    async def boom(lines):
        raise RuntimeError("x")

    assert asyncio.run(T.triage(r, boom)).unclassified == 1  # other errors still leave it unknown


def _outside_code(md: str) -> str:
    """The markdown with fenced blocks and <code> spans removed."""
    md = re.sub(r"(`{3,})text\n.*?\n\1\n", "", md, flags=re.S)
    return re.sub(r"<code>.*?</code>", "", md)


def test_render_markdown_log_text_cannot_inject():
    log = "FAILED tests/test_a.py::test_x - AssertionError: ping @octocat see https://evil.example/x and torvalds/linux#1\n"
    md = T.render_markdown(T.classify(log))
    rest = _outside_code(md)
    for bad in ("@octocat", "evil.example", "torvalds", "#1"):
        assert bad not in rest
    assert "ping &#64;octocat" in md


def test_render_markdown_llm_fix_is_one_line_inert_code():
    fix = "line1\n\n## Owned\n[click me](https://evil.example) ![](https://evil.example/p.png) @octocat"
    f = Failure(category="test", summary="s\n# H", fix=fix, source="llm")
    assert "\n" not in f.fix
    md = T.render_markdown(TriageReport(source="x", failures=[f], blocks=1, by_rules=0, by_llm=1))
    assert not any(ln.startswith("#") for ln in md.splitlines() if not ln.startswith("### CI triage"))
    assert "](" not in md and "@octocat" not in md and "evil.example" not in _outside_code(md)
    assert "<code>" in md and "Suggested fix:" in md
    assert len(Failure(category="test", summary="s", fix="y" * 1000).fix) == T.MAX_FIX


@pytest.mark.parametrize("text", [
    "Running" + " " * 60000 + "!",
    "a.py::b" + " " * 60000 + "x",
    "  Failed X.Y [1 ms]\n" + "in :" * 15000,
])
def test_no_quadratic_regex_on_long_lines(text):
    t0 = time.perf_counter()
    T.classify(text)
    assert time.perf_counter() - t0 < 0.5


def test_nunit_stack_frame_is_capped():
    t0 = time.perf_counter()
    assert T._frame_of("in :" * 15000)[0] is None
    assert time.perf_counter() - t0 < 0.5


def test_run_passed_still_matches_forms():
    for line in ("Running Foo.Bar ... Passed", "Passed : Foo.Bar", "Passed: Foo.Bar", "  Passed Foo.Bar"):
        assert T._RUN_PASSED.match(line), line


def test_dedupe_is_near_linear():
    cases = "".join(f'<test-case result="Failed" fullname="T.t{i}"><failure><message>boom {i}</message></failure></test-case>'
                    for i in range(8000))
    xml = f"<test-run>{cases}</test-run>"
    t0 = time.perf_counter()
    r = T.parse_nunit_xml(xml, "f.xml")
    assert time.perf_counter() - t0 < 3
    assert len(r.failures) == 8000


def test_dedupe_subsumes_less_specific():
    gen = Failure(category="compile", summary="boom", rule="x")
    spec = Failure(category="compile", summary="boom", file="a.cs", line=1, rule="x")
    other = Failure(category="compile", summary="other", file="b.cs", line=1, rule="x")
    out = T._dedupe([gen, spec, other])
    assert gen not in out and spec in out and other in out
    tgen = Failure(category="test", summary="s1", test="T.a")
    tspec = Failure(category="test", summary="s2", test="T.a", file="a.py")
    assert T._dedupe([tgen, tspec]) == [tspec]


_DTD_XML = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE r [<!ENTITY a "AAAA">]>'
            '<test-run><test-case result="Failed" fullname="T.x"><failure><message>&a;</message></failure></test-case></test-run>')
_PLAIN_XML = ('<?xml version="1.0" encoding="UTF-16"?><test-run><test-case result="Failed" fullname="T.x">'
              '<failure><message>bad</message></failure></test-case></test-run>')


def test_nunit_utf16_doctype_refused_and_plain_parses():
    with pytest.raises(ValueError):
        T.parse_nunit_xml(_DTD_XML.encode("utf-16"), "f.xml")
    with pytest.raises(ValueError):
        T.parse_nunit_xml(_DTD_XML.replace("UTF-16", "UTF-8").encode("utf-8"), "f.xml")
    assert T.parse_nunit_xml(_PLAIN_XML.encode("utf-16"), "f.xml").failures[0].summary == "bad"
    assert T.parse_nunit_xml(_PLAIN_XML.replace("UTF-16", "UTF-8").encode("utf-8"), "f.xml").failures[0].test == "T.x"
