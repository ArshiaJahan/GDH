"""Agent Review Desk: reviews, preferences, the labelled dataset, the LLM pre-review and the REST routes,
on a throwaway Eval Forge run directory (no real runs, no model calls except a scripted fake)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.features import review_desk as RD

STREAM = [
    {"type": "system", "subtype": "init", "model": "claude-opus-5-5", "timestamp": "2026-11-20T22:35:00Z"},
    {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "", "signature": "x"},
                                                  {"type": "tool_use", "id": "t1", "name": "Bash",
                                                   "input": {"command": "pytest -q"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "1 failed",
                                              "is_error": True}]}},
    {"type": "result", "subtype": "success", "is_error": False, "result": "Done.", "total_cost_usd": 0.5,
     "num_turns": 3},
]


def make_run(root: Path) -> Path:
    run = root / "runs" / "2026-11-20-x"
    for n, passed in ((1, False), (2, True)):
        d = run / "clamp-task" / "claude_code"
        d.mkdir(parents=True, exist_ok=True)
        trial = {"task": "clamp-task", "agent": "claude_code", "trial": n, "passed": passed,
                 "blame": "" if passed else "agent", "reason": "passed" if passed else "failed command 'tests'",
                 "wall_s": 10.0, "cost_usd": 0.5, "tool_calls": 3, "model": "claude-opus-5-5",
                 "grade": {"passed": passed, "steps": [{"name": "tests", "kind": "command", "passed": passed,
                                                        "exit": 0 if passed else 1, "output": "AssertionError",
                                                        "environment": False}], "tampered": []}}
        (d / f"trial-{n}.json").write_text(json.dumps(trial), encoding="utf-8")
        (d / f"trial-{n}.diff").write_text(f"--- a/s.py\n+++ b/s.py\n@@ -1 +1 @@\n-old\n+new{n}\n", encoding="utf-8")
        (d / f"trial-{n}.log").write_text("\n".join(json.dumps(x) for x in STREAM) + "\nnot json\n", encoding="utf-8")
    (run / "clamp-task" / "claude_code" / "trial-2.prompt.md").write_text("Clamp scores (saved prompt).",
                                                                          encoding="utf-8")
    suite = root / "suite" / "clamp-task"  # evals/runs/X -> evals/suite/<task>/prompt.md for older runs
    suite.mkdir(parents=True)
    (suite / "prompt.md").write_text("Clamp scores (suite prompt).", encoding="utf-8")
    return run


GOOD = {"reviewer": "ali", "verdict": "reject", "scores": {"correctness": 2, "maintainability": 4, "test_quality": 3},
        "failure_mode": "missed_requirement", "tags": ["overreach"], "notes": "misses the upper bound"}


@pytest.fixture
def run(tmp_path):
    return make_run(tmp_path)


def test_a_trial_has_everything_a_reviewer_needs(run):
    t = RD.load_trial(run, "clamp-task/claude_code/1")
    assert t["prompt"] == "Clamp scores (suite prompt)."  # older run: from the suite
    assert RD.load_trial(run, "clamp-task/claude_code/2")["prompt"] == "Clamp scores (saved prompt)."
    assert "+new1" in t["diff"] and t["grade"]["passed"] is False and t["grade"]["steps"][0]["output"] == "AssertionError"
    assert [s["title"] for s in t["steps"]] == ["Started on claude-opus-5-5", "pytest -q", "Finished: 3 turns, $0.5000"]
    assert t["steps"][1]["is_error"] is True and t["steps"][1]["output"] == "1 failed"  # empty thinking dropped
    assert "environment" not in t["grade"]["steps"][0]


@pytest.mark.parametrize("key", ["../x/1", "clamp-task/claude_code/../../1", "a/b", "clamp-task/claude_code/9",
                                 "/etc/passwd/1"])
def test_bad_keys_are_refused(run, key):
    with pytest.raises(RD.ReviewError):
        RD.load_trial(run, key)


def test_reviews_are_validated_and_append_only(run):
    r1 = RD.add_review(run, "clamp-task/claude_code/1", GOOD)
    r2 = RD.add_review(run, "clamp-task/claude_code/1", GOOD | {"verdict": "accept", "failure_mode": "none"})
    assert r1["source"] == "human" and r1["id"] != r2["id"]
    assert len(RD.read_jsonl(run / RD.REVIEWS)) == 2
    summary = RD.run_summary(run)
    assert summary["trials"][0]["human"]["verdict"] == "accept" and summary["trials"][0]["llm"] is None
    for bad in ({"scores": {"correctness": 6, "maintainability": 4, "test_quality": 3}},
                {"scores": {"correctness": 2}}, {"failure_mode": "laziness"}, {"tags": ["nope"]}, {"verdict": "maybe"},
                {"reviewer": ""}):
        with pytest.raises(ValueError):
            RD.add_review(run, "clamp-task/claude_code/1", GOOD | bad)
    # a torn last line (crash mid-write) doesn't lose the others
    with open(run / RD.REVIEWS, "a", encoding="utf-8") as f:
        f.write('{"id": "rv_torn", "key":')
    assert len(RD.read_jsonl(run / RD.REVIEWS)) == 2


def test_preferences_compare_two_trials_of_the_same_task(run):
    p = RD.add_preference(run, {"task": "clamp-task", "a": "clamp-task/claude_code/1", "b": "clamp-task/claude_code/2",
                                "winner": "b", "reason": "b handles the max", "reviewer": "ali"})
    assert p["winner"] == "b"
    for bad in ({"b": "clamp-task/claude_code/1"}, {"task": "other-task"}):
        with pytest.raises(RD.ReviewError):
            RD.add_preference(run, {"task": "clamp-task", "a": "clamp-task/claude_code/1",
                                    "b": "clamp-task/claude_code/2", "winner": "a", "reviewer": "ali"} | bad)


def test_the_dataset_has_reviews_and_preference_pairs(run, tmp_path):
    RD.add_review(run, "clamp-task/claude_code/1", GOOD | {"notes": "older"})
    RD.add_review(run, "clamp-task/claude_code/1", GOOD)  # latest per reviewer wins
    RD.add_review(run, "clamp-task/claude_code/1", GOOD | {"reviewer": "sam", "verdict": "accept"})
    RD.add_review(run, "clamp-task/claude_code/2", GOOD, source="llm:claude-haiku-5-5")  # not a label
    RD.add_preference(run, {"task": "clamp-task", "a": "clamp-task/claude_code/1", "b": "clamp-task/claude_code/2",
                            "winner": "b", "reviewer": "ali"})
    RD.add_preference(run, {"task": "clamp-task", "a": "clamp-task/claude_code/1", "b": "clamp-task/claude_code/2",
                            "winner": "tie", "reviewer": "sam"})
    res = RD.export([run], tmp_path / "out" / "data.jsonl")
    assert (res["reviews"], res["preferences"]) == (2, 2)
    lines = [json.loads(x) for x in (tmp_path / "out" / "data.jsonl").read_text(encoding="utf-8").splitlines()]
    ali = next(x for x in lines if x["type"] == "review" and x["reviewer"] == "ali")
    assert ali["notes"] == "misses the upper bound" and ali["prompt"] == "Clamp scores (suite prompt)."
    assert "+new1" in ali["diff"] and ali["tests_passed"] is False and ali["scores"]["correctness"] == 2
    pref = next(x for x in lines if x["type"] == "preference" and x["winner"] == "b")
    assert "+new2" in pref["chosen"] and "+new1" in pref["rejected"] and pref["b"]["tests_passed"] is True
    tie = next(x for x in lines if x["type"] == "preference" and x["winner"] == "tie")
    assert "chosen" not in tie
    assert not (tmp_path / "out" / "data.tmp").exists()


def test_model_replies_are_normalized():
    r = RD.normalize({"verdict": "ACCEPT", "scores": {"correctness": 9, "maintainability": "2.6"},
                      "failure_mode": "made_up", "tags": ["overreach", "x"], "notes": 5})
    assert r == {"verdict": "reject", "scores": {"correctness": 5, "maintainability": 3, "test_quality": 1},
                 "failure_mode": "other", "tags": ["overreach"], "notes": "5"}
    assert RD.normalize("not a dict")["verdict"] == "reject"


@pytest.fixture
def state(tmp_path):
    from gamedevworkstation.app import AppState
    from gamedevworkstation.providers.fake import FakeProvider

    a = AppState(db_path=tmp_path / "rd.db")
    a.fake = FakeProvider()
    a.providers.override("anthropic", "default", a.fake)
    return a


async def test_prereview_goes_through_the_model_and_is_measured(run, state):
    from gamedevworkstation.providers.fake import text_response

    state.fake.script.append(text_response(json.dumps(
        {"verdict": "reject", "scores": {"correctness": 2, "maintainability": 3, "test_quality": 3},
         "failure_mode": "missed_requirement", "tags": [], "notes": "the max isn't clamped"})))
    r = await RD.prereview_trial(state, run, "clamp-task/claude_code/1")
    assert r["source"].startswith("llm:") and r["failure_mode"] == "missed_requirement"
    body = state.fake.calls[0].messages[0].content[0].text
    assert "untrusted" in body and "+new1" in body and "pytest -q" in body  # diff and trajectory are data, not orders
    assert RD.agreement(run)["n"] == 0  # no human review yet
    RD.add_review(run, "clamp-task/claude_code/1", GOOD)
    ag = RD.agreement(run)
    assert ag["n"] == 1 and ag["verdict_agreement"] == 1.0 and ag["failure_mode_agreement"] == 1.0
    assert ag["score_mae"]["maintainability"] == 1.0 and ag["pairs"][0]["human"] == "reject"


def test_rest_routes(run, state):
    from gamedevworkstation.server import create_app

    c = TestClient(create_app("t", state), headers={"Authorization": "Bearer t"})
    root = str(run.parent)
    runs = c.get("/api/review/runs", params={"root": root}).json()["runs"]
    assert runs[0]["name"] == "2026-11-20-x" and runs[0]["trials"] == 2 and runs[0]["passed"] == 1
    summary = c.get("/api/review/run", params={"dir": str(run)}).json()
    assert [t["key"] for t in summary["trials"]] == ["clamp-task/claude_code/1", "clamp-task/claude_code/2"]
    assert {r["id"] for r in summary["rubric"]} == {"correctness", "maintainability", "test_quality"}
    t = c.get("/api/review/trial", params={"dir": str(run), "key": "clamp-task/claude_code/1"}).json()
    assert t["steps"][1]["tool"] == "Bash"
    assert c.get("/api/review/trial", params={"dir": str(run), "key": "../../x/1"}).status_code == 400
    assert c.get("/api/review/run", params={"dir": root + "/nope"}).status_code == 400
    r = c.post("/api/review/reviews", json={"dir": str(run), "key": "clamp-task/claude_code/1", **GOOD})
    assert r.status_code == 200 and r.json()["source"] == "human"
    bad = c.post("/api/review/reviews", json={"dir": str(run), "key": "clamp-task/claude_code/1",
                                              **GOOD, "source": "llm:fake", "verdict": "nope"})
    assert bad.status_code == 422
    p = c.post("/api/review/preferences", json={"dir": str(run), "task": "clamp-task", "a": "clamp-task/claude_code/1",
                                                "b": "clamp-task/claude_code/2", "winner": "a", "reviewer": "ali"})
    assert p.status_code == 200
    e = c.post("/api/review/export", json={"dir": str(run)}).json()
    assert e["reviews"] == 1 and e["preferences"] == 1 and Path(e["path"]).is_file()


def test_cli(run, capsys):
    RD.add_review(run, "clamp-task/claude_code/1", GOOD)
    assert RD.cli(["export", str(run)]) == 0 and "1 reviews and 0 preference pairs" in capsys.readouterr().out
    assert RD.cli(["agreement", str(run)]) == 1  # nothing to compare yet
    RD.add_review(run, "clamp-task/claude_code/1", GOOD | {"verdict": "accept"}, source="llm:m")
    assert RD.cli(["agreement", str(run)]) == 0 and '"kappa"' in capsys.readouterr().out
    assert RD.cli(["export", str(run / "missing")]) == 2
