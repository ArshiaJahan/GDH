"""Updates from GitHub Releases, for builds made by the release workflow.

CI release builds carry `channel = "github"` in their build info (scripts/version.py build-info
with GDW_UPDATE_CHANNEL set). Those builds ask the repository's latest release for a newer
version now and then and download the asset for this platform into the updates folder:

    macOS:    GameDevWorkstation-<v>-macos-arm64.zip  ->  <dir>/<v>/GameDevWorkstation.app
    Windows:  GameDevWorkstation-<v>-x64-setup.exe    ->  <dir>/<v>/GameDevWorkstation-<v>-x64-setup.exe

then write `<dir>/<v>/release.json` and `<dir>/latest.json`, the same layout `make release`
produces, so the folder updater (updates.py) takes it from there. Local builds have no channel
and never call GitHub, so a locally signed app is never replaced by a CI build.

Downloads go to a `.part` file first and are renamed only when complete; a release whose asset
is missing or whose size doesn't match is skipped.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

API = "https://api.github.com/repos/{repo}/releases/latest"
USER_AGENT = "GameDevWorkstation-updater"

Fetch = Callable[[str], bytes]


def asset_name(version: str, platform: str | None = None) -> str | None:
    plat = platform or sys.platform
    if plat == "darwin":
        return f"GameDevWorkstation-{version}-macos-arm64.zip"
    if plat == "win32":
        return f"GameDevWorkstation-{version}-x64-setup.exe"
    return None


def _http_get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed https URLs only
        return r.read()


def latest_release(repo: str, fetch: Fetch = _http_get) -> dict | None:
    """{version, notes, published_at, assets: {name: {url, size}}} for the latest release, or None."""
    try:
        data = json.loads(fetch(API.format(repo=repo)))
    except Exception as e:  # noqa: BLE001 — offline, rate-limited or a bad answer: try again later
        log.info("release check failed: %s", e)
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    assets = {a.get("name"): {"url": a.get("browser_download_url"), "size": a.get("size")}
              for a in data.get("assets") or [] if isinstance(a, dict) and a.get("name")}
    return {"version": tag.removeprefix("v"), "notes": str(data.get("body") or ""),
            "published_at": data.get("published_at"), "git_commit": (data.get("target_commitish") or "")[:7] or None,
            "assets": assets}


def download(url: str, dest: Path, size: int | None, fetch: Fetch = _http_get) -> Path:
    """Write `url` to `dest` via `dest.part`; raise ValueError if the size is wrong."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    data = fetch(url)  # the timeout is per socket read, so a slow large download still finishes
    if size is not None and len(data) != size:
        raise ValueError(f"{dest.name}: got {len(data)} bytes, the release says {size}")
    part.write_bytes(data)
    os.replace(part, dest)
    return dest


def unpack_app(zip_path: Path, into: Path) -> Path:
    """Extract a zipped GameDevWorkstation.app (made with `ditto -c -k --keepParent`)."""
    into.mkdir(parents=True, exist_ok=True)
    if shutil.which("ditto"):  # keeps symlinks and the code signature intact
        r = subprocess.run(["ditto", "-x", "-k", str(zip_path), str(into)], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise ValueError(f"couldn't unzip {zip_path.name}: {r.stderr.strip()[:300]}")
    else:
        with zipfile.ZipFile(zip_path) as z:
            for m in z.namelist():
                if m.startswith("/") or ".." in Path(m).parts:
                    raise ValueError(f"{zip_path.name} has an unsafe path: {m}")
            z.extractall(into)
    app = into / "GameDevWorkstation.app"
    if not (app / "Contents" / "Info.plist").is_file():
        raise ValueError(f"{zip_path.name} has no GameDevWorkstation.app inside")
    return app


def fetch_into(d: Path, rel: dict, *, platform: str | None = None, fetch: Fetch = _http_get,
               write_json: Callable[[Path, dict], None]) -> dict | None:
    """Download `rel`'s asset for this platform into the updates folder `d` and advertise it in
    latest.json. Returns the release record written, or None when there's nothing for this
    platform. Already-downloaded versions are not fetched again."""
    v = rel["version"]
    name = asset_name(v, platform)
    asset = rel["assets"].get(name) if name else None
    if not asset or not asset.get("url"):
        return None
    vdir = d / v
    plat = platform or sys.platform
    record = {"version": v, "built_at": rel.get("published_at"), "git_commit": rel.get("git_commit"),
              "notes": rel.get("notes") or "", "source": "github"}
    if plat == "darwin":
        app = vdir / "GameDevWorkstation.app"
        if not (app / "Contents" / "Info.plist").is_file():
            z = download(asset["url"], d / ".download" / name, asset.get("size"), fetch)
            try:
                unpack_app(z, vdir)
            finally:
                z.unlink(missing_ok=True)
        record["app"] = f"{v}/GameDevWorkstation.app"
    else:
        exe = vdir / name
        if not exe.is_file():
            download(asset["url"], exe, asset.get("size"), fetch)
        record["installer"] = f"{v}/{name}"
    write_json(vdir / "release.json", record)
    write_json(d / "latest.json", record)  # last, so a half-downloaded version is never advertised
    return record


class ReleaseFeed:
    """Polls GitHub at most every `interval_s` and downloads newer versions into the updates folder."""

    def __init__(self, repo: str, interval_s: float = 3600, fetch: Fetch = _http_get):
        self.repo, self.interval_s, self.fetch = repo, interval_s, fetch
        self.last_check = 0.0
        self.last_error: str | None = None
        self.last_seen: str | None = None

    def due(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.last_check >= self.interval_s

    def poll(self, d: Path, current: str, *, is_newer: Callable[[Any, Any], bool],
             write_json: Callable[[Path, dict], None], platform: str | None = None) -> dict | None:
        self.last_check = time.time()
        rel = latest_release(self.repo, self.fetch)
        if not rel:
            return None
        self.last_seen = rel["version"]
        if not is_newer(rel["version"], current):
            return None
        try:
            out = fetch_into(d, rel, platform=platform, fetch=self.fetch, write_json=write_json)
            self.last_error = None
            return out
        except Exception as e:  # noqa: BLE001 — a bad download must never take the app down
            self.last_error = str(e)[:300]
            log.warning("couldn't download %s: %s", rel["version"], e)
            return None
