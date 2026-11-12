---
name: asset-pipeline
description: Sets up and audits the Unity 6 (6000.3) asset pipeline for 2D pixel-art games - folder-filtered Presets, an AssetPostprocessor enforcing Point/uncompressed/fixed-PPU sprites and SFX/music audio settings, Sprite Atlas v2 per folder, labelled placeholder sprites, optional Addressables 2.x content builds, and a .meta import-settings audit. Use when importing art or audio, sprites look blurry or compressed, setting up atlases, generating placeholder art, deciding on Addressables, or auditing import settings.
---

# asset-pipeline

Make import settings a rule instead of a habit: folders decide settings, an editor script enforces them, a script proves them.

Pinned: Unity 6000.3 LTS (tested 6000.3.21f1, macOS), URP 17.3 2D, Addressables 2.x (bench 2.9.1; 6000.3 "released" 2.10.x), MCP for Unity 10.3.
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. mcp__UnityMCP__manage_texture). For tool parameters see unity-mcp-orchestrator. `<skill>` = this skill's folder, `<skills>` = the folder holding all skills.

## When to use / not to use
- Use for: first-time pipeline setup, adding art/audio, blurry or smeared pixel art, inconsistent sprite sizes (PPU), audio memory/latency, atlas setup or draw-call batching of sprites, placeholder art for a prototype, the Addressables decision, pre-commit import audits.
- Not for: moving/renaming/duplicating assets or editing scenes/prefabs (scene-prefab-safety), runtime code structure (architecture-patterns), build profiles and shipping (build-ship), profiling memory/draw calls (perf-pass).

## Folder convention (all rules key off it)
```
Assets/Art/Sprites/<Group>/**      pixel sprites -> Sprite, Point, uncompressed, no mipmaps, Clamp, PPU 16 (one value per game)
Assets/Art/Sprites/Placeholders/<Category>/PH_<Category>_<name>.png   generated placeholders
Assets/Art/Atlases/<Group>.spriteatlasv2   one Sprite Atlas v2 per Sprites/<Group> folder
Assets/Audio/SFX/**                Decompress On Load + ADPCM, preload, mono on first import
Assets/Audio/Music/**              Streaming + Vorbis q0.7, no preload, load in background
Assets/Settings/Presets/*.preset   Texture_PixelSprite, Audio_SFX, Audio_Music
any .../_NoRules/...               opt-out (ImportRules and asset_audit.py skip it)
```
Change PPU or folders in one place: `ImportRuleConfig` in `templates/Editor/ImportRules.cs`; then pass the same `--ppu` (or a `--rules` file) to `asset_audit.py`.

## Inputs
- Project root, the game's tile size in pixels (PPU, default 16), art/audio already in the project and where it lives.
- Editor open (MCP route) or closed (batchmode / headless-ops route).

## Procedure
1. **Precheck.** `mcpforunity://instances` → `set_active_instance` → `mcpforunity://editor/state` (`ready_for_tools`, not `is_compiling`). `read_console(types=["error"])` empty. Baseline: `python3 <skill>/scripts/asset_audit.py "$P"` and `git -C "$P" status --porcelain > /tmp/ap_before.txt`.
2. **Install templates** (new files; Unity creates the `.meta`s). `templates/Editor/` = ImportRules, PresetSetup, AtlasSetup, PlaceholderArt, BatchExit + `Harness.Assets.Editor.asmdef`; `templates/EditorAddressables/` references it:
   ```bash
   mkdir -p "$P/Assets/Harness/AssetPipeline"; cp -R <skill>/templates/Editor "$P/Assets/Harness/AssetPipeline/"
   # optional, only if com.unity.addressables >= 2.0 is installed (compiles to nothing otherwise):
   cp -R <skill>/templates/EditorAddressables "$P/Assets/Harness/AssetPipeline/"
   ```
   Set `ImportRuleConfig.PixelsPerUnit` before the first import if the game is not 16 PPU. Compile: `refresh_unity(compile="request", wait_for_ready=true)` → `read_console(types=["error"])` = 0.
3. **Presets + Preset Manager defaults.** `execute_menu_item(menu_path="Tools/Harness/Assets/Create Import Presets + Defaults")` (batchmode: `-executeMethod Harness.Assets.PresetSetup.CreateAllBatch`, log `PresetSetup RESULT: OK presets=3`). Creates the three presets and registers them with filters `glob:"Assets/Art/Sprites/**"`, `glob:"Assets/Audio/SFX/**"`, `glob:"Assets/Audio/Music/**"` (other existing defaults are kept). Presets apply only on FIRST import. Details: [references/presets-and-import-rules.md](references/presets-and-import-rules.md).
4. **Enforce existing assets.** `execute_menu_item(menu_path="Tools/Harness/Assets/Reimport Rule Folders")` (batchmode: `Harness.Assets.ImportRules.ReimportRuleFoldersBatch`). `ImportRules` re-applies the folder invariants on every import and warns (`[ImportRules] ... override`) about per-platform overrides it does not touch.
5. **Atlases.** `execute_menu_item(menu_path="Tools/Harness/Assets/Create Or Update Folder Atlases")`, then `.../Pack All Atlases` (batchmode: `Harness.Assets.AtlasSetup.SetupAndPackBatch`, log `AtlasSetup RESULT: OK atlases=N sprites=M empty=0 mode=SpriteAtlasV2`). ⚠ version-sensitive: this switches Editor Settings > Sprite Atlas Mode to "Sprite Atlas V2 - Enabled" (6000.3 default is Disabled); the V1 → V2 upgrade of existing `.spriteatlas` files cannot be undone, so ask before running it on a project that has V1 atlases. Read [references/sprite-atlas.md](references/sprite-atlas.md) when choosing atlas groups.
6. **Placeholder art (when real art is missing).**
   - Editor generator: `execute_menu_item(menu_path="Tools/Harness/Assets/Generate Placeholder Sprites")` or `execute_code` with `Harness.Assets.PlaceholderArt.Generate(new[]{ new Harness.Assets.PlaceholderArt.Spec("Enemies","bat",16,16,Harness.Assets.PlaceholderArt.Shape.Diamond, new UnityEngine.Color(0.6f,0.2f,0.8f),"B") }, false)`. Batchmode: `Harness.Assets.PlaceholderArt.GenerateDefaultBatch` (12 roguelike defaults).
   - MCP only: `manage_texture(action="create_sprite", path="Assets/Art/Sprites/Placeholders/Enemies/PH_Enemies_bat.png", width=16, height=16, fill_color="#9933CC", as_sprite={"pixels_per_unit":16}, import_settings={"filter_mode":"point","compression":"none","generate_mipmaps":false,"wrap_mode":"clamp"})`. [UNVERIFIED] that `create_sprite` honours `import_settings` in one call; if the audit disagrees, follow with `manage_texture(action="set_import_settings", path=..., import_settings=...)`. Under `Assets/Art/Sprites/` ImportRules applies the settings anyway. Plain colour only (no label).
   - Replace later by overwriting the PNG bytes at the same path (keeps GUID and every reference), then drop the `PH_` prefix with `manage_asset(action="move", path=..., destination=<same folder, new name>)` or `AssetDatabase.RenameAsset`. Read [references/placeholder-art.md](references/placeholder-art.md).
7. **Addressables decision.** Default for a 2D roguelike: direct serialized references (DefinitionDatabase, prefabs) and no `Resources/`. Use Addressables only for the cases in [references/addressables.md](references/addressables.md) (DLC/remote content, large optional content, memory pressure on mobile/Web). If used: groups via `Harness.Assets.AddressablesSetup.AddFolder(folder, group, label)`, content build via `-executeMethod Harness.Assets.AddressablesSetup.BuildContentBatch` (log `Addressables RESULT: OK ...`) before every player build.
8. **No editor available** (CI, editor closed): run steps 3–6 through headless-ops: `<skills>/headless-ops/scripts/unity.sh exec Harness.Assets.<Class>.<Method>Batch --no-quit` (raw: `Unity -batchmode -nographics -projectPath "$P" -executeMethod <method> -logFile <log>` with a timeout, no `-quit`). The *Batch methods end through `templates/Editor/BatchExit.cs`: exit 0/1/2 deferred one editor tick (⚠ version-sensitive: a synchronous `EditorApplication.Exit` inside `-executeMethod` crashed 6000.3.21f1 once, exit 134); with `-quit` they still work but every failure becomes exit 1; from a menu or `execute_code` they never quit the editor. Never write `.meta` files by hand to "import" assets; let Unity import them.
9. **Verify** (below), then compare `git status --porcelain` with `/tmp/ap_before.txt`: expect new presets/atlases/placeholders and their `.meta`s, `ProjectSettings/PresetManager.asset`, `ProjectSettings/EditorSettings.asset` (atlas mode), reimported `.meta` changes in rule folders. Nothing else.

## Rules
- Pixel art: Point filter, no compression (default platform and every overridden platform), no mipmaps, one PPU for the whole game, Clamp wrap. Use the 2D Pixel Perfect Camera (URP 2D Renderer) for crisp scaling; do not "fix" blur by changing PPU per sprite.
- ⚠ version-sensitive: importer defaults differ between Unity versions and between project templates (on the 6000.3 bench a PNG outside rule folders imported as Default type, Bilinear, compressed, mipmaps on, PPU 100). Never rely on defaults; Presets + ImportRules make settings explicit.
- Presets = defaults on first import (artists may change them later); ImportRules = invariants on every import. Keep both, or only ImportRules if nobody tweaks import settings by hand. Keep `asset_audit.py` rules in sync with `ImportRuleConfig`.
- Audio: SFX Decompress On Load + ADPCM (low CPU, ~3.5× smaller than PCM); very short critical SFX may use PCM in a `_NoRules` folder. Music Streaming + Vorbis (one stream per playing clip, ~200 KB overhead each). Compressed In Memory falls back to Decompress On Load on Chromium Web.
- Atlases: one per co-drawn group (player+projectiles, enemies of a biome, UI). Folder entries, not single sprites, so new sprites join automatically. Padding ≥ 2 (template uses 4), no rotation, no tight packing for pixel art.
- Change import settings only through importers/presets/ImportRules or `manage_texture(action="set_import_settings")`; never hand-edit `.meta` files (scene-prefab-safety owns `.meta` rules). Never move assets with shell `mv`.
- Generated files are normal assets: commit them with their `.meta`; never commit `Library/`, `ServerData/` or Addressables build output (vcs-hygiene).

## Failure handling / stop conditions
- `asset_audit.py` violations after step 4: the asset is outside the rule folders' path prefix, under `_NoRules`, has a per-platform override (ImportRules only warns: remove it in the importer or `TextureImporter.ClearPlatformTextureSettings`), or ImportRules is not compiled (check `read_console`). Do not edit the `.meta` to make the audit pass.
- `AtlasSetup RESULT: FAIL ... empty=N`: an atlas folder has no sprites (non-Sprite textures or wrong folder). Fix imports, re-run.
- `Addressables RESULT: FAIL`: read the error; missing settings → create them once (`AddressableAssetSettingsDefaultObject.GetSettings(true)`, done by `AddFolder`); then stop and report rather than retrying blindly.
- Preset Manager filter not applied to new files: confirm `ProjectSettings/PresetManager.asset` has the `glob:"..."` filters; `asset_audit.py` + ImportRules still guarantee the result.
- Project open in another editor and you are on the batchmode route: stop; use MCP or ask the user to close it.

## References
- [references/presets-and-import-rules.md](references/presets-and-import-rules.md): read when changing rules, PPU, folders, or adding a new asset type.
- [references/sprite-atlas.md](references/sprite-atlas.md): read when grouping atlases, packing in CI, or debugging batching.
- [references/addressables.md](references/addressables.md): read before adopting Addressables or building content in batchmode.
- [references/placeholder-art.md](references/placeholder-art.md): read when generating or replacing placeholder art.

## Verify
1. **Import settings:** `python3 <skill>/scripts/asset_audit.py "$P" [--ppu N]` exits 0 and prints `RESULT: OK checked=<n> violations=0`, with `checked` > 0 once art exists and `sprite_ppu_values` showing a single PPU. Use `--strict` before a release (also fails on never-imported files and audio overrides).
2. **Compiles:** `read_console(types=["error"])` returns 0 entries (batchmode: exit 0, no `error CS` in the log).
3. **Atlases packed:** `unity.sh exec Harness.Assets.AtlasSetup.SetupAndPackBatch --no-quit` exits 0 and logs `AtlasSetup RESULT: OK atlases=N sprites=M empty=0 mode=SpriteAtlasV2` (N ≥ 1, M = number of sprites in atlas folders). With the editor open: `execute_code` → `var r = Harness.Assets.AtlasSetup.Inspect(); return r.atlases + " " + r.sprites + " " + r.empty.Count;` returns `N M 0` after Pack All Atlases.
4. **Placeholders:** each generated sprite reports `Sprite Point Uncompressed mipmaps=False PPU=16` (`execute_code` reading `TextureImporter` for the paths, or `asset_audit.py` covering `Assets/Art/Sprites/Placeholders`).
5. **Addressables (only if used):** `BuildContentBatch` exits 0 and logs `Addressables RESULT: OK`. Expected side diffs: `Assets/AddressableAssetsData/**`, `ProjectSettings/EditorBuildSettings.asset` config objects, URP asset prefilter fields.
6. **Scope:** `git -C "$P" status --porcelain` minus `/tmp/ap_before.txt` lists only the files named in step 9.
