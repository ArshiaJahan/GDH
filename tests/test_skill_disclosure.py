"""Progressive skill protocols live in history; only pinned text and the index are cached."""
import importlib.util
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation import skills as sk
from gamedevworkstation.agent import context as cx
from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Message, TextBlock, ToolResultBlock, ToolUseBlock
from gamedevworkstation.features.hookbus import TurnState
from gamedevworkstation.features.session_routes import context_breakdown
from gamedevworkstation.providers.fake import FakeProvider, text_response, tool_response
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}
PROGRESSIVE = {"skill_mode": "progressive", "pinned_skills": ["delegation"], "loaded_skills": []}


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "skills.db")
    a.fake = FakeProvider()
    a.providers.override("anthropic", "default", a.fake)
    a.api = create_app("t", a)
    return a


@pytest.fixture
def env(app):
    with TestClient(app.api) as client:
        yield client, app


def wait_idle(client, sid):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        if not client.get(f"/api/sessions/{sid}", headers=H).json()["running"]:
            return
        time.sleep(0.01)
    raise TimeoutError("skill disclosure test turn did not finish")


def load_message(name):
    return Message(role="user", content=[TextBlock(text=sk.skill_load_text(name))], meta={"skill_load": name})


def add_read(app, sid, name, *, path="", error=False):
    call = ToolUseBlock(id=f"read-{name}-{time.monotonic_ns()}", name="read_skill",
                        input={"name": name, **({"path": path} if path else {})})
    app.store.add_message(sid, Message.assistant(call))
    result = ToolResultBlock.text(call.id, "missing" if error else sk.read_skill_file(name, path), is_error=error)
    app.store.add_message(sid, Message(role="user", content=[result], meta={"tool_results": True}))
    return result


@pytest.mark.parametrize("names", [[], ["delegation"], ["delegation", "graphify", "grill-me"]])
def test_legacy_system_segments_are_byte_equal(names):
    before = sk.skills_prompt(names)
    expected = ["Enabled skills:\n\n" + before] if before else []
    assert sk.system_skill_segments({"skills": names}) == expected
    assert sk.system_skill_segments({"skills": names, "skill_mode": "full", "loaded_skills": ["grilling"],
                                     "pinned_skills": ["graphify"]}) == expected
    assert sk.system_skill_segments({}) == []


@pytest.mark.parametrize("name", ["delegation", "graphify", "play-verify"])
def test_load_text_matches_the_legacy_wrapper(name):
    expected = sk.skills_prompt([name])
    if expected.startswith(sk.TOOL_MAPPING_NOTE):
        expected = expected[len(sk.TOOL_MAPPING_NOTE) + 2:]
    assert sk.skill_load_text(name).encode() == expected.encode()
    assert sk.skill_load_text("missing") == ""


def test_delegation_stays_pinned_even_if_pin_settings_omit_it():
    settings = {**PROGRESSIVE, "pinned_skills": []}
    assert sk.skill_load_text("delegation") in "\n".join(sk.system_skill_segments(settings))
    assert "- delegation:" not in sk.skills_index(settings)
    assert sk.skill_lru(settings, "delegation", 3) == []


def test_index_sorted_excludes_pins_and_limits_descriptions(app):
    app.config.skills["index_description_chars"] = 19
    settings = {**PROGRESSIVE, "pinned_skills": ["delegation", "graphify"]}
    index = sk.skills_index(settings)
    lines = [line for line in index.splitlines() if line.startswith("- ")]
    names = [line[2:].split(": ", 1)[0] for line in lines]
    assert names == sorted(x["name"] for x in sk.list_skills() if x["name"] not in settings["pinned_skills"])
    assert all(len(line.split(": ", 1)[1]) <= 19 for line in lines)
    assert index.endswith("To follow a skill, load it first with read_skill(name); a loaded skill stays loaded until "
                          "the conversation is compacted and it is no longer among the 3 most recent.\n</skill-index>")
    system = sk.system_skill_segments(settings)
    assert sk.skill_load_text("delegation") in system[0]
    assert sk.skill_load_text("graphify") in system[0]
    assert system.count(sk.TOOL_MAPPING_NOTE) == 1 and system[-1] == index


def test_skill_snapshot_uses_turn_state_and_leaves_legacy_live():
    turn = TurnState("snapshot", 0)
    initial = sk.turn_skill_segments(PROGRESSIVE, turn)
    changed = {**PROGRESSIVE, "pinned_skills": ["delegation", "graphify"]}
    assert sk.turn_skill_segments(changed, turn) == initial
    initial.clear()  # callers cannot mutate the stored snapshot
    assert sk.turn_skill_segments(changed, turn)
    assert sk.turn_skill_segments(changed, TurnState("next", 0)) == sk.system_skill_segments(changed)
    legacy_turn = TurnState("legacy", 0)
    assert sk.turn_skill_segments({"skills": ["delegation"]}, legacy_turn) == [
        "Enabled skills:\n\n" + sk.skills_prompt(["delegation"])]
    assert sk.turn_skill_segments({"skills": ["delegation", "graphify"]}, legacy_turn) == [
        "Enabled skills:\n\n" + sk.skills_prompt(["delegation", "graphify"])]
    assert "skill_segments" not in legacy_turn.data


def test_new_http_sessions_follow_disclosure_config_and_global_pins(env):
    c, app = env
    app.db.kv_set("skills_global", ["delegation", "grilling"])
    progressive = c.post("/api/sessions", json={}, headers=H).json()["settings"]
    assert progressive["skill_mode"] == "progressive"
    assert progressive["pinned_skills"] == progressive["skills"] == ["delegation", "grilling"]
    assert progressive["loaded_skills"] == []
    app.config.skills["disclosure"] = "full"
    legacy = c.post("/api/sessions", json={}, headers=H).json()["settings"]
    assert "skill_mode" not in legacy and "pinned_skills" not in legacy and "loaded_skills" not in legacy
    assert sk.system_skill_segments(legacy) == ["Enabled skills:\n\n" + sk.skills_prompt(legacy["skills"])]


@pytest.mark.parametrize("mode", ["progressive", "full"])
def test_scheduled_sessions_follow_disclosure_config(env, mode):
    c, app = env
    app.config.skills["disclosure"] = mode
    app.db.kv_set("skills_global", ["delegation", "grilling"])
    task = c.post("/api/tasks", json={"name": "Skill check", "prompt": "follow the protocols",
                                    "schedule": "every:30m", "enabled": False}, headers=H).json()
    response = c.post(f"/api/tasks/{task['id']}/run", headers=H)
    assert response.status_code == 200
    sid = response.json()["session_id"]
    wait_idle(c, sid)
    settings = app.store.get(sid)["settings"]
    assert settings["scheduled_task"] == task["id"]
    assert settings["skills"] == ["delegation", "grilling"]
    if mode == "progressive":
        assert settings["skill_mode"] == "progressive"
        assert settings["pinned_skills"] == settings["skills"] and settings["loaded_skills"] == []
        assert "<skill-index>" in "\n".join(app.fake.calls[-1].system)
    else:
        assert not {"skill_mode", "pinned_skills", "loaded_skills"} & settings.keys()
        assert app.fake.calls[-1].system[1] == "Enabled skills:\n\n" + sk.skills_prompt(settings["skills"])


def test_store_creation_defaults_do_not_migrate_existing_sessions(app):
    app.config.skills["disclosure"] = "full"
    sid = app.store.create()["id"]
    app.config.skills["disclosure"] = "progressive"
    assert "skill_mode" not in app.store.get(sid)["settings"]
    settings = app.store.create()["settings"]
    assert settings["skill_mode"] == "progressive"
    assert settings["pinned_skills"] == ["delegation"] and settings["loaded_skills"] == []


def test_invoking_inserts_once_before_user_and_reloads_after_clear(env, monkeypatch):
    c, app = env
    enabled = []
    monkeypatch.setattr(app.mcp, "enable_for_skills", lambda sid, names: enabled.extend(names))
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    app.fake.script = [text_response("first"), text_response("again"), text_response("after clear")]
    initial = app.runner.system_segments(app.store.get(sid))
    for _ in range(2):
        r = c.post(f"/api/sessions/{sid}/messages", json={"text": "my plan", "skill": "grill-me"}, headers=H)
        assert r.status_code == 200
        wait_idle(c, sid)
    messages = app.store.messages(sid)
    loads = [m for m in messages if m.meta.get("skill_load")]
    assert len(loads) == 1 and messages[0] == loads[0]
    assert loads[0].role == "user" and loads[0].meta["skill_load"] == "grill-me"
    assert loads[0].text() == sk.skill_load_text("grill-me")
    assert messages[1].meta["invoked_skill"] == "grill-me"
    assert messages[1].text() == "Use the grill-me skill.\n\nmy plan"
    settings = app.store.get(sid)["settings"]
    assert settings["loaded_skills"] == ["grill-me"] and settings["skills"] == ["delegation", "grill-me"]
    assert enabled == ["grill-me", "grill-me"]
    assert all(call.system == initial for call in app.fake.calls)
    assert app.store.get(sid)["title"] == "my plan"
    app.store.clear(sid)
    c.post(f"/api/sessions/{sid}/messages", json={"skill": "grill-me"}, headers=H)
    wait_idle(c, sid)
    assert [m.meta["skill_load"] for m in app.runner.model_history(sid) if m.meta.get("skill_load")] == ["grill-me"]


@pytest.mark.parametrize("skill", ["grill-me", "high-performance-claude-delegation"])
def test_legacy_invocation_has_no_load_and_keeps_full_system_prompt(env, skill):
    c, app = env
    app.config.skills["disclosure"] = "full"
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    app.config.skills["disclosure"] = "progressive"  # an existing session still uses legacy disclosure
    c.post(f"/api/sessions/{sid}/messages", json={"text": "launch plan", "skill": skill}, headers=H)
    wait_idle(c, sid)
    messages = app.store.messages(sid)
    assert messages[0].meta["invoked_skill"] == skill
    assert not any(m.meta.get("skill_load") for m in messages)
    assert "loaded_skills" not in app.store.get(sid)["settings"]
    assert app.fake.calls[-1].system[1] == "Enabled skills:\n\n" + sk.skills_prompt(["delegation", skill])


def test_pinned_invocation_does_not_take_an_lru_slot(env):
    c, app = env
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    c.post(f"/api/sessions/{sid}/messages", json={"skill": "delegation"}, headers=H)
    wait_idle(c, sid)
    assert app.store.get(sid)["settings"]["loaded_skills"] == []
    assert not any(m.meta.get("skill_load") for m in app.store.messages(sid))
    assert sk.skill_load_text("delegation") in "\n".join(app.fake.calls[-1].system)


async def test_system_is_byte_identical_across_every_model_call_when_skills_are_read(app):
    s = app.store.create(**PROGRESSIVE)
    initial = app.runner.system_segments(s)
    app.fake.script = [tool_response("read_skill", {"name": n}) for n in
                       ("graphify", "grilling", "game-designer", "grill-me", "graphify", "delegation")]
    app.fake.script.append(text_response("done"))
    app.store.add_message(s["id"], Message.user("follow these protocols"))
    await app.runner.start(s["id"])
    assert len(app.fake.calls) == 7
    assert all(call.system == initial for call in app.fake.calls)
    settings = app.store.get(s["id"])["settings"]
    assert settings["loaded_skills"] == ["game-designer", "grill-me", "graphify"]
    assert settings["skills"] == ["delegation"]
    updates = [e["data"] for e in app.bus.replay(0, s["id"]) if e["type"] == "session.updated"]
    assert any(e["settings"].get("loaded_skills") == settings["loaded_skills"] for e in updates)
    assert app.runner.system_segments(app.store.get(s["id"])) == initial


async def test_turn_snapshot_survives_catalog_and_pin_changes_and_refreshes_next_turn(app):
    sk.save_skill("wp1-pinned", "---\nname: wp1-pinned\ndescription: Original pin.\n---\nOriginal pinned protocol")
    sk.save_skill("wp1-indexed", "---\nname: wp1-indexed\ndescription: Original index.\n---\nProtocol")
    s = app.store.create(**{**PROGRESSIVE, "pinned_skills": ["delegation", "wp1-pinned"]})
    sid = s["id"]
    initial = app.runner.system_segments(s)

    def edit_during_turn(req):
        sk.save_skill("wp1-pinned", "---\nname: wp1-pinned\ndescription: Updated pin.\n---\nChanged pinned protocol")
        sk.save_skill("wp1-indexed", "---\nname: wp1-indexed\ndescription: Changed index.\n---\nProtocol")
        app.store.update(sid, settings={"pinned_skills": ["delegation", "graphify"]})
        app.config.skills["index_description_chars"] = 10
        assert app.runner.system_segments(app.store.get(sid)) == req.system
        breakdown = context_breakdown(app, sid)
        assert breakdown["skill_parts"]["pinned"] == cx.est(initial[1])
        return tool_response("read_skill", {"name": "grilling"})

    app.fake.script = [edit_during_turn, text_response("done"), text_response("next turn")]
    app.store.add_message(sid, Message.user("use the current catalog"))
    await app.runner.start(sid)
    assert len(app.fake.calls) == 2 and all(call.system == initial for call in app.fake.calls)
    app.store.add_message(sid, Message.user("use the updated catalog"))
    await app.runner.start(sid)
    refreshed = app.fake.calls[-1].system
    assert refreshed != initial
    assert sk.skill_load_text("graphify") in "\n".join(refreshed)
    assert "- wp1-indexed: Changed in\n" in "\n".join(refreshed)
    assert "Original pinned protocol" not in "\n".join(refreshed)


async def test_read_skill_only_tracks_successful_main_agent_full_reads(app):
    app.config.skills["max_loaded"] = 2
    s = app.store.create(**PROGRESSIVE)
    ctx = ToolContext(app=app, session=s, run_id="main:skills")
    for n in ("grilling", "graphify", "grill-me", "graphify"):
        assert not (await app.tools.run(ctx, "read_skill", {"name": n})).is_error
    assert app.store.get(s["id"])["settings"]["loaded_skills"] == ["grill-me", "graphify"]
    for args in ({"name": "game-designer", "path": "templates/one-page-concept.md"},
                 {"name": "missing"}, {"name": "game-designer", "path": "missing"}):
        await app.tools.run(ctx, "read_skill", args)
    for role in ("subagent", "hook"):
        child = ToolContext(app=app, session=s, run_id=role + ":skills", role=role)
        await app.tools.run(child, "read_skill", {"name": "game-designer"})
    assert app.store.get(s["id"])["settings"]["loaded_skills"] == ["grill-me", "graphify"]
    app.config.skills["disclosure"] = "full"
    legacy = app.store.create()
    app.config.skills["disclosure"] = "progressive"
    await app.tools.run(ToolContext(app=app, session=legacy, run_id="main:old"), "read_skill", {"name": "graphify"})
    assert "loaded_skills" not in app.store.get(legacy["id"])["settings"]
    app.config.skills["max_loaded"] = 0
    await app.tools.run(ctx, "read_skill", {"name": "graphify"})
    assert app.store.get(s["id"])["settings"]["loaded_skills"] == []


def test_invocation_after_read_skill_does_not_duplicate_load(env):
    c, app = env
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    app.fake.script = [tool_response("read_skill", {"name": "grilling"}), text_response("loaded"), text_response("done")]
    c.post(f"/api/sessions/{sid}/messages", json={"text": "load the interview protocol"}, headers=H)
    wait_idle(c, sid)
    c.post(f"/api/sessions/{sid}/messages", json={"skill": "grilling"}, headers=H)
    wait_idle(c, sid)
    assert not any(m.meta.get("skill_load") for m in app.store.messages(sid))
    assert app.store.get(sid)["settings"]["loaded_skills"] == ["grilling"]


@pytest.mark.parametrize("cap, truncated", [(30_000, True), (100_000, False)])
def test_graphify_invocation_after_read_only_deduplicates_full_protocol(env, cap, truncated):
    c, app = env
    app.config.orchestrator["tool_output_chars"] = cap
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    app.fake.script = [tool_response("read_skill", {"name": "graphify"}), text_response("read"),
                       text_response("invoked"), text_response("again")]
    c.post(f"/api/sessions/{sid}/messages", json={"text": "read graphify"}, headers=H)
    wait_idle(c, sid)
    history = app.runner.model_history(sid)
    result = next(b for m in history for b in m.content if isinstance(b, ToolResultBlock))
    assert ("[Output cut at " in result.as_text()) == truncated
    assert ("graphify" in cx.skill_load_positions(history)) == (not truncated)
    c.post(f"/api/sessions/{sid}/messages", json={"skill": "graphify"}, headers=H)
    wait_idle(c, sid)
    c.post(f"/api/sessions/{sid}/messages", json={"skill": "graphify"}, headers=H)
    wait_idle(c, sid)
    loads = [m for m in app.runner.model_history(sid) if m.meta.get("skill_load") == "graphify"]
    assert len(loads) == int(truncated)
    if loads:
        assert loads[0].text() == sk.skill_load_text("graphify")
        assert len(loads[0].text()) > cap
    assert app.store.get(sid)["settings"]["loaded_skills"] == ["graphify"]


async def test_compaction_reinjects_each_lru_skill_once_in_order_and_drops_evicted(app):
    retained = ["compile-fix-loop", "play-verify", "perf-pass"]
    s = app.store.create(**{**PROGRESSIVE, "loaded_skills": retained})
    sid = s["id"]
    app.store.add_message(sid, Message.user("build the game"))
    app.store.add_message(sid, load_message("unity-router"))  # evicted
    add_read(app, sid, retained[0])
    for n in (retained[1], retained[1], retained[2]):
        app.store.add_message(sid, load_message(n))
    cut = len(app.runner.model_history(sid))
    app.store.add_message(sid, Message.user("keep going"))
    app.store.add_message(sid, Message.assistant("working"))
    initial = app.runner.system_segments(s)
    app.fake.script = [text_response("summary"), text_response("second summary")]
    await cx.compact_messages(app, sid, app.runner.model_history(sid), cut, auto=True)
    active = app.runner.model_history(sid)
    assert active[0].meta.get("summary") and active[0].meta.get("auto")
    assert [m.meta.get("skill_load") for m in active[1:4]] == retained
    assert [m.text() for m in active[4:]] == ["keep going", "working"]
    assert [m.meta["skill_load"] for m in active if m.meta.get("skill_load")] == retained
    assert all(m.meta["compacted"] for m in app.store.messages(sid) if m.id not in {a.id for a in active})
    await cx.compact_messages(app, sid, active, 4)
    active = app.runner.model_history(sid)
    assert active[0].meta.get("summary")
    assert [m.meta["skill_load"] for m in active if m.meta.get("skill_load")] == retained
    assert app.runner.system_segments(app.store.get(sid)) == initial


async def test_compaction_leaves_latest_kept_loads_alone_and_ignores_failed_reads(app):
    s = app.store.create(**{**PROGRESSIVE, "loaded_skills": ["grilling", "grill-me", "game-designer"]})
    sid = s["id"]
    app.store.add_message(sid, load_message("grilling"))
    add_read(app, sid, "grill-me")
    add_read(app, sid, "game-designer", error=True)
    cut = len(app.runner.model_history(sid))
    app.store.add_message(sid, Message.user("keep this turn"))
    add_read(app, sid, "grilling")
    app.fake.script = [text_response("summary")]
    await cx.compact_messages(app, sid, app.runner.model_history(sid), cut)
    active = app.runner.model_history(sid)
    assert active[0].meta.get("summary") and active[1].meta.get("skill_load") == "grill-me"
    assert [m.meta["skill_load"] for m in active if m.meta.get("skill_load")] == ["grill-me"]
    assert "grilling" in cx.skill_load_positions(active) and "game-designer" not in cx.skill_load_positions(active)
    assert cx._pairs_intact(active)


async def test_compaction_keeps_full_protocol_when_latest_read_was_truncated(app):
    s = app.store.create(**{**PROGRESSIVE, "loaded_skills": ["graphify"]})
    sid = s["id"]
    app.store.add_message(sid, Message.user("inspect the project"))
    app.store.add_message(sid, load_message("graphify"))
    cut = len(app.runner.model_history(sid))
    app.store.add_message(sid, Message.user("read graphify again"))
    call = ToolUseBlock(id="cut-read", name="read_skill", input={"name": "graphify"})
    app.store.add_message(sid, Message.assistant(call))
    result = await app.tools.run(ToolContext(app=app, session=s, run_id="main:cut-read"), "read_skill", call.input)
    assert "[Output cut at " in result.text
    app.store.add_message(sid, Message(role="user", content=[result.to_block(call.id)], meta={"tool_results": True}))
    app.fake.script = [text_response("summary")]
    await cx.compact_messages(app, sid, app.runner.model_history(sid), cut)
    history = app.runner.model_history(sid)
    assert history[0].meta.get("summary")
    assert history[1].meta.get("skill_load") == "graphify"
    assert history[1].text() == sk.skill_load_text("graphify")
    assert cx.skill_load_positions(history) == {"graphify": 1}


async def test_compaction_reinjects_skill_whose_only_load_was_a_truncated_read(app):
    s = app.store.create(**{**PROGRESSIVE, "loaded_skills": ["graphify"]})
    sid = s["id"]
    app.store.add_message(sid, Message.user("read graphify"))
    call = ToolUseBlock(id="cut-only", name="read_skill", input={"name": "graphify"})
    app.store.add_message(sid, Message.assistant(call))
    result = await app.tools.run(ToolContext(app=app, session=s, run_id="main:cut-only"), "read_skill", call.input)
    assert "[Output cut at " in result.text
    app.store.add_message(sid, Message(role="user", content=[result.to_block(call.id)], meta={"tool_results": True}))
    cut = len(app.runner.model_history(sid))
    assert "graphify" not in cx.skill_load_positions(app.runner.model_history(sid))
    app.store.add_message(sid, Message.user("keep going"))
    app.store.add_message(sid, Message.assistant("working"))
    app.fake.script = [text_response("summary")]
    await cx.compact_messages(app, sid, app.runner.model_history(sid), cut)
    history = app.runner.model_history(sid)
    assert history[0].meta.get("summary")
    assert history[1].meta.get("skill_load") == "graphify"
    assert history[1].text() == sk.skill_load_text("graphify")
    assert [m.text() for m in history[2:]] == ["keep going", "working"]


async def test_compaction_preserves_real_goal_instead_of_skill_protocol(app):
    s = app.store.create(**{**PROGRESSIVE, "loaded_skills": ["grilling"]})
    sid = s["id"]
    app.store.add_message(sid, Message.user("GOAL: build the requested feature"))
    app.store.add_message(sid, load_message("grilling"))
    app.store.add_message(sid, Message.assistant("working"))
    app.fake.script = [text_response("summary")]
    await cx.compact_messages(app, sid, app.runner.model_history(sid), 2)
    active = app.runner.model_history(sid)
    assert "GOAL: build the requested feature" in active[0].text()
    assert active[1].meta["skill_load"] == "grilling" and not cx.is_user_turn(active[1])


def test_context_breakdown_splits_system_and_history_skills_without_double_counting(app):
    s = app.store.create(**PROGRESSIVE)
    sid = s["id"]
    app.store.add_message(sid, Message.user("do the work"))
    app.store.add_message(sid, load_message("grilling"))
    result = add_read(app, sid, "grill-me")
    ctx = context_breakdown(app, sid)
    split = ctx["skill_parts"]
    assert split["pinned"] == cx.est("Enabled skills:\n\n" + sk.skill_load_text("delegation"))
    assert split["index"] > 0
    assert split["loaded"] == cx.est(sk.skill_load_text("grilling")) + sum(cx.block_tokens(result))
    assert ctx["parts"]["skills"] == sum(split.values())
    expected = (cx.est("\n".join(app.runner.system_segments(s)))
                + ctx["parts"]["tools"] + cx.messages_tokens(app.runner.model_history(sid)))
    assert ctx["total"] == sum(ctx["parts"].values()) == expected
    app.config.skills["disclosure"] = "full"
    assert "skill_parts" not in context_breakdown(app, app.store.create()["id"])


def test_progressive_unity_pipeline_saves_at_least_30k_system_tokens():
    path = Path(__file__).resolve().parents[1] / "scripts" / "skill_tokens.py"
    spec = importlib.util.spec_from_file_location("skill_tokens", path)
    measurement = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measurement)
    scenarios = measurement.scenarios()
    legacy = measurement.system_tokens(scenarios[1][1])
    progressive = measurement.system_tokens(scenarios[2][1])
    assert legacy - progressive >= 30_000, (legacy, progressive)
    assert sk.skill_load_text("delegation") in "\n".join(sk.system_skill_segments(scenarios[2][1]))
