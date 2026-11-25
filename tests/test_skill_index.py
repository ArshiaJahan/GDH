"""The progressive skill index: short index hints, Unity-only skills hidden outside Unity projects,
user-only skills left out, the token budget, and an offline check that the hints still trigger."""
import importlib.util
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation import skills as sk
from gamedevworkstation.agent import context as cx
from gamedevworkstation.app import AppState
from gamedevworkstation.features.hookbus import HookEvent
from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.providers.fake import FakeProvider, text_response
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}
P = {"skill_mode": "progressive", "pinned_skills": ["delegation"], "loaded_skills": []}
ALWAYS_LISTED = {"unity-router", "game-designer", "gdd-to-backlog"}  # planning or starting a game needs no project yet
HINT_MAX_CHARS = 200

# Token budget for the index (cx.est), paid on every call of every progressive session.
INDEX_MAX_UNITY = 1300
INDEX_MAX_OUTSIDE_UNITY = 600

_spec = importlib.util.spec_from_file_location("skill_trigger_cases", Path(__file__).with_name("skill_trigger_cases.py"))
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "index.db")
    a.fake = FakeProvider()
    a.providers.override("anthropic", "default", a.fake)
    a.api = create_app("t", a)
    return a


def unity_folder(tmp_path: Path) -> Path:
    d = tmp_path / "MyGame"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n", encoding="utf-8")
    return d


def listed(settings: dict) -> list[str]:
    return [line[2:].split(":", 1)[0] for line in sk.skills_index(settings).splitlines() if line.startswith("- ")
            and not line.startswith("- (")]


def indexed_builtins() -> list[dict]:
    return [s for s in sk.list_skills() if s["source"] == "builtin" and s["model_invocable"]
            and s["name"] not in sk.pinned_skill_names(P)]


# ------------------------------------------------------------------ hints


def test_every_indexed_builtin_has_a_short_hint_and_keeps_its_description():
    for s in indexed_builtins():
        assert s["index_hint"], f"{s['name']} has no index-hint"
        assert len(s["index_hint"]) <= HINT_MAX_CHARS, s["name"]
        assert s["description"] and len(s["index_hint"]) < len(s["description"]), s["name"]


def test_index_uses_hints_and_falls_back_to_descriptions(app):
    sk.save_skill("no-hint", "---\nname: no-hint\ndescription: A user skill without a hint.\n---\nBody")
    index = sk.skills_index(P)
    router = next(s for s in sk.list_skills() if s["name"] == "unity-router")
    assert f"- unity-router: {router['index_hint']}" in index
    assert router["description"] not in index
    assert "- no-hint: A user skill without a hint." in index
    app.config.skills["index_hints"] = False
    try:
        assert f"- unity-router: {' '.join(router['description'].split())[:300]}" in sk.skills_index(P)
    finally:
        app.config.skills["index_hints"] = True


def test_user_only_skills_are_not_offered_to_the_model():
    handoff = next(s for s in sk.list_skills() if s["name"] == "claude-handoff")
    assert handoff["model_invocable"] is False
    assert "claude-handoff" not in listed(P)
    assert sk.read_skill_file("claude-handoff")  # still readable, and invocable from the composer


def test_hints_trigger_as_well_as_descriptions():
    """Word-overlap stand-in for the model's choice: the expected skill ranks in the top 3 from its
    hint for every request, and the hints rank first at least as often as the full descriptions."""
    skills = [s for s in sk.list_skills() if s["model_invocable"] and s["name"] != "delegation"]
    hints = {s["name"]: s["index_hint"] or s["description"] for s in skills}
    descriptions = {s["name"]: s["description"] for s in skills}
    assert tc.hits(hints) == []
    first = lambda lines: sum(1 for r, e in tc.CASES if tc.rank(r, lines)[:1] and tc.rank(r, lines)[0] in e)  # noqa: E731
    assert first(hints) >= first(descriptions)
    assert {n for _r, e in tc.CASES for n in e} >= {s["name"] for s in indexed_builtins()} - {"claude-handoff"}


# ------------------------------------------------------------------ Unity-only skills


def test_unity_skills_are_hidden_only_when_the_session_is_known_not_to_be_unity():
    unity_only = {s["name"] for s in sk.list_skills() if s["requires"] == "unity-project"}
    assert {"compile-fix-loop", "unity-practices", "scene-prefab-safety", "play-verify"} <= unity_only
    assert not unity_only & ALWAYS_LISTED
    for settings in (P, {**P, "unity_project": True}):
        assert unity_only <= set(listed(settings))
        assert "Unity project skills are not listed" not in sk.skills_index(settings)
    outside = {**P, "unity_project": False}
    names = set(listed(outside))
    assert not names & unity_only and ALWAYS_LISTED <= names
    assert f"- ({len(unity_only)} Unity project skills are not listed" in sk.skills_index(outside)
    assert sk.read_skill_file("compile-fix-loop")  # hidden from the index, still readable


def test_hiding_can_be_turned_off(app):
    app.config.skills["hide_unity_skills_outside_unity"] = False
    try:
        assert "compile-fix-loop" in listed({**P, "unity_project": False})
    finally:
        app.config.skills["hide_unity_skills_outside_unity"] = True


def test_unity_project_flag(tmp_path):
    assert sk.unity_project_flag(None) is False and sk.unity_project_flag("") is False
    assert sk.unity_project_flag(str(tmp_path)) is False
    assert sk.unity_project_flag(str(unity_folder(tmp_path))) is True
    assert sk.unity_project_flag(str(tmp_path / "not-yet")) is None


def test_flag_is_frozen_at_creation_and_kept_stable_through_turns(app, tmp_path):
    plain = app.store.create(folder=str(tmp_path))
    game = app.store.create(folder=str(unity_folder(tmp_path)))
    missing = app.store.create(folder=str(tmp_path / "later"))
    assert plain["settings"]["unity_project"] is False and game["settings"]["unity_project"] is True
    assert "unity_project" not in missing["settings"]
    legacy = app.store.create(skill_mode="full")
    assert "unity_project" not in legacy["settings"]

    initial = app.runner.system_segments(plain)
    assert "Unity project skills are not listed" in next(seg for seg in initial if "<skill-index>" in seg)
    app.fake.script = [text_response("one"), text_response("two")]
    with TestClient(app.api) as c:
        for text in ("hello", "again"):
            c.post(f"/api/sessions/{plain['id']}/messages", json={"text": text}, headers=H)
            until = time.monotonic() + 5
            while c.get(f"/api/sessions/{plain['id']}", headers=H).json()["running"] and time.monotonic() < until:
                time.sleep(0.01)
    assert len(app.fake.calls) == 2 and all(call.system == initial for call in app.fake.calls)


async def test_session_start_hook_fills_in_a_folder_that_appeared(app, tmp_path):
    later = tmp_path / "later"
    s = app.store.create(folder=str(later))
    assert "unity_project" not in s["settings"]
    (later / "ProjectSettings").mkdir(parents=True)
    (later / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n", encoding="utf-8")
    from gamedevworkstation.features.hooks import get_engine, install

    eng = get_engine(app) or install(app)
    await eng.context_pack(HookEvent("session_start", ToolContext(app=app, session=s, run_id="main:x")))
    assert app.store.get(s["id"])["settings"]["unity_project"] is True


# ------------------------------------------------------------------ budget


def test_index_token_budget():
    before = cx.est("\n".join(["<skill-index>", *(f"- {s['name']}: {' '.join(s['description'].split())[:300]}"
                                                    for s in sorted(sk.list_skills(), key=lambda s: s["name"])
                                                    if s["name"] not in sk.pinned_skill_names(P)), "</skill-index>"]))
    unity = cx.est(sk.skills_index({**P, "unity_project": True}))
    outside = cx.est(sk.skills_index({**P, "unity_project": False}))
    assert unity <= INDEX_MAX_UNITY and outside <= INDEX_MAX_OUTSIDE_UNITY
    assert unity <= before * 0.6  # at least 40% cheaper than description lines
    assert outside <= before * 0.3


def test_savings_baseline_still_counts_every_skill():
    """The Context card's "full" baseline hides nothing: a full session carries every skill."""
    text = sk.full_disclosure_text({**P, "unity_project": False})
    assert sk.skill_load_text("compile-fix-loop") in text and sk.skill_load_text("claude-handoff") not in text
