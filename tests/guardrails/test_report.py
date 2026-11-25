"""Contract tests for guardrail report loading and threshold logic."""
import json

import pytest

from tests.guardrails.report import CaseResult, KnownGap, evaluate, load_cases, load_known_gaps, summary_line, to_json


def result(i, vector="web", klass="must_block", blocked=True, wrapped=True):
    return CaseResult(str(i), vector, klass, "refused", blocked, "approval_card", "approval_card", wrapped)


def population():
    vectors = ("web", "console", "asset", "commit", "mcp", "subagent", "direct_delete", "direct_secret")
    return [result(i, vectors[i % len(vectors)]) for i in range(32)]


def test_catalogue_loads():
    assert len(load_cases()) == 48


def test_loader_rejects_schema_and_duplicate(tmp_path):
    case = {"id": "x", "vector": "bad"}
    (tmp_path / "a.json").write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    with pytest.raises(ValueError, match="top-level keys"):
        load_cases(tmp_path)


def test_loader_requires_carrier_wrapped(tmp_path):
    case = {
        "id": "x", "vector": "web", "title": "title", "payload": "payload",
        "carrier": None, "attack": [{"tool": "run_command", "args": {}}],
        "surface": "loop", "mode": "ask", "role": "main", "setup": {},
        "class": "must_block", "expect": {"enforcement": "approval_card"}, "gap": None,
    }
    (tmp_path / "a.json").write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    with pytest.raises(ValueError, match="expect requires carrier_wrapped"):
        load_cases(tmp_path)


def test_rates_and_json():
    rows = population()
    rows.append(result("design", "web", "by_design", False))
    report = evaluate(rows, [])
    assert report.block_rate() == (32, 32, 1.0)
    assert to_json(report)["schema"] == 1
    assert summary_line(report) == "guardrail block rate: 32/32 (100.0%) | must_block 32/32 blocked | known gaps 0 | unwrapped carriers 0 (G6) | by_design 1"


def test_gap_status_and_wrap_gaps():
    rows = population()
    rows[0] = result("W01", blocked=False, wrapped=False)
    report = evaluate(rows, [KnownGap("W01", "G1", "reason")], [KnownGap("W01", "G6", "reason")])
    assert report.verdicts[0].status == "known_gap"
    assert report.unwrapped == 1


def test_known_gaps_require_reason(tmp_path):
    path = tmp_path / "g.toml"
    path.write_text('[[gap]]\nid="x"\ngap="G1"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_known_gaps(path)
