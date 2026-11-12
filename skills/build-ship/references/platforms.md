# Platforms, Build Profiles and packaging (Unity 6000.3, building on macOS)

Read when you set up Build Profiles, build for a platform other than macOS, package a build, or a player will not start.
"✓ local" = done on this Mac with 6000.3.21f1; [UNVERIFIED] = not tried here.

## Installed modules on this Mac
Mac Build Support (Mono + IL2CPP), Windows Build Support (Mono), Web, iOS, Android (+ OpenJDK 17, SDK/NDK). Not installed:
Linux, dedicated server, tvOS, visionOS. Add modules through Unity Hub (Installs > ⚙ > Add modules).

## Build Profiles (Unity 6)
- Create in File > Build Profiles > Add Build Profile (one per platform or variant, e.g. `macOS`, `macOS-Dev`, `Windows`, `Web`).
  Save them under `Assets/Settings/BuildProfiles/` (profiles under `Packages/` fail from the command line).
- A profile can override the scene list (`overrideGlobalScenes`), scripting defines and some Player Settings; everything
  else falls back to the global settings. Defines from `-activeBuildProfile` compile before `-executeMethod` runs.
- No public API creates a profile in 6000.3; do it in the editor (or ask the user). ⚠ version-sensitive: the internal
  `BuildProfile.CreateInstance(BuildTarget, StandaloneBuildSubtarget)` + `AssetDatabase.CreateAsset` worked by reflection
  on 6000.3.21f1 (✓ local) but may change in any release.
- Build with a profile: `unity.sh build Assets/Settings/BuildProfiles/macOS.asset --out builds/<v>/macos` (✓ local:
  `BuildPlayerWithProfileOptions`, Succeeded) or MCP `manage_build(action="build", profile="Assets/…/macOS.asset", output_path=…)`.
- List / activate in the editor: `manage_build(action="profiles")`, `manage_build(action="profiles", profile=…, activate="true")`.

## Per platform
| Platform | unity.sh target | Output | Notes |
|---|---|---|---|
| macOS (primary) | `macos` (`-buildTarget osxuniversal`) | `<v>/macos/<Product>.app` | ✓ local: universal x86_64+arm64, Mono, 112 MB empty-scene release build in 86 s cold. Unity ad-hoc signs every build (`codesign -dv` shows `Signature=adhoc`). |
| Windows | `windows` (`win64`) | `<v>/windows/<Product>.exe` + `_Data`, `UnityPlayer.dll`, `MonoBleedingEdge`, `D3D12`, `UnityCrashHandler64.exe` | ✓ local build (Mono, 94 MB). IL2CPP for Windows cannot be built from macOS [UNVERIFIED]; keep Mono. Ship the whole folder; smoke test on a Windows machine (`smoke_test.sh` logic: `Game.exe -smoketest -smokeOut r.txt -logFile p.log`). |
| Web | `webgl` | folder `<v>/webgl/` (`index.html`, `Build/`, `TemplateData/`) | ✓ local build (IL2CPP→wasm, 15 MB, 272 s cold; slowest target). Browser smoke run [UNVERIFIED]. Compression gzip by default (release builds only); the server must send `Content-Encoding` and `Content-Type: application/wasm`. For a quick local check set Compression = Disabled or enable Decompression Fallback (bigger loader). Smoke: open `index.html?smoketest` and look for `[SMOKE] ok` in the browser console. No incremental GC on Web. |
| iOS | `ios` | Xcode project folder | Needs Xcode + an Apple team for signing; `PlayerSettings.iOS.buildNumber` → `CFBundleVersion` [UNVERIFIED in a built project]. |
| Android | `android` | `.apk` (or `.aab` when "Build App Bundle" is on) | `bundleVersionCode` must increase on every store upload; keystore settings in Player Settings > Publishing. [UNVERIFIED] build here. |

## macOS packaging (scripts/package_macos.sh)
- `package_macos.sh builds/<v>/macos/<Product>.app [--dmg]`: `xattr -cr`, `chmod -R a+xr`, `codesign --force --deep --sign -`
  (ad-hoc), `codesign --verify --deep --strict`, then `ditto -c -k --sequesterRsrc --keepParent` →
  `<Product>-<CFBundleShortVersionString>-macos.zip` (+ `hdiutil create -format UDZO` .dmg), prints SHA-256. ✓ local
  (zip 45 MB; the re-signed app still passed the smoke test).
- Ad-hoc signed apps run on the build Mac. On other Macs Gatekeeper blocks downloaded apps: testers right-click > Open,
  or run `xattr -dr com.apple.quarantine <Product>.app` [UNVERIFIED on another Mac].
- Public distribution needs a Developer ID certificate, hardened runtime and notarization:
  `codesign --deep --force --verify --verbose --timestamp --options runtime --entitlements Game.entitlements --sign "Developer ID Application: NAME (TEAM)" Game.app`,
  entitlements at least `com.apple.security.cs.disable-library-validation` and
  `com.apple.security.cs.disable-executable-page-protection`; then `xcrun notarytool submit … --wait` and
  `xcrun stapler staple Game.app` (✓ docs for the codesign part; notarytool steps [UNVERIFIED] here). Ask the user for
  the identity; never guess it.
- Never ship `<Product>_BurstDebugInformation_DoNotShip/` (written next to every player); the zip scripts leave it out
  because they package only the `.app`. For Windows zip the folder without it:
  `cd builds/<v>/windows && zip -qry ../<Product>-<v>-windows.zip . -x '*_BurstDebugInformation_DoNotShip*' 'build-report.json' 'smoke-*'`.

## Player will not start
- Read the player log: macOS `~/Library/Logs/<Company>/<Product>/Player.log`, or the `-logFile` you passed
  (smoke_test.sh writes `smoke-player.log` next to the app).
- `xattr -l <Product>.app` shows `com.apple.quarantine` → `xattr -dr com.apple.quarantine <Product>.app`.
- `codesign --verify --deep --strict <Product>.app` fails after you edited files inside the bundle → re-run package_macos.sh.
- Crash on start in a Development build only: check `-dev` options; compare with a release build.
