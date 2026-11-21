import json
import os
import struct
import urllib.parse
import urllib.request

import pytest

from gamedevworkstation.comfyplug import client, batch, workflow, cli, edit, model3d, image, audio


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    monkeypatch.setitem(client._settings, "url", None)
    monkeypatch.setitem(client._settings, "cli", None)
    monkeypatch.delenv("COMFY_URL", raising=False)
    monkeypatch.delenv("COMFY_CLI", raising=False)


def test_comfy_url_default_and_env_and_configure(monkeypatch):
    assert client.comfy_url() == "http://127.0.0.1:8188"
    monkeypatch.setenv("COMFY_URL", "http://10.1.2.3:9000/")
    assert client.comfy_url() == "http://10.1.2.3:9000"
    client.configure(url="http://5.6.7.8:1234")
    assert client.comfy_url() == "http://5.6.7.8:1234"
    client.configure()
    assert client.comfy_url() == "http://10.1.2.3:9000"


def test_host_port_and_is_remote():
    assert client.is_remote() is False
    client.configure(url="http://10.0.0.5:9000")
    assert client.host_port() == ("10.0.0.5", 9000)
    assert client.is_remote() is True


def test_find_comfy_configure_wins(monkeypatch, tmp_path):
    exe = tmp_path / "comfy"
    exe.write_text("", encoding="utf-8")
    client.configure(cli=str(exe))
    assert client.find_comfy() == str(exe)


def test_find_comfy_env(monkeypatch, tmp_path):
    exe = tmp_path / "comfy2"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("COMFY_CLI", str(exe))
    assert client.find_comfy() == str(exe)


def test_find_comfy_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(client.shutil, "which", lambda x: None)
    monkeypatch.setattr(client.os.path, "expanduser", lambda p: str(tmp_path / "nope" / "comfy"))
    with pytest.raises(client.ComfyError):
        client.find_comfy()


def test_last_json():
    text = 'noise\nnot json {\nbroken {"x":\n{"data": {"prompt_id": "p1"}}\nmore noise'
    assert client.last_json(text) == {"data": {"prompt_id": "p1"}}
    with pytest.raises(client.ComfyError):
        client.last_json("no json here\nreally none")


def test_set_slots_argv(monkeypatch):
    seen = []
    monkeypatch.setattr(client, "run_comfy", lambda args: seen.append(args))
    client.set_slots("wf.json", {"459.seed": 11, "459.switch": False, "459.text": "hi"})
    args = seen[0]
    assert args[0] == "workflow" and args[1] == "set-slot" and args[2] == "wf.json"
    kv = set(args[3:])
    assert "459.seed=11" in kv
    assert "459.switch=false" in kv
    assert '459.text="hi"' in kv
    assert args[-4:] == ["--host", "127.0.0.1", "--port", "8188"]


def test_set_slots_on_a_remote_server_passes_its_node_definitions(monkeypatch, tmp_path):
    # comfy-cli refuses to fetch /object_info from a non-loopback host, so ComfyPlug fetches it and passes --input
    seen, urls = [], []
    monkeypatch.setattr(client, "run_comfy", lambda args: seen.append(args))

    class Resp:
        def __init__(self):
            self.data = b'{"KSampler": {}}'
        def read(self, n=-1):
            d, self.data = self.data, b""
            return d
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    monkeypatch.setattr(client.urllib.request, "urlopen", lambda url, timeout=None: urls.append(url) or Resp())
    client.configure(url="http://10.0.0.5:9000")
    wf = tmp_path / "wf.json"
    client.set_slots(str(wf), {"3.seed": 1})
    info = tmp_path / "object_info.json"
    assert urls == ["http://10.0.0.5:9000/object_info"] and info.read_bytes() == b'{"KSampler": {}}'
    assert seen[0][-2:] == ["--input", str(info)]
    client.set_slots(str(wf), {"3.seed": 2})
    assert len(urls) == 1  # fetched once per work dir
    client.set_slots(str(wf), {})
    assert len(seen) == 2  # nothing to set: no comfy-cli call


def test_workflow_path_bundled_and_custom(tmp_path):
    p = client.workflow_path("qwen21_t2i_direct.json")
    assert p.startswith(client.WORKFLOW_DIR) and os.path.isfile(p)
    custom = tmp_path / "w.json"
    custom.write_text("{}", encoding="utf-8")
    assert client.workflow_path(str(custom)) == str(custom)
    with pytest.raises(client.ComfyError):
        client.workflow_path("no_such_template.json")


def test_run_workflow_local(monkeypatch, tmp_path):
    monkeypatch.setattr(client, "check_server", lambda: {})
    outpng = {}
    calls = []
    def fake_run(args):
        calls.append(args)
        if args[:2] == ["--json", "run"]:
            return 'progress...\n{"data": {"prompt_id": "p1"}}'
        if args[0] == "download":
            dl = args[args.index("-o") + 1]
            f = os.path.join(dl, "out.png")
            with open(f, "wb") as fh:
                fh.write(b"png")
            outpng["f"] = f
            return ""
        return ""
    monkeypatch.setattr(client, "run_comfy", fake_run)
    work, pid, files = client.run_workflow("qwen21_t2i_direct.json", {"459.seed": 3}, [".png"])
    try:
        assert pid == "p1"
        assert files == [outpng["f"]]
        # the template is copied into the work dir before its slots are set: the bundled file never changes
        assert calls[0][:4] == ["workflow", "set-slot", os.path.join(work, "wf.json"), "459.seed=3"]
        run = calls[1]
        assert run[run.index("--host") + 1] == "127.0.0.1" and run[run.index("--port") + 1] == "8188"
        assert calls[2][:2] == ["download", "p1"]
    finally:
        client.cleanup(work)


def test_run_workflow_remote_host_port(monkeypatch, tmp_path):
    client.configure(url="http://10.0.0.5:9000")
    monkeypatch.setattr(client, "check_server", lambda: {})
    captured = {}
    def fake_run(args):
        if args[:2] == ["--json", "run"]:
            captured["args"] = args
            return '{"data": {"prompt_id": "p9"}}'
        assert args[0] != "download", "a remote server's outputs come over HTTP"
        return ""
    monkeypatch.setattr(client, "run_comfy", fake_run)
    def fake_download(pid, dl):
        with open(os.path.join(dl, "a.png"), "wb") as f:
            f.write(b"x")
    monkeypatch.setattr(client, "download_http", fake_download)
    work, pid, files = client.run_workflow("qwen21_t2i_direct.json", {}, [".png"])
    client.cleanup(work)
    assert pid == "p9"
    args = captured["args"]
    i = args.index("--host")
    assert args[i + 1] == "10.0.0.5"
    j = args.index("--port")
    assert args[j + 1] == "9000"
    assert files == [os.path.join(work, "dl", "a.png")]


def test_run_workflow_no_file_cleans_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(client, "check_server", lambda: {})
    monkeypatch.setattr(client.tempfile, "mkdtemp", lambda prefix: str((tmp_path / prefix).mkdir() or tmp_path / prefix))
    def fake_run(args):
        if args[:2] == ["--json", "run"]:
            return '{"data": {"prompt_id": "p1"}}'
        return ""
    monkeypatch.setattr(client, "run_comfy", fake_run)
    with pytest.raises(client.ComfyError, match="no .png output"):
        client.run_workflow("qwen21_t2i_direct.json", {}, [".png"])
    assert not (tmp_path / "comfyplug_").exists()


def test_download_http(monkeypatch, tmp_path):
    history = json.dumps({"p1": {"outputs": {"9": {"images": [
        {"filename": "a.png", "subfolder": "", "type": "output"}]}}}}).encode()
    views = []
    class FakeResp:
        def __init__(self, data):
            self.data = data
        def read(self, n=-1):
            d, self.data = (self.data, b"") if n is None or n < 0 else (self.data[:n], self.data[n:])
            return d
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    def fake_urlopen(url, timeout=None):
        views.append(url)
        if "/history/" in url:
            return FakeResp(history)
        return FakeResp(b"bytes")
    monkeypatch.setattr(client.urllib.request, "urlopen", fake_urlopen)
    out = tmp_path / "dl"
    out.mkdir()
    client.download_http("p1", str(out))
    assert (out / "a.png").read_bytes() == b"bytes"
    q = urllib.parse.parse_qs(urllib.parse.urlparse(views[-1]).query)
    assert q["filename"] == ["a.png"]


def test_run_any(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    with open(work / "b.mp4", "wb") as f:
        f.write(b"v")
    with open(work / "a.png", "wb") as f:
        f.write(b"i")
    monkeypatch.setattr(client, "run_workflow", lambda *a, **k: (str(work), "p", [str(work / "b.mp4"), str(work / "a.png")]))
    cleaned = []
    monkeypatch.setattr(client, "cleanup", lambda w: cleaned.append(w))
    out_dir = tmp_path / "out"
    outs = workflow.run_any("tmpl", str(out_dir), prefix="x")
    assert outs == [str(out_dir / "x_1.png"), str(out_dir / "x_2.mp4")]
    assert cleaned == [str(work)]
    assert (out_dir / "x_1.png").read_bytes() == b"i"
    assert (out_dir / "x_2.mp4").read_bytes() == b"v"


def test_generate_image(monkeypatch, tmp_path):
    captured = {}
    def fake_run(template, slots, exts, timeout=900):
        captured["slots"] = slots
        work = tmp_path / "w"
        work.mkdir(exist_ok=True)
        f = work / "o.png"
        f.write_bytes(b"i")
        return str(work), "p", [str(f)]
    monkeypatch.setattr(client, "run_workflow", fake_run)
    cleaned = []
    monkeypatch.setattr(client, "cleanup", lambda w: cleaned.append(w))
    out = tmp_path / "nested" / "deep" / "img.png"
    r = image.generate_image("a fox", str(out))
    assert r == str(out)
    assert out.read_bytes() == b"i"
    s = captured["slots"]
    assert s["459/452.prompt"] == "a fox"
    assert s["459.switch"] is False
    assert s["461.filename_prefix"] == "comfyplug"
    assert cleaned


def test_generate_image_transparent(monkeypatch, tmp_path):
    captured = {}
    def fake_run(template, slots, exts, timeout=900):
        captured["slots"] = slots
        work = tmp_path / "w"
        work.mkdir(exist_ok=True)
        f = work / "o.png"
        f.write_bytes(b"i")
        return str(work), "p", [str(f)]
    monkeypatch.setattr(client, "run_workflow", fake_run)
    monkeypatch.setattr(client, "cleanup", lambda w: None)
    image.generate_image("a cat", str(tmp_path / "o.png"), transparent=True)
    assert captured["slots"]["459/452.prompt"] == image.TRANSPARENT_WRAP.format(p="a cat")


def test_generate_sound(monkeypatch, tmp_path):
    monkeypatch.setattr(client, "find_ffmpeg", lambda: "ffmpeg")
    captured = {}
    def fake_run(template, slots, exts, timeout=900):
        captured["slots"] = slots
        work = tmp_path / "w"
        work.mkdir(exist_ok=True)
        f = work / "o.flac"
        f.write_bytes(b"f")
        return str(work), "p", [str(f)]
    monkeypatch.setattr(client, "run_workflow", fake_run)
    calls = []
    def fake_subprocess_run(cmd, **kw):
        calls.append(cmd)
        out = cmd[-1]
        with open(out, "wb") as f:
            f.write(b"w")
        import subprocess as sp
        return sp.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(audio.subprocess, "run", fake_subprocess_run)
    out = tmp_path / "s.wav"
    audio.generate_sound("boom", str(out))
    assert out.read_bytes() == b"w"
    assert captured["slots"]["52.use_reprompt"] is False
    assert "-af" in calls[0]
    audio.generate_sound("boom", str(tmp_path / "s2.wav"), trim=False)
    assert "-af" not in calls[1]


def test_generate_variants(monkeypatch, tmp_path):
    monkeypatch.setattr(client, "find_ffmpeg", lambda: "ffmpeg")
    seeds = []
    def fake_run(template, slots, exts, timeout=900):
        seeds.append(slots["52.seed"])
        if slots["52.seed"] == 2:
            raise client.ComfyError("boom take")
        work = tmp_path / "w"
        work.mkdir(exist_ok=True)
        f = work / "o.flac"
        f.write_bytes(b"f")
        return str(work), "p", [str(f)]
    monkeypatch.setattr(client, "run_workflow", fake_run)
    def fake_subprocess_run(cmd, **kw):
        import subprocess as sp
        with open(cmd[-1], "wb") as f:
            f.write(b"w")
        return sp.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(audio.subprocess, "run", fake_subprocess_run)
    out_dir = tmp_path / "out"
    outs = audio.generate_variants("x", str(out_dir), "n", n=3, seed=1)
    assert seeds == [1, 2, 3]
    assert outs[0] == str(out_dir / "n_1.wav")
    assert outs[2] == str(out_dir / "n_3.wav")
    assert isinstance(outs[1], tuple) and "boom take" in outs[1][1]


def make_png(w, h):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">II", w, h) + b"\x00\x00\x00")


def make_jpeg(w, h):
    sof = struct.pack(">BHHB", 8, h, w, 3)
    seg = lambda m, d: b"\xff" + m + struct.pack(">H", len(d) + 2) + d
    return b"\xff\xd8" + seg(b"\xe0", b"JFIF\x00") + seg(b"\xc0", sof) + b"\xff\xd9"


def test_image_size(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(make_png(640, 480))
    assert edit.image_size(str(p)) == (640, 480)
    j = tmp_path / "b.jpg"
    j.write_bytes(make_jpeg(320, 200))
    assert edit.image_size(str(j)) == (320, 200)


def test_image_size_no_pil(monkeypatch, tmp_path):
    p = tmp_path / "c.bin"
    p.write_bytes(b"not an image at all" * 2)
    real_import = __import__
    def fake_import(name, *a, **k):
        if name == "PIL":
            raise ImportError("no PIL")
        return real_import(name, *a, **k)
    monkeypatch.setattr("builtins.__import__", fake_import)
    with pytest.raises(client.ComfyError):
        edit.image_size(str(p))


def write_glb(tmp_path, obj, name="m.glb"):
    j = json.dumps(obj).encode()
    data = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(j)) + b"JSON" + struct.pack("<I", len(j)) + j
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_glb_score(tmp_path):
    p = write_glb(tmp_path, {"meshes": [{"primitives": [{"attributes": {"TEXCOORD_0": 0}}]}], "images": [{}]})
    assert model3d._glb_score(p) == (1, 1, 0)
    g = tmp_path / "bad.glb"
    g.write_bytes(b"garbage")
    assert model3d._glb_score(str(g)) == (-1, 0, 0)


def test_generate_model_ref_only(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(client, "run_workflow", lambda *a, **k: calls.append(a))
    ref = tmp_path / "r.png"
    ref.write_bytes(b"i")
    monkeypatch.setattr(model3d, "generate_image", lambda *a, **k: str(ref))
    out = tmp_path / "m.glb"
    r = model3d.generate_model("a chair", str(out), ref_only=True)
    assert r == {"glb": None, "ref": str(ref), "prompt_id": None}
    assert not calls


def test_batch_item_name_and_outputs():
    assert batch.item_name({"out": "x/y/thing.png"}) == "thing"
    assert batch.item_name({"name": "nm", "out": "x/y/thing.png"}) == "nm"
    assert batch._outputs({"kind": "sound", "out": "o/s.wav", "variants": 3}) == ["o/s_1.wav", "o/s_2.wav", "o/s_3.wav"]
    assert batch._outputs({"kind": "model", "out": "o/m.glb", "ref_only": True}) == ["o/m_ref.png"]


def test_run_items(monkeypatch, tmp_path):
    ok_items = [
        {"kind": "image", "name": "a", "out": str(tmp_path / "a.png"), "prompt": "p"},
        {"kind": "image", "name": "b", "out": str(tmp_path / "b.png"), "prompt": "p"},
        {"kind": "image", "name": "c", "out": str(tmp_path / "c.png"), "prompt": "p"},
    ]
    (tmp_path / "b.png").write_bytes(b"x")
    calls = []
    def fake_run(item):
        calls.append(item["name"])
        if item["name"] == "a":
            raise client.ComfyError("nope")
        with open(item["out"], "wb") as f:
            f.write(b"x")
        return item["out"]
    monkeypatch.setattr(batch, "run_item", fake_run)
    ok, skipped, failed = batch.run_items(ok_items)
    assert (ok, skipped, failed) == (1, 1, 1)
    assert calls == ["a", "c"]
    ok, skipped, failed = batch.run_items(ok_items, names=("c",), force=True)
    assert (ok, skipped, failed) == (1, 0, 0)
    ok, skipped, failed = batch.run_items(ok_items, names=("c",))
    assert (ok, skipped, failed) == (0, 1, 0)


def test_run_batch_file_rejects_non_list(tmp_path):
    p = tmp_path / "batch.json"
    p.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(client.ComfyError):
        batch.run_batch_file(str(p))


def test_cli_workflow_slots(monkeypatch, tmp_path, capsys):
    captured = {}
    def fake_run_any(wf, out_dir, slots, exts, timeout, prefix):
        captured["slots"] = slots
        captured["wf"] = wf
        return []
    monkeypatch.setattr(cli, "run_any", fake_run_any)
    rc = cli.main(["workflow", "t.json", "--out-dir", str(tmp_path),
                   "--slot", "3.seed=7", "--slot", '6.text="a fox"', "--slot", "9.note=plain text"])
    assert rc == 0
    assert captured["slots"] == {"3.seed": 7, "6.text": "a fox", "9.note": "plain text"}
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True


def test_cli_bad_slot(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "run_any", lambda *a, **k: [])
    rc = cli.main(["workflow", "t.json", "--out-dir", str(tmp_path), "--slot", "badsignature"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "FAILED" in err


def test_cli_check_failure(monkeypatch, capsys):
    def boom():
        raise client.ComfyError("not answering")
    monkeypatch.setattr(client, "check_server", boom)
    assert cli.main(["check"]) == 1
    assert "FAILED" in capsys.readouterr().err
