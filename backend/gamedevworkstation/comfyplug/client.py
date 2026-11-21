"""Shared plumbing: find comfy-cli, run it, set workflow slots, run a workflow, download outputs."""
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.join(PKG_DIR, "workflows")
DEFAULT_URL = "http://127.0.0.1:8188"
# configure() overrides (a host app such as GDH sets these from its settings); else the environment.
_settings = {"url": None, "cli": None}


def configure(url=None, cli=None):
    """Point ComfyPlug at a ComfyUI server and/or a comfy-cli executable ("" or None = environment/default)."""
    _settings["url"] = url or None
    _settings["cli"] = cli or None


def comfy_url():
    """The ComfyUI base URL: configure(url=...), else $COMFY_URL, else http://127.0.0.1:8188."""
    return (_settings["url"] or os.environ.get("COMFY_URL") or DEFAULT_URL).rstrip("/")


def host_port():
    u = urllib.parse.urlparse(comfy_url())
    return u.hostname or "127.0.0.1", u.port or 8188


def is_remote():
    """Another machine's ComfyUI (COMFY_URL=http://<ip>:8188): comfy-cli's `run` gets --host/--port, and outputs
    are fetched over HTTP because `comfy download` only reaches a local server."""
    return host_port()[0] not in ("127.0.0.1", "localhost", "::1")


class ComfyError(RuntimeError):
    """Any generation failure, with a readable message."""


def workflow_path(name):
    """A bundled template by name (workflows/<name>), or a path to any workflow JSON file."""
    p = name if os.path.isabs(name) or os.sep in name or "/" in name else os.path.join(WORKFLOW_DIR, name)
    if not os.path.isfile(p):
        raise ComfyError(f"workflow template missing: {p}")
    return p


def find_comfy():
    exe = _settings["cli"] or os.environ.get("COMFY_CLI") or shutil.which("comfy")
    if not exe:
        for cand in ("~/.local/bin/comfy", "~/.local/bin/comfy.exe"):
            c = os.path.expanduser(cand)
            if os.path.isfile(c):
                exe = c
                break
    if not exe:
        raise ComfyError("comfy-cli not found (looked on PATH and ~/.local/bin). Install it or set COMFY_CLI.")
    return exe


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise ComfyError("ffmpeg not found on PATH (needed for sound clean-up).")
    return exe


def check_server(timeout=5):
    """Return the /system_stats dict, or raise ComfyError if ComfyUI is not answering."""
    try:
        with urllib.request.urlopen(comfy_url() + "/system_stats", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ComfyError(f"ComfyUI is not answering at {comfy_url()} ({e}). Start Comfy Desktop first.")


def run_comfy(args):
    """Run `comfy <args>`; return stdout. Raises ComfyError with the output on failure."""
    p = subprocess.run([find_comfy()] + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise ComfyError(f"comfy {args[0]} failed ({p.returncode}):\n{p.stdout[-1500:]}\n{p.stderr[-1500:]}")
    return p.stdout


def last_json(text):
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise ComfyError("no JSON envelope in comfy output:\n" + text[-2000:])


def set_slots(wf_path, slots):
    """slots: dict like {"459/452.prompt": "text", "459.seed": 11, "459.switch": False}. Values are JSON-encoded.
    set-slot reads the server's node definitions (/object_info). comfy-cli fetches them itself only from a local
    server; for another machine ComfyPlug fetches them from comfy_url() and passes the file with --input."""
    if not slots:
        return
    host, port = host_port()
    where = ["--host", host, "--port", str(port)]
    if is_remote():
        info = os.path.join(os.path.dirname(os.path.abspath(wf_path)), "object_info.json")
        if not os.path.isfile(info):
            try:
                with urllib.request.urlopen(comfy_url() + "/object_info", timeout=120) as r, open(info, "wb") as f:
                    shutil.copyfileobj(r, f)
            except OSError as e:
                raise ComfyError(f"couldn't read node definitions from {comfy_url()}/object_info ({e})")
        where = ["--input", info]
    run_comfy(["workflow", "set-slot", wf_path] + [f"{k}={json.dumps(v)}" for k, v in slots.items()] + where)


def run_workflow(template, slots, exts, timeout=900):
    """Copy a template, set slots, run it, download outputs.

    Returns (work_dir, prompt_id, [downloaded file paths whose extension is in exts]).
    The caller must shutil.rmtree(work_dir) when done (see `cleanup`).
    """
    check_server()
    host, port = host_port()
    work = tempfile.mkdtemp(prefix="comfyplug_")
    try:
        wf = os.path.join(work, "wf.json")
        shutil.copy(workflow_path(template), wf)
        set_slots(wf, slots)
        env = last_json(run_comfy(["--json", "run", "--workflow", wf, "--wait", "--timeout", str(timeout),
                                   "--host", host, "--port", str(port)]))
        pid = (env.get("data") or {}).get("prompt_id") or env.get("prompt_id")
        if not pid:
            raise ComfyError("no prompt_id: " + json.dumps(env)[:1000])
        dl = os.path.join(work, "dl")
        os.makedirs(dl, exist_ok=True)
        if is_remote():
            download_http(pid, dl)
        else:
            run_comfy(["download", pid, "--where", "local", "-o", dl])
        files = [os.path.join(r, f) for r, _, fs in os.walk(dl) for f in fs if f.lower().endswith(tuple(exts))]
        if not files:
            raise ComfyError(f"no {'/'.join(exts)} output downloaded for {pid}")
        return work, pid, files
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def download_http(pid, out_dir):
    """Fetch every output file of a finished prompt from comfy_url() (/history + /view) into out_dir."""
    base = comfy_url()
    with urllib.request.urlopen(f"{base}/history/{pid}", timeout=60) as r:
        entry = json.loads(r.read().decode()).get(pid) or {}
    for node in (entry.get("outputs") or {}).values():
        for items in node.values():
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict) or "filename" not in it:
                    continue
                q = urllib.parse.urlencode({"filename": it["filename"], "subfolder": it.get("subfolder", ""),
                                            "type": it.get("type", "output")})
                dst = os.path.join(out_dir, os.path.basename(it["filename"]))
                with urllib.request.urlopen(f"{base}/view?{q}", timeout=300) as r, open(dst, "wb") as f:
                    shutil.copyfileobj(r, f)


def cleanup(work):
    shutil.rmtree(work, ignore_errors=True)


def ensure_parent(path):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    return d
