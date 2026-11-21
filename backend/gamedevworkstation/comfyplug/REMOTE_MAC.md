# Using ComfyPlug from another machine (Mac guide for an agent)

comfyplug runs image, 3D-model and sound generation on the owner's Windows PC, which has the GPU and ComfyUI. You
run comfyplug on the Mac; it sends each job to that PC over the network and downloads the results to the Mac.
Read `README.md` in this folder for every command and option. This file covers only the remote setup.

## 1. What you need on the Mac

- Python 3 (no extra packages for images and models).
- comfy-cli: `pip3 install comfy-cli` (comfyplug uses it to fill workflow slots and to submit jobs).
  If `comfy` is not on PATH afterwards, set `export COMFY_CLI=$(python3 -m site --user-base)/bin/comfy`.
- For sound only: `brew install ffmpeg`, and `pip3 install numpy` for `loop` / `normalize` / `measure`.
- This folder (`comfyplug/`), including `workflows/`.

## 2. Point comfyplug at the PC

```bash
export COMFY_URL=http://<pc-lan-ip>:8188     # same Wi-Fi as the PC
# or, from anywhere on the owner's Tailscale network:
export COMFY_URL=http://<pc-tailscale-ip>:8188
```

When `COMFY_URL` is not localhost, comfyplug passes `--host`/`--port` to `comfy run` and downloads outputs over HTTP
(`/history` + `/view`). Set it in every shell you run comfyplug from (agent tools often start a fresh shell per
command, so put the `export` in the same command line: `COMFY_URL=http://... python3 -m comfyplug ...`).

## 3. Check, then generate

```bash
python3 -m comfyplug check     # must show ComfyUI answering at COMFY_URL, comfy-cli and (for sound) ffmpeg

python3 -m comfyplug image --prompt "a brass gear on a dark table" --out out/gear.png --aspect "1:1 (Square)"
python3 -m comfyplug sound --prompt "single heavy metal clank, close-up, dry" --out out/clank.wav --seconds 1.5 --variants 4
python3 -m comfyplug model --prompt "a brass lantern" --out out/lantern.glb --ref-only    # look at out/lantern_ref.png first
python3 -m comfyplug model --prompt "a brass lantern" --out out/lantern.glb --from-image out/lantern_ref.png
python3 -m comfyplug batch my_batch.json                # JSON list format: see README.md
```

Rough times: image 20-60 s, sound 10-40 s per take, 3D model 3-10 min.

## 4. Rules

- The PC runs ONE job at a time and other people may be using it: run your jobs one after another (never several
  comfyplug processes in parallel); expect to wait in the queue.
- No brand, franchise, film or show names in prompts; describe the style instead.
- Look at every output before using it (open the PNG, render or inspect the GLB, check the WAV).
- Do not try to start, stop, restart or update ComfyUI, install nodes or download models: you do not control that
  PC. If `check` says ComfyUI is not answering, tell your user to ask the PC owner to start it.

## 5. If it fails

- `ComfyUI is not answering at ...`: the PC is off, ComfyUI is not running, it is not listening on the network
  (Comfy Desktop: Settings > Server-Config > Host = 0.0.0.0), the Windows firewall blocks port 8188, or the Mac is not
  on the same network / Tailscale.
- `comfy-cli not found`: install comfy-cli or set `COMFY_CLI` to its path.
- `ffmpeg not found`: `brew install ffmpeg` (sound only).
- A job fails inside ComfyUI (missing model or node): report the error text to your user; the PC owner has to fix it.
