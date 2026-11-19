"""Regression gates for the prompt improver, run on the frozen 48-prompt corpus.

Every corpus prompt goes through the real PromptImprover.improve (see scripts/eval_prompt_improver.py) with an
isolated AppState, a temporary Unity-like project and a scripted FakeProvider; question cards are auto-answered with
the recommended option. The fake's predictions come from a deterministic cue heuristic, so passing proves the
plumbing, token accounting and bypass rules of the real coordinator hold. It says nothing about how accurate a real
model is.
"""
import asyncio
import importlib.util
import json
import re
import tempfile
from pathlib import Path

import pytest

from gamedevworkstation.features.pi_contracts import TOPICS
from gamedevworkstation.features.pi_research import QUESTION_BANK
from gamedevworkstation.features.prompt_improver import BYPASS_REASONS

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "tests" / "fixtures" / "prompt_improver" / "prompts.json"


def _load_script():
    spec = importlib.util.spec_from_file_location("eval_prompt_improver", REPO / "scripts" / "eval_prompt_improver.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def corpus():
    return json.loads(CORPUS.read_text())


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    mod = _load_script()
    rep = mod.run_fake()
    s = rep["summary"]
    print("\n" + mod.markdown(s, "fake"))
    print("measured:", json.dumps({k: s[k] for k in ("vague_ask_rate", "clear_false_ask_rate", "bypass_accuracy",
                                                     "mean_clear_overhead_tokens", "calls_per_prompt", "cards_per_prompt")}))
    return rep


def test_corpus_schema(corpus):
    ps = corpus["prompts"]
    assert corpus["version"] == 1 and len(ps) == 48
    assert sum(p["label"] == "vague" for p in ps) == 24 and sum(p["label"] == "clear" for p in ps) == 24
    assert len({p["id"] for p in ps}) == 48
    cats = {"mechanics", "scenes", "input", "assets", "performance", "multiplayer", "bugs", "shipping"}
    assert {p["category"] for p in ps} == cats
    for p in ps:
        assert p["prompt"].strip() and p["rationale"].strip()
        assert set(p["context"]) >= {"unity_version", "render_pipeline", "input_handler", "candidates", "docs",
                                     "history", "attached_task", "console"}
        assert len(p["context"]["history"]) <= 3
        assert set(p["expected_missing"]) <= set(QUESTION_BANK)
        assert set(p["expected_missing"]) <= set(TOPICS)
        assert bool(p["expected_missing"]) == (p["label"] == "vague")
        assert set(p["tags"]) <= {"terse", "long", "continuation", "non_english"}
    tags = [t for p in ps for t in p["tags"]]
    assert {"terse", "long", "continuation"} <= set(tags) and tags.count("non_english") == 2
    assert any(p["label"] == "vague" and "long" in p["tags"] for p in ps)
    assert any(p["label"] == "clear" and "terse" in p["tags"] for p in ps)


def test_bypass_corpus_schema(corpus):
    bs = corpus["bypass"]
    assert len({b["id"] for b in bs}) == len(bs)
    reasons = {b["expected_reason"] for b in bs}
    assert reasons <= set(BYPASS_REASONS) | {"ok"}
    assert {"star_prefix", "slash_prefix", "hash_prefix", "scheduled", "not_unity", "ok"} <= reasons
    assert all(b["session"]["folder_kind"] in ("unity", "plain", "none") for b in bs)


def test_fake_model_never_sees_labels(corpus):
    mod = _load_script()
    entry = corpus["prompts"][0]

    async def go():
        base = Path(tempfile.mkdtemp(prefix="pi-eval-test-"))
        app, imp, rec = mod.build_app(base, mod.ScriptedProvider())
        holder: dict = {}
        with mod.corpus_facts(holder):
            r = await mod.improve_one(app, imp, rec, mod.make_project(base), entry, holder)
        return r, rec.inner.calls

    r, calls = asyncio.run(go())
    assert r["error"] is None and r["calls"] == len(calls) >= 1
    first = calls[0].messages[0].text()
    assert first.count(entry["prompt"]) == 1
    assert "expected_missing" not in first and entry["rationale"] not in first


def test_vague_ask_rate(report):
    assert report["summary"]["vague_ask_rate"] >= 0.80


def test_clear_false_ask_rate(report):
    assert report["summary"]["clear_false_ask_rate"] <= 0.10


def test_calls_and_cards_bounded(report):
    assert report["summary"]["errors"] == 0
    assert report["summary"]["calls_per_prompt"]["max"] <= 2
    assert report["summary"]["cards_per_prompt"]["max"] <= 3
    assert all(re.fullmatch(r"[a-z_]+", t) and t in TOPICS for r in report["prompts"] for t in r["topics"])


def test_clear_overhead(report):
    assert report["summary"]["mean_clear_overhead_tokens"] <= 2500


def test_every_bypass_returns_its_reason(report):
    bad = [b for b in report["bypass"] if not b["ok"]]
    assert not bad, bad
    assert report["summary"]["bypass_accuracy"] == 1.0
