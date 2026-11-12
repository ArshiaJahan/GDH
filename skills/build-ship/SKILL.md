---
name: build-ship
description: Ships a Unity 6 (6000.3) game from macOS - preflight (compile, tests via headless-ops, clean git), SemVer + build-number bump, Build Profiles per platform (macOS primary, Windows Mono, Web), builds into builds/<version>/<platform>/, player smoke test, Keep a Changelog section, git tag, macOS ad-hoc sign/zip/dmg. Use when asked to make a release or test build, ship, bump the version, write the changelog, tag a release (e.g. v1.2.0), or smoke test the player.
---

# build-ship

Turn a green project into a versioned, smoke-tested, tagged player build with a changelog entry.

Pinned: Unity 6000.3.21f1 (macOS Apple Silicon host), Mono backend, MCP for Unity 10.3.0, Keep a Changelog 1.1, SemVer 2.0.
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. `mcp__UnityMCP__manage_build`). For tool parameters see unity-mcp-orchestrator.
`<skills>` = the folder holding the skills; `H=<skills>/headless-ops/scripts`, `B=<skills>/build-ship/scripts`.

## When to use / not to use
- Use for release or test builds, version bumps, changelog/tag work, player smoke tests, macOS packaging.
- Not for: fixing compile errors (compile-fix-loop), gameplay acceptance (play-verify), batchmode mechanics
  (headless-ops), git hooks/LFS/merge setup (vcs-hygiene), performance budgets (perf-pass).

## Inputs
- Project root, target platforms (default: macOS), release kind (major|minor|patch or an explicit X.Y.Z), dev or release build.
- Optional: Build Profile assets, repo compare URL for changelog links, signing identity (only if the user gives one).

## One-time setup
1. Copy `<skills>/build-ship/templates/Runtime/` → `Assets/Harness/Ship/Runtime/` (SmokeTest.cs + `Harness.Ship.asmdef`,
   all platforms, auto-referenced) and `templates/Editor/` → `Assets/Harness/Ship/Editor/` (ShipVersion.cs, Editor-only asmdef).
   headless-ops' HarnessCli must be installed too (`Assets/Harness/Headless/Editor/`).
2. Optional: add the `Harness.Ship.SmokeTest` component to a GameObject in the first build scene (its Inspector value is
   the default smoke duration). Without it the runner is created automatically when the player gets `-smoketest`.
   It is inert in normal runs and never runs in the Editor.
3. Make sure `builds/` and `Logs/` are git-ignored (vcs-hygiene's Unity6.gitignore has `/[Bb]uilds/`).
4. Optional Build Profiles under `Assets/Settings/BuildProfiles/` (see references/platforms.md); otherwise the scenes in
   the global scene list (EditorBuildSettings) are built.

## Procedure
In GameDevWorkstation, builds go through the `unity` tool (`op=build profile=… | target=…, out=…`; `dev=true` uses unity.sh +
HarnessCli): the official Unity CLI's `unity build` when the user's Unity backend allows it, else headless-ops.
1. **Path.** Read `mcpforunity://instances`. Editor open on this project → MCP path (step 6b); otherwise headless.
2. **Preflight (all must pass; stop on the first failure).**
   - `git status --porcelain` is empty (otherwise ask the user to commit or stash; never discard changes).
   - Tag check: `git tag -l vX.Y.Z` is empty.
   - Compile: `$H/unity.sh compile` → `RESULT: OK` (editor open: compile-fix-loop's MCP Verify).
   - Tests: `$H/unity.sh test editmode` and `$H/unity.sh test playmode` → `RESULT: OK … failed=0` (a project without
     tests: say so in the report; editor open: `run_tests` + `get_test_job` with `failed == 0`).
3. **Pick the version.** `python3 $B/version.py show`; next = `python3 $B/version.py next major|minor|patch` (rules in
   references/versioning.md; `feat` → minor, breaking → major, else patch). Confirm with the user when it is a MAJOR.
4. **Bump.** Editor closed: `python3 $B/version.py set X.Y.Z` (bundleVersion + build number max+1 for macOS/iOS/Android).
   Editor open: `manage_build(action="settings", property="version", value="X.Y.Z")`, then `execute_code` with
   `Harness.Ship.ShipVersion.Apply("X.Y.Z", 0);` for the build numbers. ⚠ version-sensitive: `PlayerSettings.macOS.buildNumber`
   is undocumented for 6000.3 but works on 6000.3.21f1 (writes `CFBundleVersion`).
5. **Changelog + release commit.** `python3 $B/changelog.py --version X.Y.Z [--compare-url <repo-url>]`, read the new
   section, fix wording by hand if needed, then `git add ProjectSettings/ProjectSettings.asset CHANGELOG.md` and
   `git commit -m "chore(release): vX.Y.Z"`.
6. **Build each platform** (one Unity run per platform; release unless the user asked for dev):
   a. Headless: `$H/unity.sh build macos --out builds/X.Y.Z/macos` (or a profile:
      `$H/unity.sh build Assets/Settings/BuildProfiles/macOS.asset --out builds/X.Y.Z/macos`; `windows`, `webgl` the same way;
      `--dev` for development builds). Read `builds/X.Y.Z/<platform>/build-report.json`.
   b. MCP: `manage_build(action="build", target="osx", output_path="builds/X.Y.Z/macos/<Product>.app")` (or
      `profile="Assets/…asset"`), poll `manage_build(action="status", job_id=…)` until it finishes; no build-report.json
      is written on this path, so record the status result. [UNVERIFIED] whether `output_path` wants the `.app` path or a folder:
      check where the player landed before the smoke test.
   Switching platforms reimports assets for that target; budget minutes per switch on a large project.
7. **Smoke test** (macOS, on this Mac): `$B/smoke_test.sh builds/X.Y.Z/macos/<Product>.app [--seconds 10] [--headless]`.
   It starts the player with `-smoketest -smokeSeconds N -smokeOut <file> -logFile <file>` and a watchdog, and passes when
   the result file's first line is `ok` (no exceptions, asserts or `Debug.LogError`, frames advanced) and the player exited 0.
   Windows/Web: see references/platforms.md (needs a Windows machine / a browser).
8. **Package (macOS).** `$B/package_macos.sh builds/X.Y.Z/macos/<Product>.app [--dmg]` → ad-hoc signed `.app`,
   `<Product>-X.Y.Z-macos.zip` (+ `.dmg`) and SHA-256 lines. Re-run the smoke test if you changed the bundle afterwards.
9. **Tag.** `git tag -a vX.Y.Z -m "vX.Y.Z"`. Push the commit and tag only when the user asks.
10. **Report** (format below).

## Rules
- Never build from a dirty tree or with failing tests; never skip the smoke test for a release.
- Output layout is fixed: `builds/<version>/<platform>/` (`macos`, `windows`, `webgl`, `ios`, `android`), each with
  `build-report.json`; never overwrite an existing version folder for a different commit (bump PATCH instead).
- One target per Unity invocation; batchmode cannot switch targets from code. Keep Build Profiles under `Assets/`.
- Version lives only in `PlayerSettings.bundleVersion` (SemVer) + build numbers; never hard-code it in scripts
  (read `Application.version`).
- Do not ship `<Product>_BurstDebugInformation_DoNotShip/`, `build-report.json` or `smoke-*` files.
- Signing: ad-hoc only, unless the user supplies a Developer ID identity; never invent identities or notarize on your own.
- Do not edit `ProjectSettings.asset` by script while an editor has the project open.

## Failure handling / stop conditions
- Preflight failure → stop, report which gate failed, hand over (compile-fix-loop for compile errors, the failing test
  names for tests, the user for a dirty tree).
- `RESULT: FAIL build …` → read `errorMessages` in build-report.json and the log; missing module ("not installed"
  / "No … module loaded") → ask the user to add it in Unity Hub; stop.
- Smoke `fail: N exception(s)` → read `message=` lines in the result file and `smoke-player.log`; fix, rebuild (same
  version if not yet tagged). `timeout` → the script prints the log tail and whether `[SMOKE] start` was reached. A windowed
  launch stalled once in 7 runs here (not reproducible; the next run passed): retry once, then try `--headless` to separate
  window/GPU problems from game problems; two failures → stop and report.
- Smoke `no result file` → SmokeTest is not compiled into the player (asmdef missing, or a define stripped it) or the
  player crashed early; check `smoke-player.log`.
- changelog.py exit 2 (nothing to release) → ask whether to release anyway with a hand-written entry.

## Report format
```
build-ship: vX.Y.Z (build N) <OK|FAILED at step k>
Preflight: compile OK · editmode N/N · playmode N/N · git clean
Builds: macos Succeeded 112 MB builds/X.Y.Z/macos/<Product>.app · windows …
Smoke: macos ok frames=… exceptions=0 errors=0
Package: builds/X.Y.Z/macos/<Product>-X.Y.Z-macos.zip sha256 …
Changelog: [X.Y.Z] Added n · Changed n · Fixed n   Tag: vX.Y.Z (not pushed)
```

## References
- references/platforms.md: read for Build Profiles, Windows/Web/iOS/Android specifics, macOS signing/notarization, player logs.
- references/versioning.md: read for version fields, build numbers, next-version rules, changelog.py mapping and tagging.

## Verify
All must be observed for the release (per platform built):
- `unity.sh build …` exits 0 and prints `RESULT: OK build Succeeded …`; `python3 -c "import json;print(json.load(open('builds/X.Y.Z/macos/build-report.json'))['result'])"` prints `Succeeded` and `version` in that file is `X.Y.Z`.
- `smoke_test.sh builds/X.Y.Z/macos/<Product>.app` exits 0, prints `RESULT: OK smoke …`, and the result file's first line is `ok`.
- `/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' builds/X.Y.Z/macos/<Product>.app/Contents/Info.plist` prints `X.Y.Z`.
- `grep -n '^## \[X.Y.Z\]' CHANGELOG.md` finds exactly one line.
- `git tag -l vX.Y.Z` prints `vX.Y.Z`, and `git status --porcelain` is empty.
