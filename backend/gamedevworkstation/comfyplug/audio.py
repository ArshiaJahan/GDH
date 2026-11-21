"""Sound with the Stable Audio 3 Medium template, cleaned up to a game-ready WAV with ffmpeg.

The template's Qwen re-prompter is OFF (prompts are used as written). No brand, franchise, film or show names.
"""
import os
import shutil
import subprocess

from . import client

TEMPLATE = "stable_audio3.json"


def _clean_filter(seconds):
    # cut leading/trailing silence, cap the length, short fade-out, peak-normalise
    return ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
            "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
            f"atrim=0:{seconds + 0.25},afade=t=out:st={max(0.05, seconds - 0.15)}:d=0.35,"
            "dynaudnorm=p=0.89:m=1:g=3")


def generate_sound(prompt, out_wav, seconds=2.0, seed=1, category="SFX", raw_out=None, trim=True, sample_rate=44100):
    """Make one mono WAV at out_wav. raw_out: optional path to keep the untouched model output (flac).
    trim=False skips the silence cut / fade / normalise and only converts. Returns out_wav."""
    ffmpeg = client.find_ffmpeg()
    work, pid, files = client.run_workflow(TEMPLATE, {
        "52.user_input": prompt + f" Length: {int(round(seconds))} seconds",
        "52.duration": float(seconds),
        "52.seed": int(seed),
        "52.use_reprompt": False,
        "52.category": category,
        "57.format": "flac",
        "57.filename_prefix": "comfyplug_sfx",
    }, [".flac", ".mp3", ".wav", ".opus"])
    try:
        raw = files[0]
        if raw_out:
            if not os.path.splitext(raw_out)[1]:
                raw_out += os.path.splitext(raw)[1]
            client.ensure_parent(raw_out)
            shutil.copy(raw, raw_out)
        client.ensure_parent(out_wav)
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", raw, "-ac", "1", "-ar", str(int(sample_rate))]
        if trim:
            cmd += ["-af", _clean_filter(seconds)]
        r = subprocess.run(cmd + [out_wav], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise client.ComfyError("ffmpeg failed:\n" + r.stderr[-1500:])
    finally:
        client.cleanup(work)
    return out_wav


def generate_variants(prompt, out_dir, name, n=3, seconds=2.0, seed=1, **kw):
    """N takes with seed+i written to <out_dir>/<name>_1.wav .. <name>_N.wav. Returns the list of paths.
    A take that fails does not stop the others; failures are returned as (path, error) tuples at the end of the list."""
    outs = []
    for i in range(1, n + 1):
        path = os.path.join(out_dir, f"{name}_{i}.wav")
        try:
            outs.append(generate_sound(prompt, path, seconds=seconds, seed=seed + i - 1, **kw))
        except (client.ComfyError, OSError) as e:
            outs.append((path, str(e)))
    return outs
