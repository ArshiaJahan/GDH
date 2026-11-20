Fix Claude Code login detection on Windows

The env allowlist for every claude process only had macOS/Linux names, so
on Windows claude ran without USERPROFILE, APPDATA, SystemRoot or ComSpec.
It couldn't find the login saved by 'claude auth login' and always
reported 'not logged in'.

- Pass the Windows profile and system variables (case-insensitive)
- Find claude.exe / claude.cmd in ~/.local/bin, ~/.claude/local,
  %APPDATA%/npm and %LOCALAPPDATA%/Programs/claude when PATH lacks it
- Windows CI runs a real probe through a fake claude.cmd

Interface the tests use (declarations only; the change adds or changes these):
- `def _windows() -> bool:`
