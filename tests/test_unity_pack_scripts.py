"""The Unity audit is a standalone Python tool; exercise its public CLI and lexer."""

import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/perf-pass/scripts/unity_antipatterns.py"
FIXTURES = Path(__file__).parent / "fixtures/unity_antipatterns"
RULE_IDS = {
    "HOT_GETCOMPONENT", "HOT_FIND", "HOT_CAMERA_MAIN", "HOT_LINQ", "HOT_STRING_ALLOC",
    "HOT_NEW_COLLECTION", "HOT_INSTANTIATE_DESTROY", "HOT_LAMBDA", "HOT_DEBUG_LOG",
    "HOT_SENDMESSAGE", "HOT_RESOURCES_LOAD", "TAG_STRING_COMPARE", "COROUTINE_NEW_WAIT",
    "EVENT_NO_UNSUBSCRIBE", "OBSOLETE_VELOCITY", "NONALLOC_DEPRECATED",
}


@pytest.fixture(scope="module")
def audit():
    spec = importlib.util.spec_from_file_location("unity_antipatterns", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "Game"
    shutil.copytree(FIXTURES, root / "Assets/Scripts")
    return root


def run(project, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--project", str(project), *map(str, args)],
                          text=True, capture_output=True, check=False)


def json_run(project, *args):
    result = run(project, "--json", *args)
    assert result.returncode in (0, 1), result.stderr
    return result, json.loads(result.stdout)


@pytest.mark.parametrize("rule", sorted(RULE_IDS))
def test_every_rule_in_realistic_fixtures(audit, project, rule):
    findings = audit.scan_sources(audit.project_sources(project))
    assert rule in {finding["rule"] for finding in findings}
    assert audit.RULE_IDS == RULE_IDS


def test_clean_fixture_and_literals_are_not_flagged(audit, project):
    source = audit.parse_source("Assets/Clean.cs", (FIXTURES / "CleanBehaviour.cs").read_text())
    assert audit.scan_sources([source]) == []


def test_suppression_is_rule_specific_and_requires_reason(audit, project):
    source = audit.parse_source("Assets/Suppressed.cs", (FIXTURES / "SuppressedBehaviour.cs").read_text())
    findings = audit.scan_sources([source])
    assert {finding["rule"] for finding in findings} == {
        "HOT_NEW_COLLECTION", "HOT_CAMERA_MAIN", "HOT_DEBUG_LOG",
    }
    assert next(f for f in findings if f["rule"] == "HOT_DEBUG_LOG")["line_text"] == 'Debug.Log("unsuppressed");'
    text = '''class Test { void Update() {
        Debug.Log("x" + 1); // harness:allow HOT_DEBUG_LOG intentional diagnostic
    } }'''
    assert [f["rule"] for f in audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])] == ["HOT_STRING_ALLOC"]


def test_call_depth_and_cross_file_via(audit, project):
    findings = audit.scan_sources(audit.project_sources(project))
    helper = next(f for f in findings if f["file"].endswith("SharedEffects.cs"))
    assert helper["method"] == "SharedEffects.AllocatePulse"
    assert helper["hot_method"] == "HotBehaviour.Update"
    assert helper["via"] == ["SharedEffects.AllocatePulse"]
    nested = next(f for f in findings if f["method"] == "HotBehaviour.RefreshNested")
    assert nested["via"] == ["HotBehaviour.RefreshLocal", "HotBehaviour.RefreshNested"]
    assert not any(f["method"].endswith(("TooDeep", "AllocateDeeper")) for f in findings)
    result = run(project)
    assert "via SharedEffects.AllocatePulse" in result.stdout


def test_hot_callback_frequencies_and_scores(audit, project):
    findings = audit.scan_sources(audit.project_sources(project))
    for method in ("OnTriggerStay", "OnCollisionStay", "OnTriggerStay2D", "OnCollisionStay2D"):
        finding = next(f for f in findings if f["method"] == "HotBehaviour." + method)
        assert finding["frequency"] == 3
        assert finding["score"] == finding["sites"] * 3
    for method in ("Update", "FixedUpdate", "LateUpdate", "OnGUI"):
        assert all(f["frequency"] == 1 for f in findings if f["method"] == "HotBehaviour." + method)
    report = audit.make_report(findings, set())
    assert report["top_files"] == sorted(report["top_files"], key=lambda item: (-item["score"], item["file"]))
    assert sum(item["score"] for item in report["top_files"]) == sum(f["score"] for f in findings)


def test_baseline_ratchet_and_line_independence(project, tmp_path):
    baseline = tmp_path / "baseline.json"
    initial, report = json_run(project, "--baseline", baseline)
    assert initial.returncode == 1 and report["new"] == report["total"] > 0
    accepted, snapshot = json_run(project, "--baseline", baseline, "--update-baseline")
    assert accepted.returncode == 0 and snapshot["new"] == 0
    data = json.loads(baseline.read_text())
    assert isinstance(data["findings"], dict)
    assert all("line" not in value for value in data["findings"].values())
    script = project / "Assets/Scripts/HotBehaviour.cs"
    script.write_text("// unrelated change\n\n" + script.read_text())
    unchanged, report = json_run(project, "--baseline", baseline)
    assert unchanged.returncode == 0 and report["new"] == 0
    script.write_text(script.read_text().replace("void Update()\n    {", 'void Update()\n    {\n        Resources.Load<AudioClip>("new sound");'))
    added, report = json_run(project, "--baseline", baseline)
    assert added.returncode == 1 and report["new"] == 1
    assert [f["rule"] for f in report["findings"] if f["is_new"]] == ["HOT_RESOURCES_LOAD"]
    assert added.stderr.splitlines()[-1] == "RESULT: FAIL 1 new"


def test_normalized_source_preserves_literal_contents(audit):
    def finding(text):
        return {"rule": "HOT_DEBUG_LOG", "file": "Assets/Test.cs", "line_text": text}
    assert audit.baseline_key(finding(' Debug.Log ( "a b" ); // ignored')) == audit.baseline_key(finding('Debug.Log("a b");'))
    assert audit.baseline_key(finding('Debug.Log("a  b");')) != audit.baseline_key(finding('Debug.Log("a b");'))


def test_changed_filters_reports_but_keeps_project_index(project, tmp_path):
    result, report = json_run(project, "--changed", "Assets/Scripts/SharedEffects.cs")
    assert result.returncode == 1
    assert {f["file"] for f in report["findings"]} == {"Assets/Scripts/SharedEffects.cs"}
    assert report["findings"][0]["via"] == ["SharedEffects.AllocatePulse"]
    _, clean = json_run(project, "--changed", project / "Assets/Scripts/CleanBehaviour.cs")
    assert clean["total"] == 0
    baseline = tmp_path / "baseline.json"
    updated = run(project, "--changed", "Assets/Scripts/SharedEffects.cs", "--baseline", baseline, "--update-baseline")
    assert updated.returncode == 0
    assert run(project, "--baseline", baseline).returncode == 0


def test_json_schema_and_result_format(project):
    result, report = json_run(project)
    assert set(report) == {"version", "findings", "total", "new", "top_files", "result"}
    assert report["version"] == 1 and report["total"] == len(report["findings"])
    assert report["new"] == report["total"]
    for finding in report["findings"]:
        assert {"rule", "file", "line", "line_text", "method", "hot_method", "via", "sites", "frequency", "score", "key", "is_new"} == set(finding)
        assert isinstance(finding["line"], int) and finding["line"] > 0
        assert finding["rule"] in RULE_IDS
        assert isinstance(finding["via"], list) and finding["is_new"] is True
    assert result.stderr.splitlines()[-1] == report["result"]
    assert re.fullmatch(r"RESULT: FAIL \d+ new", report["result"])
    assert run(project).stdout.splitlines()[-1] == report["result"]


def test_ok_exit_codes_markdown_and_help(project, tmp_path):
    clean = run(project, "--changed", "Assets/Scripts/CleanBehaviour.cs")
    assert clean.returncode == 0
    assert clean.stdout.splitlines()[-1] == "RESULT: OK 0 findings (0 new)"
    md = run(project, "--md")
    assert md.returncode == 1 and "### Assets/Scripts/HotBehaviour.cs" in md.stdout
    assert "File | Score" in md.stdout
    target = tmp_path / "audit.md"
    assert run(project, "--md", target).returncode == 1
    assert target.read_text() == md.stdout
    assert run(project, "-h").returncode == 0
    baseline = tmp_path / "accepted.json"
    updated = run(project, "--baseline", baseline, "--update-baseline")
    assert updated.returncode == 0
    assert re.fullmatch(r"RESULT: OK \d+ findings \(0 new\)", updated.stdout.splitlines()[-1])


@pytest.mark.parametrize("args", [("--unknown",), ("--changed",), ("--update-baseline",), ("--json", "--md")])
def test_usage_errors_exit_two(project, args):
    assert run(project, *args).returncode == 2


def test_input_errors_exit_two(project, tmp_path):
    baseline = tmp_path / "broken.json"
    baseline.write_text("not json")
    assert run(project, "--baseline", baseline).returncode == 2
    baseline.write_text('{"findings": []}')
    assert run(project, "--baseline", baseline).returncode == 2
    assert run(tmp_path / "missing").returncode == 2


def test_discovery_only_assets_and_optional_test_folders(project):
    bad = 'class Ignored { void Update() { Debug.Log("x"); } }'
    for folder in ("Library", "Packages", "Temp", "Assets/Library", "Assets/Packages", "Assets/Temp", "Assets/Combat.Tests", "Assets/Tests"):
        target = project / folder / "Ignored.cs"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(bad)
    _, default = json_run(project)
    assert not any(f["file"].endswith("Ignored.cs") for f in default["findings"])
    _, included = json_run(project, "--include-tests")
    assert {f["file"] for f in included["findings"] if f["file"].endswith("Ignored.cs")} == {
        "Assets/Combat.Tests/Ignored.cs", "Assets/Tests/Ignored.cs",
    }


def test_linq_requires_using_and_expression_body_is_not_lambda(audit):
    text = 'class Test { void Update() => items.Where(Predicate); }'
    assert audit.scan_sources([audit.parse_source("Assets/Test.cs", text)]) == []
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", "using System.Linq; " + text)])
    assert [f["rule"] for f in findings] == ["HOT_LINQ"]


def test_comments_verbatim_and_raw_strings_preserve_offsets(audit):
    text = '''class Test { void Update() {
        var a = "GetComponent( \\"escaped\\"";
        var b = @"Camera.main ""literal""";
        var c = """Debug.Log("raw"); =>""";
        /* Debug.Log("fake");
           Camera.main; */
        Debug.Log("real");
    } }'''
    source = audit.parse_source("Assets/Test.cs", text)
    assert len(source.code) == len(text)
    assert [i for i, c in enumerate(source.code) if c == "\n"] == [i for i, c in enumerate(text) if c == "\n"]
    findings = audit.scan_sources([source])
    assert [(f["rule"], f["line"]) for f in findings] == [("HOT_DEBUG_LOG", 7)]


def test_interpolation_masks_nested_strings_and_calls(audit):
    text = '''class Test { void Update() {
        var label = $"Result: {Lookup("GetComponent( Debug.Log(")}";
        var other = $@"Value: {Lookup(@"Camera.main")} {{literal}}";
        Debug.Log("real");
    } }'''
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert [(f["rule"], f["line"]) for f in findings] == [
        ("HOT_STRING_ALLOC", 2), ("HOT_STRING_ALLOC", 3), ("HOT_DEBUG_LOG", 4),
    ]


def test_wait_only_in_actual_loop_body(audit):
    text = '''class Test { IEnumerator Emit() {
        while (running)
            if (ready) { yield return new WaitForSeconds(1); }
            else { yield return new WaitForSecondsRealtime(2); }
        yield return new WaitForSeconds(3);
        for (;;) for (;;) { yield return new WaitForSeconds(4); }
        yield return new WaitForSeconds(5);
    } }'''
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert [(f["rule"], f["line"], f["sites"]) for f in findings] == [
        ("COROUTINE_NEW_WAIT", 3, 1), ("COROUTINE_NEW_WAIT", 4, 1),
        ("COROUTINE_NEW_WAIT", 6, 1),
    ]


def test_velocity_types_are_scoped_to_class_and_method(audit):
    text = '''class TwoD {
        Rigidbody2D left, right;
        void Move() { left.velocity = right.velocity; }
        void Local(Rigidbody2D body) { body.velocity = Vector2.zero; }
        void Another(Rigidbody body) { body.velocity = Vector3.zero; }
        void Infer() { var local = GetComponent<Rigidbody2D>(); local.velocity = Vector2.zero; }
    }
    class ThreeD {
        Rigidbody body;
        void Move() { body.velocity = Vector3.zero; }
    }'''
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert [(f["method"], f["sites"]) for f in findings] == [
        ("TwoD.Move", 2), ("TwoD.Local", 1), ("TwoD.Infer", 1),
    ]


def test_event_pair_requires_same_event_handler_and_class(audit):
    text = '''namespace A { class Test {
        void OnEnable() { this.Changed += this.Handle; Other += Handle; }
        void OnDisable() { Changed -= Handle; Other -= WrongHandle; }
    } }
    namespace B { class Test {
        void OnEnable() { Changed += Handle; }
    } }'''
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert len(findings) == 2
    assert all(f["rule"] == "EVENT_NO_UNSUBSCRIBE" and f["sites"] == 1 for f in findings)


def test_named_attributes_and_hiding_modifier_keep_hot_methods(audit):
    text = '''class Test {
        [SomeAttribute(Order = 1)]
        public new void Update() { Debug.Log("tick"); }
    }'''
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert [(f["rule"], f["method"]) for f in findings] == [("HOT_DEBUG_LOG", "Test.Update")]


def test_string_variable_and_nested_type_scopes(audit):
    text = '''class Test {
        class Nested { string count; Rigidbody2D body; }
        Rigidbody body;
        void Setup(string count) { }
        void Update() { int count = 1; count = count + 1; body.velocity = Vector3.zero; }
    }'''
    assert audit.scan_sources([audit.parse_source("Assets/Test.cs", text)]) == []


def test_non_event_compound_assignments(audit):
    text = '''class Test {
        int score;
        float time;
        void Start() { this.score += delta; var count = 0; count += 1; }
        void Awake() { time += elapsed; Changed += Handle; }
        void OnDestroy() { Changed -= Handle; }
    }'''
    assert audit.scan_sources([audit.parse_source("Assets/Test.cs", text)]) == []


@pytest.mark.parametrize("body", [
    'var label = "Ready"; label += "!";',
    'var label = $"Ready {1}"; label += suffix;',
    'var label = string.Empty; label += suffix;',
    "var mark = 'a'; mark += (char)1;",
    "var flag = true; flag += other;",
    'string label = Compute(); label += suffix;',
    'String label = Compute(); label += suffix;',
    'inherited += "!";',
])
def test_string_and_literal_compound_assignments_are_not_events(audit, body):
    text = "class Test { void Start() { %s } }" % body
    assert audit.scan_sources([audit.parse_source("Assets/Test.cs", text)]) == []


def test_lifecycle_event_subscription_still_flagged_beside_strings(audit):
    text = 'class Test { void Start() { var label = "Ready"; label += "!"; Changed += Handle; } }'
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert [f["rule"] for f in findings] == ["EVENT_NO_UNSUBSCRIBE"]


@pytest.mark.parametrize("statement", [
    "System.Action work = new System.Action(Refresh);",
    "Action<int> work = new Action<int>(Apply);",
    "var work = new Func<int, bool>(Check);",
    "var work = new UnityEngine.Events.UnityAction(Refresh);",
    "var work = new global::System.Predicate<int>(Check);",
])
def test_explicit_delegate_allocation_in_hot_path(audit, statement):
    text = "class Test { void Update() { %s } void Refresh() { } }" % statement
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert [f["rule"] for f in findings] == ["HOT_LAMBDA"]
    cold = text.replace("Update", "Setup")
    assert audit.scan_sources([audit.parse_source("Assets/Test.cs", cold)]) == []


def test_non_delegate_construction_is_not_lambda(audit):
    text = "class Test { void Update() { var a = new ActionQueue(); var b = new MyAction(1); } }"
    assert audit.scan_sources([audit.parse_source("Assets/Test.cs", text)]) == []


@pytest.mark.parametrize("declaration, expression", [
    ("string first, second;", "second + count"),
    ('string first = "a", second = Join("b", "c"), third;', "third + count"),
    ("", '("Score: ") + count'),
    ("", 'count + ((" points"))'),
    ("string first, second;", "((second)) + count"),
])
def test_string_concat_declarators_and_parenthesized_operands(audit, declaration, expression):
    text = "class Test { %s void Update() { int count = 1; var label = %s; } }" % (declaration, expression)
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert [(f["rule"], f["sites"]) for f in findings] == [("HOT_STRING_ALLOC", 1)]


def test_string_local_declarators_and_numeric_parentheses(audit):
    text = '''class Test { void Update() {
        string first, second;
        var label = second + count;
        var sum = (count) + (other);
    } }'''
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert [(f["rule"], f["line"]) for f in findings] == [("HOT_STRING_ALLOC", 3)]


def test_parenthesized_strings_in_return_and_numeric_call_arguments(audit):
    text = '''class Test {
        void Update() { Label(); var sum = Measure("Score: ") + count; }
        string Label() { return ("Score: ") + count; }
    }'''
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert [(f["rule"], f["line"]) for f in findings] == [("HOT_STRING_ALLOC", 3)]


def test_clean_lifecycle_member_arithmetic(audit):
    text = '''class Test : MonoBehaviour {
        Transform target;
        Vector3 offset;
        void Start() {
            transform.position += Vector3.up;
            this.transform.localPosition += offset;
            target.localScale += Vector3.one;
            offset.x += 1;
            Changed += Handle;
        }
    }'''
    findings = audit.scan_sources([audit.parse_source("Assets/Test.cs", text)])
    assert [(f["rule"], f["line"]) for f in findings] == [("EVENT_NO_UNSUBSCRIBE", 9)]


@pytest.mark.parametrize("namespace", ["namespace Game.Play { %s }", "namespace Game.Play; %s"])
def test_partial_class_teardown_matches_project_wide(audit, namespace):
    subscribe = '''partial class Player {
        void OnEnable() { this.Changed += this.Handle; Other += Handle; }
    }'''
    unsubscribe = '''partial class Player {
        void OnDisable() { Changed -= Handle; Other -= WrongHandle; }
    }'''
    sources = [
        audit.parse_source("Assets/A.cs", namespace % subscribe),
        audit.parse_source("Assets/B.cs", namespace % unsubscribe),
        audit.parse_source("Assets/C.cs", "namespace Other { " + subscribe + " }"),
    ]
    findings = audit.scan_sources(sources)
    assert [(f["file"], f["rule"], f["sites"]) for f in findings] == [
        ("Assets/A.cs", "EVENT_NO_UNSUBSCRIBE", 1),
        ("Assets/C.cs", "EVENT_NO_UNSUBSCRIBE", 2),
    ]
    assert audit.scan_sources(list(reversed(sources))) == findings


def test_partial_class_teardown_respects_nested_class_identity(audit):
    sources = [
        audit.parse_source("Assets/A.cs", '''namespace Game { namespace Play {
            partial class Outer { partial class Player {
                void Awake() { Changed += Handle; }
            } }
        } }'''),
        audit.parse_source("Assets/B.cs", '''namespace Game.Play {
            partial class Outer { partial class Player {
                void OnDestroy() { Changed -= Handle; }
            } }
        }'''),
        audit.parse_source("Assets/C.cs", '''namespace Game.Play {
            class Other { class Player { void Start() { Changed += Handle; } } }
        }'''),
    ]
    findings = audit.scan_sources(sources)
    assert [(f["file"], f["rule"]) for f in findings] == [("Assets/C.cs", "EVENT_NO_UNSUBSCRIBE")]


def test_fixture_directory_cli_result_footer():
    result = run(FIXTURES, "--md")
    assert result.returncode == 1, result.stderr
    assert re.fullmatch(r"RESULT: FAIL \d+ new", result.stdout.splitlines()[-1])


def test_changed_subscription_uses_teardown_in_unchanged_partial_file(tmp_path):
    assets = tmp_path / "Assets"
    assets.mkdir()
    (assets / "A.cs").write_text('''namespace Game {
        partial class Player { void OnEnable() { Changed += Handle; } }
    }''')
    (assets / "B.cs").write_text('''namespace Game {
        partial class Player { void OnDisable() { Changed -= Handle; } }
    }''')
    result, report = json_run(tmp_path, "--changed", "Assets/A.cs")
    assert result.returncode == 0
    assert report["findings"] == []


BACKLOG_SCRIPT = ROOT / "skills/gdd-to-backlog/scripts/backlog_lint.py"
BACKLOG_HEADER = """Current milestone: M0
## M0 Boot
Goal: Boot the game.
Exit: Boot test passes.
Status: active
"""


def backlog_story(number, fields=""):
    sid = "M0-S%02d" % number
    return """### %s Boot
- Status: todo
- Owner skill: architecture-patterns
%s
| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| %s-AC1 | Given boot, When started, Then 1 scene loads | EditMode | test:BootTests.Loads |
""" % (sid, fields, sid)


def run_backlog(tmp_path, stories, *args):
    path = tmp_path / "BACKLOG.md"
    path.write_text(BACKLOG_HEADER + stories, encoding="utf-8")
    return subprocess.run([sys.executable, str(BACKLOG_SCRIPT), str(path), *args],
                          text=True, capture_output=True, check=False)


@pytest.mark.parametrize("fields, visual, critique", [
    ("", None, None),
    ("- Visual: yes", True, None),
    ("- Critique: no", None, False),
    ("- Visual: YeS\n- Critique: nO", True, False),
    ("- vIsUaL: NO\n- cRiTiQuE: YES", False, True),
])
def test_backlog_optional_fields_json(tmp_path, fields, visual, critique):
    result = run_backlog(tmp_path, backlog_story(1, fields), "--json", "--strict")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout[:result.stdout.rfind("\nRESULT:")])
    story = report["milestones"][0]["stories"][0]
    assert story == {
        "id": "M0-S01", "title": "Boot", "status": "todo", "owner": "architecture-patterns",
        "visual": visual, "critique": critique,
        "acs": [{"id": "M0-S01-AC1", "gwt": "Given boot, When started, Then 1 scene loads",
                 "test": "EditMode", "signal": "test:BootTests.Loads"}],
    }


@pytest.mark.parametrize("field", ["Visual", "Critique"])
@pytest.mark.parametrize("value", ["", "true", "false", "1", "maybe", "yes please"])
def test_backlog_optional_fields_reject_invalid_values(tmp_path, field, value):
    result = run_backlog(tmp_path, backlog_story(1, "- %s: %s" % (field, value)))
    assert result.returncode == 1
    assert "story M0-S01 %s '%s' must be yes|no" % (field.lower(), value) in result.stdout
    assert result.stdout.splitlines()[-1] == "RESULT: FAIL 1 error(s), 0 warning(s)"


@pytest.mark.parametrize("field", ["Visual", "Critique"])
@pytest.mark.parametrize("first", ["yes", "no", "invalid"])
def test_backlog_optional_fields_reject_duplicates(tmp_path, field, first):
    fields = "- %s: %s\n- %s: yes" % (field, first, field.upper())
    result = run_backlog(tmp_path, backlog_story(1, fields))
    assert result.returncode == 1
    assert "duplicate '%s' field" % field.lower() in result.stdout
    if first == "invalid":
        assert "must be yes|no" in result.stdout


def test_backlog_optional_fields_are_scoped_to_each_story(tmp_path):
    stories = backlog_story(1, "- Visual: yes\n- Critique: no")
    stories += backlog_story(2, "- Visual: no\n- Critique: yes") + backlog_story(3)
    result = run_backlog(tmp_path, stories, "--json", "--strict")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout[:result.stdout.rfind("\nRESULT:")])
    assert [(s["visual"], s["critique"]) for s in report["milestones"][0]["stories"]] == [
        (True, False), (False, True), (None, None),
    ]


def test_backlog_optional_fields_preserve_text_output(tmp_path):
    original = run_backlog(tmp_path, backlog_story(1), "--milestone", "M0", "--strict")
    explicit = run_backlog(tmp_path, backlog_story(1, "- Visual: no\n- Critique: yes"),
                           "--milestone", "M0", "--strict")
    assert original.returncode == explicit.returncode == 0
    assert original.stdout == explicit.stdout
    assert original.stderr == explicit.stderr == ""
