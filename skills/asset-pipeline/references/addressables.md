# Addressables 2.x for a 2D roguelike: when, how, batchmode build

File: `templates/EditorAddressables/AddressablesSetup.cs` + `Harness.Assets.Addressables.Editor.asmdef` (compiles only when `com.unity.addressables` ≥ 2.0.0 is installed: `versionDefines` → `HARNESS_ADDRESSABLES` + `defineConstraints`).

## Decide
| Option | Use when | Cost |
|---|---|---|
| Direct serialized references (prefabs, `DefinitionDatabase`, SO lists) | default; everything ships in the build and fits in memory (typical 2D pixel-art roguelike: tens of MB) | none; everything referenced from a loaded scene is in memory |
| `Resources/` | almost never: tiny prototypes, or a single bootstrap config | everything in Resources ships and is indexed at startup; no memory control; Unity recommends against it |
| Addressables | DLC/remote content updates, very large optional content (many biomes of hi-res art, audio packs), strict memory budgets (mobile/Web) where you must unload whole biomes, modding-like catalogs | package, groups/labels to maintain, async loading everywhere, a content build before every player build, release discipline (`Addressables.Release`) |
Start with direct references. Move to Addressables when memory profiling (perf-pass) shows content you cannot unload, or when you need remote updates. Versions: 6000.3 lists 2.10.x as "released for" the editor (bench uses 2.9.1); up to 4.x is also available. ⚠ version-sensitive: APIs below were compiled and run on 2.9.1 only.

## Setup through the template
```csharp
// editor (execute_code or a menu/batch method)
Harness.Assets.AddressablesSetup.AddFolder("Assets/Art/Sprites/Enemies_Crypt", "Biome_Crypt", "crypt");
```
- `EnsureGroup(name)` creates a packed group (BundledAssetGroupSchema + ContentUpdateGroupSchema) if missing. `AddFolder` makes every asset in the folder an entry, address = file name without extension, optional label; creates `Assets/AddressableAssetsData/` settings on first use (`GetSettings(true)`).
- Runtime loading (in your game code, `Game.Runtime` asmdef referencing `Unity.Addressables` + `Unity.ResourceManager`):
  ```csharp
  var handle = Addressables.LoadAssetsAsync<Sprite>("crypt", null); await handle.Task; ... Addressables.Release(handle);
  ```
  Prefer `AssetReferenceT<T>` fields over string addresses for things referenced from data.

## Content build (batchmode)
`<skills>/headless-ops/scripts/unity.sh exec Harness.Assets.AddressablesSetup.BuildContentBatch --no-quit` (raw: `Unity -batchmode -nographics -projectPath "$P" -executeMethod Harness.Assets.AddressablesSetup.BuildContentBatch -logFile <log>`, no `-quit`, see BatchExit.cs) → calls `AddressableAssetSettings.BuildPlayerContent(out AddressablesPlayerBuildResult result)`; logs `Addressables RESULT: OK duration=…s output=Library/com.unity.addressables/aa/<Platform>/settings.json` (exit 0) or `RESULT: FAIL <error>` (exit 1/2).
- Bench (6000.3.21f1, Addressables 2.9.1, StandaloneOSX): 3 sprites in one group → OK in 8.3 s; output `Library/com.unity.addressables/aa/OSX/` (`catalog.bin`, `settings.json`, `StandaloneOSX/` bundles).
- ⚠ version-sensitive: run the content build for the same build target as the player (switch target first; build-ship owns that). The "Build Addressables on Player Build" setting (Addressables settings, Build section) can do it automatically; [UNVERIFIED] its exact behaviour with 6000.3 Build Profiles; build-ship should call `BuildContentBatch` explicitly before the player build to be safe.
- Expected side effects in git: `Assets/AddressableAssetsData/**` (commit), `ProjectSettings/EditorBuildSettings.asset` (Addressables config objects), and on URP projects the URP asset's shader prefilter fields (`m_Prefilter*`) rewritten by the build preprocessing. Build output under `Library/` and `ServerData/` is never committed.
- Remote catalogs/content update builds (`ContentUpdateScript`, `addressables_content_state.bin`) are out of scope; keep `addressables_content_state.bin` under version control if you ship remote updates.

## Rules
- Every `LoadAssetAsync`/`InstantiateAsync` has a matching `Release`/`ReleaseInstance`; leaks keep whole bundles in memory.
- Do not mix: an asset referenced directly from a scene in the build AND marked addressable is duplicated (once in the player data, once in a bundle). Use Analyze rules (Window > Asset Management > Addressables > Analyze) after grouping.
- No `Resources/` folders inside addressable groups.
