# Presets, Preset Manager defaults, ImportRules, asset_audit.py

## Three layers
| Layer | File | When it acts | Can artists override? |
|---|---|---|---|
| Preset Manager default (folder filter) | `templates/Editor/PresetSetup.cs` → `Assets/Settings/Presets/*.preset` + `ProjectSettings/PresetManager.asset` | first import of a new file only | yes |
| AssetPostprocessor | `templates/Editor/ImportRules.cs` (`Harness.Assets.ImportRules`, order 1000) | every import/reimport in rule folders | no (re-applied), except `spriteImportMode` after first import and `forceToMono` for SFX |
| Audit | `scripts/asset_audit.py` | on demand / CI, editor closed or open | n/a, reports only |

## Settings enforced
Textures under `Assets/Art/Sprites/` (`ImportRuleConfig.SpritesRoot`): `textureType=Sprite`, `spriteImportMode=Single` on first import (sheets may switch to Multiple), `filterMode=Point`, `textureCompression=Uncompressed`, `mipmapEnabled=false`, `spritePixelsPerUnit=ImportRuleConfig.PixelsPerUnit (16)`, `alphaIsTransparency=true`, `wrapMode=Clamp`, `npotScale=None`. Platform overrides for Standalone/WebGL/iPhone/Android that compress are logged as warnings.
SFX under `Assets/Audio/SFX/`: `loadType=DecompressOnLoad`, `compressionFormat=ADPCM`, `preloadAudioData=true`, `loadInBackground=false`, `forceToMono=true` on first import.
Music under `Assets/Audio/Music/`: `loadType=Streaming`, `compressionFormat=Vorbis`, `quality=0.7`, `preloadAudioData=false`, `loadInBackground=true`.
Opt-out: any path containing `/_NoRules/`; global kill switch: environment variable `HARNESS_IMPORT_RULES_OFF=1` for the editor process.

## Preset Manager API (6000.3)
- Default presets are set with the static methods on `Preset`: `Preset.GetDefaultPresetsForType(PresetType)` and `Preset.SetDefaultPresetsForType(PresetType, DefaultPreset[])`. ⚠ version-sensitive: `PresetManager` itself is internal in 6000.3 (`error CS0122 'PresetManager' is inaccessible` on 6000.3.21f1); older docs/snippets that call `PresetManager.SetDefaultPresetsForType` do not compile.
- `new DefaultPreset(filter, preset)`; filter syntax `glob:"Assets/Art/Sprites/**"` (what the Preset Manager UI writes). Verified on the bench: with ImportRules disabled, a new PNG under the filtered folder imported as Sprite/Point/PPU 16/uncompressed and a new WAV under `Audio/SFX` as DecompressOnLoad/ADPCM/mono, while a PNG outside the folders got Unity defaults.
- `PresetSetup.Save` updates an existing preset in place (`UpdateProperties`, GUID kept); `SetDefault` replaces only the entry with the same filter, keeping other defaults.
- The presets are created from a temporary PNG/WAV in `Assets/__HarnessPresetTemp` that is deleted afterwards.
- Presets only apply on first import. To push new preset values onto existing files use `preset.ApplyTo(importer)` + `SaveAndReimport()`, or rely on ImportRules + Reimport Rule Folders.

## Adding a rule (example: UI sprites at 100 PPU, bilinear)
1. `ImportRuleConfig`: add `public const string UiRoot = "Assets/Art/UI/";` and a branch in `OnPreprocessTexture` (check the UI root before the Sprites root if one contains the other).
2. Optional preset: create one in `PresetSetup.CreateAll` and `SetDefault(uiPreset, "Assets/Art/UI")`.
3. `asset_audit.py`: `python3 asset_audit.py --print-default-rules > Tools/asset_rules.json`, add
   ```json
   {"name": "ui", "folder": "Assets/Art/UI", "exts": [".png"], "importer": "TextureImporter",
    "expect": {"textureType": "8", "textureSettings.filterMode": "1", "spritePixelsToUnits": "100"}}
   ```
   and run with `--rules Tools/asset_rules.json`. Keys are paths inside the importer block of the `.meta` (`mipmaps.enableMipMap`, `textureSettings.filterMode`, `defaultSettings.loadType`); `platform[<BuildTarget>].<key>` reads a platform entry (`platform[DefaultTexturePlatform].textureCompression`). `overridden_platforms_expect` checks every platform entry with `overridden: 1`. Values are compared as the strings Unity writes (enums as numbers).
4. Reimport the folder, run the audit.

## .meta values (for reading audit output)
`textureType` 0 Default, 8 Sprite · `filterMode` 0 Point, 1 Bilinear, 2 Trilinear · `textureCompression` 0 Uncompressed, 1 Compressed, 2 HQ, 3 LQ · `wrapU/V` 0 Repeat, 1 Clamp · `loadType` 0 DecompressOnLoad, 1 CompressedInMemory, 2 Streaming · `compressionFormat` 0 PCM, 1 Vorbis, 2 ADPCM, 3 MP3 · sprite PPU is `spritePixelsToUnits`.

## asset_audit.py
`python3 asset_audit.py [PROJECT] [--ppu N] [--rules FILE] [--print-default-rules] [--strict] [--json] [--max N]`. Exit 0 no violations, 1 violations (or warnings with `--strict`), 2 setup error. Last line `RESULT: OK|FAIL checked=.. violations=.. warnings=..`. Warnings: file without `.meta` (never imported), importer mismatch (e.g. Aseprite/PSD scripted importers are skipped), audio per-platform overrides. Missing rule folders are listed as notes and never fail (not even with `--strict`). `--json` prints only the JSON document (no RESULT line; use the exit code). Tested on the bench: clean project → exit 0; Bilinear sprite, compressed Standalone override and DecompressOnLoad music → 3 violations, exit 1; ImportRules reimport fixed the first and last, the override stayed (by design, only warned).
