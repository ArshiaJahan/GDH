"""trailer-maker: the skill's files and wiring, the stdlib scripts (EDL checks, timeline math, plan golden, beat
grid, review aggregation, captions), the Unity template's static shape, and, when ffmpeg is on this machine, a real
render + export + qc of synthetic clips. No Unity, no ElevenLabs, no network."""
import importlib.util
import json
import math
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tomllib
import wave
import zlib
from pathlib import Path

import pytest

from gamedevworkstation import skills as sk

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/trailer-maker"
SCRIPTS = SKILL / "scripts"
EDL_PY = SCRIPTS / "trailer_edl.py"
GRID_PY = SCRIPTS / "beat_grid.py"
REVIEW_PY = SCRIPTS / "trailer_review.py"
CHECK_SKILLS = ROOT / "skills/unity-router/scripts/check_skills.py"
FIX = Path(__file__).parent / "fixtures/trailer"
NOFF = {"TRAILER_FFMPEG": "none"}  # hide ffmpeg: pure tests behave the same on every machine
FIXED_MTIME = 1_700_000_000


def load(name):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


edl_mod = load("trailer_edl")
common = load("_trailer_common")
FFMPEG, FFPROBE = common.find_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe not installed")


def run(script, *args, env=None, cwd=None, timeout=600):
    e = dict(os.environ)
    e.update(env or {})
    e.pop("UNITY_SKILLS_DIRS", None)
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, env=e,
                          cwd=cwd, timeout=timeout)


def last(r):
    return (r.stdout.strip().splitlines() or [""])[-1]


def png(path, w, h, color=(200, 40, 40), alpha=None):
    """A solid PNG written with the standard library (RGB, or RGBA when alpha is given)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    px = bytes(color) + (bytes([alpha]) if alpha is not None else b"")
    raw = b"".join(b"\x00" + px * w for _ in range(h))
    ctype = 6 if alpha is not None else 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))
    return path


# ====================================================================== skill wiring


def test_skill_is_builtin_with_files_and_not_featured():
    listed = {x["name"]: x for x in sk.list_skills()}
    s = listed["trailer-maker"]
    assert s["source"] == "builtin" and len(s["description"]) > 40 and not s["featured"] and not s["native"]
    assert Path(s["path"]).parent.name == "trailer-maker"
    files = set(sk.skill_files("trailer-maker"))
    assert {"scripts/trailer_edl.py", "scripts/beat_grid.py", "scripts/trailer_review.py", "scripts/_trailer_common.py",
            "chains/trailer.toml", "references/craft.md", "references/beat-sheets.md", "references/platform-specs.md",
            "references/shot-list.md", "references/edl-schema.md", "references/audio.md", "references/reviewers.md",
            "templates/brief.template.md", "templates/beats.template.json", "templates/shots.template.json",
            "templates/edl.template.json", "templates/cards.template.json",
            "templates/Harness.Trailer/Editor/Harness.Trailer.Editor.asmdef",
            "templates/Harness.Trailer/Editor/TrailerCapture.cs", "templates/Harness.Trailer/Editor/TrailerCards.cs",
            "templates/Harness.Trailer/Editor/TrailerJob.cs"} <= files
    body = (SKILL / "SKILL.md").read_text()
    for ref in [f for f in files if f.startswith("references/")]:
        assert ref in body, f"SKILL.md doesn't point to {ref}"
    assert "FMOD" in body and "Recorder" in body and ".gitignore" in body


def test_router_and_check_skills_know_trailer_maker():
    router = (ROOT / "skills/unity-router/SKILL.md").read_text()
    assert "| 17 | trailer" in router and "trailer-maker" in router and "| `trailer` |" in router
    r = run(CHECK_SKILLS, "trailer-maker")
    assert r.returncode == 0 and last(r) == "RESULT: OK 1 skill(s) found", r.stdout
    r = run(CHECK_SKILLS, "--all")
    assert r.returncode == 0, r.stdout
    assert last(r) == "RESULT: OK 18 skill(s) found"  # 16 harness skills + unity-mcp-orchestrator + game-designer
    assert "16 harness skills" in CHECK_SKILLS.read_text()


def test_config_turns_unity_on_for_trailer_maker(cfg):
    assert cfg.skill_mcp_servers("trailer-maker") == ["unity"]


def test_chain_template_shape():
    data = tomllib.loads((SKILL / "chains/trailer.toml").read_text())
    assert data["id"] == "trailer" and data["applies_to"] == "unity" and set(data["kinds"]) == {"chain", "campaign"}
    names = [p["name"] for p in data["phase"]]
    assert names == ["Brief", "Beat sheet", "Shot list", "Capture", "Rough cut", "Music, VO and SFX",
                     "Trailer review", "Exports"]
    listed = {x["name"] for x in sk.list_skills()}
    allowed = {"file_exists", "command_passes", "metric_threshold", "gate", "visual_verify", "git_clean", "manual"}
    for p in data["phase"]:
        assert p["type"] in ("research", "plan", "build", "wire", "verify", "prune")
        assert set(p["skills"]) <= listed, p["skills"]
        conds = p["done_when"]
        assert all(c["type"] in allowed for c in conds)
        assert any(c["type"] != "manual" for c in conds), p["name"]
        for c in conds:
            if c["type"] == "command_passes":  # each observed script exists and prints RESULT lines
                assert (SCRIPTS / f"{c['observe']}.py").is_file()
            if c["type"] == "file_exists":
                assert c["path"].startswith("Trailer/") and c.get("newer_than") == "phase_start"


def test_chain_template_validates_with_the_chains_engine():
    chains = pytest.importorskip("gamedevworkstation.features.chains", reason="chains engine not merged on this branch")
    t = chains.validate_template(tomllib.loads((SKILL / "chains/trailer.toml").read_text()), "trailer.toml")
    assert t["id"] == "trailer" and len(t["phases"]) == 8


# ====================================================================== Unity template (static)


TEMPLATE = SKILL / "templates/Harness.Trailer/Editor"


def _guarded(text, using_prefix, define):
    """Every `using <prefix>` line sits inside `#if <define>` ... `#endif`."""
    depth_ok, stack = True, []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#if"):
            stack.append(s)
        elif s.startswith("#endif"):
            stack.pop()
        elif s.startswith("#else"):
            stack[-1] = "#else " + stack[-1]
        elif s.startswith(using_prefix):
            depth_ok &= any(x == f"#if {define}" for x in stack)
    return depth_ok


def test_unity_template_static_shape():
    asm = json.loads((TEMPLATE / "Harness.Trailer.Editor.asmdef").read_text())
    assert asm["name"] == "Harness.Trailer.Editor" and asm["includePlatforms"] == ["Editor"]
    assert asm["autoReferenced"] is False and not asm["defineConstraints"]
    vd = {d["define"]: d for d in asm["versionDefines"]}
    assert vd["HARNESS_RECORDER"]["name"] == "com.unity.recorder" and vd["HARNESS_RECORDER"]["expression"] == "5.0.0"
    assert vd["HARNESS_TMP"]["name"] == "com.unity.ugui"
    assert "Unity.Recorder.Editor" in asm["references"]
    for cs in TEMPLATE.glob("*.cs"):
        text = cs.read_text()
        assert "namespace Harness.Trailer" in text, cs.name
        assert _guarded(text, "using UnityEditor.Recorder", "HARNESS_RECORDER"), cs.name
        assert _guarded(text, "using TMPro", "HARNESS_TMP"), cs.name
        directives = [x.strip().split()[0] for x in text.splitlines() if x.strip().startswith("#")]
        assert directives.count("#if") == directives.count("#endif"), cs.name
    cap = (TEMPLATE / "TrailerCapture.cs").read_text()
    for api in ("public static string Start(string shotsJsonPath", "public static string Status()",
                "public static void RunFromCli()", "GameViewInputSettings", "FrameRatePlayback.Constant",
                "[TRAILER] shot=", "WriteReport", "isBatchMode"):
        assert api in cap, api
    assert "public static string Render(string cardsJsonPath)" in (TEMPLATE / "TrailerCards.cs").read_text()
    assert "capture output must be outside Assets/" in (TEMPLATE / "TrailerJob.cs").read_text()


def test_capture_report_and_cli_exit_guards():
    cap = (TEMPLATE / "TrailerCapture.cs").read_text()
    # the report's duration_s is the PLANNED length, so check --capture can compare recorded frames against it
    assert "duration_s = shot.duration_s," in cap and "(float)S.rec_frames / fps" not in cap
    # a stale job.json with cli=true must not close a normal editor: only a job RunFromCli started in this session
    assert "TrailerJob.CliStartedThisSession = cli;" in cap
    done = cap[cap.index("static void TickInner()"):]
    exit_check = done[:done.index("EditorApplication.Exit(")]
    assert "S.cli && TrailerJob.CliStartedThisSession" in exit_check
    job = (TEMPLATE / "TrailerJob.cs").read_text()
    assert "SessionState.GetBool(CliSessionKey, false)" in job


def test_capture_check_flags_short_takes_against_the_planned_length(tmp_path):
    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "t.mp4").write_bytes(b"fake")
    rep = {"shots": [{"id": "s01", "takes": [{"take": 1, "file": "t.mp4", "frames": 200, "fps": 60,
                                              "duration_s": 6.0, "status": "ok", "errors": 0}]}]}
    errs, warns = edl_mod.check_capture(rep, str(tmp_path / "report.json"))
    assert not errs and any("200 frames, expected 360" in w for w in warns), warns
    errs, _w = edl_mod.check_capture({"shots": ["s01", {"id": "s02", "takes": [3]}]}, str(tmp_path / "r.json"))
    assert any("every shot must be an object" in x for x in errs) and any("every take" in x for x in errs)


def test_planning_templates_pass_the_checker():
    r = run(EDL_PY, "check", "--beats", SKILL / "templates/beats.template.json", env=NOFF)
    assert r.returncode == 0 and last(r).startswith("RESULT: OK"), r.stdout
    r = run(EDL_PY, "check", "--shots", SKILL / "templates/shots.template.json", env=NOFF)
    assert r.returncode == 0 and last(r).startswith("RESULT: OK"), r.stdout
    tpl = json.loads((SKILL / "templates/edl.template.json").read_text())
    e = edl_mod.normalize_edl(tpl, str(SKILL))
    assert [it["id"] for it in e["items"]] == ["c01", "c02", "c03"] and e["exports"] == ["steam", "youtube", "shorts"]


# ====================================================================== beats / shots checks


def beats_doc(**over):
    b = json.loads((SKILL / "templates/beats.template.json").read_text())
    b.update(over)
    return b


def _unhook(beats):
    for x in beats:
        x.pop("hook", None)
        x["id"] = x["id"].replace("hook", "core")


@pytest.mark.parametrize("mutate,needle", [
    (lambda b: b["beats"][1].update(start=5.5), "contiguous"),
    (lambda b: _unhook(b["beats"]), "no hook beat"),
    (lambda b: b.update(beats=[{"id": "intro", "start": 0, "end": 16, "intent": "lore", "shots": []},
                               {"id": "hook", "start": 16, "end": 55, "intent": "verbs", "shots": []},
                               {"id": "end-slate", "start": 55, "end": 60, "intent": "CTA", "shots": []}]),
     "the hook starts at 16 s"),
    (lambda b: b["beats"][3].update(card="one two three four five six seven eight"), "8 words"),
    (lambda b: b["beats"][-1].update(id="outro", end_slate=False), "end slate"),
    (lambda b: b.update(type="trailer"), "type 'trailer'"),
])
def test_beats_errors(tmp_path, mutate, needle):
    b = beats_doc()
    mutate(b)
    r = run(EDL_PY, "check", "--beats", write_json(tmp_path / "beats.json", b), env=NOFF)
    assert r.returncode == 1 and last(r).startswith("RESULT: FAIL"), r.stdout
    assert needle in r.stdout, r.stdout


def test_shots_errors(tmp_path):
    s = json.loads((SKILL / "templates/shots.template.json").read_text())
    s["output_dir"] = "Assets/Trailer/capture"
    s["shots"][0]["camera"]["ortho_size"] = None
    s["shots"][1]["id"] = "s01"
    s["shots"][1]["setup"] = "not a method"
    r = run(EDL_PY, "check", "--shots", write_json(tmp_path / "shots.json", s), env=NOFF)
    assert r.returncode == 1
    for needle in ("outside Assets/", "ortho_size must be a number", "duplicate id", "Namespace.Type.Method"):
        assert needle in r.stdout, needle


def test_capture_report_check(tmp_path):
    (tmp_path / "ProjectSettings").mkdir()
    cap = tmp_path / "Trailer/x/capture"
    (cap / "s01").mkdir(parents=True)
    (cap / "s01/take-01.mp4").write_bytes(b"fake")
    rep = {"shots": [{"id": "s01", "takes": [
        {"take": 1, "file": "Trailer/x/capture/s01/take-01.mp4", "frames": 360, "fps": 60, "duration_s": 6.0,
         "status": "ok", "errors": 0, "message": ""},
        {"take": 2, "file": "", "frames": 0, "fps": 60, "duration_s": 0, "status": "failed", "errors": 1,
         "message": "setup threw"}]}]}
    shots = {"version": 1, "fps": 60, "resolution": {"w": 1920, "h": 1080}, "output_dir": "Trailer/x/capture",
             "shots": [{"id": "s01", "scene": "Assets/Scenes/G.unity", "duration_s": 6, "takes": 2},
                       {"id": "s02", "scene": "Assets/Scenes/G.unity", "duration_s": 3, "takes": 1}]}
    write_json(cap / "report.json", rep)
    write_json(tmp_path / "Trailer/x/shots.json", shots)
    r = run(EDL_PY, "check", "--shots", tmp_path / "Trailer/x/shots.json", "--capture", cap / "report.json", env=NOFF)
    assert r.returncode == 1 and "shot s02 has no ok take" in r.stdout and "setup threw" in r.stdout, r.stdout
    shots["shots"].pop()
    write_json(tmp_path / "Trailer/x/shots.json", shots)
    r = run(EDL_PY, "check", "--shots", tmp_path / "Trailer/x/shots.json", "--capture", cap / "report.json", env=NOFF)
    assert r.returncode == 0 and last(r).startswith("RESULT: OK shots+capture valid"), r.stdout


# ====================================================================== EDL checks and timeline


def edl_project(root, fps=30, w=320, h=180):
    """A small trailer folder with fake sources (pure tests never decode them), card and overlay PNGs, audio."""
    for rel in ("capture/s01.mp4", "capture/s02.mp4", "audio/music.wav", "audio/vo.wav"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"not really media " + rel.encode())
    png(root / "cards/end.png", w, h)
    png(root / "cards/bug.png", 40, 20, color=(255, 255, 255), alpha=128)
    edl = {"version": 1, "id": "t1", "type": "social", "fps": fps, "canvas": {"w": w, "h": h},
           "sources": {"s01": "capture/s01.mp4", "s02": "capture/s02.mp4"},
           "video": [{"id": "c01", "src": "s01", "in": 0.5, "out": 2.5},
                     {"id": "c02", "src": "s02", "in": 1.0, "out": 2.0, "speed": 0.5, "freeze_end": 0.5,
                      "transition_in": {"type": "fade", "dur": 0.5}, "vcrop": {"x": 0.3}},
                     {"id": "c03", "card": "cards/end.png", "dur": 1.5,
                      "transition_in": {"type": "fadeblack", "dur": 0.25}}],
           "overlays": [{"image": "cards/bug.png", "start": 0, "end": 2, "pos": "top-right", "margin": 8, "fade": 0.2}],
           "audio": {"game": {"enabled": True, "gain_db": -6}, "music": {"path": "audio/music.wav", "fade_out": 1},
                     "vo": [{"path": "audio/vo.wav", "at": 1.0}]},
           "exports": ["steam", "shorts"], "poster_at": 1.0}
    for p in root.rglob("*"):
        if p.is_file():
            os.utime(p, (FIXED_MTIME, FIXED_MTIME))
    return edl


def test_timeline_math_matches_the_worked_example():
    data = {"fps": 60, "type": "gameplay", "sources": {"s01": "a.mp4", "s05": "b.mp4"},
            "video": [{"id": "c01", "src": "s01", "in": 0.80, "out": 3.20},
                      {"id": "c02", "src": "s05", "in": 2.00, "out": 3.00, "speed": 0.5, "freeze_end": 0.25},
                      {"id": "c03", "card": "cards/title.png", "dur": 1.5,
                       "transition_in": {"type": "fadeblack", "dur": 0.25}}]}
    e = edl_mod.normalize_edl(data, "/x")
    assert [(it["start"], it["end"], it["n"], it["d"]) for it in e["items"]] == \
        [(0, 144, 144, 0), (144, 279, 135, 0), (264, 354, 90, 15)]
    assert e["total_n"] == 354 and abs(e["total"] - 5.9) < 1e-9
    assert [(i, round(t, 4)) for i, t in edl_mod.cut_points(e)] == [("c02", 2.4), ("c03", 4.525)]
    assert edl_mod.item_at(e, 4.5)["id"] == "c03" and edl_mod.item_at(e, 0.0)["id"] == "c01"


def test_valid_edl_checks_ok_without_ffmpeg(tmp_path):
    edl = edl_project(tmp_path)
    r = run(EDL_PY, "check", write_json(tmp_path / "edl.json", edl), env=NOFF)
    assert r.returncode == 0 and last(r).startswith("RESULT: OK edl valid"), r.stdout
    assert "ffprobe not found" in r.stdout  # durations unchecked, said so
    assert re.search(r"c03\s+card\s+3.733333-5.233333 s\s+fadeblack", r.stdout), r.stdout


@pytest.mark.parametrize("mutate,needle", [
    (lambda e: e["video"][0].update(src="s09"), "unknown src 's09'"),
    (lambda e: e["sources"].update(s01="capture/missing.mp4"), "file missing: capture/missing.mp4"),
    (lambda e: e["video"][0].update(out=0.5), "must be greater than in"),
    (lambda e: e["video"][1]["transition_in"].update(dur=3.0), "transition 3 s is as long as"),
    (lambda e: e["video"].insert(0, {"id": "c00", "card": "cards/end.png", "dur": 2.0}), "hook rule"),
    (lambda e: e.update(exports=["steam", "myspace"]), "unknown export 'myspace'"),
    (lambda e: e["overlays"][0].update(end=99), "outside the timeline"),
    (lambda e: e["video"][0].update(speed=8), "speed must be from 0.1 to 4"),
    (lambda e: e["overlays"][0].update(image="cards/end.png"), "no alpha channel"),
    (lambda e: e["audio"]["vo"][0].update(at=60), "beyond the end"),
])
def test_edl_errors(tmp_path, mutate, needle):
    edl = edl_project(tmp_path)
    mutate(edl)
    r = run(EDL_PY, "check", write_json(tmp_path / "edl.json", edl), env=NOFF)
    assert r.returncode == 1 and last(r).startswith("RESULT: FAIL"), r.stdout
    assert needle in r.stdout, r.stdout


def test_card_size_and_missing_end_slate(tmp_path):
    edl = edl_project(tmp_path)
    png(tmp_path / "cards/end.png", 100, 50)
    r = run(EDL_PY, "check", write_json(tmp_path / "edl.json", edl), env=NOFF)
    assert r.returncode == 1 and "not the canvas size 320x180" in r.stdout
    edl = edl_project(tmp_path)
    edl["video"].pop()  # ends on gameplay, no overlay at the end: a warning, not an error
    edl["overlays"] = []
    r = run(EDL_PY, "check", write_json(tmp_path / "edl.json", edl), env=NOFF)
    assert r.returncode == 0 and "WARN  no end slate in the last 6 s" in r.stdout, r.stdout


def test_snap_report_against_a_beat_grid(tmp_path):
    edl = edl_project(tmp_path)
    write_json(tmp_path / "grid.json", {"bpm": 120, "beats": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]})
    r = run(EDL_PY, "check", write_json(tmp_path / "edl.json", edl), "--grid", tmp_path / "grid.json", env=NOFF)
    # c02's 0.5 s dissolve is centred on 1.75 s, between the beats at 1.5 and 2.0: 7.5 -> 8 frames off
    assert r.returncode == 0 and "cut into c02 at 1.75 s is 8 frame(s) off the nearest beat" in r.stdout, r.stdout


def test_snap_report_maps_music_file_beats_onto_the_timeline(tmp_path):
    edl = edl_project(tmp_path)
    # the music plays from 2.0 s in the file, starting at 0.5 s on the timeline: file beat b lands at b - 2.0 + 0.5
    edl["audio"]["music"].update({"in": 2.0, "at": 0.5})
    # file beats at 3.25 -> 1.75 s (c02's dissolve centre), 1.0 -> before the music starts, 99 -> past the end
    write_json(tmp_path / "grid.json", {"beats": [1.0, 3.25, 99.0]})
    e = edl_mod.normalize_edl(edl, str(tmp_path))
    warns = edl_mod.snap_report(e, str(tmp_path / "grid.json"))
    assert not any("c02" in w for w in warns), warns  # on the beat once mapped
    assert any("cut into c03" in w and "nearest beat 1.75 s" in w for w in warns), warns
    # beats only before the music starts / after the cut: nothing to snap to
    write_json(tmp_path / "grid.json", {"beats": [1.0, 1.9, 99.0]})  # -> -0.5, 0.4 (< at 0.5), 97.5
    assert edl_mod.snap_report(e, str(tmp_path / "grid.json")) == [
        "beat grid %s has no beats inside the music on the timeline" % (tmp_path / "grid.json")]
    # no music: no snapping report at all
    edl["audio"].pop("music")
    e = edl_mod.normalize_edl(edl, str(tmp_path))
    assert edl_mod.snap_report(e, str(tmp_path / "grid.json")) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda e: e["overlays"][0].update(margin="x"), "overlays[0]: margin must be a number"),
    (lambda e: e["overlays"][0].update(fade="q"), "overlays[0]: fade must be a number"),
    (lambda e: e["audio"]["music"].update({"in": "z"}), "audio.music.in must be a number"),
    (lambda e: e["audio"].update(game="off"), "audio.game must be an object"),
    (lambda e: e["audio"].update(duck={"ratio": "lots"}), "audio.duck.ratio must be a number"),
    (lambda e: e["audio"].update(duck=[1]), "audio.duck must be an object"),
    (lambda e: e["audio"].update(loudness={"i": "loud"}), "audio.loudness.i must be a number"),
    (lambda e: e["audio"]["vo"][0].update(gain_db="up"), "audio.vo[0].gain_db must be a number"),
    (lambda e: e.update(audio="none"), "audio must be an object"),
    (lambda e: e.update(vertical={"max_s": "long"}), "vertical.max_s must be a number"),
    (lambda e: e.update(vertical=5), "vertical must be an object"),
    (lambda e: e.update(captions="en.srt"), "captions must be an object"),
    (lambda e: e.update(captions={"burn_in_for": [["shorts"]]}), "is not a vertical platform"),
    (lambda e: e.update(exports=[["steam"]]), "unknown export"),
    (lambda e: e.update(type=["social"]), "is not one of"),
    (lambda e: e.update(snap_tolerance_frames="one"), "snap_tolerance_frames must be a number"),
    (lambda e: e.update(overlays=7), "overlays must be a list"),
])
def test_bad_values_are_errors_not_crashes(tmp_path, mutate, needle):
    edl = edl_project(tmp_path)
    mutate(edl)
    r = run(EDL_PY, "check", write_json(tmp_path / "edl.json", edl), env=NOFF)
    assert r.returncode == 1 and last(r).startswith("RESULT: FAIL"), r.stdout + r.stderr
    assert needle in r.stdout and "Traceback" not in r.stderr, r.stdout + r.stderr


def test_transitions_may_not_overlap_inside_a_short_item():
    # c02 is 0.5 s (15 frames); its own 0.25 s dissolve in plus c03's 0.3 s dissolve need 16.5 frames
    data = {"fps": 30, "type": "social", "sources": {"s": "a.mp4"},
            "video": [{"id": "c01", "src": "s", "in": 0, "out": 2},
                      {"id": "c02", "src": "s", "in": 0, "out": 0.5, "transition_in": {"type": "fade", "dur": 0.25}},
                      {"id": "c03", "src": "s", "in": 0, "out": 2, "transition_in": {"type": "fade", "dur": 0.3}}]}
    e = edl_mod.normalize_edl(data, "/x")
    assert any("video[2] c03: transition" in x and "overlaps" in x for x in e["errors"]), e["errors"]
    data["video"][2]["transition_in"]["dur"] = 0.2  # 8 + 6 frames < 15: fits
    assert not edl_mod.normalize_edl(data, "/x")["errors"]


def test_interrupted_render_never_reuses_a_partial_clip(tmp_path, capsys):
    e = edl_mod.normalize_edl(edl_project(tmp_path), str(tmp_path))
    st = {"name": "clip c01", "argv": ["ffmpeg", "-y", "build/clips/c01.mov"], "outputs": ["build/clips/c01.mov"],
          "inputs": [], "cache": True}
    out = tmp_path / "build/clips/c01.mov"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"complete render of an older edit")
    (tmp_path / "build/clips/c01.mov.key").write_text("old-key\n")
    fake = tmp_path / "fake-ffmpeg"
    fake.write_text("#!/bin/sh\nprintf partial > build/clips/c01.mov\nexit 1\n")  # dies half way
    fake.chmod(0o755)
    ok, msg = edl_mod.run_steps(e, [st], str(fake), quiet=True)
    assert not ok and "failed" in msg
    assert not (tmp_path / "build/clips/c01.mov.key").exists()  # the partial output carries no key
    assert out.read_bytes() == b"partial"
    # a finished render writes the key again, and the next run reuses the clip
    fake.write_text("#!/bin/sh\nprintf complete > build/clips/c01.mov\nexit 0\n")
    ok, _msg = edl_mod.run_steps(e, [st], str(fake), quiet=True)
    assert ok and (tmp_path / "build/clips/c01.mov.key").read_text().strip() == edl_mod.cache_key(e, st)
    capsys.readouterr()
    ok, _msg = edl_mod.run_steps(e, [st], str(fake))
    assert ok and "cached" in capsys.readouterr().out


def test_mix_limiter_has_no_lookahead_delay(tmp_path):
    e = edl_mod.normalize_edl(edl_project(tmp_path), str(tmp_path))
    mix = edl_mod.mix_steps(e, "build/picture.mov", "build")[0]
    fc = mix["argv"][mix["argv"].index("-filter_complex") + 1]
    assert "alimiter=limit=0.891:level=0:latency=1," in fc


def test_x_720_export_and_trailer_qc_entry_point(tmp_path):
    edl = edl_project(tmp_path)
    write_json(tmp_path / "edl.json", edl)
    r = run(EDL_PY, "plan", tmp_path / "edl.json", "--platform", "x", "--x-720", env=NOFF)
    assert r.returncode == 0 and "scale=1280:720:" in r.stdout and "NOTE  x exported at 1280x720" in r.stdout
    r = run(EDL_PY, "plan", tmp_path / "edl.json", "--platform", "x", env=NOFF)
    assert "scale=1920:1080:" in r.stdout and "1280x720" not in r.stdout
    s, _n = edl_mod.export_steps(edl_mod.normalize_edl(edl, str(tmp_path)), "steam", {}, x_720=True)
    assert any("scale=1920:1080:" in a for a in s[0]["argv"])  # only x changes
    # trailer_qc.py is `trailer_edl.py qc` under its own name (the Exports phase observes it)
    r = run(SCRIPTS / "trailer_qc.py", tmp_path / "exports", env=NOFF)
    assert r.returncode == 3 and last(r) == "RESULT: FAIL ffmpeg not found", r.stdout


def test_exports_phase_requires_the_qc_command():
    data = tomllib.loads((SKILL / "chains/trailer.toml").read_text())
    exports = next(p for p in data["phase"] if p["name"] == "Exports")
    observed = [c["observe"] for c in exports["done_when"] if c["type"] == "command_passes"]
    assert observed == ["trailer_qc"]  # not trailer_edl: poster/export runs must not satisfy the gate
    assert any(c.get("path") == "Trailer/*/review/qc.json" for c in exports["done_when"])


def test_qc_video_scan_decodes_once_for_freeze_and_flash(monkeypatch):
    calls = []

    def fake_run(ff, args):
        calls.append(args)
        return ("frame:0 pts:0 pts_time:0\nlavfi.signalstats.YAVG=10\n",
                "[freezedetect @ 0x1] lavfi.freezedetect.freeze_start: 2.5\n")

    monkeypatch.setattr(edl_mod, "_ff_run", fake_run)
    black, freezes, flashes = edl_mod.video_scan("ffmpeg", "x.mp4")
    assert freezes == [2.5] and black == [] and flashes == []
    assert sum(any("freezedetect" in a for a in c) for c in calls) == 1, calls


def test_sections_from_skips_non_object_chunks(tmp_path):
    grid = load("beat_grid")
    p = write_json(tmp_path / "plan.json", {"chunks": ["oops", {"text": "[Build] x", "duration_ms": 4000}, 7]})
    assert grid.sections_from(str(p), 10) == [{"name": "Build", "start": 0.0, "end": 4.0}]
    p = write_json(tmp_path / "beats.json", {"beats": [None, {"id": "hook", "start": 0, "end": 3}]})
    assert grid.sections_from(str(p), 10) == [{"name": "hook", "start": 0.0, "end": 3.0}]


FFMPEG_I_STDERR = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 's01.mp4':
  Duration: 00:00:04.03, start: 0.000000, bitrate: 1234 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 640x360, 30 fps
"""


def test_without_ffprobe_audio_is_detected_with_ffmpeg_not_assumed(tmp_path):
    info = common.parse_ffmpeg_info(FFMPEG_I_STDERR)
    assert info["format"]["duration"] == "4.03" and [s["codec_type"] for s in info["streams"]] == ["video"]
    assert (info["streams"][0]["width"], info["streams"][0]["height"]) == (640, 360)
    with_audio = common.parse_ffmpeg_info(FFMPEG_I_STDERR + "  Stream #0:1(und): Audio: aac (LC), 48000 Hz, "
                                                            "stereo, fltp, 128 kb/s (default)\n")
    assert common.stream(with_audio, "audio")["codec_name"] == "aac"
    assert common.parse_ffmpeg_info("s01.mp4: Invalid data found when processing input") is None
    e = edl_mod.normalize_edl(edl_project(tmp_path), str(tmp_path))
    it = e["items"][0]
    silent = edl_mod.clip_step(e, it, {"s01": info}, "build/clips/c01.mov", 320, 180)
    fc = silent["argv"][silent["argv"].index("-filter_complex") + 1]
    assert "[0:a]" not in fc and "anullsrc" in fc  # a source without audio gets silence, not a failing [0:a]
    loud = edl_mod.clip_step(e, it, {"s01": with_audio}, "build/clips/c01.mov", 320, 180)
    assert "[0:a]atrim" in loud["argv"][loud["argv"].index("-filter_complex") + 1]
    # nothing could probe the sources: render says so instead of silently assuming
    _steps, notes = edl_mod.render_steps(e, {})
    assert any("could not be probed" in n and "s01" in n for n in notes), notes
    # check without ffprobe but with an ffmpeg: the layout comes from ffmpeg -i
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\ncat >&2 <<'EOF'\n" + FFMPEG_I_STDERR + "EOF\nexit 1\n")
    fake.chmod(0o755)
    probes = edl_mod.check_edl_files(e, None, str(fake))
    assert probes["s01"]["probed_with"] == "ffmpeg"
    assert any("came from ffmpeg -i" in w for w in e["warnings"]), e["warnings"]


def test_plan_json_matches_golden(tmp_path):
    edl = edl_project(tmp_path)
    r = run(EDL_PY, "plan", write_json(tmp_path / "edl.json", edl), "--json", env=NOFF)
    assert r.returncode == 0 and last(r).startswith("RESULT: OK"), r.stdout + r.stderr
    got = json.loads("\n".join(r.stdout.strip().splitlines()[:-1]))
    golden = FIX / "plan_golden.json"
    if os.environ.get("TRAILER_UPDATE_GOLDEN"):
        golden.write_text(json.dumps(got, indent=1) + "\n")
    assert got == json.loads(golden.read_text())
    # The parts that matter, spelled out: positions, xfade offset, sample-exact audio, loudness placeholders.
    assert got["total_frames"] == 157 and [t["start"] for t in got["timeline"]] == [0, 45, 112]
    join = next(s for s in got["steps"] if s["name"] == "join")
    fc = join["argv"][join["argv"].index("-filter_complex") + 1]
    assert "xfade=transition=fade:duration=0.5:offset=1.5" in fc and "xfade=transition=fadeblack" in fc
    assert "trim=end_frame=157" in fc and "atrim=end_sample=251200" in fc
    apply_ = next(s for s in got["steps"] if s["name"] == "loudness apply")
    assert any("measured_I={input_i}" in a for a in apply_["argv"])
    assert all(s.get("key") for s in got["steps"] if s["name"].startswith("clip "))
    # plan for an export adds the vertical re-render and the encode
    r = run(EDL_PY, "plan", tmp_path / "edl.json", "--platform", "shorts", env=NOFF)
    assert r.returncode == 0 and "build/vertical/clips/c01.mov" in r.stdout and "exports/t1-shorts.mp4" in r.stdout
    assert "crop=1080:1920:(iw-ow)*0.3:0" in r.stdout and "gblur=sigma=30" in r.stdout


def test_ffmpeg_missing_exits_3(tmp_path):
    edl = edl_project(tmp_path)
    write_json(tmp_path / "edl.json", edl)
    for args in (["doctor"], ["render", tmp_path / "edl.json"], ["export", tmp_path / "edl.json"],
                 ["qc", tmp_path]):
        r = run(EDL_PY, *args, env=NOFF)
        assert r.returncode == 3 and last(r) == "RESULT: FAIL ffmpeg not found", (args, r.stdout)
    r = run(EDL_PY, env=NOFF)
    assert r.returncode == 2


# ====================================================================== captions


def test_srt_from_elevenlabs_transcript(tmp_path):
    out = tmp_path / "Trailer/x/captions/en.srt"
    (tmp_path / "ProjectSettings").mkdir()
    r = run(EDL_PY, "srt", FIX / "transcript.json", "--out", out, "--offset", "10", "--cards",
            tmp_path / "Trailer/x/captions/cards.json", "--font", "Assets/Fonts/G SDF.asset", env=NOFF)
    assert r.returncode == 0 and last(r).startswith("RESULT: OK"), r.stdout
    cues = edl_mod.read_srt(str(out))
    assert len(cues) >= 4
    assert cues[0][2] == "Every run rewrites the map." and abs(cues[0][0] - 10.1) < 1e-6
    assert any(c[2] == "[explosion]" for c in cues)
    for k, (a, b, text) in enumerate(cues):
        lines = text.split("\n")
        assert len(lines) <= 2 and all(len(x) <= 42 for x in lines), text
        assert 1.0 - 1e-6 <= b - a <= 6.0 + 1e-6, (a, b, text)
        if k + 1 < len(cues):
            assert b <= cues[k + 1][0] + 1e-6
    cards = json.loads((tmp_path / "Trailer/x/captions/cards.json").read_text())
    assert cards["out_dir"] == "Trailer/x/captions/png" and cards["cards"][0]["id"] == "cue-001"
    assert cards["font"] == "Assets/Fonts/G SDF.asset" and len(cards["cards"]) == len(cues)


def test_srt_from_vo_script(tmp_path):
    out = tmp_path / "en.srt"
    r = run(EDL_PY, "srt", FIX / "vo-script.md", "--out", out, env=NOFF)
    assert r.returncode == 0, r.stdout
    cues = edl_mod.read_srt(str(out))
    assert abs(cues[0][0] - 12.0) < 1e-6 and cues[0][2] == "Every run rewrites the map."
    assert len(cues) == 4  # the long line is split into two cues
    assert all(len(x) <= 42 for c in cues for x in c[2].split("\n"))
    assert abs(cues[-1][0] - 55.0) < 1e-6
    bad = tmp_path / "bad.md"
    bad.write_text("no marks here\n")
    assert run(EDL_PY, "srt", bad, "--out", out, env=NOFF).returncode == 1


# ====================================================================== beat grid


def click_track(path, bpm=120.0, dur=30.0, offset=0.25, sr=22050, channels=1):
    """Clicks on every beat, louder on every 4th (the downbeat)."""
    n = int(dur * sr)
    x = [0.0] * n
    per, k = 60.0 / bpm, 0
    while offset + k * per < dur - 0.05:
        s = int(round((offset + k * per) * sr))
        amp = 0.9 if k % 4 == 0 else 0.45
        for i in range(int(0.01 * sr)):
            if s + i < n:
                x[s + i] += amp * math.sin(2 * math.pi * 1000 * i / sr) * math.exp(-i / (0.003 * sr))
        k += 1
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<" + "h" * channels, *([int(v * 32767)] * channels)) for v in x))
    return path


def test_beat_grid_on_a_click_track(tmp_path):
    wav = click_track(tmp_path / "click.wav")
    plan = write_json(tmp_path / "plan.json", {"chunks": [
        {"text": "[Cold open] drums", "duration_ms": 10000, "positive_styles": ["x"]},
        {"text": "[Build] rising", "duration_ms": 20000, "positive_styles": ["y"]}]})
    out = tmp_path / "grid.json"
    r = run(GRID_PY, wav, "--sections", plan, "--out", out)
    assert r.returncode == 0 and last(r).startswith("RESULT: OK"), r.stdout
    g = json.loads(out.read_text())
    assert abs(g["bpm"] - 120.0) <= 0.5 and g["confidence"] >= 0.4
    assert len(g["beats"]) == 60
    assert max(abs(b - (0.25 + i * 0.5)) for i, b in enumerate(g["beats"])) <= 0.015
    assert abs(g["downbeats"][0] - 0.25) <= 0.015 and abs(g["downbeats"][1] - 2.25) <= 0.015
    assert [s["name"] for s in g["sections"]] == ["Cold open", "Build"] and g["sections"][1]["end"] == 30.0


def test_beat_grid_other_tempo_stereo_and_bpm_override(tmp_path):
    wav = click_track(tmp_path / "c97.wav", bpm=97, dur=20, offset=0.6, sr=32000, channels=2)
    r = run(GRID_PY, wav, "--out", tmp_path / "g.json")
    g = json.loads((tmp_path / "g.json").read_text())
    assert r.returncode == 0 and abs(g["bpm"] - 97) <= 0.5, r.stdout
    assert max(abs(b - (0.6 + i * 60 / 97)) for i, b in enumerate(g["beats"])) <= 0.015
    r = run(GRID_PY, wav, "--bpm", "97", "--out", tmp_path / "g2.json")
    g2 = json.loads((tmp_path / "g2.json").read_text())
    assert r.returncode == 0 and g2["bpm"] == 97.0 and g2["bpm_given"] is True
    assert abs(g2["beats"][0] - 0.6) <= 0.015


def test_beat_grid_fails_on_noise_unless_bpm_given(tmp_path):
    random.seed(7)
    p = tmp_path / "noise.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(random.uniform(-0.5, 0.5) * 32767)) for _ in range(16000 * 15)))
    r = run(GRID_PY, p, "--out", tmp_path / "n.json")
    assert r.returncode == 1 and "low confidence" in last(r), r.stdout
    r = run(GRID_PY, p, "--bpm", "120", "--out", tmp_path / "n.json")
    assert r.returncode == 0, r.stdout
    assert run(GRID_PY, tmp_path / "missing.wav").returncode == 1
    assert run(GRID_PY, p, "--bpm", "1000").returncode == 2


# ====================================================================== trailer review


def review(name, score, blockers=(), issues=(), words=None):
    return {"reviewer": name, "score": score, "blockers": list(blockers), "issues": list(issues),
            "three_words": words if words is not None else {
                "crunchy": {"answer": "yes", "evidence": "first5.png 3-6"},
                "readable": {"answer": "yes", "evidence": "sheet-01.png"},
                "cozy": {"answer": "no", "evidence": "sheet-02.png cell 4"}},
            "timestamps": [1.0]}


def write_reviews(d, scores, **extra):
    names = ("Muted Scroller", "Trailer Editor", "Platform & Accessibility Auditor")
    for n, s in zip(names, scores):
        write_json(d / f"{n.split()[0].lower()}.json", review(n, s, **(extra.get(n) or {})))
    write_json(d / "qc.json", {"files": [], "failures": 0})  # not a review: skipped


def test_review_pass_uses_the_minimum(tmp_path):
    write_reviews(tmp_path, [8, 7, 9])
    r = run(REVIEW_PY, str(tmp_path / "*.json"), "--pass-score", "7", "--out", tmp_path / "decision.json")
    assert r.returncode == 0 and "TRAILER_REVIEW: PASS min=7" in r.stdout and last(r).startswith("RESULT: OK")
    assert "skipped (no reviewer key): qc.json" in r.stdout
    assert json.loads((tmp_path / "decision.json").read_text())["status"] == "PASS"
    r = run(REVIEW_PY, str(tmp_path / "*.json"), "--pass-score", "8")  # decision.json is skipped too
    assert r.returncode == 1 and "TRAILER_REVIEW: REFINE min=7" in r.stdout


def test_review_blocker_refines_then_escalates_in_round_two(tmp_path):
    write_reviews(tmp_path, [8, 8, 9], **{"Muted Scroller": {"blockers": ["first5.png frame 1: studio logo"]}})
    r = run(REVIEW_PY, str(tmp_path / "*.json"), "--pass-score", "7")
    assert r.returncode == 1 and "TRAILER_REVIEW: REFINE min=8" in r.stdout and "studio logo" in r.stdout
    r = run(REVIEW_PY, str(tmp_path / "*.json"), "--pass-score", "7", "--round", "2")
    assert r.returncode == 1 and "TRAILER_REVIEW: ESCALATE min=8" in r.stdout and "Accept as is" in r.stdout
    issue = {"severity": "blocker", "evidence": "qc.json: black start", "fix": "start later"}
    write_reviews(tmp_path, [8, 8, 9], **{"Trailer Editor": {"issues": [issue]}})
    assert "TRAILER_REVIEW: REFINE" in run(REVIEW_PY, str(tmp_path / "*.json")).stdout


def test_review_disagreement_escalates_and_taste_words_count(tmp_path):
    write_reviews(tmp_path, [9, 5, 9])
    r = run(REVIEW_PY, str(tmp_path / "*.json"), "--pass-score", "5")
    assert r.returncode == 1 and "TRAILER_REVIEW: ESCALATE min=5" in r.stdout and "disagree by 4" in r.stdout
    no = {"answer": "no", "evidence": "sheet"}
    write_reviews(tmp_path, [8, 8, 8], **{"Trailer Editor": {"words": {"a": no, "b": no, "c": {"answer": "yes",
                                                                                             "evidence": "x"}}}})
    r = run(REVIEW_PY, str(tmp_path / "*.json"))
    assert "TRAILER_REVIEW: REFINE min=8" in r.stdout and "taste words" in r.stdout


def test_review_invalid_or_missing_fails(tmp_path):
    write_reviews(tmp_path, [8, 8, 8])
    (tmp_path / "trailer.json").write_text("{not json")
    r = run(REVIEW_PY, str(tmp_path / "*.json"))
    assert r.returncode == 1 and "not valid JSON" in r.stdout and "TRAILER_REVIEW: ESCALATE min=0" in r.stdout
    (tmp_path / "trailer.json").unlink()
    (tmp_path / "platform.json").unlink()
    r = run(REVIEW_PY, str(tmp_path / "*.json"))
    assert r.returncode == 1 and "missing review from Platform & Accessibility Auditor" in r.stdout
    write_json(tmp_path / "platform.json", review("Platform & Accessibility Auditor", 11))
    r = run(REVIEW_PY, str(tmp_path / "*.json"))
    assert r.returncode == 1 and "score must be an integer 1-10" in r.stdout


# ====================================================================== real ffmpeg


def ff(*args, cwd=None):
    r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], capture_output=True,
                       text=True, cwd=cwd)
    assert r.returncode == 0, r.stderr
    return r


def ffprobe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True)
    info = json.loads(r.stdout)
    return {s["codec_type"]: s for s in info["streams"]}, info["format"]


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """Synthetic captures (testsrc2 + sine), a card, an overlay, music and VO; render + export steam and shorts."""
    if not (FFMPEG and FFPROBE):
        pytest.skip("ffmpeg/ffprobe not installed")
    d = tmp_path_factory.mktemp("trailer")
    (d / "capture").mkdir()
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4", "-f", "lavfi", "-i",
       "sine=frequency=440:duration=4:sample_rate=48000", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
       "-pix_fmt", "yuv420p", "-c:a", "aac", d / "capture/s01.mp4")
    ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4", "-c:v", "libx264", "-preset", "ultrafast",
       "-pix_fmt", "yuv420p", d / "capture/s02.mp4")
    (d / "audio").mkdir()
    ff("-f", "lavfi", "-i", "sine=frequency=220:duration=8:sample_rate=44100", d / "audio/music.wav")
    ff("-f", "lavfi", "-i", "sine=frequency=660:duration=1:sample_rate=44100", d / "audio/vo.wav")
    png(d / "cards/end.png", 640, 360, color=(200, 40, 40))
    png(d / "cards/bug.png", 80, 40, color=(255, 255, 255), alpha=160)
    png(d / "captions/png/cue-001.png", 600, 120, color=(0, 0, 0), alpha=160)
    (d / "captions/en.srt").write_text("1\n00:00:00,500 --> 00:00:02,000\nEvery run rewrites the map.\n\n")
    edl = {"version": 1, "id": "t1", "type": "social", "fps": 30, "canvas": {"w": 640, "h": 360},
           "sources": {"s01": "capture/s01.mp4", "s02": "capture/s02.mp4"},
           "video": [{"id": "c01", "src": "s01", "in": 0.0, "out": 2.0},
                     {"id": "c02", "src": "s02", "in": 1.0, "out": 2.0, "transition_in": {"type": "fade", "dur": 0.5},
                      "vcrop": {"x": 0.4}},
                     {"id": "c03", "src": "s01", "in": 2.0, "out": 3.0},
                     {"id": "c04", "card": "cards/end.png", "dur": 1.0,
                      "transition_in": {"type": "fadeblack", "dur": 0.25}}],
           "overlays": [{"image": "cards/bug.png", "start": 0, "end": 2, "pos": "top-right", "margin": 8,
                         "fade": 0.2}],
           "audio": {"game": {"enabled": True, "gain_db": -6},
                     "music": {"path": "audio/music.wav", "fade_out": 0.5},
                     "vo": [{"path": "audio/vo.wav", "at": 1.0}]},
           "captions": {"srt": "captions/en.srt", "burn_in_for": ["shorts"]},
           "exports": ["steam", "shorts"], "poster_at": 0.5}
    write_json(d / "edl.json", edl)
    out = {"dir": d}
    out["render"] = run(EDL_PY, "render", d / "edl.json")
    out["export"] = run(EDL_PY, "export", d / "edl.json", "--x264-preset", "veryfast")
    out["qc"] = run(EDL_PY, "qc", d / "exports", "--edl", d / "edl.json")
    return out


@needs_ffmpeg
def test_doctor_with_local_ffmpeg():
    r = run(EDL_PY, "doctor")
    assert r.returncode == 0 and last(r).startswith("RESULT: OK ffmpeg ready"), r.stdout


@needs_ffmpeg
def test_render_master_is_frame_and_sample_exact(rendered):
    r, d = rendered["render"], rendered["dir"]
    assert r.returncode == 0 and last(r).startswith("RESULT: OK rendered build/master.mov"), r.stdout + r.stderr
    assert any(x.startswith("TRAILER_OUTPUT: ") and x.endswith("build/master.mov") for x in r.stdout.splitlines())
    total = 60 + 30 - 15 + 30 + 30 - 8  # frames: c01 + c02 - fade + c03 + c04 - fadeblack (0.25 s -> 8 frames)
    st, _fmt = ffprobe(d / "build/master.mov")
    assert int(st["video"]["nb_frames"]) == total and st["video"]["codec_name"] == "prores"
    assert int(st["audio"]["sample_rate"]) == 48000 and int(st["audio"]["channels"]) == 2
    assert abs(float(st["audio"]["duration"]) - total / 30) < 0.001
    # the clip cache: a second render reuses every pass-1 clip
    r2 = run(EDL_PY, "render", d / "edl.json")
    assert r2.returncode == 0 and r2.stdout.count("cached") == 4, r2.stdout


@needs_ffmpeg
def test_exports_meet_platform_specs_and_qc_passes(rendered):
    d = rendered["dir"]
    r = rendered["export"]
    assert r.returncode == 0 and last(r).startswith("RESULT: OK exported steam, shorts"), r.stdout + r.stderr
    total = 127
    for name, (w, h) in (("t1-steam.mp4", (1920, 1080)), ("t1-shorts.mp4", (1080, 1920))):
        st, fmt = ffprobe(d / "exports" / name)
        v, a = st["video"], st["audio"]
        assert (v["width"], v["height"]) == (w, h), name
        assert v["codec_name"] == "h264" and v["profile"] == "High" and v["pix_fmt"] == "yuv420p", name
        assert v["avg_frame_rate"] == "30/1" and abs(int(v["nb_frames"]) - total) <= 1, name
        assert a["codec_name"] == "aac" and a["profile"] == "LC", name
        assert int(a["sample_rate"]) == 48000 and int(a["channels"]) == 2, name
        li, tp = edl_mod.loudness(FFMPEG, str(d / "exports" / name))
        assert abs(li - (-14)) <= 1.0 and tp <= -0.5, (name, li, tp)
    poster = common.png_info(str(d / "exports/poster.png"))
    assert poster[:2] == (1920, 1080)
    q = rendered["qc"]
    assert q.returncode == 0 and last(q).startswith("RESULT: OK 2 file(s) pass"), q.stdout
    report = json.loads((d / "review/qc.json").read_text())
    assert {f["platform"] for f in report["files"]} == {"steam", "shorts"} and report["failures"] == 0


@needs_ffmpeg
def test_sheets_and_poster_command(rendered):
    d = rendered["dir"]
    r = run(EDL_PY, "sheet", d / "build/master.mov", "--first5")
    assert r.returncode == 0 and (d / "review/first5.png").is_file(), r.stdout
    assert common.png_info(str(d / "review/first5.png"))[:2] == (2400, 540)
    r = run(EDL_PY, "sheet", d / "build/master.mov", "--scenes")
    assert r.returncode == 0 and (d / "review/sheet-01.png").is_file() and "SCENE: " in r.stdout, r.stdout
    r = run(EDL_PY, "poster", d / "edl.json", "--at", "3.9")
    assert r.returncode == 0 and "WARN" in r.stdout and "card c04" in r.stdout, r.stdout


@needs_ffmpeg
def test_qc_fails_a_black_start(tmp_path):
    ff("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=3", "-f", "lavfi", "-i",
       "sine=frequency=440:duration=3:sample_rate=48000", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
       "-pix_fmt", "yuv420p", "-c:a", "aac", tmp_path / "s01.mp4")
    png(tmp_path / "black.png", 320, 180, color=(0, 0, 0))
    edl = {"id": "b", "type": "social", "fps": 30, "canvas": {"w": 320, "h": 180}, "sources": {"s01": "s01.mp4"},
           "video": [{"id": "c00", "card": "black.png", "dur": 1.0}, {"id": "c01", "src": "s01", "in": 0, "out": 3}],
           "audio": {"game": {"enabled": False}},  # and nothing else: a silent mix
           "exports": ["steam"]}
    write_json(tmp_path / "edl.json", edl)
    r = run(EDL_PY, "render", tmp_path / "edl.json")
    assert r.returncode == 0 and "WARN  the mix is silent" in r.stdout, r.stdout + r.stderr
    assert run(EDL_PY, "export", tmp_path / "edl.json", "--x264-preset", "veryfast").returncode == 0
    r = run(EDL_PY, "qc", tmp_path / "exports", "--edl", tmp_path / "edl.json")
    assert r.returncode == 1 and "FAIL black start" in r.stdout and "FAIL loudness" in r.stdout, r.stdout


@needs_ffmpeg
def test_beat_grid_decodes_mp3_with_ffmpeg(tmp_path):
    wav = click_track(tmp_path / "c.wav", dur=12)
    enc = tmp_path / ("c.mp3" if "libmp3lame" in common.ffmpeg_caps(FFMPEG)["encoders"] else "c.m4a")
    ff("-i", wav, enc)
    r = run(GRID_PY, enc, "--out", tmp_path / "g.json")
    g = json.loads((tmp_path / "g.json").read_text())
    assert r.returncode == 0 and abs(g["bpm"] - 120) <= 0.5, r.stdout
    # encoder delay shifts compressed audio a little; the grid still lands within ~30 ms of the clicks
    assert abs(g["beats"][0] - 0.25) <= 0.035
