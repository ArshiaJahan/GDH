"""unity-practices: progressive loading and unloading, the token budget, the skill's scripts, and
the Context card's token-savings and API-price numbers."""
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation import skills as sk
from gamedevworkstation.agent import context as cx
from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Message, TextBlock, Usage
from gamedevworkstation.features.session_routes import context_breakdown
from gamedevworkstation.features.skill_unload import unload
from gamedevworkstation.providers.fake import FakeProvider, text_response
from gamedevworkstation.server import create_app

NAME = "unity-practices"
ROOT = Path(__file__).resolve().parents[1] / "skills" / NAME
SCRIPTS = ROOT / "scripts"
H = {"Authorization": "Bearer t"}
PROGRESSIVE = {"skill_mode": "progressive", "pinned_skills": ["delegation"], "loaded_skills": []}
TOPICS = ["coding", "enemies", "pooling", "textures", "performance", "readable-code", "tuning", "debug-tools"]

# Token budget (Context card estimate, cx.est). The index line is paid on every call of every
# progressive session; the rest only when the skill is used.
INDEX_LINE_MAX = 90
LOAD_MAX = 800
REFERENCE_MAX = 800


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "unity-practices.db")
    a.fake = FakeProvider()
    a.providers.override("anthropic", "default", a.fake)
    a.api = create_app("t", a)
    return a


def run(script: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd, timeout=60, stdin=subprocess.DEVNULL)


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ discovery and budget


def test_skill_is_discovered_and_routes_every_topic():
    s = next(x for x in sk.list_skills() if x["name"] == NAME)
    assert s["source"] == "builtin" and not s["native"]  # written to work in Claude Code too
    meta, body = sk.parse_skill((ROOT / "SKILL.md").read_text(encoding="utf-8"))
    assert meta["name"] == NAME and meta.get("argument-hint")
    files = sk.skill_files(NAME)
    for topic in TOPICS:
        assert f"references/{topic}.md" in files
        assert f"`references/{topic}.md`" in body  # the router table names every reference
    for script in ("cs_lint.py", "texture_audit.py", "scaffold.py", "issue_cache.py"):
        assert f"scripts/{script}" in files and script in body


def test_token_budget():
    line = next(x for x in sk.skills_index(PROGRESSIVE).splitlines() if x.startswith(f"- {NAME}:"))
    assert cx.est(line) <= INDEX_LINE_MAX
    assert cx.est(sk.skill_load_text(NAME)) <= LOAD_MAX
    refs = {p.stem: cx.est(p.read_text(encoding="utf-8")) for p in (ROOT / "references").glob("*.md")}
    assert set(refs) == set(TOPICS)
    assert max(refs.values()) <= REFERENCE_MAX
    # Progressive disclosure pays off: a typical task (SKILL.md + one reference) costs well under a
    # third of one file holding everything.
    monolith = cx.est(sk.skill_load_text(NAME)) + sum(refs.values())
    assert cx.est(sk.skill_load_text(NAME)) + max(refs.values()) < monolith / 3


def test_system_prompt_grows_only_by_the_index_line():
    without = {**PROGRESSIVE}
    segs = sk.system_skill_segments(without)
    text = "\n".join(segs)
    assert sk.skill_load_text(NAME) not in text  # the body never sits in the cached system prompt
    line = next(x for x in sk.skills_index(without).splitlines() if x.startswith(f"- {NAME}:"))
    stripped = text.replace(line + "\n", "")
    assert cx.est(text) - cx.est(stripped) <= INDEX_LINE_MAX
    # Pinned, it is in full (that's the user's choice).
    pinned = sk.system_skill_segments({**PROGRESSIVE, "pinned_skills": ["delegation", NAME]})
    assert sk.skill_load_text(NAME) in "\n".join(pinned)


# ------------------------------------------------------------------ loading and unloading


async def test_load_reference_then_unload(app):
    s = app.store.create(**PROGRESSIVE)
    sid = s["id"]
    ctx = ToolContext(app=app, session=s, run_id="main:unity")
    out = await app.tools.run(ctx, "read_skill", {"name": NAME})
    assert not out.is_error and "references/pooling.md" in out.text
    assert app.store.get(sid)["settings"]["loaded_skills"] == [NAME]
    ref = await app.tools.run(ctx, "read_skill", {"name": NAME, "path": "references/pooling.md"})
    assert "ObjectPool" in ref.text
    assert app.store.get(sid)["settings"]["loaded_skills"] == [NAME]  # a reference read is not a load

    names = [t.name for t in app.tools.specs(session=app.store.get(sid))]
    assert "unload_skill" in names
    out = await app.tools.run(ctx, "unload_skill", {"name": NAME})
    assert not out.is_error and "Unloaded unity-practices" in out.text
    settings = app.store.get(sid)["settings"]
    assert NAME not in settings["loaded_skills"] and NAME not in settings.get("skills", [])
    assert (await app.tools.run(ctx, "unload_skill", {"name": NAME})).is_error  # not loaded any more
    assert (await app.tools.run(ctx, "unload_skill", {"name": "delegation"})).is_error  # pinned


def test_unload_is_offered_only_in_progressive_sessions(app):
    app.config.skills["disclosure"] = "full"
    legacy = app.store.create()
    app.config.skills["disclosure"] = "progressive"
    assert "unload_skill" not in [t.name for t in app.tools.specs(session=legacy)]
    assert "unload_skill" in [t.name for t in app.tools.specs(session=app.store.create(**PROGRESSIVE))]


def test_unload_settings_update():
    update, msg = unload({**PROGRESSIVE, "skills": ["delegation", NAME, "graphify"],
                          "loaded_skills": [NAME, "graphify"]}, NAME)
    assert update == {"loaded_skills": ["graphify"], "skills": ["delegation", "graphify"]}
    assert "tokens" in msg
    assert unload({**PROGRESSIVE, "loaded_skills": []}, NAME)[0] == {}


async def test_unloaded_skill_is_not_reinjected_by_compaction(app):
    s = app.store.create(**{**PROGRESSIVE, "loaded_skills": ["graphify", NAME]})
    sid = s["id"]
    app.store.add_message(sid, Message.user("make enemies"))
    for n in ("graphify", NAME):
        app.store.add_message(sid, Message(role="user", content=[TextBlock(text=sk.skill_load_text(n))],
                                           meta={"skill_load": n}))
    cut = len(app.runner.model_history(sid))
    app.store.add_message(sid, Message.user("keep going"))
    app.store.add_message(sid, Message.assistant("working"))
    ctx = ToolContext(app=app, session=app.store.get(sid), run_id="main:unity")
    assert not (await app.tools.run(ctx, "unload_skill", {"name": NAME})).is_error
    app.fake.script = [text_response("summary")]
    await cx.compact_messages(app, sid, app.runner.model_history(sid), cut)
    reloaded = [m.meta["skill_load"] for m in app.runner.model_history(sid) if m.meta.get("skill_load")]
    assert reloaded == ["graphify"]


# ------------------------------------------------------------------ token savings and API prices


def test_context_shows_skill_savings_priced_at_api_rates(app):
    s = app.store.create(**{**PROGRESSIVE, "loaded_skills": []})
    for _ in range(3):
        app.usage.record(provider="anthropic", model=s["model"], session_id=s["id"], role="main",
                         usage=Usage(input_tokens=10, output_tokens=5, cost_usd=0.001))
    sv = context_breakdown(app, s["id"])["skill_savings"]
    full = cx.est(sk.full_disclosure_text(s["settings"]))
    assert sv["full_tokens"] == full and sv["now_tokens"] < full
    assert sv["saved_tokens_per_call"] == full - sv["now_tokens"] > 0
    assert sv["main_calls"] == 3 and sv["saved_tokens_session"] == 3 * sv["saved_tokens_per_call"]
    m = app.config.model(s["model"])
    assert sv["priced"] == (m.input > 0)
    assert sv["saved_usd_per_call"] == pytest.approx(sv["saved_tokens_per_call"] * m.input / 1e6, abs=1e-6)
    assert sv["saved_usd_per_call_cached"] <= sv["saved_usd_per_call"]
    app.config.skills["disclosure"] = "full"
    legacy = app.store.create()
    assert "skill_savings" not in context_breakdown(app, legacy["id"])


def test_session_usage_reports_api_price_including_subscription_calls(app):
    with TestClient(app.api) as c:
        sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
        model = app.store.get(sid)["model"]
        u = Usage(input_tokens=1_000_000, output_tokens=0, cost_usd=0.0)
        app.usage.record(provider="anthropic", model=model, session_id=sid, usage=u, billing="subscription")
        app.usage.record(provider="anthropic", model=model, session_id=sid,
                         usage=Usage(input_tokens=10, output_tokens=0, cost_usd=0.5))
        body = c.get(f"/api/usage/session/{sid}", headers=H).json()
    price = app.config.model(model).input  # 1M uncached input tokens at list price
    assert body["total_cost"] == pytest.approx(0.5)  # what was billed is unchanged
    assert body["api_price_total"] == pytest.approx(price + 0.5)
    sub = next(m for m in body["models"] if m["billing"] == "subscription")
    assert sub["api_price"] == pytest.approx(price)


def test_skill_tokens_script_reports_savings_and_prices():
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(root / "scripts" / "skill_tokens.py")], capture_output=True, text=True,
                       encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr
    assert "saved, Unity pipeline" in r.stdout and "API list prices" in r.stdout
    assert "always in context (index line, every call)" in r.stdout


# ------------------------------------------------------------------ scripts


BAD_CS = """using System.Linq;
using UnityEngine;
public class Bad : MonoBehaviour {
    public float speed = 5f;
    [SerializeField] private Transform target;
    void Awake() { GetComponent<Health>().Died += OnDied; }
    void Update() {
        var e = FindObjectsByType<Enemy>(FindObjectsSortMode.None).Where(x => x.enabled).ToList();
        if (other.tag == "Enemy") Instantiate(prefab);
        target?.SetParent(null);
        GetComponent<Renderer>().material.color = Color.red;
        // GetComponent<Foo>() in a comment is ignored
        string s = "GetComponent<Foo>() in a string is ignored";
    }
}
"""


def test_cs_lint_finds_known_problems_and_ignores_comments(tmp_path):
    lint = load_module("cs_lint")
    found = lint.lint_text(BAD_CS, str(tmp_path / "Bad.cs"))
    rules = {r for _line, r in found}
    assert {"PUBLIC_FIELD", "EVENT_UNSUB", "FIND_HOT", "LINQ_HOT", "LAMBDA_HOT", "TAG_COMPARE", "INSTANTIATE_HOT",
            "NULL_PROPAGATION", "GETCOMPONENT_HOT", "MATERIAL_CLONE"} <= rules
    assert not any(line in (12, 13) for line, _r in found)  # the comment and the string
    (tmp_path / "Bad.cs").write_text(BAD_CS, encoding="utf-8")
    r = run("cs_lint.py", str(tmp_path), "--only", "TAG_COMPARE")
    assert r.returncode == 1 and r.stdout.strip().splitlines()[-1] == "RESULT: FAIL findings=1 files=1"


def test_templates_compile_clean_under_their_own_lint():
    r = run("cs_lint.py", str(ROOT / "templates"))
    assert r.returncode == 0, r.stdout
    assert r.stdout.strip().startswith("RESULT: OK")


def test_scaffold_writes_kits_with_namespace_and_skips_existing(tmp_path):
    r = run("scaffold.py", "list")
    assert {"pooling", "enemies", "tuning", "debug-kit"} <= {x.split(":")[0] for x in r.stdout.splitlines()}
    out = tmp_path / "Assets" / "Game"
    for kit in ("pooling", "enemies", "tuning", "debug-kit"):
        r = run("scaffold.py", kit, "--out", str(out / kit), "--namespace", "My.Game")
        assert r.returncode == 0 and "RESULT: OK" in r.stdout, r.stdout
    files = list(out.rglob("*.cs"))
    assert len(files) == len(list((ROOT / "templates").rglob("*.cs")))
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "GdwKit" not in text and "namespace My.Game" in text
    assert (out / "debug-kit" / "Editor" / "DebugSceneBuilder.cs").is_file()
    again = run("scaffold.py", "pooling", "--out", str(out / "pooling"), "--namespace", "My.Game")
    assert "written=0" in again.stdout and "skip" in again.stdout
    assert run("scaffold.py", "pooling", "--out", str(tmp_path / "x"), "--namespace", "1bad").returncode == 2


META = """fileFormatVersion: 2
guid: 474ce57d7c1704418af05d72d996ae5e
TextureImporter:
  mipmaps:
    enableMipMap: {mips}
    sRGBTexture: {srgb}
  isReadable: {readable}
  maxTextureSize: 2048
  textureSettings:
    serializedVersion: 2
    filterMode: {filter}
  textureType: {type}
  platformSettings:
  - serializedVersion: 4
    buildTarget: DefaultTexturePlatform
    maxTextureSize: {size}
    textureFormat: -1
    textureCompression: {comp}
    overridden: 0
  - serializedVersion: 4
    buildTarget: Android
    maxTextureSize: 2048
    textureFormat: 4
    textureCompression: 1
    overridden: {android}
"""


def write_texture(root: Path, name: str, **kw) -> None:
    values = {"mips": 0, "srgb": 1, "readable": 0, "filter": 1, "type": 0, "size": 2048, "comp": 1, "android": 0}
    values.update(kw)
    (root / name).write_bytes(b"\x89PNG")
    (root / f"{name}.meta").write_text(META.format(**values), encoding="utf-8")


def test_texture_audit_profiles(tmp_path):
    write_texture(tmp_path, "ok.png")
    r = run("texture_audit.py", str(tmp_path), "--profile", "mobile")
    assert r.returncode == 0 and "RESULT: OK textures=1" in r.stdout
    write_texture(tmp_path, "ui_icon.png", type=8, mips=1)
    write_texture(tmp_path, "rock_mask.png", srgb=1)
    write_texture(tmp_path, "huge.png", size=8192, readable=1)
    write_texture(tmp_path, "forced.png", android=1)  # Android override to RGBA32
    r = run("texture_audit.py", str(tmp_path), "--profile", "mobile")
    assert r.returncode == 1
    for rule in ("SPRITE_MIPS", "SRGB_DATA", "MAX_SIZE", "READ_WRITE", "UNCOMPRESSED"):
        assert rule in r.stdout
    pixel = tmp_path / "pixel"
    pixel.mkdir()
    write_texture(pixel, "hero.png", type=8, filter=0, comp=0)
    assert run("texture_audit.py", str(pixel), "--profile", "pixel").returncode == 0
    write_texture(pixel, "blurry.png", type=8, filter=1, comp=1)
    r = run("texture_audit.py", str(pixel), "--profile", "pixel")
    assert "PIXEL_FILTER" in r.stdout and "PIXEL_COMPRESSION" in r.stdout


def test_issue_cache_round_trip(tmp_path):
    r = run("issue_cache.py", "find", "NullReferenceException in EnemyBrain.Update", "--project", str(tmp_path))
    assert r.returncode == 1 and r.stdout.startswith("MISS")
    r = run("issue_cache.py", "add", "NullReferenceException: Object reference not set EnemyBrain.Update () "
            "(at Assets/Game/EnemyBrain.cs:42)", "--fix", "clear Target in OnReleaseToPool",
            "--files", "Assets/Game/EnemyBrain.cs", "--project", str(tmp_path))
    assert r.returncode == 0 and "SAVED id=I001" in r.stdout
    r = run("issue_cache.py", "find", "NullReferenceException at EnemyBrain.Update (Assets/Scripts/EnemyBrain.cs:57)",
            "--project", str(tmp_path))
    assert r.returncode == 0 and "HIT" in r.stdout and "clear Target in OnReleaseToPool" in r.stdout
    # Different compiler error codes never match, however many words they share.
    run("issue_cache.py", "add", "error CS0103: The name 'pool' does not exist", "--fix", "add using",
        "--project", str(tmp_path))
    r = run("issue_cache.py", "find", "error CS0246: The name 'pool' does not exist", "--project", str(tmp_path))
    assert "add using" not in r.stdout
    store = tmp_path / ".gdw" / "unity-issues.jsonl"
    entries = [json.loads(x) for x in store.read_text(encoding="utf-8").splitlines()]
    assert entries[0]["hits"] >= 1 and len(entries) == 2
    # The same symptom again updates the entry instead of adding a duplicate.
    run("issue_cache.py", "add", "error CS0103: The name 'pool' does not exist", "--fix", "add using UnityEngine.Pool",
        "--project", str(tmp_path))
    entries = [json.loads(x) for x in store.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 2 and entries[1]["fix"] == "add using UnityEngine.Pool"


def test_unity_router_routes_to_unity_practices():
    router = (ROOT.parent / "unity-router" / "SKILL.md").read_text(encoding="utf-8")
    rows = [line for line in router.splitlines() if line.startswith("| ") and "unity-practices" in line]
    assert any(line.startswith("| 5 |") for line in rows)  # implementing a system
    assert any("pooling" in line and "magic numbers" in line and line.split("|")[3].strip().startswith("unity-practices")
               for line in rows)
    assert "unload_skill" in router
    r = subprocess.run([sys.executable, "-I", str(ROOT.parent / "unity-router" / "scripts" / "check_skills.py"), "--all",
                        "--root", str(ROOT.parent)], capture_output=True, text=True, encoding="utf-8", timeout=60,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0 and "unity-practices" in r.stdout, r.stdout
