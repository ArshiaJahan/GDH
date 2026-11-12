# Versioning, changelog and tags

Read when choosing the next version, editing build numbers, or when changelog.py output looks wrong.

## Fields (6000.3)
| Setting | API | ProjectSettings.asset key | Player shows it as |
|---|---|---|---|
| Version (all platforms) | `PlayerSettings.bundleVersion` = `Application.version` | `bundleVersion` | macOS/iOS `CFBundleShortVersionString` (✓ local: `0.1.0`), Windows file/product version, Web build metadata (✓ docs) |
| macOS build number | `PlayerSettings.macOS.buildNumber` (string) | `buildNumber: Standalone` | `CFBundleVersion` (✓ local: `2`). ⚠ version-sensitive: not on the 6000.3 bundleVersion docs page; compiles and works on 6000.3.21f1 |
| iOS build number | `PlayerSettings.iOS.buildNumber` (string) | `buildNumber: iPhone` | `CFBundleVersion` [UNVERIFIED in a built Xcode project] |
| Android version code | `PlayerSettings.Android.bundleVersionCode` (int) | `AndroidBundleVersionCode` | `versionCode` [UNVERIFIED in a built APK] |

Convention (ours): `bundleVersion` = SemVer `MAJOR.MINOR.PATCH` (optional `-rc.1` pre-release), one integer build number
shared by macOS/iOS/Android that only ever increases (stores reject lower numbers), git tag `vMAJOR.MINOR.PATCH`.

## Choosing the next version
From the commits since the last tag (what changelog.py groups):
- any `type!:` or `BREAKING CHANGE:` footer → MAJOR (before 1.0.0: MINOR)
- any `feat` → MINOR
- otherwise (`fix`, `perf`, `refactor`, …) → PATCH
`python3 scripts/version.py next major|minor|patch` prints the candidate; the user may override.

## Ways to write it
| Editor state | Command |
|---|---|
| closed | `python3 scripts/version.py set X.Y.Z [--build N]` (edits ProjectSettings.asset text; without `--build` uses max+1) ✓ local |
| closed, via Unity | `unity.sh exec Harness.Ship.ShipVersion.Set -shipVersion X.Y.Z [-buildNumber N]` ✓ local (never `-version`: Unity's own flag) |
| open | `manage_build(action="settings", property="version", value="X.Y.Z")`, or `execute_code` calling `Harness.Ship.ShipVersion.Apply("X.Y.Z", 0)` |
Read back: `version.py show` or `unity.sh exec Harness.Ship.ShipVersion.Print` (`[HARNESS] VERSION bundleVersion=…`).
Do not edit ProjectSettings.asset while an editor has the project open: the editor overwrites it on save.

## changelog.py (Keep a Changelog 1.1)
`python3 scripts/changelog.py --version X.Y.Z [--repo .] [--date YYYY-MM-DD] [--since REF] [--include-all] [--compare-url https://github.com/o/r] [--force] [--dry-run]`
- Reads `git log --no-merges <last v* tag>..HEAD`; inserts `## [X.Y.Z] - DATE` under `## [Unreleased]` (creating the file
  with the standard header if needed) and moves hand-written Unreleased bullets into it.
- Mapping: `feat`/add → Added · `fix`/hotfix → Fixed · `perf`/`refactor`/`style`/update/change → Changed ·
  deprecate → Deprecated · remove/delete/revert → Removed · security → Security · `docs`/`test`/`chore`/`ci`/`build`/`release`
  skipped (unless `--include-all`). Scope renders as `**scope:**`, breaking changes as `**BREAKING**`. Non-conventional
  subjects use their first word (`Remove …` → Removed), else Changed. Each bullet ends with the short hash.
- Exit 0 written · 1 error (bad version, git failure, section already exists without `--force`) · 2 nothing to release.
- ✓ local: two releases in a scratch repo (0.2.0 with Added/Changed/Removed/Fixed and a breaking entry; 0.2.1 merging a
  hand-written Unreleased bullet), compare links, refusal on a duplicate section, exit 2 right after a tag.

## Tagging
After the release commit (version bump + CHANGELOG) and a passing smoke test:
`git tag -a vX.Y.Z -m "vX.Y.Z"`; check with `git tag -l vX.Y.Z` and `git describe --tags --abbrev=0` → `vX.Y.Z`.
Push (`git push origin vX.Y.Z`) only when the user asks. Never move or delete an existing tag; ship a new PATCH instead.
