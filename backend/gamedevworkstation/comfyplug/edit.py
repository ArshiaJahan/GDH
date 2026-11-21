"""Image edit with Qwen Image 2.1: input image + instruction -> new image.

Uses the same models as `image` (Qwen Image 2.1 int8, qwen3vl text encoder, Qwen VAE), so nothing extra to download.
The graph is the gallery template `image_qwen_image_2_1_image_edit` rebuilt as a plain API prompt and sent to
ComfyUI's HTTP API (no comfy-cli): the template's subgraph through `comfy run` produced a purple, ruined image.
The input is spliced in as a reference image of TextEncodeQwenImage21; sampling starts from an empty latent.
The instruction is used as written (no prompt re-writer). No brand names in prompts.
"""
import json
import mimetypes
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import client


def image_size(path):
    """(width, height) of a PNG or JPEG, read from its header (Pillow when installed, for anything else)."""
    with open(path, "rb") as f:
        head = f.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
            return struct.unpack(">II", head[16:24])
        if head[:2] == b"\xff\xd8":
            f.seek(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    break
                if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
                    continue
                n = struct.unpack(">H", f.read(2))[0]
                if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">xHH", f.read(5))
                    return w, h
                f.seek(n - 2, 1)
    try:
        from PIL import Image
    except ImportError:
        raise client.ComfyError(f"can't read the size of {path}; pass width and height") from None
    with Image.open(path) as im:
        return im.size


def upload_input(path):
    """Upload `path` to ComfyUI's input folder (overwrite); return the stored file name."""
    name = "comfyplug_" + os.path.basename(path)
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    ctype = mimetypes.guess_type(path)[0] or "image/png"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode(),
        data,
        f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--{boundary}--\r\n'.encode(),
    ]
    req = urllib.request.Request(client.comfy_url() + "/upload/image", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()
    return name


def build_graph(name, prompt, seed, steps, width, height):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": name}},
        "5": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "prompt": prompt, "negative_prompt": "", "resolution": 0,
            "images.image_1": ["4", 0], "vae": ["3", 0]}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "7": {"class_type": "QwenImage21Cache", "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["7", 0], "positive": ["5", 0], "negative": ["5", 1], "latent_image": ["6", 0], "seed": seed,
            "steps": steps, "cfg": 1, "sampler_name": "euler", "scheduler": "simple", "denoise": 1}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "comfyplug_edit"}},
    }


def edit_image(src, prompt, out, seed=11, steps=25, width=None, height=None, timeout=900):
    """Edit `src` (PNG/JPG path) following `prompt`; write the result PNG to `out`. Returns out.

    Output size defaults to the input's size (multiple of 8, capped to ~1 megapixel).
    """
    client.check_server()
    if width is None or height is None:
        w, h = image_size(src)
        s = min(1.0, (1024 * 1024 / (w * h)) ** 0.5)
        width, height = max(64, int(w * s) // 8 * 8), max(64, int(h * s) // 8 * 8)
    name = upload_input(src)
    graph = build_graph(name, prompt, int(seed), int(steps), int(width), int(height))
    req = urllib.request.Request(client.comfy_url() + "/prompt", data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.load(urllib.request.urlopen(req, timeout=60))["prompt_id"]
    except urllib.error.HTTPError as e:
        raise client.ComfyError("edit rejected by ComfyUI: " + e.read().decode(errors="replace")[:1500])
    t0 = time.time()
    while True:
        with urllib.request.urlopen(f"{client.comfy_url()}/history/{pid}", timeout=30) as r:
            h = json.load(r)
        if pid in h:
            break
        if time.time() - t0 > timeout:
            raise client.ComfyError(f"edit timed out after {timeout}s ({pid})")
        time.sleep(1.5)
    entry = h[pid]
    imgs = (entry.get("outputs", {}).get("10") or {}).get("images")
    if not imgs:
        raise client.ComfyError("edit produced no image: " + json.dumps(entry.get("status", {}))[:1500])
    i = imgs[0]
    q = urllib.parse.urlencode({"filename": i["filename"], "subfolder": i.get("subfolder", ""), "type": i.get("type", "output")})
    client.ensure_parent(out)
    with urllib.request.urlopen(f"{client.comfy_url()}/view?{q}", timeout=60) as r, open(out, "wb") as f:
        f.write(r.read())
    return out
