# Sprite Atlas v2 for pixel-art games

File: `templates/Editor/AtlasSetup.cs` (`Harness.Assets.AtlasSetup`).

## Mode
Editor Settings > Sprite Atlas Mode (6000.3): Disabled (default) / Sprite Atlas V1 - Enabled For Builds / V1 - Always Enabled / **Sprite Atlas V2 - Enabled** (packs for builds and before entering Play Mode) / V2 - Enabled For Builds. `AtlasSetup.EnsureV2()` sets `EditorSettings.spritePackerMode = SpritePackerMode.SpriteAtlasV2`. ⚠ version-sensitive: switching a project that has V1 `.spriteatlas` assets to V2 migrates them and cannot be undone; ask first. V2 assets are `.spriteatlasv2` (text YAML, merge with UnityYAMLMerge; vcs-hygiene).

## What the template does
- For every direct subfolder `Assets/Art/Sprites/<Group>` → `Assets/Art/Atlases/<Group>.spriteatlasv2` containing the FOLDER as a packable (new sprites join automatically). Existing atlases keep their packables and get their settings re-applied.
- Importer settings (`SpriteAtlasImporter`): padding 4, blockOffset 1, rotation off, tight packing off, alpha dilation off, Point filter, no mipmaps, sRGB, not readable, default platform max 2048 uncompressed, `includeInBuild = true` (`bindAsDefault: 1` in the `.meta`).
- `PackAll()` = `SpriteAtlasUtility.PackAllAtlases(EditorUserBuildSettings.activeBuildTarget, false)`; `Inspect()` returns atlas count, total sprite count and empty atlases.
- Batchmode: `unity.sh exec Harness.Assets.AtlasSetup.SetupAndPackBatch --no-quit` (headless-ops) → `AtlasSetup RESULT: OK atlases=N sprites=M empty=0 mode=SpriteAtlasV2`; exit 0 OK, 1 empty/no atlases, 2 exception. Bench (6000.3.21f1, -nographics): 1 atlas, 12 placeholder sprites, 14 s.

## Grouping
- Group sprites that are drawn together in the same frames: `Player` (player + its projectiles + FX), `Enemies_<Biome>`, `Tiles_<Biome>`, `Pickups`, `UI`. One huge atlas wastes memory when most of it is not on screen; dozens of tiny atlases break batching.
- A sprite must be in exactly one atlas (Unity picks one arbitrarily otherwise; the console warns). Do not add a parent folder and its subfolder to different atlases.
- Tilemaps: tiles in one atlas render in one batch per tilemap chunk; keep a biome's tiles together.
- Keep each atlas ≤ 2048×2048 for broad device support; if `Inspect()` shows a group overflowing into multiple pages, split the folder.

## Pixel-art specifics
- Point filter + padding ≥ 2 avoids bleeding; tight packing and rotation can clip edges or misalign pixels.
- Sprites' own import settings still matter (PPU, Point); the atlas texture uses the atlas importer's filter.
- Variant atlases (`Type: Variant`, scale < 1) are for hi-res art on low-end devices, not for pixel art.

## Late binding (optional)
`includeInBuild = false` + `SpriteAtlasManager.atlasRequested` callback lets you load an atlas yourself (e.g. from Addressables). Not needed for a typical 2D roguelike; leave `includeInBuild = true`.

## Checking batching
Frame Debugger or `manage_profiler` (perf-pass) during Play: sprites from one atlas with the same material should batch (SRP Batcher / dynamic batching for sprites). If not: check material, sorting layers interleaving with other atlases, or sprites outside atlases.
