Automatic updates from GitHub Releases

- [new file]: when main has a version with no release
  yet, build the macOS app (zip and .dmg) and the Windows installer and
  publish them as GitHub Release v<version>.
- Those builds carry the "github" update channel. They check the latest
  release, download the asset for their platform into the updates folder,
  and the existing folder updater takes it from there. Local builds never
  call GitHub.
- The app installs a pending update by itself once no session is running
  ([updates] auto_install, on by default). It tries each version once, so
  a failed install never loops.
- Windows: a release is an installer; a PowerShell helper stops the app,
  runs it silently and starts the app again.

Interface the tests use (declarations only; the change adds or changes these):
- `def asset_name(version: str, platform: str | None = None) -> str | None:`
- `def latest_release(repo: str, fetch: Fetch = _http_get) -> dict | None:`
- `def download(url: str, dest: Path, size: int | None, fetch: Fetch = _http_get) -> Path:`
- `class ReleaseFeed:`
- `def due(self, now: float | None = None) -> bool:`
- `def poll(self, d: Path, current: str, *, is_newer: Callable[[Any, Any], bool],`
- `return Path(buf.value)`
- `def windows_helper_script(*, app_pid: int, backend_pid: int, installer: Path, app_exe: Path | None) -> str:`
- `def auto_install_enabled(self) -> bool:`
- `def busy(self) -> int:`
- `async def maybe_auto_install(self) -> dict | None:`
- `raise HTTPException(400, f"`
